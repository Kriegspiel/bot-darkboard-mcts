"""Belief-state primitives for the Darkboard-inspired bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import chess


WILD16_RULESET = "wild16"


@dataclass(frozen=True)
class BeliefState:
    """Player-visible state plus opponent probability placeholders.

    The public Darkboard papers describe three 8x8 probability matrices for the
    opponent king, pawns, and other pieces. This first value object reserves that
    shape while keeping the scaffold intentionally small.
    """

    color: chess.Color
    visible_fen: str
    legal_actions: tuple[str, ...]
    ruleset: str = WILD16_RULESET
    ply: int = 1
    game_id: str = ""
    game_state: str = ""
    turn: str | None = None
    possible_actions: tuple[str, ...] = ()
    material_summary: dict[str, Any] = field(default_factory=dict)
    referee_log: tuple[dict[str, Any], ...] = ()
    referee_turns: tuple[dict[str, Any], ...] = ()
    opponent_king: tuple[float, ...] = field(default_factory=lambda: (0.0,) * 64)
    opponent_pawns: tuple[float, ...] = field(default_factory=lambda: (0.0,) * 64)
    opponent_pieces: tuple[float, ...] = field(default_factory=lambda: (0.0,) * 64)

    def __post_init__(self) -> None:
        if self.ruleset != WILD16_RULESET:
            raise ValueError(f"only {WILD16_RULESET!r} is supported in this scaffold")
        if len(self.opponent_king) != 64:
            raise ValueError("opponent_king must contain 64 probabilities")
        if len(self.opponent_pawns) != 64:
            raise ValueError("opponent_pawns must contain 64 probabilities")
        if len(self.opponent_pieces) != 64:
            raise ValueError("opponent_pieces must contain 64 probabilities")

    @property
    def your_fen(self) -> str:
        """Return the API's player-projected board FEN."""
        return self.visible_fen

    @classmethod
    def from_api_state(cls, state: dict, *, ruleset: str | None = None) -> "BeliefState":
        """Build a scaffold belief state from a Kriegspiel API state payload."""
        color_name = str(state.get("your_color") or "").lower()
        if color_name not in {"white", "black"}:
            raise ValueError("state must include your_color as white or black")
        color = chess.WHITE if color_name == "white" else chess.BLACK
        allowed_moves = state.get("allowed_moves") if isinstance(state.get("allowed_moves"), list) else []
        legal_actions = tuple(move for move in allowed_moves if isinstance(move, str))
        possible_actions = state.get("possible_actions") if isinstance(state.get("possible_actions"), list) else []
        material_summary = state.get("material_summary") if isinstance(state.get("material_summary"), dict) else {}
        referee_log = state.get("referee_log") if isinstance(state.get("referee_log"), list) else []
        referee_turns = state.get("referee_turns") if isinstance(state.get("referee_turns"), list) else []
        return cls(
            color=color,
            visible_fen=str(state.get("your_fen") or state.get("visible_fen") or ""),
            legal_actions=legal_actions,
            ruleset=str(ruleset or state.get("rule_variant") or WILD16_RULESET),
            ply=int(state.get("ply") or state.get("move_number") or 1),
            game_id=str(state.get("game_id") or ""),
            game_state=str(state.get("state") or ""),
            turn=str(state.get("turn")) if state.get("turn") is not None else None,
            possible_actions=tuple(action for action in possible_actions if isinstance(action, str)),
            material_summary=material_summary,
            referee_log=tuple(item for item in referee_log if isinstance(item, dict)),
            referee_turns=tuple(item for item in referee_turns if isinstance(item, dict)),
        )
