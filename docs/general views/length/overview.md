# Length Viewer Overview

## Purpose

The length viewer is the first implemented browser stats page and the baseline
for the rest of the viewer family.

It already exists technically at:

- route: `/browser/lengths/`
- view: `RepeatLengthExplorerView`

This document explains how that implementation should be treated inside the
general-views architecture.

## Current baseline

The current length explorer already provides:

- normalized filter handling through the shared stats layer
- grouped taxon summaries over `CanonicalRepeatCall`
- a server-rendered summary table
- a page-local ECharts browse view
- branch drill-down and detail-page handoffs
- targeted tests for routing, filtering, drill-down, payload shape, and UX

Relevant existing docs:

- `docs/lengthview/plan.md`
- `docs/lengthview/implementation_plan.md`
- `docs/lengthview/session-log-2026-04-16.md`

## Where it fits in the 3-tier model

### `Tier 1 - Overview`

Target state:

- taxonomy-first `Taxon x Length-bin` hex overview
- lineage-aware taxon order on the shared overview axis
- count, normalized count, or log count by length bin as the cell value

This is still missing from the current browser and should be added on top of
the existing stats foundation.

### `Tier 2 - Browse`

Current baseline:

- the existing ranked length explorer at `/browser/lengths/`
- grouped taxon distributions with min, quartiles, median, and max

This is the part of the viewer that already works and should be preserved as
the browse baseline instead of being rewritten.

### `Tier 3 - Inspect`

Target state:

- branch- or taxon-focused statistical charts
- histogram and boxplot-style views for one lineage or filtered subset

This tier should build on the same normalized filters and bounded aggregate
rules as the current page.

## Reuse strategy

- keep the existing length explorer as the source of truth for stats-page
  structure
- only extract shared abstractions once the codon-composition viewer needs them
  too
- reuse the current filters, table behavior, branch handoff semantics, and
  chart payload patterns
- reuse the shared taxonomy gutter contract from
  `docs/general views/taxonomy_gutter_plan.md` when length charts need an
  explicit lineage axis
- add overview and inspect layers around the implemented browse layer rather
  than replacing it
- adopt the shared taxonomy-first overview shell instead of inventing a
  length-specific Tier 1 layout

## Design constraints

- do not regress the current length explorer while generalizing it
- keep the page meaningful without JavaScript
- keep visible result sets bounded through rank, `top_n`, `min_count`, and
  branch scope
- move lineage-aware ordering into reusable helpers before building the
  taxonomy-first hex overview
