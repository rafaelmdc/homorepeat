from pathlib import Path

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from apps.browser.models import (
    AccessionCallCount,
    AccessionStatus,
    AcquisitionBatch,
    CanonicalRepeatCall,
    DownloadManifestEntry,
    Genome,
    NormalizationWarning,
    PipelineRun,
    Protein,
    RepeatCall,
    RepeatCallCodonUsage,
    RepeatCallContext,
    RunParameter,
    Sequence,
    Taxon,
    TaxonClosure,
)
from apps.imports.models import CATALOG_VERSION_CACHE_KEY, CatalogVersion, ImportBatch, UploadedRun
from apps.imports.services.import_run.state import _normalize_progress_payload


class PipelineRunModelTests(TestCase):
    def test_run_id_must_be_unique(self):
        PipelineRun.objects.create(run_id="run-alpha", status="success")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PipelineRun.objects.create(run_id="run-alpha", status="failed")

    def test_browser_metadata_defaults_to_empty_mapping(self):
        pipeline_run = PipelineRun.objects.create(run_id="run-alpha", status="success")

        self.assertEqual(pipeline_run.browser_metadata, {})


class TaxonModelTests(TestCase):
    def test_taxon_can_reference_parent(self):
        root = Taxon.objects.create(taxon_id=1, taxon_name="root", rank="no rank")
        child = Taxon.objects.create(
            taxon_id=9606,
            taxon_name="Homo sapiens",
            rank="species",
            parent_taxon=root,
        )

        self.assertEqual(child.parent_taxon, root)
        self.assertEqual(root.children.get(), child)

    def test_taxon_id_must_be_unique(self):
        Taxon.objects.create(taxon_id=9606, taxon_name="Homo sapiens", rank="species")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Taxon.objects.create(taxon_id=9606, taxon_name="Duplicate", rank="species")


class TaxonClosureModelTests(TestCase):
    def setUp(self):
        self.root = Taxon.objects.create(taxon_id=1, taxon_name="root", rank="no rank")
        self.species = Taxon.objects.create(
            taxon_id=9606,
            taxon_name="Homo sapiens",
            rank="species",
            parent_taxon=self.root,
        )

    def test_taxon_closure_requires_unique_ancestor_descendant_pair(self):
        TaxonClosure.objects.create(ancestor=self.root, descendant=self.species, depth=1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TaxonClosure.objects.create(ancestor=self.root, descendant=self.species, depth=1)

    def test_taxon_closure_depth_must_be_non_negative(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TaxonClosure.objects.create(ancestor=self.root, descendant=self.root, depth=-1)


class ImportBatchModelTests(TestCase):
    def test_import_batch_can_link_to_pipeline_run(self):
        pipeline_run = PipelineRun.objects.create(run_id="run-alpha", status="success")
        batch = ImportBatch.objects.create(
            pipeline_run=pipeline_run,
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.PENDING,
        )

        self.assertEqual(batch.pipeline_run, pipeline_run)
        self.assertEqual(batch.status, ImportBatch.Status.PENDING)
        self.assertEqual(batch.phase, "")
        self.assertIsNone(batch.heartbeat_at)
        self.assertEqual(batch.celery_task_id, "")
        self.assertEqual(batch.progress_payload, {})

    def test_progress_payload_normalizes_percent_from_current_and_total(self):
        payload = _normalize_progress_payload(
            {
                "message": "Importing retained sequence rows.",
                "current": 25,
                "total": 80,
                "unit": "sequences",
            }
        )

        self.assertEqual(payload["percent"], 31.2)

    def test_progress_payload_normalizes_percent_from_processed_and_total(self):
        payload = _normalize_progress_payload(
            {
                "message": "Syncing canonical protein rows.",
                "processed": 5,
                "total": 10,
                "unit": "proteins",
            }
        )

        self.assertEqual(payload["current"], 5)
        self.assertEqual(payload["percent"], 50.0)

    def test_import_batch_progress_steps_mark_current_phase(self):
        batch = ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.RUNNING,
            phase="importing_rows",
        )

        states = {step["phase"]: step["state"] for step in batch.progress_steps}

        self.assertEqual(states["queued"], "complete")
        self.assertEqual(states["importing_rows"], "active")
        self.assertEqual(states["syncing_canonical_catalog"], "pending")

    def test_import_batch_progress_steps_mark_failed_phase(self):
        batch = ImportBatch.objects.create(
            source_path="/tmp/run-alpha/publish",
            status=ImportBatch.Status.FAILED,
            phase="failed",
            progress_payload={"failed_phase": "importing_rows"},
        )

        states = {step["phase"]: step["state"] for step in batch.progress_steps}

        self.assertEqual(states["preparing_import"], "complete")
        self.assertEqual(states["importing_rows"], "failed")
        self.assertEqual(states["syncing_canonical_catalog"], "pending")


class UploadedRunModelTests(TestCase):
    def test_uploaded_run_defaults_to_receiving_status(self):
        uploaded_run = UploadedRun.objects.create(
            original_filename="run-alpha.zip",
            size_bytes=123,
            total_chunks=1,
        )

        self.assertEqual(uploaded_run.status, UploadedRun.Status.RECEIVING)
        self.assertEqual(uploaded_run.received_bytes, 0)
        self.assertEqual(uploaded_run.chunk_size_bytes, 8 * 1024 * 1024)
        self.assertEqual(uploaded_run.received_chunks, [])
        self.assertEqual(uploaded_run.publish_root, "")
        self.assertEqual(uploaded_run.run_id, "")
        self.assertIsNone(uploaded_run.import_batch)

    @override_settings(HOMOREPEAT_IMPORTS_ROOT="/tmp/homorepeat-imports")
    def test_uploaded_run_paths_resolve_against_imports_root(self):
        uploaded_run = UploadedRun.objects.create(
            original_filename="run-alpha.zip",
            run_id="run-alpha",
        )
        upload_root = Path("/tmp/homorepeat-imports") / "uploads" / str(uploaded_run.upload_id)

        self.assertEqual(uploaded_run.upload_root, upload_root)
        self.assertEqual(uploaded_run.chunks_root, upload_root / "chunks")
        self.assertEqual(uploaded_run.zip_path, upload_root / "source.zip")
        self.assertEqual(uploaded_run.extracted_root, upload_root / "extracted")
        self.assertEqual(uploaded_run.library_root, Path("/tmp/homorepeat-imports") / "library" / "run-alpha")

    @override_settings(HOMOREPEAT_IMPORTS_ROOT="/tmp/homorepeat-imports")
    def test_uploaded_run_library_root_is_empty_until_run_id_is_known(self):
        uploaded_run = UploadedRun.objects.create(original_filename="run-alpha.zip")

        self.assertIsNone(uploaded_run.library_root)


class CatalogVersionModelTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_current_creates_singleton_at_zero(self):
        self.assertEqual(CatalogVersion.current(), 0)
        self.assertEqual(CatalogVersion.objects.count(), 1)
        self.assertEqual(CatalogVersion.objects.get(pk=1).version, 0)

    def test_cached_current_uses_cache_and_increment_invalidates_it(self):
        self.assertEqual(CatalogVersion.cached_current(), 0)
        self.assertEqual(cache.get(CATALOG_VERSION_CACHE_KEY), 0)

        CatalogVersion.increment()

        self.assertIsNone(cache.get(CATALOG_VERSION_CACHE_KEY))
        self.assertEqual(CatalogVersion.current(), 1)
        self.assertEqual(CatalogVersion.cached_current(), 1)


class RawProvenanceModelTests(TestCase):
    def setUp(self):
        self.run = PipelineRun.objects.create(run_id="run-alpha", status="success")
        self.batch = AcquisitionBatch.objects.create(
            pipeline_run=self.run,
            batch_id="batch_0001",
        )

    def test_acquisition_batch_is_unique_within_run(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcquisitionBatch.objects.create(
                    pipeline_run=self.run,
                    batch_id="batch_0001",
                )

    def test_download_manifest_entry_is_unique_per_run_batch_accession(self):
        DownloadManifestEntry.objects.create(
            pipeline_run=self.run,
            batch=self.batch,
            assembly_accession="GCF_000001405.40",
            download_status="downloaded",
            package_mode="direct_zip",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DownloadManifestEntry.objects.create(
                    pipeline_run=self.run,
                    batch=self.batch,
                    assembly_accession="GCF_000001405.40",
                    download_status="downloaded",
                    package_mode="direct_zip",
                )

    def test_normalization_warning_allows_blank_scoped_identifiers(self):
        warning = NormalizationWarning.objects.create(
            pipeline_run=self.run,
            batch=self.batch,
            warning_code="partial_cds",
            warning_scope="sequence",
            warning_message="CDS is partial",
        )

        self.assertEqual(warning.assembly_accession, "")
        self.assertEqual(warning.sequence_id, "")

    def test_raw_provenance_models_expose_historical_import_labels(self):
        self.assertEqual(DownloadManifestEntry._meta.verbose_name_plural, "imported download-manifest rows")
        self.assertEqual(NormalizationWarning._meta.verbose_name_plural, "imported normalization warnings")
        self.assertEqual(AccessionStatus._meta.verbose_name_plural, "imported accession status rows")
        self.assertEqual(AccessionCallCount._meta.verbose_name_plural, "imported accession call-count rows")


class BiologicalModelTests(TestCase):
    def setUp(self):
        self.run_alpha = PipelineRun.objects.create(run_id="run-alpha", status="success")
        self.run_beta = PipelineRun.objects.create(run_id="run-beta", status="success")
        self.root = Taxon.objects.create(taxon_id=1, taxon_name="root", rank="no rank")
        self.species = Taxon.objects.create(
            taxon_id=9606,
            taxon_name="Homo sapiens",
            rank="species",
            parent_taxon=self.root,
        )
        self.genome = Genome.objects.create(
            pipeline_run=self.run_alpha,
            genome_id="genome_1",
            source="ncbi_datasets",
            accession="GCF_000001405.40",
            genome_name="Homo sapiens",
            assembly_type="haploid-with-alt-loci",
            taxon=self.species,
            assembly_level="Chromosome",
            species_name="Homo sapiens",
        )
        self.sequence = Sequence.objects.create(
            pipeline_run=self.run_alpha,
            genome=self.genome,
            taxon=self.species,
            sequence_id="seq_1",
            sequence_name="NM_000001.1",
            sequence_length=900,
            gene_symbol="GENE1",
        )
        self.protein = Protein.objects.create(
            pipeline_run=self.run_alpha,
            genome=self.genome,
            sequence=self.sequence,
            taxon=self.species,
            protein_id="prot_1",
            protein_name="NP_000001.1",
            protein_length=300,
            accession=self.genome.accession,
            repeat_call_count=1,
            gene_symbol="GENE1",
        )

    def test_genome_is_unique_within_run(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Genome.objects.create(
                    pipeline_run=self.run_alpha,
                    genome_id="genome_1",
                    source="ncbi_datasets",
                    accession="GCF_duplicate",
                    genome_name="Duplicate",
                    assembly_type="chromosome",
                    taxon=self.species,
                )

    def test_same_accession_can_exist_in_multiple_runs(self):
        genome = Genome.objects.create(
            pipeline_run=self.run_beta,
            genome_id="genome_1",
            source="ncbi_datasets",
            accession="GCF_000001405.40",
            genome_name="Homo sapiens second import",
            assembly_type="haploid-with-alt-loci",
            taxon=self.species,
        )

        self.assertEqual(genome.accession, self.genome.accession)
        self.assertNotEqual(genome.pipeline_run_id, self.genome.pipeline_run_id)

    def test_sequence_model_defines_hot_raw_browse_index(self):
        self.assertIn(
            ("pipeline_run", "assembly_accession", "sequence_name", "id"),
            [tuple(index.fields) for index in Sequence._meta.indexes],
        )

    def test_protein_model_defines_hot_raw_browse_index(self):
        self.assertIn(
            ("pipeline_run", "accession", "protein_name", "id"),
            [tuple(index.fields) for index in Protein._meta.indexes],
        )

    def test_sequence_is_unique_within_run(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Sequence.objects.create(
                    pipeline_run=self.run_alpha,
                    genome=self.genome,
                    taxon=self.species,
                    sequence_id="seq_1",
                    sequence_name="duplicate",
                    sequence_length=100,
                )

    def test_protein_is_unique_within_run(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Protein.objects.create(
                    pipeline_run=self.run_alpha,
                    genome=self.genome,
                    sequence=self.sequence,
                    taxon=self.species,
                    protein_id="prot_1",
                    protein_name="duplicate",
                    protein_length=50,
                )

    def test_run_parameter_is_unique_within_run_method_residue_name(self):
        RunParameter.objects.create(
            pipeline_run=self.run_alpha,
            method=RunParameter.Method.PURE,
            repeat_residue="Q",
            param_name="min_repeat_count",
            param_value="6",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RunParameter.objects.create(
                    pipeline_run=self.run_alpha,
                    method=RunParameter.Method.PURE,
                    repeat_residue="Q",
                    param_name="min_repeat_count",
                    param_value="8",
                )

    def test_run_parameter_allows_same_method_name_for_different_residues(self):
        RunParameter.objects.create(
            pipeline_run=self.run_alpha,
            method=RunParameter.Method.PURE,
            repeat_residue="Q",
            param_name="min_repeat_count",
            param_value="6",
        )

        other_residue = RunParameter.objects.create(
            pipeline_run=self.run_alpha,
            method=RunParameter.Method.PURE,
            repeat_residue="N",
            param_name="min_repeat_count",
            param_value="6",
        )

        self.assertEqual(other_residue.repeat_residue, "N")

    def test_repeat_call_is_unique_within_run(self):
        RepeatCall.objects.create(
            pipeline_run=self.run_alpha,
            genome=self.genome,
            sequence=self.sequence,
            protein=self.protein,
            taxon=self.species,
            call_id="call_1",
            method=RepeatCall.Method.PURE,
            accession=self.genome.accession,
            gene_symbol=self.protein.gene_symbol,
            protein_name=self.protein.protein_name,
            protein_length=self.protein.protein_length,
            start=10,
            end=20,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="QQQQQQQQQQQ",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RepeatCall.objects.create(
                    pipeline_run=self.run_alpha,
                    genome=self.genome,
                    sequence=self.sequence,
                    protein=self.protein,
                    taxon=self.species,
                    call_id="call_1",
                    method=RepeatCall.Method.THRESHOLD,
                    accession=self.genome.accession,
                    gene_symbol=self.protein.gene_symbol,
                    protein_name=self.protein.protein_name,
                    protein_length=self.protein.protein_length,
                    start=30,
                    end=35,
                    length=6,
                    repeat_residue="Q",
                    repeat_count=5,
                    non_repeat_count=1,
                    purity=0.8,
                    aa_sequence="QQQAQQ",
                )

    def test_repeat_call_model_defines_hot_raw_browse_index(self):
        self.assertIn(
            ("pipeline_run", "accession", "protein_name", "start", "id"),
            [tuple(index.fields) for index in RepeatCall._meta.indexes],
        )

    def test_repeat_call_enforces_purity_bounds(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RepeatCall.objects.create(
                    pipeline_run=self.run_alpha,
                    genome=self.genome,
                    sequence=self.sequence,
                    protein=self.protein,
                    taxon=self.species,
                    call_id="call_bad_purity",
                    method=RepeatCall.Method.PURE,
                    accession=self.genome.accession,
                    gene_symbol=self.protein.gene_symbol,
                    protein_name=self.protein.protein_name,
                    protein_length=self.protein.protein_length,
                    start=10,
                    end=20,
                    length=11,
                    repeat_residue="Q",
                    repeat_count=11,
                    non_repeat_count=0,
                    purity=1.2,
                    aa_sequence="QQQQQQQQQQQ",
                )

    def test_repeat_call_requires_end_not_before_start(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RepeatCall.objects.create(
                    pipeline_run=self.run_alpha,
                    genome=self.genome,
                    sequence=self.sequence,
                    protein=self.protein,
                    taxon=self.species,
                    call_id="call_bad_coords",
                    method=RepeatCall.Method.PURE,
                    accession=self.genome.accession,
                    gene_symbol=self.protein.gene_symbol,
                    protein_name=self.protein.protein_name,
                    protein_length=self.protein.protein_length,
                    start=25,
                    end=20,
                    length=6,
                    repeat_residue="Q",
                    repeat_count=6,
                    non_repeat_count=0,
                    purity=1.0,
                    aa_sequence="QQQQQQ",
                )

    def test_repeat_call_can_store_denormalized_browse_fields(self):
        repeat_call = RepeatCall.objects.create(
            pipeline_run=self.run_alpha,
            genome=self.genome,
            sequence=self.sequence,
            protein=self.protein,
            taxon=self.species,
            call_id="call_with_denorm",
            method=RepeatCall.Method.PURE,
            accession=self.genome.accession,
            gene_symbol="GENE1",
            protein_name="NP_000001.1",
            protein_length=300,
            start=10,
            end=20,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="QQQQQQQQQQQ",
        )

        self.assertEqual(repeat_call.accession, self.genome.accession)
        self.assertEqual(repeat_call.protein_name, self.protein.protein_name)
        self.assertEqual(repeat_call.protein_length, self.protein.protein_length)

    def test_repeat_call_can_store_nullable_numeric_codon_ratio_value(self):
        repeat_call = RepeatCall.objects.create(
            pipeline_run=self.run_alpha,
            genome=self.genome,
            sequence=self.sequence,
            protein=self.protein,
            taxon=self.species,
            call_id="call_with_codon_ratio",
            method=RepeatCall.Method.PURE,
            accession=self.genome.accession,
            gene_symbol=self.protein.gene_symbol,
            protein_name=self.protein.protein_name,
            protein_length=self.protein.protein_length,
            start=10,
            end=20,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="QQQQQQQQQQQ",
            codon_ratio_value=1.25,
        )
        repeat_call_without_value = RepeatCall.objects.create(
            pipeline_run=self.run_alpha,
            genome=self.genome,
            sequence=self.sequence,
            protein=self.protein,
            taxon=self.species,
            call_id="call_without_codon_ratio",
            method=RepeatCall.Method.PURE,
            accession=self.genome.accession,
            gene_symbol=self.protein.gene_symbol,
            protein_name=self.protein.protein_name,
            protein_length=self.protein.protein_length,
            start=30,
            end=40,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="QQQQQQQQQQQ",
        )

        self.assertEqual(repeat_call.codon_ratio_value, 1.25)
        self.assertIsNone(repeat_call_without_value.codon_ratio_value)

    def test_repeat_call_models_expose_nullable_codon_ratio_value_field(self):
        repeat_call_field = RepeatCall._meta.get_field("codon_ratio_value")
        canonical_repeat_call_field = CanonicalRepeatCall._meta.get_field("codon_ratio_value")

        self.assertTrue(repeat_call_field.null)
        self.assertTrue(repeat_call_field.blank)
        self.assertTrue(canonical_repeat_call_field.null)
        self.assertTrue(canonical_repeat_call_field.blank)

    def test_repeat_call_codon_usage_rows_can_store_per_codon_values(self):
        repeat_call = RepeatCall.objects.create(
            pipeline_run=self.run_alpha,
            genome=self.genome,
            sequence=self.sequence,
            protein=self.protein,
            taxon=self.species,
            call_id="call_with_codon_usage",
            method=RepeatCall.Method.PURE,
            accession=self.genome.accession,
            gene_symbol=self.protein.gene_symbol,
            protein_name=self.protein.protein_name,
            protein_length=self.protein.protein_length,
            start=10,
            end=20,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="QQQQQQQQQQQ",
        )
        codon_usage = RepeatCallCodonUsage.objects.create(
            repeat_call=repeat_call,
            amino_acid="Q",
            codon="CAG",
            codon_count=11,
            codon_fraction=1.0,
        )

        self.assertEqual(codon_usage.repeat_call, repeat_call)
        self.assertEqual(codon_usage.codon, "CAG")
        self.assertEqual(codon_usage.codon_count, 11)
        self.assertEqual(codon_usage.codon_fraction, 1.0)

    def test_repeat_call_context_stores_repeat_local_flanks(self):
        repeat_call = RepeatCall.objects.create(
            pipeline_run=self.run_alpha,
            genome=self.genome,
            sequence=self.sequence,
            protein=self.protein,
            taxon=self.species,
            call_id="call_with_context",
            method=RepeatCall.Method.PURE,
            accession=self.genome.accession,
            gene_symbol=self.protein.gene_symbol,
            protein_name=self.protein.protein_name,
            protein_length=self.protein.protein_length,
            start=10,
            end=20,
            length=11,
            repeat_residue="Q",
            repeat_count=11,
            non_repeat_count=0,
            purity=1.0,
            aa_sequence="QQQQQQQQQQQ",
        )

        context = RepeatCallContext.objects.create(
            repeat_call=repeat_call,
            pipeline_run=self.run_alpha,
            protein_id="prot_1",
            sequence_id="seq_1",
            aa_left_flank="M",
            aa_right_flank="A",
            nt_left_flank="ATG",
            nt_right_flank="GCT",
            aa_context_window_size=12,
            nt_context_window_size=36,
        )

        self.assertEqual(context.repeat_call, repeat_call)
        self.assertEqual(repeat_call.context.protein_id, "prot_1")
        self.assertEqual(context.nt_right_flank, "GCT")

    def test_biological_run_scoped_models_expose_imported_observation_labels(self):
        self.assertEqual(Genome._meta.verbose_name_plural, "imported genome observations")
        self.assertEqual(Sequence._meta.verbose_name_plural, "imported sequence observations")
        self.assertEqual(Protein._meta.verbose_name_plural, "imported protein observations")
        self.assertEqual(RepeatCall._meta.verbose_name_plural, "imported repeat-call observations")
        self.assertEqual(RepeatCallCodonUsage._meta.verbose_name_plural, "imported repeat-call codon-usage rows")
        self.assertEqual(RepeatCallContext._meta.verbose_name_plural, "imported repeat-call contexts")
        self.assertEqual(RunParameter._meta.verbose_name_plural, "imported run parameters")
