"""Belief-state primitives for the Darkboard-inspired bot."""

from __future__ import annotations

from dataclasses import dataclass, field

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

    @classmethod
    def from_api_state(cls, state: dict) -> "BeliefState":
        """Build a scaffold belief state from a Kriegspiel API state payload."""
        color_name = str(state.get("your_color") or "").lower()
        if color_name not in {"white", "black"}:
            raise ValueError("state must include your_color as white or black")
        color = chess.WHITE if color_name == "white" else chess.BLACK
        allowed_moves = state.get("allowed_moves") if isinstance(state.get("allowed_moves"), list) else []
        legal_actions = tuple(move for move in allowed_moves if isinstance(move, str))
        return cls(
            color=color,
            visible_fen=str(state.get("visible_fen") or ""),
            legal_actions=legal_actions,
            ruleset=str(state.get("rule_variant") or WILD16_RULESET),
            ply=int(state.get("ply") or state.get("move_number") or 1),
        )

