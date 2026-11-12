export const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) =>
  ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[char]);

export const link = (href, label, style = "") =>
  `<a href="#${escape(href)}" ${style ? `class="btn btn-${style}"` : ""}>${escape(label)}</a>`;

export const button = (action, label, style = "outline-secondary", id = "") =>
  `<button type="button" class="btn btn-${style}" data-action="${escape(action)}" data-id="${escape(id)}">${escape(label)}</button>`;

export const heading = (title, description = "", actions = "") =>
  `<div class="heading"><div><h1>${escape(title)}</h1>${description ? `<p class="muted mb-0">${escape(description)}</p>` : ""}</div><div class="actions">${actions}</div></div>`;

export const empty = (title, message, action = "") =>
  `<section class="empty"><h2 class="h5">${escape(title)}</h2><p>${escape(message)}</p>${action}</section>`;

export function field(name, label, options = {}) {
  const {value = "", type = "text", required = false, choices, hint = "", attributes = ""} = options;
  const id = `field-${name}`;
  const props = `id="${id}" name="${name}" aria-describedby="${id}-error${hint ? ` ${id}-hint` : ""}" ${required ? "required" : ""} ${attributes}`;
  let control;
  if (choices) {
    control = `<select class="form-select" ${props}>${choices.map(([key, text]) =>
      `<option value="${escape(key)}"${String(key) === String(value) ? " selected" : ""}>${escape(text)}</option>`).join("")}</select>`;
  } else if (type === "textarea") {
    control = `<textarea class="form-control" rows="3" ${props}>${escape(value)}</textarea>`;
  } else {
    control = `<input class="form-control" type="${type}" ${props} ${type === "file" ? "" : `value="${escape(value)}"`}>`;
  }
  return `<div class="field"><label for="${id}">${escape(label)}${required ? " (required)" : ""}</label>${control}
    ${hint ? `<div class="form-text muted" id="${id}-hint">${escape(hint)}</div>` : ""}
    <div class="field-error" id="${id}-error"></div></div>`;
}

export const choices = (values) => values.map((value) => [value, value]);

export function form(kind, fields, submit, cancel, id = "") {
  return `<form class="panel form-shell" data-form="${kind}" data-id="${escape(id)}" novalidate>
    <div class="alert alert-danger" data-errors tabindex="-1" hidden></div>
    ${fields}<div class="actions"><button class="btn btn-primary" type="submit">${escape(submit)}</button>
    ${link(cancel, "Cancel", "outline-secondary")}</div><p class="mb-0 mt-2" role="status" data-saving></p></form>`;
}

export function table(label, columns, rows, fallback) {
  if (!rows.length) return fallback || empty("Nothing here yet", "Records will appear here when added.");
  return `<div class="table-wrap" role="region" aria-label="${escape(label)}" tabindex="0">
    <table class="table"><caption class="visually-hidden">${escape(label)}</caption>
    <thead><tr>${columns.map((column) => `<th scope="col">${escape(column)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
