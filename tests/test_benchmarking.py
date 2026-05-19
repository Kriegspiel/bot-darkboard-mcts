import json

import pytest

from darkboard_mcts.benchmarking import generate_benchmark_report, main, render_markdown_report


def test_benchmark_report_aggregates_manifest_coverage_and_attempt_metrics() -> None:
    manifest = {
        "benchmark_name": "Darkboard benchmark smoke",
        "bot": {"username": "darkboardmcts", "commit": "bot123"},
        "required_matchups": [
            {"opponent": "randobot", "opponent_commit": "rand123", "time_budget_seconds": 1, "target_games": 2},
            {"opponent": "simpleheuristics", "opponent_commit": "simple123", "time_budget_seconds": 1, "target_games": 1},
            {"opponent": "gptnano", "provider_available": False, "target_games": 1},
        ],
    }
    games = [
        _game(
            game_code="WIN001",
            white="darkboardmcts",
            black="randobot",
            winner="white",
            reason="checkmate",
            turn_count=12,
            benchmark={"time_budget_seconds": 1, "bot_commit": "bot123"},
            white_turns=[
                [_attempt("e2e5", "ILLEGAL_MOVE", False), _attempt("e2e4", "REGULAR_MOVE", True)],
                [_attempt("g1f3", "REGULAR_MOVE", True)],
            ],
        ),
        _game(
            game_code="LOSS01",
            white="randobot",
            black="darkboardmcts",
            winner="white",
            reason="timeout",
            turn_count=8,
            benchmark={"time_budget_seconds": 1, "bot_commit": "bot123"},
            black_turns=[[_attempt("e7e5", "REGULAR_MOVE", True)]],
        ),
        _game(game_code="SKIP01", white="darkboardmcts", black="randobot", status="active"),
        _game(game_code="SKIP02", white="other", black="randobot"),
    ]

    report = generate_benchmark_report(games, manifest=manifest)
    overall = report["overall"]

    assert report["bot"] == {"username": "darkboardmcts", "commit": "bot123"}
    assert report["source"]["archive_records"] == 4
    assert report["source"]["completed_wild16_games"] == 2
    assert report["source"]["skipped"] == {"bot_not_in_game": 1, "not_completed_wild16": 1}
    assert overall["games"] == 2
    assert overall["wins"] == 1
    assert overall["losses"] == 1
    assert overall["draws"] == 0
    assert overall["illegal_attempt_rate"] == pytest.approx(0.25)
    assert overall["average_tries_per_completed_move"] == pytest.approx(1.333)
    assert overall["average_turns"] == pytest.approx(10.0)
    assert overall["timeout_rate"] == pytest.approx(0.5)
    assert report["matchups"][0]["opponent"] == "randobot"
    assert report["matchups"][0]["opponent_commit"] == "rand123"
    assert report["coverage"]["complete"] is False
    assert [row["status"] for row in report["coverage"]["requirements"]] == [
        "complete",
        "missing",
        "skipped_unavailable",
    ]
    assert report["failure_modes"] == [{"reason": "timeout", "count": 1}]


def test_benchmark_report_uses_public_history_when_scoresheets_are_absent() -> None:
    report = generate_benchmark_report(
        [
            {
                "game_code": "PUB001",
                "rule_variant": "wild16",
                "state": "completed",
                "white": {"username": "darkboardmcts", "role": "bot"},
                "black": {"username": "randobot", "role": "bot"},
                "result": {"winner": None, "reason": "stalemate"},
                "moves": [
                    {
                        "color": "white",
                        "question_type": "COMMON",
                        "uci": "e2e5",
                        "announcement": "ILLEGAL_MOVE",
                        "move_done": False,
                    },
                    {
                        "color": "white",
                        "question_type": "COMMON",
                        "uci": "e2e4",
                        "announcement": "REGULAR_MOVE",
                        "move_done": True,
                    },
                    {
                        "color": "black",
                        "question_type": "COMMON",
                        "uci": "d7d5",
                        "announcement": "REGULAR_MOVE",
                        "move_done": True,
                    },
                ],
            }
        ]
    )

    assert report["overall"]["games"] == 1
    assert report["overall"]["draws"] == 1
    assert report["overall"]["attempts"] == 2
    assert report["overall"]["illegal_attempts"] == 1
    assert report["overall"]["completed_moves"] == 1
    assert report["overall"]["illegal_attempt_rate"] == pytest.approx(0.5)
    assert report["failure_modes"] == [{"reason": "stalemate", "count": 1}]


def test_benchmark_report_cli_writes_markdown_and_json(tmp_path) -> None:
    archive_path = tmp_path / "games.jsonl"
    manifest_path = tmp_path / "manifest.json"
    markdown_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"
    archive_path.write_text(json.dumps(_game(game_code="CLI001", white="darkboardmcts", black="randobot")) + "\n")
    manifest_path.write_text(
        json.dumps(
            {
                "required_matchups": [{"opponent": "randobot", "target_games": 1}],
                "collection": {
                    "method": "local_ks_game_wild16",
                    "runner": "darkboard-run-local-benchmark",
                    "engine_commit": "engine123",
                    "seed": 20260519,
                    "mcts_max_iterations": 384,
                    "selection_rule": "visits",
                    "max_plies": 700,
                    "raw_archives_committed": False,
                },
            }
        )
    )

    result = main([str(archive_path), str(markdown_path), "--manifest", str(manifest_path), "--json-output", str(json_path)])
    payload = json.loads(json_path.read_text())
    markdown = markdown_path.read_text()

    assert result == 0
    assert payload["coverage"]["complete"] is True
    assert payload["collection"]["runner"] == "darkboard-run-local-benchmark"
    assert "# Darkboard MCTS benchmark" in markdown
    assert "## Collection" in markdown
    assert "`local_ks_game_wild16`" in markdown
    assert "`randobot`" in markdown


def test_render_markdown_report_includes_missing_coverage() -> None:
    report = generate_benchmark_report(
        [_game(game_code="MD001", white="darkboardmcts", black="randobot")],
        manifest={"required_matchups": [{"opponent": "simpleheuristics", "target_games": 2}]},
    )

    markdown = render_markdown_report(report)

    assert "## Coverage" in markdown
    assert "`simpleheuristics`" in markdown
    assert "`missing`" in markdown
    assert "Treat incomplete coverage as a blocker" in markdown


def _game(
    *,
    game_code: str,
    white: str,
    black: str,
    winner: str | None = "white",
    reason: str = "checkmate",
    status: str = "completed",
    turn_count: int = 4,
    benchmark: dict | None = None,
    white_turns: list | None = None,
    black_turns: list | None = None,
) -> dict:
    return {
        "game_code": game_code,
        "rule_variant": "wild16",
        "state": status,
        "white": {"username": white, "role": "bot"},
        "black": {"username": black, "role": "bot"},
        "result": {"winner": winner, "reason": reason},
        "turn_count": turn_count,
        "benchmark": benchmark or {},
        "engine_state": {
            "game_state": {
                "white_scoresheet": {"moves_own": white_turns or [[_attempt("e2e4", "REGULAR_MOVE", True)]]},
                "black_scoresheet": {"moves_own": black_turns or [[_attempt("e7e5", "REGULAR_MOVE", True)]]},
            }
        },
    }


def _attempt(uci: str, announcement: str, move_done: bool) -> dict:
    return {
        "question": {"question_type": "COMMON", "move_uci": uci},
        "answer": {"main_announcement": announcement, "move_done": move_done},
    }
