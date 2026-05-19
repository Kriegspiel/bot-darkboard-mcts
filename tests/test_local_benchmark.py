from darkboard_mcts.benchmarking import generate_benchmark_report
from darkboard_mcts.local_benchmark import DEFAULT_RANDOM_USERNAME
from darkboard_mcts.local_benchmark import DEFAULT_SELF_USERNAME
from darkboard_mcts.local_benchmark import play_local_game
from darkboard_mcts.local_benchmark import PlayerSpec
from darkboard_mcts.local_benchmark import run_benchmark_games


def test_local_benchmark_generates_completed_wild16_archive_records() -> None:
    bot = PlayerSpec("darkboardmcts", "darkboard", "bot123")
    random = PlayerSpec("randobot", "random", "random123")

    record = play_local_game(
        game_code="TEST001",
        benchmark_bot=bot,
        white=bot,
        black=random,
        seed=7,
        time_budget_seconds=0.0,
        mcts_max_iterations=1,
        selection_rule="visits",
        engine_commit="engine123",
        max_plies=2,
    )

    assert record["state"] == "completed"
    assert record["rule_variant"] == "wild16"
    assert record["benchmark"]["collection_method"] == "local_ks_game_wild16"
    assert record["benchmark"]["bot_commit"] == "bot123"
    assert record["benchmark"]["opponent_commit"] == "random123"
    assert record["engine_state"]["game_state"]["white_scoresheet"]["moves_own"]


def test_run_benchmark_games_builds_manifest_and_reportable_self_matchup() -> None:
    records, manifest = run_benchmark_games(
        games_per_matchup=1,
        bot_commit="bot123",
        random_commit="random123",
        simple_commit="simple123",
        engine_commit="engine123",
        seed=11,
        matchups=(DEFAULT_RANDOM_USERNAME, DEFAULT_SELF_USERNAME),
        time_budget_seconds=0.0,
        mcts_max_iterations=1,
        max_plies=2,
    )

    assert len(records) == 2
    assert [row["opponent"] for row in manifest["required_matchups"]] == ["randobot", "darkboardmcts-self"]

    report = generate_benchmark_report(records, manifest=manifest)
    assert report["coverage"]["complete"] is True
    assert report["overall"]["games"] == 2
    assert {row["opponent"] for row in report["matchups"]} == {"randobot", "darkboardmcts-self"}
