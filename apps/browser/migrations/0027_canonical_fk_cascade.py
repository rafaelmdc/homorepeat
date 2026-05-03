from django.db import migrations


_CASCADE_FKS = [
    # (table, column, constraint_name, ref_table, ref_column)
    (
        "browser_canonicalsequence",
        "genome_id",
        "browser_canonicalseq_genome_id_e1c420fc_fk_browser_c",
        "browser_canonicalgenome",
        "id",
    ),
    (
        "browser_canonicalprotein",
        "genome_id",
        "browser_canonicalpro_genome_id_6eb7f92b_fk_browser_c",
        "browser_canonicalgenome",
        "id",
    ),
    (
        "browser_canonicalprotein",
        "sequence_id",
        "browser_canonicalpro_sequence_id_5478ff8d_fk_browser_c",
        "browser_canonicalsequence",
        "id",
    ),
    (
        "browser_canonicalrepeatcall",
        "genome_id",
        "browser_canonicalrep_genome_id_34379c35_fk_browser_c",
        "browser_canonicalgenome",
        "id",
    ),
    (
        "browser_canonicalrepeatcall",
        "protein_id",
        "browser_canonicalrep_protein_id_7510bfbe_fk_browser_c",
        "browser_canonicalprotein",
        "id",
    ),
    (
        "browser_canonicalrepeatcall",
        "sequence_id",
        "browser_canonicalrep_sequence_id_9581ccd2_fk_browser_c",
        "browser_canonicalsequence",
        "id",
    ),
    (
        "browser_canonicalrepeatcallcodonusage",
        "repeat_call_id",
        "browser_canonicalrep_repeat_call_id_d28a1533_fk_browser_c",
        "browser_canonicalrepeatcall",
        "id",
    ),
]


def _apply_cascade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table, col, constraint, ref_table, ref_col in _CASCADE_FKS:
            cursor.execute(f"""
                ALTER TABLE {table}
                    DROP CONSTRAINT {constraint},
                    ADD CONSTRAINT {constraint}
                        FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col})
                        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
            """)


def _remove_cascade(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table, col, constraint, ref_table, ref_col in _CASCADE_FKS:
            cursor.execute(f"""
                ALTER TABLE {table}
                    DROP CONSTRAINT {constraint},
                    ADD CONSTRAINT {constraint}
                        FOREIGN KEY ({col}) REFERENCES {ref_table}({ref_col})
                        DEFERRABLE INITIALLY DEFERRED
            """)


class Migration(migrations.Migration):

    dependencies = [
        ("browser", "0026_pipelinerun_lifecycle_and_canonical_run_indexes"),
    ]

    operations = [
        migrations.RunPython(_apply_cascade, reverse_code=_remove_cascade),
    ]
