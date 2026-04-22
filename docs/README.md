# HomoRepeat Documentation

This directory contains the durable documentation for the HomoRepeat web
application. Historical working notes are kept in `journal/`; the other files
describe the current system contract.

## Documents

- [Usage](usage.md): local setup, imports, tests, and the main browser surfaces.
- [Architecture](architecture.md): Django app layout, data model, request flow,
  frontend chart structure, and production boundaries.
- [Statistics and Scientific Semantics](statistics.md): exact definitions for
  filters, rollups, length summaries, codon composition, codon-by-length
  summaries, pairwise metrics, support, and taxonomy gutters.
- [Operations](operations.md): import/backfill commands, cache behavior,
  validation, and maintenance notes.
- [Development Guide](development.md): contributor workflow, code organization,
  testing strategy, and safe change patterns.
- [Stat View Development](stat-view-development.md): practical guidance for
  adding or changing statistical browser views and ECharts integrations.
- [Journal](journal/): dated session logs and handoff notes. These are retained
  for project history, not treated as current implementation guidance.

## Documentation Principles

- Prefer stable contracts over implementation plans.
- Keep formulas and biological assumptions explicit.
- Document current behavior, not intended future behavior.
- Put transient planning and debugging notes in `journal/`, not in evergreen
  docs.
