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
- a placeholder chooser that returns deterministic move attempts
- an implementation plan grounded in the public Darkboard papers
- tests for the scaffold and runtime loop

The championship-strength work is intentionally still ahead: probability
matrices, referee-message simulation, UCT tree search, quiescence handling,
game-log priors, and benchmarking.

The runtime is intentionally conservative:

- supports only `wild16`
- registers listed by default
- defaults to one active game
- auto-creates one open Wild 16 lobby game when below the active-game cap
- samples compatible bot-vs-bot lobby joins at most once per minute with 50% probability
- submits only public API move attempts and never receives hidden-board data

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
