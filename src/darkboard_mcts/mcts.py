"""Bounded MCTS over public referee outcome branches."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import os
import random
import time
from typing import TypeVar

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.evaluation import ActionScore
from darkboard_mcts.evaluation import ranked_action_scores


logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class MCTSConfig:
    enabled: bool = True
    time_budget_seconds: float = 1.0
    max_iterations: int = 384
    exploration: float = 1.4
    selection_rule: str = "visits"
    seed: int = 0

    @classmethod
    def from_env(cls) -> "MCTSConfig":
        return cls(
            enabled=_bool_env("DARKBOARD_MCTS_ENABLED", True),
            time_budget_seconds=_float_env("DARKBOARD_MCTS_TIME_BUDGET_SECONDS", 1.0, minimum=0.0, maximum=8.0),
            max_iterations=_int_env("DARKBOARD_MCTS_MAX_ITERATIONS", 384, minimum=1),
            exploration=_float_env("DARKBOARD_MCTS_EXPLORATION", 1.4, minimum=0.0, maximum=10.0),
            selection_rule=_selection_rule_env("DARKBOARD_MCTS_SELECTION_RULE", "visits"),
            seed=_int_env("DARKBOARD_MCTS_SEED", 0, minimum=0),
        )


@dataclass
class OpponentOutcomeNode:
    name: str
    probability: float
    value: float
    visits: int = 0
    value_sum: float = 0.0


@dataclass
class OwnOutcomeNode:
    name: str
    probability: float
    value: float
    opponent_outcomes: dict[str, OpponentOutcomeNode]
    visits: int = 0
    value_sum: float = 0.0


@dataclass
class ActionNode:
    uci: str
    prior_score: ActionScore
    own_outcomes: dict[str, OwnOutcomeNode]
    visits: int = 0
    value_sum: float = 0.0
    best_value: float = -math.inf

    @property
    def average_value(self) -> float:
        if self.visits <= 0:
            return self.prior_score.score
        return self.value_sum / self.visits


@dataclass
class RootNode:
    children: dict[str, ActionNode]
    visits: int = 0


@dataclass(frozen=True)
class MCTSResult:
    actions: tuple[str, ...]
    root: RootNode
    iterations: int
    elapsed_seconds: float
    selection_rule: str
    used_fallback: bool = False


def ranked_actions_mcts(belief: BeliefState, *, config: MCTSConfig | None = None) -> tuple[str, ...]:
    result = search(belief, config=config)
    return result.actions


def search(belief: BeliefState, *, config: MCTSConfig | None = None) -> MCTSResult:
    config = config or MCTSConfig.from_env()
    fallback_scores = ranked_action_scores(belief)
    fallback_actions = tuple(score.uci for score in fallback_scores)
    if not config.enabled or config.time_budget_seconds <= 0 or not fallback_scores:
        return MCTSResult(
            actions=fallback_actions,
            root=RootNode({}),
            iterations=0,
            elapsed_seconds=0.0,
            selection_rule=config.selection_rule,
            used_fallback=True,
        )

    try:
        root = build_root(fallback_scores)
        started = time.monotonic()
        rng = random.Random(config.seed)
        iterations = 0
        while iterations < config.max_iterations and time.monotonic() - started < config.time_budget_seconds:
            action = _select_action(root, config=config)
            value = _simulate_action(action, rng=rng)
            _backup(root, action=action, value=value)
            iterations += 1

        elapsed = time.monotonic() - started
        if iterations <= 0:
            return MCTSResult(
                actions=fallback_actions,
                root=root,
                iterations=0,
                elapsed_seconds=elapsed,
                selection_rule=config.selection_rule,
                used_fallback=True,
            )

        actions = _rank_actions(root, config=config)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("mcts_result iterations=%s elapsed=%.4f actions=%s", iterations, elapsed, actions)
        return MCTSResult(
            actions=actions,
            root=root,
            iterations=iterations,
            elapsed_seconds=elapsed,
            selection_rule=config.selection_rule,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime fallback
        logger.warning("mcts fallback after search failure: %s", exc)
        return MCTSResult(
            actions=fallback_actions,
            root=RootNode({}),
            iterations=0,
            elapsed_seconds=0.0,
            selection_rule=config.selection_rule,
            used_fallback=True,
        )


def build_root(scores: tuple[ActionScore, ...]) -> RootNode:
    return RootNode({score.uci: _action_node(score) for score in scores})


def _action_node(score: ActionScore) -> ActionNode:
    legal = _clamp(score.legal_probability)
    illegal = 1.0 - legal
    capture = legal * _clamp(score.capture_probability)
    check = legal * (1.0 - _clamp(score.capture_probability)) * _clamp(score.check_probability)
    quiet = max(0.0, legal - capture - check)

    branches = _normalize_branches(
        {
            "illegal": (illegal, -max(score.legality_penalty, 20.0)),
            "capture": (capture, _event_value(score.capture_value, capture) + score.recapture_bonus),
            "check": (check, _event_value(score.check_pressure, check) + score.development),
            "quiet": (quiet, score.development),
        }
    )
    return ActionNode(
        uci=score.uci,
        prior_score=score,
        own_outcomes={
            name: OwnOutcomeNode(
                name=name,
                probability=probability,
                value=value,
                opponent_outcomes=_opponent_outcomes(score, own_outcome=name),
            )
            for name, (probability, value) in branches.items()
        },
    )


def _opponent_outcomes(score: ActionScore, *, own_outcome: str) -> dict[str, OpponentOutcomeNode]:
    if own_outcome == "illegal":
        return {"none": OpponentOutcomeNode(name="none", probability=1.0, value=0.0)}

    recapture = _clamp(score.opponent_recapture_probability if own_outcome == "capture" else 0.0)
    exposed = _clamp(score.exposed_piece_capture_probability) * (1.0 - recapture)
    quiet = max(0.0, 1.0 - recapture - exposed)
    safety_loss = _event_value(score.safety_penalty, max(recapture + exposed, 0.01))
    vulnerability_loss = _event_value(score.checking_piece_vulnerability, max(exposed, 0.01))
    branches = _normalize_branches(
        {
            "recapture": (recapture, -max(safety_loss, 40.0)),
            "capture_exposed": (exposed, -max(safety_loss + vulnerability_loss, 25.0)),
            "quiet": (quiet, 0.0),
        }
    )
    return {
        name: OpponentOutcomeNode(name=name, probability=probability, value=value)
        for name, (probability, value) in branches.items()
    }


def _select_action(root: RootNode, *, config: MCTSConfig) -> ActionNode:
    unvisited = [child for child in root.children.values() if child.visits == 0]
    if unvisited:
        return max(unvisited, key=lambda child: (child.prior_score.score, child.uci))

    log_visits = math.log(max(2, root.visits + 1))
    return max(
        root.children.values(),
        key=lambda child: (
            child.average_value + (config.exploration * math.sqrt(log_visits / child.visits)),
            child.prior_score.score,
            child.uci,
        ),
    )


def _simulate_action(action: ActionNode, *, rng: random.Random) -> float:
    own = _weighted_choice(action.own_outcomes, rng=rng)
    opponent = _weighted_choice(own.opponent_outcomes, rng=rng)
    own.visits += 1
    opponent.visits += 1
    value = own.value + opponent.value
    own.value_sum += value
    opponent.value_sum += value
    return value


def _backup(root: RootNode, *, action: ActionNode, value: float) -> None:
    root.visits += 1
    action.visits += 1
    action.best_value = max(action.best_value, value)
    action.value_sum += action.best_value


def _rank_actions(root: RootNode, *, config: MCTSConfig) -> tuple[str, ...]:
    if config.selection_rule == "value":
        key = lambda child: (
            -child.best_value,
            -child.average_value,
            -child.visits,
            -child.prior_score.score,
            child.uci,
        )
    else:
        key = lambda child: (
            -child.visits,
            -child.best_value,
            -child.average_value,
            -child.prior_score.score,
            child.uci,
        )
    return tuple(child.uci for child in sorted(root.children.values(), key=key))


def _weighted_choice(branches: dict[str, T], *, rng: random.Random) -> T:
    total = sum(max(0.0, getattr(branch, "probability")) for branch in branches.values())
    if total <= 0:
        return next(iter(branches.values()))

    threshold = rng.random() * total
    cumulative = 0.0
    last = next(iter(branches.values()))
    for branch in branches.values():
        last = branch
        cumulative += max(0.0, getattr(branch, "probability"))
        if threshold <= cumulative:
            return branch
    return last


def _normalize_branches(source: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    total = sum(max(0.0, probability) for probability, _ in source.values())
    if total <= 0:
        return {"quiet": (1.0, 0.0)}
    return {
        name: (max(0.0, probability) / total, value)
        for name, (probability, value) in source.items()
        if probability > 0
    }


def _event_value(expected_value: float, probability: float) -> float:
    if probability <= 0:
        return 0.0
    return max(-1200.0, min(1200.0, expected_value / max(probability, 0.05)))


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return min(maximum, max(minimum, float(raw)))
    except ValueError:
        return default


def _selection_rule_env(name: str, default: str) -> str:
    raw = os.environ.get(name, default).strip().lower()
    return raw if raw in {"visits", "value"} else default


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
