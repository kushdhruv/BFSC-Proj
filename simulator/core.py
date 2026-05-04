import heapq
import itertools
import math
import random
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import networkx as nx

from agent.rl_agent import QLearningAttacker

@dataclass(order=True)
class Event:
    time: float
    order: int
    event_type: str
    node_id: int
    block_id: str
    source_id: Optional[int] = field(compare=False, default=None)

@dataclass
class Block:
    block_id: str
    parent_id: str
    height: int
    miner_id: int
    timestamp: float
    is_attacker: bool

class Node:
    def __init__(self, node_id: int, is_attacker: bool = False):
        self.node_id = node_id
        self.is_attacker = is_attacker
        self.known_blocks: Dict[str, Block] = {}
        self.tip_id: Optional[str] = None
        self.tip_height = -1
        self.tip_arrival = 0.0
        self.private_chain: List[Block] = []

    def receive_block(self, block: Block, arrival_time: float) -> bool:
        if block.block_id in self.known_blocks:
            return False
        self.known_blocks[block.block_id] = block
        if block.height > self.tip_height or (
            block.height == self.tip_height and arrival_time < self.tip_arrival
        ):
            self.tip_id = block.block_id
            self.tip_height = block.height
            self.tip_arrival = arrival_time
            return True
        return False

    def best_tip(self) -> Optional[str]:
        return self.tip_id

class BlockchainSimulator:
    def __init__(
        self,
        n_nodes: int = 30,
        edge_prob: float = 0.1,
        alpha: float = 0.2,
        baseline_delay_ms: float = 150.0,
        delay_sigma: float = 0.8,
        delay_intensity: float = 0.0,
        target_fraction: float = 0.0,
        attacker_delay_mode: str = 'NO_DELAY',
        delay_target_nodes: Optional[Set[int]] = None,
        honest_delay_enabled: bool = True,
        asymmetric_delay: bool = False,
        attacker_delay_multiplier: float = 0.1,
        partition_prob: float = 0.0,
        propagation_variance: float = 0.0,
        rng: Optional[np.random.Generator] = None,
    ):
        self.n_nodes = n_nodes
        self.edge_prob = edge_prob
        self.alpha = alpha
        self.baseline_delay_ms = baseline_delay_ms
        self.delay_sigma = delay_sigma
        self.delay_intensity = delay_intensity
        self.target_fraction = target_fraction
        self.attacker_delay_mode = attacker_delay_mode
        self.honest_delay_enabled = honest_delay_enabled
        self.asymmetric_delay = asymmetric_delay
        self.attacker_delay_multiplier = attacker_delay_multiplier
        self.partition_prob = partition_prob
        self.propagation_variance = propagation_variance
        self.network = nx.erdos_renyi_graph(n_nodes, edge_prob, seed=random.randint(0, 10**6))
        self.nodes = {i: Node(i, is_attacker=(i == 0)) for i in range(n_nodes)}
        self.rng = rng or np.random.default_rng()
        self.delay_target_nodes = delay_target_nodes or self._pick_target_nodes()
        self.reset()

    def _pick_target_nodes(self) -> Set[int]:
        honest_nodes = [i for i in self.nodes if i != 0]
        target_size = int(self.target_fraction * len(honest_nodes))
        return set(self.rng.choice(honest_nodes, size=target_size, replace=False)) if target_size > 0 else set()

    def reset(self) -> None:
        self.event_queue: List[Event] = []
        self.blocks: Dict[str, Block] = {}
        self.public_head_id: Optional[str] = None
        self.history: List[Event] = []
        self.global_time = 0.0
        self.event_counter = itertools.count()
        self.fork_events = 0
        self.delay_action_count = 0
        self.delay_cost_total = 0.0
        self.step_delay_cost = 0.0
        self.orphan_penalties = 0
        self.step_orphan_penalty = 0
        self.attacker_rewards = 0.0
        self.step_attacker_reward = 0.0
        self.attacker_blocks_mined = 0
        self.attacker_blocks_in_main = 0
        self.total_blocks = 0
        self.public_blocks: Set[str] = set()
        self.attacker_private_blocks: List[Block] = []
        self.last_block_time = 0.0
        self.time_since_last_block = 0.0
        self.state_transitions: List[Tuple[int, int, float, int]] = []
        for node in self.nodes.values():
            node.known_blocks.clear()
            node.tip_id = None
            node.tip_height = -1
            node.tip_arrival = 0.0
            node.private_chain = []
        self._seed_genesis()

    def _seed_genesis(self) -> None:
        genesis = Block('genesis', '', 0, -1, 0.0, False)
        self.blocks[genesis.block_id] = genesis
        self.public_head_id = genesis.block_id
        for node in self.nodes.values():
            node.known_blocks[genesis.block_id] = genesis
            node.tip_id = genesis.block_id
            node.tip_height = 0
            node.tip_arrival = 0.0

    def sample_baseline_delay(self, is_attacker: bool = False) -> float:
        if not self.honest_delay_enabled and not is_attacker:
            return 0.0
        sigma = self.delay_sigma
        mu = math.log(max(1.0, self.baseline_delay_ms)) - 0.5 * sigma**2
        delay = float(self.rng.lognormal(mu, sigma))
        if self.asymmetric_delay and is_attacker:
            delay *= self.attacker_delay_multiplier
        return delay

    def schedule_event(self, event: Event) -> None:
        heapq.heappush(self.event_queue, event)

    def schedule_block_delivery(
        self,
        block: Block,
        from_node: int,
        to_node: int,
        current_time: float,
    ) -> None:
        delay = self.sample_baseline_delay(is_attacker=block.is_attacker)
        if block.is_attacker:
            pass  # Attacker's own blocks already handled by asymmetric
        else:
            if self.attacker_delay_mode == 'GLOBAL_CONGESTION':
                delay += self.delay_intensity
            elif self.attacker_delay_mode == 'SELECTIVE_DELAY':
                if to_node in self.delay_target_nodes:
                    delay += self.delay_intensity
        self.delay_cost_total += delay if not block.is_attacker else 0.0
        self.step_delay_cost += delay if not block.is_attacker else 0.0
        event = Event(
            time=current_time + delay,
            order=next(self.event_counter),
            event_type='receive',
            node_id=to_node,
            block_id=block.block_id,
            source_id=from_node,
        )
        self.schedule_event(event)

    def broadcast_block(self, block: Block, origin_node: int) -> None:
        self.public_blocks.add(block.block_id)
        neighbors = list(self.network.neighbors(origin_node))
        # Partial partition: randomly drop some links
        active_neighbors = [n for n in neighbors if self.rng.random() > self.partition_prob]
        for neighbor in active_neighbors:
            # Add propagation variance
            variance_factor = 1.0 + self.rng.normal(0, self.propagation_variance)
            variance_factor = max(0.1, variance_factor)  # Prevent negative delays
            self.schedule_block_delivery(block, origin_node, neighbor, self.global_time + self.sample_baseline_delay() * variance_factor)

    def next_reception_event(self) -> Optional[Event]:
        if self.event_queue:
            return heapq.heappop(self.event_queue)
        return None

    def schedule_mining_event(self, node_id: int, rate: float, current_time: float) -> None:
        interval = self.rng.exponential(1.0 / max(rate, 1e-9))
        event = Event(
            time=current_time + interval,
            order=next(self.event_counter),
            event_type='mine',
            node_id=node_id,
            block_id='',
        )
        self.schedule_event(event)

    def effective_state(self, rl_agent: QLearningAttacker) -> int:
        la = len(self.attacker_private_blocks)
        public_height = self.blocks[self.public_head_id].height if self.public_head_id else 0
        lh = max(0, public_height - (self.blocks[self.attacker_private_blocks[-1].parent_id].height if self.attacker_private_blocks else public_height))
        congestion = min(1.0, len(self.event_queue) / 50.0)
        elapsed = self.global_time - self.last_block_time
        return rl_agent.discretize_state(la, lh, congestion, elapsed)

    def run_episode(
        self,
        num_blocks: int,
        rl_agent: Optional[QLearningAttacker] = None,
        mode: str = 'A',
        fixed_delay_action: Optional[str] = None,
        fixed_strategy: Optional[str] = None,
        lambda_penalty: float = 0.001,
        mu_penalty: float = 1.0,
    ) -> Dict[str, float]:
        self.reset()
        self.delay_action_count = 0
        self.delay_cost_total = 0.0
        self.attacker_rewards = 0.0
        self.attacker_blocks_mined = 0
        self.total_blocks = 0
        self.fork_events = 0
        self.orphan_penalties = 0
        self.state_transitions.clear()

        mining_rates = {
            0: max(1e-6, self.alpha),
        }
        honest_rate = max(1e-6, (1.0 - self.alpha) / max(self.n_nodes - 1, 1))
        for node_id in range(1, self.n_nodes):
            mining_rates[node_id] = honest_rate
        for node_id, rate in mining_rates.items():
            self.schedule_mining_event(node_id, rate, 0.0)

        while self.total_blocks < num_blocks and self.event_queue:
            event = self.next_reception_event()
            if event is None:
                break
            self.global_time = event.time
            if event.event_type == 'receive':
                self.process_receive_event(event, fixed_strategy=fixed_strategy)
            elif event.event_type == 'mine':
                self.process_mine_event(
                    event, mining_rates, rl_agent, mode, fixed_delay_action, fixed_strategy,
                    lambda_penalty, mu_penalty,
                )

        main_chain = self.reconstruct_chain(self.public_head_id)
        attacker_blocks_main = sum(1 for block_id in main_chain if self.blocks[block_id].is_attacker)
        orphan_blocks = self.total_blocks - len(main_chain)
        return {
            'REV': attacker_blocks_main / max(self.total_blocks, 1),
            'attacker_blocks': attacker_blocks_main,
            'total_blocks': self.total_blocks,
            'fork_rate': self.fork_events / max(self.total_blocks, 1),
            'orphan_blocks': orphan_blocks,
            'delay_usage_freq': self.delay_action_count / max(self.total_blocks, 1),
            'delay_cost': self.delay_cost_total,
            'mean_reward': float(np.mean(rl_agent.history)) if rl_agent else 0.0,
            'epsilon': float(rl_agent.epsilon) if rl_agent else 0.0,
        }

    def reconstruct_chain(self, head_id: str) -> List[str]:
        chain = []
        current = head_id
        while current and current != 'genesis':
            chain.append(current)
            current = self.blocks[current].parent_id
        if current == 'genesis':
            chain.append(current)
        return list(reversed(chain))

    def process_receive_event(self, event: Event, fixed_strategy: Optional[str] = None) -> None:
        block = self.blocks[event.block_id]
        recipient = self.nodes[event.node_id]
        accepted = recipient.receive_block(block, event.time)
        if accepted and not recipient.is_attacker:
            if self.public_head_id is None:
                self.public_head_id = block.block_id
            else:
                current_height = self.blocks[self.public_head_id].height
                if block.height > current_height or (
                    block.height == current_height and event.time < self.blocks[self.public_head_id].timestamp
                ):
                    self.public_head_id = block.block_id
        if accepted and block.height == recipient.tip_height and recipient.tip_id != event.block_id:
            self.fork_events += 1
        if fixed_strategy == 'fixed' and not block.is_attacker and self.attacker_private_blocks:
            self.apply_fixed_strategy(latest_honest=True)

    def process_mine_event(
        self,
        event: Event,
        mining_rates: Dict[int, float],
        rl_agent: Optional[QLearningAttacker],
        mode: str,
        fixed_delay_action: Optional[str],
        fixed_strategy: Optional[str],
        lambda_penalty: float,
        mu_penalty: float,
    ) -> None:
        miner_id = event.node_id
        self.schedule_mining_event(miner_id, mining_rates[miner_id], self.global_time)
        parent_id = self.nodes[miner_id].tip_id
        height = self.blocks[parent_id].height + 1 if parent_id else 1
        block_id = str(uuid.uuid4())
        is_attacker = miner_id == 0
        block = Block(block_id, parent_id, height, miner_id, self.global_time, is_attacker)
        self.blocks[block_id] = block
        self.total_blocks += 1
        self.last_block_time = self.global_time

        if is_attacker:
            self.attacker_blocks_mined += 1
            if mode != 'C' or fixed_strategy == 'honest':
                self.publish_block(block, miner_id)
                return
            self.attacker_private_blocks.append(block)
            if fixed_strategy == 'fixed':
                self.apply_fixed_strategy(latest_honest=False)
                return
            self.decide_attacker_action(rl_agent, block, mode, fixed_delay_action, fixed_strategy, lambda_penalty, mu_penalty)
        else:
            self.publish_block(block, miner_id)
            if mode == 'B' and fixed_delay_action == 'passive':
                pass
            if mode == 'C' and fixed_strategy != 'fixed':
                self.decide_attacker_action(rl_agent, block, mode, fixed_delay_action, fixed_strategy, lambda_penalty, mu_penalty)

    def publish_block(self, block: Block, miner_id: int) -> None:
        self.nodes[miner_id].receive_block(block, self.global_time)
        self.broadcast_block(block, miner_id)
        if block.is_attacker:
            self.public_head_id = block.block_id
            self.attacker_rewards += 1.0
            self.step_attacker_reward += 1.0

    def decide_attacker_action(
        self,
        rl_agent: Optional[QLearningAttacker],
        block: Block,
        mode: str,
        fixed_delay_action: Optional[str],
        fixed_strategy: Optional[str],
        lambda_penalty: float,
        mu_penalty: float,
    ) -> None:
        if mode != 'C' or rl_agent is None:
            return
        state_idx = self.effective_state(rl_agent)
        action_idx = rl_agent.choose_action(state_idx)
        mining_action, delay_action = QLearningAttacker.action_tuple(action_idx)
        if delay_action != 'NO_DELAY':
            self.delay_action_count += 1
        self.attacker_delay_mode = delay_action
        if fixed_strategy == 'global_only' and delay_action == 'SELECTIVE_DELAY':
            self.attacker_delay_mode = 'GLOBAL_CONGESTION'
        if self.attacker_private_blocks and mining_action == 'override':
            for private_block in list(self.attacker_private_blocks):
                self.publish_block(private_block, 0)
            self.attacker_private_blocks.clear()
        elif self.attacker_private_blocks and mining_action == 'match':
            private_block = self.attacker_private_blocks.pop(0)
            self.publish_block(private_block, 0)
        elif mining_action == 'adopt':
            self.attacker_private_blocks.clear()
        reward = self.compute_reward(lambda_penalty, mu_penalty)
        next_state_idx = self.effective_state(rl_agent)
        rl_agent.update(state_idx, action_idx, reward, next_state_idx)
        rl_agent.decay_epsilon()
        self.step_attacker_reward = 0.0
        self.step_delay_cost = 0.0
        self.step_orphan_penalty = 0

    def apply_fixed_strategy(self, latest_honest: bool = False) -> None:
        if latest_honest and self.attacker_private_blocks:
            private_block = self.attacker_private_blocks.pop(0)
            self.publish_block(private_block, 0)
        elif len(self.attacker_private_blocks) >= 2:
            for private_block in list(self.attacker_private_blocks):
                self.publish_block(private_block, 0)
            self.attacker_private_blocks.clear()

    def compute_reward(self, lambda_penalty: float, mu_penalty: float) -> float:
        reward = self.step_attacker_reward
        reward -= lambda_penalty * self.step_delay_cost
        reward -= mu_penalty * self.step_orphan_penalty
        return reward
