# Implementation Plan

This bot should be implemented as a Python service that uses the Kriegspiel API
as the referee. It should not replace `ks-game`; it should consume the legal
actions, submit attempts, and update its own uncertainty model from the public
referee announcements it receives.

## Rule Set

Start with `wild16`, the Internet Chess Club / ICGA Computer Olympiad rule line
used by the public Darkboard papers. In platform terms this means:

- private illegal attempts
- pawn/piece capture announcements
- counted pawn tries for the next player
- check direction announcements
- no Berkeley `Any?`

## Milestones

1. API adapter
   - Convert `/game/{id}/state` payloads into `BeliefState`.
   - Submit selected moves through `/game/{id}/move`.
   - Persist per-game belief state between polling turns.

2. Probability matrices
   - Maintain opponent king, pawn, and generic-piece 8x8 matrices.
   - Normalize totals against public material counts.
   - Update matrices after empty-square evidence, captures, pawn-try counts, and
     opponent turns.

3. Referee-message model
   - Estimate move legality from path occupancy and pin/control probabilities.
   - Estimate capture probabilities from destination-square occupancy.
   - Estimate check probabilities from king-density over attacked squares.
   - Estimate opponent retaliation and capture risk.

4. MCTS Approach C
   - Build a three-tier tree: player move, own referee outcome, opponent outcome.
   - Use UCT for move selection.
   - Evaluate each new node with weighted one-move outcome probabilities.
   - Use max-style backup as described for Approach C.

5. Quiescence
   - Continue evaluation through forced or likely recapture chains.
   - Prefer immediate recaptures when the public log reveals a capture square.

6. Benchmarks
   - Random bot matchups.
   - Simple-heuristics bot matchups.
   - Fixed opening-position tactical tests.
   - Time-budget sweeps at 1s, 2s, 4s, and 8s per move.

7. Priors and learning
   - Start with hand-built priors.
   - Generate priors from the platform's own completed Wild 16 games.
   - Keep per-opponent priors out of the first version unless privacy and data
     retention rules are explicitly designed.

## Non-goals

- Exact reproduction of original Darkboard source code.
- Support for all Kriegspiel rulesets in the first version.
- A replacement for the deterministic referee engine in `ks-game`.

