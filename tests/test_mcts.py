from __future__ import annotations

from unittest.mock import patch

import chess

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.evaluation import ranked_action_scores
from darkboard_mcts.mcts import MCTSConfig
from darkboard_mcts.mcts import search


def matrix(square: chess.Square, value: float) -> tuple[float, ...]:
    values = [0.0] * 64
    values[square] = value
    return tuple(values)


def test_mcts_prefers_high_value_capture_by_value() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a2", "a1a8"),
        opponent_pieces=matrix(chess.A8, 1.0),
    )

    result = search(
        belief,
        config=MCTSConfig(time_budget_seconds=1.0, max_iterations=64, selection_rule="value", seed=7),
    )

    assert result.actions[0] == "a1a8"
    assert result.iterations == 64
    assert result.used_fallback is False


def test_mcts_builds_public_outcome_tree_levels() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a8",),
        opponent_pieces=matrix(chess.A8, 1.0),
        opponent_king=matrix(chess.H8, 1.0),
    )

    result = search(
        belief,
        config=MCTSConfig(time_budget_seconds=1.0, max_iterations=12, selection_rule="visits", seed=3),
    )
    action = result.root.children["a1a8"]

    assert result.iterations == 12
    assert action.visits == 12
    assert {"capture", "quiet"} & set(action.own_outcomes)
    capture = action.own_outcomes.get("capture")
    assert capture is not None
    assert "quiet" in capture.opponent_outcomes


def test_mcts_disabled_returns_deterministic_fallback() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a2", "a1a8"),
        opponent_pieces=matrix(chess.A8, 1.0),
    )

    result = search(belief, config=MCTSConfig(enabled=False))

    assert result.actions == tuple(score.uci for score in ranked_action_scores(belief))
    assert result.used_fallback is True
    assert result.iterations == 0


def test_mcts_config_reads_env_and_clamps_budget() -> None:
    with patch.dict(
        "os.environ",
        {
            "DARKBOARD_MCTS_ENABLED": "true",
            "DARKBOARD_MCTS_TIME_BUDGET_SECONDS": "99",
            "DARKBOARD_MCTS_MAX_ITERATIONS": "25",
            "DARKBOARD_MCTS_EXPLORATION": "2.5",
            "DARKBOARD_MCTS_SELECTION_RULE": "value",
            "DARKBOARD_MCTS_SEED": "42",
        },
    ):
        config = MCTSConfig.from_env()

    assert config.enabled is True
    assert config.time_budget_seconds == 8.0
    assert config.max_iterations == 25
    assert config.exploration == 2.5
    assert config.selection_rule == "value"
    assert config.seed == 42


def test_mcts_defaults_to_value_selection() -> None:
    with patch.dict("os.environ", {}, clear=True):
        config = MCTSConfig.from_env()

    assert config.selection_rule == "value"


def test_mcts_legal_leaf_branches_include_endgame_urgency() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/3P4/4K3 w - - 0 1",
        legal_actions=("d2e3",),
        opponent_pieces=matrix(chess.E3, 1.0),
        ply=600,
    )

    score = ranked_action_scores(belief)[0]
    result = search(
        belief,
        config=MCTSConfig(time_budget_seconds=1.0, max_iterations=1, selection_rule="value", seed=5),
    )
    capture = result.root.children["d2e3"].own_outcomes["capture"]

    assert score.endgame_urgency > 0
    assert capture.value >= score.endgame_urgency
