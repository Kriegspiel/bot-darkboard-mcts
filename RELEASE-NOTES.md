# Release Notes

These notes summarize the packaged bot runtime release history reconstructed
from the current repository state. Add a new section at the top when the
package version changes or when runtime, deployment-facing, or user-visible bot
behavior changes. Test-only and docs-only changes do not need entries unless
they affect operator workflow.

## bot-darkboard-mcts v. 1.2.2

- **Bot Identity**: `darkboardmcts`, the listed Darkboard-inspired Wild 16 bot.
- **Rulesets**: supports `wild16` only and never reads hidden-board backend
  internals.
- **Runtime Shape**: runs one process with one lightweight runner thread per
  active game, defaults to one active game, restores per-game belief snapshots,
  and keeps local belief state in `.bot-state.json`.
- **Lobby Policy**: can keep one Wild 16 human-joinable lobby game open and can
  join compatible bot-created Wild 16 waiting games with 10% probability on a
  one-minute scan.
- **Policy**: samples public-state opponent priors, updates belief from referee
  evidence, ranks moves with bounded public-outcome MCTS, uses deterministic
  fallback evaluation, tactical quiescence, metaposition-inspired positional
  scoring, reviewed aggregate priors, and benchmark-driven endgame urgency.
- **Research Tooling**: includes repeatable benchmark reporting and local
  Wild 16 bot-only benchmark runs for reviewed baseline batches.
