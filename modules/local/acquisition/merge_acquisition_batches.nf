process MERGE_ACQUISITION_BATCHES {
    label 'acquisition_merge'
    publishDir("${params.output_dir}/acquisition", mode: 'copy', saveAs: { filename ->
        filename.startsWith('acquisition_artifacts/') ? filename.substring('acquisition_artifacts/'.length()) : filename
    })

    input:
    path(translated_batch_dirs)

    output:
    path("acquisition_artifacts/genomes.tsv"), emit: genomes_tsv
    path("acquisition_artifacts/taxonomy.tsv"), emit: taxonomy_tsv
    path("acquisition_artifacts/sequences.tsv"), emit: sequences_tsv
    path("acquisition_artifacts/proteins.tsv"), emit: proteins_tsv
    path("acquisition_artifacts/cds.fna"), emit: cds_fasta
    path("acquisition_artifacts/proteins.faa"), emit: proteins_fasta
    path("acquisition_artifacts/download_manifest.tsv"), emit: download_manifest_tsv
    path("acquisition_artifacts/normalization_warnings.tsv"), emit: normalization_warnings_tsv
    path("acquisition_artifacts/acquisition_validation.json"), emit: acquisition_validation

    script:
    def batchInputs = translated_batch_dirs instanceof List ? translated_batch_dirs : [translated_batch_dirs]
    def batchArgs = batchInputs.collect { "--batch-inputs '${it}'" }.join(' ')
    """
    export PYTHONPATH="${projectDir}:\${PYTHONPATH:-}"

    ${params.python_bin} ${projectDir}/bin/merge_acquisition_batches.py \
      ${batchArgs} \
      --outdir acquisition_artifacts
    """
}
