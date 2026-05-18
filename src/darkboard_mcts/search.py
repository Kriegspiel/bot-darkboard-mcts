"""Search entrypoints for the Darkboard-inspired bot."""

from __future__ import annotations

from darkboard_mcts.belief import BeliefState


def choose_action(belief: BeliefState) -> str | None:
    """Choose an action from a belief state.

    This placeholder is deliberately simple. The next implementation step is to
    replace it with Approach C from Ciancarini and Favini's MCTS paper: UCT over
    player moves, probabilistic referee-message outcomes, one-move weighted
    evaluation, and quiescence over capture chains.
    """

    if not belief.legal_actions:
        return None
    return sorted(belief.legal_actions)[0]

