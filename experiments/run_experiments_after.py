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

RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results_after')
PLOTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'plots_after')

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
        asymmetric_delay=True,   # After: asymmetric delay
        partition_prob=0.2,      # After: partitions
        propagation_variance=0.5, # After: variance
        n_nodes=100,             # After: larger network
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

def run_mode(alpha, delay_intensity, target_fraction, mode, runs=5, episode_blocks=600, fixed_strategy=None, lambda_penalty=0.001, n_nodes=100, asymmetric_delay=True, attacker_delay_multiplier=0.1, partition_prob=0.2, propagation_variance=0.5):
    results = []
    agent = None
    training_history = []
    if mode == 'C':
        agent, training_history = train_rl_agent(alpha, delay_intensity, target_fraction)
        agent.epsilon = 0.05
    else:
        agent = None
        training_history = []

    if agent is not None:
        policy_file = os.path.join(
            RESULTS_DIR,
            f'policy_{mode}_alpha{alpha}_delay{delay_intensity}_target{target_fraction}.npy',
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
        if mode == 'C':
            result = simulator.run_episode(num_blocks=episode_blocks, rl_agent=agent, mode='C')
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
    alphas = [0.05, 0.2, 0.5]
    delay_intensities = [0, 1000]
    target_fractions = [0.0]
    mode_labels = ['A', 'C']
    summary_rows = []
    raw_rows = []

    for alpha in alphas:
        for delay_intensity in delay_intensities:
            for target_fraction in target_fractions:
                for mode in mode_labels:
                    print(f'Running mode={mode} alpha={alpha} delay={delay_intensity} target={target_fraction}')
                    df, summary = run_mode(
                        alpha,
                        delay_intensity,
                        target_fraction,
                        mode,
                        runs=5,
                        episode_blocks=600,
                        n_nodes=100,
                        asymmetric_delay=True,
                        partition_prob=0.2,
                        propagation_variance=0.5,
                    )
                    summary_rows.append(summary.assign(run_mode=mode))
                    df['mode'] = mode
                    df['alpha'] = alpha
                    df['delay_intensity'] = delay_intensity
                    df['target_fraction'] = target_fraction
                    raw_rows.append(df)
    raw_results = pd.concat(raw_rows, ignore_index=True)
    summary_results = pd.concat(summary_rows, ignore_index=True)
    raw_results.to_csv(os.path.join(RESULTS_DIR, 'sdm_raw_results_after.csv'), index=False)
    summary_results.to_csv(os.path.join(RESULTS_DIR, 'sdm_summary_results_after.csv'), index=False)
    return raw_results, summary_results

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
        ax.set_title(f'REV vs alpha (After Changes - {mode})')
        ax.set_xlabel('alpha')
        ax.set_ylabel('REV')
        ax.legend()
        ax.grid(True)
        fig.savefig(os.path.join(PLOTS_DIR, f'rev_vs_alpha_after_{mode}.png'))
        plt.close(fig)

if __name__ == '__main__':
    raw_results, summary_results = aggregate_experiments()
    plot_results(raw_results, summary_results)
    print('After results saved to', RESULTS_DIR)
    print('Plots saved to', PLOTS_DIR)