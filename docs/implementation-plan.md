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
   - Backup tracks sampled average value for UCT selection while retaining the
     best sampled value only as a secondary ordering signal.
   - Runtime config supports 1s, 2s, 4s, and 8s budgets through
     `DARKBOARD_MCTS_TIME_BUDGET_SECONDS`, with `DARKBOARD_MCTS_MAX_ITERATIONS`
     as a second bound.
   - Move return defaults to best value and can still use most visited via
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
- blends in reviewed aggregate priors from an optional `priors.json`
- can generate repeatable benchmark reports from completed Wild 16 archives
- can generate local Wild 16 benchmark archives for reviewed bot-only baseline
  batches
- applies benchmark-driven endgame urgency when games become long or when
  public material suggests a conversion phase
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
   - Done for the initial benchmark reporting workflow.
   - Generate aggregate reports from prepared completed Wild 16 archive exports
     with `darkboard-benchmark-report`.
   - Generate reproducible local Wild 16 bot-only archive exports with
     `darkboard-run-local-benchmark` when a reviewed offline baseline is needed.
   - Use a manifest to require random bot, simple-heuristics, provider-backed
     model bots when available, previous-version, and self-play matchups.
   - Report bot commit, opponent commits, time budget, game count, ruleset,
     win/loss/draw counts, illegal-attempt rate, average tries per completed
     move, average turns, timeout rate, and representative failure modes.
   - Record collection method, runner, engine commit, seed, MCTS settings, and
     local adjudication cap in the report.
   - Treat incomplete manifest coverage as a blocker for public strength claims.
   - Keep actual game scheduling outside this bot runtime so benchmarks remain
     explicit, reviewed, and reproducible.

8. Priors and learning
   - Start with hand-built priors.
   - Done for the semi-manual aggregate workflow.
   - Load a reviewed `priors.json` when present, with `DARKBOARD_PRIORS_PATH`
     as an optional override.
   - Generate candidate priors from prepared completed Wild 16 archive exports
     with `darkboard-generate-priors`.
   - Learn aggregate opening piece-density priors, pawn movement tendencies,
     recapture and retaliation rates, and capture-chain lengths.
   - Keep hand-built priors as the fallback whenever the file is missing,
     malformed, incompatible, or not Wild 16.
   - Keep per-opponent priors out of the first version unless privacy and data
     retention rules are explicitly designed.
   - Do not let the live bot continuously learn from production games.

9. Benchmark-driven tuning
   - First baseline is committed under `benchmarks/base-1.0.0`.
   - Baseline covers 100 local Wild 16 games against `randobot`, 100 against
     `simpleheuristics`, and 100 against `darkboardmcts-self`.
   - Increase default illegal-attempt pressure after the baseline showed a
     30.1% illegal-attempt rate.
   - Add `DARKBOARD_ENDGAME_*` urgency weights after the baseline showed 257
     draws and 80 local max-ply adjudications.
   - Keep raw archive exports out of git; commit reviewed reports and manifests.

## Non-goals

- Exact reproduction of original Darkboard source code.
- Support for all Kriegspiel rulesets in the first version.
- A replacement for the deterministic referee engine in `ks-game`.
