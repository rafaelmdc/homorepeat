nextflow.enable.dsl = 2

include { ACQUISITION_FROM_ACCESSIONS } from './workflows/acquisition_from_accessions'
include { DETECTION_FROM_ACQUISITION } from './workflows/detection_from_acquisition'
include { DATABASE_REPORTING } from './workflows/database_reporting'

workflow {
  acquisition = ACQUISITION_FROM_ACCESSIONS()
  detection = DETECTION_FROM_ACQUISITION(
    acquisition.sequences_tsv,
    acquisition.cds_fasta,
    acquisition.proteins_tsv,
    acquisition.proteins_fasta,
  )
  reporting = DATABASE_REPORTING(
    acquisition.taxonomy_tsv,
    acquisition.genomes_tsv,
    acquisition.sequences_tsv,
    acquisition.proteins_tsv,
    detection.call_tsv,
    detection.run_params_tsv,
  )

  emit:
  acquisition_validation = acquisition.acquisition_validation
  sqlite = reporting.sqlite
  sqlite_validation = reporting.sqlite_validation
  summary_by_taxon = reporting.summary_by_taxon
  regression_input = reporting.regression_input
  report_prep = reporting.report_prep
  echarts_report = reporting.echarts_report
}
