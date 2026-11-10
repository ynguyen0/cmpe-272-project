from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("audit", "0003_audit_schema")]
    operations = [
        migrations.RunSQL(
            """
            CREATE FUNCTION lexflow_protect_audit_history() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'Audit history is append-only' USING ERRCODE = '23514';
            END;
            $$;
            CREATE TRIGGER audit_history_immutable
              BEFORE UPDATE OR DELETE ON audit_auditevent
              FOR EACH ROW EXECUTE FUNCTION lexflow_protect_audit_history();
            """,
            """
            DROP TRIGGER audit_history_immutable ON audit_auditevent;
            DROP FUNCTION lexflow_protect_audit_history();
            """,
        )
    ]
