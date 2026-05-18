# Aggregate Priors Format

`priors.json` is an optional reviewed data file. The live bot may load it at
startup or during polling, but the bot does not write it and does not learn from
production games directly.

By default the bot looks for `priors.json` at the repository root. Set
`DARKBOARD_PRIORS_PATH` to point at a different reviewed file.

Generate a candidate file from a prepared archive export with:

```bash
darkboard-generate-priors games.jsonl priors.json --opening-plies 8 --blend 0.65
```

The generator accepts:

- a JSON array of game records
- a JSON object with a top-level `games` list
- a JSONL file with one game object per line

Only completed `wild16` games are included. Active games, non-Wild-16 games, and
malformed records are ignored.

## Schema

Schema version `1` is the current format.

Opening matrices are shortened in this example for readability; actual files
must contain 64 numbers for each matrix.

```json
{
  "schema_version": 1,
  "ruleset": "wild16",
  "generated_at": "2026-05-18T00:00:00Z",
  "blend": 0.65,
  "games_analyzed": 25,
  "source": {
    "kind": "completed_wild16_archives",
    "games_with_fen": 25,
    "games_with_moves": 25,
    "opening_plies": 8
  },
  "opening": {
    "white": {
      "samples": 225,
      "king": [1.0],
      "pawns": [1.0],
      "pieces": [1.0]
    },
    "black": {
      "samples": 225,
      "king": [1.0],
      "pawns": [1.0],
      "pieces": [1.0]
    }
  },
  "movement": {
    "white": {
      "pawn_rank_weights": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
      "pawn_file_weights": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    },
    "black": {
      "pawn_rank_weights": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
      "pawn_file_weights": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    }
  },
  "tactics": {
    "capture_opportunities": 10,
    "recaptures": 3,
    "recapture_rate": 0.3,
    "retaliations": 4,
    "retaliation_rate": 0.4,
    "capture_chain_lengths": {"2": 2},
    "capture_chain_length_average": 2.0
  },
  "data_policy": {
    "aggregate_only": true,
    "completed_wild16_only": true,
    "per_opponent_modeling": false,
    "live_learning": false
  }
}
```

The three `opening` matrices must contain 64 non-negative numbers in
`python-chess` square order: index `0` is `a1`, index `63` is `h8`. Runtime
loading rejects a side if any of its king, pawn, or piece matrices are missing
or contain no positive weights.

The pawn movement rank weights are side-relative: white index `0` is rank 1,
black index `0` is rank 8. File weights are board files from `a` to `h`.

`blend` is clamped to `0.0..1.0`. `0.0` keeps only hand-built priors; `1.0`
uses the reviewed aggregate opening priors wherever the public board and
material counts allow.

## Review Checklist

- Confirm `ruleset` is `wild16` and `schema_version` is `1`.
- Confirm `games_analyzed` matches the intended completed Wild 16 export.
- Confirm no player names, emails, tokens, or per-opponent identifiers are
  present.
- Inspect outlier-heavy matrices before deployment.
- Commit or deploy only the reviewed output, not the raw archive export.
