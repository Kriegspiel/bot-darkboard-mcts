import chess
import pytest

from darkboard_mcts import BeliefState, ranked_actions
from darkboard_mcts.evaluation import ranked_action_scores
from darkboard_mcts.priors import opponent_priors


def matrix(square: chess.Square, value: float) -> tuple[float, ...]:
    values = [0.0] * 64
    values[square] = value
    return tuple(values)


def test_opponent_priors_normalize_public_material_counts() -> None:
    priors = opponent_priors(
        visible_fen="8/8/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1",
        color=chess.WHITE,
        material_summary={"black": {"pieces_remaining": 13, "pawns_captured": 2}},
    )

    assert sum(priors.king) == pytest.approx(1.0)
    assert sum(priors.pawns) == pytest.approx(6.0)
    assert sum(priors.pieces) == pytest.approx(6.0)
    assert priors.king[chess.A1] == 0
    assert priors.pawns[chess.E2] == 0


def test_ranked_actions_prioritize_probable_capture_value() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/8/R6K w - - 0 1",
        legal_actions=("a1a2", "a1a8"),
        opponent_pieces=matrix(chess.A8, 1.0),
    )

    scores = ranked_action_scores(belief)

    assert [score.uci for score in scores] == ["a1a8", "a1a2"]
    assert scores[0].capture_value > scores[1].capture_value


def test_ranked_actions_reward_recent_capture_square() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/3P4/4K3 w - - 0 1",
        legal_actions=("d2d3", "d2e3"),
        referee_log=({"announcement": "Piece captured at E3"},),
    )

    scores = ranked_action_scores(belief)

    assert scores[0].uci == "d2e3"
    assert scores[0].recapture_bonus > 0


def test_ranked_actions_do_not_treat_straight_pawn_blocks_as_captures() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/3P4/4K3 w - - 0 1",
        legal_actions=("d2d3", "d2e3"),
        opponent_pawns=matrix(chess.D3, 1.0),
    )

    scores = ranked_action_scores(belief)

    assert scores[0].uci == "d2e3"
    assert next(score for score in scores if score.uci == "d2d3").capture_value < 0


def test_ranked_actions_reward_high_value_promotion() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/4P3/8/8/8/8/8/4K3 w - - 0 1",
        legal_actions=("e7e8n", "e7e8q"),
    )

    assert ranked_actions(belief)[0] == "e7e8q"


def test_action_scores_include_referee_outcome_probabilities() -> None:
    belief = BeliefState(
        color=chess.WHITE,
        visible_fen="8/8/8/8/8/8/3P4/4K3 w - - 0 1",
        legal_actions=("d2e3",),
    )

    score = ranked_action_scores(belief)[0]

    assert score.legal_probability == pytest.approx(0.0)
    assert score.capture_probability == pytest.approx(0.0)
    assert score.legality_penalty > 0
