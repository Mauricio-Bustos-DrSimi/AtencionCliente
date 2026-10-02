const state = { user: null, csrf: null, evaluations: [], summary: {}, activeEvaluation: null, activePlanTab: "todos" };
const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

async function api(url, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.csrf && options.method && options.method !== "GET") {
    headers["X-CSRF-Token"] = state.csrf;
  }
  const response = await fetch(url, { credentials: "same-origin", ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(body.detail || `Error ${response.status}`);
  }
  return body;
}

function showLogin() {
  state.user = null;
  state.csrf = null;
  $("#login-screen").classList.remove("hidden");
  $("#app-screen").classList.add("hidden");
}

function showApp(user) {
  state.user = user;
  state.csrf = user.csrf_token;
  $("#login-screen").classList.add("hidden");
  $("#app-screen").classList.remove("hidden");
  $("#user-name").textContent = user.full_name;
  $("#user-role").textContent = user.role_label;
  $("#user-avatar").textContent = (user.full_name || "U").trim().slice(0, 1).toUpperCase();
  $("#users-nav").classList.toggle("hidden", user.role !== "admin");
  const scope = user.scope_name ? ` · Alcance: ${user.scope_name}` : "";
  $("#scope-copy").textContent = `${user.role_label}${scope}. Evaluaciones y seguimiento por local.`;
  loadDashboard();
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.remove("hidden");
  window.setTimeout(() => toast.classList.add("hidden"), 3600);
}

function categoryClass(category) {
  if (category === "Mala") return "bad";
  if (category === "Regular") return "regular";
  if (category === "Buena") return "good";
  return "none";
}

function statusLabel(status) {
  return ({ pendiente: "Plan pendiente", abierto: "Abierto", en_proceso: "En proceso", concluido: "Concluido" })[status] || status;
}

function localDate(dateValue) {
  const match = String(dateValue || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
}

function formatDate(dateValue) {
  const date = localDate(dateValue);
  return date ? date.toLocaleDateString("es-CL") : "Fecha no disponible";
}

function elapsedDays(dateValue) {
  const attended = localDate(dateValue);
  if (!attended) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.floor((today - attended) / 86400000);
}

function divisionFor(item) {
  if (item.Division === "Franquicia" || item.Division === "Sucursal") return item.Division;
  return String(item.CveUnidad || "").toUpperCase().startsWith("F") ? "Franquicia" : "Sucursal";
}

function sourceFor(item) {
  const source = String(item.Fuente || "").trim().toLocaleLowerCase("es-CL");
  if (source === "ms" || source.includes("mystery")) return "MS";
  if (source.includes("qr")) return "OpinionesQR";
  if (source === "google") return "Google";
  return item.Fuente || "";
}

function renderKpis(summary) {
  const split = (franchise, branch) => `Franquicias: ${Number(franchise || 0)} · Sucursales: ${Number(branch || 0)}`;
  const cards = [
    ["Evaluaciones", summary.evaluaciones, split(summary.evaluaciones_franquicias, summary.evaluaciones_sucursales), "#2877a6", "#edf5fa"],
    ["Malas", summary.malas, `${split(summary.malas_franquicias, summary.malas_sucursales)} · Planes pendientes: ${Number(summary.planes_pendientes || 0)}`, "#b42318", "#fff0ee"],
    ["Regulares", summary.regulares, split(summary.regulares_franquicias, summary.regulares_sucursales), "#a35c00", "#fff5df"],
    ["Buenas", summary.buenas, split(summary.buenas_franquicias, summary.buenas_sucursales), "#187342", "#e8f6ed"],
  ];
  $("#kpi-grid").innerHTML = cards.map(([label, value, detail, color, background]) => `
    <article class="kpi-card" style="--kpi-color:${color};--kpi-bg:${background}">
      <div class="kpi-top"><span>${label}</span><span class="kpi-icon">${label === "Evaluaciones" ? "▦" : label === "Malas" ? "!" : label === "Regulares" ? "↗" : "✓"}</span></div>
      <div class="kpi-value">${Number(value || 0)}</div><div class="kpi-split">${detail}</div>
    </article>`).join("");
}

function localMarkup(code, rows) {
  const first = rows[0];
  const localName = first.Unidad || "Local sin maestro";
  const division = first.Division || (String(code).startsWith("F") ? "FRANQUICIA" : "SUCURSAL");
  const supervisor = first.NomSupervisor || "Supervisor sin asignar";
  const evaluations = rows.map((item) => {
    const plan = item.plan;
    const planStatus = plan ? plan.status : "pendiente";
    const buttonLabel = plan ? "Gestionar plan" : "Abrir plan de acción";
    const date = formatDate(item.Fecha);
    const days = elapsedDays(item.Fecha);
    const ageClass = days === null ? "" : days < 0 ? "age-future" : days <= 3 ? "age-green" : days <= 7 ? "age-yellow" : "age-red";
    const elapsed = days === null
      ? ""
      : `<span class="elapsed-days ${ageClass}"><span class="age-dot" aria-hidden="true"></span>${days < 0 ? "Fecha futura" : days === 0 ? "0 d\u00edas \u00b7 Atenci\u00f3n de hoy" : `${days} d\u00eda${days === 1 ? "" : "s"} desde la atenci\u00f3n`}</span>`;
    const score = item.Fuente === "MS"
      ? `Puntaje MS: ${item.PuntajeMS ?? "Sin dato"}`
      : `Rating: ${item.Rating ?? "Sin dato"}`;
    const planText = plan ? `<div class="plan-snippet"><b>Plan:</b> ${escapeHtml(plan.plan_text)}</div>` : "";
    const planActions = plan
      ? `<div class="row-action plan-actions"><button class="button primary small plan-button" data-id="${escapeHtml(item.ID)}">Editar plan</button><button class="button danger small plan-delete-button" data-id="${escapeHtml(item.ID)}">Eliminar</button></div>`
      : `<div class="row-action"><button class="button primary small plan-button" data-id="${escapeHtml(item.ID)}">${buttonLabel}</button></div>`;
    return `
      <article class="evaluation-row">
        <div class="identity-col"><div class="eval-source">${escapeHtml(item.Fuente || "Fuente")}</div>
          <div class="eval-id">${escapeHtml(item.ID)}</div><div class="eval-date">${escapeHtml(date)}</div>${elapsed}</div>
        <div class="comment-col"><div class="comment-text">${escapeHtml(item.Comentario || "Sin comentario asociado")}</div>${planText}</div>
        <div class="rating-col"><span class="category-badge ${categoryClass(item.category)}">${escapeHtml(item.category)}</span>
          <div class="eval-date">${escapeHtml(score)}</div></div>
        <div class="plan-col"><span class="plan-badge ${escapeHtml(planStatus)}">${escapeHtml(statusLabel(planStatus))}</span>
          ${item.plan_required && !plan ? '<div class="required-label">Requiere plan</div>' : ""}</div>
        ${planActions}
      </article>`;
  }).join("");
  return `<section class="local-group">
    <header class="local-heading"><div class="local-heading-main"><span class="local-code">${escapeHtml(code)}</span><div><h3>${escapeHtml(localName)}</h3><small>${escapeHtml(division)} · ${rows.length} evaluación${rows.length === 1 ? "" : "es"}</small></div></div>
    <div class="local-meta"><span>Supervisor: ${escapeHtml(supervisor)}</span><span>${escapeHtml(first.NomComuna || "")}</span></div></header>
    ${evaluations}</section>`;
}

function renderPlanTabs() {
  const counts = {
    todos: state.evaluations.length,
    abierto: state.evaluations.filter((item) => item.plan_status === "abierto").length,
    en_proceso: state.evaluations.filter((item) => item.plan_status === "en_proceso").length,
    concluido: state.evaluations.filter((item) => item.plan_status === "concluido").length,
  };
  document.querySelectorAll(".plan-tab").forEach((button) => {
    const active = button.dataset.planTab === state.activePlanTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.querySelector("span").textContent = counts[button.dataset.planTab] || 0;
  });
}

function renderEvaluations() {
  renderPlanTabs();
  const query = $("#search-input").value.trim().toLocaleLowerCase("es-CL");
  const category = $("#category-filter").value;
  const division = $("#division-filter").value;
  const source = $("#source-filter").value;
  const fromDate = $("#date-from-filter").value;
  const toDate = $("#date-to-filter").value;
  const filtered = state.evaluations.filter((item) => {
    const searchable = [item.CveUnidad, item.Unidad, item.ID, item.Comentario, item.NomSupervisor]
      .join(" ").toLocaleLowerCase("es-CL");
    const date = String(item.Fecha || "").slice(0, 10);
    return (!query || searchable.includes(query))
      && (category === "todas" || item.category === category)
      && (division === "todos" || divisionFor(item) === division)
      && (source === "todas" || sourceFor(item) === source)
      && (!fromDate || (date && date >= fromDate))
      && (!toDate || (date && date <= toDate))
      && (state.activePlanTab === "todos" || item.plan_status === state.activePlanTab);
  });
  $("#evaluation-count").textContent = `${filtered.length} de ${state.evaluations.length} evaluaciones`;
  const localGroups = new Map();
  filtered.forEach((item) => {
    if (!localGroups.has(item.CveUnidad)) localGroups.set(item.CveUnidad, []);
    localGroups.get(item.CveUnidad).push(item);
  });
  let markup = "";
  const jefeRole = ["jefe_comercial_ventas", "jefe_comercial_franquicias"].includes(state.user?.role);
  if (jefeRole) {
    const supervisors = new Map();
    for (const [code, rows] of localGroups) {
      const key = rows[0].NomSupervisor || "Supervisor sin asignar";
      if (!supervisors.has(key)) supervisors.set(key, []);
      supervisors.get(key).push(localMarkup(code, rows));
    }
    markup = [...supervisors.entries()].map(([name, groups]) => `
      <section class="supervisor-group"><div class="supervisor-heading">Supervisor: ${escapeHtml(name)}</div>${groups.join("")}</section>`).join("");
  } else {
    markup = [...localGroups.entries()].map(([code, rows]) => localMarkup(code, rows)).join("");
  }
  $("#evaluations-list").innerHTML = markup;
  $("#empty-state").classList.toggle("hidden", filtered.length > 0);
  document.querySelectorAll(".plan-button").forEach((button) => {
    button.addEventListener("click", () => openPlan(button.dataset.id));
  });
  document.querySelectorAll(".plan-delete-button").forEach((button) => {
    button.addEventListener("click", () => deletePlan(button.dataset.id));
  });
}

async function loadDashboard() {
  $("#source-notice").classList.add("hidden");
  try {
    const result = await api("/api/dashboard");
    state.evaluations = result.evaluations;
    state.summary = result.summary;
    renderKpis(result.summary);
    renderEvaluations();
  } catch (error) {
    $("#source-notice").textContent = `${error.message} Configura las conexiones en el archivo .env.`;
    $("#source-notice").classList.remove("hidden");
    state.evaluations = [];
    state.summary = {};
    renderKpis({});
    renderEvaluations();
  }
}

async function deletePlan(id) {
  const item = state.evaluations.find((row) => row.ID === id);
  if (!item || !window.confirm(`Quieres eliminar el plan de ${item.CveUnidad} - ${item.Unidad || "este local"}? El plan se ocultará y su historial se conservará.`)) return;
  try {
    await api(`/api/attention/${encodeURIComponent(id)}/plan`, { method: "DELETE" });
    showToast("Plan eliminado; su historial se conservó.");
    await loadDashboard();
  } catch (error) {
    showToast(error.message, true);
  }
}

function transactionLabel(type) {
  return ({
    plan_creado: "Plan creado",
    estado_actualizado: "Estado actualizado",
    accion_actualizada: "Acci\u00f3n actualizada",
    plan_y_estado_actualizados: "Acci\u00f3n y estado actualizados",
    registro_confirmado: "Guardado sin cambios",
    migracion_inicial: "Estado inicial migrado",
    plan_eliminado: "Plan eliminado",
    plan_restaurado: "Plan restaurado",
  })[type] || type;
}

function renderPlanHistory(transactions) {
  if (!transactions.length) {
    return '<p class="history-empty">A\u00fan no hay acciones registradas.</p>';
  }
  const entries = transactions.map((transaction) => {
    const timestamp = transaction.performed_at
      ? new Date(transaction.performed_at).toLocaleString("es-CL")
      : "Fecha no disponible";
    const previousStatus = transaction.previous_status
      ? `${statusLabel(transaction.previous_status)} \u2192 `
      : "";
    const stateChange = `${previousStatus}${statusLabel(transaction.new_status)}`;
    const previousText = transaction.previous_text && transaction.previous_text !== transaction.action_text
      ? `<details><summary>Ver acci\u00f3n anterior</summary><p>${escapeHtml(transaction.previous_text)}</p></details>`
      : "";
    return `<li class="history-entry">
      <div class="history-entry-heading"><b>${escapeHtml(transactionLabel(transaction.event_type))}</b><span>${escapeHtml(timestamp)}</span></div>
      <div class="history-entry-meta">Estado: ${escapeHtml(stateChange)} \u00b7 Usuario: ${escapeHtml(transaction.actor_username)}</div>
      <p class="history-action">${escapeHtml(transaction.action_text)}</p>${previousText}
    </li>`;
  }).join("");
  return `<section><h3>Historial de acciones (${transactions.length})</h3><ol class="history-list">${entries}</ol></section>`;
}

async function openPlan(id) {
  const item = state.evaluations.find((row) => row.ID === id);
  if (!item) return;
  state.activeEvaluation = item;
  $("#dialog-title").textContent = item.plan ? "Actualizar plan de acci\u00f3n" : "Abrir plan de acci\u00f3n";
  $("#dialog-evaluation").innerHTML = `<b>${escapeHtml(item.CveUnidad)} \u00b7 ${escapeHtml(item.Unidad || "Local")}</b><br>${escapeHtml(item.Fuente)} | ${escapeHtml(item.Fecha || "")} | ${escapeHtml(item.category)}<br>${escapeHtml(item.Comentario || "Sin comentario")}`;
  $("#plan-text").value = item.plan?.plan_text || "";
  $("#plan-status").value = item.plan?.status || "abierto";
  $("#required-label").classList.toggle("hidden", !item.plan_required);
  $("#plan-error").classList.add("hidden");
  $("#plan-history").innerHTML = '<p class="history-empty">Cargando historial...</p>';
  $("#plan-dialog").showModal();
  try {
    const result = await api(`/api/attention/${encodeURIComponent(id)}/history`);
    $("#plan-history").innerHTML = renderPlanHistory(result.transactions || []);
  } catch (error) {
    $("#plan-history").innerHTML = `<p class="history-error">No se pudo cargar el historial: ${escapeHtml(error.message)}</p>`;
  }
}

async function loadUsers() {
  const data = await api("/api/admin/users");
  $("#new-user-role").innerHTML = data.roles.map((role) => `<option value="${escapeHtml(role.value)}">${escapeHtml(role.label)}</option>`).join("");
  $("#users-list").innerHTML = data.users.map((user) => `
    <div class="user-list-item"><div><b>${escapeHtml(user.full_name)}</b><small>${escapeHtml(user.username)}${user.scope_name ? ` · ${escapeHtml(user.scope_name)}` : ""}</small></div><span class="user-role-tag">${escapeHtml(data.roles.find((role) => role.value === user.role)?.label || user.role)}</span></div>`).join("") || '<p class="muted">Todavía no hay cuentas.</p>';
}

function setView(view) {
  $("#dashboard-view").classList.toggle("hidden", view !== "dashboard");
  $("#users-view").classList.toggle("hidden", view !== "users");
  document.querySelectorAll(".nav-link").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  if (view === "users") loadUsers().catch((error) => showToast(error.message, true));
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorBox = $("#login-error");
  errorBox.classList.add("hidden");
  const form = new FormData(event.currentTarget);
  try {
    const user = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
    });
    showApp(user);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  }
});

$("#logout-button").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (_) { /* Clear local view anyway. */ }
  showLogin();
});
$("#refresh-button").addEventListener("click", loadDashboard);
document.querySelectorAll(".plan-tab").forEach((button) => button.addEventListener("click", () => {
  state.activePlanTab = button.dataset.planTab;
  renderEvaluations();
}));
$("#search-input").addEventListener("input", renderEvaluations);
$("#category-filter").addEventListener("change", renderEvaluations);
$("#division-filter").addEventListener("change", renderEvaluations);
$("#source-filter").addEventListener("change", renderEvaluations);
$("#date-from-filter").addEventListener("change", renderEvaluations);
$("#date-to-filter").addEventListener("change", renderEvaluations);
$("#clear-filters").addEventListener("click", () => {
  $("#category-filter").value = "todas";
  $("#division-filter").value = "todos";
  $("#source-filter").value = "todas";
  $("#date-from-filter").value = "";
  $("#date-to-filter").value = "";
  state.activePlanTab = "todos";
  $("#search-input").value = "";
  renderEvaluations();
});
document.querySelectorAll(".nav-link").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
$("#dialog-close").addEventListener("click", () => $("#plan-dialog").close());
$("#dialog-cancel").addEventListener("click", () => $("#plan-dialog").close());

$("#plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const item = state.activeEvaluation;
  const text = $("#plan-text").value.trim();
  const errorBox = $("#plan-error");
  if (!item) return;
  if (!text) {
    errorBox.textContent = item.plan_required
      ? "Las evaluaciones malas requieren un plan de acción escrito."
      : "Escribe la acción que se realizará.";
    errorBox.classList.remove("hidden");
    return;
  }
  try {
    await api(`/api/attention/${encodeURIComponent(item.ID)}/plan`, {
      method: "PUT",
      body: JSON.stringify({ status: $("#plan-status").value, plan_text: text }),
    });
    $("#plan-dialog").close();
    showToast("Plan de acción guardado.");
    await loadDashboard();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  }
});

$("#new-user-role").addEventListener("change", (event) => {
  const scoped = ["jefe_comercial_ventas", "jefe_comercial_franquicias", "supervisor"].includes(event.target.value);
  $("#scope-field").classList.toggle("hidden", !scoped);
  $("#scope-field").querySelector("input").required = scoped;
});

$("#user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  const errorBox = $("#user-error");
  errorBox.classList.add("hidden");
  try {
    await api("/api/admin/users", { method: "POST", body: JSON.stringify(payload) });
    event.currentTarget.reset();
    $("#scope-field").classList.add("hidden");
    showToast("Usuario creado.");
    await loadUsers();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  }
});

(async function initialize() {
  try { showApp(await api("/api/me")); } catch (_) { showLogin(); }
})();
