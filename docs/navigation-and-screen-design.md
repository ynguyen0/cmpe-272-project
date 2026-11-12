# Navigation and screen design

Open the clickable wireframe at `/wireframe/` with development settings. It uses fictional records and simulated sign-in, recovery, uploads, and saves. Changes live in the open page and reset on refresh. The existing Django sign-in and case views are separate.

## Journey and navigation

The landing page explains how law-firm teams use LexFlow to connect clients, cases, documents, and assigned work. Sign in leads to the dashboard. The preview uses an account picker to let the team compare roles. The production sign-in screen uses email and password. Account recovery starts with a work email and shows the same acknowledgment for known and unknown addresses. The preview can open the reset form directly. A reset asks for a new password and confirmation, returns to sign-in on success, and offers a new request when a link is expired or used.

| Screen | Entry and primary action | Next screen or return path |
| --- | --- | --- |
| Dashboard | After sign-in. Review assigned cases, open tasks, and upcoming deadlines. | Open the relevant case, personal task list, or deadlines. |
| Clients | Primary navigation. Search by name, filter by type, and open a client. | New client and edit save to client detail. Detail links to visible cases and starts a case with the client selected. |
| Cases | Primary navigation. Search by title or reference and filter by status. | New case requires a client and responsible attorney. Save opens the new case workspace. |
| Case workspace | Open from Cases, Clients, or Dashboard. Persistent case title and section navigation. | Overview summarizes the case. Clients and Team show its relationships. Documents supports upload and archive. Tasks supports assignment and completion. Deadlines shows responsible people and due times. Activity shows case events. |
| My tasks | Primary navigation. Filter work assigned to the signed-in user. | Complete a task after confirmation or follow its case link. |
| Upcoming deadlines | Primary navigation. Review upcoming and overdue case dates. | Follow the case link for context. |
| User administration | Administrator navigation. Review accounts and preview creating or deactivating one. | Return to users after saving or cancelling. |
| Audit log | Administrator navigation. Filter recent events. | Review event outcomes and references without exposing document contents or secrets. |

The dashboard and case links respect the selected demo role and case membership. Staff can create clients, upload to an assigned open case, and complete their own tasks. Attorneys and administrators can open cases and assign work. The prototype represents a forbidden role action with a permission screen and uses the same unavailable screen for missing and out-of-scope records. Production screens must enforce the release backlog's server-side policy.

## Shared screen behavior

- Forms use persistent labels, field hints, inline errors, and a summary that receives focus on failure. Invalid input preserves the draft. Successful actions show a status message on the destination.
- Lists use search, filters, result counts, paginated tables, and distinct empty states for no records and no matches. On small screens, tables scroll inside labeled, keyboard-focusable regions. Navigation wraps and forms stack.
- Saving briefly shows a busy state and disables the submit control. A duplicate internal case reference or invalid file shows validation feedback. A missing record offers a route back. The preview controls also expose loading and retryable error states.
- Confirmation dialogs keep focus inside the dialog and place initial focus on Cancel or Keep editing. Archive removes a document from the default list and keeps it in authorized history. Leaving a changed form asks whether to discard the draft. Escape cancels the dialog.
- The skip link, page headings, current navigation markers, live feedback, and visible focus support keyboard navigation. Case section links are ordinary navigation links and follow standard Tab behavior.

## Team walkthrough

1. Open the landing page, choose **Open wireframe**, and continue as **Attorney**.
2. Open **Clients → New client**. Enter a fictional name and type and save. Confirm the client detail shows the new record.
3. Select **Open case for this client**. Enter a title and unique internal reference. Confirm the client and responsible attorney and save.
4. Open **Documents → Upload document**. Choose a small fictional PDF or text file, enter a title and category, and save. Confirm the document appears. Archive it, then select **Include archived** and apply the filters to find it again. The upload preview retains the filename and form metadata in memory.
5. Open **Tasks → Assign task**. Give the task a title and due date/time and assign it to yourself. Open **My tasks**, choose **Complete**, and confirm. Switch to the Done filter to verify the result. The case Activity section shows the simulated changes.
6. Repeat an action at a narrow viewport. Try an empty required field, a changed form followed by navigation, the recovery screen, and a staff visit to the administrator URL. Use the preview controls to inspect loading and retry.

The wireframe defaults the new case's attorney to the signed-in attorney, and the assignment form to the first eligible member. A demo sign-out keeps the open page's fictional records so the team can switch roles during rehearsal.
