# Length Viewer Slices

## Goal

Align the implemented length explorer with the new general-views architecture
without rewriting working code unnecessarily.

## Already complete baseline

These slices are already effectively done and should be treated as the starting
point, not re-implementation work:

### `L0.1` Shared stats foundation exists

- `apps/browser/views/stats/lengths.py`
- `apps/browser/stats/filters.py`
- `apps/browser/stats/queries.py`
- `apps/browser/stats/summaries.py`
- `apps/browser/stats/payloads.py`

### `L0.2` Browse page exists

- `/browser/lengths/`
- server-rendered grouped summary table
- page-local chart payload and JS

### `L0.3` Navigation and handoffs exist

- browser home discoverability
- taxon, protein, and repeat-call handoffs
- branch drill-down within the explorer

## Next slices

### `L1` Document the current page as the official Tier 2 baseline

Goal:

- stop treating the length explorer as a one-off page

Scope:

- align docs and page copy with the `Overview / Browse / Inspect` model
- treat the current ranked explorer as `Tier 2 - Browse`

Exit criteria:

- the project docs consistently describe `/browser/lengths/` as the length
  browse layer

### `L2` Extract only the first proven shared helpers

Goal:

- prepare for codon viewer reuse without broad refactoring

Scope:

- move repeated stats-page context assembly into a small shared helper or mixin
- extract any duplicated template partials only if the codon-composition viewer
  immediately reuses them

Exit criteria:

- shared abstractions exist only where length and codon already overlap

### `L3` Add reusable lineage-aware taxon ordering

Goal:

- make the future overview page biologically coherent

Scope:

- add one shared lineage-order helper for overview viewers
- keep the current browse page behavior stable unless the new helper is adopted
  explicitly

Exit criteria:

- the overview tier will not need page-local taxon-ordering logic

### `L4` Add length-bin summary queries

Goal:

- support the length overview without changing the browse page contract

Scope:

- add grouped bin counts by display taxon and length bin
- keep the same normalized stats filter contract
- return bounded, aggregated rows only

Tests:

- broad scope bin counts
- branch-scoped bin counts
- bin filtering under method, residue, and length constraints

Exit criteria:

- backend data exists for a `Taxon x Length-bin` overview

### `L5` Add a server-rendered overview fallback

Goal:

- prove the overview semantics before wiring the taxonomy-first chart layer

Scope:

- render a simple HTML fallback summary for visible taxon/bin combinations
- keep no-JS output meaningful

Exit criteria:

- the overview tier is understandable even before chart wiring

### `L6` Add the Tier 1 taxonomy-first hex overview

Goal:

- deliver the scalable overview page for length

Scope:

- ECharts taxonomy-first hex overview using the shared bin payload
- lineage-aware row order on the taxonomy axis
- tooltip with taxon, bin, and count information
- shared overview shell conventions aligned with the codon viewers

Tests:

- payload shape
- page-local asset loading
- empty-state behavior

Exit criteria:

- length has a real overview tier, not just a browse page

### `L7` Add Tier 3 inspect charts

Goal:

- support taxon- or branch-level inspection without leaving the viewer family

Scope:

- histogram and boxplot-style detail charts
- one selected taxon, branch, or filtered subset at a time
- reuse the same normalized filter state

Tests:

- inspect page with no JS
- inspect payload for one branch
- handoff from browse row into inspect state

Exit criteria:

- length now spans all three tiers

### `L8` Final polish and discoverability alignment

Goal:

- make the three tiers feel intentional and connected

Scope:

- tier navigation or view-mode switching
- consistent copy on browser home and handoff links
- docs updates if implementation details changed while landing the slices

Exit criteria:

- length is fully aligned with the general-views model
