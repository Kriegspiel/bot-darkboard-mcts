"""Offline aggregate prior generation from completed Wild 16 archives."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
from datetime import UTC
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import chess

from darkboard_mcts.priors import PRIORS_SCHEMA_VERSION


DEFAULT_OPENING_PLIES = 8


def generate_priors_payload(
    games: Iterable[dict[str, Any]],
    *,
    opening_plies: int = DEFAULT_OPENING_PLIES,
    blend: float = 0.65,
) -> dict[str, Any]:
    """Generate reviewed priors from prepared completed Wild 16 archive docs."""

    aggregate = _Aggregate(opening_plies=max(0, opening_plies))
    for game in games:
        if _is_completed_wild16(game):
            aggregate.add_game(game)
    return aggregate.payload(blend=blend)


def read_archive_records(path: str | Path) -> list[dict[str, Any]]:
    """Read JSON, JSONL, or an object containing a top-level `games` list."""

    source = Path(path)
    text = source.read_text()
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            return [item for item in loaded if isinstance(item, dict)]
        if isinstance(loaded, dict):
            games = loaded.get("games")
            if isinstance(games, list):
                return [item for item in games if isinstance(item, dict)]
            return [loaded]

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        loaded = json.loads(line)
        if isinstance(loaded, dict):
            records.append(loaded)
    return records


class _Aggregate:
    def __init__(self, *, opening_plies: int) -> None:
        self.opening_plies = opening_plies
        self.games_analyzed = 0
        self.games_with_fen = 0
        self.games_with_moves = 0
        self.opening_samples = {"white": 0, "black": 0}
        self.king = {"white": [0.0] * 64, "black": [0.0] * 64}
        self.pawns = {"white": [0.0] * 64, "black": [0.0] * 64}
        self.pieces = {"white": [0.0] * 64, "black": [0.0] * 64}
        self.pawn_rank_counts = {"white": [0.0] * 8, "black": [0.0] * 8}
        self.pawn_file_counts = {"white": [0.0] * 8, "black": [0.0] * 8}
        self.capture_opportunities = 0
        self.recaptures = 0
        self.retaliations = 0
        self.capture_chains: list[int] = []

    def add_game(self, game: dict[str, Any]) -> None:
        self.games_analyzed += 1
        fens = _extract_full_fens(game)
        moves = _extract_move_stack(game)
        if not fens and moves:
            fens = _opening_fens_from_move_stack(moves, opening_plies=self.opening_plies)
        if fens:
            self.games_with_fen += 1
            self._add_opening_fens(fens)
        if moves:
            self.games_with_moves += 1
            self._add_move_stats(moves)

    def payload(self, *, blend: float) -> dict[str, Any]:
        return {
            "schema_version": PRIORS_SCHEMA_VERSION,
            "ruleset": "wild16",
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "blend": min(1.0, max(0.0, float(blend))),
            "games_analyzed": self.games_analyzed,
            "source": {
                "kind": "completed_wild16_archives",
                "games_with_fen": self.games_with_fen,
                "games_with_moves": self.games_with_moves,
                "opening_plies": self.opening_plies,
            },
            "opening": {
                side: {
                    "samples": self.opening_samples[side],
                    "king": _matrix_or_default(self.king[side]),
                    "pawns": _matrix_or_default(self.pawns[side]),
                    "pieces": _matrix_or_default(self.pieces[side]),
                }
                for side in ("white", "black")
            },
            "movement": {
                side: {
                    "pawn_rank_weights": _weights(self.pawn_rank_counts[side]),
                    "pawn_file_weights": _weights(self.pawn_file_counts[side]),
                }
                for side in ("white", "black")
            },
            "tactics": {
                "capture_opportunities": self.capture_opportunities,
                "recaptures": self.recaptures,
                "recapture_rate": _ratio(self.recaptures, self.capture_opportunities),
                "retaliations": self.retaliations,
                "retaliation_rate": _ratio(self.retaliations, self.capture_opportunities),
                "capture_chain_lengths": dict(sorted(Counter(self.capture_chains).items())),
                "capture_chain_length_average": _average(self.capture_chains),
            },
            "data_policy": {
                "aggregate_only": True,
                "completed_wild16_only": True,
                "per_opponent_modeling": False,
                "live_learning": False,
            },
        }

    def _add_opening_fens(self, fens: list[str]) -> None:
        for fen in fens[: self.opening_plies + 1]:
            try:
                board = chess.Board(fen)
            except ValueError:
                continue
            for color, side in ((chess.WHITE, "white"), (chess.BLACK, "black")):
                self.opening_samples[side] += 1
                for square, piece in board.piece_map().items():
                    if piece.color != color:
                        continue
                    if piece.piece_type == chess.KING:
                        self.king[side][square] += 1.0
                    elif piece.piece_type == chess.PAWN:
                        self.pawns[side][square] += 1.0
                    else:
                        self.pieces[side][square] += 1.0

    def _add_move_stats(self, move_stack: list[str]) -> None:
        board = chess.Board()
        previous_capture_square: chess.Square | None = None
        current_chain = 0
        for uci in move_stack:
            try:
                move = chess.Move.from_uci(uci)
            except ValueError:
                continue
            if move not in board.legal_moves:
                break
            piece = board.piece_at(move.from_square)
            if piece is None:
                break
            side = "white" if piece.color == chess.WHITE else "black"
            if piece.piece_type == chess.PAWN:
                rank = chess.square_rank(move.to_square)
                rank_index = rank if piece.color == chess.WHITE else 7 - rank
                self.pawn_rank_counts[side][rank_index] += 1.0
                self.pawn_file_counts[side][chess.square_file(move.to_square)] += 1.0
            is_capture = board.is_capture(move)
            if previous_capture_square is not None:
                self.capture_opportunities += 1
                if is_capture:
                    self.retaliations += 1
                    if move.to_square == previous_capture_square:
                        self.recaptures += 1
            if is_capture:
                current_chain += 1
                previous_capture_square = move.to_square
            else:
                if current_chain:
                    self.capture_chains.append(current_chain)
                current_chain = 0
                previous_capture_square = None
            board.push(move)
        if current_chain:
            self.capture_chains.append(current_chain)


def _is_completed_wild16(game: dict[str, Any]) -> bool:
    ruleset = str(game.get("rule_variant") or game.get("ruleset") or "").lower()
    state = str(game.get("state") or game.get("status") or "").lower()
    return ruleset == "wild16" and state == "completed"


def _extract_full_fens(game: dict[str, Any]) -> list[str]:
    fens: list[str] = []
    candidates = [
        game.get("initial_full_fen"),
        game.get("initial_fen"),
    ]
    engine_state = game.get("engine_state")
    if isinstance(engine_state, dict):
        game_state = engine_state.get("game_state")
        if isinstance(game_state, dict):
            candidates.append(game_state.get("initial_fen"))
    for value in candidates:
        if isinstance(value, str):
            fens.append(value)

    for item in _iter_move_records(game):
        replay = item.get("replay_fen")
        if isinstance(replay, dict):
            full = replay.get("full") or replay.get("full_fen")
            if isinstance(full, str):
                fens.append(full)
        full = item.get("full_fen")
        if isinstance(full, str):
            fens.append(full)
    return _dedupe_preserving_order(fens)


def _extract_move_stack(game: dict[str, Any]) -> list[str]:
    for value in (
        game.get("move_stack"),
        _nested_get(game, ("engine_state", "game_state", "move_stack")),
    ):
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]

    moves: list[str] = []
    for item in _iter_move_records(game):
        move_done = item.get("move_done")
        if move_done is False:
            continue
        uci = item.get("uci") or item.get("move_uci") or item.get("move")
        if isinstance(uci, str):
            moves.append(uci)
    return moves


def _opening_fens_from_move_stack(move_stack: list[str], *, opening_plies: int) -> list[str]:
    board = chess.Board()
    fens = [board.fen()]
    for uci in move_stack[:opening_plies]:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        board.push(move)
        fens.append(board.fen())
    return fens


def _iter_move_records(game: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in ("moves", "transcript", "attempts"):
        value = game.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            nested = value.get("moves")
            if isinstance(nested, list):
                records.extend(item for item in nested if isinstance(item, dict))
    return records


def _nested_get(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = source
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _matrix_or_default(values: list[float]) -> list[float]:
    if sum(values) <= 0:
        return [1.0] * 64
    return [round(value, 6) for value in values]


def _weights(values: list[float]) -> list[float]:
    if sum(values) <= 0:
        return [1.0] * len(values)
    average = sum(values) / len(values)
    if average <= 0:
        return [1.0] * len(values)
    return [round(max(0.05, value / average), 6) for value in values]


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator > 0 else 0.0


def _average(values: list[int]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate reviewed aggregate priors from completed Wild 16 archives.")
    parser.add_argument("input", help="JSON/JSONL archive export")
    parser.add_argument("output", help="path to write priors.json")
    parser.add_argument("--opening-plies", type=int, default=DEFAULT_OPENING_PLIES)
    parser.add_argument("--blend", type=float, default=0.65)
    args = parser.parse_args(argv)

    payload = generate_priors_payload(read_archive_records(args.input), opening_plies=args.opening_plies, blend=args.blend)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
