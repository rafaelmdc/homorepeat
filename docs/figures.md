# Figures

## Purpose

This document freezes the reporting scope for Phase 0.

It does not define rendering code.
It defines which outputs the first reporting rebuild is expected to cover, and which figure families are explicitly deferred.

---

## Reporting principles

For v1:
- figures must be generated from finalized summary or regression-oriented outputs
- chart rendering must remain downstream-only
- ECharts is the planned charting layer for reproducible HTML/JSON outputs

Charts must not:
- derive biology directly from raw detection code
- invent grouping rules inside the rendering layer
- depend on undocumented front-end-only transformations

---

## Mandatory v1 reporting outputs

The first reporting rebuild is expected to cover these core outputs:

1. Taxon and method overview
   Purpose:
   show how many calls, genomes, and proteins are represented across methods and taxa

   Planned inputs:
   - `summary_by_taxon.tsv`

   Planned output forms:
   - grouped bar or stacked bar chart
   - accompanying inspectable ECharts options JSON

2. Repeat-length distribution by taxon, method, and repeat residue
   Purpose:
   show how tract-length distributions differ across taxa, repeat residues, and detection strategies

   Planned inputs:
   - finalized call tables or derived reporting tables

   Planned output forms:
   - histogram or other explicit binned distribution view
   - accompanying inspectable ECharts options JSON

3. Reproducible report bundle
   Purpose:
   provide one portable reporting artifact for review and sharing

   Planned outputs:
   - `echarts_options.json`
   - `echarts_report.html`

---

## Deferred reporting outputs

These figure families are valuable, but they do not block the first scientifically valid rebuild:

- sign-test heatmaps
- clustering-oriented heatmaps
- large supplementary panel grids
- publication-polish layouts for every figure variant
- annotation/domain-context visualizations
- repeat residue composition charts beyond the current overview and length-distribution blocks

These remain Phase 6 or later unless they are promoted explicitly.

---

## Relationship to the dissertation

The dissertation suggests several useful report families:
- database distribution summaries
- length-distribution comparisons across taxa and methods
- residue-specific codon-versus-length relationships
- pairwise or clustered comparative heatmaps

For v1, the rebuild should prioritize residue-neutral summary and distribution views first.
Residue-specific codon analyses can return in a later phase once the general homorepeat workflow is stable.

---

## Open decisions for later approval

No additional Phase 0 reporting-scope decisions are currently blocking the residue-neutral first release.
