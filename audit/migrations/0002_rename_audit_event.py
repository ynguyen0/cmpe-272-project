from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RenameModel("Event", "AuditEvent")]
