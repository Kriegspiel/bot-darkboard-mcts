from __future__ import annotations

from unittest.mock import patch

import chess
import pytest

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.evaluation import ranked_action_scores
from darkboard_mcts.metaposition import MetapositionWeights
from darkboard_mcts.metaposition import build_metaposition
from darkboard_mcts.mcts import build_root


def matrix(square: chess.Square, value: float) -> tuple[float, ...]:
    values = [0.0] * 64
    values[square] = value
    return tuple(values)


def test_metaposition_exposes_possible_occupancy_helpers() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R3K3 w - - 0 1",
        legal_actions=("a1a2",),
        opponent_king=matrix(chess.H8, 1.0),
        opponent_pawns=matrix(chess.D6, 0.75),
        opponent_pieces=matrix(chess.C5, 0.5),
    )

    metaposition = build_metaposition(belief, board=chess.Board(belief.visible_fen))

    assert metaposition.opponent_occupancy_at(chess.H8) == pytest.approx(1.0)
    assert metaposition.possible_king_squares(threshold=0.9) == (chess.H8,)
    assert metaposition.possible_pawn_squares(threshold=0.7) == (chess.D6,)
    assert metaposition.possible_piece_squares(threshold=0.4) == (chess.C5,)
    assert metaposition.open_file_probability(0) == pytest.approx(1.0)
    assert metaposition.open_file_probability(3) == pytest.approx(0.25)


def test_metaposition_rewards_promotion_pressure_and_passed_pawns() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/4P3/8/8/8/8/4K3 w - - 0 1",
        legal_actions=("e6e7",),
    )

    score = ranked_action_scores(belief)[0]

    assert score.uci == "e6e7"
    assert score.metaposition_adjustment > 0
    assert score.pawn_advancement > 0
    assert score.promotion_pressure > 0
    assert score.friendly_open_file_value > 0


def test_metaposition_rewards_king_edge_and_checkmating_pressure() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/4K2R w - - 0 1",
        legal_actions=("h1h7",),
        opponent_king=matrix(chess.H8, 1.0),
    )

    score = ranked_action_scores(belief)[0]

    assert score.king_edge_pressure > 0
    assert score.checkmating_pressure > 0
    assert score.open_file_value > 0


def test_metaposition_penalizes_expected_opponent_promotion_pressure() -> None:
    safe = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/4K3 w - - 0 1",
        legal_actions=("e1e2",),
    )
    dangerous = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/4K3 w - - 0 1",
        legal_actions=("e1e2",),
        opponent_pawns=matrix(chess.E2, 1.0),
    )

    safe_score = ranked_action_scores(safe)[0]
    dangerous_score = ranked_action_scores(dangerous)[0]

    assert dangerous_score.promotion_pressure < safe_score.promotion_pressure
    assert dangerous_score.metaposition_adjustment < safe_score.metaposition_adjustment


def test_metaposition_weights_can_be_overridden_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "DARKBOARD_METAPOSITION_PROMOTION_PRESSURE_SCALE": "1.25",
            "DARKBOARD_METAPOSITION_MAX_ADJUSTMENT": "90",
            "DARKBOARD_METAPOSITION_CONTROLLED_SQUARES_SCALE": "not-a-number",
        },
    ):
        weights = MetapositionWeights.from_env()

    assert weights.promotion_pressure_scale == pytest.approx(1.25)
    assert weights.max_adjustment == pytest.approx(90.0)
    assert weights.controlled_squares_scale == pytest.approx(1.0)


def test_mcts_legal_leaf_branches_include_metaposition_adjustment() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/4P3/8/8/8/8/4K3 w - - 0 1",
        legal_actions=("e6e7",),
    )

    score = ranked_action_scores(belief)[0]
    root = build_root((score,))
    quiet = root.children["e6e7"].own_outcomes["quiet"]

    assert score.metaposition_adjustment > 0
    assert quiet.value >= score.development + score.metaposition_adjustment
