from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from darkboard_mcts import api


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

    assert posts == [
        ("/game/game-1/move", {"uci": "d2d4"}),
        ("/game/game-1/move", {"uci": "e2e4"}),
    ]
    assert saved["beliefs"]["game-1"]["your_fen"] == state["your_fen"]
    sleep_mock.assert_called_once_with(api.FAILED_MOVE_RETRY_DELAY_SECONDS)


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
