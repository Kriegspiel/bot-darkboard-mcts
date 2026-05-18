from __future__ import annotations

from unittest.mock import patch

import chess
import pytest

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.evaluation import ranked_action_scores
from darkboard_mcts.outcome_model import estimate_referee_outcome
from darkboard_mcts.quiescence import QuiescenceWeights
from darkboard_mcts.quiescence import evaluate_quiescence


def matrix(square: chess.Square, value: float) -> tuple[float, ...]:
    values = [0.0] * 64
    values[square] = value
    return tuple(values)


def estimate_for(
    belief: BeliefState,
    uci: str,
    *,
    latest_capture_square: chess.Square | None = None,
    weights: QuiescenceWeights | None = None,
):
    board = chess.Board(belief.visible_fen)
    move = chess.Move.from_uci(uci)
    piece = board.piece_at(move.from_square)
    assert piece is not None
    outcome = estimate_referee_outcome(
        belief,
        board=board,
        move=move,
        piece=piece,
        latest_capture_square=latest_capture_square,
    )
    return evaluate_quiescence(
        belief,
        board=board,
        move=move,
        piece=piece,
        outcome=outcome,
        latest_capture_square=latest_capture_square,
        weights=weights,
    )


def test_quiescence_penalizes_high_value_piece_landing_under_pawn_attack() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a2",),
        opponent_pawns=matrix(chess.B3, 1.0),
    )

    estimate = estimate_for(belief, "a1a2")

    assert estimate.immediate_loss_penalty == pytest.approx(275.0)
    assert estimate.adjustment < 0


def test_quiescence_rewards_public_recapture_target() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/3P4/4K3 w - - 0 1",
        legal_actions=("d2e3",),
    )

    estimate = estimate_for(belief, "d2e3", latest_capture_square=chess.E3)

    assert estimate.recapture_chain_value > 0
    assert estimate.capture_chain_value > 0
    assert estimate.adjustment > 0


def test_quiescence_rewards_near_promotion_pawns() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/4P3/8/8/8/8/4K3 w - - 0 1",
        legal_actions=("e6e7",),
    )

    estimate = estimate_for(belief, "e6e7")

    assert estimate.promotion_race_bonus > 0
    assert estimate.adjustment > 0


def test_quiescence_penalizes_informative_probe_when_risk_exceeds_gain() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a8",),
        opponent_king=matrix(chess.A8, 0.8),
        opponent_pawns=matrix(chess.B3, 1.0),
    )

    estimate = estimate_for(belief, "a1a8")

    assert estimate.informative_probe_penalty > 0
    assert estimate.adjustment < 0


def test_quiescence_weights_can_be_overridden_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "DARKBOARD_QUIESCENCE_CAPTURE_CHAIN_SCALE": "0.9",
            "DARKBOARD_QUIESCENCE_MAX_ADJUSTMENT": "125",
            "DARKBOARD_QUIESCENCE_PROMOTION_RACE_SCALE": "not-a-number",
        },
    ):
        weights = QuiescenceWeights.from_env()

    assert weights.capture_chain_scale == pytest.approx(0.9)
    assert weights.max_adjustment == pytest.approx(125.0)
    assert weights.promotion_race_scale == pytest.approx(0.65)


def test_action_scores_include_quiescence_terms() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/3P4/4K3 w - - 0 1",
        legal_actions=("d2e3",),
        referee_log=({"announcement": "Piece captured at E3"},),
    )

    score = ranked_action_scores(belief)[0]

    assert score.uci == "d2e3"
    assert score.quiescence_adjustment > 0
    assert score.recapture_chain_value > 0
