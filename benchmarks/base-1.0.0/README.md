# Darkboard MCTS 1.0 Baseline Benchmark

This directory contains the reviewed baseline benchmark for
`bot-darkboard-mcts` `1.0.0`.

## Data

- [`manifest.json`](manifest.json) records the required matchup matrix and
  collection settings.
- [`report.json`](report.json) is the machine-readable benchmark report,
  including aggregate and per-game summary metrics.
- [`report.md`](report.md) is the human-readable version of the same report.

The raw local archive export was generated at
`/tmp/darkboard-base-1.0.0-archive.jsonl` while collecting the benchmark and was
not committed. The committed report is aggregate/per-game summary data only.

## Collection

The benchmark was collected on 2026-05-19 with:

```bash
PYTHONPATH=src /home/codex/dev/kriegspiel/bot-darkboard-mcts/.venv/bin/python \
  -m darkboard_mcts.local_benchmark \
  /tmp/darkboard-base-1.0.0-archive.jsonl \
  --manifest-output benchmarks/base-1.0.0/manifest.json \
  --games-per-matchup 100 \
  --matchups randobot,simpleheuristics,self \
  --benchmark-name "Darkboard MCTS 1.0 Wild 16 local baseline" \
  --bot-commit 505b40bb8ac755ec176a4b207d79cec4e3e2c5c8 \
  --random-commit 9b14973f6f7def42cd2b638f814fa4cdfa8b37c5 \
  --simple-commit f852bcca8f42322ccffb6d1ab604d3a5ff361950 \
  --engine-commit 79be70e30b977e2f45e26840557920eaad75f7d8 \
  --mcts-max-iterations 384 \
  --time-budget-seconds 1 \
  --max-plies 700 \
  --workers 6
```

Then the report was generated with:

```bash
PYTHONPATH=src /home/codex/dev/kriegspiel/bot-darkboard-mcts/.venv/bin/python \
  -m darkboard_mcts.benchmarking \
  /tmp/darkboard-base-1.0.0-archive.jsonl \
  benchmarks/base-1.0.0/report.md \
  --manifest benchmarks/base-1.0.0/manifest.json \
  --json-output benchmarks/base-1.0.0/report.json
```

## Notes

- All games used the local `ks-game` Wild 16 engine at commit
  `79be70e30b977e2f45e26840557920eaad75f7d8`.
- The benchmark bot alternated colors within each matchup.
- Self-play used a cloned opponent identity, `darkboardmcts-self`, so report
  attribution remains unambiguous.
- `80` of `300` games reached the 700-ply local adjudication cap; those are
  marked as `adjudicated_max_plies` in the report rather than hidden.
