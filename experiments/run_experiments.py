import os
import sys
import time
from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from agent.rl_agent import QLearningAttacker
from simulator.core import BlockchainSimulator

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')
PLOTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'plots')

os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(PLOTS_DIR, exist_ok=True)


def train_rl_agent(
    alpha,
    delay_intensity,
    target_fraction,
    train_episodes=8,
    episode_blocks=600,
    fixed_strategy=None,
    lambda_penalty=0.001,
    mu_penalty=1.0,
):
    agent = QLearningAttacker(alpha=0.05, epsilon=0.5, epsilon_decay=0.98, min_epsilon=0.05)
    simulator = BlockchainSimulator(
        alpha=alpha,
        delay_intensity=delay_intensity,
        target_fraction=target_fraction,
        attacker_delay_mode='NO_DELAY',
        honest_delay_enabled=True,
    )
    training_history = []
    for episode in range(train_episodes):
        result = simulator.run_episode(
            num_blocks=episode_blocks,
            rl_agent=agent,
            mode='C',
            fixed_strategy=fixed_strategy,
            lambda_penalty=lambda_penalty,
            mu_penalty=mu_penalty,
        )
        training_history.append(result['mean_reward'])
    return agent, training_history


def run_mode(alpha, delay_intensity, target_fraction, mode, runs=20, episode_blocks=1000, fixed_strategy=None, lambda_penalty=0.001, n_nodes=30, asymmetric_delay=False, attacker_delay_multiplier=0.1, partition_prob=0.0, propagation_variance=0.0):
    results = []
    agent = None
    training_history = []
    if mode == 'C':
        agent, training_history = train_rl_agent(alpha, delay_intensity, target_fraction)
        agent.epsilon = 0.05
    elif mode == 'no_targeting':
        agent, training_history = train_rl_agent(
            alpha,
            delay_intensity,
            target_fraction,
            fixed_strategy='global_only',
        )
        agent.epsilon = 0.05
    elif mode == 'no_cost':
        agent, training_history = train_rl_agent(
            alpha,
            delay_intensity,
            target_fraction,
            lambda_penalty=0.0,
            mu_penalty=0.0,
        )
        agent.epsilon = 0.05
    else:
        agent = None
        training_history = []

    if agent is not None:
        policy_file = os.path.join(
            RESULTS_DIR,
            f'policy_{mode}_alpha{alpha}_delay{delay_intensity}_target{target_fraction}_nodes{n_nodes}.npy',
        )
        np.save(policy_file, agent.q)

    for run in range(runs):
        simulator = BlockchainSimulator(
            n_nodes=n_nodes,
            alpha=alpha,
            delay_intensity=delay_intensity,
            target_fraction=target_fraction,
            attacker_delay_mode='NO_DELAY',
            honest_delay_enabled=(mode != 'A'),
            asymmetric_delay=asymmetric_delay,
            attacker_delay_multiplier=attacker_delay_multiplier,
            partition_prob=partition_prob,
            propagation_variance=propagation_variance,
        )
        if mode == 'A':
            result = simulator.run_episode(num_blocks=episode_blocks, rl_agent=None, mode='A')
        elif mode == 'B':
            result = simulator.run_episode(num_blocks=episode_blocks, rl_agent=None, mode='B', fixed_delay_action='passive')
        elif mode == 'C':
            result = simulator.run_episode(num_blocks=episode_blocks, rl_agent=agent, mode='C')
        elif mode == 'no_targeting':
            result = simulator.run_episode(num_blocks=episode_blocks, rl_agent=agent, mode='C', fixed_strategy='global_only')
        elif mode == 'no_rl':
            result = simulator.run_episode(num_blocks=episode_blocks, rl_agent=None, mode='C', fixed_strategy='fixed')
        elif mode == 'no_cost':
            result = simulator.run_episode(num_blocks=episode_blocks, rl_agent=agent, mode='C', lambda_penalty=0.0, mu_penalty=0.0)
        else:
            result = simulator.run_episode(num_blocks=episode_blocks, rl_agent=None, mode='A')
        results.append(result)
    df = pd.DataFrame(results)
    summary = df.agg(['mean', 'std']).transpose().reset_index()
    summary = summary.rename(columns={'index': 'metric'})
    summary['mode'] = mode
    summary['alpha'] = alpha
    summary['delay_intensity'] = delay_intensity
    summary['target_fraction'] = target_fraction
    summary['n_nodes'] = n_nodes
    summary['asymmetric_delay'] = asymmetric_delay
    summary['partition_prob'] = partition_prob
    summary['propagation_variance'] = propagation_variance
    summary['runs'] = runs
    if training_history:
        summary['training_mean_reward'] = np.mean(training_history)
        summary['training_reward_history'] = [training_history] * len(summary)
    return df, summary


def aggregate_experiments():
    alphas = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5]
    delay_intensities = [0, 500, 1000, 2000]
    target_fractions = [0.0, 0.5]
    mode_labels = ['A', 'B', 'C', 'no_targeting', 'no_rl', 'no_cost']
    summary_rows = []
    raw_rows = []

    for alpha in alphas:
        for delay_intensity in delay_intensities:
            for target_fraction in target_fractions:
                for mode in mode_labels:
                    for n_nodes in [30, 100, 500]:  # Experiment 4: Larger networks
                        for asymmetric_delay, attacker_delay_multiplier in [(False, 0.1), (True, 0.1)]:  # Experiment 2: Asymmetric delay
                            print(f'Running mode={mode} alpha={alpha} delay={delay_intensity} target={target_fraction} nodes={n_nodes} asym={asymmetric_delay}')
                            df, summary = run_mode(
                                alpha,
                                delay_intensity,
                                target_fraction,
                                mode,
                                runs=10,
                                episode_blocks=600,
                                fixed_strategy=mode if mode in ['no_targeting', 'no_rl'] else None,
                                n_nodes=n_nodes,
                                asymmetric_delay=asymmetric_delay,
                                attacker_delay_multiplier=attacker_delay_multiplier,
                            )
                            summary_rows.append(summary.assign(run_mode=mode))
                            df['mode'] = mode
                            df['alpha'] = alpha
                            df['delay_intensity'] = delay_intensity
                            df['target_fraction'] = target_fraction
                            df['n_nodes'] = n_nodes
                            df['asymmetric_delay'] = asymmetric_delay
                            raw_rows.append(df)
    raw_results = pd.concat(raw_rows, ignore_index=True)
    summary_results = pd.concat(summary_rows, ignore_index=True)
    raw_results.to_csv(os.path.join(RESULTS_DIR, 'sdm_raw_results.csv'), index=False)
    summary_results.to_csv(os.path.join(RESULTS_DIR, 'sdm_summary_results.csv'), index=False)
    return raw_results, summary_results


def compute_alpha_threshold(summary_results):
    alpha_thresholds = []
    rev = summary_results[summary_results['metric'] == 'REV']
    for delay_intensity in rev['delay_intensity'].unique():
        for target_fraction in rev['target_fraction'].unique():
            rows = rev[(rev['mode'] == 'C') &
                       (rev['delay_intensity'] == delay_intensity) &
                       (rev['target_fraction'] == target_fraction)]
            for _, row in rows.sort_values('alpha').iterrows():
                alpha = row['alpha']
                if row['mean'] > alpha:
                    alpha_thresholds.append({'delay_intensity': delay_intensity, 'target_fraction': target_fraction, 'alpha_min': alpha})
                    break
    return pd.DataFrame(alpha_thresholds)


def plot_results(raw_results, summary_results):
    sd = summary_results[summary_results['metric'] == 'REV'].copy()
    if 'mean' not in sd.columns:
        return
    for mode in sd['mode'].unique():
        subset = sd[sd['mode'] == mode]
        fig, ax = plt.subplots(figsize=(8, 5))
        for delay in sorted(subset['delay_intensity'].unique()):
            series = subset[subset['delay_intensity'] == delay]
            ax.errorbar(series['alpha'], series['mean'], yerr=series['std'], label=f'delay={delay}ms', marker='o')
        ax.set_title(f'REV vs alpha ({mode})')
        ax.set_xlabel('alpha')
        ax.set_ylabel('REV')
        ax.legend()
        ax.grid(True)
        fig.savefig(os.path.join(PLOTS_DIR, f'rev_vs_alpha_{mode}.png'))
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6))
    csubset = sd[sd['mode'] == 'C']
    pivot = csubset.pivot_table(index='delay_intensity', columns='alpha', values='mean')
    im = ax.imshow(pivot, aspect='auto', origin='lower', cmap='viridis')
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel('alpha')
    ax.set_ylabel('delay_intensity')
    fig.colorbar(im, ax=ax, label='REV')
    fig.savefig(os.path.join(PLOTS_DIR, 'heatmap_alpha_delay_rev.png'))
    plt.close(fig)

    baseline = sd[sd['mode'] == 'B'].set_index(['alpha', 'delay_intensity', 'target_fraction'])
    sdm = sd[sd['mode'] == 'C'].set_index(['alpha', 'delay_intensity', 'target_fraction'])
    efficiency_rows = []
    for idx, row in sdm.iterrows():
        if idx in baseline.index:
            delta_rev = row['mean'] - baseline.loc[idx]['mean']
            delay_cost = idx[1] if idx[1] > 0 else 1.0
            efficiency_rows.append({'alpha': idx[0], 'delay_intensity': idx[1], 'target_fraction': idx[2], 'SE': delta_rev / delay_cost})
    eff_df = pd.DataFrame(efficiency_rows)
    for target in eff_df['target_fraction'].unique():
        subset = eff_df[eff_df['target_fraction'] == target]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(subset['delay_intensity'], subset['SE'], marker='o')
        ax.set_title(f'Sabotage Efficiency vs delay (target={target})')
        ax.set_xlabel('delay_intensity')
        ax.set_ylabel('SE')
        ax.grid(True)
        fig.savefig(os.path.join(PLOTS_DIR, f'se_vs_delay_target_{target}.png'))
        plt.close(fig)


def main():
    start = time.time()
    raw_results, summary_results = aggregate_experiments()
    plot_results(raw_results, summary_results)
    alpha_min = compute_alpha_threshold(summary_results)
    alpha_min.to_csv(os.path.join(RESULTS_DIR, 'alpha_thresholds.csv'), index=False)
    print('Experiment complete.')
    print('Results saved to', RESULTS_DIR)
    print('Plots saved to', PLOTS_DIR)
    print('Total runtime:', time.time() - start)

if __name__ == '__main__':
    main()
