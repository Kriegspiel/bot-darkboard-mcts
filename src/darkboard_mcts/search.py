"""Search entrypoints for the Darkboard-inspired bot."""

from __future__ import annotations

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.evaluation import ranked_action_scores


def ranked_actions(belief: BeliefState) -> tuple[str, ...]:
    """Return deterministic candidate attempts for the current belief state."""

    return tuple(score.uci for score in ranked_action_scores(belief))


def choose_action(belief: BeliefState) -> str | None:
    """Choose the first deterministic action from a belief state."""

    actions = ranked_actions(belief)
    return actions[0] if actions else None
