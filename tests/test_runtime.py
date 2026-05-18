from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import chess

from darkboard_mcts import api
from darkboard_mcts.belief import BeliefState


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
        "KRIEGSPIEL_BOT_REGISTRATION_KEY": "registration-key",
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


def test_register_bot_can_be_kept_unlisted_by_env() -> None:
    posts: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"api_token": "token-123"}

    env = {
        "KRIEGSPIEL_API_BASE": "https://api.example.test",
        "KRIEGSPIEL_BOT_REGISTRATION_KEY": "registration-key",
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


def test_botplay_policy_defaults_allow_one_active_game_and_bot_lobbies() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert api.auto_create_enabled() is True
        assert api.bot_game_pick_probability() == 0.1
        assert api.max_active_games() == 1


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
