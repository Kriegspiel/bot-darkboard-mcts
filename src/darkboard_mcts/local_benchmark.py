"""Local Wild 16 benchmark runner for Darkboard MCTS.

The runner uses the same public-state boundary as the API bot, but drives the
`ks-game` Wild 16 engine in-process so benchmark batches are reproducible and
do not depend on production lobby cooldowns.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
from typing import Any, TypeVar

import chess

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.evidence import apply_move_result_evidence
from darkboard_mcts.evidence import restore_belief_snapshot
from darkboard_mcts.search import ranked_actions


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BOT_USERNAME = "darkboardmcts"
DEFAULT_RANDOM_USERNAME = "randobot"
DEFAULT_SIMPLE_USERNAME = "simpleheuristics"
DEFAULT_SELF_USERNAME = "darkboardmcts-self"
DEFAULT_MATCHUPS = (DEFAULT_RANDOM_USERNAME, DEFAULT_SIMPLE_USERNAME, DEFAULT_SELF_USERNAME)
DEFAULT_TIME_BUDGET_SECONDS = 1.0
DEFAULT_MCTS_MAX_ITERATIONS = 384
DEFAULT_SELECTION_RULE = "value"
DEFAULT_MAX_PLIES = 700
BENCHMARK_RUNNER_VERSION = 1
T = TypeVar("T")


def _ensure_ks_game_importable() -> None:
    if importlib.util.find_spec("kriegspiel") is not None:
        return

    candidates: list[Path] = []
    env_path = os.environ.get("DARKBOARD_KS_GAME_PATH")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    if REPO_ROOT.parent.name == "_worktrees":
        candidates.append(REPO_ROOT.parent.parent / "ks-game")
    candidates.append(REPO_ROOT.parent / "ks-game")

    for candidate in candidates:
        if (candidate / "kriegspiel").is_dir():
            sys.path.insert(0, str(candidate))
            return


_ensure_ks_game_importable()

from kriegspiel.move import CapturedPieceAnnouncement  # noqa: E402
from kriegspiel.move import KriegspielMove  # noqa: E402
from kriegspiel.move import QuestionAnnouncement  # noqa: E402
from kriegspiel.move import SpecialCaseAnnouncement  # noqa: E402
from kriegspiel.serialization import serialize_berkeley_game  # noqa: E402
from kriegspiel.wild16 import Wild16Game  # noqa: E402


@dataclass(frozen=True)
class PlayerSpec:
    username: str
    policy: str
    commit: str | None = None


@dataclass(frozen=True)
class MatchupSpec:
    opponent: PlayerSpec
    target_games: int
    time_budget_seconds: float


@dataclass
class GameContext:
    game_code: str
    benchmark_bot: PlayerSpec
    white: PlayerSpec
    black: PlayerSpec
    rng: random.Random
    bot_beliefs: dict[str, dict[str, Any]]


def run_benchmark_games(
    *,
    games_per_matchup: int,
    bot_commit: str | None,
    random_commit: str | None,
    simple_commit: str | None,
    engine_commit: str | None,
    seed: int,
    matchups: Sequence[str] = DEFAULT_MATCHUPS,
    time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
    mcts_max_iterations: int = DEFAULT_MCTS_MAX_ITERATIONS,
    selection_rule: str = DEFAULT_SELECTION_RULE,
    max_plies: int = DEFAULT_MAX_PLIES,
    workers: int = 1,
    benchmark_name: str = "Darkboard MCTS Wild 16 local benchmark",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run a local benchmark matrix and return archive-like records plus a manifest."""

    benchmark_bot = PlayerSpec(DEFAULT_BOT_USERNAME, "darkboard", bot_commit)
    matchup_specs = _matchup_specs(
        matchups=matchups,
        games_per_matchup=games_per_matchup,
        bot_commit=bot_commit,
        random_commit=random_commit,
        simple_commit=simple_commit,
        time_budget_seconds=time_budget_seconds,
    )
    manifest = _manifest(
        benchmark_bot=benchmark_bot,
        matchups=matchup_specs,
        engine_commit=engine_commit,
        seed=seed,
        mcts_max_iterations=mcts_max_iterations,
        selection_rule=selection_rule,
        max_plies=max_plies,
        benchmark_name=benchmark_name,
    )

    jobs: list[dict[str, Any]] = []
    for matchup_index, matchup in enumerate(matchup_specs):
        for game_index in range(games_per_matchup):
            bot_as_white = game_index % 2 == 0
            white = benchmark_bot if bot_as_white else matchup.opponent
            black = matchup.opponent if bot_as_white else benchmark_bot
            jobs.append(
                {
                    "game_code": _game_code(matchup.opponent.username, game_index + 1),
                    "benchmark_bot": benchmark_bot,
                    "white": white,
                    "black": black,
                    "seed": seed + (matchup_index * 100_000) + game_index,
                    "time_budget_seconds": time_budget_seconds,
                    "mcts_max_iterations": mcts_max_iterations,
                    "selection_rule": selection_rule,
                    "engine_commit": engine_commit,
                    "max_plies": max_plies,
                }
            )

    if workers <= 1:
        records = [_play_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            records = list(executor.map(_play_job, jobs, chunksize=1))
    return records, manifest


def _play_job(job: dict[str, Any]) -> dict[str, Any]:
    with _temporary_darkboard_env(
        time_budget_seconds=float(job["time_budget_seconds"]),
        max_iterations=int(job["mcts_max_iterations"]),
        selection_rule=str(job["selection_rule"]),
    ):
        return play_local_game(**job)


def play_local_game(
    *,
    game_code: str,
    benchmark_bot: PlayerSpec,
    white: PlayerSpec,
    black: PlayerSpec,
    seed: int,
    time_budget_seconds: float,
    mcts_max_iterations: int,
    selection_rule: str,
    engine_commit: str | None,
    max_plies: int = DEFAULT_MAX_PLIES,
) -> dict[str, Any]:
    """Play one local Wild 16 game and return an archive-shaped record."""

    game = Wild16Game()
    ctx = GameContext(
        game_code=game_code,
        benchmark_bot=benchmark_bot,
        white=white,
        black=black,
        rng=random.Random(seed),
        bot_beliefs={},
    )
    move_records: list[dict[str, Any]] = []
    completed_plies = 0
    terminal_reason: str | None = None
    terminal_winner: str | None = None

    while not bool(game.game_over) and completed_plies < max_plies:
        color = _color_name(game.turn)
        player = white if color == "white" else black
        state = _state_payload(
            game,
            game_code=game_code,
            viewer_color=color,
            state="active",
            move_number=completed_plies + 1,
            move_records=move_records,
        )
        attempts = _rank_attempts(player, state=state, ctx=ctx)
        if not attempts:
            terminal_reason = "no_attempts"
            break

        completed_this_turn = False
        for uci in attempts:
            result = _attempt_move(game, uci)
            record = _move_record(
                ply=len(move_records) + 1,
                color=color,
                uci=uci,
                result=result,
            )
            move_records.append(record)
            if player.policy == "darkboard":
                _update_darkboard_belief(ctx, color=color, uci=uci, result=result)
            if result.get("move_done"):
                completed_plies += 1
                completed_this_turn = True
                terminal_winner, terminal_reason = _terminal_result(result.get("special_announcement"))
                break

        if bool(game.game_over):
            break
        if not completed_this_turn:
            continue

    if not bool(game.game_over) and completed_plies >= max_plies:
        terminal_reason = "adjudicated_max_plies"
        terminal_winner = None

    if terminal_reason is None:
        terminal_winner, terminal_reason = _terminal_result(None)

    benchmark = {
        "runner": "darkboard-run-local-benchmark",
        "runner_version": BENCHMARK_RUNNER_VERSION,
        "collection_method": "local_ks_game_wild16",
        "bot_commit": benchmark_bot.commit,
        "opponent_commit": _opponent_for_game(ctx).commit,
        "engine_commit": engine_commit,
        "time_budget_seconds": time_budget_seconds,
        "mcts_max_iterations": mcts_max_iterations,
        "selection_rule": selection_rule,
        "seed": seed,
        "max_plies": max_plies,
    }
    return {
        "game_code": game_code,
        "state": "completed",
        "status": "completed",
        "rule_variant": "wild16",
        "ruleset": "wild16",
        "white": _player_payload(white),
        "black": _player_payload(black),
        "result": {"winner": terminal_winner, "reason": terminal_reason},
        "turn_count": completed_plies,
        "move_count": completed_plies,
        "moves": move_records,
        "engine_state": serialize_berkeley_game(game),
        "benchmark": benchmark,
    }


def _matchup_specs(
    *,
    matchups: Sequence[str],
    games_per_matchup: int,
    bot_commit: str | None,
    random_commit: str | None,
    simple_commit: str | None,
    time_budget_seconds: float,
) -> list[MatchupSpec]:
    out: list[MatchupSpec] = []
    for raw in matchups:
        opponent = raw.strip().lower()
        if not opponent:
            continue
        if opponent in {"random", DEFAULT_RANDOM_USERNAME}:
            spec = PlayerSpec(DEFAULT_RANDOM_USERNAME, "random", random_commit)
        elif opponent in {"simple", "simpleheuristics", DEFAULT_SIMPLE_USERNAME}:
            spec = PlayerSpec(DEFAULT_SIMPLE_USERNAME, "simple", simple_commit)
        elif opponent in {"self", DEFAULT_SELF_USERNAME}:
            spec = PlayerSpec(DEFAULT_SELF_USERNAME, "darkboard", bot_commit)
        else:
            raise ValueError(f"unsupported matchup: {raw}")
        out.append(MatchupSpec(opponent=spec, target_games=games_per_matchup, time_budget_seconds=time_budget_seconds))
    return out


def _manifest(
    *,
    benchmark_bot: PlayerSpec,
    matchups: Sequence[MatchupSpec],
    engine_commit: str | None,
    seed: int,
    mcts_max_iterations: int,
    selection_rule: str,
    max_plies: int,
    benchmark_name: str,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "benchmark_name": benchmark_name,
        "generated_at": generated_at,
        "bot": {"username": benchmark_bot.username, "commit": benchmark_bot.commit},
        "required_matchups": [
            {
                "opponent": matchup.opponent.username,
                "opponent_commit": matchup.opponent.commit,
                "time_budget_seconds": matchup.time_budget_seconds,
                "target_games": matchup.target_games,
            }
            for matchup in matchups
        ],
        "collection": {
            "method": "local_ks_game_wild16",
            "runner": "darkboard-run-local-benchmark",
            "runner_version": BENCHMARK_RUNNER_VERSION,
            "engine_commit": engine_commit,
            "seed": seed,
            "mcts_max_iterations": mcts_max_iterations,
            "selection_rule": selection_rule,
            "max_plies": max_plies,
            "color_assignment": "alternating; benchmark bot is white on even-indexed games per matchup",
            "raw_archives_committed": False,
        },
    }


def _rank_attempts(player: PlayerSpec, *, state: dict[str, Any], ctx: GameContext) -> tuple[str, ...]:
    allowed = tuple(move for move in state.get("allowed_moves", []) if isinstance(move, str))
    if player.policy == "random":
        moves = list(allowed)
        ctx.rng.shuffle(moves)
        return tuple(moves)
    if player.policy == "simple":
        return tuple(_simple_heuristic_attempts(state, rng=ctx.rng))
    if player.policy == "darkboard":
        belief = BeliefState.from_api_state(state, ruleset="wild16")
        belief = restore_belief_snapshot(belief, ctx.bot_beliefs.get(str(state.get("your_color"))))
        ctx.bot_beliefs[str(state.get("your_color"))] = _serialize_belief(belief)
        return ranked_actions(belief)
    raise ValueError(f"unsupported policy: {player.policy}")


def _update_darkboard_belief(ctx: GameContext, *, color: str, uci: str, result: dict[str, Any]) -> None:
    snapshot = ctx.bot_beliefs.get(color)
    if not isinstance(snapshot, dict):
        return
    belief = BeliefState(
        color=chess.WHITE if color == "white" else chess.BLACK,
        visible_fen=str(snapshot.get("your_fen") or ""),
        legal_actions=tuple(snapshot.get("legal_actions") or ()),
        ruleset=str(snapshot.get("ruleset") or "wild16"),
        ply=int(snapshot.get("ply") or 1),
        game_id=str(snapshot.get("game_id") or ctx.game_code),
        possible_actions=tuple(snapshot.get("possible_actions") or ()),
        observed_referee_log_size=int(snapshot.get("observed_referee_log_size") or 0),
        opponent_king=tuple(float(value) for value in snapshot.get("opponent_king", (0.0,) * 64)),
        opponent_pawns=tuple(float(value) for value in snapshot.get("opponent_pawns", (0.0,) * 64)),
        opponent_pieces=tuple(float(value) for value in snapshot.get("opponent_pieces", (0.0,) * 64)),
    )
    ctx.bot_beliefs[color] = _serialize_belief(apply_move_result_evidence(belief, uci=uci, result=result))


def _serialize_belief(belief: BeliefState) -> dict[str, Any]:
    return {
        "game_id": belief.game_id,
        "ruleset": belief.ruleset,
        "color": "white" if belief.color == chess.WHITE else "black",
        "ply": belief.ply,
        "your_fen": belief.your_fen,
        "legal_actions": list(belief.legal_actions),
        "possible_actions": list(belief.possible_actions),
        "observed_referee_log_size": belief.observed_referee_log_size,
        "opponent_king": list(belief.opponent_king),
        "opponent_pawns": list(belief.opponent_pawns),
        "opponent_pieces": list(belief.opponent_pieces),
    }


def _state_payload(
    game: Wild16Game,
    *,
    game_code: str,
    viewer_color: str,
    state: str,
    move_number: int,
    move_records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    turn = _color_name(game.turn)
    allowed_moves = []
    if state == "active" and turn == viewer_color:
        allowed_moves = sorted(
            option.chess_move.uci()
            for option in game.possible_to_ask
            if option.question_type == QuestionAnnouncement.COMMON and option.chess_move is not None
        )
    return {
        "game_id": game_code,
        "state": state,
        "rule_variant": "wild16",
        "turn": turn,
        "move_number": move_number,
        "your_color": viewer_color,
        "your_fen": _visible_fen(game, viewer_color),
        "allowed_moves": allowed_moves,
        "material_summary": _public_material_summary(game),
        "referee_log": _viewer_referee_log(move_records, viewer_color=viewer_color),
        "referee_turns": [],
        "possible_actions": ["move"] if allowed_moves else [],
    }


def _attempt_move(game: Wild16Game, move_uci: str) -> dict[str, Any]:
    try:
        chess_move = chess.Move.from_uci(move_uci)
    except ValueError:
        return {
            "move_done": False,
            "announcement": "INVALID_UCI",
            "special_announcement": None,
            "capture_square": None,
            "captured_piece_announcement": None,
            "promotion_announced": None,
            "next_turn_pawn_tries": None,
            "turn": _color_name(game.turn),
            "game_over": bool(game.game_over),
        }

    answer = game.ask_for(KriegspielMove(QuestionAnnouncement.COMMON, chess_move))
    special = answer.special_announcement
    captured_piece = answer.captured_piece_announcement
    return {
        "move_done": bool(answer.move_done),
        "announcement": answer.main_announcement.name,
        "special_announcement": None if special in {None, SpecialCaseAnnouncement.NONE} else special.name,
        "capture_square": chess.square_name(answer.capture_at_square) if answer.capture_at_square is not None else None,
        "captured_piece_announcement": (
            captured_piece.name if isinstance(captured_piece, CapturedPieceAnnouncement) else None
        ),
        "promotion_announced": True if answer.promotion_announced else None,
        "next_turn_pawn_tries": answer.next_turn_pawn_tries,
        "turn": _color_name(game.turn),
        "game_over": bool(game.game_over),
    }


def _move_record(*, ply: int, color: str, uci: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ply": ply,
        "color": color,
        "question_type": "COMMON",
        "uci": uci,
        "announcement": result.get("announcement"),
        "special_announcement": result.get("special_announcement"),
        "capture_square": result.get("capture_square"),
        "captured_piece_announcement": result.get("captured_piece_announcement"),
        "promotion_announced": result.get("promotion_announced"),
        "next_turn_pawn_tries": result.get("next_turn_pawn_tries"),
        "move_done": bool(result.get("move_done")),
    }


def _viewer_referee_log(move_records: Sequence[dict[str, Any]], *, viewer_color: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in move_records:
        if record.get("color") != viewer_color and not bool(record.get("move_done")):
            continue
        out.append(
            {
                "ply": record.get("ply"),
                "color": record.get("color"),
                "announcement": record.get("announcement"),
                "special_announcement": record.get("special_announcement"),
                "capture_square": record.get("capture_square"),
                "captured_piece_announcement": record.get("captured_piece_announcement"),
                "move_done": record.get("move_done"),
            }
        )
    return out


def _visible_fen(game: Wild16Game, color: str) -> str:
    board = game._board.copy(stack=False)  # noqa: SLF001
    viewer = chess.WHITE if color == "white" else chess.BLACK
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is not None and piece.color != viewer:
            board.remove_piece_at(square)
    turn = "w" if game.turn == chess.WHITE else "b"
    return f"{board.board_fen()} {turn} - - 0 1"


def _public_material_summary(game: Wild16Game) -> dict[str, dict[str, int | None]]:
    summary = game.public_material_summary
    return {
        "white": _material_side_payload(summary.white),
        "black": _material_side_payload(summary.black),
    }


def _material_side_payload(side: Any) -> dict[str, int | None]:
    return {
        "pieces_remaining": int(getattr(side, "pieces_remaining", 16)),
        "pawns_captured": getattr(side, "pawns_captured", None),
    }


def _simple_heuristic_attempts(state: dict[str, Any], *, rng: random.Random) -> tuple[str, ...]:
    special_moves = _priority_moves(state)
    if special_moves:
        return tuple(special_moves)

    sequence: list[str] = []
    excluded: set[str] = set()
    while True:
        ranked_pieces = [square for square, _moves in _piece_move_groups(state.get("allowed_moves", [])) if square not in excluded]
        piece = _choose_geometric_item(ranked_pieces, rng=rng)
        if piece is None:
            return tuple(sequence)
        sequence.extend(_moves_for_piece(state, piece))
        excluded.add(piece)


def _priority_moves(state: dict[str, Any]) -> list[str]:
    recaptures = _recapture_moves(state)
    if recaptures:
        return recaptures
    promotions = [move for move in state.get("allowed_moves", []) if isinstance(move, str) and len(move) >= 5 and move[4].lower() == "q"]
    return _sort_moves_longest_first(promotions)


def _recapture_moves(state: dict[str, Any]) -> list[str]:
    capture_square = _last_opponent_capture_square(state)
    if not capture_square:
        return []
    return _sort_moves_longest_first(
        [
            move
            for move in state.get("allowed_moves", [])
            if isinstance(move, str) and len(move) >= 4 and move[2:4].lower() == capture_square
        ]
    )


def _last_opponent_capture_square(state: dict[str, Any]) -> str | None:
    our_color = str(state.get("your_color") or "").strip().lower()
    opponent_color = "black" if our_color == "white" else "white"
    for entry in reversed(state.get("referee_log") or []):
        if not isinstance(entry, dict) or entry.get("color") != opponent_color:
            continue
        capture_square = entry.get("capture_square")
        if isinstance(capture_square, str) and capture_square.strip():
            return capture_square.strip().lower()
    return None


def _piece_move_groups(allowed_moves: Iterable[str]) -> list[tuple[str, list[str]]]:
    grouped: dict[str, list[str]] = {}
    for move in _sort_moves_longest_first(list(allowed_moves)):
        if isinstance(move, str) and len(move) >= 4:
            grouped.setdefault(move[:2].lower(), []).append(move)
    return sorted(grouped.items(), key=lambda item: (-_move_distance(item[1][0]), item[0]))


def _moves_for_piece(state: dict[str, Any], square: str) -> list[str]:
    target_square = square.strip().lower()
    return [move for origin, moves in _piece_move_groups(state.get("allowed_moves", [])) if origin == target_square for move in moves]


def _sort_moves_longest_first(allowed_moves: Iterable[str]) -> list[str]:
    valid_moves = [move for move in allowed_moves if isinstance(move, str) and len(move) >= 4]
    return sorted(valid_moves, key=lambda move: (-_move_distance(move), move))


def _move_distance(uci: str) -> int:
    if len(uci) < 4:
        return -1
    start = _square_coords(uci[:2].lower())
    end = _square_coords(uci[2:4].lower())
    if start is None or end is None:
        return -1
    return max(abs(end[0] - start[0]), abs(end[1] - start[1]))


def _square_coords(square: str) -> tuple[int, int] | None:
    if len(square) != 2 or square[0] < "a" or square[0] > "h" or square[1] < "1" or square[1] > "8":
        return None
    return ord(square[0]) - ord("a"), int(square[1]) - 1


def _choose_geometric_item(items: Sequence[T], *, rng: random.Random) -> T | None:
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    roll = rng.random()
    cumulative = 0.0
    weight = 0.5
    for index, item in enumerate(items):
        if index == len(items) - 1:
            return item
        cumulative += weight
        if roll < cumulative:
            return item
        weight /= 2
    return items[-1]


def _terminal_result(special: Any) -> tuple[str | None, str | None]:
    if special == "CHECKMATE_WHITE_WINS":
        return "white", "checkmate"
    if special == "CHECKMATE_BLACK_WINS":
        return "black", "checkmate"
    if special == "DRAW_STALEMATE":
        return None, "stalemate"
    if special == "DRAW_INSUFFICIENT":
        return None, "insufficient_material"
    if special == "DRAW_TOOMANYREVERSIBLEMOVES":
        return None, "too_many_reversible_moves"
    return None, None


def _opponent_for_game(ctx: GameContext) -> PlayerSpec:
    return ctx.black if ctx.white.username == ctx.benchmark_bot.username else ctx.white


def _player_payload(player: PlayerSpec) -> dict[str, str]:
    return {
        "user_id": player.username,
        "username": player.username,
        "role": "bot",
    }


def _color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def _game_code(opponent: str, index: int) -> str:
    prefixes = {
        DEFAULT_RANDOM_USERNAME: "DBR",
        DEFAULT_SIMPLE_USERNAME: "DBS",
        DEFAULT_SELF_USERNAME: "DBD",
    }
    prefix = prefixes.get(opponent, "DBX")
    return f"{prefix}{index:04d}"


@contextmanager
def _temporary_darkboard_env(
    *,
    time_budget_seconds: float,
    max_iterations: int,
    selection_rule: str,
) -> Iterable[None]:
    keys = {
        "DARKBOARD_MCTS_TIME_BUDGET_SECONDS": str(time_budget_seconds),
        "DARKBOARD_MCTS_MAX_ITERATIONS": str(max_iterations),
        "DARKBOARD_MCTS_SELECTION_RULE": selection_rule,
    }
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ.update(keys)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def write_jsonl(path: str | Path, records: Sequence[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Wild 16 benchmark games for Darkboard MCTS.")
    parser.add_argument("output", help="JSONL archive output path")
    parser.add_argument("--manifest-output", help="optional manifest JSON output path")
    parser.add_argument("--games-per-matchup", type=int, default=100)
    parser.add_argument("--matchups", default=",".join(DEFAULT_MATCHUPS))
    parser.add_argument("--seed", type=int, default=20260519)
    parser.add_argument("--bot-commit")
    parser.add_argument("--random-commit")
    parser.add_argument("--simple-commit")
    parser.add_argument("--engine-commit")
    parser.add_argument("--time-budget-seconds", type=float, default=DEFAULT_TIME_BUDGET_SECONDS)
    parser.add_argument("--mcts-max-iterations", type=int, default=DEFAULT_MCTS_MAX_ITERATIONS)
    parser.add_argument("--selection-rule", choices=("visits", "value"), default=DEFAULT_SELECTION_RULE)
    parser.add_argument("--max-plies", type=int, default=DEFAULT_MAX_PLIES)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--benchmark-name", default="Darkboard MCTS Wild 16 local benchmark")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    records, manifest = run_benchmark_games(
        games_per_matchup=max(1, args.games_per_matchup),
        bot_commit=args.bot_commit,
        random_commit=args.random_commit,
        simple_commit=args.simple_commit,
        engine_commit=args.engine_commit,
        seed=args.seed,
        matchups=tuple(item.strip() for item in args.matchups.split(",") if item.strip()),
        time_budget_seconds=max(0.0, args.time_budget_seconds),
        mcts_max_iterations=max(1, args.mcts_max_iterations),
        selection_rule=args.selection_rule,
        max_plies=max(1, args.max_plies),
        workers=max(1, args.workers),
        benchmark_name=args.benchmark_name,
    )
    write_jsonl(args.output, records)
    if args.manifest_output:
        write_json(args.manifest_output, manifest)
    completed = sum(1 for record in records if record.get("state") == "completed")
    adjudicated = sum(1 for record in records if (record.get("result") or {}).get("reason") == "adjudicated_max_plies")
    print(
        json.dumps(
            {
                "records": len(records),
                "completed": completed,
                "adjudicated_max_plies": adjudicated,
                "output": str(args.output),
                "manifest_output": args.manifest_output,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
