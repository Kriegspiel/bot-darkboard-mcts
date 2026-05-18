import chess
import pytest

from darkboard_mcts import BeliefState, choose_action, ranked_actions


def test_belief_state_from_api_state_accepts_wild16_payload() -> None:
    belief = BeliefState.from_api_state(
        {
            "your_color": "white",
            "your_fen": "8/8/8/8/8/8/PPPPPPPP/RNBQKBNR w KQ - 0 1",
            "allowed_moves": ["e2e4", "d2d4"],
            "rule_variant": "wild16",
            "move_number": 1,
            "possible_actions": ["move"],
            "material_summary": {"white": {"pieces_remaining": 16}, "black": {"pieces_remaining": 16}},
            "referee_log": [{"announcement": "Move complete"}],
            "referee_turns": [{"turn": 1, "white": [], "black": []}],
        }
    )

    assert belief.color == chess.WHITE
    assert belief.ruleset == "wild16"
    assert belief.your_fen == "8/8/8/8/8/8/PPPPPPPP/RNBQKBNR w KQ - 0 1"
    assert belief.legal_actions == ("e2e4", "d2d4")
    assert belief.possible_actions == ("move",)
    assert belief.referee_log == ({"announcement": "Move complete"},)
    assert sum(belief.opponent_king) == pytest.approx(1.0)
    assert sum(belief.opponent_pawns) == pytest.approx(8.0)
    assert sum(belief.opponent_pieces) == pytest.approx(7.0)
    assert belief.opponent_king[chess.A1] == 0
    assert belief.opponent_pawns[chess.E2] == 0


def test_choose_action_is_deterministic_when_visible_board_is_missing() -> None:
    belief = BeliefState(
        color=chess.BLACK,
        visible_fen="",
        legal_actions=("g8f6", "b8c6"),
    )

    assert choose_action(belief) == "b8c6"
    assert ranked_actions(belief) == ("b8c6", "g8f6")


def test_belief_state_accepts_ruleset_context_when_state_omits_ruleset() -> None:
    belief = BeliefState.from_api_state(
        {
            "your_color": "black",
            "your_fen": "rnbqkbnr/pppppppp/8/8/8/8/8/8 b kq - 0 1",
            "allowed_moves": ["g8f6"],
            "move_number": 1,
        },
        ruleset="wild16",
    )

    assert belief.color == chess.BLACK
    assert belief.ruleset == "wild16"
    assert belief.legal_actions == ("g8f6",)


def test_scaffold_rejects_non_wild16_rulesets() -> None:
    with pytest.raises(ValueError, match="only 'wild16'"):
        BeliefState(color=chess.WHITE, visible_fen="", legal_actions=(), ruleset="berkeley")
