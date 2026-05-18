from __future__ import annotations

import chess
import pytest

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.evidence import apply_move_result_evidence
from darkboard_mcts.evidence import apply_referee_log_evidence
from darkboard_mcts.evidence import restore_belief_snapshot


def matrix(square: chess.Square, value: float, *, total: float | None = None) -> tuple[float, ...]:
    values = [0.0] * 64
    values[square] = value
    if total is not None and total > value:
        values[chess.H6] = total - value
    return tuple(values)


def base_belief(**overrides) -> BeliefState:
    values = {
        "color": chess.WHITE,
        "visible_fen": "8/8/8/8/8/8/3P4/R6K w - - 0 1",
        "legal_actions": ("d2e3", "d2d3"),
        "material_summary": {"white": {"pieces_remaining": 10}, "black": {"pieces_remaining": 16}},
    }
    values.update(overrides)
    return BeliefState(**values)


def test_failed_pawn_capture_attempt_suppresses_target_occupancy() -> None:
    belief = base_belief(opponent_pawns=matrix(chess.E3, 4.0, total=8.0))

    updated = apply_move_result_evidence(
        belief,
        uci="d2e3",
        result={"announcement": "ILLEGAL_MOVE", "move_done": False},
    )

    assert updated.opponent_pawns[chess.E3] < belief.opponent_pawns[chess.E3]
    assert sum(updated.opponent_pawns) == pytest.approx(8.0)
    assert updated.observed_referee_log_size == 1


def test_failed_sliding_attempt_boosts_possible_hidden_blockers() -> None:
    belief = base_belief(
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a8",),
    )

    updated = apply_move_result_evidence(
        belief,
        uci="a1a8",
        result={"announcement": "ILLEGAL_MOVE", "move_done": False},
    )

    assert updated.opponent_pieces[chess.A2] > belief.opponent_pieces[chess.A2]
    assert updated.opponent_pawns[chess.A2] > belief.opponent_pawns[chess.A2]


def test_capture_result_removes_captured_pawn_from_expected_count() -> None:
    belief = base_belief(opponent_pawns=matrix(chess.E3, 4.0, total=8.0))

    updated = apply_move_result_evidence(
        belief,
        uci="d2e3",
        result={
            "announcement": "CAPTURE_DONE",
            "move_done": True,
            "capture_square": "e3",
            "captured_piece_announcement": "PAWN",
        },
    )

    assert updated.opponent_pawns[chess.E3] == 0
    assert sum(updated.opponent_pawns) == pytest.approx(7.0)


def test_check_announcement_boosts_king_density_on_attacked_squares() -> None:
    belief = base_belief(
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a8",),
    )

    updated = apply_move_result_evidence(
        belief,
        uci="a1a8",
        result={"announcement": "REGULAR_MOVE", "special_announcement": "CHECK_FILE", "move_done": True},
    )

    assert updated.opponent_king[chess.A7] > belief.opponent_king[chess.A7]
    assert sum(updated.opponent_king) == pytest.approx(1.0)


def test_restore_snapshot_applies_new_referee_log_once() -> None:
    current = base_belief(
        referee_log=({"announcement": "Move attempt — Pawn captured at E3", "capture_square": None},),
    )
    snapshot = {
        "game_id": "",
        "ruleset": "wild16",
        "color": "white",
        "observed_referee_log_size": 0,
        "opponent_pawns": list(matrix(chess.E3, 4.0, total=8.0)),
        "opponent_king": list(current.opponent_king),
        "opponent_pieces": list(current.opponent_pieces),
    }

    updated = restore_belief_snapshot(current, snapshot)
    reapplied = apply_referee_log_evidence(updated)

    assert updated.opponent_pawns[chess.E3] == 0
    assert sum(updated.opponent_pawns) == pytest.approx(8.0)
    assert updated.observed_referee_log_size == 1
    assert reapplied.opponent_pawns == updated.opponent_pawns


def test_incompatible_snapshot_falls_back_to_current_priors() -> None:
    current = base_belief()
    snapshot = {
        "ruleset": "wild16",
        "color": "black",
        "observed_referee_log_size": 10,
        "opponent_pawns": list(matrix(chess.E3, 8.0)),
    }

    updated = restore_belief_snapshot(current, snapshot)

    assert updated.color == chess.WHITE
    assert updated.observed_referee_log_size == 0
    assert updated.opponent_pawns == current.opponent_pawns
