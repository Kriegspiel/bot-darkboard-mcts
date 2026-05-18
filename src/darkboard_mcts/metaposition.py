"""Coarse metaposition abstractions over public belief matrices."""

from __future__ import annotations

from dataclasses import dataclass, fields
from os import environ

import chess

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.outcome_model import GENERIC_OPPONENT_PIECE_VALUE
from darkboard_mcts.outcome_model import PIECE_VALUES
from darkboard_mcts.outcome_model import RefereeOutcomeEstimate


WEIGHT_ENV_PREFIX = "DARKBOARD_METAPOSITION_"


@dataclass(frozen=True)
class Metaposition:
    """Public-safe matrix abstraction for one coarse Kriegspiel state.

    The matrices are expected occupancies/control scores. They intentionally do
    not enumerate compatible hidden boards.
    """

    color: chess.Color
    own_occupancy: tuple[float, ...]
    own_pawns: tuple[float, ...]
    opponent_king: tuple[float, ...]
    opponent_pawns: tuple[float, ...]
    opponent_pieces: tuple[float, ...]
    opponent_occupancy: tuple[float, ...]
    own_control: tuple[float, ...]
    opponent_control: tuple[float, ...]
    open_files: tuple[float, ...]
    own_material_value: float
    opponent_material_value: float

    def opponent_occupancy_at(self, square: chess.Square) -> float:
        return self.opponent_occupancy[square] if 0 <= square < 64 else 0.0

    def possible_king_squares(self, *, threshold: float = 0.0) -> tuple[chess.Square, ...]:
        return _possible_squares(self.opponent_king, threshold=threshold)

    def possible_pawn_squares(self, *, threshold: float = 0.0) -> tuple[chess.Square, ...]:
        return _possible_squares(self.opponent_pawns, threshold=threshold)

    def possible_piece_squares(self, *, threshold: float = 0.0) -> tuple[chess.Square, ...]:
        return _possible_squares(self.opponent_pieces, threshold=threshold)

    def open_file_probability(self, file: int) -> float:
        if file < 0 or file > 7:
            return 0.0
        return self.open_files[file]


@dataclass(frozen=True)
class MetapositionWeights:
    material_balance_scale: float = 0.08
    pawn_advancement_scale: float = 1.15
    promotion_pressure_scale: float = 0.72
    open_file_scale: float = 1.0
    friendly_open_file_scale: float = 0.85
    controlled_squares_scale: float = 1.0
    king_edge_scale: float = 1.0
    checkmating_pressure_scale: float = 1.0
    max_adjustment: float = 520.0

    @classmethod
    def from_env(cls) -> "MetapositionWeights":
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
class MetapositionEstimate:
    material_balance: float = 0.0
    pawn_advancement: float = 0.0
    promotion_pressure: float = 0.0
    open_file_value: float = 0.0
    friendly_open_file_value: float = 0.0
    controlled_squares: float = 0.0
    king_edge_pressure: float = 0.0
    checkmating_pressure: float = 0.0
    adjustment: float = 0.0


def build_metaposition(belief: BeliefState, *, board: chess.Board) -> Metaposition:
    """Build a compact state abstraction from visible pieces and belief matrices."""

    king = _matrix(belief.opponent_king)
    pawns = _matrix(belief.opponent_pawns)
    pieces = _matrix(belief.opponent_pieces)
    opponent_occupancy = tuple(_clamp_probability(king[sq] + pawns[sq] + pieces[sq]) for sq in chess.SQUARES)
    own_occupancy = tuple(
        1.0 if (piece := board.piece_at(sq)) is not None and piece.color == belief.color else 0.0
        for sq in chess.SQUARES
    )
    own_pawns = tuple(
        1.0
        if (piece := board.piece_at(sq)) is not None
        and piece.color == belief.color
        and piece.piece_type == chess.PAWN
        else 0.0
        for sq in chess.SQUARES
    )
    return Metaposition(
        color=belief.color,
        own_occupancy=own_occupancy,
        own_pawns=own_pawns,
        opponent_king=king,
        opponent_pawns=pawns,
        opponent_pieces=pieces,
        opponent_occupancy=opponent_occupancy,
        own_control=_own_control(board=board, color=belief.color),
        opponent_control=_opponent_control(board=board, belief=belief, pawns=pawns, pieces=pieces, king=king),
        open_files=_open_files(board=board, color=belief.color, opponent_pawns=pawns),
        own_material_value=_own_material_value(board=board, color=belief.color),
        opponent_material_value=_opponent_material_value(pawns=pawns, pieces=pieces),
    )


def evaluate_metaposition(
    belief: BeliefState,
    *,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
    outcome: RefereeOutcomeEstimate,
    weights: MetapositionWeights | None = None,
) -> MetapositionEstimate:
    """Score the coarse metaposition after a modeled legal move."""

    weights = weights or MetapositionWeights.from_env()
    if outcome.legal_probability <= 0:
        return MetapositionEstimate()

    projected = _project_move(board=board, move=move, piece=piece)
    metaposition = build_metaposition(belief, board=projected)
    legality = outcome.legal_probability

    material_balance = _material_balance(metaposition) * weights.material_balance_scale * legality
    pawn_advancement = _pawn_advancement(metaposition) * weights.pawn_advancement_scale * legality
    promotion_pressure = _promotion_pressure(metaposition, board=projected) * weights.promotion_pressure_scale * legality
    open_file_value = _open_file_value(metaposition, board=projected) * weights.open_file_scale * legality
    friendly_open_file_value = (
        _friendly_open_file_value(metaposition, board=projected) * weights.friendly_open_file_scale * legality
    )
    controlled_squares = _controlled_squares(metaposition) * weights.controlled_squares_scale * legality
    king_edge_pressure = _king_edge_pressure(metaposition) * weights.king_edge_scale * legality
    checkmating_pressure = _checkmating_pressure(metaposition) * weights.checkmating_pressure_scale * legality
    adjustment = (
        material_balance
        + pawn_advancement
        + promotion_pressure
        + open_file_value
        + friendly_open_file_value
        + controlled_squares
        + king_edge_pressure
        + checkmating_pressure
    )
    adjustment = _clamp(adjustment, -weights.max_adjustment, weights.max_adjustment)
    return MetapositionEstimate(
        material_balance=material_balance,
        pawn_advancement=pawn_advancement,
        promotion_pressure=promotion_pressure,
        open_file_value=open_file_value,
        friendly_open_file_value=friendly_open_file_value,
        controlled_squares=controlled_squares,
        king_edge_pressure=king_edge_pressure,
        checkmating_pressure=checkmating_pressure,
        adjustment=adjustment,
    )


def _material_balance(metaposition: Metaposition) -> float:
    return metaposition.own_material_value - metaposition.opponent_material_value


def _pawn_advancement(metaposition: Metaposition) -> float:
    own_score = 0.0
    opponent_score = 0.0
    opponent = not metaposition.color
    for square in chess.SQUARES:
        rank = chess.square_rank(square)
        own_density = metaposition.own_pawns[square]
        if own_density:
            own_score += own_density * _pawn_progress(color=metaposition.color, rank=rank) * 8.0
        opponent_score += metaposition.opponent_pawns[square] * _pawn_progress(color=opponent, rank=rank) * 5.5
    return own_score - opponent_score


def _promotion_pressure(metaposition: Metaposition, *, board: chess.Board) -> float:
    own_pressure = 0.0
    opponent_pressure = 0.0
    opponent = not metaposition.color
    own_queens = 0
    for square, piece in board.piece_map().items():
        if piece.color != metaposition.color:
            continue
        if piece.piece_type == chess.QUEEN:
            own_queens += 1
        if piece.piece_type != chess.PAWN:
            continue
        ranks = _ranks_to_promotion(color=metaposition.color, square=square)
        if ranks <= 3:
            file = chess.square_file(square)
            own_pressure += (4 - ranks) * 44.0
            own_pressure += metaposition.open_file_probability(file) * 26.0
            own_pressure += _passed_pawn_probability(metaposition, square=square) * 34.0

    own_pressure += max(0, own_queens - 1) * 95.0
    for square, density in enumerate(metaposition.opponent_pawns):
        if density <= 0:
            continue
        ranks = _ranks_to_promotion(color=opponent, square=square)
        if ranks <= 3:
            opponent_pressure += density * (4 - ranks) * 34.0
    return own_pressure - opponent_pressure


def _open_file_value(metaposition: Metaposition, *, board: chess.Board) -> float:
    value = 0.0
    for square, piece in board.piece_map().items():
        if piece.color != metaposition.color or piece.piece_type not in {chess.ROOK, chess.QUEEN}:
            continue
        file = chess.square_file(square)
        piece_scale = 30.0 if piece.piece_type == chess.ROOK else 18.0
        rank_pressure = 1.0 + (_pawn_progress(color=metaposition.color, rank=chess.square_rank(square)) * 0.08)
        value += metaposition.open_file_probability(file) * piece_scale * rank_pressure
    return value


def _friendly_open_file_value(metaposition: Metaposition, *, board: chess.Board) -> float:
    value = 0.0
    for square, piece in board.piece_map().items():
        if piece.color != metaposition.color or piece.piece_type != chess.PAWN:
            continue
        file = chess.square_file(square)
        progress = _pawn_progress(color=metaposition.color, rank=chess.square_rank(square))
        pass_probability = _passed_pawn_probability(metaposition, square=square)
        value += progress * pass_probability * (10.0 + (metaposition.open_file_probability(file) * 8.0))
    return value


def _controlled_squares(metaposition: Metaposition) -> float:
    value = 0.0
    for square in chess.SQUARES:
        own = min(2.0, metaposition.own_control[square])
        opponent = min(2.0, metaposition.opponent_control[square])
        value += (own - opponent) * _square_control_weight(square)
    return value * 5.0


def _king_edge_pressure(metaposition: Metaposition) -> float:
    value = 0.0
    for square, density in enumerate(metaposition.opponent_king):
        if density <= 0:
            continue
        value += density * _king_edge_factor(square) * 26.0
    return value


def _checkmating_pressure(metaposition: Metaposition) -> float:
    value = 0.0
    for square, density in enumerate(metaposition.opponent_king):
        if density <= 0:
            continue
        zone = _king_zone(square)
        own_pressure = sum(min(1.0, metaposition.own_control[item]) for item in zone)
        opponent_relief = sum(min(1.0, metaposition.opponent_control[item]) for item in zone)
        confinement = 1.0 + _king_edge_factor(square)
        value += density * max(0.0, own_pressure - (0.35 * opponent_relief)) * confinement * 11.0
    return value


def _project_move(*, board: chess.Board, move: chess.Move, piece: chess.Piece) -> chess.Board:
    projected = board.copy(stack=False)
    projected.remove_piece_at(move.from_square)
    projected.remove_piece_at(move.to_square)
    promoted_type = move.promotion or piece.piece_type
    projected.set_piece_at(move.to_square, chess.Piece(promoted_type, piece.color))
    if piece.piece_type == chess.KING and abs(chess.square_file(move.to_square) - chess.square_file(move.from_square)) == 2:
        _project_castling_rook(projected, move=move, color=piece.color)
    return projected


def _project_castling_rook(board: chess.Board, *, move: chess.Move, color: chess.Color) -> None:
    rank = chess.square_rank(move.from_square)
    if chess.square_file(move.to_square) == 6:
        rook_from = chess.square(7, rank)
        rook_to = chess.square(5, rank)
    else:
        rook_from = chess.square(0, rank)
        rook_to = chess.square(3, rank)
    rook = board.piece_at(rook_from)
    if rook == chess.Piece(chess.ROOK, color):
        board.remove_piece_at(rook_from)
        board.set_piece_at(rook_to, rook)


def _own_control(*, board: chess.Board, color: chess.Color) -> tuple[float, ...]:
    control = [0.0] * 64
    for square, piece in board.piece_map().items():
        if piece.color != color:
            continue
        for target in board.attacks(square):
            control[target] += 1.0
    return tuple(control)


def _opponent_control(
    *,
    board: chess.Board,
    belief: BeliefState,
    pawns: tuple[float, ...],
    pieces: tuple[float, ...],
    king: tuple[float, ...],
) -> tuple[float, ...]:
    opponent = not belief.color
    control = [0.0] * 64
    for square, density in enumerate(pawns):
        if density <= 0:
            continue
        for target in chess.SquareSet(chess.BB_PAWN_ATTACKS[opponent][square]):
            control[target] += density
    for square, density in enumerate(pieces):
        if density <= 0:
            continue
        for target in chess.SQUARES:
            control[target] += density * _generic_piece_attack_factor(board=board, source=square, target=target)
    for square, density in enumerate(king):
        if density <= 0:
            continue
        for target in chess.SQUARES:
            if chess.square_distance(square, target) == 1:
                control[target] += density * 0.35
    return tuple(control)


def _generic_piece_attack_factor(*, board: chess.Board, source: chess.Square, target: chess.Square) -> float:
    if source == target:
        return 0.0
    if _is_knight_move(source, target):
        return 0.24
    if _is_slider_line(source, target):
        between = tuple(chess.SquareSet(chess.between(source, target)))
        visible_blockers = sum(1 for square in between if board.piece_at(square) is not None)
        return 0.32 / (1.0 + visible_blockers)
    if chess.square_distance(source, target) == 1:
        return 0.08
    return 0.0


def _open_files(*, board: chess.Board, color: chess.Color, opponent_pawns: tuple[float, ...]) -> tuple[float, ...]:
    files: list[float] = []
    for file in range(8):
        own_pawn_count = sum(
            1
            for rank in range(8)
            if board.piece_at(chess.square(file, rank)) == chess.Piece(chess.PAWN, color)
        )
        if own_pawn_count:
            files.append(0.0)
            continue
        expected_opponent_pawns = sum(opponent_pawns[chess.square(file, rank)] for rank in range(8))
        files.append(max(0.0, 1.0 - min(1.0, expected_opponent_pawns)))
    return tuple(files)


def _own_material_value(*, board: chess.Board, color: chess.Color) -> float:
    return sum(
        PIECE_VALUES.get(piece.piece_type, GENERIC_OPPONENT_PIECE_VALUE)
        for piece in board.piece_map().values()
        if piece.color == color
    )


def _opponent_material_value(*, pawns: tuple[float, ...], pieces: tuple[float, ...]) -> float:
    return (sum(pawns) * PIECE_VALUES[chess.PAWN]) + (sum(pieces) * GENERIC_OPPONENT_PIECE_VALUE)


def _passed_pawn_probability(metaposition: Metaposition, *, square: chess.Square) -> float:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    direction = 1 if metaposition.color == chess.WHITE else -1
    expected_blockers = 0.0
    for file_offset in (-1, 0, 1):
        check_file = file + file_offset
        if check_file < 0 or check_file > 7:
            continue
        for check_rank in range(rank + direction, 8 if direction > 0 else -1, direction):
            expected_blockers += metaposition.opponent_pawns[chess.square(check_file, check_rank)]
    return max(0.0, 1.0 - min(1.0, expected_blockers))


def _pawn_progress(*, color: chess.Color, rank: int) -> int:
    start_rank = 1 if color == chess.WHITE else 6
    direction = 1 if color == chess.WHITE else -1
    return max(0, (rank - start_rank) * direction)


def _ranks_to_promotion(*, color: chess.Color, square: chess.Square) -> int:
    promotion_rank = 7 if color == chess.WHITE else 0
    return abs(promotion_rank - chess.square_rank(square))


def _square_control_weight(square: chess.Square) -> float:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    center_distance = abs(file - 3.5) + abs(rank - 3.5)
    return max(0.35, 2.6 - (0.42 * center_distance))


def _king_edge_factor(square: chess.Square) -> float:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    factor = 0.0
    if file in {0, 7}:
        factor += 1.0
    if rank in {0, 7}:
        factor += 1.0
    return factor


def _king_zone(square: chess.Square) -> tuple[chess.Square, ...]:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    zone: list[chess.Square] = []
    for file_delta in (-1, 0, 1):
        for rank_delta in (-1, 0, 1):
            zone_file = file + file_delta
            zone_rank = rank + rank_delta
            if 0 <= zone_file <= 7 and 0 <= zone_rank <= 7:
                zone.append(chess.square(zone_file, zone_rank))
    return tuple(zone)


def _matrix(values: tuple[float, ...]) -> tuple[float, ...]:
    if len(values) != 64:
        return (0.0,) * 64
    return tuple(max(0.0, value) for value in values)


def _possible_squares(values: tuple[float, ...], *, threshold: float) -> tuple[chess.Square, ...]:
    return tuple(square for square, value in enumerate(values) if value > threshold)


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


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))
