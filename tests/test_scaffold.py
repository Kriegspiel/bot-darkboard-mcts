import chess
import pytest

from darkboard_mcts import BeliefState, choose_action


def test_belief_state_from_api_state_accepts_wild16_payload() -> None:
    belief = BeliefState.from_api_state(
        {
            "your_color": "white",
            "visible_fen": "8/8/8/8/8/8/PPPPPPPP/RNBQKBNR w KQ - 0 1",
            "allowed_moves": ["e2e4", "d2d4"],
            "rule_variant": "wild16",
            "ply": 1,
        }
    )

    assert belief.color == chess.WHITE
    assert belief.ruleset == "wild16"
    assert belief.legal_actions == ("e2e4", "d2d4")


def test_choose_action_is_deterministic_placeholder() -> None:
    belief = BeliefState(
        color=chess.BLACK,
        visible_fen="",
        legal_actions=("g8f6", "b8c6"),
    )

    assert choose_action(belief) == "b8c6"


def test_scaffold_rejects_non_wild16_rulesets() -> None:
    with pytest.raises(ValueError, match="only 'wild16'"):
        BeliefState(color=chess.WHITE, visible_fen="", legal_actions=(), ruleset="berkeley")

