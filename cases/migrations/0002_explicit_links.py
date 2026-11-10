"""Promote existing join tables into protected, explicit relationship models.

The underlying tables/columns/unique pairs are unchanged. Splitting database and
model state preserves every old link in both fresh installs and upgrades.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="CaseClient",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                        ("case", models.ForeignKey("cases.Case", on_delete=django.db.models.deletion.PROTECT, related_name="client_links")),
                        ("client", models.ForeignKey("clients.Client", on_delete=django.db.models.deletion.PROTECT, related_name="case_links")),
                    ],
                    options={"db_table": "cases_case_clients", "unique_together": {("case", "client")}},
                ),
                migrations.CreateModel(
                    name="CaseMembership",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False, auto_created=True, verbose_name="ID")),
                        ("case", models.ForeignKey("cases.Case", on_delete=django.db.models.deletion.PROTECT, related_name="memberships")),
                        ("user", models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name="memberships")),
                    ],
                    options={"db_table": "cases_case_members", "unique_together": {("case", "user")}},
                ),
                migrations.AlterField(
                    model_name="case", name="clients",
                    field=models.ManyToManyField("clients.Client", through="cases.CaseClient", related_name="cases"),
                ),
                migrations.AlterField(
                    model_name="case", name="members",
                    field=models.ManyToManyField(settings.AUTH_USER_MODEL, through="cases.CaseMembership", related_name="cases"),
                ),
            ],
        ),
    ]
