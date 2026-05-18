"""Kriegspiel API runtime for the Darkboard-inspired bot."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

import requests

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.belief import WILD16_RULESET
from darkboard_mcts.search import ranked_actions


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = Path(os.environ.get("DARKBOARD_MCTS_ENV_PATH", PACKAGE_ROOT / ".env"))
STATE_PATH = Path(os.environ.get("DARKBOARD_MCTS_STATE_PATH", PACKAGE_ROOT / ".bot-state.json"))
DEFAULT_TIMEOUT_SECONDS = 20
BOT_JOIN_COOLDOWN_SECONDS = 60
FAILED_MOVE_RETRY_DELAY_SECONDS = 1
SUPPORTED_RULE_VARIANTS = (WILD16_RULESET,)
BOTPLAY_CONFIG_MIGRATION = "darkboard_botplay_config_20260518"
BOTPLAY_CONFIG_DEFAULTS = {
    "KRIEGSPIEL_AUTO_CREATE_LOBBY_GAME": "true",
    "BOT_GAME_PICK_PROBABILITY": "0.5",
    "KRIEGSPIEL_MAX_ACTIVE_GAMES": "1",
}
BOTPLAY_CONFIG_LEGACY_VALUES = {
    "KRIEGSPIEL_AUTO_CREATE_LOBBY_GAME": {"0", "false", "no", "off"},
    "BOT_GAME_PICK_PROBABILITY": {"0", "0.0"},
    "KRIEGSPIEL_MAX_ACTIVE_GAMES": {"1"},
}
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_env_file(path: str | Path = ENV_PATH) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def base_url() -> str:
    return os.environ.get("KRIEGSPIEL_API_BASE", "http://localhost:8000").rstrip("/")


def auth_headers() -> dict[str, str]:
    token = os.environ.get("KRIEGSPIEL_BOT_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def bot_username() -> str:
    return os.environ.get("KRIEGSPIEL_BOT_USERNAME", "").strip().lower()


def bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def float_env(name: str, default: float, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = max(minimum, float(raw))
    except ValueError:
        return default
    if maximum is not None:
        return min(maximum, value)
    return value


def max_active_games() -> int:
    return int_env("KRIEGSPIEL_MAX_ACTIVE_GAMES", 1, minimum=1)


def bot_game_pick_probability() -> float:
    return float_env("BOT_GAME_PICK_PROBABILITY", 0.5, minimum=0.0, maximum=1.0)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    except json.JSONDecodeError:
        logger.warning("ignoring malformed bot state at %s", STATE_PATH)
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def save_token(token: str) -> None:
    state = load_state()
    state["token"] = token
    save_state(state)


def maybe_restore_token() -> None:
    if os.environ.get("KRIEGSPIEL_BOT_TOKEN"):
        return
    token = load_state().get("token")
    if isinstance(token, str) and token:
        os.environ["KRIEGSPIEL_BOT_TOKEN"] = token


def _env_value_for_compare(value: str) -> str:
    normalized = value.strip()
    if (normalized.startswith('"') and normalized.endswith('"')) or (
        normalized.startswith("'") and normalized.endswith("'")
    ):
        normalized = normalized[1:-1]
    return normalized.strip().lower()


def _split_env_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value


def apply_botplay_config_migration(env_path: str | Path = ENV_PATH) -> None:
    """Move launch-era deployments onto the bot-vs-bot policy once."""

    state = load_state()
    migrations = state.get("config_migrations")
    if not isinstance(migrations, dict):
        migrations = {}
    if migrations.get(BOTPLAY_CONFIG_MIGRATION):
        return

    path = Path(env_path)
    if not path.exists():
        return

    lines = path.read_text().splitlines()
    updated_lines: list[str] = []
    seen: set[str] = set()
    changed = False

    for line in lines:
        assignment = _split_env_assignment(line)
        if assignment is None:
            updated_lines.append(line)
            continue
        key, value = assignment
        if key not in BOTPLAY_CONFIG_DEFAULTS:
            updated_lines.append(line)
            continue

        seen.add(key)
        desired = BOTPLAY_CONFIG_DEFAULTS[key]
        legacy_values = BOTPLAY_CONFIG_LEGACY_VALUES.get(key, set())
        if _env_value_for_compare(value) in legacy_values:
            updated_lines.append(f"{key}={desired}")
            os.environ[key] = desired
            changed = True
        else:
            updated_lines.append(line)

    for key, desired in BOTPLAY_CONFIG_DEFAULTS.items():
        if key not in seen:
            updated_lines.append(f"{key}={desired}")
            os.environ[key] = desired
            changed = True

    if changed:
        path.write_text("\n".join(updated_lines) + "\n")
        logger.info("updated bot-vs-bot runtime config in %s", path)

    migrations[BOTPLAY_CONFIG_MIGRATION] = True
    state["config_migrations"] = migrations
    save_state(state)


def supported_rule_variants() -> list[str]:
    raw = os.environ.get("KRIEGSPIEL_SUPPORTED_RULE_VARIANTS", WILD16_RULESET)
    variants: list[str] = []
    for item in raw.split(","):
        value = item.strip()
        if value in SUPPORTED_RULE_VARIANTS and value not in variants:
            variants.append(value)
    return variants or [WILD16_RULESET]


def register_bot() -> None:
    response = requests.post(
        f"{base_url()}/auth/bots/register",
        headers={"X-Bot-Registration-Key": os.environ["KRIEGSPIEL_BOT_REGISTRATION_KEY"]},
        json={
            "username": os.environ.get("KRIEGSPIEL_BOT_USERNAME", "darkboardmcts"),
            "display_name": os.environ.get("KRIEGSPIEL_BOT_DISPLAY_NAME", "Darkboard MCTS"),
            "owner_email": os.environ["KRIEGSPIEL_BOT_OWNER_EMAIL"],
            "description": os.environ.get(
                "KRIEGSPIEL_BOT_DESCRIPTION",
                "Darkboard-inspired Wild 16 bot runtime.",
            ),
            "listed": bool_env("KRIEGSPIEL_BOT_LISTED", True),
            "supported_rule_variants": supported_rule_variants(),
        },
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    save_token(payload["api_token"])
    logger.info("registered bot %s", os.environ.get("KRIEGSPIEL_BOT_USERNAME", "darkboardmcts"))


def get_json(path: str) -> dict[str, Any]:
    response = requests.get(f"{base_url()}{path}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def get_public_user(username: str) -> dict[str, Any]:
    response = requests.get(f"{base_url()}/user/{username}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def post_json(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(
        f"{base_url()}{path}",
        headers=auth_headers(),
        json=payload or {},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def active_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [game for game in games if game.get("state") == "active"]


def waiting_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [game for game in games if game.get("state") == "waiting"]


def under_active_game_limit(games: list[dict[str, Any]]) -> bool:
    return len(active_games(games)) < max_active_games()


def auto_create_enabled() -> bool:
    return bool_env("KRIEGSPIEL_AUTO_CREATE_LOBBY_GAME", True)


def create_payload() -> dict[str, str]:
    return {
        "rule_variant": WILD16_RULESET,
        "play_as": os.environ.get("KRIEGSPIEL_AUTO_CREATE_PLAY_AS", "random").strip() or "random",
        "time_control": "rapid",
        "opponent_type": "human",
    }


def has_own_waiting_game(open_games: list[dict[str, Any]]) -> bool:
    own_username = bot_username()
    for game in open_games:
        created_by = str(game.get("created_by") or "").strip().lower()
        if created_by and created_by == own_username:
            return True
    return False


def maybe_create_lobby_game(games: list[dict[str, Any]]) -> bool:
    if not auto_create_enabled() or not under_active_game_limit(games) or waiting_games(games):
        return False
    open_games = get_json("/game/open").get("games", [])
    if not isinstance(open_games, list) or has_own_waiting_game(open_games):
        return False
    created = post_json("/game/create", create_payload())
    logger.info("created Wild 16 lobby game %s (%s)", created.get("game_id"), created.get("game_code"))
    return True


def open_bot_lobby_candidates(open_games: list[dict[str, Any]], *, profile_lookup=None) -> list[dict[str, Any]]:
    profile_lookup = profile_lookup or get_public_user
    own_username = bot_username()
    candidates: list[dict[str, Any]] = []
    for game in open_games:
        if str(game.get("rule_variant") or "").strip() != WILD16_RULESET:
            continue
        creator_username = str(game.get("created_by") or "").strip()
        if not creator_username or creator_username.lower() == own_username:
            continue
        try:
            profile = profile_lookup(creator_username)
        except requests.RequestException:
            continue
        is_bot = bool(profile.get("is_bot")) or str(profile.get("role") or "").strip().lower() == "bot"
        if is_bot:
            candidates.append(game)
    return candidates


def can_attempt_bot_join(now: float | None = None) -> bool:
    current = time.time() if now is None else now
    last_attempt = load_state().get("last_bot_game_join_attempt_at", 0)
    try:
        last_attempt = float(last_attempt)
    except (TypeError, ValueError):
        last_attempt = 0
    return current - last_attempt >= BOT_JOIN_COOLDOWN_SECONDS


def record_bot_join_attempt(now: float | None = None) -> None:
    state = load_state()
    state["last_bot_game_join_attempt_at"] = time.time() if now is None else now
    save_state(state)


def choose_bot_game_to_join(open_games: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = open_bot_lobby_candidates(open_games)
    return candidates[0] if candidates else None


def maybe_join_bot_lobby_game(games: list[dict[str, Any]]) -> bool:
    if not under_active_game_limit(games) or not can_attempt_bot_join():
        return False
    open_games = get_json("/game/open").get("games", [])
    if not isinstance(open_games, list):
        return False
    candidate = choose_bot_game_to_join(open_games)
    if candidate is None:
        return False
    record_bot_join_attempt()
    if bot_game_pick_probability() <= 0:
        return False
    if random.random() >= bot_game_pick_probability():
        return False
    game_code = str(candidate.get("game_code") or "").strip()
    if not game_code:
        return False
    joined = post_json(f"/game/join/{game_code}")
    logger.info("joined Wild 16 bot lobby game %s (%s)", joined.get("game_id"), joined.get("game_code"))
    return True


def game_ref(game: dict[str, Any]) -> str | None:
    for key in ("game_id", "game_code"):
        value = game.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def game_ruleset(game: dict[str, Any]) -> str:
    return str(game.get("rule_variant") or WILD16_RULESET)


def serialize_belief(belief: BeliefState) -> dict[str, Any]:
    return {
        "game_id": belief.game_id,
        "ruleset": belief.ruleset,
        "ply": belief.ply,
        "your_fen": belief.your_fen,
        "legal_actions": list(belief.legal_actions),
        "possible_actions": list(belief.possible_actions),
        "opponent_king": list(belief.opponent_king),
        "opponent_pawns": list(belief.opponent_pawns),
        "opponent_pieces": list(belief.opponent_pieces),
    }


def save_belief(game_id: str, belief: BeliefState) -> None:
    state = load_state()
    beliefs = state.get("beliefs")
    if not isinstance(beliefs, dict):
        beliefs = {}
    beliefs[game_id] = serialize_belief(belief)
    state["beliefs"] = beliefs
    save_state(state)


def maybe_play_game(game: dict[str, Any] | str) -> bool:
    if isinstance(game, str):
        ref = game
        ruleset = WILD16_RULESET
    else:
        ref = game_ref(game)
        ruleset = game_ruleset(game)
    if not ref or ruleset != WILD16_RULESET:
        return False

    state = get_json(f"/game/{ref}/state")
    if state.get("state") != "active" or state.get("turn") != state.get("your_color"):
        return False
    if "move" not in (state.get("possible_actions") if isinstance(state.get("possible_actions"), list) else []):
        return False

    belief = BeliefState.from_api_state(state, ruleset=ruleset)
    save_belief(ref, belief)
    actions = ranked_actions(belief)
    if not actions:
        return False

    for index, uci in enumerate(actions):
        result = post_json(f"/game/{ref}/move", {"uci": uci})
        logger.debug("%s: tried %s -> %s", ref, uci, result.get("announcement"))
        if result.get("move_done"):
            return True
        if index < len(actions) - 1:
            time.sleep(FAILED_MOVE_RETRY_DELAY_SECONDS)
    return False


def run_loop(poll_seconds: float) -> None:
    while True:
        try:
            mine = get_json("/game/mine/active")
            games = mine.get("games", [])
            if not isinstance(games, list):
                games = []
            maybe_create_lobby_game(games)
            maybe_join_bot_lobby_game(games)
            for game in active_games(games):
                maybe_play_game(game)
        except requests.RequestException as exc:
            logger.warning("poll failed: %s", exc)
        time.sleep(poll_seconds)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Darkboard-inspired Wild 16 bot.")
    parser.add_argument("--register", action="store_true", help="register the bot and store its bearer token")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="poll interval between API rounds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    apply_botplay_config_migration()
    maybe_restore_token()
    args = parse_args(argv or sys.argv[1:])

    if args.register:
        register_bot()
        return 0

    if not os.environ.get("KRIEGSPIEL_BOT_TOKEN"):
        logger.error("missing KRIEGSPIEL_BOT_TOKEN; run with --register first or set it in the environment")
        return 1

    run_loop(args.poll_seconds)
    return 0
