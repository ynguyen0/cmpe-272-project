import {escape as e, link, button, heading, empty, field, choices, form, table} from "./components.js";

const main = document.querySelector("#main");
const header = document.querySelector("#header");
const notice = document.querySelector("#notice");
const dialog = document.querySelector("#confirmation");
const users = [
  {id: "ava", name: "Ava Morgan", email: "ava@example.test", role: "Attorney", active: true},
  {id: "eli", name: "Eli Chen", email: "eli@example.test", role: "Staff", active: true},
  {id: "admin", name: "Sam Patel", email: "sam@example.test", role: "Administrator", active: true},
  {id: "jules", name: "Jules Rivera", email: "jules@example.test", role: "Attorney", active: true},
];
const clients = [
  {id: "cedar", name: "Cedar Works", type: "Organization", email: "contact@example.test", owner: "ava"},
  {id: "reed", name: "Morgan Reed", type: "Individual", email: "morgan@example.test", owner: "jules"},
];
const cases = [
  {id: "alpha", title: "Cedar contract review", reference: "LF-001", client: "cedar", lead: "ava", team: ["ava", "eli"], type: "Corporate", status: "Open", summary: "Review the proposed vendor agreement."},
  {id: "beta", title: "Reed intake", reference: "LF-002", client: "reed", lead: "jules", team: ["jules"], type: "Civil", status: "Open", summary: "Review intake materials."},
];
const firmTimeZone = "America/Los_Angeles";
const firmClock = new Intl.DateTimeFormat("en-US", {
  timeZone: firmTimeZone, year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const clockParts = (instant) => Object.fromEntries(firmClock.formatToParts(instant).map(({type, value}) => [type, value]));
function firmDay(instant, offset) {
  const {year, month, day} = clockParts(instant);
  return new Date(Date.UTC(Number(year), Number(month) - 1, Number(day) + offset)).toISOString().slice(0, 10);
}
const firmDate = firmDay(new Date(), 2);
const tasks = [{id: "review", caseId: "alpha", title: "Review draft agreement", assignee: "eli", due: firmDate + "T17:00", priority: "Normal", status: "To do"}];
const deadlines = [{caseId: "alpha", title: "Vendor response", category: "Filing", owner: "ava", due: firmDate + "T17:00", status: "Pending"}];
const documents = [];
const events = [];
const sections = ["Overview", "Clients", "Team", "Documents", "Tasks", "Deadlines", "Activity"];
const fileTypes = new Set(["pdf", "docx", "txt", "png", "jpg", "jpeg"]);
let viewer = null;
let route = location.hash.slice(1) || "/";
let dirty = false;
let pending = false;
let previewState = "";
let filters = {};
let confirmAction = null;
let resetRequested = false;
let sequence = 0;

const byId = (records, id) => records.find((record) => record.id === id);
const person = (id) => byId(users, id)?.name || "Unassigned";
const isAdmin = () => viewer?.role === "Administrator";
const canManage = () => viewer && viewer.role !== "Staff";
const visibleCases = () => viewer ? cases.filter((item) => isAdmin() || item.team.includes(viewer.id)) : [];
const visibleClients = () => clients.filter((item) => {
  const linked = cases.some((matter) => matter.client === item.id);
  return isAdmin() || (linked ? visibleCases().some((matter) => matter.client === item.id) : item.owner === viewer?.id);
});
const availableCase = (id) => byId(visibleCases(), id);
const casePath = (id, section = "overview") => `/cases/${id}/${section}`;
const formatDue = (value) => `${value.replace("T", " ")} Pacific`;
const canComplete = (task) => availableCase(task.caseId)?.status !== "Closed" &&
  Boolean(availableCase(task.caseId)) && task.status !== "Done" && (canManage() || task.assignee === viewer.id);
const idFor = (prefix) => `${prefix}-${++sequence}`;

function announce(message) {
  notice.innerHTML = message ? `<div class="container"><p class="alert alert-success mb-0">${e(message)}</p></div>` : "";
}

function record(action, target, caseId = "") {
  events.unshift({action, target, caseId, actor: viewer.name, time: new Date(), result: "Success"});
}

function navigate(next, message = "", addHistory = true) {
  route = next;
  dirty = false;
  filters = {};
  previewState = "";
  if (addHistory) history.pushState(null, "", "#" + next);
  announce(message);
  render();
  main.focus();
}

function confirm(title, description, label, action, cancel = "Cancel") {
  dialog.querySelector("h2").textContent = title;
  dialog.querySelector("p").textContent = description;
  dialog.querySelector('[value="confirm"]').textContent = label;
  dialog.querySelector('[value="cancel"]').textContent = cancel;
  confirmAction = action;
  dialog.returnValue = "";
  dialog.showModal();
}

dialog.addEventListener("close", () => {
  const action = confirmAction;
  confirmAction = null;
  if (dialog.returnValue === "confirm") action?.();
});

function requestNavigation(next) {
  if (pending || route === next) return;
  if (dirty) {
    confirm("Discard unsaved changes?", "Changes to this form will be lost when you leave.", "Discard changes", () => navigate(next), "Keep editing");
  } else {
    navigate(next);
  }
}

window.addEventListener("hashchange", () => {
  const next = location.hash.slice(1) || "/";
  if (next === route) return;
  if (dirty || pending) {
    history.replaceState(null, "", "#" + route);
    requestNavigation(next);
  } else {
    navigate(next, "", false);
  }
});

window.addEventListener("beforeunload", (event) => {
  if (!dirty) return;
  event.preventDefault();
  event.returnValue = true;
});

function navigation() {
  const items = [["/dashboard", "Dashboard"], ["/clients", "Clients"], ["/cases", "Cases"],
    ["/my-tasks", "My tasks"], ["/deadlines", "Upcoming deadlines"]];
  if (isAdmin()) items.push(["/admin/users", "Users"], ["/admin/audit", "Audit log"]);
  const item = ([href, label]) => `<a href="#${href}"${route === href || route.startsWith(href + "/") ? ' aria-current="page"' : ""}>${label}</a>`;
  header.innerHTML = `<div class="container shell"><a class="brand" href="#/">LexFlow</a>
    <div class="actions"><span class="demo-label">Fictional data · Wireframe</span>
      ${viewer ? `<span>${e(viewer.name)} · ${e(viewer.role)}</span>${button("logout", "Sign out", "outline-light")}` : link("/login", "Sign in", "outline-light")}</div></div>
    ${viewer ? `<nav class="container nav-items" aria-label="Primary">${items.map(item).join("")}</nav>` : ""}`;
}

function listing(label, records, columns, row, options = {}) {
  const {statuses, searchable = false, archived = false, emptyMessage = "Records will appear here when added.", defaultStatus = ""} = options;
  const selected = filters.status ?? defaultStatus;
  const query = (filters.search || "").trim().toLowerCase();
  const matching = records.filter((item) =>
    (!query || [item.name, item.title, item.reference, item.action, item.target, item.email]
      .some((value) => value?.toLowerCase().includes(query))) &&
    (!selected || (item.status || item.type || item.result) === selected) &&
    (!archived || filters.archived || !item.archived));
  const pages = Math.max(1, Math.ceil(matching.length / 5));
  const page = Math.min(filters.page || 1, pages);
  const controls = (searchable || statuses || archived) ? `<form class="filters" data-filter>
    ${searchable ? field("search", "Search", {type: "search", value: filters.search}) : ""}
    ${statuses ? field("status", options.filterLabel || "Status", {value: selected, choices: [["", "All"], ...choices(statuses)]}) : ""}
    ${archived ? `<label class="form-check"><input type="checkbox" class="form-check-input" name="archived" ${filters.archived ? "checked" : ""}> Include archived</label>` : ""}
    <button class="btn btn-outline-secondary">Apply filters</button></form>` : "";
  return controls + `<p class="muted" role="status">${matching.length} ${matching.length === 1 ? "result" : "results"}</p>` +
    table(label, columns, matching.slice((page - 1) * 5, page * 5).map(row),
      records.length ? empty("No matches", "Change the filters to see more records.", button("clear", "Clear filters")) :
        empty("Nothing here yet", emptyMessage)) +
    (pages > 1 ? `<nav aria-label="Pagination" class="actions mt-3">
      ${page > 1 ? button("page", "Previous", "outline-secondary", page - 1) : ""}
      <span>Page ${page} of ${pages}</span>
      ${page < pages ? button("page", "Next", "outline-secondary", page + 1) : ""}</nav>` : "");
}

function dashboard() {
  const cards = [
    ["Cases", visibleCases().length, "/cases", "View cases"],
    ["Open tasks assigned to me", tasks.filter((task) => task.assignee === viewer.id && availableCase(task.caseId) && task.status !== "Done").length, "/my-tasks", "View my tasks"],
    ["Upcoming deadlines", upcomingDeadlines().length, "/deadlines", "View deadlines"],
  ];
  return heading("Dashboard", `Welcome, ${viewer.name}.`) + `<div class="grid">${cards.map(([label, count, href, action]) =>
    `<section class="panel"><h2 class="h5">${label}</h2><p class="display-5">${count}</p>${link(href, action)}</section>`).join("")}</div>`;
}

function clientForm(client) {
  return heading(client ? "Edit client" : "New client") + form("client",
    field("name", "Client name", {value: client?.name, required: true, attributes: 'maxlength="150"'}) +
    field("type", "Client type", {value: client?.type, choices: [["", "Select a type"], ...choices(["Individual", "Organization"])], required: true}) +
    field("email", "Email", {value: client?.email, type: "email", attributes: 'maxlength="254"'}) +
    field("phone", "Phone", {value: client?.phone, type: "tel", attributes: 'maxlength="30"'}) +
    field("address", "Address", {value: client?.address, type: "textarea", attributes: 'maxlength="500"'}),
    "Save client", client ? `/clients/${client.id}` : "/clients", client?.id);
}

function caseForm(clientId) {
  return heading("New case") + form("case",
    field("title", "Case title", {required: true, attributes: 'maxlength="200"'}) +
    field("reference", "Internal reference", {required: true, value: `LF-${String(cases.length + 1).padStart(3, "0")}`, attributes: 'maxlength="40"'}) +
    field("type", "Case type", {value: "Civil", choices: choices(["Civil", "Criminal", "Family", "Corporate", "Other"]), required: true}) +
    field("docket", "Court docket number", {hint: "Optional. Use the number assigned by the court.", attributes: 'maxlength="100"'}) +
    field("client", "Client", {required: true, value: clientId, choices: [["", "Select a client"], ...visibleClients().map((item) => [item.id, item.name])]}) +
    field("lead", "Responsible attorney", {required: true, value: viewer.role === "Attorney" ? viewer.id : "", choices: [["", "Select an attorney"], ...users.filter((item) => item.role === "Attorney" && item.active).map((item) => [item.id, item.name])]}) +
    field("summary", "Summary", {type: "textarea", attributes: 'maxlength="2000"'}),
    "Open case", clientId ? `/clients/${clientId}` : "/cases");
}

function taskList(records, includeCase = false) {
  return listing("Tasks", records, ["Task", includeCase ? "Case" : "Assignee", "Due", "Priority", "Status", "Action"],
    (task) => [e(task.title), includeCase ? link(casePath(task.caseId, "tasks"), availableCase(task.caseId).reference) : e(person(task.assignee)),
      e(formatDue(task.due)), e(task.priority), e(task.status), canComplete(task) ? button("complete", "Complete", "outline-primary", task.id) : "—"],
    {statuses: ["To do", "Done"], emptyMessage: "There are no assigned tasks here."});
}

function upcomingDeadlines() {
  const instant = new Date();
  const {year, month, day, hour, minute} = clockParts(instant);
  const current = `${year}-${month}-${day}T${hour}:${minute}`;
  const through = firmDay(instant, 7);
  return deadlines.filter((item) => availableCase(item.caseId) && item.status === "Pending" && item.due <= through + "T23:59")
    .map((item) => ({...item, status: item.due < current ? "Overdue" : "Upcoming"}));
}

function deadlineList(records, personal = false) {
  return listing("Deadlines", [...records].sort((a, b) => a.due.localeCompare(b.due)), ["Deadline", "Category", "Due", "Responsible", "Status"],
    (item) => [personal ? link(casePath(item.caseId, "deadlines"), item.title) : e(item.title), e(item.category), e(formatDue(item.due)), e(person(item.owner)), e(item.status)],
    {statuses: personal ? ["Upcoming", "Overdue"] : ["Pending", "Completed"], emptyMessage: "There are no deadlines to display."});
}

function activityList(records) {
  const time = new Intl.DateTimeFormat("en-US", {timeZone: "America/Los_Angeles", dateStyle: "short", timeStyle: "short"});
  return listing("Activity", records, ["Time (Pacific)", "Actor", "Action", "Reference", "Result"],
    (item) => [e(time.format(item.time)), e(item.actor), e(item.action), e(item.target), e(item.result)],
    {searchable: true, statuses: ["Success"], emptyMessage: "Changes will appear here as you rehearse workflows."});
}

function workspace(matter, section, action, targetId) {
  const base = casePath(matter.id, section);
  const editable = matter.status !== "Closed";
  const client = byId(visibleClients(), matter.client);
  const nav = `<nav class="sections" aria-label="Case workspace">${sections.map((name) =>
    `<a href="#${casePath(matter.id, name.toLowerCase())}"${section === name.toLowerCase() ? ' aria-current="page"' : ""}>${name}</a>`).join("")}</nav>`;
  const shell = link("/cases", "All cases") + heading(matter.title, `${matter.reference} · ${matter.status}`) + nav;
  if (action) {
    if (!editable) return denied();
    if (section === "documents" && action === "upload") {
      return shell + '<h2>Upload document</h2>' + form("upload",
        field("title", "Document title", {required: true, attributes: 'maxlength="200"'}) +
        field("category", "Category", {value: "Other", required: true, choices: choices(["Pleading", "Evidence", "Correspondence", "Contract", "Other"])}) +
        field("file", "Choose file", {type: "file", required: true, hint: "PDF, DOCX, TXT, PNG or JPEG up to 10 MiB. Choose a fictional file.", attributes: 'accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"'}),
        "Save document", base, matter.id);
    }
    if (section === "documents" && action === "archive") {
      if (!canManage()) return denied();
      const doc = documents.find((item) => item.id === targetId && item.caseId === matter.id && !item.archived);
      if (!doc) return unavailable();
      return shell + '<h2>Archive document</h2>' + `<p>${e(doc.title)} will leave the default list and remain available in authorized history.</p>` +
        form("archive", field("reason", "Archive reason", {required: true, attributes: 'maxlength="500"'}), "Archive document", base, doc.id);
    }
    if (section === "tasks" && action === "assign") {
      if (!canManage()) return denied();
      const members = matter.team.map((id) => byId(users, id)).filter((item) => item?.active);
      return shell + '<h2>Assign task</h2>' + form("task",
        field("title", "Task title", {required: true, attributes: 'maxlength="200"'}) +
        field("assignee", "Assignee", {required: true, value: members[0]?.id, choices: members.map((item) => [item.id, item.name])}) +
        field("due", "Due date and time", {required: true, type: "datetime-local", value: firmDate + "T17:00", hint: "Enter time in Pacific time."}) +
        field("priority", "Priority", {value: "Normal", choices: choices(["Low", "Normal", "High"])}),
        "Assign task", base, matter.id);
    }
    return unavailable();
  }
  switch (section) {
    case "overview":
      return shell + `<section class="panel"><h2 class="h5">Overview</h2><p>${e(matter.summary || "No summary yet.")}</p>
        <dl><dt>Case type</dt><dd>${e(matter.type)}</dd><dt>Responsible attorney</dt><dd>${e(person(matter.lead))}</dd>
        <dt>Court docket number</dt><dd>${e(matter.docket || "None recorded")}</dd></dl></section>`;
    case "clients":
      return shell + '<h2>Clients</h2>' + table("Case clients", ["Client", "Relationship"],
        client ? [[link(`/clients/${client.id}`, client.name), "Client"]] : []);
    case "team":
      return shell + '<h2>Team</h2>' + table("Case team", ["Name", "Role", "Responsibility"],
        matter.team.map((id) => [e(person(id)), e(byId(users, id)?.role), id === matter.lead ? "Lead attorney" : "Case team"]));
    case "documents":
      return shell + `<div class="heading"><h2>Documents</h2>${editable ? link(base + "/upload", "Upload document", "primary") : ""}</div>` +
        listing("Documents", documents.filter((item) => item.caseId === matter.id), ["Title", "File", "Category", "State", "Action"],
          (item) => [e(item.title), e(item.filename), e(item.category), item.archived ? `Archived. ${e(item.reason)}` : "Active",
            !item.archived && editable && canManage() ? link(base + "/archive/" + item.id, "Archive") : "—"],
          {archived: true, emptyMessage: "Upload a document to see its details here."});
    case "tasks":
      return shell + `<div class="heading"><h2>Tasks</h2>${editable && canManage() ? link(base + "/assign", "Assign task", "primary") : ""}</div>` +
        taskList(tasks.filter((item) => item.caseId === matter.id));
    case "deadlines":
      return shell + '<h2>Deadlines</h2>' + deadlineList(deadlines.filter((item) => item.caseId === matter.id));
    case "activity":
      return shell + '<h2>Activity</h2>' + activityList(events.filter((item) => item.caseId === matter.id));
    default:
      return unavailable();
  }
}

const denied = () => heading("Permission denied") +
  empty("This action is restricted", "Your demo role does not have permission to open this screen.", link("/dashboard", "Back to dashboard", "primary"));
const unavailable = () => heading("Record unavailable") +
  empty("This record could not be opened", "The link may be out of date or the record may be outside your assigned work.", link("/cases", "Back to cases", "primary"));

function landing() {
  return `<section class="hero"><h1>Legal case management for law firms</h1>
    <p class="lead">LexFlow brings client records, case documents, deadlines, and assigned work into one workspace for attorneys and staff.</p>
    ${link(viewer ? "/dashboard" : "/login", viewer ? "Open dashboard" : "Open wireframe", "primary")}</section>
    <div class="grid mt-4">
      <section class="panel"><h2 class="h5">Manage client matters</h2><p>Connect each case with its clients and responsible team.</p></section>
      <section class="panel"><h2 class="h5">Organize case documents</h2><p>Keep working files and archived records with the relevant matter.</p></section>
      <section class="panel"><h2 class="h5">Track work and deadlines</h2><p>See who owns each task and when work is due.</p></section>
    </div>`;
}

function screen() {
  const [path, query = ""] = route.split("?");
  const [, area, id, section, action, targetId, ...extra] = path.split("/");
  if (path === "/") return landing();
  if (path === "/login") return heading("Sign in", "Choose a fictional account to preview its workspace.") +
    form("login", field("user", "Demo account", {value: "ava", required: true, choices: users.filter((item) => item.active)
      .map((item) => [item.id, `${item.role} · ${item.name}`])}), "Continue", "/") +
    `<p class="mt-3">${link("/recovery", "Forgot your password?")}</p>`;
  if (path === "/recovery") return heading("Recover your account") + form("recovery",
    field("email", "Work email", {type: "email", required: true, hint: "Use a fictional address. This preview sends no email."}),
    "Request reset link", "/login");
  if (path === "/recovery/sent") return heading("Check your email") +
    empty("Recovery requested", "If an account exists for that address, recovery instructions will be sent. No email was sent in this wireframe.",
      '<div class="actions">' + link("/recovery/reset", "Preview reset link", "primary") + link("/login", "Back to sign in") + "</div>");
  if (path === "/recovery/reset") {
    if (!resetRequested) return heading("Reset link unavailable") +
      empty("Request a new link", "This link has expired or has already been used.", link("/recovery", "Request a new link", "primary"));
    return heading("Set a new password", "Use a fictional password for this preview.") + form("reset",
      field("password", "New password", {type: "password", required: true, hint: "Use 12 to 128 characters.", attributes: 'minlength="12" maxlength="128" autocomplete="new-password"'}) +
      field("repeat", "Confirm new password", {type: "password", required: true, attributes: 'maxlength="128" autocomplete="new-password"'}),
      "Reset password", "/login");
  }
  if (!viewer) return heading("Sign in to continue") +
    empty("A demo account is required", "Choose an account to open the workspace.", link("/login", "Sign in", "primary"));
  if (path === "/dashboard") return dashboard();
  if (path === "/my-tasks") return heading("My tasks", "Work assigned to you across your visible cases.") +
    taskList(tasks.filter((item) => item.assignee === viewer.id && availableCase(item.caseId)), true);
  if (path === "/deadlines") return heading("Upcoming deadlines", "Overdue items and deadlines through the next seven days in Pacific time.") +
    deadlineList(upcomingDeadlines(), true);
  if (path === "/clients") return heading("Clients", "", link("/clients/new", "New client", "primary")) +
    listing("Clients", visibleClients(), ["Client", "Type", "Email"],
      (item) => [link(`/clients/${item.id}`, item.name), e(item.type), e(item.email || "—")],
      {searchable: true, statuses: ["Individual", "Organization"], filterLabel: "Client type", emptyMessage: "Create a client to start an intake."});
  if (path === "/clients/new") return clientForm();
  if (area === "clients" && id && !action && !targetId && !extra.length) {
    const client = byId(visibleClients(), id);
    if (!client) return unavailable();
    if (section === "edit") return clientForm(client);
    if (section) return unavailable();
    return link("/clients", "All clients") + heading(client.name, client.type,
      link(`/clients/${id}/edit`, "Edit client", "outline-secondary") +
      (canManage() ? link(`/cases/new?client=${id}`, "Open case for this client", "primary") : "")) +
      `<section class="panel mb-4"><h2 class="h5">Contact details</h2><dl class="mb-0">
      <dt>Email</dt><dd>${e(client.email || "None recorded")}</dd><dt>Phone</dt><dd>${e(client.phone || "None recorded")}</dd>
      <dt>Address</dt><dd>${e(client.address || "None recorded")}</dd></dl></section><h2>Cases</h2>` +
      table("Client cases", ["Reference", "Case", "Status"],
        visibleCases().filter((item) => item.client === id).map((item) => [e(item.reference), link(casePath(item.id), item.title), e(item.status)]),
        empty("No visible cases", "Cases linked to this client will appear here when you have access."));
  }
  if (path === "/cases") return heading("Cases", "", canManage() ? link("/cases/new", "New case", "primary") : "") +
    listing("Cases", visibleCases(), ["Reference", "Title", "Responsible attorney", "Status"],
      (item) => [e(item.reference), link(casePath(item.id), item.title), e(person(item.lead)), e(item.status)],
      {searchable: true, statuses: ["Open", "On hold", "Closed"], emptyMessage: "Cases appear here when you open one or join a case team."});
  if (path === "/cases/new") {
    if (!canManage()) return denied();
    const clientId = new URLSearchParams(query).get("client");
    if (clientId && !byId(visibleClients(), clientId)) return unavailable();
    if (!visibleClients().length) return heading("New case") +
      empty("A client is required", "Create a client before opening this case.", link("/clients/new", "New client", "primary"));
    return caseForm(clientId);
  }
  if (area === "cases" && id && !extra.length) {
    const matter = availableCase(id);
    return matter ? workspace(matter, section || "overview", action, targetId) : unavailable();
  }
  if (area === "admin") {
    if (!isAdmin()) return denied();
    if (path === "/admin/audit") return heading("Audit log", "Administrator access") + activityList(events);
    if (path === "/admin/users") return heading("User administration", "Administrator access", link("/admin/users/new", "New user", "primary")) +
      listing("Users", users.map((item) => ({...item, status: item.active ? "Active" : "Inactive"})), ["Name", "Email", "Role", "Status", "Action"],
        (item) => [e(item.name), e(item.email), e(item.role), e(item.status),
          item.id !== viewer.id ? button("toggle-user", item.active ? "Deactivate" : "Reactivate", "outline-secondary", item.id) : "Current account"],
        {searchable: true, statuses: ["Active", "Inactive"]});
    if (path === "/admin/users/new") return heading("New user") + form("user",
      field("name", "Full name", {required: true, attributes: 'maxlength="100"'}) +
      field("email", "Work email", {type: "email", required: true, attributes: 'maxlength="254"'}) +
      field("role", "Role", {required: true, value: "Staff", choices: choices(["Staff", "Attorney", "Administrator"])}),
      "Create user", "/admin/users");
  }
  return unavailable();
}

function render() {
  navigation();
  if (previewState === "loading") {
    main.setAttribute("aria-busy", "true");
    main.innerHTML = '<h1>Loading workspace</h1><p role="status">Loading records…</p>';
    return;
  }
  main.removeAttribute("aria-busy");
  main.innerHTML = previewState === "error" ?
    heading("We couldn't load this screen") +
    `<p role="alert">The request failed. Try loading the screen again.</p>${button("retry", "Try again", "primary")}` : screen();
  document.title = `${main.querySelector("h1")?.textContent || "Workspace"} | LexFlow wireframe`;
}

function setPreview(state) {
  const apply = () => {
    dirty = false;
    previewState = state;
    announce("");
    render();
    main.focus();
    if (state === "loading") setTimeout(() => {
      if (previewState === "loading") setPreview("");
    }, 1300);
  };
  if (dirty) confirm("Discard unsaved changes?", "Opening a preview state will discard this draft.", "Discard changes", apply, "Keep editing");
  else apply();
}

function fieldErrors(node, data) {
  const errors = {};
  for (const control of node.querySelectorAll("input, select, textarea")) {
    const {name, validity, validationMessage} = control;
    if (!validity.valid) errors[name] = validationMessage;
    else if (control.required && typeof data[name] === "string" && !data[name]) errors[name] = "Enter a value.";
  }
  if (node.dataset.form === "reset" && data.password !== data.repeat) {
    errors.repeat = "The passwords must match.";
  }
  if (node.dataset.form === "case" && cases.some((item) => item.reference.toLowerCase() === data.reference.toLowerCase())) {
    errors.reference = "This internal reference already exists.";
  }
  if (node.dataset.form === "user" && users.some((item) => item.email.toLowerCase() === data.email.toLowerCase())) {
    errors.email = "An account already uses this address.";
  }
  if (node.dataset.form === "upload" && data.file.size) {
    const extension = data.file.name.split(".").at(-1).toLowerCase();
    if (!data.file.name.includes(".") || !fileTypes.has(extension) || data.file.size > 10 * 1024 * 1024) {
      errors.file = "Choose a supported file up to 10 MiB.";
    }
  } else if (node.dataset.form === "upload") {
    errors.file = "Choose a nonempty file.";
  }
  return errors;
}

function showErrors(node, errors) {
  const summary = node.querySelector("[data-errors]");
  summary.hidden = !Object.keys(errors).length;
  summary.innerHTML = "";
  for (const control of node.querySelectorAll("input, select, textarea")) {
    const error = errors[control.name];
    document.getElementById(control.id + "-error").textContent = error || "";
    if (error) control.setAttribute("aria-invalid", "true");
    else control.removeAttribute("aria-invalid");
  }
  if (!summary.hidden) {
    summary.innerHTML = "<strong>Check the highlighted fields.</strong><ul class='mb-0'>" +
      Object.entries(errors).map(([name, message]) => {
        const label = node.elements[name].labels[0].textContent;
        return `<li><a href="#field-${name}" data-focus="field-${name}">${e(label)} · ${e(message)}</a></li>`;
      }).join("") + "</ul>";
    summary.focus();
  }
}

function save(kind, id, data) {
  switch (kind) {
    case "login":
      viewer = users.find((item) => item.id === data.user && item.active);
      navigate(viewer ? "/dashboard" : "/login");
      break;
    case "recovery":
      resetRequested = true;
      navigate("/recovery/sent");
      break;
    case "reset":
      resetRequested = false;
      navigate("/login", "Password reset preview complete. Choose a fictional account to continue.");
      break;
    case "client": {
      const client = id ? byId(visibleClients(), id) : {id: idFor("client"), owner: viewer.id};
      if (!client) return navigate("/clients");
      Object.assign(client, data);
      if (!id) clients.push(client);
      record(id ? "Client updated" : "Client created", client.id);
      navigate(`/clients/${client.id}`, "Client saved.");
      break;
    }
    case "case": {
      const matter = {...data, id: idFor("case"), status: "Open", team: [...new Set([data.lead, viewer.id])]};
      cases.push(matter);
      record("Case opened", matter.reference, matter.id);
      navigate(casePath(matter.id), "Case opened.");
      break;
    }
    case "upload":
      documents.push({id: idFor("document"), caseId: id, title: data.title, category: data.category, filename: data.file.name});
      record("Document uploaded", availableCase(id).reference, id);
      navigate(casePath(id, "documents"), "Document added to the wireframe.");
      break;
    case "archive": {
      const doc = byId(documents, id);
      doc.archived = true;
      doc.reason = data.reason;
      record("Document archived", availableCase(doc.caseId).reference, doc.caseId);
      navigate(casePath(doc.caseId, "documents"), "Document archived. Use Include archived to find it.");
      break;
    }
    case "task":
      tasks.push({...data, caseId: id, id: idFor("task"), status: "To do"});
      record("Task assigned", availableCase(id).reference, id);
      navigate(casePath(id, "tasks"), "Task assigned.");
      break;
    case "user": {
      const user = {...data, id: idFor("user"), active: true};
      users.push(user);
      record("User created", user.id);
      navigate("/admin/users", "User created.");
      break;
    }
  }
}

document.addEventListener("input", (event) => {
  if (event.target.closest("form[data-form]")) dirty = true;
});

document.addEventListener("change", (event) => {
  if (event.target.closest("form[data-form]")) dirty = true;
});

document.addEventListener("submit", (event) => {
  const node = event.target;
  if (!node.matches("[data-filter], [data-form]")) return;
  event.preventDefault();
  if (pending) return;
  const data = Object.fromEntries([...new FormData(node)].map(([key, value]) =>
    [key, typeof value === "string" && node.elements[key]?.type !== "password" ? value.trim() : value]));
  if (node.hasAttribute("data-filter")) {
    filters = data;
    render();
    main.querySelector("[data-filter] button")?.focus();
    return;
  }
  const errors = fieldErrors(node, data);
  showErrors(node, errors);
  if (Object.keys(errors).length) return;
  pending = true;
  node.setAttribute("aria-busy", "true");
  node.querySelector("[data-saving]").textContent = "Working…";
  for (const control of node.elements) control.disabled = true;
  setTimeout(() => {
    pending = false;
    save(node.dataset.form, node.dataset.id, data);
  }, 250);
});

document.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const anchor = event.target.closest('a[href^="#"]');
  if (anchor) {
    event.preventDefault();
    if (anchor.id === "skip") main.focus();
    else if (anchor.dataset.focus) document.getElementById(anchor.dataset.focus)?.focus();
    else requestNavigation(anchor.getAttribute("href").slice(1));
    return;
  }
  const control = event.target.closest("[data-action]");
  if (!control || pending) return;
  const {action, id} = control.dataset;
  switch (action) {
    case "logout":
      if (dirty) {
        confirm("Discard changes and sign out?", "Your unsaved draft will be lost.", "Sign out", () => {
          viewer = null;
          navigate("/login", "Signed out of the wireframe.");
        }, "Keep editing");
      } else {
        viewer = null;
        navigate("/login", "Signed out of the wireframe.");
      }
      break;
    case "complete": {
      const task = byId(tasks, id);
      if (task && canComplete(task)) confirm("Complete task?", task.title + " will move to Done.", "Mark done", () => {
        task.status = "Done";
        record("Task completed", availableCase(task.caseId).reference, task.caseId);
        filters.status = "Done";
        announce("Task completed.");
        render();
        main.focus();
      });
      break;
    }
    case "toggle-user": {
      const user = byId(users, id);
      if (isAdmin() && user && user !== viewer) {
        const label = user.active ? "Deactivate" : "Reactivate";
        confirm(label + " account?", user.active ? "This demo account will lose sign-in access. Its history is retained." : "This demo account will regain sign-in access.", label, () => {
          user.active = !user.active;
          record(`User ${label.toLowerCase()}d`, user.id);
          announce(`Account ${label.toLowerCase()}d.`);
          render();
          main.focus();
        });
      }
      break;
    }
    case "page":
      filters.page = Number(id);
      render();
      main.querySelector(".table-wrap")?.focus();
      break;
    case "clear":
      filters = {};
      render();
      main.querySelector("[data-filter] input, [data-filter] select")?.focus();
      break;
    case "loading":
      setPreview("loading");
      break;
    case "error":
      setPreview("error");
      break;
    case "retry":
      setPreview("");
      break;
  }
});

render();
