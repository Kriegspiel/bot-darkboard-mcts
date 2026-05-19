"""Benchmark report generation for completed Wild 16 archive exports."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from darkboard_mcts.prior_generation import read_archive_records


BENCHMARK_SCHEMA_VERSION = 1
DEFAULT_BOT_USERNAME = "darkboardmcts"


@dataclass(frozen=True)
class BenchmarkRequirement:
    opponent: str
    target_games: int = 0
    opponent_commit: str | None = None
    time_budget_seconds: float | None = None
    provider_available: bool = True
    label: str = ""


@dataclass(frozen=True)
class AttemptStats:
    attempts: int = 0
    illegal_attempts: int = 0
    completed_moves: int = 0


@dataclass(frozen=True)
class GameSummary:
    game_id: str
    opponent: str
    opponent_role: str
    play_as: str
    outcome: str
    reason: str | None
    turn_count: int
    time_budget_seconds: float | None
    bot_commit: str | None
    opponent_commit: str | None
    attempts: AttemptStats


def generate_benchmark_report(
    games: Iterable[dict[str, Any]],
    *,
    manifest: dict[str, Any] | None = None,
    bot_username: str = DEFAULT_BOT_USERNAME,
    bot_commit: str | None = None,
) -> dict[str, Any]:
    """Generate an aggregate benchmark report from completed Wild 16 archives."""

    parsed_manifest = _parse_manifest(manifest or {})
    bot_username = str(_nested_get(manifest or {}, ("bot", "username")) or bot_username or DEFAULT_BOT_USERNAME)
    bot_commit = _string_or_none(_nested_get(manifest or {}, ("bot", "commit"))) or bot_commit

    archive_records = list(games)
    summaries: list[GameSummary] = []
    skipped = Counter()
    for game in archive_records:
        if not _is_completed_wild16(game):
            skipped["not_completed_wild16"] += 1
            continue
        summary = _summarize_game(game, bot_username=bot_username)
        if summary is None:
            skipped["bot_not_in_game"] += 1
            continue
        summaries.append(_apply_manifest_defaults(summary, parsed_manifest))

    report = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "benchmark_name": str((manifest or {}).get("benchmark_name") or "Darkboard MCTS benchmark"),
        "ruleset": "wild16",
        "bot": {
            "username": bot_username,
            "commit": bot_commit or _first_present(summary.bot_commit for summary in summaries),
        },
        "source": {
            "archive_records": len(archive_records),
            "completed_wild16_games": len(summaries),
            "skipped": dict(sorted(skipped.items())),
        },
        "overall": _aggregate_summaries(summaries),
        "matchups": _matchup_rows(summaries),
        "coverage": _coverage(parsed_manifest, summaries),
        "collection": _collection_metadata(manifest or {}),
        "failure_modes": _failure_modes(summaries),
        "games": [_game_payload(summary) for summary in summaries],
        "data_policy": {
            "completed_wild16_only": True,
            "aggregate_report_only": True,
            "hidden_board_data_required": False,
            "strength_claim_requires_complete_coverage": True,
        },
    }
    return report


def load_manifest(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text())
    return payload if isinstance(payload, dict) else {}


def render_markdown_report(report: dict[str, Any]) -> str:
    bot = report.get("bot") if isinstance(report.get("bot"), dict) else {}
    overall = report.get("overall") if isinstance(report.get("overall"), dict) else {}
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    lines = [
        f"# {report.get('benchmark_name') or 'Darkboard MCTS benchmark'}",
        "",
        f"- Generated: `{report.get('generated_at')}`",
        f"- Bot: `{bot.get('username') or DEFAULT_BOT_USERNAME}`",
        f"- Bot commit: `{bot.get('commit') or 'unknown'}`",
        f"- Ruleset: `{report.get('ruleset') or 'wild16'}`",
        f"- Coverage complete: `{coverage.get('complete')}`",
        "",
        "## Summary",
        "",
        "| Games | W | L | D | Win rate | Illegal attempt rate | Avg tries / completed move | Avg turns | Timeout rate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {overall.get('games', 0)} | {overall.get('wins', 0)} | {overall.get('losses', 0)} | "
            f"{overall.get('draws', 0)} | {_percent(overall.get('win_rate', 0.0))} | "
            f"{_percent(overall.get('illegal_attempt_rate', 0.0))} | "
            f"{_fixed(overall.get('average_tries_per_completed_move', 0.0))} | "
            f"{_fixed(overall.get('average_turns', 0.0))} | {_percent(overall.get('timeout_rate', 0.0))} |"
        ),
        "",
        "## Matchups",
        "",
        "| Opponent | Opponent commit | Time budget | Games | W-L-D | Illegal rate | Avg tries | Avg turns | Timeout rate |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("matchups", []):
        lines.append(
            f"| `{row['opponent']}` | `{row.get('opponent_commit') or 'unknown'}` | "
            f"{_time_budget(row.get('time_budget_seconds'))} | {row['games']} | "
            f"{row['wins']}-{row['losses']}-{row['draws']} | {_percent(row['illegal_attempt_rate'])} | "
            f"{_fixed(row['average_tries_per_completed_move'])} | {_fixed(row['average_turns'])} | "
            f"{_percent(row['timeout_rate'])} |"
        )

    requirements = coverage.get("requirements") if isinstance(coverage.get("requirements"), list) else []
    if requirements:
        lines.extend(
            [
                "",
                "## Coverage",
                "",
                "| Opponent | Target games | Matched games | Time budget | Status |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for row in requirements:
            lines.append(
                f"| `{row['opponent']}` | {row['target_games']} | {row['matched_games']} | "
                f"{_time_budget(row.get('time_budget_seconds'))} | `{row['status']}` |"
            )

    collection = report.get("collection") if isinstance(report.get("collection"), dict) else {}
    if collection:
        lines.extend(
            [
                "",
                "## Collection",
                "",
                f"- Method: `{collection.get('method') or 'unknown'}`",
                f"- Runner: `{collection.get('runner') or 'unknown'}`",
                f"- Engine commit: `{collection.get('engine_commit') or 'unknown'}`",
                f"- Seed: `{collection.get('seed') if collection.get('seed') is not None else 'unknown'}`",
                f"- MCTS max iterations: `{collection.get('mcts_max_iterations') if collection.get('mcts_max_iterations') is not None else 'unknown'}`",
                f"- Selection rule: `{collection.get('selection_rule') or 'unknown'}`",
                f"- Max plies: `{collection.get('max_plies') if collection.get('max_plies') is not None else 'unknown'}`",
                f"- Raw archives committed: `{collection.get('raw_archives_committed')}`",
            ]
        )

    failure_modes = report.get("failure_modes") if isinstance(report.get("failure_modes"), list) else []
    lines.extend(["", "## Failure Modes", ""])
    if failure_modes:
        lines.extend(f"- `{row['reason']}`: {row['count']}" for row in failure_modes)
    else:
        lines.append("- none observed")

    lines.extend(
        [
            "",
            "## Data Policy",
            "",
            "- Includes only completed Wild 16 games involving the benchmark bot.",
            "- Uses aggregate report data; no per-opponent modeling is produced.",
            "- Treat incomplete coverage as a blocker for public strength claims.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _parse_manifest(payload: dict[str, Any]) -> list[BenchmarkRequirement]:
    raw = payload.get("required_matchups") or payload.get("matchups") or []
    if not isinstance(raw, list):
        return []
    requirements: list[BenchmarkRequirement] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        opponent = str(item.get("opponent") or item.get("username") or "").strip()
        if not opponent:
            continue
        requirements.append(
            BenchmarkRequirement(
                opponent=opponent,
                target_games=_int_value(item.get("target_games"), default=0, minimum=0),
                opponent_commit=_string_or_none(item.get("opponent_commit") or item.get("commit")),
                time_budget_seconds=_float_or_none(item.get("time_budget_seconds")),
                provider_available=_bool_value(item.get("provider_available"), default=True),
                label=str(item.get("label") or ""),
            )
        )
    return requirements


def _is_completed_wild16(game: dict[str, Any]) -> bool:
    ruleset = str(game.get("rule_variant") or game.get("ruleset") or "").lower()
    state = str(game.get("state") or game.get("status") or "").lower()
    return ruleset == "wild16" and state == "completed"


def _summarize_game(game: dict[str, Any], *, bot_username: str) -> GameSummary | None:
    play_as = _bot_color(game, bot_username=bot_username)
    if play_as is None:
        return None
    opponent_color = "black" if play_as == "white" else "white"
    opponent = game.get(opponent_color) if isinstance(game.get(opponent_color), dict) else {}
    result = game.get("result") if isinstance(game.get("result"), dict) else {}
    winner = result.get("winner")
    reason = _result_reason(game)
    attempts = _attempt_stats(game, color=play_as)
    metadata = _benchmark_metadata(game)
    return GameSummary(
        game_id=str(game.get("game_code") or game.get("_id") or ""),
        opponent=str(opponent.get("username") or "unknown").strip() or "unknown",
        opponent_role=str(opponent.get("role") or "unknown").strip() or "unknown",
        play_as=play_as,
        outcome=_outcome_for_bot(winner=winner, play_as=play_as),
        reason=reason,
        turn_count=_turn_count(game),
        time_budget_seconds=_float_or_none(metadata.get("time_budget_seconds")),
        bot_commit=_string_or_none(metadata.get("bot_commit")),
        opponent_commit=_string_or_none(metadata.get("opponent_commit")),
        attempts=attempts,
    )


def _apply_manifest_defaults(summary: GameSummary, requirements: list[BenchmarkRequirement]) -> GameSummary:
    for requirement in requirements:
        if requirement.opponent.lower() != summary.opponent.lower():
            continue
        if requirement.time_budget_seconds is not None and summary.time_budget_seconds not in {None, requirement.time_budget_seconds}:
            continue
        return GameSummary(
            game_id=summary.game_id,
            opponent=summary.opponent,
            opponent_role=summary.opponent_role,
            play_as=summary.play_as,
            outcome=summary.outcome,
            reason=summary.reason,
            turn_count=summary.turn_count,
            time_budget_seconds=summary.time_budget_seconds
            if summary.time_budget_seconds is not None
            else requirement.time_budget_seconds,
            bot_commit=summary.bot_commit,
            opponent_commit=summary.opponent_commit or requirement.opponent_commit,
            attempts=summary.attempts,
        )
    return summary


def _bot_color(game: dict[str, Any], *, bot_username: str) -> str | None:
    target = bot_username.lower()
    for color in ("white", "black"):
        player = game.get(color)
        if isinstance(player, dict) and str(player.get("username") or "").lower() == target:
            return color
    return None


def _benchmark_metadata(game: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        game.get("benchmark"),
        game.get("benchmark_metadata"),
        _nested_get(game, ("metadata", "benchmark")),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _collection_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    collection = manifest.get("collection")
    return dict(collection) if isinstance(collection, dict) else {}


def _attempt_stats(game: dict[str, Any], *, color: str) -> AttemptStats:
    attempts = _scoresheet_attempts(game, color=color)
    if not attempts:
        attempts = _public_history_attempts(game, color=color)
    total = len(attempts)
    illegal = sum(1 for item in attempts if _is_illegal_attempt(item))
    completed = sum(1 for item in attempts if bool(item.get("move_done")))
    return AttemptStats(attempts=total, illegal_attempts=illegal, completed_moves=completed)


def _scoresheet_attempts(game: dict[str, Any], *, color: str) -> list[dict[str, Any]]:
    scoresheet = _nested_get(game, ("engine_state", "game_state", f"{color}_scoresheet"))
    if not isinstance(scoresheet, dict):
        scoresheet = _nested_get(game, (f"{color}_scoresheet",))
    if not isinstance(scoresheet, dict):
        return []
    attempts: list[dict[str, Any]] = []
    for turn in scoresheet.get("moves_own") or []:
        if not isinstance(turn, list):
            continue
        for pair in turn:
            item = _scoresheet_pair_to_attempt(pair)
            if item is not None:
                attempts.append(item)
    return attempts


def _scoresheet_pair_to_attempt(pair: Any) -> dict[str, Any] | None:
    if isinstance(pair, dict):
        question = pair.get("question") if isinstance(pair.get("question"), dict) else {}
        answer = pair.get("answer") if isinstance(pair.get("answer"), dict) else {}
    elif isinstance(pair, list) and len(pair) == 2:
        question = pair[0] if isinstance(pair[0], dict) else {}
        answer = pair[1] if isinstance(pair[1], dict) else {}
    else:
        return None

    question_type = str(question.get("question_type") or "").upper()
    uci = question.get("move_uci") or question.get("chess_move")
    if question_type and question_type != "COMMON":
        return None
    if not isinstance(uci, str):
        return None

    announcement = answer.get("main_announcement") or answer.get("announcement")
    return {
        "uci": uci,
        "announcement": announcement,
        "move_done": _move_done(answer),
    }


def _public_history_attempts(game: dict[str, Any], *, color: str) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for key in ("moves", "attempts"):
        value = game.get(key)
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict) or item.get("color") != color:
                    continue
                if str(item.get("question_type") or "COMMON").upper() != "COMMON":
                    continue
                if not isinstance(item.get("uci"), str):
                    continue
                attempts.append(
                    {
                        "uci": item.get("uci"),
                        "announcement": item.get("announcement") or item.get("main_announcement"),
                        "move_done": bool(item.get("move_done", False)),
                    }
                )
    return attempts


def _move_done(answer: dict[str, Any]) -> bool:
    if "move_done" in answer:
        return bool(answer.get("move_done"))
    announcement = str(answer.get("main_announcement") or answer.get("announcement") or "")
    return announcement not in {"ILLEGAL_MOVE", "NONSENSE", "NONE", ""}


def _is_illegal_attempt(item: dict[str, Any]) -> bool:
    announcement = str(item.get("announcement") or "")
    return announcement == "ILLEGAL_MOVE" and not bool(item.get("move_done"))


def _turn_count(game: dict[str, Any]) -> int:
    for key in ("turn_count", "move_count"):
        value = _int_value(game.get(key), default=0, minimum=0)
        if value > 0:
            return value
    moves = game.get("moves")
    if isinstance(moves, list):
        return sum(1 for move in moves if isinstance(move, dict) and bool(move.get("move_done")))
    move_stack = _nested_get(game, ("engine_state", "game_state", "move_stack"))
    return len(move_stack) if isinstance(move_stack, list) else 0


def _result_reason(game: dict[str, Any]) -> str | None:
    result = game.get("result") if isinstance(game.get("result"), dict) else {}
    reason = result.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    for move in reversed(game.get("moves") or []):
        if not isinstance(move, dict):
            continue
        special = move.get("special_announcement")
        if not isinstance(special, str):
            continue
        if special.startswith("CHECKMATE_"):
            return "checkmate"
        if special == "DRAW_STALEMATE":
            return "stalemate"
        if special == "DRAW_INSUFFICIENT":
            return "insufficient"
        if special == "DRAW_TOOMANYREVERSIBLEMOVES":
            return "too_many_reversible_moves"
    return None


def _outcome_for_bot(*, winner: Any, play_as: str) -> str:
    if winner == play_as:
        return "win"
    if winner in {"white", "black"}:
        return "loss"
    return "draw"


def _aggregate_summaries(summaries: list[GameSummary]) -> dict[str, Any]:
    games = len(summaries)
    attempts = sum(summary.attempts.attempts for summary in summaries)
    illegal = sum(summary.attempts.illegal_attempts for summary in summaries)
    completed_moves = sum(summary.attempts.completed_moves for summary in summaries)
    timeouts = sum(1 for summary in summaries if summary.reason == "timeout")
    wins = sum(1 for summary in summaries if summary.outcome == "win")
    losses = sum(1 for summary in summaries if summary.outcome == "loss")
    draws = sum(1 for summary in summaries if summary.outcome == "draw")
    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": _ratio(wins, games),
        "attempts": attempts,
        "illegal_attempts": illegal,
        "completed_moves": completed_moves,
        "illegal_attempt_rate": _ratio(illegal, attempts),
        "average_tries_per_completed_move": _ratio_float(attempts, completed_moves),
        "average_turns": _average([summary.turn_count for summary in summaries]),
        "timeouts": timeouts,
        "timeout_rate": _ratio(timeouts, games),
    }


def _matchup_rows(summaries: list[GameSummary]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, float | None, str | None], list[GameSummary]] = {}
    for summary in summaries:
        key = (summary.opponent.lower(), summary.time_budget_seconds, summary.opponent_commit)
        grouped.setdefault(key, []).append(summary)
    rows: list[dict[str, Any]] = []
    for (_opponent_key, time_budget, opponent_commit), values in grouped.items():
        aggregate = _aggregate_summaries(values)
        rows.append(
            {
                "opponent": values[0].opponent,
                "opponent_role": values[0].opponent_role,
                "opponent_commit": opponent_commit,
                "time_budget_seconds": time_budget,
                **aggregate,
            }
        )
    rows.sort(key=lambda row: (-int(row["games"]), str(row["opponent"]), str(row.get("time_budget_seconds"))))
    return rows


def _coverage(requirements: list[BenchmarkRequirement], summaries: list[GameSummary]) -> dict[str, Any]:
    if not requirements:
        return {"complete": None, "requirements": [], "note": "no benchmark manifest supplied"}
    rows: list[dict[str, Any]] = []
    complete = True
    for requirement in requirements:
        matched = [
            summary
            for summary in summaries
            if summary.opponent.lower() == requirement.opponent.lower()
            and (
                requirement.time_budget_seconds is None
                or summary.time_budget_seconds == requirement.time_budget_seconds
            )
        ]
        if not requirement.provider_available:
            status = "skipped_unavailable"
        elif len(matched) >= requirement.target_games:
            status = "complete"
        else:
            status = "missing"
            complete = False
        rows.append(
            {
                "opponent": requirement.opponent,
                "label": requirement.label,
                "target_games": requirement.target_games,
                "matched_games": len(matched),
                "opponent_commit": requirement.opponent_commit,
                "time_budget_seconds": requirement.time_budget_seconds,
                "provider_available": requirement.provider_available,
                "status": status,
            }
        )
    return {"complete": complete, "requirements": rows}


def _failure_modes(summaries: list[GameSummary]) -> list[dict[str, Any]]:
    counts = Counter(
        summary.reason or summary.outcome
        for summary in summaries
        if summary.outcome != "win" or summary.reason == "timeout"
    )
    return [{"reason": reason, "count": count} for reason, count in counts.most_common()]


def _game_payload(summary: GameSummary) -> dict[str, Any]:
    return {
        "game_id": summary.game_id,
        "opponent": summary.opponent,
        "opponent_role": summary.opponent_role,
        "play_as": summary.play_as,
        "outcome": summary.outcome,
        "reason": summary.reason,
        "turn_count": summary.turn_count,
        "time_budget_seconds": summary.time_budget_seconds,
        "bot_commit": summary.bot_commit,
        "opponent_commit": summary.opponent_commit,
        "attempts": {
            "attempts": summary.attempts.attempts,
            "illegal_attempts": summary.attempts.illegal_attempts,
            "completed_moves": summary.attempts.completed_moves,
        },
    }


def _nested_get(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = source
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _int_value(value: Any, *, default: int, minimum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _float_or_none(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    parsed = str(value).strip()
    return parsed or None


def _bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _first_present(values: Iterable[str | None]) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator > 0 else 0.0


def _ratio_float(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator > 0 else 0.0


def _average(values: list[int]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _fixed(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _time_budget(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "unknown"
    return f"{parsed:g}s"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a benchmark report from completed Wild 16 archives.")
    parser.add_argument("input", help="JSON/JSONL archive export")
    parser.add_argument("output", help="path to write markdown report")
    parser.add_argument("--manifest", help="benchmark manifest JSON")
    parser.add_argument("--json-output", help="optional path to write the machine-readable report JSON")
    parser.add_argument("--bot-username", default=DEFAULT_BOT_USERNAME)
    parser.add_argument("--bot-commit")
    args = parser.parse_args(argv)

    report = generate_benchmark_report(
        read_archive_records(args.input),
        manifest=load_manifest(args.manifest),
        bot_username=args.bot_username,
        bot_commit=args.bot_commit,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown_report(report))
    if args.json_output:
        json_output = Path(args.json_output)
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
