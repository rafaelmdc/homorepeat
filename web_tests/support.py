import json
from pathlib import Path


_TEST_CODON_TRIPLETS = {
    "A": "GCT",
    "N": "AAC",
    "Q": "CAG",
}

_TEST_DEFAULT_CODON_RATIO_VALUES = {
    "A": 0.75,
    "N": 0.5,
    "Q": 1.25,
}


def _test_codon_triplet_for_residue(residue: str) -> str:
    return _TEST_CODON_TRIPLETS.get((residue or "").upper(), "NNN")


def build_test_repeat_call_values(
    *,
    residue: str,
    length: int,
    purity: float,
    codon_metric_name: str = "codon_ratio",
    codon_ratio_value: float | None = None,
) -> dict[str, object]:
    residue = (residue or "Q").upper()
    repeat_count = max(1, min(length, int(round(length * purity))))
    non_repeat_count = max(length - repeat_count, 0)
    filler = "A" if residue != "A" else "Q"
    resolved_codon_ratio_value = (
        _TEST_DEFAULT_CODON_RATIO_VALUES.get(residue, 1.0)
        if codon_ratio_value is None
        else codon_ratio_value
    )

    return {
        "repeat_count": repeat_count,
        "non_repeat_count": non_repeat_count,
        "aa_sequence": (residue * repeat_count) + (filler * non_repeat_count),
        "codon_sequence": _test_codon_triplet_for_residue(residue) * length,
        "codon_metric_name": codon_metric_name,
        "codon_metric_value": str(resolved_codon_ratio_value),
        "codon_ratio_value": resolved_codon_ratio_value,
    }


def build_minimal_publish_root(base_dir: Path, *, run_id: str = "run-alpha") -> Path:
    publish_root = base_dir / "publish"
    batch_root = publish_root / "acquisition" / "batches" / "batch_0001"
    (publish_root / "metadata").mkdir(parents=True)
    batch_root.mkdir(parents=True)
    (publish_root / "calls").mkdir(parents=True)
    (publish_root / "status").mkdir(parents=True)
    seq_1_nt = "CAG" * 30
    seq_2_nt = "GCT" * 28
    prot_1_aa = "Q" * 30
    prot_2_aa = "A" * 28

    manifest = {
        "run_id": run_id,
        "status": "success",
        "started_at_utc": "2026-04-06T12:03:46Z",
        "finished_at_utc": "2026-04-06T12:05:44Z",
        "profile": "docker",
        "acquisition_publish_mode": "raw",
        "git_revision": "abc123",
        "inputs": {},
        "paths": {"publish_root": f"runs/{run_id}/publish", "run_root": f"runs/{run_id}"},
        "params": {},
        "enabled_methods": ["pure"],
        "repeat_residues": ["Q"],
        "artifacts": {
            "acquisition": {"batches_root": "publish/acquisition/batches"},
            "calls": {
                "repeat_calls_tsv": "publish/calls/repeat_calls.tsv",
                "run_params_tsv": "publish/calls/run_params.tsv",
            },
            "status": {
                "accession_status_tsv": "publish/status/accession_status.tsv",
                "accession_call_counts_tsv": "publish/status/accession_call_counts.tsv",
            },
        },
    }
    (publish_root / "metadata" / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    (batch_root / "taxonomy.tsv").write_text(
        "taxon_id\ttaxon_name\tparent_taxon_id\trank\tsource\n"
        "1\troot\t\tno rank\ttest\n"
        "9606\tHomo sapiens\t1\tspecies\ttest\n",
        encoding="utf-8",
    )
    (batch_root / "genomes.tsv").write_text(
        "genome_id\tsource\taccession\tgenome_name\tassembly_type\ttaxon_id\tassembly_level\tspecies_name\tnotes\n"
        "genome_1\tncbi_datasets\tGCF_000001405.40\tExample genome\thaploid\t9606\tChromosome\tHomo sapiens\t\n",
        encoding="utf-8",
    )
    (batch_root / "sequences.tsv").write_text(
        "sequence_id\tgenome_id\tsequence_name\tsequence_length\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\n"
        "seq_1\tgenome_1\tNM_000001.1\t90\tGENE1\tNM_000001.1\tNP_000001.1\tGCF_000001405.40\t9606\tcds-1\tNP_000001.1\t1\tGENE1\tgff\t\n"
        "seq_2\tgenome_1\tNM_000002.1\t84\tGENE2\tNM_000002.1\tNP_000002.1\tGCF_000001405.40\t9606\tcds-2\tNP_000002.1\t1\tGENE2\tgff\t\n",
        encoding="utf-8",
    )
    (batch_root / "proteins.tsv").write_text(
        "protein_id\tsequence_id\tgenome_id\tprotein_name\tprotein_length\tgene_symbol\ttranslation_method\ttranslation_status\tassembly_accession\ttaxon_id\tgene_group\tprotein_external_id\n"
        "prot_1\tseq_1\tgenome_1\tNP_000001.1\t30\tGENE1\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE1\tNP_000001.1\n"
        "prot_2\tseq_2\tgenome_1\tNP_000002.1\t28\tGENE2\ttranslated\ttranslated\tGCF_000001405.40\t9606\tGENE2\tNP_000002.1\n",
        encoding="utf-8",
    )
    (batch_root / "cds.fna").write_text(
        f">seq_1\n{seq_1_nt}\n>seq_2\n{seq_2_nt}\n",
        encoding="utf-8",
    )
    (batch_root / "proteins.faa").write_text(
        f">prot_1\n{prot_1_aa}\n>prot_2\n{prot_2_aa}\n",
        encoding="utf-8",
    )
    (batch_root / "download_manifest.tsv").write_text(
        "batch_id\tassembly_accession\tdownload_status\tpackage_mode\tdownload_path\trehydrated_path\tchecksum\tfile_size_bytes\tdownload_started_at\tdownload_finished_at\tnotes\n"
        "batch_0001\tGCF_000001405.40\tdownloaded\tdirect_zip\t\t\t\t106807993\t\t\t\n",
        encoding="utf-8",
    )
    (batch_root / "normalization_warnings.tsv").write_text(
        "warning_code\twarning_scope\twarning_message\tbatch_id\tgenome_id\tsequence_id\tprotein_id\tassembly_accession\tsource_file\tsource_record_id\n",
        encoding="utf-8",
    )
    (batch_root / "acquisition_validation.json").write_text(
        json.dumps(
            {
                "batch_id": "batch_0001",
                "status": "pass",
                "scope": "batch",
                "counts": {
                    "n_selected_assemblies": 1,
                    "n_downloaded_packages": 1,
                    "n_genomes": 1,
                    "n_sequences": 2,
                    "n_proteins": 2,
                    "n_warning_rows": 0,
                },
                "checks": {
                    "all_genomes_have_taxids": True,
                    "all_proteins_belong_to_genomes": True,
                    "all_retained_proteins_trace_to_cds": True,
                    "all_selected_accessions_accounted_for": True,
                },
                "failed_accessions": [],
                "warning_summary": {},
                "notes": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (publish_root / "calls" / "run_params.tsv").write_text(
        "method\trepeat_residue\tparam_name\tparam_value\n"
        "pure\tQ\tmin_repeat_count\t6\n",
        encoding="utf-8",
    )
    (publish_root / "calls" / "repeat_calls.tsv").write_text(
        "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
        "call_1\tpure\tgenome_1\t9606\tseq_1\tprot_1\t10\t20\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\t\t\t\t\t\t\t\n",
        encoding="utf-8",
    )
    (publish_root / "status" / "accession_status.tsv").write_text(
        "assembly_accession\tbatch_id\tdownload_status\tnormalize_status\ttranslate_status\tdetect_status\tfinalize_status\tterminal_status\tfailure_stage\tfailure_reason\tn_genomes\tn_proteins\tn_repeat_calls\tnotes\n"
        "GCF_000001405.40\tbatch_0001\tsuccess\tsuccess\tsuccess\tsuccess\tsuccess\tcompleted\t\t\t1\t2\t1\t\n",
        encoding="utf-8",
    )
    (publish_root / "status" / "accession_call_counts.tsv").write_text(
        "assembly_accession\tbatch_id\tmethod\trepeat_residue\tdetect_status\tfinalize_status\tn_repeat_calls\n"
        "GCF_000001405.40\tbatch_0001\tpure\tQ\tsuccess\tsuccess\t1\n",
        encoding="utf-8",
    )
    return publish_root


def build_multibatch_publish_root(base_dir: Path, *, run_id: str = "run-multi-batch") -> Path:
    publish_root = build_minimal_publish_root(base_dir, run_id=run_id)
    batch_root = publish_root / "acquisition" / "batches" / "batch_0002"
    batch_root.mkdir(parents=True)

    (batch_root / "taxonomy.tsv").write_text(
        "taxon_id\ttaxon_name\tparent_taxon_id\trank\tsource\n"
        "1\troot\t\tno rank\ttest\n"
        "10090\tMus musculus\t1\tspecies\ttest\n",
        encoding="utf-8",
    )
    (batch_root / "genomes.tsv").write_text(
        "genome_id\tsource\taccession\tgenome_name\tassembly_type\ttaxon_id\tassembly_level\tspecies_name\tnotes\n"
        "genome_2\tncbi_datasets\tGCF_000001635.27\tMouse genome\thaploid\t10090\tChromosome\tMus musculus\t\n",
        encoding="utf-8",
    )
    (batch_root / "sequences.tsv").write_text(
        "sequence_id\tgenome_id\tsequence_name\tsequence_length\tgene_symbol\ttranscript_id\tisoform_id\tassembly_accession\ttaxon_id\tsource_record_id\tprotein_external_id\ttranslation_table\tgene_group\tlinkage_status\tpartial_status\n"
        "seq_3\tgenome_2\tNM_000003.1\t72\tGENE3\tNM_000003.1\tNP_000003.1\tGCF_000001635.27\t10090\tcds-3\tNP_000003.1\t1\tGENE3\tgff\t\n",
        encoding="utf-8",
    )
    (batch_root / "proteins.tsv").write_text(
        "protein_id\tsequence_id\tgenome_id\tprotein_name\tprotein_length\tgene_symbol\ttranslation_method\ttranslation_status\tassembly_accession\ttaxon_id\tgene_group\tprotein_external_id\n"
        "prot_3\tseq_3\tgenome_2\tNP_000003.1\t24\tGENE3\ttranslated\ttranslated\tGCF_000001635.27\t10090\tGENE3\tNP_000003.1\n",
        encoding="utf-8",
    )
    (batch_root / "cds.fna").write_text(
        ">seq_3\nATG" + ("CAG" * 23) + "\n",
        encoding="utf-8",
    )
    (batch_root / "proteins.faa").write_text(
        ">prot_3\nM" + ("Q" * 23) + "\n",
        encoding="utf-8",
    )
    (batch_root / "download_manifest.tsv").write_text(
        "batch_id\tassembly_accession\tdownload_status\tpackage_mode\tdownload_path\trehydrated_path\tchecksum\tfile_size_bytes\tdownload_started_at\tdownload_finished_at\tnotes\n"
        "batch_0002\tGCF_000001635.27\tdownloaded\tdirect_zip\t\t\t\t123456\t\t\t\n",
        encoding="utf-8",
    )
    (batch_root / "normalization_warnings.tsv").write_text(
        "warning_code\twarning_scope\twarning_message\tbatch_id\tgenome_id\tsequence_id\tprotein_id\tassembly_accession\tsource_file\tsource_record_id\n"
        "partial_cds\tsequence\tCDS is partial\tbatch_0002\tgenome_2\tseq_3\t\tGCF_000001635.27\t/source/path\tcds-3\n",
        encoding="utf-8",
    )
    (batch_root / "acquisition_validation.json").write_text(
        json.dumps(
            {
                "batch_id": "batch_0002",
                "status": "warn",
                "scope": "batch",
                "counts": {
                    "n_selected_assemblies": 1,
                    "n_downloaded_packages": 1,
                    "n_genomes": 1,
                    "n_sequences": 1,
                    "n_proteins": 1,
                    "n_warning_rows": 1,
                },
                "checks": {
                    "all_genomes_have_taxids": True,
                    "all_proteins_belong_to_genomes": True,
                    "all_retained_proteins_trace_to_cds": True,
                    "all_selected_accessions_accounted_for": True,
                },
                "failed_accessions": [],
                "warning_summary": {"partial_cds": 1},
                "notes": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (publish_root / "calls" / "repeat_calls.tsv").write_text(
        "call_id\tmethod\tgenome_id\ttaxon_id\tsequence_id\tprotein_id\tstart\tend\tlength\trepeat_residue\trepeat_count\tnon_repeat_count\tpurity\taa_sequence\tcodon_sequence\tcodon_metric_name\tcodon_metric_value\twindow_definition\ttemplate_name\tmerge_rule\tscore\n"
        "call_1\tpure\tgenome_1\t9606\tseq_1\tprot_1\t10\t20\t11\tQ\t11\t0\t1.0\tQQQQQQQQQQQ\t\t\t\t\t\t\t\n"
        "call_2\tthreshold\tgenome_2\t10090\tseq_3\tprot_3\t2\t11\t10\tQ\t9\t1\t0.9\tQQQQQQQQQA\t\t\t\tQ9/10\t\t\t\n",
        encoding="utf-8",
    )
    (publish_root / "calls" / "run_params.tsv").write_text(
        "method\trepeat_residue\tparam_name\tparam_value\n"
        "pure\tQ\tmin_repeat_count\t6\n"
        "threshold\tQ\tmin_target_count\t9\n",
        encoding="utf-8",
    )
    (publish_root / "status" / "accession_status.tsv").write_text(
        "assembly_accession\tbatch_id\tdownload_status\tnormalize_status\ttranslate_status\tdetect_status\tfinalize_status\tterminal_status\tfailure_stage\tfailure_reason\tn_genomes\tn_proteins\tn_repeat_calls\tnotes\n"
        "GCF_000001405.40\tbatch_0001\tsuccess\tsuccess\tsuccess\tsuccess\tsuccess\tcompleted\t\t\t1\t2\t1\t\n"
        "GCF_000001635.27\tbatch_0002\tsuccess\tsuccess\tsuccess\tsuccess\tsuccess\tcompleted\t\t\t1\t1\t1\t\n",
        encoding="utf-8",
    )
    (publish_root / "status" / "accession_call_counts.tsv").write_text(
        "assembly_accession\tbatch_id\tmethod\trepeat_residue\tdetect_status\tfinalize_status\tn_repeat_calls\n"
        "GCF_000001405.40\tbatch_0001\tpure\tQ\tsuccess\tsuccess\t1\n"
        "GCF_000001635.27\tbatch_0002\tthreshold\tQ\tsuccess\tsuccess\t1\n",
        encoding="utf-8",
    )

    return publish_root


def create_imported_run_fixture(
    *,
    run_id: str,
    genome_id: str,
    sequence_id: str,
    protein_id: str,
    call_id: str,
    accession: str,
    taxon_key: str = "human",
    genome_name: str | None = None,
    repeat_residue: str = "Q",
    codon_metric_name: str = "codon_ratio",
    codon_ratio_value: float | None = None,
):
    from apps.browser.models import (
        AccessionCallCount,
        AccessionStatus,
        AcquisitionBatch,
        Genome,
        PipelineRun,
        Protein,
        RepeatCall,
        RunParameter,
        Sequence,
    )
    from apps.browser.catalog import sync_canonical_catalog_for_run
    from apps.imports.models import ImportBatch
    from django.utils import timezone

    taxa = ensure_test_taxonomy()
    selected_taxon = taxa[taxon_key]
    residue = repeat_residue.upper()
    protein_length = 300
    repeat_call_values = build_test_repeat_call_values(
        residue=residue,
        length=11,
        purity=1.0,
        codon_metric_name=codon_metric_name,
        codon_ratio_value=codon_ratio_value,
    )

    pipeline_run = PipelineRun.objects.create(
        run_id=run_id,
        status="success",
        profile="docker",
        acquisition_publish_mode="raw",
        git_revision="abc123",
        manifest_path=f"/tmp/{run_id}/metadata/run_manifest.json",
        publish_root=f"/tmp/{run_id}/publish",
        manifest_payload={"run_id": run_id, "acquisition_publish_mode": "raw"},
    )
    batch = AcquisitionBatch.objects.create(
        pipeline_run=pipeline_run,
        batch_id="batch_0001",
    )
    genome = Genome.objects.create(
        pipeline_run=pipeline_run,
        batch=batch,
        genome_id=genome_id,
        source="ncbi_datasets",
        accession=accession,
        genome_name=genome_name or f"Genome for {run_id}",
        assembly_type="haploid",
        taxon=selected_taxon,
        assembly_level="Chromosome",
        species_name=selected_taxon.taxon_name,
        analyzed_protein_count=1,
    )
    sequence = Sequence.objects.create(
        pipeline_run=pipeline_run,
        genome=genome,
        taxon=selected_taxon,
        sequence_id=sequence_id,
        sequence_name=f"NM_{run_id}",
        sequence_length=900,
        nucleotide_sequence=_test_codon_triplet_for_residue(residue) * protein_length,
        gene_symbol="GENE1",
        assembly_accession=accession,
    )
    protein = Protein.objects.create(
        pipeline_run=pipeline_run,
        genome=genome,
        sequence=sequence,
        taxon=selected_taxon,
        protein_id=protein_id,
        protein_name=f"NP_{run_id}",
        protein_length=protein_length,
        accession=accession,
        amino_acid_sequence=residue * protein_length,
        gene_symbol="GENE1",
        assembly_accession=accession,
    )
    run_parameter = RunParameter.objects.create(
        pipeline_run=pipeline_run,
        method=RunParameter.Method.PURE,
        repeat_residue=residue,
        param_name="min_repeat_count",
        param_value="6",
    )
    accession_status = AccessionStatus.objects.create(
        pipeline_run=pipeline_run,
        batch=batch,
        assembly_accession=accession,
        download_status="success",
        normalize_status="success",
        translate_status="success",
        detect_status="success",
        finalize_status="success",
        terminal_status="completed",
        n_genomes=1,
        n_proteins=1,
        n_repeat_calls=1,
    )
    accession_call_count = AccessionCallCount.objects.create(
        pipeline_run=pipeline_run,
        batch=batch,
        assembly_accession=accession,
        method=RunParameter.Method.PURE,
        repeat_residue=residue,
        detect_status="success",
        finalize_status="success",
        n_repeat_calls=1,
    )
    repeat_call = RepeatCall.objects.create(
        pipeline_run=pipeline_run,
        genome=genome,
        sequence=sequence,
        protein=protein,
        taxon=selected_taxon,
        call_id=call_id,
        method=RepeatCall.Method.PURE,
        accession=accession,
        gene_symbol=protein.gene_symbol or sequence.gene_symbol,
        protein_name=protein.protein_name,
        protein_length=protein.protein_length,
        start=10,
        end=20,
        length=11,
        repeat_residue=residue,
        purity=1.0,
        repeat_count=repeat_call_values["repeat_count"],
        non_repeat_count=repeat_call_values["non_repeat_count"],
        aa_sequence=repeat_call_values["aa_sequence"],
        codon_sequence=repeat_call_values["codon_sequence"],
        codon_metric_name=repeat_call_values["codon_metric_name"],
        codon_metric_value=repeat_call_values["codon_metric_value"],
        codon_ratio_value=repeat_call_values["codon_ratio_value"],
    )
    import_batch = ImportBatch.objects.create(
        pipeline_run=pipeline_run,
        source_path=pipeline_run.publish_root,
        status=ImportBatch.Status.RUNNING,
        phase="syncing_canonical_catalog",
        heartbeat_at=timezone.now(),
    )
    sync_canonical_catalog_for_run(
        pipeline_run,
        import_batch=import_batch,
        last_seen_at=timezone.now(),
    )
    return {
        "pipeline_run": pipeline_run,
        "batch": batch,
        "import_batch": import_batch,
        "genome": genome,
        "sequence": sequence,
        "protein": protein,
        "run_parameter": run_parameter,
        "accession_status": accession_status,
        "accession_call_count": accession_call_count,
        "repeat_call": repeat_call,
        "taxon": selected_taxon,
        "taxa": taxa,
    }


def ensure_test_taxonomy():
    from apps.browser.models import Taxon, TaxonClosure

    definitions = {
        "root": {"taxon_id": 1, "taxon_name": "root", "rank": "no rank", "parent": None},
        "chordata": {"taxon_id": 7711, "taxon_name": "Chordata", "rank": "phylum", "parent": "root"},
        "mammalia": {"taxon_id": 40674, "taxon_name": "Mammalia", "rank": "class", "parent": "chordata"},
        "primates": {"taxon_id": 9443, "taxon_name": "Primates", "rank": "order", "parent": "mammalia"},
        "human": {"taxon_id": 9606, "taxon_name": "Homo sapiens", "rank": "species", "parent": "primates"},
        "mouse": {"taxon_id": 10090, "taxon_name": "Mus musculus", "rank": "species", "parent": "mammalia"},
    }

    taxa = {}
    for key, definition in definitions.items():
        parent_taxon = taxa.get(definition["parent"])
        taxon, _ = Taxon.objects.get_or_create(
            taxon_id=definition["taxon_id"],
            defaults={
                "taxon_name": definition["taxon_name"],
                "rank": definition["rank"],
                "parent_taxon": parent_taxon,
            },
        )
        update_fields = []
        if taxon.taxon_name != definition["taxon_name"]:
            taxon.taxon_name = definition["taxon_name"]
            update_fields.append("taxon_name")
        if taxon.rank != definition["rank"]:
            taxon.rank = definition["rank"]
            update_fields.append("rank")
        if taxon.parent_taxon_id != (parent_taxon.pk if parent_taxon else None):
            taxon.parent_taxon = parent_taxon
            update_fields.append("parent_taxon")
        if update_fields:
            update_fields.append("updated_at")
            taxon.save(update_fields=update_fields)
        taxa[key] = taxon

    for taxon in taxa.values():
        ancestor = taxon
        depth = 0
        while ancestor is not None:
            TaxonClosure.objects.get_or_create(
                ancestor=ancestor,
                descendant=taxon,
                defaults={"depth": depth},
            )
            ancestor = ancestor.parent_taxon
            depth += 1

    return taxa
