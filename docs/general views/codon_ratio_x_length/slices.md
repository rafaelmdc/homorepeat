# Codon Ratio x Length Viewer Slices

## Goal

Build the main comparison viewer on top of the shared length and codon
foundations, with each slice remaining small enough to resemble a normal human
commit.

## Phase 1: Backend support and fallback page

### `CL1` Add binned codon-length summary helpers

Goal:

- produce one reusable summary layer for taxon x length-bin codon data

Scope:

- reuse the shared normalized stats filters
- reuse the shared length-bin definitions
- group by display taxon plus length bin
- summarize numeric `codon_ratio_value` plus count

Tests:

- broad-scope bin summaries
- branch-scoped bin summaries
- residue-specific behavior

Exit criteria:

- the backend can answer the core comparison question without page code

### `CL2` Add grouped taxon coverage summaries

Goal:

- make the comparison page understandable before charting

Scope:

- grouped HTML table showing which taxa and bins are represented
- current-scope summary text
- explicit empty states for no codon data vs no visible taxa

Exit criteria:

- the page has a meaningful no-JS fallback

### `CL3` Add the route and server-rendered page shell

Goal:

- land the comparison viewer as a browser page before visual polish

Scope:

- route: `/browser/codon-ratio-length/`
- URL-facing view under `apps/browser/views/stats/`
- shared filter form and shared summary-card conventions

Tests:

- route resolution
- default render
- fallback summary output

Exit criteria:

- the comparison viewer exists as a first-class browser route

## Phase 2: Overview first

### `CL4` Add the Tier 1 heatmap payload and chart

Goal:

- deliver the main overview as soon as the backend is ready

Scope:

- ECharts heatmap from taxon/bin codon summaries
- lineage-aware row order
- tooltip with taxon, bin, count, and codon summary

Tests:

- payload shape
- asset loading
- empty-state behavior

Exit criteria:

- the comparison viewer has its flagship overview state

### `CL5` Add overview drill-down behavior

Goal:

- let users move from broad comparison into narrower scopes

Scope:

- click cell or row to reopen the page with a narrower branch
- preserve relevant filter state
- keep drill-down behavior consistent with length and codon viewers

Tests:

- branch URL preservation
- rank stepping behavior

Exit criteria:

- overview exploration does not dead-end at the top level

## Phase 3: Browse and inspect tiers

### `CL6` Add small-multiple browse panels

Goal:

- let users compare a manageable set of taxa without a spaghetti plot

Scope:

- one trend panel per selected or visible taxon
- bounded visible taxon count
- reuse branch and rank filter semantics from the shared stats layer

Tests:

- payload shape for selected taxa
- bounded panel count behavior

Exit criteria:

- the comparison viewer has a usable Tier 2 browse layer

### `CL7` Add the inspect density view

Goal:

- support detailed analysis for one taxon or branch

Scope:

- 2D rectangular binned density plot over length and codon ratio
- one selected taxon, branch, or filtered subset
- no true hexbin implementation in the first pass

Tests:

- inspect payload shape
- single-branch render

Exit criteria:

- the comparison viewer spans all three tiers

## Phase 4: Optional companion view after the core viewer is stable

### `CL8` Add the pairwise comparison matrix in a separate mode

Goal:

- preserve the statistical comparison view without displacing the biological
  overview

Scope:

- separate tab, mode, or panel
- same lineage-aware ordering on both axes
- clearly positioned as a comparison/statistical layer

Exit criteria:

- the viewer has its optional matrix companion without confusing the primary
  browsing flow

### `CL9` Add discoverability and cross-viewer handoffs

Goal:

- connect the comparison viewer to the rest of the browser

Scope:

- browser home entry
- branch handoff from taxon detail
- optional jump from length or codon pages into the same scoped comparison

Exit criteria:

- codon ratio x length is discoverable through normal browser navigation
