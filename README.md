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

This initial repository contains:

- a package skeleton for belief-state and MCTS work
- a minimal `BeliefState` value object
- a placeholder chooser that returns deterministic legal actions
- an implementation plan grounded in the public Darkboard papers
- tests for the scaffold

The championship-strength work is intentionally still ahead: probability
matrices, referee-message simulation, UCT tree search, quiescence handling,
game-log priors, benchmarking, and API integration.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```

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

