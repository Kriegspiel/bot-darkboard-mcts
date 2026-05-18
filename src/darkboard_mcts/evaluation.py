"""One-ply evaluation for the Darkboard-inspired bot."""

from __future__ import annotations

from dataclasses import dataclass
import re

import chess

from darkboard_mcts.belief import BeliefState


PIECE_VALUES = {
    chess.PAWN: 100.0,
    chess.KNIGHT: 320.0,
    chess.BISHOP: 330.0,
    chess.ROOK: 500.0,
    chess.QUEEN: 900.0,
    chess.KING: 0.0,
}
GENERIC_OPPONENT_PIECE_VALUE = 360.0
CAPTURE_SQUARE_PATTERN = re.compile(r"\b([A-H][1-8])\b", re.IGNORECASE)


@dataclass(frozen=True)
class ActionScore:
    uci: str
    score: float
    capture_value: float = 0.0
    check_pressure: float = 0.0
    recapture_bonus: float = 0.0
    development: float = 0.0
    safety_penalty: float = 0.0


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

    piece_value = PIECE_VALUES.get(piece.piece_type, GENERIC_OPPONENT_PIECE_VALUE)
    capture_value = _capture_value(belief, move=move, piece=piece)
    check_pressure = _check_pressure(belief, board=board, move=move, piece=piece)
    recapture_bonus = _recapture_bonus(belief, move=move)
    development = _development_score(board=board, color=belief.color, move=move, piece=piece)
    safety_penalty = _safety_penalty(belief, target=move.to_square, piece_value=piece_value)

    score = capture_value + check_pressure + recapture_bonus + development - safety_penalty
    return ActionScore(
        uci=uci,
        score=score,
        capture_value=capture_value,
        check_pressure=check_pressure,
        recapture_bonus=recapture_bonus,
        development=development,
        safety_penalty=safety_penalty,
    )


def _visible_board(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _capture_value(belief: BeliefState, *, move: chess.Move, piece: chess.Piece) -> float:
    pawn_density = _density_at(belief.opponent_pawns, move.to_square)
    piece_density = _density_at(belief.opponent_pieces, move.to_square)
    if piece.piece_type == chess.PAWN and chess.square_file(move.from_square) == chess.square_file(move.to_square):
        return -min(1.0, pawn_density + piece_density) * 80.0
    return (min(1.0, pawn_density) * PIECE_VALUES[chess.PAWN]) + (
        min(1.0, piece_density) * GENERIC_OPPONENT_PIECE_VALUE
    )


def _check_pressure(belief: BeliefState, *, board: chess.Board, move: chess.Move, piece: chess.Piece) -> float:
    attacks = _attacks_after_move(board=board, move=move, piece=piece)
    king_density = sum(_density_at(belief.opponent_king, square) for square in attacks)
    return min(1.0, king_density) * 180.0


def _attacks_after_move(*, board: chess.Board, move: chess.Move, piece: chess.Piece) -> chess.SquareSet:
    if piece.piece_type == chess.PAWN:
        return chess.SquareSet(chess.BB_PAWN_ATTACKS[piece.color][move.to_square])

    projected = board.copy(stack=False)
    projected.remove_piece_at(move.from_square)
    promoted_type = move.promotion or piece.piece_type
    projected.set_piece_at(move.to_square, chess.Piece(promoted_type, piece.color))
    return projected.attacks(move.to_square)


def _recapture_bonus(belief: BeliefState, *, move: chess.Move) -> float:
    square = _latest_capture_square(belief)
    if square is None or square != move.to_square:
        return 0.0
    return 260.0


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

    if piece.piece_type == chess.ROOK and _file_has_no_own_pawns(board=board, color=color, file=chess.square_file(move.to_square)):
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


def _safety_penalty(belief: BeliefState, *, target: chess.Square, piece_value: float) -> float:
    pawn_attack_density = 0.0
    opponent = not belief.color
    for square, density in enumerate(belief.opponent_pawns):
        if density <= 0:
            continue
        if target in chess.SquareSet(chess.BB_PAWN_ATTACKS[opponent][square]):
            pawn_attack_density += density
    return min(1.0, pawn_attack_density) * piece_value * 0.25


def _density_at(matrix: tuple[float, ...], square: chess.Square) -> float:
    return matrix[square] if 0 <= square < len(matrix) else 0.0
