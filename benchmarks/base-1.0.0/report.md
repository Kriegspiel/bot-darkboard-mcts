# Darkboard MCTS 1.0 Wild 16 local baseline

- Generated: `2026-05-19T00:50:17Z`
- Bot: `darkboardmcts`
- Bot commit: `505b40bb8ac755ec176a4b207d79cec4e3e2c5c8`
- Ruleset: `wild16`
- Coverage complete: `True`

## Summary

| Games | W | L | D | Win rate | Illegal attempt rate | Avg tries / completed move | Avg turns | Timeout rate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 300 | 29 | 14 | 257 | 9.7% | 30.1% | 1.43 | 349.01 | 0.0% |

## Matchups

| Opponent | Opponent commit | Time budget | Games | W-L-D | Illegal rate | Avg tries | Avg turns | Timeout rate |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| `darkboardmcts-self` | `505b40bb8ac755ec176a4b207d79cec4e3e2c5c8` | 1s | 100 | 0-0-100 | 39.1% | 1.64 | 190.00 | 0.0% |
| `randobot` | `9b14973f6f7def42cd2b638f814fa4cdfa8b37c5` | 1s | 100 | 23-7-70 | 24.2% | 1.32 | 298.11 | 0.0% |
| `simpleheuristics` | `f852bcca8f42322ccffb6d1ab604d3a5ff361950` | 1s | 100 | 6-7-87 | 29.4% | 1.42 | 558.92 | 0.0% |

## Coverage

| Opponent | Target games | Matched games | Time budget | Status |
| --- | ---: | ---: | ---: | --- |
| `randobot` | 100 | 100 | 1s | `complete` |
| `simpleheuristics` | 100 | 100 | 1s | `complete` |
| `darkboardmcts-self` | 100 | 100 | 1s | `complete` |

## Collection

- Method: `local_ks_game_wild16`
- Runner: `darkboard-run-local-benchmark`
- Engine commit: `79be70e30b977e2f45e26840557920eaad75f7d8`
- Seed: `20260519`
- MCTS max iterations: `384`
- Selection rule: `visits`
- Max plies: `700`
- Raw archives committed: `False`

## Failure Modes

- `stalemate`: 126
- `adjudicated_max_plies`: 80
- `insufficient_material`: 51
- `checkmate`: 14

## Data Policy

- Includes only completed Wild 16 games involving the benchmark bot.
- Uses aggregate report data; no per-opponent modeling is produced.
- Treat incomplete coverage as a blocker for public strength claims.
