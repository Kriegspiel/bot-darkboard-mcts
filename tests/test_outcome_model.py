from __future__ import annotations

from unittest.mock import patch

import chess
import pytest

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.outcome_model import OutcomeModelWeights
from darkboard_mcts.outcome_model import estimate_referee_outcome


def matrix(square: chess.Square, value: float) -> tuple[float, ...]:
    values = [0.0] * 64
    values[square] = value
    return tuple(values)


def outcome_for(belief: BeliefState, uci: str):
    board = chess.Board(belief.visible_fen)
    move = chess.Move.from_uci(uci)
    piece = board.piece_at(move.from_square)
    assert piece is not None
    return estimate_referee_outcome(belief, board=board, move=move, piece=piece)


def test_sliding_path_density_lowers_legality_probability() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a8",),
        opponent_pieces=matrix(chess.A4, 1.0),
    )

    outcome = outcome_for(belief, "a1a8")

    assert outcome.path_block_probability == pytest.approx(1.0)
    assert outcome.legal_probability == pytest.approx(0.0)


def test_capture_and_check_probabilities_come_from_belief_matrices() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a8",),
        opponent_pieces=matrix(chess.A8, 1.0),
        opponent_king=matrix(chess.A7, 1.0),
    )

    outcome = outcome_for(belief, "a1a8")

    assert outcome.capture_probability == pytest.approx(1.0)
    assert outcome.expected_capture_value == pytest.approx(360.0)
    assert outcome.check_probability == pytest.approx(1.0)


def test_pawn_diagonal_without_target_occupancy_is_likely_illegal() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/3P4/4K3 w - - 0 1",
        legal_actions=("d2e3",),
    )

    outcome = outcome_for(belief, "d2e3")

    assert outcome.capture_probability == pytest.approx(0.0)
    assert outcome.legal_probability == pytest.approx(0.0)
    assert outcome.illegal_probability == pytest.approx(1.0)


def test_exposed_piece_capture_probability_uses_opponent_pawn_attacks() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a2",),
        opponent_pawns=matrix(chess.B3, 1.0),
    )

    outcome = outcome_for(belief, "a1a2")

    assert outcome.exposed_piece_capture_probability == pytest.approx(1.0)


def test_outcome_model_weights_can_be_overridden_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "DARKBOARD_MODEL_CHECK_PRESSURE": "210",
            "DARKBOARD_MODEL_ILLEGAL_ATTEMPT_PENALTY": "55.5",
            "DARKBOARD_MODEL_SAFETY_PENALTY_SCALE": "not-a-number",
        },
    ):
        weights = OutcomeModelWeights.from_env()

    assert weights.check_pressure == pytest.approx(210.0)
    assert weights.illegal_attempt_penalty == pytest.approx(55.5)
    assert weights.safety_penalty_scale == pytest.approx(0.28)
