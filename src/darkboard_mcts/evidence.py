"""Evidence updates for Darkboard-style opponent belief matrices."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence
import re

import chess

from darkboard_mcts.belief import BeliefState
from darkboard_mcts.priors import opponent_priors


CAPTURE_SQUARE_PATTERN = re.compile(r"\b([A-H][1-8])\b", re.IGNORECASE)
CHECK_CODES = {
    "CHECK_RANK",
    "CHECK_FILE",
    "CHECK_LONG_DIAGONAL",
    "CHECK_SHORT_DIAGONAL",
    "CHECK_KNIGHT",
    "CHECK_DOUBLE",
}


def restore_belief_snapshot(belief: BeliefState, snapshot: Mapping[str, Any] | None) -> BeliefState:
    """Carry compatible persisted matrices into the current API state."""

    if not isinstance(snapshot, Mapping):
        return apply_referee_log_evidence(belief)

    if not _snapshot_is_compatible(belief, snapshot):
        return apply_referee_log_evidence(belief)

    restored = replace(
        belief,
        observed_referee_log_size=_bounded_log_size(snapshot.get("observed_referee_log_size")),
        opponent_king=_matrix_from_snapshot(snapshot.get("opponent_king"), fallback=belief.opponent_king),
        opponent_pawns=_matrix_from_snapshot(snapshot.get("opponent_pawns"), fallback=belief.opponent_pawns),
        opponent_pieces=_matrix_from_snapshot(snapshot.get("opponent_pieces"), fallback=belief.opponent_pieces),
    )
    restored = _renormalize_to_public_state(restored)
    return apply_referee_log_evidence(restored)


def apply_referee_log_evidence(belief: BeliefState) -> BeliefState:
    """Apply newly visible public referee-log evidence once."""

    start = min(belief.observed_referee_log_size, len(belief.referee_log))
    updated = belief
    for item in belief.referee_log[start:]:
        square = _capture_square(item)
        if square is not None:
            updated = _apply_capture(updated, square=square, captured_kind=_capture_kind(item), decrement=False)

    if updated.observed_referee_log_size != len(belief.referee_log):
        updated = replace(updated, observed_referee_log_size=len(belief.referee_log))
    return updated


def apply_move_result_evidence(belief: BeliefState, *, uci: str, result: Mapping[str, Any]) -> BeliefState:
    """Update belief from the immediate response to one of our own attempts."""

    updated = belief
    board = _visible_board(belief.visible_fen)
    move = _parse_move(uci)
    piece = board.piece_at(move.from_square) if board is not None and move is not None else None

    if not bool(result.get("move_done")):
        if board is not None and move is not None and piece is not None:
            updated = _apply_failed_attempt(updated, board=board, move=move, piece=piece)
        return _mark_attempt_observed(updated)

    if board is not None and move is not None and piece is not None:
        capture_square = _capture_square(result) or move.to_square
        if _capture_square(result) is not None:
            updated = _apply_capture(
                updated,
                square=capture_square,
                captured_kind=_capture_kind(result),
                decrement=True,
            )
        else:
            updated = _suppress_occupancy(updated, [move.to_square, *_path_squares(move=move, piece=piece)])

        updated = _apply_check_evidence(
            updated,
            board=board,
            move=move,
            piece=piece,
            gave_check=_has_check_announcement(result),
        )
        updated = _apply_next_turn_pawn_try_evidence(
            updated,
            board=_project_own_move(board=board, move=move, piece=piece),
            result=result,
        )

    return _mark_attempt_observed(updated)


def _snapshot_is_compatible(belief: BeliefState, snapshot: Mapping[str, Any]) -> bool:
    ruleset = snapshot.get("ruleset")
    if isinstance(ruleset, str) and ruleset and ruleset != belief.ruleset:
        return False

    color = snapshot.get("color")
    if isinstance(color, str) and color in {"white", "black"}:
        expected = "white" if belief.color == chess.WHITE else "black"
        if color != expected:
            return False

    game_id = snapshot.get("game_id")
    if isinstance(game_id, str) and game_id and belief.game_id and game_id != belief.game_id:
        return False

    return True


def _bounded_log_size(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _matrix_from_snapshot(value: Any, *, fallback: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return fallback
    if len(value) != 64:
        return fallback
    try:
        return tuple(max(0.0, float(item)) for item in value)
    except (TypeError, ValueError):
        return fallback


def _mark_attempt_observed(belief: BeliefState) -> BeliefState:
    return replace(belief, observed_referee_log_size=max(belief.observed_referee_log_size, len(belief.referee_log) + 1))


def _apply_failed_attempt(
    belief: BeliefState,
    *,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
) -> BeliefState:
    if piece.piece_type == chess.PAWN:
        from_file = chess.square_file(move.from_square)
        to_file = chess.square_file(move.to_square)
        if from_file != to_file:
            return _suppress_occupancy(belief, [move.to_square])
        return _boost_occupancy(belief, [move.to_square], amount=0.85)

    path = _path_squares(move=move, piece=piece)
    if path:
        return _boost_occupancy(belief, path, amount=0.85)

    if piece.piece_type in {chess.KNIGHT, chess.KING}:
        return _suppress_occupancy(belief, [move.to_square], factor=0.45)

    return belief


def _apply_capture(
    belief: BeliefState,
    *,
    square: chess.Square,
    captured_kind: str | None,
    decrement: bool,
) -> BeliefState:
    king = list(belief.opponent_king)
    pawns = list(belief.opponent_pawns)
    pieces = list(belief.opponent_pieces)
    captured_kind = (captured_kind or "").upper()

    if captured_kind == "PAWN":
        pawns[square] = 0.0
        totals = _effective_current_totals(belief)
        totals["pawns"] = max(0.0, totals["pawns"] - (1.0 if decrement else 0.0))
    elif captured_kind in {"PIECE", "KNIGHT", "BISHOP", "ROOK", "QUEEN"}:
        pieces[square] = 0.0
        totals = _effective_current_totals(belief)
        totals["pieces"] = max(0.0, totals["pieces"] - (1.0 if decrement else 0.0))
    else:
        totals = _effective_current_totals(belief)
        if belief.opponent_pawns[square] >= belief.opponent_pieces[square]:
            pawns[square] = 0.0
            pieces[square] *= 0.25
            totals["pawns"] = max(0.0, totals["pawns"] - (1.0 if decrement else 0.0))
        else:
            pieces[square] = 0.0
            pawns[square] *= 0.25
            totals["pieces"] = max(0.0, totals["pieces"] - (1.0 if decrement else 0.0))

    king[square] *= 0.1
    return _renormalize_to_public_state(
        replace(
            belief,
            opponent_king=tuple(king),
            opponent_pawns=tuple(pawns),
            opponent_pieces=tuple(pieces),
        ),
        totals=totals,
    )


def _suppress_occupancy(
    belief: BeliefState,
    squares: Sequence[chess.Square],
    *,
    factor: float = 0.08,
) -> BeliefState:
    king = _multiply_squares(belief.opponent_king, squares, factor=factor)
    pawns = _multiply_squares(belief.opponent_pawns, squares, factor=factor)
    pieces = _multiply_squares(belief.opponent_pieces, squares, factor=factor)
    return _renormalize_to_public_state(
        replace(belief, opponent_king=king, opponent_pawns=pawns, opponent_pieces=pieces),
        totals=_effective_current_totals(belief),
    )


def _boost_occupancy(
    belief: BeliefState,
    squares: Sequence[chess.Square],
    *,
    amount: float,
) -> BeliefState:
    pawns = _add_to_squares(belief.opponent_pawns, squares, amount=amount)
    pieces = _add_to_squares(belief.opponent_pieces, squares, amount=amount)
    return _renormalize_to_public_state(
        replace(belief, opponent_pawns=pawns, opponent_pieces=pieces),
        totals=_effective_current_totals(belief),
    )


def _apply_check_evidence(
    belief: BeliefState,
    *,
    board: chess.Board,
    move: chess.Move,
    piece: chess.Piece,
    gave_check: bool,
) -> BeliefState:
    attacks = tuple(_attacks_after_move(board=board, move=move, piece=piece))
    if not attacks:
        return belief

    if gave_check:
        king = _add_to_squares(belief.opponent_king, attacks, amount=0.5)
    else:
        king = _multiply_squares(belief.opponent_king, attacks, factor=0.72)
    return _renormalize_to_public_state(replace(belief, opponent_king=king), totals=_effective_current_totals(belief))


def _apply_next_turn_pawn_try_evidence(
    belief: BeliefState,
    *,
    board: chess.Board,
    result: Mapping[str, Any],
) -> BeliefState:
    exact_sources = _pawn_try_source_squares(result.get("next_turn_pawn_try_squares"))
    if exact_sources:
        return _renormalize_to_public_state(
            replace(belief, opponent_pawns=_add_to_squares(belief.opponent_pawns, exact_sources, amount=1.35)),
            totals=_effective_current_totals(belief),
        )

    count = result.get("next_turn_pawn_tries")
    if not isinstance(count, int):
        return belief

    candidate_sources = tuple(_opponent_pawn_sources_attacking_own_pieces(board=board, color=belief.color))
    if not candidate_sources:
        return belief

    if count <= 0:
        pawns = _multiply_squares(belief.opponent_pawns, candidate_sources, factor=0.08)
    else:
        pawns = _add_to_squares(belief.opponent_pawns, candidate_sources, amount=min(1.5, 0.35 * count))
    return _renormalize_to_public_state(replace(belief, opponent_pawns=pawns), totals=_effective_current_totals(belief))


def _renormalize_to_public_state(
    belief: BeliefState,
    *,
    totals: Mapping[str, float] | None = None,
) -> BeliefState:
    fresh = opponent_priors(
        visible_fen=belief.visible_fen,
        color=belief.color,
        material_summary=belief.material_summary,
    )
    totals = totals or {}
    king_total = totals.get("king", sum(fresh.king))
    pawn_total = totals.get("pawns", sum(fresh.pawns))
    piece_total = totals.get("pieces", sum(fresh.pieces))
    return replace(
        belief,
        opponent_king=_normalize_like(belief.opponent_king, fresh.king, total=king_total),
        opponent_pawns=_normalize_like(belief.opponent_pawns, fresh.pawns, total=pawn_total),
        opponent_pieces=_normalize_like(belief.opponent_pieces, fresh.pieces, total=piece_total),
    )


def _effective_current_totals(belief: BeliefState) -> dict[str, float]:
    fresh = opponent_priors(
        visible_fen=belief.visible_fen,
        color=belief.color,
        material_summary=belief.material_summary,
    )

    def total_or_fresh(current: float, fallback: float) -> float:
        return current if current > 0 else fallback

    return {
        "king": total_or_fresh(sum(belief.opponent_king), sum(fresh.king)),
        "pawns": total_or_fresh(sum(belief.opponent_pawns), sum(fresh.pawns)),
        "pieces": total_or_fresh(sum(belief.opponent_pieces), sum(fresh.pieces)),
    }


def _normalize_like(values: tuple[float, ...], fresh: tuple[float, ...], *, total: float) -> tuple[float, ...]:
    if total <= 0:
        return (0.0,) * 64

    masked = [max(0.0, value) if fresh[index] > 0 else 0.0 for index, value in enumerate(values)]
    current = sum(masked)
    if current <= 0:
        current = sum(fresh)
        if current <= 0:
            return (0.0,) * 64
        return tuple((value / current) * total for value in fresh)

    return tuple((value / current) * total for value in masked)


def _multiply_squares(
    matrix: tuple[float, ...],
    squares: Sequence[chess.Square],
    *,
    factor: float,
) -> tuple[float, ...]:
    out = list(matrix)
    for square in squares:
        if 0 <= square < 64:
            out[square] *= factor
    return tuple(out)


def _add_to_squares(matrix: tuple[float, ...], squares: Sequence[chess.Square], *, amount: float) -> tuple[float, ...]:
    out = list(matrix)
    for square in squares:
        if 0 <= square < 64:
            out[square] += amount
    return tuple(out)


def _visible_board(fen: str) -> chess.Board | None:
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _parse_move(uci: str) -> chess.Move | None:
    try:
        return chess.Move.from_uci(uci)
    except ValueError:
        return None


def _path_squares(*, move: chess.Move, piece: chess.Piece) -> tuple[chess.Square, ...]:
    if piece.piece_type not in {chess.BISHOP, chess.ROOK, chess.QUEEN}:
        return ()
    return tuple(chess.SquareSet(chess.between(move.from_square, move.to_square)))


def _project_own_move(*, board: chess.Board, move: chess.Move, piece: chess.Piece) -> chess.Board:
    projected = board.copy(stack=False)
    projected.remove_piece_at(move.from_square)
    promoted_type = move.promotion or piece.piece_type
    projected.set_piece_at(move.to_square, chess.Piece(promoted_type, piece.color))
    return projected


def _attacks_after_move(*, board: chess.Board, move: chess.Move, piece: chess.Piece) -> chess.SquareSet:
    if piece.piece_type == chess.PAWN:
        return chess.SquareSet(chess.BB_PAWN_ATTACKS[piece.color][move.to_square])

    projected = _project_own_move(board=board, move=move, piece=piece)
    return projected.attacks(move.to_square)


def _opponent_pawn_sources_attacking_own_pieces(*, board: chess.Board, color: chess.Color) -> tuple[chess.Square, ...]:
    own_squares = tuple(square for square, piece in board.piece_map().items() if piece.color == color)
    opponent = not color
    out: list[chess.Square] = []
    for source in chess.SQUARES:
        if board.piece_at(source) is not None:
            continue
        attacks = chess.SquareSet(chess.BB_PAWN_ATTACKS[opponent][source])
        if any(target in attacks for target in own_squares):
            out.append(source)
    return tuple(out)


def _capture_square(payload: Mapping[str, Any]) -> chess.Square | None:
    square = payload.get("capture_square")
    if isinstance(square, str):
        parsed = _parse_square(square)
        if parsed is not None:
            return parsed

    match = CAPTURE_SQUARE_PATTERN.search(_payload_text(payload))
    if match:
        return _parse_square(match.group(1))
    return None


def _capture_kind(payload: Mapping[str, Any]) -> str | None:
    explicit = payload.get("captured_piece_announcement")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip().upper()

    text = _payload_text(payload).lower()
    if "pawn captured" in text:
        return "PAWN"
    if any(f"{name} captured" in text for name in ("piece", "knight", "bishop", "rook", "queen")):
        return "PIECE"
    return None


def _has_check_announcement(payload: Mapping[str, Any]) -> bool:
    special = payload.get("special_announcement")
    if isinstance(special, str) and special.upper() in CHECK_CODES:
        return True

    text = _payload_text(payload).lower()
    return "check on " in text or "check by " in text or "double check" in text


def _pawn_try_source_squares(value: Any) -> tuple[chess.Square, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()

    squares: list[chess.Square] = []
    for item in value:
        if isinstance(item, int) and chess.A1 <= item <= chess.H8:
            squares.append(item)
        elif isinstance(item, str):
            parsed = _parse_square(item)
            if parsed is not None:
                squares.append(parsed)
    return tuple(dict.fromkeys(squares))


def _payload_text(payload: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("announcement", "message", "special_announcement"):
        value = payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    messages = payload.get("messages")
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
        parts.extend(item for item in messages if isinstance(item, str))
    return " ".join(parts)


def _parse_square(value: str) -> chess.Square | None:
    try:
        return chess.parse_square(value.lower())
    except ValueError:
        return None
