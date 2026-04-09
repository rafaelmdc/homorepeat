from django.contrib import admin

from .models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    DownloadManifestEntry,
    Genome,
    NormalizationWarning,
    PipelineRun,
    Protein,
    RepeatCall,
    RunParameter,
    Sequence,
    Taxon,
    TaxonClosure,
)


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ("run_id", "status", "profile", "acquisition_publish_mode", "imported_at")
    search_fields = ("run_id", "git_revision", "status", "profile", "acquisition_publish_mode")
    list_filter = ("status", "profile", "acquisition_publish_mode")


@admin.register(Taxon)
class TaxonAdmin(admin.ModelAdmin):
    list_display = ("taxon_name", "taxon_id", "rank", "parent_taxon")
    search_fields = ("taxon_name", "taxon_id", "rank")
    list_filter = ("rank",)


@admin.register(TaxonClosure)
class TaxonClosureAdmin(admin.ModelAdmin):
    list_display = ("ancestor", "descendant", "depth")
    search_fields = (
        "ancestor__taxon_name",
        "ancestor__taxon_id",
        "descendant__taxon_name",
        "descendant__taxon_id",
    )
    list_filter = ("depth",)


@admin.register(AcquisitionBatch)
class AcquisitionBatchAdmin(admin.ModelAdmin):
    list_display = ("pipeline_run", "batch_id")
    search_fields = ("pipeline_run__run_id", "batch_id")
    list_filter = ("pipeline_run",)


@admin.register(DownloadManifestEntry)
class DownloadManifestEntryAdmin(admin.ModelAdmin):
    list_display = ("assembly_accession", "pipeline_run", "batch", "download_status", "package_mode")
    search_fields = ("assembly_accession", "pipeline_run__run_id", "batch__batch_id", "download_status")
    list_filter = ("pipeline_run", "batch", "download_status", "package_mode")


@admin.register(NormalizationWarning)
class NormalizationWarningAdmin(admin.ModelAdmin):
    list_display = ("warning_code", "warning_scope", "pipeline_run", "batch", "assembly_accession")
    search_fields = (
        "warning_code",
        "warning_scope",
        "assembly_accession",
        "genome_id",
        "sequence_id",
        "protein_id",
        "pipeline_run__run_id",
    )
    list_filter = ("pipeline_run", "batch", "warning_code", "warning_scope")


@admin.register(Genome)
class GenomeAdmin(admin.ModelAdmin):
    list_display = ("accession", "genome_name", "pipeline_run", "batch", "taxon", "assembly_level")
    search_fields = ("accession", "genome_name", "genome_id", "species_name")
    list_filter = ("assembly_level", "source", "pipeline_run", "batch")


@admin.register(AccessionStatus)
class AccessionStatusAdmin(admin.ModelAdmin):
    list_display = ("assembly_accession", "pipeline_run", "batch", "terminal_status", "n_repeat_calls")
    search_fields = ("assembly_accession", "pipeline_run__run_id", "terminal_status", "failure_stage")
    list_filter = ("pipeline_run", "batch", "terminal_status", "detect_status", "finalize_status")


@admin.register(AccessionCallCount)
class AccessionCallCountAdmin(admin.ModelAdmin):
    list_display = ("assembly_accession", "pipeline_run", "batch", "method", "repeat_residue", "n_repeat_calls")
    search_fields = ("assembly_accession", "pipeline_run__run_id", "method", "repeat_residue")
    list_filter = ("pipeline_run", "batch", "method", "repeat_residue")


@admin.register(Sequence)
class SequenceAdmin(admin.ModelAdmin):
    list_display = ("sequence_name", "pipeline_run", "genome", "taxon", "gene_symbol")
    search_fields = ("sequence_id", "sequence_name", "gene_symbol", "transcript_id")
    list_filter = ("pipeline_run", "taxon")


@admin.register(Protein)
class ProteinAdmin(admin.ModelAdmin):
    list_display = ("protein_name", "pipeline_run", "genome", "taxon", "gene_symbol")
    search_fields = ("protein_id", "protein_name", "gene_symbol", "protein_external_id")
    list_filter = ("pipeline_run", "taxon", "translation_method", "translation_status")


@admin.register(RunParameter)
class RunParameterAdmin(admin.ModelAdmin):
    list_display = ("pipeline_run", "method", "repeat_residue", "param_name", "param_value")
    search_fields = ("pipeline_run__run_id", "method", "repeat_residue", "param_name", "param_value")
    list_filter = ("pipeline_run", "method", "repeat_residue")


@admin.register(RepeatCall)
class RepeatCallAdmin(admin.ModelAdmin):
    list_display = ("call_id", "pipeline_run", "method", "repeat_residue", "length", "purity")
    search_fields = ("call_id", "protein__protein_name", "protein__protein_id", "genome__accession")
    list_filter = ("pipeline_run", "method", "repeat_residue")
