"""One-move public referee outcome model for Darkboard-style scoring."""

from __future__ import annotations

from dataclasses import dataclass, fields
from os import environ

import chess

from darkboard_mcts.belief import BeliefState


PIECE_VALUES = {
    chess.PAWN: 100.0,
    chess.KNIGHT: 320.0,
    chess.BISHOP: 330.0,
    chess.ROOK: 500.0,
    chess.QUEEN: 900.0,
    chess.KING: 0.0,
}
GENERIC_OPPONENT_PIECE_VALUE = 360.0
WEIGHT_ENV_PREFIX = "DARKBOARD_MODEL_"


@dataclass(frozen=True)
class OutcomeModelWeights:
    """Tunable scoring weights around the public referee outcome model."""

    capture_value_scale: float = 1.0
    check_pressure: float = 180.0
    recapture_bonus: float = 260.0
    illegal_attempt_penalty: float = 70.0
    safety_penalty_scale: float = 0.28
    checking_piece_vulnerability_scale: float = 0.16
    development_scale: float = 1.0
    legal_development_floor: float = 0.35

    @classmethod
    def from_env(cls) -> "OutcomeModelWeights":
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
class RefereeOutcomeEstimate:
    """Probabilities for the public/referee messages relevant to one attempt."""

    legal_probability: float
    path_block_probability: float
    king_safety_risk: float
    target_occupancy_probability: float
    pawn_capture_probability: float
    piece_capture_probability: float
    capture_probability: float
    expected_capture_value: float
    check_probability: float
    recapture_probability: float
    exposed_piece_capture_probability: float
    checking_piece_vulnerability: float

    @property
    def illegal_probability(self) -> float:
        return 1.0 - self.legal_probability


def estimate_referee_outcome(
    belief: BeliefState,
    *,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
    latest_capture_square: chess.Square | None = None,
) -> RefereeOutcomeEstimate:
    """Estimate public referee outcomes for one possible attempt."""

    target = move.to_square
    path_block_probability = _path_block_probability(belief, move=move, piece=piece)
    pawn_capture_probability = min(1.0, _density_at(belief.opponent_pawns, target))
    piece_capture_probability = min(1.0, _density_at(belief.opponent_pieces, target))
    target_king_probability = min(1.0, _density_at(belief.opponent_king, target))
    target_occupancy = _clamp_probability(
        pawn_capture_probability + piece_capture_probability + target_king_probability
    )
    is_recapture_target = latest_capture_square is not None and latest_capture_square == target
    exposed_piece_capture_probability = _opponent_attack_probability(belief, board=board, target=target)
    king_safety_risk = _king_safety_risk(
        belief,
        board=board,
        move=move,
        piece=piece,
        target_attack_probability=exposed_piece_capture_probability,
    )

    if piece.piece_type == chess.PAWN and chess.square_file(move.from_square) == chess.square_file(target):
        capture_probability = 0.0
        expected_capture_value = -target_occupancy * 80.0
        legal_probability = (1.0 - path_block_probability) * (1.0 - target_occupancy)
    else:
        capture_probability = _clamp_probability(pawn_capture_probability + piece_capture_probability)
        expected_capture_value = (
            pawn_capture_probability * PIECE_VALUES[chess.PAWN]
            + piece_capture_probability * GENERIC_OPPONENT_PIECE_VALUE
        )
        if is_recapture_target:
            capture_probability = max(capture_probability, 0.75)
            expected_capture_value = max(expected_capture_value, GENERIC_OPPONENT_PIECE_VALUE * 0.75)
        if piece.piece_type == chess.PAWN:
            legal_probability = (1.0 - path_block_probability) * capture_probability
        else:
            legal_probability = (1.0 - path_block_probability) * (1.0 - target_king_probability)

    legal_probability *= 1.0 - king_safety_risk
    legal_probability = _clamp_probability(legal_probability)

    check_probability = _check_probability(belief, board=board, move=move, piece=piece)
    recapture_probability = _recapture_probability(
        latest_capture_square=latest_capture_square,
        target=target,
        exposed_piece_capture_probability=exposed_piece_capture_probability,
    )
    checking_piece_vulnerability = check_probability * exposed_piece_capture_probability

    return RefereeOutcomeEstimate(
        legal_probability=legal_probability,
        path_block_probability=path_block_probability,
        king_safety_risk=king_safety_risk,
        target_occupancy_probability=target_occupancy,
        pawn_capture_probability=pawn_capture_probability,
        piece_capture_probability=piece_capture_probability,
        capture_probability=capture_probability,
        expected_capture_value=expected_capture_value,
        check_probability=check_probability,
        recapture_probability=recapture_probability,
        exposed_piece_capture_probability=exposed_piece_capture_probability,
        checking_piece_vulnerability=checking_piece_vulnerability,
    )


def _path_block_probability(belief: BeliefState, *, move: chess.Move, piece: chess.Piece) -> float:
    if piece.piece_type == chess.PAWN:
        direction = 1 if piece.color == chess.WHITE else -1
        if abs(chess.square_rank(move.to_square) - chess.square_rank(move.from_square)) == 2:
            intermediate_rank = chess.square_rank(move.from_square) + direction
            intermediate = chess.square(chess.square_file(move.from_square), intermediate_rank)
            return _occupancy_probability(belief, intermediate)
        return 0.0

    if piece.piece_type not in {chess.BISHOP, chess.ROOK, chess.QUEEN}:
        return 0.0

    clear_probability = 1.0
    for square in chess.SquareSet(chess.between(move.from_square, move.to_square)):
        clear_probability *= 1.0 - _occupancy_probability(belief, square)
    return _clamp_probability(1.0 - clear_probability)


def _king_safety_risk(
    belief: BeliefState,
    *,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
    target_attack_probability: float,
) -> float:
    if piece.piece_type == chess.KING:
        return min(0.85, target_attack_probability)

    own_king = board.king(belief.color)
    if own_king is None:
        return 0.0

    projected = board.copy(stack=False)
    projected.remove_piece_at(move.from_square)
    return min(0.35, _opponent_attack_probability(belief, board=projected, target=own_king) * 0.35)


def _check_probability(
    belief: BeliefState,
    *,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
) -> float:
    attacks = _attacks_after_move(board=board, move=move, piece=piece)
    return min(1.0, sum(_density_at(belief.opponent_king, square) for square in attacks))


def _recapture_probability(
    *,
    latest_capture_square: chess.Square | None,
    target: chess.Square,
    exposed_piece_capture_probability: float,
) -> float:
    if latest_capture_square is not None and latest_capture_square == target:
        return max(0.75, exposed_piece_capture_probability)
    return 0.0


def _opponent_attack_probability(
    belief: BeliefState,
    *,
    board: chess.Board,
    target: chess.Square,
) -> float:
    opponent = not belief.color
    attack_score = 0.0

    for square, density in enumerate(belief.opponent_pawns):
        if density <= 0:
            continue
        if target in chess.SquareSet(chess.BB_PAWN_ATTACKS[opponent][square]):
            attack_score += density

    for square, density in enumerate(belief.opponent_pieces):
        if density <= 0:
            continue
        attack_score += density * _generic_piece_attack_factor(board=board, source=square, target=target)

    for square, density in enumerate(belief.opponent_king):
        if density <= 0:
            continue
        if chess.square_distance(square, target) == 1:
            attack_score += density * 0.25

    return _clamp_probability(attack_score)


def _generic_piece_attack_factor(*, board: chess.Board, source: chess.Square, target: chess.Square) -> float:
    if source == target:
        return 0.0

    if _is_knight_move(source, target):
        return 0.35

    if _is_slider_line(source, target):
        between = tuple(chess.SquareSet(chess.between(source, target)))
        visible_blockers = sum(1 for square in between if board.piece_at(square) is not None)
        return 0.55 / (1.0 + visible_blockers)

    if chess.square_distance(source, target) == 1:
        return 0.12

    return 0.0


def _attacks_after_move(*, board: chess.Board, move: chess.Move, piece: chess.Piece) -> chess.SquareSet:
    if piece.piece_type == chess.PAWN:
        return chess.SquareSet(chess.BB_PAWN_ATTACKS[piece.color][move.to_square])

    projected = board.copy(stack=False)
    projected.remove_piece_at(move.from_square)
    promoted_type = move.promotion or piece.piece_type
    projected.set_piece_at(move.to_square, chess.Piece(promoted_type, piece.color))
    return projected.attacks(move.to_square)


def _occupancy_probability(belief: BeliefState, square: chess.Square) -> float:
    return _clamp_probability(
        _density_at(belief.opponent_king, square)
        + _density_at(belief.opponent_pawns, square)
        + _density_at(belief.opponent_pieces, square)
    )


def _density_at(matrix: tuple[float, ...], square: chess.Square) -> float:
    return matrix[square] if 0 <= square < len(matrix) else 0.0


def _is_knight_move(source: chess.Square, target: chess.Square) -> bool:
    file_delta = abs(chess.square_file(source) - chess.square_file(target))
    rank_delta = abs(chess.square_rank(source) - chess.square_rank(target))
    return (file_delta, rank_delta) in {(1, 2), (2, 1)}


def _is_slider_line(source: chess.Square, target: chess.Square) -> bool:
    file_delta = abs(chess.square_file(source) - chess.square_file(target))
    rank_delta = abs(chess.square_rank(source) - chess.square_rank(target))
    return file_delta == 0 or rank_delta == 0 or file_delta == rank_delta


def _clamp_probability(value: float) -> float:
    return min(1.0, max(0.0, value))
