"""One-ply evaluation for the Darkboard-inspired bot."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re

import chess

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.endgame import EndgameWeights
from darkboard_mcts.endgame import evaluate_endgame_urgency
from darkboard_mcts.metaposition import MetapositionWeights
from darkboard_mcts.metaposition import evaluate_metaposition
from darkboard_mcts.outcome_model import GENERIC_OPPONENT_PIECE_VALUE
from darkboard_mcts.outcome_model import OutcomeModelWeights
from darkboard_mcts.outcome_model import PIECE_VALUES
from darkboard_mcts.outcome_model import estimate_referee_outcome
from darkboard_mcts.quiescence import QuiescenceWeights
from darkboard_mcts.quiescence import evaluate_quiescence


CAPTURE_SQUARE_PATTERN = re.compile(r"\b([A-H][1-8])\b", re.IGNORECASE)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionScore:
    uci: str
    score: float
    capture_value: float = 0.0
    check_pressure: float = 0.0
    recapture_bonus: float = 0.0
    development: float = 0.0
    safety_penalty: float = 0.0
    legality_penalty: float = 0.0
    checking_piece_vulnerability: float = 0.0
    legal_probability: float = 1.0
    capture_probability: float = 0.0
    check_probability: float = 0.0
    opponent_recapture_probability: float = 0.0
    exposed_piece_capture_probability: float = 0.0
    quiescence_adjustment: float = 0.0
    capture_chain_value: float = 0.0
    recapture_chain_value: float = 0.0
    immediate_loss_penalty: float = 0.0
    promotion_race_bonus: float = 0.0
    informative_probe_penalty: float = 0.0
    metaposition_adjustment: float = 0.0
    material_balance: float = 0.0
    pawn_advancement: float = 0.0
    promotion_pressure: float = 0.0
    open_file_value: float = 0.0
    friendly_open_file_value: float = 0.0
    controlled_squares: float = 0.0
    king_edge_pressure: float = 0.0
    checkmating_pressure: float = 0.0
    endgame_urgency: float = 0.0


def ranked_action_scores(belief: BeliefState) -> tuple[ActionScore, ...]:
    actions = tuple(dict.fromkeys(belief.legal_actions))
    board = _visible_board(belief.visible_fen)
    if board is None:
        return tuple(ActionScore(uci=uci, score=0.0) for uci in sorted(actions))

    scores = [evaluate_action(belief, board=board, uci=uci) for uci in actions]
    return tuple(sorted(scores, key=lambda item: (-item.score, item.uci)))


def evaluate_action(belief: BeliefState, *, board: chess.Board, uci: str) -> ActionScore:
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return ActionScore(uci=uci, score=-10_000.0)

    piece = board.piece_at(move.from_square)
    if piece is None or piece.color != belief.color:
        return ActionScore(uci=uci, score=0.0)

    weights = OutcomeModelWeights.from_env()
    latest_capture_square = _latest_capture_square(belief)
    outcome = estimate_referee_outcome(
        belief,
        board=board,
        move=move,
        piece=piece,
        latest_capture_square=latest_capture_square,
    )
    quiescence = evaluate_quiescence(
        belief,
        board=board,
        move=move,
        piece=piece,
        outcome=outcome,
        latest_capture_square=latest_capture_square,
        weights=QuiescenceWeights.from_env(),
    )
    metaposition = evaluate_metaposition(
        belief,
        board=board,
        move=move,
        piece=piece,
        outcome=outcome,
        weights=MetapositionWeights.from_env(),
    )
    endgame_urgency = evaluate_endgame_urgency(
        belief,
        move=move,
        piece=piece,
        outcome=outcome,
        weights=EndgameWeights.from_env(),
    )
    piece_value = PIECE_VALUES.get(piece.piece_type, GENERIC_OPPONENT_PIECE_VALUE)
    development_factor = weights.legal_development_floor + (
        (1.0 - weights.legal_development_floor) * outcome.legal_probability
    )
    capture_probability_factor = outcome.legal_probability if outcome.expected_capture_value >= 0 else 1.0
    capture_value = outcome.expected_capture_value * weights.capture_value_scale * capture_probability_factor
    check_pressure = outcome.check_probability * weights.check_pressure * outcome.legal_probability
    recapture_bonus = outcome.recapture_probability * weights.recapture_bonus * outcome.legal_probability
    development = (
        _development_score(board=board, color=belief.color, move=move, piece=piece)
        * weights.development_scale
        * development_factor
    )
    safety_penalty = outcome.exposed_piece_capture_probability * piece_value * weights.safety_penalty_scale
    checking_piece_vulnerability = (
        outcome.checking_piece_vulnerability * piece_value * weights.checking_piece_vulnerability_scale
    )
    legality_penalty = outcome.illegal_probability * weights.illegal_attempt_penalty

    score = (
        capture_value
        + check_pressure
        + recapture_bonus
        + development
        - safety_penalty
        - checking_piece_vulnerability
        - legality_penalty
        + quiescence.adjustment
        + metaposition.adjustment
        + endgame_urgency
    )
    action_score = ActionScore(
        uci=uci,
        score=score,
        capture_value=capture_value,
        check_pressure=check_pressure,
        recapture_bonus=recapture_bonus,
        development=development,
        safety_penalty=safety_penalty,
        legality_penalty=legality_penalty,
        checking_piece_vulnerability=checking_piece_vulnerability,
        legal_probability=outcome.legal_probability,
        capture_probability=outcome.capture_probability,
        check_probability=outcome.check_probability,
        opponent_recapture_probability=outcome.recapture_probability,
        exposed_piece_capture_probability=outcome.exposed_piece_capture_probability,
        quiescence_adjustment=quiescence.adjustment,
        capture_chain_value=quiescence.capture_chain_value,
        recapture_chain_value=quiescence.recapture_chain_value,
        immediate_loss_penalty=quiescence.immediate_loss_penalty,
        promotion_race_bonus=quiescence.promotion_race_bonus,
        informative_probe_penalty=quiescence.informative_probe_penalty,
        metaposition_adjustment=metaposition.adjustment,
        material_balance=metaposition.material_balance,
        pawn_advancement=metaposition.pawn_advancement,
        promotion_pressure=metaposition.promotion_pressure,
        open_file_value=metaposition.open_file_value,
        friendly_open_file_value=metaposition.friendly_open_file_value,
        controlled_squares=metaposition.controlled_squares,
        king_edge_pressure=metaposition.king_edge_pressure,
        checkmating_pressure=metaposition.checkmating_pressure,
        endgame_urgency=endgame_urgency,
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("action_score %s", action_score)
    return action_score


def _visible_board(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _latest_capture_square(belief: BeliefState) -> chess.Square | None:
    for item in reversed(belief.referee_log):
        square = item.get("capture_square")
        if isinstance(square, str):
            parsed = _parse_square(square)
            if parsed is not None:
                return parsed
        announcement = item.get("announcement")
        if isinstance(announcement, str) and "captured" in announcement.lower():
            match = CAPTURE_SQUARE_PATTERN.search(announcement)
            if match:
                parsed = _parse_square(match.group(1))
                if parsed is not None:
                    return parsed
    return None


def _parse_square(value: str) -> chess.Square | None:
    try:
        return chess.parse_square(value.lower())
    except ValueError:
        return None


def _development_score(*, board: chess.Board, color: chess.Color, move: chess.Move, piece: chess.Piece) -> float:
    if move.promotion:
        return PIECE_VALUES.get(move.promotion, 0.0) * 0.8

    if piece.piece_type == chess.PAWN:
        direction = 1 if color == chess.WHITE else -1
        rank_gain = (chess.square_rank(move.to_square) - chess.square_rank(move.from_square)) * direction
        file = chess.square_file(move.to_square)
        center_file_bonus = 8.0 - (2.0 * abs(file - 3.5))
        return (rank_gain * 16.0) + center_file_bonus

    if piece.piece_type in {chess.KNIGHT, chess.BISHOP} and _is_home_minor(color=color, square=move.from_square):
        return 32.0 + _centrality(move.to_square)

    if piece.piece_type == chess.ROOK and _file_has_no_own_pawns(
        board=board,
        color=color,
        file=chess.square_file(move.to_square),
    ):
        return 18.0

    return _centrality(move.to_square) - _centrality(move.from_square)


def _is_home_minor(*, color: chess.Color, square: chess.Square) -> bool:
    home_rank = 0 if color == chess.WHITE else 7
    return chess.square_rank(square) == home_rank and chess.square_file(square) in {1, 2, 5, 6}


def _file_has_no_own_pawns(*, board: chess.Board, color: chess.Color, file: int) -> bool:
    for rank in range(8):
        piece = board.piece_at(chess.square(file, rank))
        if piece == chess.Piece(chess.PAWN, color):
            return False
    return True


def _centrality(square: chess.Square) -> float:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    return 7.0 - (abs(file - 3.5) + abs(rank - 3.5))
