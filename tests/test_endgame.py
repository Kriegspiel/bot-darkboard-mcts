import chess

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.endgame import EndgameWeights
from darkboard_mcts.endgame import evaluate_endgame_urgency
from darkboard_mcts.outcome_model import RefereeOutcomeEstimate


def _outcome(**overrides: float) -> RefereeOutcomeEstimate:
    values = {
        "legal_probability": 0.9,
        "path_block_probability": 0.0,
        "king_safety_risk": 0.0,
        "target_occupancy_probability": 0.0,
        "pawn_capture_probability": 0.0,
        "piece_capture_probability": 0.0,
        "capture_probability": 0.0,
        "expected_capture_value": 0.0,
        "check_probability": 0.0,
        "recapture_probability": 0.0,
        "exposed_piece_capture_probability": 0.0,
        "checking_piece_vulnerability": 0.0,
    }
    values.update(overrides)
    return RefereeOutcomeEstimate(**values)


def test_endgame_urgency_is_inactive_before_benchmark_drag_window() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/4P3/4K3 w - - 0 1",
        legal_actions=("e2e4",),
        ply=40,
    )

    score = evaluate_endgame_urgency(
        belief,
        move=chess.Move.from_uci("e2e4"),
        piece=chess.Piece(chess.PAWN, chess.WHITE),
        outcome=_outcome(capture_probability=1.0, expected_capture_value=900.0),
        weights=EndgameWeights(start_ply=100.0),
    )

    assert score == 0.0


def test_endgame_urgency_prefers_forcing_capture_over_quiet_late_move() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/4P3/4K3 w - - 0 1",
        legal_actions=("e2e4", "e2d3"),
        ply=600,
    )
    piece = chess.Piece(chess.PAWN, chess.WHITE)
    weights = EndgameWeights(start_ply=100.0, full_ply=200.0)

    capture = evaluate_endgame_urgency(
        belief,
        move=chess.Move.from_uci("e2d3"),
        piece=piece,
        outcome=_outcome(capture_probability=0.9, expected_capture_value=360.0),
        weights=weights,
    )
    quiet = evaluate_endgame_urgency(
        belief,
        move=chess.Move.from_uci("e2e4"),
        piece=piece,
        outcome=_outcome(capture_probability=0.0, expected_capture_value=0.0),
        weights=weights,
    )

    assert capture > 0
    assert quiet < 0
    assert capture > quiet
