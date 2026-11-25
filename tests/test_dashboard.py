"""DASH-01 / issue #17: dashboard summaries and combined search stay in scope."""

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case, CaseMembership
from clients.models import Client
from work.models import Deadline, Task

from .test_foundation import DEMO_PASSWORD, SeededTestCase


class DashboardTestCase(SeededTestCase):
    def setUp(self):
        self.admin = User.objects.get(email="admin@example.test")
        self.attorney = User.objects.get(email="attorney.a@example.test")
        self.other_attorney = User.objects.get(email="attorney.b@example.test")
        self.staff = User.objects.get(email="staff.a@example.test")
        self.alpha = Case.objects.get(number="DEMO-ALPHA")
        self.beta = Case.objects.get(number="DEMO-BETA")
        self.url = reverse("cases:dashboard")

    def cards(self, response):
        return {card.key: card for card in response.context["cards"]}

    def add_task(self, case, assignee, due_in, **fields):
        return Task.objects.create(
            case=case,
            title=fields.pop("title", f"Dashboard task {due_in}"),
            assignee=assignee,
            due_at=timezone.now() + due_in,
            created_by=self.attorney,
            **fields,
        )

    def add_deadline(self, case, due_in, **fields):
        return Deadline.objects.create(
            case=case,
            title=fields.pop("title", f"Dashboard deadline {due_in}"),
            type=Deadline.Type.HEARING,
            due_at=timezone.now() + due_in,
            responsible_user=fields.pop("responsible_user", self.attorney),
            created_by=self.attorney,
            **fields,
        )


class DashboardSummaryTests(DashboardTestCase):
    def test_every_count_matches_the_list_it_links_to(self):
        self.add_task(self.alpha, self.staff, timedelta(days=-2))
        self.add_task(self.alpha, self.staff, timedelta(days=2))
        self.add_task(
            self.alpha,
            self.staff,
            timedelta(days=3),
            status=Task.Status.DONE,
            completed_at=timezone.now(),
        )
        self.add_deadline(self.alpha, timedelta(days=-1))
        self.add_deadline(self.alpha, timedelta(days=4))
        for user in (self.attorney, self.staff, self.other_attorney, self.admin):
            self.client.force_login(user)
            for card in self.cards(self.client.get(self.url)).values():
                with self.subTest(user=user.email, card=card.key):
                    listed = self.client.get(card.url)
                    self.assertEqual(listed.status_code, 200)
                    self.assertEqual(listed.context["page"].paginator.count, card.count)
                    self.assertLessEqual(len(card.items), 5)

    def test_previews_are_sorted_by_due_date_then_id(self):
        same = timezone.now() + timedelta(days=1)
        first = self.add_task(self.alpha, self.staff, timedelta(days=1))
        second = self.add_task(self.alpha, self.staff, timedelta(days=1))
        Task.objects.filter(pk__in=[first.pk, second.pk]).update(due_at=same)
        self.client.force_login(self.staff)
        items = self.cards(self.client.get(self.url))["upcoming_tasks"].items
        keys = [(task.due_at, task.pk) for task in items]
        self.assertEqual(keys, sorted(keys))

    def test_a_user_with_no_work_sees_zeros_and_empty_states(self):
        newcomer = User.objects.create_user(
            "newcomer@example.test", DEMO_PASSWORD, full_name="New Staff", role=User.Role.STAFF
        )
        self.client.force_login(newcomer)
        response = self.client.get(self.url)
        self.assertEqual({card.count for card in self.cards(response).values()}, {0})
        self.assertEqual(response.context["activity"], [])
        self.assertContains(response, "You Have No Open Cases.")
        self.assertContains(response, "No Recent Activity In Your Cases.")
        self.assertNotContains(response, self.alpha.title)
        self.assertNotContains(response, self.beta.title)

    def test_an_unassigned_administrator_sees_nothing_firm_wide(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual({card.count for card in self.cards(response).values()}, {0})
        self.assertNotContains(response, self.alpha.title)

    def test_other_teams_records_never_appear(self):
        hidden_task = self.add_task(
            self.alpha, self.attorney, timedelta(days=-1), title="Alpha secret task"
        )
        self.add_deadline(self.alpha, timedelta(days=1), title="Alpha secret deadline")
        self.client.force_login(self.other_attorney)
        response = self.client.get(self.url)
        for text in (
            self.alpha.title,
            self.alpha.number,
            hidden_task.title,
            "Alpha secret deadline",
            "Fictional sample",
        ):
            self.assertNotContains(response, text)
        self.assertContains(response, self.beta.title)

    def test_completion_closure_and_membership_changes_recalculate(self):
        task = self.add_task(self.alpha, self.staff, timedelta(days=-1), title="Recount me")
        self.client.force_login(self.staff)
        before = self.cards(self.client.get(self.url))
        Task.objects.filter(pk=task.pk).update(status=Task.Status.DONE, completed_at=timezone.now())
        after = self.cards(self.client.get(self.url))
        self.assertEqual(after["overdue_tasks"].count, before["overdue_tasks"].count - 1)

        Task.objects.filter(case=self.alpha).update(assignee=self.attorney)
        self.assertEqual(self.cards(self.client.get(self.url))["overdue_tasks"].count, 0)

        CaseMembership.objects.filter(case=self.alpha, user=self.staff).update(is_active=False)
        response = self.client.get(self.url)
        self.assertEqual({card.count for card in self.cards(response).values()}, {0})
        self.assertEqual(response.context["activity"], [])
        self.assertNotContains(response, self.alpha.title)

    def test_closed_cases_leave_the_open_case_count(self):
        self.client.force_login(self.attorney)
        self.assertEqual(self.cards(self.client.get(self.url))["cases"].count, 1)
        Case.objects.filter(pk=self.alpha.pk).update(
            status=Case.Status.CLOSED, closed_on=timezone.localdate()
        )
        self.assertEqual(self.cards(self.client.get(self.url))["cases"].count, 0)
        open_list = self.client.get(reverse("cases:index"), {"status": "open"})
        self.assertEqual(open_list.context["page"].paginator.count, 0)

    def test_recent_activity_shows_only_visible_records_newest_first(self):
        self.add_task(self.beta, self.other_attorney, timedelta(days=1), title="Beta busywork")
        self.client.force_login(self.attorney)
        activity = self.client.get(self.url).context["activity"]
        self.assertTrue(activity)
        self.assertLessEqual(len(activity), 8)
        self.assertEqual({row.case.pk for row in activity}, {self.alpha.pk})
        times = [row.when for row in activity]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_query_count_does_not_grow_with_the_amount_of_work(self):
        self.client.force_login(self.staff)
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url)
        for offset in range(15):
            self.add_task(self.alpha, self.staff, timedelta(days=-1, minutes=offset))
            self.add_deadline(self.alpha, timedelta(days=1, minutes=offset))
        with CaptureQueriesContext(connection) as large:
            self.client.get(self.url)
        self.assertEqual(len(large), len(small))

    def test_dashboard_view_is_audited_and_requires_sign_in(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.staff)
        self.client.get(self.url)
        event = AuditEvent.objects.get(action="dashboard.read")
        self.assertEqual((event.actor, event.resource_type), (self.staff, "dashboard"))

    def test_quick_links_follow_capabilities(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertNotContains(response, reverse("cases:create"))
        self.assertNotContains(response, reverse("accounts:list"))
        self.client.force_login(self.attorney)
        self.assertContains(self.client.get(self.url), reverse("cases:create"))

    def test_task_window_filter_rejects_unknown_values(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("cases:work"), {"window": "someday"})
        self.assertIsNone(response.context["page"])


class GlobalSearchTests(DashboardTestCase):
    def setUp(self):
        super().setUp()
        self.search = reverse("cases:search")

    def test_finds_only_authorized_cases_and_clients(self):
        self.client.force_login(self.other_attorney)
        response = self.client.get(self.search, {"q": "Fictional"})
        self.assertEqual(response.status_code, 200)
        results = response.context["results"]
        self.assertEqual([case.pk for case in results["cases"].items], [self.beta.pk])
        names = {client.name for client in results["clients"].items}
        self.assertNotIn("Fictional Avery Lane", names)  # Alpha-only client
        self.assertNotIn("Fictional Intake A", names)  # another creator's intake
        self.assertNotContains(response, self.alpha.title)
        self.assertNotContains(response, "Fictional Avery Lane")

    def test_counts_match_the_linked_case_and_client_lists(self):
        self.client.force_login(self.attorney)
        results = self.client.get(self.search, {"q": "Fictional"}).context["results"]
        for section in results.values():
            with self.subTest(section=section.key):
                listed = self.client.get(section.url)
                self.assertEqual(listed.context["page"].paginator.count, section.count)

    def test_matches_on_reference_and_docket_metadata(self):
        Case.objects.filter(pk=self.alpha.pk).update(court_docket_number="CV-2026-0042")
        self.client.force_login(self.attorney)
        for query in ("DEMO-ALPHA", "cv-2026-0042"):
            with self.subTest(query=query):
                results = self.client.get(self.search, {"q": query}).context["results"]
                self.assertEqual([case.pk for case in results["cases"].items], [self.alpha.pk])

    def test_results_show_names_not_contact_details_or_notes(self):
        client = Client.objects.get(email="client.alpha@example.test")
        self.client.force_login(self.attorney)
        response = self.client.get(self.search, {"q": "client.alpha@example.test"})
        self.assertContains(response, client.name)
        self.assertNotContains(response, "+12025550101")
        self.assertNotContains(response, "client.alpha@example.test</")

    def test_previews_are_capped_and_link_to_the_full_list(self):
        for index in range(12):
            Client.objects.create(
                name=f"Fictional Bulk {index:02d}",
                type=Client.Type.INDIVIDUAL,
                created_by=self.attorney,
            )
        self.client.force_login(self.attorney)
        response = self.client.get(self.search, {"q": "Bulk"})
        clients = response.context["results"]["clients"]
        self.assertEqual((clients.count, len(clients.items)), (12, 10))
        self.assertContains(response, "Showing 10 Of 12.")

    def test_rejects_blank_long_and_unexpected_input(self):
        self.client.force_login(self.attorney)
        for params in ({}, {"q": "   "}, {"q": "x" * 151}, {"q": "alpha", "extra": "1"}):
            with self.subTest(params=params):
                response = self.client.get(self.search, params)
                self.assertEqual(response.status_code, 400)
                self.assertIsNone(response.context["results"])
        self.assertFalse(AuditEvent.objects.filter(action__endswith=".search").exists())

    def test_search_is_audited_without_the_query_text(self):
        self.client.force_login(self.attorney)
        self.client.get(self.search, {"q": "Confidential phrase"})
        events = AuditEvent.objects.filter(action__in=["case.search", "client.search"])
        self.assertEqual(events.count(), 2)
        for event in events:
            self.assertEqual(event.resource_id, "")
            self.assertEqual(event.changed_fields, [])

    def test_search_requires_sign_in(self):
        response = self.client.get(self.search, {"q": "Fictional"})
        self.assertEqual(response.status_code, 302)
