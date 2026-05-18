"""Search entrypoints for the Darkboard-inspired bot."""

from __future__ import annotations

import logging

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.evaluation import ranked_action_scores
from darkboard_mcts.mcts import ranked_actions_mcts


logger = logging.getLogger(__name__)


def ranked_actions(belief: BeliefState) -> tuple[str, ...]:
    """Return MCTS-ranked candidate attempts with deterministic fallback."""

    try:
        return ranked_actions_mcts(belief)
    except Exception as exc:  # pragma: no cover - defensive runtime fallback
        logger.warning("falling back to deterministic ranking: %s", exc)
        return tuple(score.uci for score in ranked_action_scores(belief))


def choose_action(belief: BeliefState) -> str | None:
    """Choose the first search-ranked action from a belief state."""

    actions = ranked_actions(belief)
    return actions[0] if actions else None
