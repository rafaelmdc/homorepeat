CREATE INDEX idx_genomes_taxon_id ON genomes(taxon_id);

CREATE INDEX idx_sequences_genome_id ON sequences(genome_id);
CREATE INDEX idx_sequences_taxon_id ON sequences(taxon_id);
CREATE INDEX idx_sequences_gene_group ON sequences(gene_group);

CREATE INDEX idx_proteins_sequence_id ON proteins(sequence_id);
CREATE INDEX idx_proteins_genome_id ON proteins(genome_id);
CREATE INDEX idx_proteins_taxon_id ON proteins(taxon_id);
CREATE INDEX idx_proteins_gene_group ON proteins(gene_group);

CREATE INDEX idx_repeat_calls_method_residue ON repeat_calls(method, repeat_residue);
CREATE INDEX idx_repeat_calls_protein_id ON repeat_calls(protein_id);
CREATE INDEX idx_repeat_calls_sequence_id ON repeat_calls(sequence_id);
CREATE INDEX idx_repeat_calls_genome_id ON repeat_calls(genome_id);
CREATE INDEX idx_repeat_calls_taxon_id ON repeat_calls(taxon_id);

CREATE INDEX idx_run_params_method ON run_params(method);
