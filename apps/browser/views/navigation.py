from urllib.parse import urlencode

from django.urls import reverse

from ..models import (
    AccessionCallCount,
    AccessionStatus,
    CanonicalGenome,
    CanonicalProtein,
    CanonicalRepeatCall,
    CanonicalRepeatCallCodonUsage,
    CanonicalSequence,
    DownloadManifestEntry,
    NormalizationWarning,
    PipelineRun,
    Taxon,
)


def _url_with_query(base_url: str, **params) -> str:
    cleaned_params = {key: value for key, value in params.items() if value not in ("", None)}
    if not cleaned_params:
        return base_url
    return f"{base_url}?{urlencode(cleaned_params)}"


def _nav_item(title: str, description: str, *, url_name: str, count: int | None = None, **params):
    item = {
        "title": title,
        "description": description,
        "url": _url_with_query(reverse(url_name), **params),
    }
    if count is not None:
        item["count"] = count
    return item


def _browser_directory_sections():
    homorepeat_count = CanonicalRepeatCall.objects.count()
    return [
        {
            "title": "Primary scientific tables",
            "description": "Start here for biology-first row-level browsing of homorepeats and codon usage profiles.",
            "items": [
                _nav_item(
                    "Homorepeats",
                    "Biology-first current homorepeat observations with organism, protein, repeat architecture, position, purity, and method.",
                    url_name="browser:homorepeat-list",
                    count=homorepeat_count,
                ),
                _nav_item(
                    "Codon Usage",
                    "Row-level repeat codon profiles with coverage, codon counts, profile percentages, and dominant codon.",
                    url_name="browser:codon-usage-list",
                    count=homorepeat_count,
                ),
            ],
        },
        {
            "title": "Statistical explorers",
            "description": "Taxon-level summaries and visual comparisons built from the current canonical repeat catalog.",
            "items": [
                _nav_item(
                    "Repeat lengths",
                    "Current-catalog repeat length explorer for lineage-aware browsing across grouped taxon summaries.",
                    url_name="browser:lengths",
                ),
                _nav_item(
                    "Codon ratios",
                    "Current-catalog codon-ratio explorer for lineage-aware browsing across residue-specific taxon summaries.",
                    url_name="browser:codon-ratios",
                ),
                _nav_item(
                    "Codon*length",
                    "Current-catalog codon-composition-by-length explorer for lineage-aware browsing across codon trajectories and branch-scoped inspect views.",
                    url_name="browser:codon-composition-length",
                ),
            ],
        },
        {
            "title": "Supporting catalog",
            "description": "Canonical entity browsers for accession, taxonomy, genome, sequence, protein, and technical repeat-call drill-down.",
            "items": [
                _nav_item(
                    "Accessions",
                    "Canonical accession records with current counts and supporting import history.",
                    url_name="browser:accession-list",
                    count=CanonicalGenome.objects.count(),
                ),
                _nav_item(
                    "Taxa",
                    "Lineage-aware taxonomy browser with links into the current catalog and related provenance.",
                    url_name="browser:taxon-list",
                    count=Taxon.objects.count(),
                ),
                _nav_item(
                    "Genomes",
                    "Current canonical genome catalog with links back to latest-run evidence.",
                    url_name="browser:genome-list",
                    count=CanonicalGenome.objects.count(),
                ),
                _nav_item(
                    "Sequences",
                    "Current canonical sequence records with explicit genome and run provenance.",
                    url_name="browser:sequence-list",
                    count=CanonicalSequence.objects.count(),
                ),
                _nav_item(
                    "Proteins",
                    "Current canonical proteins with genome, sequence, and taxon context.",
                    url_name="browser:protein-list",
                    count=CanonicalProtein.objects.count(),
                ),
                _nav_item(
                    "Repeat calls",
                    "Technical canonical repeat-call table with source identifiers and latest-run provenance.",
                    url_name="browser:repeatcall-list",
                    count=CanonicalRepeatCall.objects.count(),
                ),
                _nav_item(
                    "Codon usage rows",
                    "Canonical per-codon rows behind repeat-level codon usage profiles.",
                    url_name="browser:codonusage-row-list",
                    count=CanonicalRepeatCallCodonUsage.objects.count(),
                ),
            ],
        },
        {
            "title": "Run provenance",
            "description": "Secondary audit and troubleshooting views for import scope, run history, and cross-run provenance.",
            "items": [
                _nav_item(
                    "Imported runs",
                    "Run history view for provenance, import activity, and operator workflows.",
                    url_name="browser:run-list",
                    count=PipelineRun.objects.count(),
                ),
            ],
        },
        {
            "title": "Operational provenance",
            "description": "Raw side-artifact tables for acquisition, normalization, and status inspection.",
            "items": [
                _nav_item(
                    "Accession status",
                    "Run-aware operational ledger for download, detect, finalize, and terminal outcomes.",
                    url_name="browser:accessionstatus-list",
                    count=AccessionStatus.objects.count(),
                ),
                _nav_item(
                    "Method and residue status",
                    "Per-accession method and residue counts emitted by the raw pipeline.",
                    url_name="browser:accessioncallcount-list",
                    count=AccessionCallCount.objects.count(),
                ),
                _nav_item(
                    "Download manifest",
                    "Batch-scoped acquisition provenance retained from imported manifest rows.",
                    url_name="browser:downloadmanifest-list",
                    count=DownloadManifestEntry.objects.count(),
                ),
                _nav_item(
                    "Normalization warnings",
                    "Imported warning rows from raw acquisition and normalization outputs.",
                    url_name="browser:normalizationwarning-list",
                    count=NormalizationWarning.objects.count(),
                ),
            ],
        },
    ]
