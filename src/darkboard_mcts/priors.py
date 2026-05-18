"""Hand-built opponent priors for the Darkboard-inspired bot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import chess


@dataclass(frozen=True)
class OpponentPriors:
    king: tuple[float, ...]
    pawns: tuple[float, ...]
    pieces: tuple[float, ...]


def opponent_priors(*, visible_fen: str, color: chess.Color, material_summary: dict[str, Any]) -> OpponentPriors:
    """Build coarse 8x8 probability/count matrices from public state.

    The matrices are expected counts, not single-piece probability distributions:
    king sums to 1, pawns sum to the public number of remaining opponent pawns,
    and pieces sum to the remaining non-pawn opponent pieces.
    """

    board = _visible_board(visible_fen)
    occupied = set(board.piece_map()) if board is not None else set()
    opponent = not color
    remaining, pawns = _opponent_material_counts(opponent=opponent, material_summary=material_summary)
    pieces = max(0, remaining - pawns - 1)

    king_weights = _king_weights(opponent=opponent, occupied=occupied)
    pawn_weights = _pawn_weights(opponent=opponent, occupied=occupied)
    piece_weights = _piece_weights(opponent=opponent, occupied=occupied)
    return OpponentPriors(
        king=_normalize(king_weights, 1.0 if remaining > 0 else 0.0),
        pawns=_normalize(pawn_weights, float(pawns)),
        pieces=_normalize(piece_weights, float(pieces)),
    )


def _visible_board(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _opponent_material_counts(*, opponent: chess.Color, material_summary: dict[str, Any]) -> tuple[int, int]:
    side_name = "white" if opponent == chess.WHITE else "black"
    side = material_summary.get(side_name) if isinstance(material_summary, dict) else None
    if not isinstance(side, dict):
        return 16, 8

    remaining = _bounded_int(side.get("pieces_remaining"), default=16, minimum=0, maximum=16)
    pawns_captured = side.get("pawns_captured")
    if pawns_captured is None:
        pawns = min(8, remaining)
    else:
        pawns = 8 - _bounded_int(pawns_captured, default=0, minimum=0, maximum=8)
        pawns = min(max(0, pawns), remaining)
    return remaining, pawns


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _king_weights(*, opponent: chess.Color, occupied: set[chess.Square]) -> list[float]:
    home_rank = 0 if opponent == chess.WHITE else 7
    weights: list[float] = []
    for square in chess.SQUARES:
        if square in occupied:
            weights.append(0.0)
            continue
        rank = chess.square_rank(square)
        file = chess.square_file(square)
        home_distance = abs(rank - home_rank)
        edge_pressure = 1.35 if file in {0, 7} else 1.0
        weights.append(max(0.25, 3.5 - home_distance) * edge_pressure)
    return weights


def _pawn_weights(*, opponent: chess.Color, occupied: set[chess.Square]) -> list[float]:
    start_rank = 1 if opponent == chess.WHITE else 6
    promotion_rank = 7 if opponent == chess.WHITE else 0
    weights: list[float] = []
    for square in chess.SQUARES:
        if square in occupied:
            weights.append(0.0)
            continue
        rank = chess.square_rank(square)
        if rank in {0, 7}:
            weights.append(0.0)
            continue
        progress = abs(rank - start_rank)
        promotion_distance = abs(rank - promotion_rank)
        weights.append(max(0.2, 3.0 - (0.55 * progress)) + (0.15 / max(1, promotion_distance)))
    return weights


def _piece_weights(*, opponent: chess.Color, occupied: set[chess.Square]) -> list[float]:
    home_rank = 0 if opponent == chess.WHITE else 7
    weights: list[float] = []
    for square in chess.SQUARES:
        if square in occupied:
            weights.append(0.0)
            continue
        rank = chess.square_rank(square)
        file = chess.square_file(square)
        home_bias = max(0.3, 3.0 - (0.7 * abs(rank - home_rank)))
        centrality = 1.0 + (0.2 * (3.5 - abs(file - 3.5)))
        weights.append(home_bias * centrality)
    return weights


def _normalize(weights: list[float], total: float) -> tuple[float, ...]:
    if total <= 0:
        return (0.0,) * 64
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return (0.0,) * 64
    scale = total / weight_sum
    return tuple(weight * scale for weight in weights)
