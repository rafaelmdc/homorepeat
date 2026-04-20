# Codon Composition x Length Viewer Slices

## Goal

Build the main composition-first comparison viewer on top of the shared length
and codon-composition foundations, with each slice still small enough to land
incrementally.

## Phase 1: Backend support and fallback page

### `CXL1` Add binned codon-composition-by-length summary helpers

Goal:

- produce one reusable summary layer for taxon x length-bin composition data

Scope:

- reuse the shared normalized stats filters
- reuse the shared length-bin definitions
- group by display taxon plus length bin plus visible codons
- aggregate codon fractions with equal call weight

Tests:

- broad-scope bin summaries
- branch-scoped bin summaries
- 2-codon and 4-codon residue behavior

Exit criteria:

- the backend can answer the core comparison question without page code

### `CXL2` Add grouped taxon/bin fallback summaries

Goal:

- make the comparison page understandable before charting

Scope:

- grouped HTML fallback showing represented taxa, bins, and codon composition
- current-scope summary text
- explicit empty states for no codon-usage data vs no visible taxa

Exit criteria:

- the page has a meaningful no-JS fallback

### `CXL3` Add the route and server-rendered page shell

Goal:

- land the comparison viewer as a first-class browser page before visual polish

Scope:

- route: `/browser/codon-composition-length/`
- URL-facing view under `apps/browser/views/stats/`
- shared filter form and shared summary-card conventions

Tests:

- route resolution
- default render
- fallback summary output

Exit criteria:

- the comparison viewer exists as a browser route

## Phase 2: Overview first

### `CXL4` Add the Tier 1 taxonomy-first overview payload and chart

Goal:

- deliver the flagship overview as soon as the backend is ready

Scope:

- taxonomy-first `Taxon x Length-bin` hex overview
- mini stacked composition cells
- lineage-aware row order
- tooltip with taxon, length bin, call count, and codon shares

Tests:

- payload shape
- asset loading
- empty-state behavior

Exit criteria:

- the comparison viewer has its composition-first overview state

### `CXL5` Add overview drill-down behavior

Goal:

- let users move from broad comparison into narrower scopes

Scope:

- click cell or row to reopen the page with a narrower branch
- preserve relevant filter state
- keep drill-down behavior consistent with length and codon-composition viewers

Tests:

- branch URL preservation
- rank stepping behavior

Exit criteria:

- overview exploration does not dead-end at the top level

## Phase 3: Browse and inspect tiers

### `CXL6` Add per-taxon browse panels

Goal:

- let users compare a manageable set of taxa without flattening composition

Scope:

- one composition-across-length panel per selected or visible taxon
- bounded visible taxon count
- reuse branch and rank filter semantics from the shared stats layer

Tests:

- payload shape for selected taxa
- bounded panel-count behavior

Exit criteria:

- the comparison viewer has a usable Tier 2 browse layer

### `CXL7` Add inspect detail for one taxon or branch

Goal:

- support detailed analysis for one selected subset

Scope:

- detailed composition across length bins for one selected taxon, branch, or
  filtered subset
- composition table or chart views
- no scalar density fallback as the primary inspect model

Tests:

- inspect payload shape
- single-branch render

Exit criteria:

- the comparison viewer spans all three tiers

## Phase 4: Companion work after the core viewer is stable

### `CXL8` Add optional scalar companion modes only if needed

Goal:

- preserve secondary derived analyses without displacing the biological viewer

Scope:

- optional entropy, dominance, or other scalar summary modes
- clearly positioned as companion analytical views rather than the main product

Exit criteria:

- derived scalar views remain secondary to composition

### `CXL9` Add discoverability and cross-viewer handoffs

Goal:

- connect the comparison viewer to the rest of the browser

Scope:

- browser home entry
- branch handoff from taxon detail
- optional jump from length or codon-composition pages into the same scoped
  comparison

Exit criteria:

- codon composition x length is discoverable through normal browser navigation
