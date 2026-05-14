# Page fields
#settings
title: PAARTA: Poly-Amino Acid Repeat Tract Atlas
subtitle: A pipeline-backed web atlas for browsing homorepeats, codon usage, taxonomy, provenance, and repeat-length statistics across annotated genomes.
tags: bioinformatics, comparative genomics, Django, Wagtail, Nextflow, Python, PostgreSQL, Celery, ECharts, PAARTA, PAASTA, homorepeats, codon usage
cover_image: Priority image 1: wide PAARTA browser screenshot. Prefer the homorepeat table with filters visible; use codon-composition-by-length only if it is visually stronger.
github_url: Add the public PAARTA repository URL when available.
external_url: Add the deployed browser URL when available.
#content
Use this page as the new portfolio entry. The old polyQ/deuterostome project becomes the origin story and example analysis, not the title or main scope.

Visual plan: 8 visual assets across 6 Wagtail image/gallery blocks. Use a browser screenshot as the cover, then include a system architecture diagram, a PAASTA pipeline DAG, a compact repeat-method/codon-validation concept figure, a PAARTA browser screenshot, and one analysis gallery with three screenshots.

#block Heading
#settings
level: h2
text: Overview
#content

#block Paragraph
#settings
none
#content
PAARTA is a database-backed web application for exploring protein homorepeats: single-amino-acid repeat tracts found across annotated genomes. It is designed as the browser and analysis layer for PAASTA, a sister Nextflow pipeline that downloads NCBI assembly annotation packages, normalizes CDS records, translates proteins, calls repeats, validates codon slices, and publishes compact tabular outputs.

Together, the two projects turn accession-driven genome analysis into a reproducible research system. PAASTA produces versioned run artifacts; PAARTA imports those artifacts into PostgreSQL, preserves run provenance, rebuilds a canonical biological catalog, and exposes the results through searchable tables, interactive statistical views, and downloadable TSV/FASTA exports.

#block Callout
#settings
style: info
title: What the system does
#content
Given annotated assembly accessions, PAASTA can produce repeat calls for one or more amino-acid residues. PAARTA then lets the user browse the calls by organism, taxonomy, protein, method, length, purity, codon usage, and run provenance, while also comparing repeat-length and codon-composition patterns across taxonomic groups.

#block Image
#settings
image: Priority image 2: system architecture diagram. Show "NCBI assembly accessions -> PAASTA Nextflow run -> publish contract v2 -> PAARTA import -> canonical catalog -> browser/statistics/downloads".
caption: "System overview: PAASTA performs accession-driven repeat discovery; PAARTA imports the published tables and serves them as a searchable atlas with statistical explorers."
alignment: wide
style: plain
max_width: xl
radius: md
shadow: sm
aspect: 16x9
alt_override: Diagram of PAASTA publishing pipeline outputs that PAARTA imports into browser and statistics views.
#content

#block Divider
#settings
none
#content

#block Heading
#settings
level: h2
text: Why It Exists
#content

#block Paragraph
#settings
none
#content
Homorepeats are easy to describe but hard to compare rigorously. A strict uninterrupted run, a density-based window, and a seed-and-extend definition can all describe plausible repeat tracts, but they do not recover identical biology. Without explicit method tracking, downstream comparisons can quietly become comparisons between repeat definitions.

The original motivation came from a polyglutamine case study in deuterostomes, where tract length and glutamine codon usage appeared to vary across lineages. PAARTA generalizes that work. Instead of building a one-off polyQ report, the system now treats repeat discovery as a reusable data product: every call is tied to a run, method, residue, protein, genome, taxon, codon profile, and import batch.

#block Quote
#settings
none
#content
The important shift was from "generate figures for one polyQ analysis" to "build an auditable atlas where repeat definitions, accession status, codon validation, and taxonomic grouping remain visible."

#block Divider
#settings
none
#content

#block Heading
#settings
level: h2
text: PAASTA Pipeline
#content

#block Paragraph
#settings
none
#content
PAASTA (Poly-Amino Acid Sequence Tract Analyzer) is the producing pipeline. It starts from a plain text list of NCBI assembly accessions, validates the inputs, downloads annotation packages, extracts and normalizes CDS records, translates retained proteins, and runs repeat detection for configurable amino-acid residues such as Q, N, A, or any standard one-letter residue code.

The pipeline currently supports three repeat-detection modes. Pure detection finds uninterrupted target-residue runs. Threshold detection uses a density rule, such as Q6/8, to tolerate limited interruptions. Seed-extend detection uses stricter seed windows and looser extension windows to recover longer interrupted tracts. All methods emit the same repeat-call schema, which makes method comparisons possible downstream.

After repeat detection, PAASTA attempts codon finalization. A repeat only receives a codon sequence when the nucleotide slice can be found, translated under the recorded translation table, and confirmed to match the amino-acid call exactly. Failed codon validation does not discard the repeat call; it leaves codon fields empty and records warnings, keeping amino-acid discovery separate from codon-level confidence.

#block Callout
#settings
style: note
title: Pipeline outputs
#content
The default publish contract includes repeat calls, run parameters, genomes, taxonomy, matched sequences, matched proteins, codon-usage rows, repeat context, accession status, call counts, normalization warnings, status summaries, a run manifest, and Nextflow diagnostics. Optional merged mode also builds SQLite and HTML report artifacts.

#block Image
#settings
image: Priority image 3: PAASTA workflow DAG. Show "accession planning -> NCBI package download -> CDS normalization -> translation -> repeat detection -> codon finalization -> published tables", with repeat detection split into pure, threshold, and seed-extend branches.
caption: "PAASTA workflow: annotated assemblies are normalized into proteins, scanned by multiple repeat definitions, checked against nucleotide codons where possible, and reduced into a stable publish contract."
alignment: wide
style: plain
max_width: xl
radius: md
shadow: sm
aspect: 16x9
alt_override: Workflow diagram of the PAASTA pipeline from accession planning to repeat detection and published tables.
#content

#block Image
#settings
image: Priority image 4: repeat-method and codon-validation concept figure. Use one protein strip with the same repeat region called by pure, threshold, and seed-extend, plus a small side path showing "AA coordinates -> CDS slice -> translate -> exact match -> codon usage".
caption: "Method and codon provenance: PAARTA can compare repeat definitions while keeping codon-level analyses restricted to calls whose nucleotide slice validates against the amino-acid repeat."
alignment: wide
style: plain
max_width: xl
radius: md
shadow: sm
aspect: 16x9
alt_override: Concept diagram comparing pure, threshold, and seed-extend repeat calls and showing codon validation from amino-acid coordinates to nucleotide slice.
#content

#block Code block
#settings
title: Example PAASTA run
language: bash
#content
nextflow run . \
  -profile docker \
  --accessions_file inputs/my_accessions.txt \
  --repeat_residues Q,N \
  --run_seed_extend true

#block Divider
#settings
none
#content

#block Heading
#settings
level: h2
text: PAARTA Browser
#content

#block Paragraph
#settings
none
#content
PAARTA is the web layer that makes those published runs usable. It is a Django application with a PostgreSQL backend, Celery workers for imports, graph pre-warming, and download generation, and a plain JavaScript/ECharts frontend for statistical exploration. Browser requests read from the database rather than from pipeline files, which keeps the UI responsive and makes imported runs durable.

The app stores two biological layers. The raw import layer preserves per-run observations linked to their original PipelineRun. The canonical layer serves the current browser catalog and records which run and import batch last touched each genome, protein, sequence, repeat call, and codon-usage row. This lets the browser show clean current data without losing provenance.

#block Section
#settings
background: soft
inner:
  - heading:
      level: h3
      text: Main browser surfaces
  - paragraph
  - callout
#content
Paragraph:
PAARTA includes list browsers for homorepeats, codon usage, runs, accessions, genomes, sequences, proteins, calls, warnings, accession statuses, call counts, and download manifests. Tables support search, filtering, ordering, virtual-scroll fragments, and TSV export. The homorepeat table also supports amino-acid FASTA and codon DNA FASTA downloads.

Callout settings:
style: info
title: Example workflow in the browser

Callout content:
Filter to a taxonomic branch, choose residue Q, compare pure and threshold calls, inspect the repeat-length distribution, switch to codon composition, then download the filtered calls and FASTA sequences for follow-up analysis.

#block Image
#settings
image: Priority image 5: PAARTA homorepeats table screenshot with filters, search, taxonomy, residue, method, length, and purity visible.
caption: "PAARTA browser: each canonical repeat call can be inspected by method, architecture, length, purity, position, protein, genome, organism, and taxonomy."
alignment: wide
style: frame
max_width: xl
radius: md
shadow: sm
aspect: 16x9
alt_override: Screenshot of the PAARTA homorepeat table with filters and repeat metadata.
#content

#block Divider
#settings
none
#content

#block Heading
#settings
level: h2
text: Analysis Views
#content

#block Paragraph
#settings
none
#content
The statistical views are built around biological questions rather than only database tables. Users can compare repeat-length distributions by taxonomic rank, inspect tail burden for long repeats, evaluate residue-specific codon composition, and study how codon usage changes across repeat-length bins. Filters include imported run, taxonomy branch, display rank, target search, detection method, repeat residue, length range, purity range, minimum observations, and visible top-N taxa.

Taxonomy is handled through an explicit closure table, so each species-level repeat call can be grouped at ranks such as phylum, class, order, family, genus, or species. Chart rows are ordered by lineage, and taxonomy gutters align cladogram-like context with ECharts axes so related taxa remain visually grouped.

#block Callout
#settings
style: tip
title: Codon analysis example
#content
For glutamine repeats, PAARTA can compare CAG and CAA shares by taxon and by repeat-length bin. For residues with more than two synonymous codons, it switches to dominance and similarity views, using codon-share vectors rather than forcing a two-codon interpretation.

#block Gallery
#settings
title: Priority analysis screenshots
columns: 3
images:
  - Priority image 6a: Repeat-length explorer, ideally showing overview heatmap plus branch inspect view or tail-burden mode.
  - Priority image 6b: Codon-composition explorer, residue Q selected, showing CAG/CAA preference or pairwise taxon similarity with taxonomy gutter visible.
  - Priority image 6c: Codon-composition-by-length explorer, showing CAG/CAA trajectories across 5-aa length bins with support trace.
#content
Use live PAARTA screenshots if available. These three should feel like result figures rather than UI decoration: filters open, taxonomic labels visible, and one clear biological question in each view.

#block Divider
#settings
none
#content

#block Heading
#settings
level: h2
text: Implementation
#content

#block Paragraph
#settings
none
#content
The implementation separates pipeline execution, import validation, canonical serving, and browser analytics. PAASTA owns acquisition and detection. PAARTA validates the published contract, streams TSVs into raw import tables, syncs the canonical catalog, rebuilds codon-composition rollups, and serves all normal browser views from PostgreSQL.

For large datasets, PAARTA avoids loading everything into one page. List views use cursor pagination and virtual scrolling. Import work runs in background Celery queues. Uploaded zipped runs are chunked, SHA-256 verified, safely extracted, validated, and copied into an app-managed run library before they can be imported. Heavy graph payloads and download artifacts are also background jobs, so the browser remains usable while data is being processed.

#block Section
#settings
background: contrast
inner:
  - heading:
      level: h3
      text: Design choices
  - paragraph
  - callout
#content
Paragraph:
The system favors explicit contracts over implicit file scraping. PAASTA publishes a versioned contract with stable TSV/JSON schemas, and PAARTA imports that contract rather than reaching into internal workflow directories. This keeps the boundary between pipeline and browser clean: the pipeline can change internally as long as the public contract remains valid.

Callout settings:
style: note
title: Accuracy boundary

Callout content:
PAARTA can show codon-composition analyses only for calls where PAASTA validated the nucleotide slice against the translated amino-acid repeat. Amino-acid repeat calls still remain available when codon validation fails, but they do not contribute to codon-share denominators.

#block Code block
#settings
title: PAARTA import path
language: text
#content
PAASTA publish/
  -> manifest and contract validation
  -> raw per-run import tables
  -> canonical genome/sequence/protein/repeat/codon catalog
  -> codon composition rollups
  -> searchable browsers, charts, and downloads

#block Divider
#settings
none
#content

#block Heading
#settings
level: h2
text: Example Use Case
#content

#block Paragraph
#settings
none
#content
The original polyglutamine-in-deuterostomes analysis is now best presented as an example of what PAARTA is meant to support. A researcher can run PAASTA on a curated accession set, import the published run into PAARTA, filter to Q repeats, compare strict and density-based calls, and inspect how CAG/CAA usage changes with repeat length across lineages.

The old analysis suggested that polyQ length and glutamine codon usage were linked, and that the trend varied by taxonomic group. PAARTA makes that kind of result easier to reproduce because the exact accession status, repeat method, codon validation status, taxonomic grouping, and filtered observations remain available beside the figure.

#block PDF downloads
#settings
title: Legacy polyQ materials
description: Optional context from the original BSc project.
documents:
  - label: Poster
    note: IJUP 2025 poster presentation.
    open_in_new: true
  - label: Report
    note: Final internship report.
    open_in_new: true
#content
Keep these as supporting historical materials, not as the primary project output.

#block Divider
#settings
none
#content

#block Heading
#settings
level: h2
text: Outcome
#content

#block Paragraph
#settings
none
#content
The result is no longer just a pipeline or a report. It is a two-part research platform: PAASTA produces auditable homorepeat calls from annotated assemblies, and PAARTA turns those calls into an interactive atlas for comparative biology. The system supports repeat discovery, method comparison, codon-level analysis, provenance tracking, import monitoring, and reusable exports from the same underlying data model.

The next step is to import the original deuterostome polyQ run under the current PAASTA contract and use PAARTA to regenerate the main biological summaries. That would close the loop between the initial case study and the newer browser implementation while making the old conclusions easier to inspect and extend.

#block Button
#settings
text: View PAARTA
url: https://github.com/rafaelmdc/homorepeat
variant: outline
#content
Use the deployed PAARTA URL or public repository URL. If neither is public yet, omit this block.
