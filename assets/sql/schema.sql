PRAGMA foreign_keys = ON;

CREATE TABLE taxonomy (
    taxon_id TEXT PRIMARY KEY,
    taxon_name TEXT NOT NULL,
    parent_taxon_id TEXT NOT NULL,
    rank TEXT NOT NULL,
    lineage TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE genomes (
    genome_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    accession TEXT NOT NULL,
    genome_name TEXT NOT NULL,
    assembly_type TEXT NOT NULL,
    taxon_id TEXT NOT NULL,
    assembly_level TEXT NOT NULL,
    species_name TEXT NOT NULL,
    download_path TEXT NOT NULL,
    notes TEXT NOT NULL,
    FOREIGN KEY (taxon_id) REFERENCES taxonomy(taxon_id)
);

CREATE TABLE sequences (
    sequence_id TEXT PRIMARY KEY,
    genome_id TEXT NOT NULL,
    sequence_name TEXT NOT NULL,
    sequence_length INTEGER NOT NULL,
    sequence_path TEXT NOT NULL,
    gene_symbol TEXT NOT NULL,
    transcript_id TEXT NOT NULL,
    isoform_id TEXT NOT NULL,
    assembly_accession TEXT NOT NULL,
    taxon_id TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    protein_external_id TEXT NOT NULL,
    translation_table TEXT NOT NULL,
    gene_group TEXT NOT NULL,
    linkage_status TEXT NOT NULL,
    partial_status TEXT NOT NULL,
    FOREIGN KEY (genome_id) REFERENCES genomes(genome_id),
    FOREIGN KEY (taxon_id) REFERENCES taxonomy(taxon_id)
);

CREATE TABLE proteins (
    protein_id TEXT PRIMARY KEY,
    sequence_id TEXT NOT NULL,
    genome_id TEXT NOT NULL,
    protein_name TEXT NOT NULL,
    protein_length INTEGER NOT NULL,
    protein_path TEXT NOT NULL,
    gene_symbol TEXT NOT NULL,
    translation_method TEXT NOT NULL,
    translation_status TEXT NOT NULL,
    assembly_accession TEXT NOT NULL,
    taxon_id TEXT NOT NULL,
    gene_group TEXT NOT NULL,
    protein_external_id TEXT NOT NULL,
    FOREIGN KEY (sequence_id) REFERENCES sequences(sequence_id),
    FOREIGN KEY (genome_id) REFERENCES genomes(genome_id),
    FOREIGN KEY (taxon_id) REFERENCES taxonomy(taxon_id)
);

CREATE TABLE run_params (
    method TEXT NOT NULL,
    param_name TEXT NOT NULL,
    param_value TEXT NOT NULL,
    PRIMARY KEY (method, param_name)
);

CREATE TABLE repeat_calls (
    call_id TEXT PRIMARY KEY,
    method TEXT NOT NULL CHECK (method IN ('pure', 'threshold', 'blast')),
    genome_id TEXT NOT NULL,
    taxon_id TEXT NOT NULL,
    sequence_id TEXT NOT NULL,
    protein_id TEXT NOT NULL,
    start INTEGER NOT NULL,
    end INTEGER NOT NULL,
    length INTEGER NOT NULL,
    repeat_residue TEXT NOT NULL,
    repeat_count INTEGER NOT NULL,
    non_repeat_count INTEGER NOT NULL,
    purity REAL NOT NULL,
    aa_sequence TEXT NOT NULL,
    codon_sequence TEXT NOT NULL,
    codon_metric_name TEXT NOT NULL,
    codon_metric_value TEXT NOT NULL,
    window_definition TEXT NOT NULL,
    template_name TEXT NOT NULL,
    merge_rule TEXT NOT NULL,
    score TEXT NOT NULL,
    source_file TEXT NOT NULL,
    FOREIGN KEY (genome_id) REFERENCES genomes(genome_id),
    FOREIGN KEY (taxon_id) REFERENCES taxonomy(taxon_id),
    FOREIGN KEY (sequence_id) REFERENCES sequences(sequence_id),
    FOREIGN KEY (protein_id) REFERENCES proteins(protein_id)
);
