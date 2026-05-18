# Implementation Plan

This bot should be implemented as a Python service that uses the Kriegspiel API
as the referee. It should not replace `ks-game`; it should consume the legal
actions, submit attempts, and update its own uncertainty model from the public
referee announcements it receives.

For the release-by-release roadmap toward full public-paper coverage, see
[`versioned-roadmap.md`](./versioned-roadmap.md).

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
   - Done for the first deterministic runtime.
   - Converts `/game/{id}/state` payloads plus game metadata into `BeliefState`.
   - Submits selected attempts through `/game/{id}/move`.
   - Persists per-game belief snapshots between polling turns.
   - Restores previous snapshots before each turn and applies new public
     referee evidence before ranking attempts.

2. Probability matrices
   - Initial hand-built opponent king, pawn, and generic-piece 8x8 priors are
     implemented.
   - The priors normalize totals against public material counts.
   - Persistent evidence updates now adjust the matrices after failed own
     attempts, legal non-captures, captures, check announcements, pawn-try
     counts returned by the referee, and new public capture messages.

3. Referee-message model
   - Initial probability model estimates legality, path blockers, captures,
     check messages, recapture targets, checking-piece vulnerability, and
     exposed-piece capture risk from public belief matrices.
   - Model weights are configurable through `DARKBOARD_MODEL_*` environment
     overrides.
   - Initial move scoring consumes the model while keeping the deterministic
     one-ply evaluator as the fallback.
   - The model now feeds MCTS node expansion over public referee outcomes.

4. MCTS Approach C
   - Initial bounded MCTS core builds a three-tier public-outcome tree:
     player move, own referee outcome, opponent outcome.
   - UCT allocates iterations across API-exposed move attempts.
   - New nodes use weighted one-move outcome probabilities from the referee
     model.
   - Backup tracks max-observed branch value while retaining average value for
     UCT selection.
   - Runtime config supports 1s, 2s, 4s, and 8s budgets through
     `DARKBOARD_MCTS_TIME_BUDGET_SECONDS`, with `DARKBOARD_MCTS_MAX_ITERATIONS`
     as a second bound.
   - Move return can use most visited or best value via
     `DARKBOARD_MCTS_SELECTION_RULE`.

Current deterministic baseline:

- registers as a `wild16` bot
- polls `/game/mine/active`
- skips non-`wild16` games defensively
- ranks currently exposed move attempts with a deterministic one-ply evaluator
- scores attempts with a one-move public referee outcome model
- ranks attempts with bounded public-outcome MCTS
- adjusts volatile leaves with public-state quiescence estimates
- adds metaposition-inspired public-safe positional evaluation underneath MCTS
- retries attempts until one completes the turn or the ranked list is exhausted
- carries forward per-game opponent matrices from `.bot-state.json`
- applies referee evidence after each move attempt and on the next observed turn
- defaults to listed, one active game, automatic Wild 16 lobby creation, and a
  10% chance to join compatible bot-created Wild 16 lobbies when sampled

5. Quiescence
   - Initial deterministic public-state quiescence is implemented.
   - Rewards likely capture and recapture chains, especially when the public log
     reveals a capture square.
   - Penalizes moves that likely lose high-value pieces immediately.
   - Evaluates checking-piece vulnerability through the quiescence layer.
   - Adds promotion-race bonuses for near-promoting pawns and promotions.
   - Penalizes informative probes when modeled material risk dominates expected
     tactical value.
   - Quiescence weights are configurable through `DARKBOARD_QUIESCENCE_*`
     environment overrides.

6. Metaposition abstraction
   - Initial metaposition-inspired matrix abstraction is implemented.
   - Builds coarse public-safe state matrices from visible own pieces plus
     opponent king, pawn, and piece belief matrices.
   - Provides helpers for possible king, pawn, piece, and aggregate occupancy.
   - Adds evaluation terms for material balance, pawn advancement, promotion
     pressure, open files, friendly passed-pawn pressure, controlled squares,
     king-edge pressure, and checkmating pressure.
   - Keeps the layer underneath MCTS as a bounded positional leaf adjustment,
     not a separate hidden-board enumerator.
   - Metaposition weights are configurable through `DARKBOARD_METAPOSITION_*`
     environment overrides.

7. Benchmarks
   - Random bot matchups.
   - Simple-heuristics bot matchups.
   - Fixed opening-position tactical tests.
   - Time-budget sweeps at 1s, 2s, 4s, and 8s per move.

8. Priors and learning
   - Start with hand-built priors.
   - Generate priors from the platform's own completed Wild 16 games.
   - Keep per-opponent priors out of the first version unless privacy and data
     retention rules are explicitly designed.

## Non-goals

- Exact reproduction of original Darkboard source code.
- Support for all Kriegspiel rulesets in the first version.
- A replacement for the deterministic referee engine in `ks-game`.
