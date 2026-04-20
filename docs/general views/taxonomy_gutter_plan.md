# Shared Taxonomy Gutter Implementation Plan

## Purpose

This document defines the shared taxonomy gutter used by taxonomy-first
browser charts.

It exists to make lineage-grouped taxon rows readable without replacing the
existing cartesian chart structure with a separate tree widget.

## Product contract

- the gutter sits to the left of the existing chart grid
- it draws lineage connectors for the visible taxon rows in chart order
- it stops explicit lineage rendering at the current display rank
- it shows a terminal `{` brace for hidden descendants below that rank
- the brace count reflects the current filtered viewer scope, not the raw
  taxonomy tree
- the current display rank is the collapse rank in v1

Example:

- if the display rank is `class`, the gutter draws lineage through `class`
  and shows `{ 1 order` or `{ N orders` beside each visible class row

## Shared backend contract

Backend ownership stays in `apps/browser/stats/`.

The shared payload builder should accept:

- the visible taxon summary rows in chart order
- the current normalized `StatsFilterState`
- an optional collapse rank override

The payload should return:

- `rows`: visible taxon rows with stable axis values and lineage entries
- `columns`: lineage ranks rendered in the gutter
- `segments`: contiguous row spans for ancestor connectors
- `terminals`: per-row labels and collapsed-descendant brace metadata
- `collapseRank`
- `collapsedChildRank`

Caching rules:

- cache the topology payload server-side
- include the ordered visible taxon ids, current filter-state cache key,
  collapse rank, and a helper version in the cache key
- do not cache pixel coordinates

## Shared frontend contract

Frontend ownership stays in one reusable page-local helper:

- `static/js/taxonomy-gutter.js`

The helper should:

- expose one small global API used by page-local chart scripts
- reserve gutter width from payload shape rather than hardcoding per viewer
- draw connectors, nodes, terminal labels, and braces in a DOM `SVG` overlay
  attached to the chart container
- redraw on initial render, `datazoom`, and resize
- keep working with the existing y-axis zoom window

Boundary:

- this is a non-tree overlay for cartesian browser charts, not a standalone
  ECharts `tree` chart
- the chart itself may still be rendered by ECharts, but the taxonomy gutter
  should not depend on ECharts `graphic` or `custom` series layout to align
  its rows

## First implementation target

The first wired viewer is codon composition:

- `/browser/codon-ratios/` overview chart
- `/browser/codon-ratios/` browse chart

The inspect chart is out of scope for the first pass.

Length and later taxonomy-first viewers should reuse the same backend payload
builder and the same shared frontend helper instead of creating viewer-local
tree code.

## Test expectations

- lineage columns are correct for mixed-clade visible rows
- terminal brace labels reflect next-rank descendants in the current filtered
  scope
- empty payloads stay valid
- cached payloads are reused for identical visible scope
- codon overview and browse contexts expose the gutter payload
- page-local JS stays valid after the shared helper is introduced
