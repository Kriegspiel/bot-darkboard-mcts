"""Benchmark-driven endgame urgency terms."""

from __future__ import annotations

from dataclasses import dataclass, fields
from os import environ

import chess

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.outcome_model import PIECE_VALUES
from darkboard_mcts.outcome_model import RefereeOutcomeEstimate


WEIGHT_ENV_PREFIX = "DARKBOARD_ENDGAME_"


@dataclass(frozen=True)
class EndgameWeights:
    """Tunable pressure to avoid very long low-contact games."""

    start_ply: float = 140.0
    full_ply: float = 420.0
    material_advantage_start: float = 260.0
    material_advantage_full: float = 900.0
    low_opponent_material_start: float = 1400.0
    low_opponent_material_full: float = 450.0
    capture_scale: float = 0.31
    check_scale: float = 190.0
    promotion_scale: float = 0.78
    quiet_penalty: float = 48.0
    illegal_penalty: float = 58.0
    max_adjustment: float = 320.0

    @classmethod
    def from_env(cls) -> "EndgameWeights":
        values: dict[str, float] = {}
        for field in fields(cls):
            raw = environ.get(f"{WEIGHT_ENV_PREFIX}{field.name.upper()}")
            if raw is None:
                continue
            try:
                values[field.name] = float(raw)
            except ValueError:
                continue
        return cls(**values)


def evaluate_endgame_urgency(
    belief: BeliefState,
    *,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
    outcome: RefereeOutcomeEstimate,
    weights: EndgameWeights | None = None,
) -> float:
    """Score forcing progress once benchmark data says games are dragging."""

    weights = weights or EndgameWeights.from_env()
    phase = max(_phase(belief.ply, weights=weights), _conversion_phase(belief, board=board, weights=weights))
    if phase <= 0:
        return 0.0

    capture_pressure = max(0.0, outcome.expected_capture_value) * outcome.capture_probability * weights.capture_scale
    check_pressure = outcome.check_probability * weights.check_scale
    promotion_pressure = _promotion_pressure(belief=belief, move=move, piece=piece, outcome=outcome) * weights.promotion_scale
    quietness = (1.0 - min(1.0, outcome.capture_probability + outcome.check_probability)) * weights.quiet_penalty
    illegal_pressure = outcome.illegal_probability * weights.illegal_penalty
    adjustment = phase * (capture_pressure + check_pressure + promotion_pressure - quietness - illegal_pressure)
    return _clamp(adjustment, -weights.max_adjustment, weights.max_adjustment)


def _phase(ply: int, *, weights: EndgameWeights) -> float:
    if ply <= weights.start_ply:
        return 0.0
    span = max(1.0, weights.full_ply - weights.start_ply)
    return _clamp((ply - weights.start_ply) / span, 0.0, 1.0)


def _conversion_phase(belief: BeliefState, *, board: chess.Board, weights: EndgameWeights) -> float:
    own_material = _own_material_value(board=board, color=belief.color)
    opponent_material = _opponent_material_value(belief)
    advantage = own_material - opponent_material
    advantage_phase = _clamp(
        (advantage - weights.material_advantage_start)
        / max(1.0, weights.material_advantage_full - weights.material_advantage_start),
        0.0,
        1.0,
    )
    low_material_phase = _clamp(
        (weights.low_opponent_material_start - opponent_material)
        / max(1.0, weights.low_opponent_material_start - weights.low_opponent_material_full),
        0.0,
        1.0,
    )
    return max(advantage_phase, low_material_phase * 0.85)


def _promotion_pressure(
    *,
    belief: BeliefState,
    move: chess.Move,
    piece: chess.Piece,
    outcome: RefereeOutcomeEstimate,
) -> float:
    if piece.piece_type != chess.PAWN:
        return 0.0
    if move.promotion:
        return max(0.0, PIECE_VALUES.get(move.promotion, 0.0) - PIECE_VALUES[chess.PAWN]) * outcome.legal_probability
    promotion_rank = 7 if belief.color == chess.WHITE else 0
    ranks_to_promotion = abs(promotion_rank - chess.square_rank(move.to_square))
    if ranks_to_promotion > 2:
        return 0.0
    return (3 - ranks_to_promotion) * 85.0 * outcome.legal_probability


def _own_material_value(*, board: chess.Board, color: chess.Color) -> float:
    return sum(
        PIECE_VALUES.get(piece.piece_type, 360.0)
        for piece in board.piece_map().values()
        if piece.color == color and piece.piece_type != chess.KING
    )


def _opponent_material_value(belief: BeliefState) -> float:
    return (sum(max(0.0, value) for value in belief.opponent_pawns) * PIECE_VALUES[chess.PAWN]) + (
        sum(max(0.0, value) for value in belief.opponent_pieces) * 360.0
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
