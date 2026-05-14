# Session Log

**Date:** 2026-05-12

## Objective

- Replace the outdated PolyGlutamine-in-Deuterostomes portfolio framing with a
  current PAARTA/PAASTA portfolio entry.
- Structure the new entry as Wagtail-compatible blocks that can be recreated in
  the custom portfolio CMS.
- Identify the small set of diagrams, screenshots, and figures that best
  communicate the project without turning the entry into a poster.
- Create editable Draw.io source diagrams for the portfolio visuals.

## What happened

- Reviewed the old exported portfolio HTML at
  `docs/PolyGlutamine in Deuterostomes.html`.
- Reviewed the portfolio Wagtail block definitions in `../portfolio/cms/models.py`
  and confirmed the available body blocks:
  - heading
  - paragraph
  - image
  - quote
  - embed
  - callout
  - code block
  - button
  - divider
  - spacer
  - gallery
  - section
  - PDF downloads
- Reframed the portfolio entry around the current project:
  - PAARTA as the Django/PostgreSQL web atlas and analysis browser
  - PAASTA as the sister Nextflow pipeline that produces published run artifacts
  - the old polyQ/deuterostome work as the origin story and example use case
- Read PAARTA documentation for browser, architecture, import, statistics, and
  export capabilities.
- Read the local sister pipeline repo at `../homorepeat_pipeline` and used its
  docs to accurately describe PAASTA:
  - accession-driven NCBI acquisition
  - CDS normalization
  - conservative translation
  - pure, threshold, and seed-extend repeat detection
  - codon finalization
  - publish contract v2
- Wrote a new block-structured draft:
  - page metadata
  - overview
  - system context
  - PAASTA pipeline section
  - PAARTA browser section
  - analysis views section
  - implementation section
  - example polyQ use case
  - outcome and next step
- Refined the visual plan to 8 visual assets across 6 Wagtail visual blocks:
  - PAARTA browser cover image
  - system architecture diagram
  - PAASTA workflow DAG
  - repeat-method/codon-validation concept diagram
  - PAARTA homorepeat table screenshot
  - analysis gallery with repeat-length, codon-composition, and codon-by-length
    screenshots
- Created a Draw.io-compatible diagram file with three editable pages:
  - `System architecture`
  - `PAASTA workflow DAG`
  - `Repeat methods and codon validation`
- Iterated the Draw.io styling:
  - first version used generic block diagrams
  - second version matched the portfolio dark/cyan palette
  - final version moved toward a more professional systems/article style with a
    light canvas, subsystem swimlanes, compact cards, and clearer grouping
- Added additional groups to the PAASTA workflow DAG so it reads as three phases:
  - setup and acquisition
  - detection fan-out
  - finalization and publication

## Files touched

- `docs/polyq_paarta_portfolio_entry_blocks.md`
- `docs/diagrams/paarta_paasta_portfolio_diagrams.drawio`
- `docs/journal/session-log-2026-05-12.md`

Existing untracked context file left untouched:

- `docs/PolyGlutamine in Deuterostomes.html`

## Validation

Successful checks run:

```text
python -m xml.etree.ElementTree docs/diagrams/paarta_paasta_portfolio_diagrams.drawio
```

Additional inspection commands were used to verify the portfolio block set,
PAARTA/PAASTA documentation claims, Draw.io page names, priority image markers,
and current git status.

## Current Status

- The new portfolio-entry draft is ready to use as a manual Wagtail build guide.
- The entry now foregrounds PAARTA/PAASTA capabilities rather than the old polyQ
  title.
- The Draw.io source file is editable and contains the three requested diagram
  figures.
- The diagrams are styled for portfolio/article use and should be exportable as
  PNG/SVG after any final manual layout tweaks in diagrams.net.

## Open Issues

- The actual PAARTA screenshots still need to be captured:
  - cover/browser table screenshot
  - homorepeat table screenshot
  - repeat-length explorer
  - codon-composition explorer
  - codon-composition-by-length explorer
- The old deuterostome polyQ run has not yet been imported into PAARTA under the
  current PAASTA publish contract.
- Public/deployed URLs for the portfolio button fields still need to be confirmed.

## Next Step

- Capture the live PAARTA screenshots for the visual slots in
  `docs/polyq_paarta_portfolio_entry_blocks.md`.
- Export the Draw.io pages as images and upload them into Wagtail.
- If time allows, import the legacy deuterostome polyQ run into PAARTA and use
  the resulting browser views for the analysis gallery.
