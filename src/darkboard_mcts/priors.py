"""Opponent priors for the Darkboard-inspired bot."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
from typing import Any

import chess


logger = logging.getLogger(__name__)
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRIORS_PATH = PACKAGE_ROOT / "priors.json"
PRIORS_SCHEMA_VERSION = 1
PRIORS_ENV_PATH = "DARKBOARD_PRIORS_PATH"


@dataclass(frozen=True)
class OpponentPriors:
    king: tuple[float, ...]
    pawns: tuple[float, ...]
    pieces: tuple[float, ...]


@dataclass(frozen=True)
class LearnedSidePriors:
    king: tuple[float, ...]
    pawns: tuple[float, ...]
    pieces: tuple[float, ...]


@dataclass(frozen=True)
class PawnMovementPriors:
    pawn_rank_weights: tuple[float, ...]
    pawn_file_weights: tuple[float, ...]


@dataclass(frozen=True)
class AggregatePriors:
    schema_version: int
    ruleset: str
    games_analyzed: int
    blend: float
    opening: dict[str, LearnedSidePriors]
    movement: dict[str, PawnMovementPriors]
    tactics: dict[str, Any]


def opponent_priors(*, visible_fen: str, color: chess.Color, material_summary: dict[str, Any]) -> OpponentPriors:
    """Build coarse 8x8 probability/count matrices from public state.

    The matrices are expected counts, not single-piece probability distributions:
    king sums to 1, pawns sum to the public number of remaining opponent pawns,
    and pieces sum to the remaining non-pawn opponent pieces.
    """

    board = _visible_board(visible_fen)
    occupied = set(board.piece_map()) if board is not None else set()
    opponent = not color
    opponent_name = "white" if opponent == chess.WHITE else "black"
    remaining, pawns = _opponent_material_counts(opponent=opponent, material_summary=material_summary)
    pieces = max(0, remaining - pawns - 1)

    king_weights = _king_weights(opponent=opponent, occupied=occupied)
    pawn_weights = _pawn_weights(opponent=opponent, occupied=occupied)
    piece_weights = _piece_weights(opponent=opponent, occupied=occupied)
    learned = load_aggregate_priors()
    if learned is not None:
        side_priors = learned.opening.get(opponent_name)
        if side_priors is not None:
            king_weights = _blend_weights(
                king_weights,
                _mask_weights(side_priors.king, occupied=occupied),
                blend=learned.blend,
            )
            pawn_weights = _blend_weights(
                pawn_weights,
                _apply_pawn_movement(
                    _mask_weights(side_priors.pawns, occupied=occupied),
                    movement=learned.movement.get(opponent_name),
                    color=opponent,
                ),
                blend=learned.blend,
            )
            piece_weights = _blend_weights(
                piece_weights,
                _mask_weights(side_priors.pieces, occupied=occupied),
                blend=learned.blend,
            )
    return OpponentPriors(
        king=_normalize(king_weights, 1.0 if remaining > 0 else 0.0),
        pawns=_normalize(pawn_weights, float(pawns)),
        pieces=_normalize(piece_weights, float(pieces)),
    )


def priors_path() -> Path:
    configured = os.environ.get(PRIORS_ENV_PATH)
    return Path(configured).expanduser() if configured else DEFAULT_PRIORS_PATH


def clear_aggregate_priors_cache() -> None:
    _load_aggregate_priors_cached.cache_clear()


def load_aggregate_priors(path: str | Path | None = None) -> AggregatePriors | None:
    resolved = Path(path).expanduser() if path is not None else priors_path()
    try:
        stat = resolved.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("could not stat priors file %s: %s", resolved, exc)
        return None
    return _load_aggregate_priors_cached(str(resolved), stat.st_mtime_ns)


@lru_cache(maxsize=8)
def _load_aggregate_priors_cached(path: str, mtime_ns: int) -> AggregatePriors | None:
    del mtime_ns
    priors_file = Path(path)
    try:
        payload = json.loads(priors_file.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ignoring malformed priors file %s: %s", priors_file, exc)
        return None

    try:
        priors = _parse_aggregate_priors(payload)
    except ValueError as exc:
        logger.warning("ignoring invalid priors file %s: %s", priors_file, exc)
        return None
    logger.info("loaded aggregate priors from %s (%s games)", priors_file, priors.games_analyzed)
    return priors


def _parse_aggregate_priors(payload: Any) -> AggregatePriors:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    schema_value = payload.get("schema_version")
    if isinstance(schema_value, bool):
        raise ValueError(f"unsupported schema_version {schema_value!r}")
    try:
        schema_version = int(schema_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported schema_version {schema_value!r}") from exc
    if schema_version != PRIORS_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {payload.get('schema_version')!r}")
    ruleset = str(payload.get("ruleset") or "")
    if ruleset != "wild16":
        raise ValueError("ruleset must be 'wild16'")
    opening_payload = payload.get("opening")
    if not isinstance(opening_payload, dict):
        raise ValueError("opening must be an object")
    opening: dict[str, LearnedSidePriors] = {}
    for side in ("white", "black"):
        side_payload = opening_payload.get(side)
        if not isinstance(side_payload, dict):
            continue
        opening[side] = LearnedSidePriors(
            king=_parse_matrix(side_payload.get("king"), name=f"opening.{side}.king"),
            pawns=_parse_matrix(side_payload.get("pawns"), name=f"opening.{side}.pawns"),
            pieces=_parse_matrix(side_payload.get("pieces"), name=f"opening.{side}.pieces"),
        )
    if not opening:
        raise ValueError("opening must include at least one side")

    movement_payload = payload.get("movement")
    movement: dict[str, PawnMovementPriors] = {}
    if isinstance(movement_payload, dict):
        for side in ("white", "black"):
            side_payload = movement_payload.get(side)
            if not isinstance(side_payload, dict):
                continue
            movement[side] = PawnMovementPriors(
                pawn_rank_weights=_parse_weights(side_payload.get("pawn_rank_weights"), length=8, default=1.0),
                pawn_file_weights=_parse_weights(side_payload.get("pawn_file_weights"), length=8, default=1.0),
            )

    blend = _float_value(payload.get("blend"), default=0.65, minimum=0.0, maximum=1.0)
    games_analyzed = _bounded_int(payload.get("games_analyzed"), default=0, minimum=0, maximum=1_000_000_000)
    tactics = payload.get("tactics") if isinstance(payload.get("tactics"), dict) else {}
    return AggregatePriors(
        schema_version=schema_version,
        ruleset=ruleset,
        games_analyzed=games_analyzed,
        blend=blend,
        opening=opening,
        movement=movement,
        tactics=tactics,
    )


def _parse_matrix(value: Any, *, name: str) -> tuple[float, ...]:
    parsed = _parse_weights(value, length=64, default=0.0)
    if sum(parsed) <= 0:
        raise ValueError(f"{name} must contain positive weights")
    return parsed


def _parse_weights(value: Any, *, length: int, default: float) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        return (default,) * length
    weights: list[float] = []
    for item in value:
        weights.append(_float_value(item, default=default, minimum=0.0, maximum=1_000_000.0))
    return tuple(weights)


def _float_value(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


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


def _mask_weights(weights: tuple[float, ...], *, occupied: set[chess.Square]) -> list[float]:
    return [0.0 if square in occupied else max(0.0, weights[square]) for square in chess.SQUARES]


def _blend_weights(base: list[float], learned: list[float], *, blend: float) -> list[float]:
    if len(learned) != 64 or sum(learned) <= 0:
        return base
    return [
        ((1.0 - blend) * max(0.0, base_value)) + (blend * max(0.0, learned_value))
        for base_value, learned_value in zip(base, learned, strict=True)
    ]


def _apply_pawn_movement(
    weights: list[float],
    *,
    movement: PawnMovementPriors | None,
    color: chess.Color,
) -> list[float]:
    if movement is None:
        return weights
    adjusted: list[float] = []
    for square, value in enumerate(weights):
        rank = chess.square_rank(square)
        file = chess.square_file(square)
        rank_index = rank if color == chess.WHITE else 7 - rank
        adjusted.append(value * movement.pawn_rank_weights[rank_index] * movement.pawn_file_weights[file])
    return adjusted


def _normalize(weights: list[float], total: float) -> tuple[float, ...]:
    if total <= 0:
        return (0.0,) * 64
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return (0.0,) * 64
    scale = total / weight_sum
    return tuple(weight * scale for weight in weights)
