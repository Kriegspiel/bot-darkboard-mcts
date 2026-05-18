import json

import chess
import pytest

from darkboard_mcts.prior_generation import generate_priors_payload, main, read_archive_records
from darkboard_mcts.priors import PRIORS_SCHEMA_VERSION, clear_aggregate_priors_cache, load_aggregate_priors, opponent_priors


@pytest.fixture(autouse=True)
def _clear_priors_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DARKBOARD_PRIORS_PATH", raising=False)
    clear_aggregate_priors_cache()
    yield
    clear_aggregate_priors_cache()


def test_opponent_priors_blend_reviewed_aggregate_priors(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    priors_path = tmp_path / "priors.json"
    priors_path.write_text(
        json.dumps(
            _runtime_priors_payload(
                pawns=_matrix({chess.D6: 1.0, chess.E6: 1.0}),
                movement_file_weights=[1.0, 1.0, 1.0, 5.0, 1.0, 1.0, 1.0, 1.0],
            )
        )
    )
    monkeypatch.setenv("DARKBOARD_PRIORS_PATH", str(priors_path))
    clear_aggregate_priors_cache()

    priors = opponent_priors(
        visible_fen="8/8/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1",
        color=chess.WHITE,
        material_summary={"black": {"pieces_remaining": 16, "pawns_captured": 0}},
    )

    assert load_aggregate_priors() is not None
    assert sum(priors.king) == pytest.approx(1.0)
    assert sum(priors.pawns) == pytest.approx(8.0)
    assert sum(priors.pieces) == pytest.approx(7.0)
    assert priors.king[chess.H8] == pytest.approx(1.0)
    assert priors.pawns[chess.D6] > priors.pawns[chess.E6]
    assert priors.pieces[chess.C8] == pytest.approx(7.0)


def test_invalid_reviewed_priors_fall_back_to_hand_built(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = opponent_priors(
        visible_fen="8/8/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1",
        color=chess.WHITE,
        material_summary={"black": {"pieces_remaining": 16, "pawns_captured": 0}},
    )
    priors_path = tmp_path / "priors.json"
    payload = _runtime_priors_payload(king=_matrix({chess.H8: 100.0}))
    payload["schema_version"] = PRIORS_SCHEMA_VERSION + 1
    priors_path.write_text(json.dumps(payload))
    monkeypatch.setenv("DARKBOARD_PRIORS_PATH", str(priors_path))
    clear_aggregate_priors_cache()

    with_invalid_file = opponent_priors(
        visible_fen="8/8/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1",
        color=chess.WHITE,
        material_summary={"black": {"pieces_remaining": 16, "pawns_captured": 0}},
    )

    assert load_aggregate_priors() is None
    assert with_invalid_file.king == pytest.approx(baseline.king)
    assert with_invalid_file.pawns == pytest.approx(baseline.pawns)
    assert with_invalid_file.pieces == pytest.approx(baseline.pieces)


def test_generate_priors_payload_uses_only_completed_wild16_games() -> None:
    games = [
        {
            "ruleset": "wild16",
            "status": "completed",
            "move_stack": ["e2e4", "d7d5", "e4d5", "d8d5", "g1f3"],
        },
        {"ruleset": "wild16", "status": "active", "move_stack": ["d2d4"]},
        {"ruleset": "classical", "status": "completed", "move_stack": ["e2e4"]},
    ]

    payload = generate_priors_payload(games, opening_plies=4, blend=0.8)

    assert payload["games_analyzed"] == 1
    assert payload["source"]["games_with_fen"] == 1
    assert payload["source"]["games_with_moves"] == 1
    assert payload["opening"]["white"]["samples"] == 5
    assert payload["opening"]["black"]["samples"] == 5
    assert payload["movement"]["white"]["pawn_file_weights"][chess.square_file(chess.D1)] > 1.0
    assert payload["movement"]["black"]["pawn_file_weights"][chess.square_file(chess.D1)] > 1.0
    assert payload["tactics"]["capture_opportunities"] == 2
    assert payload["tactics"]["recaptures"] == 1
    assert payload["tactics"]["retaliations"] == 1
    assert payload["tactics"]["capture_chain_lengths"] == {2: 1}
    assert payload["tactics"]["capture_chain_length_average"] == pytest.approx(2.0)
    assert payload["data_policy"]["aggregate_only"] is True
    assert payload["data_policy"]["per_opponent_modeling"] is False


def test_read_archive_records_accepts_jsonl_and_cli_writes_payload(tmp_path) -> None:
    archive_path = tmp_path / "games.jsonl"
    archive_path.write_text(
        "\n".join(
            [
                json.dumps({"ruleset": "wild16", "status": "completed", "move_stack": ["e2e4"]}),
                json.dumps({"ruleset": "wild16", "status": "active", "move_stack": ["d2d4"]}),
            ]
        )
        + "\n"
    )
    output_path = tmp_path / "priors.json"

    records = read_archive_records(archive_path)
    result = main([str(archive_path), str(output_path), "--opening-plies", "2", "--blend", "0.3"])
    generated = json.loads(output_path.read_text())

    assert len(records) == 2
    assert result == 0
    assert generated["blend"] == pytest.approx(0.3)
    assert generated["games_analyzed"] == 1


def _runtime_priors_payload(
    *,
    king: list[float] | None = None,
    pawns: list[float] | None = None,
    pieces: list[float] | None = None,
    movement_file_weights: list[float] | None = None,
) -> dict:
    return {
        "schema_version": PRIORS_SCHEMA_VERSION,
        "ruleset": "wild16",
        "blend": 1.0,
        "games_analyzed": 12,
        "opening": {
            "black": {
                "king": king or _matrix({chess.H8: 10.0}),
                "pawns": pawns or _matrix({chess.D6: 10.0}),
                "pieces": pieces or _matrix({chess.C8: 10.0}),
            }
        },
        "movement": {
            "black": {
                "pawn_rank_weights": [1.0, 1.0, 4.0, 1.0, 1.0, 1.0, 1.0, 1.0],
                "pawn_file_weights": movement_file_weights or [1.0] * 8,
            }
        },
        "tactics": {},
    }


def _matrix(values: dict[chess.Square, float]) -> list[float]:
    matrix = [0.0] * 64
    for square, value in values.items():
        matrix[square] = value
    return matrix
