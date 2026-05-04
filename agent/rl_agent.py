import numpy as np
from typing import Tuple

MIN_LA = 3
MIN_LH = 3
MIN_CONG = 2
MIN_TIME = 2

MINING_ACTIONS = ['adopt', 'wait', 'match', 'override']
DELAY_ACTIONS = ['NO_DELAY', 'SELECTIVE_DELAY', 'GLOBAL_CONGESTION']
ACTIONS = [(m, d) for m in MINING_ACTIONS for d in DELAY_ACTIONS]

class QLearningAttacker:
    def __init__(
        self,
        alpha=0.1,
        gamma=0.9,
        epsilon=0.4,
        epsilon_decay=0.995,
        min_epsilon=0.05,
        delay_lambda=0.001,
        orphan_mu=1.0,
    ):
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.min_epsilon = min_epsilon
        self.delay_lambda = delay_lambda
        self.orphan_mu = orphan_mu
        self.q = np.zeros((self.state_count(), len(ACTIONS)), dtype=float)
        self.history = []

    @staticmethod
    def state_count() -> int:
        return (MIN_LA + 1) * (MIN_LH + 1) * (MIN_CONG + 1) * (MIN_TIME + 1)

    @staticmethod
    def discretize_state(la: int, lh: int, congestion: float, time_since_last: float) -> int:
        la_idx = min(la, MIN_LA)
        lh_idx = min(lh, MIN_LH)
        cong_idx = min(int(congestion * (MIN_CONG + 0.9)), MIN_CONG)
        time_idx = min(int(time_since_last / 2.0), MIN_TIME)
        return (la_idx * (MIN_LH + 1) * (MIN_CONG + 1) * (MIN_TIME + 1)
                + lh_idx * (MIN_CONG + 1) * (MIN_TIME + 1)
                + cong_idx * (MIN_TIME + 1)
                + time_idx)

    def choose_action(self, state_idx: int) -> int:
        if np.random.rand() < self.epsilon:
            return np.random.randint(len(ACTIONS))
        return int(np.argmax(self.q[state_idx]))

    def decay_epsilon(self) -> None:
        self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)

    def update(self, state_idx: int, action_idx: int, reward: float, next_state_idx: int) -> None:
        best_next = np.max(self.q[next_state_idx])
        self.q[state_idx, action_idx] += self.alpha * (reward + self.gamma * best_next - self.q[state_idx, action_idx])
        self.history.append(reward)

    @staticmethod
    def action_tuple(action_idx: int) -> Tuple[str, str]:
        return ACTIONS[action_idx]

    def action_index(self, mining_action: str, delay_action: str) -> int:
        return ACTIONS.index((mining_action, delay_action))

    def reset_history(self) -> None:
        self.history = []

    def summary(self) -> dict:
        return {
            'epsilon': self.epsilon,
            'avg_reward': float(np.mean(self.history)) if self.history else 0.0,
            'std_reward': float(np.std(self.history)) if self.history else 0.0,
        }
