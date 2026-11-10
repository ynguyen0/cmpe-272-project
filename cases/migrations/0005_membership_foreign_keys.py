"""Keep case responsibility and work assignees within the same case team.

Deferrable keys allow creation of a case and its first membership in one transaction.
The existing unique(case_id, user_id) pair is the referenced candidate key.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0004_alter_case_created_at_and_more"),
        ("work", "0003_alter_deadline_due_at_and_more"),
    ]
    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE cases_case ADD CONSTRAINT case_responsible_member_fk
              FOREIGN KEY (id, responsible_attorney_id)
              REFERENCES cases_case_members (case_id, user_id)
              DEFERRABLE INITIALLY DEFERRED;
            ALTER TABLE work_task ADD CONSTRAINT task_case_assignee_fk
              FOREIGN KEY (case_id, assignee_id)
              REFERENCES cases_case_members (case_id, user_id)
              DEFERRABLE INITIALLY DEFERRED;
            ALTER TABLE work_deadline ADD CONSTRAINT deadline_case_responsible_fk
              FOREIGN KEY (case_id, responsible_user_id)
              REFERENCES cases_case_members (case_id, user_id)
              DEFERRABLE INITIALLY DEFERRED;
            """,
            """
            ALTER TABLE work_deadline DROP CONSTRAINT deadline_case_responsible_fk;
            ALTER TABLE work_task DROP CONSTRAINT task_case_assignee_fk;
            ALTER TABLE cases_case DROP CONSTRAINT case_responsible_member_fk;
            """,
        ),
    ]
