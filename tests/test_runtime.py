from __future__ import annotations

import os
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import chess

from darkboard_mcts import api
from darkboard_mcts.belief import BeliefState


def teardown_function(_function) -> None:
    api.configure_runtime_paths()


def test_runtime_paths_isolate_instance_env_and_state() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        env_path = temp_path / "darkboard.env"
        state_path = temp_path / "state" / "darkboard.json"
        env_path.write_text("KRIEGSPIEL_BOT_USERNAME=darkboardmcts2\n", encoding="utf-8")

        with patch.dict(os.environ, {}, clear=True):
            api.configure_runtime_paths(env_path=env_path, state_path=state_path)
            api.load_env_file()
            api.save_token("token-1")

            assert os.environ["KRIEGSPIEL_BOT_USERNAME"] == "darkboardmcts2"
            assert json.loads(state_path.read_text(encoding="utf-8"))["token"] == "token-1"


def test_supported_rule_variants_are_wild16_only() -> None:
    with patch.dict(os.environ, {"KRIEGSPIEL_SUPPORTED_RULE_VARIANTS": "berkeley,wild16,cincinnati"}, clear=True):
        assert api.supported_rule_variants() == ["wild16"]


def test_register_bot_advertises_wild16_and_lists_by_default() -> None:
    posts: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"api_token": "token-123"}

    def fake_post(*args, **kwargs):
        posts.append(kwargs)
        return FakeResponse()

    env = {
        "KRIEGSPIEL_API_BASE": "https://api.example.test",
        "KRIEGSPIEL_BOT_USERNAME": "darkboardmcts",
        "KRIEGSPIEL_BOT_DISPLAY_NAME": "Darkboard MCTS",
        "KRIEGSPIEL_BOT_OWNER_EMAIL": "bots@example.test",
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.object(api, "STATE_PATH", Path(temp_dir) / ".bot-state.json"):
            with patch.dict(os.environ, env, clear=True):
                with patch.object(api.requests, "post", side_effect=fake_post):
                    api.register_bot()

    assert posts[0]["json"]["supported_rule_variants"] == ["wild16"]
    assert posts[0]["json"]["listed"] is True
    assert "headers" not in posts[0]


def test_register_bot_can_be_kept_unlisted_by_env() -> None:
    posts: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"api_token": "token-123"}

    env = {
        "KRIEGSPIEL_API_BASE": "https://api.example.test",
        "KRIEGSPIEL_BOT_USERNAME": "darkboardmcts",
        "KRIEGSPIEL_BOT_DISPLAY_NAME": "Darkboard MCTS",
        "KRIEGSPIEL_BOT_OWNER_EMAIL": "bots@example.test",
        "KRIEGSPIEL_BOT_LISTED": "false",
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.object(api, "STATE_PATH", Path(temp_dir) / ".bot-state.json"):
            with patch.dict(os.environ, env, clear=True):
                with patch.object(api.requests, "post", side_effect=lambda *args, **kwargs: posts.append(kwargs) or FakeResponse()):
                    api.register_bot()

    assert posts[0]["json"]["listed"] is False
    assert "headers" not in posts[0]


def test_botplay_policy_defaults_allow_one_active_game_and_bot_lobbies() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert api.auto_create_enabled() is True
        assert api.bot_game_pick_probability() == 0.1
        assert api.max_active_games() == 1


def test_active_game_discovery_limit_parses_default_and_custom_env() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert api.active_game_discovery_limit() == 100
    with patch.dict(os.environ, {"KRIEGSPIEL_ACTIVE_GAME_DISCOVERY_LIMIT": "40"}):
        assert api.active_game_discovery_limit() == 40
    with patch.dict(os.environ, {"KRIEGSPIEL_ACTIVE_GAME_DISCOVERY_LIMIT": "0"}):
        assert api.active_game_discovery_limit() == 1
    with patch.dict(os.environ, {"KRIEGSPIEL_ACTIVE_GAME_DISCOVERY_LIMIT": "250"}):
        assert api.active_game_discovery_limit() == 100
    with patch.dict(os.environ, {"KRIEGSPIEL_ACTIVE_GAME_DISCOVERY_LIMIT": "invalid"}):
        assert api.active_game_discovery_limit() == 100


def test_botplay_config_migration_updates_launch_defaults_once() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        env_path = Path(temp_dir) / ".env"
        state_path = Path(temp_dir) / ".bot-state.json"
        env_path.write_text(
            "\n".join(
                [
                    "KRIEGSPIEL_BOT_TOKEN=secret-token",
                    "KRIEGSPIEL_AUTO_CREATE_LOBBY_GAME=false",
                    "KRIEGSPIEL_MAX_ACTIVE_GAMES=1",
                    "BOT_GAME_PICK_PROBABILITY=0",
                    "LOG_LEVEL=INFO",
                ]
            )
            + "\n"
        )
        state_path.write_text(json.dumps({"token": "secret-token"}))

        with patch.object(api, "STATE_PATH", state_path):
            with patch.dict(os.environ, {}, clear=True):
                api.load_env_file(env_path)
                api.apply_botplay_config_migration(env_path)

                assert api.auto_create_enabled() is True
                assert api.bot_game_pick_probability() == 0.1
                assert api.max_active_games() == 1

        migrated_env = env_path.read_text()
        saved_state = json.loads(state_path.read_text())

    assert "KRIEGSPIEL_BOT_TOKEN=secret-token" in migrated_env
    assert "KRIEGSPIEL_AUTO_CREATE_LOBBY_GAME=true" in migrated_env
    assert "BOT_GAME_PICK_PROBABILITY=0.1" in migrated_env
    assert saved_state["token"] == "secret-token"
    assert saved_state["config_migrations"][api.BOTPLAY_CONFIG_MIGRATION] is True


def test_botplay_config_migration_does_not_rewrite_after_marker() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        env_path = Path(temp_dir) / ".env"
        state_path = Path(temp_dir) / ".bot-state.json"
        env_path.write_text("KRIEGSPIEL_AUTO_CREATE_LOBBY_GAME=false\nBOT_GAME_PICK_PROBABILITY=0.5\n")
        state_path.write_text(json.dumps({"config_migrations": {api.BOTPLAY_CONFIG_MIGRATION: True}}))

        with patch.object(api, "STATE_PATH", state_path):
            with patch.dict(os.environ, {}, clear=True):
                api.load_env_file(env_path)
                api.apply_botplay_config_migration(env_path)

                assert api.auto_create_enabled() is False
                assert api.bot_game_pick_probability() == 0.5

        unchanged_env = env_path.read_text()

    assert unchanged_env == "KRIEGSPIEL_AUTO_CREATE_LOBBY_GAME=false\nBOT_GAME_PICK_PROBABILITY=0.5\n"


def test_join_probability_config_migration_reduces_existing_half_probability() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        env_path = Path(temp_dir) / ".env"
        state_path = Path(temp_dir) / ".bot-state.json"
        env_path.write_text("KRIEGSPIEL_AUTO_CREATE_LOBBY_GAME=true\nBOT_GAME_PICK_PROBABILITY=0.5\n")
        state_path.write_text(json.dumps({"config_migrations": {api.BOTPLAY_CONFIG_MIGRATION: True}}))

        with patch.object(api, "STATE_PATH", state_path):
            with patch.dict(os.environ, {}, clear=True):
                api.load_env_file(env_path)
                api.apply_join_probability_config_migration(env_path)

                assert api.auto_create_enabled() is True
                assert api.bot_game_pick_probability() == 0.1

        migrated_env = env_path.read_text()
        saved_state = json.loads(state_path.read_text())

    assert "BOT_GAME_PICK_PROBABILITY=0.1" in migrated_env
    assert saved_state["config_migrations"][api.BOTPLAY_CONFIG_MIGRATION] is True
    assert saved_state["config_migrations"][api.BOT_JOIN_PROBABILITY_CONFIG_MIGRATION] is True


def test_join_probability_config_migration_preserves_explicit_non_half_probability() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        env_path = Path(temp_dir) / ".env"
        state_path = Path(temp_dir) / ".bot-state.json"
        env_path.write_text("BOT_GAME_PICK_PROBABILITY=0.2\n")
        state_path.write_text("{}")

        with patch.object(api, "STATE_PATH", state_path):
            with patch.dict(os.environ, {}, clear=True):
                api.load_env_file(env_path)
                api.apply_join_probability_config_migration(env_path)

                assert api.bot_game_pick_probability() == 0.2

        unchanged_env = env_path.read_text()
        saved_state = json.loads(state_path.read_text())

    assert unchanged_env == "BOT_GAME_PICK_PROBABILITY=0.2\n"
    assert saved_state["config_migrations"][api.BOT_JOIN_PROBABILITY_CONFIG_MIGRATION] is True


def test_maybe_join_bot_lobby_game_records_sample_even_without_candidate() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        state_path = Path(temp_dir) / ".bot-state.json"
        with patch.object(api, "STATE_PATH", state_path):
            with patch.object(api, "get_json", return_value={"games": []}):
                with patch.object(api.time, "time", return_value=100.0):
                    with patch.object(api, "post_json") as post_json:
                        assert api.maybe_join_bot_lobby_game([]) is False
                        post_json.assert_not_called()

            assert api.can_attempt_bot_join(now=130.0) is False
            assert api.can_attempt_bot_join(now=161.0) is True


def test_maybe_join_bot_lobby_game_skips_open_sample_during_cooldown() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        state_path = Path(temp_dir) / ".bot-state.json"
        with patch.object(api, "STATE_PATH", state_path):
            api.record_bot_join_attempt(now=100.0)
            with patch.object(api.time, "time", return_value=130.0):
                with patch.object(api, "get_json") as get_json:
                    assert api.maybe_join_bot_lobby_game([]) is False
                    get_json.assert_not_called()


def test_maybe_play_game_retries_ranked_attempts_until_one_completes() -> None:
    state = {
        "game_id": "game-1",
        "state": "active",
        "turn": "white",
        "your_color": "white",
        "your_fen": "8/8/8/8/8/8/PPPPPPPP/RNBQKBNR w KQ - 0 1",
        "possible_actions": ["move"],
        "allowed_moves": ["e2e4", "d2d4"],
        "move_number": 1,
        "material_summary": {"white": {"pieces_remaining": 16}, "black": {"pieces_remaining": 16}},
        "referee_log": [],
        "referee_turns": [],
    }
    posts: list[tuple[str, dict | None]] = []
    results = [
        {"announcement": "Illegal move", "move_done": False},
        {"announcement": "Move complete", "move_done": True},
    ]

    def fake_post_json(path: str, payload: dict | None = None) -> dict:
        posts.append((path, payload))
        return results.pop(0)

    with tempfile.TemporaryDirectory() as temp_dir:
        state_path = Path(temp_dir) / ".bot-state.json"
        with patch.object(api, "STATE_PATH", state_path):
            with patch.object(api, "get_json", return_value=state):
                with patch.object(api, "post_json", side_effect=fake_post_json):
                    with patch.object(api.time, "sleep") as sleep_mock:
                        assert api.maybe_play_game({"game_id": "game-1", "rule_variant": "wild16"}) is True

        saved = json.loads(state_path.read_text())

    assert [path for path, _ in posts] == ["/game/game-1/move", "/game/game-1/move"]
    assert {payload["uci"] for _, payload in posts if payload is not None} == {"d2d4", "e2e4"}
    assert saved["beliefs"]["game-1"]["your_fen"] == state["your_fen"]
    assert saved["beliefs"]["game-1"]["observed_referee_log_size"] == 1
    sleep_mock.assert_called_once_with(api.FAILED_MOVE_RETRY_DELAY_SECONDS)


def test_restore_belief_uses_saved_matrices_and_cursor() -> None:
    current = BeliefState.from_api_state(
        {
            "game_id": "game-1",
            "state": "active",
            "turn": "white",
            "your_color": "white",
            "your_fen": "8/8/8/8/8/8/3P4/R6K w - - 0 1",
            "allowed_moves": ["d2e3"],
            "move_number": 1,
            "material_summary": {"white": {"pieces_remaining": 10}, "black": {"pieces_remaining": 16}},
            "referee_log": [],
        }
    )
    pawns = [0.0] * 64
    pawns[20] = 8.0

    with tempfile.TemporaryDirectory() as temp_dir:
        state_path = Path(temp_dir) / ".bot-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "beliefs": {
                        "game-1": {
                            "game_id": "game-1",
                            "ruleset": "wild16",
                            "color": "white",
                            "observed_referee_log_size": 7,
                            "opponent_king": list(current.opponent_king),
                            "opponent_pawns": pawns,
                            "opponent_pieces": list(current.opponent_pieces),
                        }
                    }
                }
            )
        )

        with patch.object(api, "STATE_PATH", state_path):
            restored = api.restore_belief("game-1", current)

    assert restored.observed_referee_log_size == 0
    assert restored.opponent_pawns[20] > current.opponent_pawns[20]


def test_maybe_play_game_persists_failed_attempt_evidence() -> None:
    state = {
        "game_id": "game-1",
        "state": "active",
        "turn": "white",
        "your_color": "white",
        "your_fen": "8/8/8/8/8/8/3P4/R6K w - - 0 1",
        "possible_actions": ["move"],
        "allowed_moves": ["d2e3"],
        "move_number": 1,
        "material_summary": {"white": {"pieces_remaining": 10}, "black": {"pieces_remaining": 16}},
        "referee_log": [],
        "referee_turns": [],
    }
    prior = BeliefState.from_api_state(state)

    with tempfile.TemporaryDirectory() as temp_dir:
        state_path = Path(temp_dir) / ".bot-state.json"
        with patch.object(api, "STATE_PATH", state_path):
            with patch.object(api, "get_json", return_value=state):
                with patch.object(api, "ranked_actions", return_value=("d2e3",)):
                    with patch.object(
                        api,
                        "post_json",
                        return_value={"announcement": "ILLEGAL_MOVE", "move_done": False},
                    ):
                        assert api.maybe_play_game({"game_id": "game-1", "rule_variant": "wild16"}) is False

        saved = json.loads(state_path.read_text())

    assert saved["beliefs"]["game-1"]["opponent_pawns"][chess.E3] < prior.opponent_pawns[chess.E3]
    assert saved["beliefs"]["game-1"]["observed_referee_log_size"] == 1


def test_maybe_play_game_skips_non_wild16_games() -> None:
    with patch.object(api, "get_json") as get_json:
        assert api.maybe_play_game({"game_id": "game-1", "rule_variant": "berkeley"}) is False

    get_json.assert_not_called()


def test_open_bot_lobby_candidates_only_include_wild16_bot_games() -> None:
    with patch.dict(os.environ, {"KRIEGSPIEL_BOT_USERNAME": "darkboardmcts"}):
        candidates = api.open_bot_lobby_candidates(
            [
                {"game_code": "WLD123", "created_by": "randobot", "rule_variant": "wild16"},
                {"game_code": "ANY123", "created_by": "randobot", "rule_variant": "berkeley_any"},
                {"game_code": "SELF12", "created_by": "darkboardmcts", "rule_variant": "wild16"},
                {"game_code": "HUM123", "created_by": "fil", "rule_variant": "wild16"},
            ],
            profile_lookup=lambda username: {"role": "bot" if username == "randobot" else "user"},
        )

    assert [game["game_code"] for game in candidates] == ["WLD123"]


def test_runner_scheduler_starts_one_runner_per_game_without_duplicates() -> None:
    class FakeRunner:
        def __init__(self, game_ref: str) -> None:
            self.game_ref = game_ref
            self.started = 0
            self.stopped = 0
            self.joined = 0
            self.alive = False

        def start(self) -> None:
            self.started += 1
            self.alive = True

        def stop(self) -> None:
            self.stopped += 1
            self.alive = False

        def join(self, timeout: float | None = None) -> None:  # noqa: ARG002
            self.joined += 1

        def is_alive(self) -> bool:
            return self.alive

    created: dict[str, FakeRunner] = {}

    def runner_factory(game_ref: str) -> FakeRunner:
        runner = FakeRunner(game_ref)
        created[game_ref] = runner
        return runner

    scheduler = api.GameRunnerScheduler(poll_seconds=0.01, runner_factory=runner_factory)
    games = [
        {"state": "active", "game_id": "g1", "rule_variant": "wild16"},
        {"state": "active", "game_id": "g2", "rule_variant": "wild16"},
        {"state": "waiting", "game_id": "w1", "rule_variant": "wild16"},
    ]

    scheduler.reconcile(games)
    scheduler.reconcile(games)

    assert set(created) == {"g1", "g2"}
    assert created["g1"].started == 1
    assert created["g2"].started == 1

    scheduler.reconcile([{"state": "active", "game_id": "g2", "rule_variant": "wild16"}])

    assert created["g1"].stopped == 0
    assert "g1" in scheduler.runners
    assert "g2" in scheduler.runners

    created["g1"].alive = False
    scheduler.reconcile([{"state": "active", "game_id": "g2", "rule_variant": "wild16"}])

    assert "g1" not in scheduler.runners
    assert "g2" in scheduler.runners


def test_one_slow_game_runner_does_not_block_another_runner() -> None:
    slow_started = threading.Event()
    release_slow = threading.Event()
    fast_played = threading.Event()

    def fake_get_json(path: str) -> dict[str, str]:
        game_ref = path.split("/")[2]
        return {"state": "active", "turn": "white", "your_color": "white", "game_id": game_ref}

    def fake_maybe_play_game(game_ref: str) -> bool:
        if game_ref == "slow":
            slow_started.set()
            release_slow.wait(timeout=1)
            return True
        fast_played.set()
        return True

    slow_runner = api.GameRunner("slow", poll_seconds=0.01)
    fast_runner = api.GameRunner("fast", poll_seconds=0.01)

    with patch.object(api, "get_json", side_effect=fake_get_json):
        with patch.object(api, "maybe_play_game", side_effect=fake_maybe_play_game):
            slow_runner.start()
            assert slow_started.wait(timeout=0.5)
            fast_runner.start()
            assert fast_played.wait(timeout=0.5)
            slow_runner.stop()
            fast_runner.stop()
            release_slow.set()
            slow_runner.join(timeout=1)
            fast_runner.join(timeout=1)

    assert not slow_runner.is_alive()
    assert not fast_runner.is_alive()
