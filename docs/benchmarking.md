# Benchmark Reporting

`darkboard-benchmark-report` turns prepared completed Wild 16 archive exports
into a repeatable benchmark report. It does not create games, schedule bots, or
claim strength by itself.

Generate a report:

```bash
darkboard-benchmark-report games.jsonl report.md \
  --manifest benchmark.json \
  --json-output report.json
```

The archive input follows the same convention as the priors generator:

- a JSON array of game records
- a JSON object with a top-level `games` list
- a JSONL file with one game object per line

Only completed `wild16` games involving the benchmark bot are included.

For local bot-only baselines, `darkboard-run-local-benchmark` can drive the
`ks-game` Wild 16 engine in-process and write a compatible JSONL archive export.
Use it for reproducible offline baselines, not as a substitute for production
platform-game evidence.

## Manifest

The manifest records the intended benchmark matrix. Missing required matchups
are reported as coverage gaps.

```json
{
  "benchmark_name": "Darkboard MCTS 1.0 Wild 16 benchmark",
  "bot": {
    "username": "darkboardmcts",
    "commit": "botcommit"
  },
  "required_matchups": [
    {
      "opponent": "randobot",
      "opponent_commit": "randcommit",
      "time_budget_seconds": 1,
      "target_games": 20
    },
    {
      "opponent": "simpleheuristics",
      "opponent_commit": "simplecommit",
      "time_budget_seconds": 1,
      "target_games": 20
    },
    {
      "opponent": "gptnano",
      "provider_available": false,
      "target_games": 20
    }
  ],
  "collection": {
    "method": "local_ks_game_wild16",
    "runner": "darkboard-run-local-benchmark",
    "engine_commit": "enginecommit",
    "seed": 20260519,
    "mcts_max_iterations": 384,
    "selection_rule": "value",
    "max_plies": 700,
    "raw_archives_committed": false
  }
}
```

Fields:

- `bot.username`: benchmark bot username, default `darkboardmcts`
- `bot.commit`: bot commit under test
- `required_matchups[].opponent`: opponent username
- `required_matchups[].opponent_commit`: opponent commit, when known
- `required_matchups[].time_budget_seconds`: expected MCTS time budget
- `required_matchups[].target_games`: required completed-game count
- `required_matchups[].provider_available`: set `false` to record a model-bot
  provider outage as intentionally skipped
- `collection`: optional operator metadata copied into reports so readers can
  tell how the benchmark data was produced

## Metrics

The report includes:

- bot commit and opponent commits
- time budget
- number of completed Wild 16 games
- win/loss/draw counts
- illegal-attempt rate for the benchmark bot
- average tries per completed benchmark-bot move
- average turns
- timeout rate
- representative failure modes from non-win games and timeout games
- collection method and local benchmark settings when present in the manifest

Attempt metrics prefer completed-game scoresheets in `engine_state`; when those
are absent, the tool falls back to public `moves` or `attempts` arrays. That
keeps old exports usable while preserving the more accurate completed-review
shape when it is available.

## Coverage Rule

Treat `coverage.complete=false` as a blocker for public strength claims. A
partial report is still useful for debugging, but it is not a benchmark result.

Provider-backed model bots may be marked `provider_available=false`; those rows
are reported as `skipped_unavailable` rather than `missing`.

## Data Policy

- Include only completed Wild 16 games.
- Keep benchmark reports aggregate-only.
- Do not emit per-opponent models.
- Do not deploy raw archive exports.
- Do not use the live bot runtime for continuous benchmark learning.

## Committed Baselines

The first reviewed local baseline lives in
[`benchmarks/base-1.0.0`](../benchmarks/base-1.0.0):

- 100 games versus `randobot`
- 100 games versus `simpleheuristics`
- 100 games versus `darkboardmcts-self`
- 1.0.0 production MCTS defaults: 1 second, 384 max iterations, `visits` selection
- 700-ply local adjudication cap, reported as `adjudicated_max_plies`
