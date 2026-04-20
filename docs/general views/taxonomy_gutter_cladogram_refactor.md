  ## Summary

  Refactor the current taxonomy gutter from a rank-column overlay into a rooted visible cladogram that stays aligned to the existing codon overview and
  browse charts. The new design must:

  - root all visible phyla through their visible common ancestor
  - preserve informative internal splits instead of always visually collapsing back to phylum
  - keep leaf rows aligned to the existing chart y-axis and dataZoom
  - continue showing collapsed-descendant braces below the current display rank
  - stay off ECharts tree series
  - prefer a deterministic non-tree overlay, even if that overlay is plain DOM
    `SVG` rather than ECharts `graphic`

  This doc should be saved under docs/general views/taxonomy_gutter_cladogram_refactor.md when implementation mode resumes.

  ## Why The Current Gutter Fails

  The current implementation is not a tree. It is a rank-column lineage grid.

  Current failure modes:

  - visible phyla are not rooted through a shared ancestor/backbone
  - every row visually descends through the same rank ladder, even when the biologically informative split happens lower
  - unary paths are overdrawn, so examples like Scleractinia / Actiniaria / Anthoathecata look like “go to phylum, then leaf” instead of showing the split
    structure that matters
  - rank headers and tight columns make the gutter hard to read
  - the payload shape (columns, segments, per-row lineage) encourages a matrix layout instead of a cladogram layout

  The refactor must fix the model first, then the renderer.

  ## Phase 1: Replace The Data Model With A Rooted Visible Tree

  Goal:

  - make the backend payload describe a rooted visible tree, not a rank grid

  Implementation:

  - keep build_taxonomy_gutter_payload(...) as the public shared backend entrypoint
  - replace the current payload internals in apps/browser/stats/taxonomy_gutter.py
  - input remains:
      - visible taxon rows in chart order
      - StatsFilterState
      - optional collapse_rank
  - output becomes:
      - root
      - nodes
      - edges
      - leaves
      - maxDepth
      - collapseRank
      - collapsedChildRank

  Backend construction steps:

  1. Start from the visible chart taxa in their existing lineage-sorted row order.
  2. Fetch full ancestor chains for those taxa from TaxonClosure, including ranks above phylum.
  3. Compute the visible root as the lowest common ancestor of all visible taxa.
  4. Build the minimal rooted ancestor tree that connects the visible taxa.
  5. Mark visible chart taxa as leaves.
  6. Compute rowStart and rowEnd spans on every kept node from the leaf order.

  Tree compression rules:

  - preserve every internal node with 2 or more kept children
  - preserve the visible root even if unary
  - compress other unary chains by default
  - preserve the last unary ancestor before leaves only if it is needed to explain the visible split semantics
  - do not preserve nodes merely because they occupy a rank slot

  This is the rule that fixes “don’t always drill down to phylum.”

  Payload contract:

  - root: { nodeId, taxonId, taxonName, rank, depth }
  - nodes: flat list of kept nodes with:
      - nodeId
      - taxonId
      - taxonName
      - rank
      - parentNodeId
      - depth
      - isLeaf
      - isPreservedSplit
      - rowStart
      - rowEnd
  - edges: { parentNodeId, childNodeId }
  - leaves: one per visible chart row with:
      - nodeId
      - axisValue
      - rowIndex
      - taxonId
      - taxonName
      - rank
      - branchExplorerUrl
      - taxonDetailUrl
      - braceCount
      - braceLabel
      - showBrace
  - maxDepth: maximum preserved depth in the visible rooted tree

  Remove from the contract:

  - columns
  - segments
  - per-row lineage

  Caching:

  - cache the full rooted visible-tree payload
  - cache key must include:
      - ordered visible leaf taxon ids
      - filter_state.cache_key_data()
      - collapse_rank
      - payload version string
  - no separate “phylum cache”
  - rooted phylum connectivity comes from the rooted visible-tree payload itself

  Brace counting:

  - keep the current rule: brace counts are next-rank descendants inside the current filtered viewer scope
  - tie collapse depth to the current display rank in this refactor
  - species leaves never show braces

  ## Phase 2: Replace The Renderer With A Real Cladogram Overlay

  Goal:

  - render a readable rooted cladogram in the gutter using the existing chart container

  Implementation:

  - keep static/js/taxonomy-gutter.js as the shared frontend helper
  - replace the current rank-column renderer with a rooted dendrogram renderer based on the new payload
  - render the gutter in a DOM `SVG` overlay anchored to the same chart
    container rather than through ECharts `graphic` or `custom` series

  Rendering rules:

  - no rank headers
  - left-to-right dendrogram with constant horizontal step by preserved tree depth
  - draw one shared root/backbone
  - draw vertical parent spans and horizontal elbows to children
  - align leaves to the existing chart row centers via axisValue
  - place leaf labels after the final elbow
  - place terminal braces after leaf labels

  Label rules:

  - leaf labels are primary
  - internal labels render only on preserved branching nodes
  - do not label every ancestor
  - hide internal labels first when density rises
  - hide leaf labels only after the existing readability threshold is exceeded
  - tree lines and braces must remain visible even when text is reduced

  Layout rules:

  - gutter width = tree depth width + widest kept internal label + widest leaf label + widest brace label
  - codon chart grid left margin must reserve that width dynamically
  - the gutter overlay must receive the same explicit top/bottom bounds and
    visible row window as the chart
  - y alignment should be treated as one visible row = one explicit row center,
    not inferred from ECharts internals

  Interaction:

  - leaf label click uses the existing branchExplorerUrl
  - brace click uses the same drill-down target
  - internal split labels are not clickable in this pass

  ## Phase 3: Codon Integration And Feasibility Gate

  Goal:

  - prove the refactor on the codon overview and browse charts only

  Integration scope:

  - /browser/codon-ratios/ overview chart
  - /browser/codon-ratios/ browse chart
  - no inspect-chart integration

  Keep unchanged:

  - routes
  - query params
  - current chart metric payloads
  - current dataZoom behavior

  Feasibility gate for the non-tree overlay:

  - the chosen overlay approach stays only if all of these pass:
      - leaf rows remain pixel-aligned during initial render, dataZoom, and resize
      - rooted backbone can connect multiple phyla cleanly
      - preserved split nodes render correctly for one-phylum subsets
      - performance is acceptable for the current bounded row counts

  Fallback trigger:

  - if an ECharts-driven gutter cannot stay aligned after one implementation
    pass and a short debugging pass, pivot to a DOM `SVG` overlay instead of
    continuing to fight chart-internal geometry
  - do not mix multiple rendering models in the same implementation cut

  ## Phase 4: Tests, Acceptance, And Docs

  Backend tests:

  - multiple phyla visible:
      - payload root is above phylum
      - phylum branches share one rooted backbone
  - one-phylum visible subset:
      - deepest informative split is preserved
      - tree does not flatten back to phylum unnecessarily
  - cnidarian-style case:
      - Anthozoa-scoped and mixed-class examples preserve the actual branching node that explains Scleractinia / Actiniaria / Anthoathecata
  - species-level rows:
      - no brace labels
  - cached payload reuse:
      - identical visible scope reuses cached payload

  View tests:

  - codon view context includes the new rooted payload for overview and browse
  - no tests depend on columns, segments, or per-row lineage
  - page-local asset wiring still works

  Frontend checks:

  - node --check static/js/taxonomy-gutter.js
  - node --check static/js/repeat-codon-ratio-explorer.js

  Targeted Django tests:

  - web_tests.test_browser_stats
  - web_tests.test_browser_codon_ratios

  Manual acceptance criteria:

  - multiple phyla display one shared rooted tree
  - one-phylum subsets show the relevant lower split instead of a dumb phylum-first ladder
  - braces remain attached to the correct visible leaves
  - tree stays aligned through zoom and resize
  - readability is materially closer to a simple cladogram than to the current lineage matrix

  ## Public Interfaces

  Backend:

  - build_taxonomy_gutter_payload(...) remains the public builder but returns a rooted-tree payload

  Frontend:

  - static/js/taxonomy-gutter.js changes its consumed payload from:
      - columns, segments, terminals
  - to:
      - root, nodes, edges, leaves, maxDepth
  - the current practical rendering path is a DOM `SVG` overlay, not an
    ECharts `tree`, `graphic`, or `custom` series

  No route or query-param changes in this refactor.

  ## Assumptions

  - branch length is topological only; no evolutionary time scaling
  - the visible root is the lowest common ancestor of the visible taxa
  - collapse depth remains tied to the current display-rank selector
  - the first implementation target remains codon overview and browse only
  - ECharts tree series is a fallback path, not the default plan
