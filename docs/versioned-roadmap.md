# Versioned Roadmap

This roadmap tracks the path from the current Darkboard-inspired Wild 16 bot to
the fullest practical implementation of the public Darkboard paper trail.

The goal is to cover the published ideas as completely as possible:

- metapositions and compact uncertainty representation from the 2007 papers
- the MCTS Approach B/C line from the 2009 and 2010 papers
- engineering context from Favini's thesis
- benchmark discipline from the tournament and paper reports

The repo should still avoid claiming to be the original Darkboard unless the
original source appears with compatible licensing. The public papers do not
publish the full original constants, code, tuning corpus, or every evaluation
detail.

## Implementation Versions

### `0.3.0` - public-state one-ply evaluator

Status: shipped.

- Uses only public Kriegspiel API state.
- Builds hand-written opponent king, pawn, and generic-piece priors from public
  Wild 16 material counts.
- Ranks move attempts with deterministic one-ply scoring:
  - likely capture value
  - check pressure
  - recapture targets
  - pawn progress
  - promotion value
  - simple pawn-attack safety
- Keeps the deterministic evaluator as the fallback for all future search work.

Paper coverage:

- Starts the probability-matrix shape needed by the later MCTS papers.
- Does not yet update the matrices from observations over time.
- Does not yet implement MCTS.

### `0.4.0` - evidence and belief updates

Status: shipped.

Implemented persistent belief reconstruction from public referee evidence.

- Load the previous per-game belief snapshot before each turn.
- Update empty/path evidence from failed own attempts.
- Update movement evidence from legal non-captures.
- Update target-square evidence from captures, including pawn/piece type.
- Update king-density pressure from check direction announcements.
- Update pawn-density constraints from Wild 16 counted pawn tries.
- Diff opponent turns from public messages without using hidden board state.
- Persist updated belief after every move attempt and every completed turn.
- Keep all updates public-safe: no hidden board state and no per-opponent model.

Paper coverage:

- Covers the practical belief-maintenance layer needed before Approach B/C can
  be meaningful.
- Still uses hand-written priors when a game lacks enough observations.

### `0.5.0` - referee-message probability model

Status: shipped.

Implemented the first outcome model over public/referee messages.

- Estimate move legality from path occupancy, blockers, and king-safety risk.
- Estimate capture probabilities from destination-square pawn and piece density.
- Estimate check probability from king density over attacked squares.
- Estimate opponent recapture probability after our captures.
- Estimate vulnerability of checking pieces.
- Estimate probability that the opponent captures exposed friendly pieces.
- Expose model weights as config so they can be tuned without code changes.
- Log score components in debug mode for post-game analysis.
- Keep the model deterministic and public-state only so it can feed the later
  UCT tree.

Paper coverage:

- Covers the one-move probabilistic outcome model described for Approach B/C.
- Provides the inputs needed for UCT node expansion.

### `0.6.0` - MCTS Approach C core

Status: shipped.

Implemented the first successful later-paper search shape.

- Build a root from the current public belief state.
- Expand candidate player attempts from the API-exposed move attempts.
- Use UCT to allocate search across candidate attempts.
- Represent tree levels as:
  - bot move
  - own referee outcome
  - opponent outcome
- Evaluate new nodes with weighted one-move outcome probabilities.
- Use the max-style backup described for Approach C.
- Support time budgets of 1, 2, 4, and 8 seconds per move.
- Return a move using an empirically selected rule: most visited or best value.
- Fall back to the deterministic evaluator on timeout or malformed state.
- Keep the tree over public referee outcomes, not sampled hidden boards.

Paper coverage:

- This is the first version that should be described as Darkboard-inspired MCTS.
- It targets the 2009/2010 Approach C result rather than the weaker sampled-board
  Approach A.

### `0.7.0` - quiescence and tactical continuation

Status: shipped.

Implemented the first deterministic public-state quiescence layer.

- Estimate likely capture and recapture chains from the public outcome model.
- Prefer recaptures when the public referee log reveals the latest capture
  square.
- Penalize moves that likely lose high-value pieces immediately.
- Evaluate checking-piece vulnerability inside the tactical continuation layer.
- Improve promotion-race handling for near-promoting pawns and promotions.
- Avoid informative probes whose expected material loss dominates the modeled
  tactical gain.
- Expose quiescence weights as `DARKBOARD_QUIESCENCE_*` environment overrides.

Paper coverage:

- Covers the quiescence idea around short-horizon MCTS evaluation.
- Reduces the worst myopic failures of a one-ply model.

### `0.8.0` - metaposition-inspired abstraction layer

Status: shipped.

Implemented the first public-safe metaposition abstraction layer.

- Represents coarse metapositions as matrix/state abstractions rather than
  enumerated hidden boards.
- Adds abstraction helpers for possible king, pawn, piece, and aggregate
  occupancy.
- Adds evaluation terms inspired by the early Darkboard papers:
  - material balance
  - pawn advancement
  - multiple queens and promotion pressure
  - open files
  - friendly passed-pawn pressure on open files
  - controlled squares
  - king-edge and checkmating pressure
- Keeps this layer underneath the MCTS policy as a bounded positional leaf
  adjustment.
- Exposes metaposition weights as `DARKBOARD_METAPOSITION_*` environment
  overrides.

Paper coverage:

- Covers the core 2007 metaposition representation idea at an implementable
  Python/API boundary.
- Does not attempt a literal Java-class or minimax clone.

### `0.9.0` - semi-manual aggregate priors

Add optional learned priors from platform game data, but keep the workflow
reviewed and offline.

- Define a stable `priors.json` format.
- Let the bot load `priors.json` if present.
- Keep hand-built priors as the default fallback.
- Add an offline analysis script that can read completed Wild 16 archives later.
- Generate aggregate priors only from completed Wild 16 games.
- Learn opening piece-density priors.
- Learn pawn movement tendencies.
- Learn recapture and retaliation rates.
- Learn capture-chain lengths.
- Review generated priors before deploying them.

Data policy:

- Do not require manual PGN input.
- Do not let the live bot continuously learn from production data.
- Do not model individual opponents in this version.
- Do not store per-opponent priors unless a separate privacy and retention design
  is approved.

Paper coverage:

- Covers the game-statistics/prior idea from the Darkboard engineering context.
- Keeps the initial system conservative while there are still few local games.

### `1.0.0` - benchmarked public bot

Promote the bot from research runtime to benchmarked opponent.

- Run repeatable Wild 16 matches against:
  - random bot
  - simple-heuristics bot
  - current model bots when provider availability allows
  - previous Darkboard-inspired bot versions
  - self-play across time budgets
- Report:
  - bot commit
  - opponent commits
  - time budget
  - number of games
  - ruleset
  - win/loss/draw counts
  - illegal-attempt rate
  - average tries per completed move
  - average turns
  - timeout rate
  - representative failure modes
- Publish a public evaluation report before making strength claims.

Paper coverage:

- Matches the empirical reporting habit of the public Darkboard papers.
- Gives the platform its first real baseline for future research claims.

### `1.1.0+` - tuning and optional advanced research

Only after the paper-shaped implementation exists.

- Tune weights from benchmark data.
- Compare most-visited versus best-valued root selection.
- Add progressive widening if branching dominates runtime.
- Add stronger endgame-specific policies.
- Consider a separate metaposition/minimax comparison mode.
- Consider per-opponent modeling only after explicit privacy, retention, and
  product decisions.

## Coverage Matrix

| Source idea | First planned version |
| --- | --- |
| public API referee boundary | `0.3.0` |
| opponent king/pawn/piece probability matrices | `0.3.0` priors, `0.4.0` updates |
| observations from illegal moves and referee messages | `0.4.0` |
| probability of legality, capture, check, retaliation | `0.5.0` |
| MCTS over perceived messages, not sampled hidden boards | `0.6.0` |
| Approach C one-move horizon plus weighted outcomes | `0.6.0` |
| quiescence for capture/recapture chains | `0.7.0` |
| 2007 metaposition-inspired abstraction | `0.8.0` |
| aggregate game-log priors | `0.9.0` |
| paper-style benchmark report | `1.0.0` |

## Non-goals Until Explicitly Revisited

- Exact reproduction of the original Darkboard source.
- Hidden-board backend access.
- Continuous online learning from production games.
- Per-opponent modeling.
- Support for non-Wild 16 rulesets in the first serious implementation line.
