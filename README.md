# bot-darkboard-mcts

Python research scaffold for a Darkboard-inspired Kriegspiel bot.

This repository is for a from-public-sources reimplementation of the ideas behind
Darkboard, the Bologna Kriegspiel program by Paolo Ciancarini and Gian Piero
Favini. It is not the original Darkboard source code.

The companion review is published at:

https://kriegspiel.org/blog/darkboard-kriegspiel-engine-review/

## Target ruleset

The first implementation target is `wild16`, the Internet Chess Club / ICGA
Computer Olympiad ruleset used by Darkboard in the public papers:

- players see only their own pieces
- opponent illegal attempts are private
- captures announce the square and whether the captured man was a pawn or piece
- checks announce rank, file, long diagonal, short diagonal, knight, or double
- the next player receives a counted pawn-try announcement
- there is no Berkeley-style `Any?` question

The implementation should eventually speak to the Kriegspiel API as an ordinary
bot runtime, using the backend as the referee and source of truth.

## Current scope

This repository now contains:

- a package skeleton for belief-state and MCTS work
- a minimal `BeliefState` value object
- a minimal API runtime for a `wild16` bot account
- hand-built opponent king/pawn/piece prior matrices from public material data
- persistent per-game belief restoration and referee-evidence updates
- a public referee-message probability model for one-move outcomes
- a bounded public-outcome MCTS core over move, referee, and opponent branches
- short tactical quiescence estimates for volatile captures, recaptures, and
  promotion races
- a metaposition-inspired matrix abstraction for public-safe positional scoring
- a deterministic one-ply evaluator for move attempts
- an implementation plan grounded in the public Darkboard papers
- a versioned roadmap for covering the public Darkboard paper ideas
- tests for the scaffold and runtime loop

The championship-strength work is intentionally still ahead: game-log priors,
tuning, and benchmarking.

The runtime is intentionally conservative:

- supports only `wild16`
- registers listed by default
- defaults to one active game
- auto-creates one open Wild 16 lobby game when below the active-game cap
- samples compatible bot-vs-bot lobby joins at most once per minute with 10% probability
- submits only public API move attempts and never receives hidden-board data
- stores only its own per-game belief matrices and referee-log cursor in `.bot-state.json`
- exposes one-move model weights through `DARKBOARD_MODEL_*` environment overrides
- searches public referee outcomes with bounded MCTS and falls back to the deterministic evaluator on malformed state
- applies deterministic public-state quiescence adjustments under
  `DARKBOARD_QUIESCENCE_*` environment overrides
- applies metaposition-inspired positional adjustments under
  `DARKBOARD_METAPOSITION_*` environment overrides

MCTS runtime controls:

- `DARKBOARD_MCTS_ENABLED`
- `DARKBOARD_MCTS_TIME_BUDGET_SECONDS` (clamped to 0-8 seconds)
- `DARKBOARD_MCTS_MAX_ITERATIONS`
- `DARKBOARD_MCTS_EXPLORATION`
- `DARKBOARD_MCTS_SELECTION_RULE` (`visits` or `value`)
- `DARKBOARD_MCTS_SEED`

Outcome model weights currently include:

- `DARKBOARD_MODEL_CAPTURE_VALUE_SCALE`
- `DARKBOARD_MODEL_CHECK_PRESSURE`
- `DARKBOARD_MODEL_RECAPTURE_BONUS`
- `DARKBOARD_MODEL_ILLEGAL_ATTEMPT_PENALTY`
- `DARKBOARD_MODEL_SAFETY_PENALTY_SCALE`
- `DARKBOARD_MODEL_CHECKING_PIECE_VULNERABILITY_SCALE`
- `DARKBOARD_MODEL_DEVELOPMENT_SCALE`
- `DARKBOARD_MODEL_LEGAL_DEVELOPMENT_FLOOR`

Quiescence weights currently include:

- `DARKBOARD_QUIESCENCE_CAPTURE_CHAIN_SCALE`
- `DARKBOARD_QUIESCENCE_RECAPTURE_CHAIN_SCALE`
- `DARKBOARD_QUIESCENCE_IMMEDIATE_LOSS_SCALE`
- `DARKBOARD_QUIESCENCE_CHECKING_PIECE_VULNERABILITY_SCALE`
- `DARKBOARD_QUIESCENCE_PROMOTION_RACE_SCALE`
- `DARKBOARD_QUIESCENCE_INFORMATIVE_PROBE_PENALTY_SCALE`
- `DARKBOARD_QUIESCENCE_MAX_ADJUSTMENT`

Metaposition weights currently include:

- `DARKBOARD_METAPOSITION_MATERIAL_BALANCE_SCALE`
- `DARKBOARD_METAPOSITION_PAWN_ADVANCEMENT_SCALE`
- `DARKBOARD_METAPOSITION_PROMOTION_PRESSURE_SCALE`
- `DARKBOARD_METAPOSITION_OPEN_FILE_SCALE`
- `DARKBOARD_METAPOSITION_FRIENDLY_OPEN_FILE_SCALE`
- `DARKBOARD_METAPOSITION_CONTROLLED_SQUARES_SCALE`
- `DARKBOARD_METAPOSITION_KING_EDGE_SCALE`
- `DARKBOARD_METAPOSITION_CHECKMATING_PRESSURE_SCALE`
- `DARKBOARD_METAPOSITION_MAX_ADJUSTMENT`

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Runtime

Create a local `.env` from `.env.example`, set the registration key and owner
email, then register and run:

```bash
python bot.py --register
python bot.py --poll-seconds 2
```

The same entrypoint is also exposed as:

```bash
darkboard-mcts-bot --poll-seconds 2
```

A production host can run the bot with
`deploy/kriegspiel-darkboard-mcts-bot.service` once credentials have been
created on that host. Set `KRIEGSPIEL_BOT_LISTED=false` only for private
testing accounts.

## Sources

Primary sources to keep close while implementing:

- Paolo Ciancarini and Gian Piero Favini, "Representing Kriegspiel States with
  Metapositions", IJCAI 2007.
- Paolo Ciancarini and Gian Piero Favini, "A Program to Play Kriegspiel", ICGA
  Journal 30(1), 2007.
- Paolo Ciancarini and Gian Piero Favini, "Monte Carlo Tree Search Techniques
  in the Game of Kriegspiel", IJCAI 2009.
- Paolo Ciancarini and Gian Piero Favini, "Monte Carlo Tree Search in
  Kriegspiel", Artificial Intelligence 174(11), 2010.
- Gian Piero Favini, "The dark side of the board: advances in chess
  Kriegspiel", PhD thesis, University of Bologna, 2010.
