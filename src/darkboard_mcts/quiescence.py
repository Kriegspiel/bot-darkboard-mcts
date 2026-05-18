"""Short tactical continuation estimates for volatile public positions."""

from __future__ import annotations

from dataclasses import dataclass, fields
from os import environ

import chess

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.outcome_model import GENERIC_OPPONENT_PIECE_VALUE
from darkboard_mcts.outcome_model import PIECE_VALUES
from darkboard_mcts.outcome_model import RefereeOutcomeEstimate


WEIGHT_ENV_PREFIX = "DARKBOARD_QUIESCENCE_"


@dataclass(frozen=True)
class QuiescenceWeights:
    capture_chain_scale: float = 0.34
    recapture_chain_scale: float = 0.42
    immediate_loss_scale: float = 0.55
    checking_piece_vulnerability_scale: float = 0.35
    promotion_race_scale: float = 0.65
    informative_probe_penalty_scale: float = 0.45
    max_adjustment: float = 700.0

    @classmethod
    def from_env(cls) -> "QuiescenceWeights":
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


@dataclass(frozen=True)
class QuiescenceEstimate:
    capture_chain_value: float = 0.0
    recapture_chain_value: float = 0.0
    immediate_loss_penalty: float = 0.0
    checking_piece_vulnerability: float = 0.0
    promotion_race_bonus: float = 0.0
    informative_probe_penalty: float = 0.0
    adjustment: float = 0.0


def evaluate_quiescence(
    belief: BeliefState,
    *,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
    outcome: RefereeOutcomeEstimate,
    latest_capture_square: chess.Square | None,
    weights: QuiescenceWeights | None = None,
) -> QuiescenceEstimate:
    """Estimate short-horizon volatility after the modeled referee outcome."""

    weights = weights or QuiescenceWeights.from_env()
    landed_value = _landed_piece_value(move=move, piece=piece)
    event_capture_value = _event_capture_value(outcome)
    capture_chain_value = _capture_chain_value(
        outcome=outcome,
        landed_value=landed_value,
        event_capture_value=event_capture_value,
        weights=weights,
    )
    recapture_chain_value = _recapture_chain_value(
        outcome=outcome,
        move=move,
        latest_capture_square=latest_capture_square,
        event_capture_value=event_capture_value,
        weights=weights,
    )
    immediate_loss_penalty = (
        outcome.legal_probability
        * outcome.exposed_piece_capture_probability
        * landed_value
        * weights.immediate_loss_scale
    )
    checking_piece_vulnerability = (
        outcome.checking_piece_vulnerability
        * landed_value
        * weights.checking_piece_vulnerability_scale
    )
    promotion_race_bonus = _promotion_race_bonus(
        belief=belief,
        board=board,
        move=move,
        piece=piece,
        outcome=outcome,
        landed_value=landed_value,
        weights=weights,
    )
    informative_probe_penalty = _informative_probe_penalty(
        outcome=outcome,
        landed_value=landed_value,
        immediate_loss_penalty=immediate_loss_penalty,
        checking_piece_vulnerability=checking_piece_vulnerability,
        weights=weights,
    )
    adjustment = (
        capture_chain_value
        + recapture_chain_value
        + promotion_race_bonus
        - immediate_loss_penalty
        - checking_piece_vulnerability
        - informative_probe_penalty
    )
    adjustment = _clamp(adjustment, -weights.max_adjustment, weights.max_adjustment)
    return QuiescenceEstimate(
        capture_chain_value=capture_chain_value,
        recapture_chain_value=recapture_chain_value,
        immediate_loss_penalty=immediate_loss_penalty,
        checking_piece_vulnerability=checking_piece_vulnerability,
        promotion_race_bonus=promotion_race_bonus,
        informative_probe_penalty=informative_probe_penalty,
        adjustment=adjustment,
    )


def _capture_chain_value(
    *,
    outcome: RefereeOutcomeEstimate,
    landed_value: float,
    event_capture_value: float,
    weights: QuiescenceWeights,
) -> float:
    if outcome.capture_probability <= 0:
        return 0.0
    recapture_drag = outcome.recapture_probability * landed_value * 0.45
    return max(0.0, event_capture_value - recapture_drag) * outcome.capture_probability * weights.capture_chain_scale


def _recapture_chain_value(
    *,
    outcome: RefereeOutcomeEstimate,
    move: chess.Move,
    latest_capture_square: chess.Square | None,
    event_capture_value: float,
    weights: QuiescenceWeights,
) -> float:
    if latest_capture_square is None or latest_capture_square != move.to_square:
        return 0.0
    if outcome.capture_probability <= 0:
        return 0.0
    return max(80.0, event_capture_value) * outcome.capture_probability * weights.recapture_chain_scale


def _promotion_race_bonus(
    *,
    belief: BeliefState,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
    outcome: RefereeOutcomeEstimate,
    landed_value: float,
    weights: QuiescenceWeights,
) -> float:
    if piece.piece_type != chess.PAWN:
        return 0.0

    if move.promotion:
        promotion_gain = max(0.0, landed_value - PIECE_VALUES[chess.PAWN])
        return promotion_gain * outcome.legal_probability * weights.promotion_race_scale

    promotion_rank = 7 if belief.color == chess.WHITE else 0
    ranks_to_promotion = abs(promotion_rank - chess.square_rank(move.to_square))
    if ranks_to_promotion > 2:
        return 0.0

    projected = board.copy(stack=False)
    projected.remove_piece_at(move.from_square)
    projected.set_piece_at(move.to_square, chess.Piece(chess.PAWN, belief.color))
    file_bonus = _passed_pawn_file_bonus(projected, belief=belief, square=move.to_square)
    advance_bonus = (3 - ranks_to_promotion) * 70.0
    exposure_discount = 1.0 - min(0.85, outcome.exposed_piece_capture_probability)
    return (advance_bonus + file_bonus) * outcome.legal_probability * exposure_discount * weights.promotion_race_scale


def _informative_probe_penalty(
    *,
    outcome: RefereeOutcomeEstimate,
    landed_value: float,
    immediate_loss_penalty: float,
    checking_piece_vulnerability: float,
    weights: QuiescenceWeights,
) -> float:
    if outcome.legal_probability >= 0.55:
        return 0.0

    tactical_gain = max(0.0, outcome.expected_capture_value) + (outcome.check_probability * 180.0)
    risk = (
        immediate_loss_penalty
        + checking_piece_vulnerability
        + (outcome.illegal_probability * min(120.0, landed_value * 0.18))
    )
    return max(0.0, risk - tactical_gain) * weights.informative_probe_penalty_scale


def _event_capture_value(outcome: RefereeOutcomeEstimate) -> float:
    if outcome.capture_probability <= 0:
        return 0.0
    return max(0.0, outcome.expected_capture_value / max(outcome.capture_probability, 0.05))


def _landed_piece_value(*, move: chess.Move, piece: chess.Piece) -> float:
    if move.promotion:
        return PIECE_VALUES.get(move.promotion, GENERIC_OPPONENT_PIECE_VALUE)
    return PIECE_VALUES.get(piece.piece_type, GENERIC_OPPONENT_PIECE_VALUE)


def _passed_pawn_file_bonus(board: chess.Board, *, belief: BeliefState, square: chess.Square) -> float:
    file = chess.square_file(square)
    direction = 1 if belief.color == chess.WHITE else -1
    rank = chess.square_rank(square)
    bonus = 0.0
    for offset in (-1, 0, 1):
        check_file = file + offset
        if check_file < 0 or check_file > 7:
            continue
        for check_rank in range(rank + direction, 8 if direction > 0 else -1, direction):
            check_square = chess.square(check_file, check_rank)
            bonus -= min(1.0, belief.opponent_pawns[check_square]) * 22.0
    return max(-60.0, bonus + 45.0)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
