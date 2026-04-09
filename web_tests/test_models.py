from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.browser.models import (
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
from apps.imports.models import ImportBatch


class PipelineRunModelTests(TestCase):
    def test_run_id_must_be_unique(self):
        PipelineRun.objects.create(run_id="run-alpha", status="success")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PipelineRun.objects.create(run_id="run-alpha", status="failed")


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
        self.assertEqual(batch.progress_payload, {})


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
