from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("browser", "0019_canonicalrepeatcallcodonusage_repeatcallcodonusage"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="canonicalrepeatcallcodonusage",
            index=models.Index(
                fields=["amino_acid", "repeat_call"],
                name="brw_crccu_aa_call_idx",
            ),
        ),
    ]
