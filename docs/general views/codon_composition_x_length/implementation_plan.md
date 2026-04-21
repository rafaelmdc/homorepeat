# Codon Composition x Length Implementation Plan

## Purpose

This document turns
[overview.md](/home/rafael/Documents/GitHub/homorepeat/docs/general views/codon_composition_x_length/overview.md)
into an execution sequence for refactoring the current codon-composition-by-length
viewer into the simpler first-wave design.

The plan starts from the current implemented baseline:

- `/browser/codon-composition-length/` exists
- `CodonCompositionLengthExplorerView` exists
- `templates/browser/codon_composition_length_explorer.html` exists
- `build_codon_length_composition_bundle(filter_state)` exists
- live and rollup-backed grouped bundle paths exist
- the server-rendered grouped fallback table exists
- the rejected `CL3.2` composition-glyph overview renderer is not the target

The goal is not to preserve the old "full composition glyph in every overview
cell" concept. The first-wave implementation should refactor the existing
bundle and page shell into simple overview matrices:

- signed preference matrix for 2-codon residues
- dominant-codon matrix for 3+ codon residues
- composition shift matrix for transitions
- optional secondary pairwise taxa similarity later

Full composition detail belongs in browse and inspect, not in every overview
cell.

## Product Boundary

This plan is for the browser viewer inside `apps.browser`.

Out of scope:

- changing `homorepeat_pipeline`
- introducing a second filter architecture
- adding mixed-residue codon aggregation
- shipping per-call codon x length rows to the browser
- rebuilding the first-wave overview around miniature per-cell composition
  glyphs or tiny stacked bars
- making pairwise taxa similarity the landing state

## Current Baseline To Keep

Keep these existing pieces and refactor around them:

- the route and view ownership for `/browser/codon-composition-length/`
- normalized stats filter handling and residue-required semantics
- the current grouped `matrix_rows` bundle shape as the source of truth
- live grouped query path for filtered scopes
- rollup-backed path for the broad default scope
- lineage ordering through existing shared helpers
- server-rendered fallback rows for no-JS usefulness and test coverage

The current bundle is already the right foundation because it carries:

- visible taxa
- visible codons
- visible length bins
- sparse per-taxon occupied bins
- codon shares
- observation and species support counts
- dominant codon and dominance margin

The refactor should derive all first-wave overview modes from this bundle. Do
not add separate database queries for preference, dominance, or shift.

## Core Data Contract

### Shared Bundle

Continue to use:

- `build_codon_length_composition_bundle(filter_state)`

Required bundle fields:

- `matching_repeat_calls_count`
- `visible_taxa_count`
- `total_taxa_count`
- `visible_codons`
- `visible_bins`
- `matrix_rows`

Each `matrix_rows[]` item should remain:

- `taxon_id`
- `taxon_name`
- `rank`
- `observation_count`
- `species_count`
- `bin_rows`

Each occupied `bin_rows[]` item should remain:

- `bin`
- `observation_count`
- `species_count`
- `codon_shares`
- `dominant_codon`
- `dominance_margin`

### Derived Overview Payloads

Add derived payload builders in the stats payload layer. They should accept the
shared bundle or the bundle's fields, not query the database.

Required payloads:

- preference overview payload for exactly 2 visible codons
- dominance overview payload for 3+ visible codons
- shift overview payload for all supported residues

Recommended behavior:

- the view chooses the default overview mode from `len(visible_codons)`
- 2 codons defaults to preference
- 3+ codons defaults to dominance
- shift is available as a companion mode when there are enough occupied adjacent
  bins to compute transitions

## Phase 1: Refactor The Existing Page Contract

### Slice `CL-R1`: Mark the current shell as the retained baseline

Goal:

- stop treating route, shell, bundle, rollup, and fallback table as future work

Scope:

- update docs and tests to describe the existing baseline as implemented
- keep the route, view, current filter controls, and fallback table
- adjust overview copy so it no longer promises a full composition matrix

Required behavior:

- no change to public route
- no change to filter semantics
- no change to no-JS fallback availability
- residue selection remains required for biological output

Exit criteria:

- the page reads as a summary-first codon-length viewer
- existing shell tests still pass after copy updates

### Slice `CL-R2`: Preserve and tighten the shared bundle

Goal:

- make the current bundle the single source of truth for all derived modes

Scope:

- keep `build_codon_length_composition_bundle(...)`
- keep live and rollup paths semantically equivalent
- add tests only where the new overview derivations need stronger guarantees

Required behavior:

- visible taxon order is lineage-aware before payload rendering
- visible codon order is fixed by the backend
- visible length-bin order is fixed by the backend
- absent codons inside occupied bins are represented as zero shares
- empty taxon-bin states stay absent rather than being fabricated as real data

Exit criteria:

- preference, dominance, shift, browse, inspect, and fallback can all derive
  from the same bundle

## Phase 2: Backend Overview Derivations

### Slice `CL-R3`: Add 2-codon signed preference payload

Goal:

- provide the default overview for 2-codon residues without tiny split bars

Scope:

- add a payload builder that runs only when `len(visible_codons) == 2`
- derive one cell per occupied `Taxon x Length-bin`
- use the first backend-ordered codon as codon A and the second as codon B

Required cell fields:

- row index or taxon id
- bin index or bin start
- preference score
- observation count
- species count
- tooltip codon shares

Preference definition:

- `preference = share(codon A) - share(codon B)`
- range is `[-1, 1]`
- negative means codon B preferred
- zero means balanced
- positive means codon A preferred

Required metadata:

- codon A
- codon B
- metric label
- support fields needed for opacity, marker, or tooltip display

Exit criteria:

- 2-codon residues can render a signed preference matrix directly from the
  payload
- no per-cell composition glyph data is required for the default overview

### Slice `CL-R4`: Add 3+ codon dominant-codon payload

Goal:

- provide the default overview for residues with 3 or more codons

Scope:

- add a payload builder that runs when `len(visible_codons) >= 3`
- derive one cell per occupied `Taxon x Length-bin`
- reuse existing `dominant_codon` and `dominance_margin` from the shared bundle

Required cell fields:

- row index or taxon id
- bin index or bin start
- dominant codon
- dominance margin
- observation count
- species count
- tooltip codon shares

Required metadata:

- fixed visible codon order
- category colors can be assigned frontend-side from backend codon order
- metric label for dominance margin

Exit criteria:

- 3+ codon residues can render a readable dominant-codon matrix
- full composition remains available in tooltip, browse, and inspect but is not
  drawn inside each overview cell

### Slice `CL-R5`: Add composition shift payload

Goal:

- expose where codon composition changes across adjacent length bins

Scope:

- derive transitions from the shared bundle
- compare only adjacent visible bins where the taxon has occupied data in both
  bins
- do not fabricate transitions across missing bins

Statistics:

- for 2-codon residues:
  - `abs(share_A(next_bin) - share_A(previous_bin))`
- for 3+ codon residues:
  - L1 distance across the normalized codon-share vectors

Required transition cell fields:

- row index or taxon id
- transition index
- previous bin
- next bin
- shift value
- previous support
- next support
- tooltip codon shares for both sides

Required metadata:

- transition labels
- metric label
- metric max or display domain for the heatmap legend

Exit criteria:

- users can identify stable taxa and sharp transition points without viewing
  full mixtures in every overview cell

## Phase 3: Simple Matrix Renderer

### Slice `CL-R6`: Add the first rectangular matrix renderer

Goal:

- prove row/bin binding with the simplest possible frontend renderer

Scope:

- add a page-specific JS module only if one does not already exist
- render rectangular heatmap-style cells from one payload
- start without taxonomy gutter unless the shared gutter path works with no
  extra chart-shape changes
- use backend-provided row order and bin order directly

Required behavior:

- no custom miniature SVG glyphs
- no tiny stacked bars
- no composition bars inside cells
- tooltip shows support and exact codon shares
- missing cells are blank, not zero-valued real observations

Exit criteria:

- the preference or dominance matrix renders correctly on the real dataset
- row labels, bin labels, cells, and tooltips bind to the same backend data

### Slice `CL-R7`: Wire default overview mode selection

Goal:

- make the page choose the correct simple landing view for the selected residue

Scope:

- if exactly 2 codons are visible, render preference by default
- if 3 or more codons are visible, render dominance by default
- if fewer than 2 codons are visible, show an explanatory empty state
- expose shift as a companion tab or segmented control once its payload exists

Required behavior:

- the user does not need to understand codon-count internals to get the right
  chart
- mode labels should describe the biological question, not implementation
  mechanics

Exit criteria:

- the landing overview is simple and residue-aware

### Slice `CL-R8`: Add support-aware cell styling

Goal:

- prevent sparse long bins from looking as reliable as dense central bins

Scope:

- start with one simple support encoding:
  - opacity by observation count, or
  - a subtle low-support marker
- show exact observation and species counts in tooltips

Required behavior:

- support styling must not obscure the preference or dominance encoding
- support thresholds should be conservative and documented in payload metadata
  or frontend constants

Exit criteria:

- low-support long-bin patterns are visibly lower-confidence

### Slice `CL-R9`: Add taxonomy gutter only after base binding is stable

Goal:

- restore lineage context without repeating the previous frontend failure mode

Scope:

- reuse the existing SVG taxonomy gutter path only after the matrix itself is
  correct
- keep row centers derived from the same visible row model as the matrix
- do not mix category labels, taxon ids, and row indices in the same renderer

Required behavior:

- gutter alignment is verified against the matrix at initial render and after
  zoom or pan
- if gutter integration destabilizes the chart, ship the simple matrix first
  and leave gutter as the next slice

Exit criteria:

- lineage context is added without compromising the chart binding

## Phase 4: Browse Layer Refactor

### Slice `CL-R10`: Add per-taxon small multiples from the shared bundle

Goal:

- preserve full composition detail where it is readable

Scope:

- one panel per selected or visible taxon
- fixed x-axis = backend length bins
- fixed codon order across panels
- reuse the same `matrix_rows` bundle

Rendering rules:

- for 2-codon residues:
  - line or area chart for codon A share is preferred
  - codon B is implied but can appear in tooltip or legend
- for 3+ codon residues:
  - stacked bars or stacked areas are preferred
  - avoid multi-line overlays for many codons

Exit criteria:

- users can read full codon-composition trajectories for selected taxa without
  overview clutter

### Slice `CL-R11`: Add support strips to browse panels

Goal:

- keep full composition trajectories support-aware

Scope:

- add a compact count strip or dot strip under each taxon panel
- use observation counts as the first support signal
- include species counts in tooltips where available

Exit criteria:

- long-bin composition changes remain visually tied to their support

### Slice `CL-R12`: Keep the grouped fallback table aligned

Goal:

- keep no-JS and testable output consistent with the refactored page

Scope:

- update table copy to match the new summary-first plan
- keep table rows derived from the same bundle
- include dominant codon, dominance margin, support, and codon shares

Exit criteria:

- no-JS output remains useful and describes the same visible data as the JS
  views

## Phase 5: Inspect Layer

### Slice `CL-R13`: Add focused inspect activation

Goal:

- provide exact codon-length detail for one taxon, branch, or filtered subset

Scope:

- start with branch-scoped inspect to match the current viewer family
- reuse the same filter-state and residue handling
- do not create a second filter system

Exit criteria:

- a focused lineage can be inspected without leaving the viewer contract

### Slice `CL-R14`: Add detailed chart and exact table

Goal:

- make Tier 3 the home for exact full-composition detail

Scope:

- render one detailed composition-across-length chart
- render one exact table with:
  - length bin
  - codon counts where available
  - codon fractions
  - support count
  - dominant codon
  - dominance margin
  - optional entropy or evenness
  - optional delta from previous bin

Required behavior:

- codon order matches browse
- length-bin order comes from the backend
- exact values match the bundle or focused inspect query

Exit criteria:

- exact composition values are available without overloading the overview

### Slice `CL-R15`: Add optional lineage comparison

Goal:

- provide context without turning inspect into a second dashboard

Scope:

- optionally compare the focused lineage with:
  - parent branch aggregate
  - selected reference taxon
  - sibling mean

Exit criteria:

- inspect gains context while remaining focused

## Phase 6: Optional Pairwise Taxa Similarity

### Slice `CL-R16`: Add secondary trajectory-similarity payload

Goal:

- support clustering and outlier detection without replacing the main overview

Scope:

- summarize each taxon's codon-length trajectory into a support-aware vector
- compute pairwise taxa distances
- present as a secondary tab, not the landing state

Required behavior:

- preserve the main `Taxon x Length-bin` overview as the primary page identity
- make clear that pairwise distance hides where along length taxa differ

Exit criteria:

- users can compare whole-trajectory similarity as a companion analysis

## Phase 7: Stabilization And Freeze

### Slice `CL-R17`: Verify performance and rendering on real data

Goal:

- ensure the simple matrix design works under realistic load

Scope:

- time bundle construction on the Compose/Postgres dataset
- verify default rollup path remains fast
- verify live path remains acceptable for filtered scopes
- test matrix rendering with dense bins and realistic visible taxa

Exit criteria:

- the viewer remains responsive under intended bounded settings

### Slice `CL-R18`: Freeze first-wave contract

Goal:

- document what shipped and mark deferred items explicitly

Scope:

- update overview and implementation docs after implementation settles
- record which modes shipped
- record which support encoding shipped
- record whether taxonomy gutter and pairwise similarity shipped or were
  deferred

Exit criteria:

- future work starts from a clear shipped contract

## Recommended Delivery Order

1. `CL-R1` to `CL-R2`
2. `CL-R3` and `CL-R4`
3. `CL-R6` and `CL-R7`
4. `CL-R5`
5. `CL-R8`
6. `CL-R9` if the simple matrix is stable
7. `CL-R10` to `CL-R12`
8. `CL-R13` to `CL-R15`
9. `CL-R16` only if a secondary pairwise view is still needed
10. `CL-R17` to `CL-R18`

Reasoning:

- keep the existing backend bundle and page shell
- derive simple overview payloads before adding frontend complexity
- ship preference/dominance first because they define the new landing state
- add shift next because it answers a distinct transition question
- delay gutter, browse, inspect, and pairwise until the simple matrix path is
  correct

## High-Risk Areas

- frontend matrix binding:
  - avoid mixing row indices, taxon ids, and category labels
- support encoding:
  - keep it subtle so it does not obscure the primary metric
- shift calculations:
  - do not fabricate transitions across missing bins
- taxonomy gutter:
  - add only after the base matrix is stable
- pairwise similarity:
  - keep secondary because it hides where along length differences occur

## Non-Negotiable Invariants

- residue is required for the page's main contract
- codon order stays fixed across browse and inspect
- length bins come from shared backend helpers
- visible taxa stay lineage-ordered
- support metadata remains first-class
- preference, dominance, and shift are derived from the shared bundle
- overview does not use tiny composition glyphs as the first-wave default
- default-path optimization must preserve the live grouped meaning
