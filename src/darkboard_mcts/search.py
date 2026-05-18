"""Search entrypoints for the Darkboard-inspired bot."""

from __future__ import annotations

from darkboard_mcts.belief import BeliefState


def ranked_actions(belief: BeliefState) -> tuple[str, ...]:
    """Return deterministic candidate attempts for the current belief state.

    This placeholder is deliberately simple. The next implementation step is to
    replace it with Approach C from Ciancarini and Favini's MCTS paper: UCT over
    player moves, probabilistic referee-message outcomes, one-move weighted
    evaluation, and quiescence over capture chains.
    """

    return tuple(sorted(dict.fromkeys(belief.legal_actions)))


def choose_action(belief: BeliefState) -> str | None:
    """Choose the first deterministic action from a belief state."""

    actions = ranked_actions(belief)
    return actions[0] if actions else None
