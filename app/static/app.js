const state = { user: null, csrf: null, evaluations: [], summary: {}, period: null, users: [], userRoles: [], activeEvaluation: null, activePlanTab: "todos", activeDatasetView: "weekly" };
const $ = (selector) => document.querySelector(selector);
let planHistoryTransactions = [];
let planHistoryExpanded = false;
let lastPlanSnapshot = "";
let tutorialSteps = [];
let tutorialStepIndex = 0;

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
  $("#login-form").reset();
  $("#edit-user-password").value = "";
  $("#login-screen").classList.remove("hidden");
  $("#app-screen").classList.add("hidden");
}

function showApp(user) {
  state.user = user;
  state.csrf = user.csrf_token;
  state.activeDatasetView = "weekly";
  document.querySelectorAll(".dataset-tab").forEach((button) => {
    const active = button.dataset.datasetView === "weekly";
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
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

function availableTutorialSteps() {
  const steps = [
    {
      selector: null,
      title: "Bienvenido a la plataforma",
      description: "Esta guía explica los espacios y controles principales. Puedes cerrarla y volver a iniciarla cuando quieras desde el botón Guía de uso.",
    },
    {
      selector: ".sidebar nav",
      title: "Navegación principal",
      description: "Panel de gestión abre las evaluaciones y sus planes. Los administradores también encuentran aquí la administración de usuarios.",
    },
    {
      selector: "#dataset-tabs",
      title: "Vista semanal e histórica",
      description: "Semanal muestra el último corte disponible. Histórico reúne todas las evaluaciones guardadas, incluidas las que ya no pertenecen a la semana actual.",
    },
    {
      selector: "#period-banner",
      title: "Período y sincronización",
      description: "Este espacio indica exactamente qué fechas estás viendo. Debajo aparece cuándo se sincronizaron por última vez las fuentes de información.",
    },
    {
      selector: "#kpi-grid",
      title: "Indicadores principales",
      description: "Resume la cantidad de evaluaciones malas, regulares y buenas, separando franquicias y sucursales dentro del alcance de tu perfil.",
    },
    {
      selector: ".filters",
      title: "Filtros de evaluaciones",
      description: "Combina clasificación, tipo de local, fuente, fechas y búsqueda. Limpiar filtros devuelve todos los registros de la vista seleccionada.",
    },
    {
      selector: "#plan-tabs",
      title: "Estados de los planes",
      description: "Estos botones separan evaluaciones con planes pendientes, en subsanación o concluidos. El número indica cuántos registros hay en cada estado.",
    },
    {
      selector: ".age-legend",
      title: "Antigüedad de la evaluación",
      description: "El semáforo indica los días transcurridos desde la evaluación: verde hasta 3 días, amarillo entre 4 y 7, y rojo desde 8 días.",
    },
    {
      selector: ".content-card",
      title: state.user?.can_manage_plans ? "Evaluaciones y planes de acción" : "Consulta de evaluaciones y planes",
      description: state.user?.can_manage_plans
        ? "Cada local agrupa sus evaluaciones. Abrir o Editar plan permite registrar el plazo, los compromisos y el estado; cada cambio confirmado queda en el historial."
        : "Cada local agrupa sus evaluaciones. Ver plan permite consultar sus compromisos, estado e historial sin modificar información.",
    },
    {
      selector: "#export-completed-plans",
      title: "Exportar planes concluidos",
      description: "Descarga un Excel con todos los planes concluidos que puedes ver, aunque pertenezcan a semanas anteriores. Incluye fechas, responsables y tiempos de gestión.",
    },
  ];
  if (state.user?.role === "admin") {
    steps.push({
      selector: "#users-nav",
      title: "Usuarios y permisos",
      description: "Como administrador puedes crear, importar, editar y eliminar cuentas, además de asignar el rol y alcance de cada persona.",
    });
  }
  steps.push({
    selector: ".user-block",
    title: "Tu sesión",
    description: "Aquí puedes confirmar el usuario y rol activos. Cerrar sesión termina el acceso de forma segura en este navegador.",
  });
  return steps.filter((step) => !step.selector || document.querySelector(step.selector));
}

function clearTutorialHighlight() {
  document.querySelectorAll(".tutorial-highlight").forEach((element) => element.classList.remove("tutorial-highlight"));
}

function renderTutorialStep() {
  clearTutorialHighlight();
  const step = tutorialSteps[tutorialStepIndex];
  if (!step) return;
  const target = step.selector ? document.querySelector(step.selector) : null;
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    target.classList.add("tutorial-highlight");
  }
  $("#tutorial-step-count").textContent = `Paso ${tutorialStepIndex + 1} de ${tutorialSteps.length}`;
  $("#tutorial-progress-bar").style.width = `${((tutorialStepIndex + 1) / tutorialSteps.length) * 100}%`;
  $("#tutorial-title").textContent = step.title;
  $("#tutorial-description").textContent = step.description;
  $("#tutorial-previous").disabled = tutorialStepIndex === 0;
  $("#tutorial-next").textContent = tutorialStepIndex === tutorialSteps.length - 1 ? "Finalizar" : "Siguiente";
}

function closeTutorial() {
  clearTutorialHighlight();
  $("#tutorial-overlay").classList.add("hidden");
  $("#tutorial-overlay").setAttribute("aria-hidden", "true");
}

function startTutorial() {
  setView("dashboard");
  tutorialSteps = availableTutorialSteps();
  tutorialStepIndex = 0;
  $("#tutorial-overlay").classList.remove("hidden");
  $("#tutorial-overlay").setAttribute("aria-hidden", "false");
  renderTutorialStep();
}

async function downloadCompletedPlans() {
  const button = $("#export-completed-plans");
  const originalLabel = button.innerHTML;
  button.disabled = true;
  button.textContent = "Preparando Excel…";
  try {
    const response = await fetch("/api/exports/completed-plans", { credentials: "same-origin" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      if (response.status === 401) showLogin();
      throw new Error(body.detail || `No fue posible exportar (error ${response.status}).`);
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || "Planes_Accion_Concluidos.xlsx";
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast("Excel de planes concluidos generado correctamente.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.innerHTML = originalLabel;
  }
}

function categoryClass(category) {
  if (category === "Mala") return "bad";
  if (category === "Regular") return "regular";
  if (category === "Buena") return "good";
  return "none";
}

function statusLabel(status) {
  return ({ pendiente: "Pendiente", en_subsanacion: "En subsanación", concluido: "Concluido" })[status] || status;
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

function renderKpiSet(summary, targetSelector) {
  const split = (franchise, branch) => `Franquicias: ${Number(franchise || 0)} · Sucursales: ${Number(branch || 0)}`;
  const cards = [
    ["Evaluaciones", summary.evaluaciones, split(summary.evaluaciones_franquicias, summary.evaluaciones_sucursales), "#2877a6", "#edf5fa"],
    ["Malas", summary.malas, `${split(summary.malas_franquicias, summary.malas_sucursales)} · Planes pendientes: ${Number(summary.planes_pendientes || 0)}`, "#b42318", "#fff0ee"],
    ["Regulares", summary.regulares, split(summary.regulares_franquicias, summary.regulares_sucursales), "#a35c00", "#fff5df"],
    ["Buenas", summary.buenas, split(summary.buenas_franquicias, summary.buenas_sucursales), "#187342", "#e8f6ed"],
  ];
  $(targetSelector).innerHTML = cards.map(([label, value, detail, color, background]) => `
    <article class="kpi-card" style="--kpi-color:${color};--kpi-bg:${background}">
      <div class="kpi-top"><span>${label}</span><span class="kpi-icon">${label.includes("Evaluaciones") ? "▦" : label.includes("Malas") ? "!" : label.includes("Regulares") ? "↗" : "✓"}</span></div>
      <div class="kpi-value">${Number(value || 0)}</div><div class="kpi-split">${detail}</div>
    </article>`).join("");
}

function renderPeriod(period) {
  state.period = period || null;
  $("#period-banner").textContent = period?.label
    ? `Período mostrado: ${period.label}`
    : "Período mostrado: sin información disponible";
}

function renderSyncStatus(lastSync) {
  if (!lastSync) {
    $("#sync-status").textContent = "Aún no se ha ejecutado la primera sincronización.";
    return;
  }
  const completed = lastSync.completed_at
    ? new Date(lastSync.completed_at).toLocaleString("es-CL", { timeZone: "America/Santiago" })
    : "en curso";
  const status = lastSync.status === "success" ? "Correcta" : lastSync.status === "failed" ? "Fallida" : "En curso";
  $("#sync-status").textContent = `Última sincronización: ${completed} · Estado: ${status} · Registros consultados: ${Number(lastSync.source_rows || 0)}`;
}

function activeFilterValue(selector, fallback) {
  return $(`${selector} .filter-button.active`)?.dataset.value || fallback;
}

function resetFilterButtons() {
  document.querySelectorAll(".filter-buttons").forEach((group) => {
    group.querySelectorAll(".filter-button").forEach((button, index) => {
      const active = index === 0;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  });
}

function localMarkup(code, rows) {
  const first = rows[0];
  const localName = first.Unidad || "Local sin maestro";
  const division = first.Division || (String(code).startsWith("F") ? "FRANQUICIA" : "SUCURSAL");
  const supervisor = first.NomSupervisor || "Supervisor sin asignar";
  const evaluations = rows.map((item) => {
    const plan = item.plan;
    const planStatus = plan ? plan.status : "pendiente";
    const canManagePlans = Boolean(state.user?.can_manage_plans);
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
    const planActions = canManagePlans
      ? (plan
        ? `<div class="row-action plan-actions"><button class="button primary small plan-button" data-id="${escapeHtml(item.ID)}">Editar plan</button><button class="button danger small plan-delete-button" data-id="${escapeHtml(item.ID)}">Eliminar</button></div>`
        : `<div class="row-action"><button class="button primary small plan-button" data-id="${escapeHtml(item.ID)}">${buttonLabel}</button></div>`)
      : `<div class="row-action"><button class="button outline small plan-button" data-id="${escapeHtml(item.ID)}">${plan ? "Ver plan" : "Ver detalle"}</button></div>`;
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
    pendiente: state.evaluations.filter((item) => item.plan_status === "pendiente").length,
    en_subsanacion: state.evaluations.filter((item) => item.plan_status === "en_subsanacion").length,
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
  const category = activeFilterValue("#category-filter", "todas");
  const division = activeFilterValue("#division-filter", "todos");
  const source = activeFilterValue("#source-filter", "todas");
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
    const result = await api(`/api/dashboard?view=${encodeURIComponent(state.activeDatasetView)}`);
    state.evaluations = result.evaluations;
    state.summary = result.summary;
    renderPeriod(result.period);
    renderSyncStatus(result.last_sync);
    renderKpiSet(result.summary || {}, "#kpi-grid");
    renderEvaluations();
  } catch (error) {
    $("#source-notice").textContent = error.message;
    $("#source-notice").classList.remove("hidden");
    state.evaluations = [];
    state.summary = {};
    renderPeriod(null);
    renderSyncStatus(null);
    renderKpiSet({}, "#kpi-grid");
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
    accion_actualizada: "Compromisos y acciones actualizados",
    fecha_plazo_actualizada: "Fecha de plazo actualizada",
    multiples_campos_actualizados: "Varios campos actualizados",
    plan_y_estado_actualizados: "Acción y estado actualizados",
    registro_confirmado: "Guardado sin cambios",
    migracion_inicial: "Estado inicial migrado",
    plan_eliminado: "Plan eliminado",
    plan_restaurado: "Plan restaurado",
  })[type] || type;
}

function renderPlanHistory(transactions) {
  if (!transactions.length) {
    return '<section><h3>Historial de acciones</h3><p class="history-empty">Aún no hay acciones registradas.</p></section>';
  }
  const visibleTransactions = planHistoryExpanded ? transactions : transactions.slice(0, 3);
  const entries = visibleTransactions.map((transaction) => {
    const timestamp = transaction.performed_at
      ? new Date(transaction.performed_at).toLocaleString("es-CL")
      : "Fecha no disponible";
    const previousStatus = transaction.previous_status
      ? `${statusLabel(transaction.previous_status)} → `
      : "";
    const stateChange = `${previousStatus}${statusLabel(transaction.new_status)}`;
    const previousText = transaction.previous_text && transaction.previous_text !== transaction.action_text
      ? `<details><summary>Ver compromisos anteriores</summary><p>${escapeHtml(transaction.previous_text)}</p></details>`
      : "";
    const dueDateChange = transaction.previous_due_date !== transaction.new_due_date
      ? `<div class="history-entry-meta">Plazo: ${escapeHtml(transaction.previous_due_date || "Sin fecha")} → ${escapeHtml(transaction.new_due_date || "Sin fecha")}</div>`
      : "";
    const actionText = transaction.action_text
      ? `<p class="history-action">${escapeHtml(transaction.action_text)}</p>`
      : '<p class="history-action muted">Sin compromisos escritos.</p>';
    return `<li class="history-entry">
      <div class="history-entry-heading"><b>${escapeHtml(transactionLabel(transaction.event_type))}</b><span>${escapeHtml(timestamp)}</span></div>
      <div class="history-entry-meta">Estado: ${escapeHtml(stateChange)} · Usuario: ${escapeHtml(transaction.actor_username)}</div>
      ${dueDateChange}${actionText}${previousText}
    </li>`;
  }).join("");
  const moreButton = transactions.length > 3
    ? `<button type="button" id="history-more-button" class="history-more">${planHistoryExpanded ? "Ver menos" : "Ver más (" + (transactions.length - 3) + ")"}</button>`
    : "";
  return `<section><h3>Historial de acciones (${transactions.length})</h3><ol class="history-list">${entries}</ol>${moreButton}</section>`;
}

function updatePlanHistory(transactions) {
  planHistoryTransactions = transactions;
  $("#plan-history").innerHTML = renderPlanHistory(transactions);
  $("#history-more-button")?.addEventListener("click", () => {
    planHistoryExpanded = !planHistoryExpanded;
    updatePlanHistory(planHistoryTransactions);
  });
}

async function refreshPlanHistory() {
  if (!state.activeEvaluation) return;
  const result = await api(`/api/attention/${encodeURIComponent(state.activeEvaluation.ID)}/history`);
  updatePlanHistory(result.transactions || []);
}

function currentPlanPayload(completionConfirmed = false) {
  return {
    status: $("#plan-status").value,
    plan_text: $("#plan-text").value,
    due_date: $("#plan-due-date").value || null,
    completion_confirmed: completionConfirmed,
  };
}

function planSnapshot(payload = currentPlanPayload()) {
  return JSON.stringify({
    status: payload.status,
    plan_text: payload.plan_text,
    due_date: payload.due_date,
  });
}

function setPlanEditStatus(message, className = "") {
  const element = $("#plan-edit-status");
  element.textContent = message;
  element.className = `edit-status ${className}`.trim();
}

function markPlanDirty() {
  if (!state.user?.can_manage_plans) return false;
  const dirty = planSnapshot() !== lastPlanSnapshot;
  setPlanEditStatus(dirty ? "Hay cambios sin guardar." : "Sin cambios pendientes.", dirty ? "pending" : "");
  return dirty;
}

function setPlanButtonsDisabled(disabled) {
  $("#plan-save-button").disabled = disabled;
  $("#plan-cancel-button").disabled = disabled;
  $("#dialog-close").disabled = disabled;
}

async function savePlan(completionConfirmed = false) {
  if (!state.activeEvaluation || !state.user?.can_manage_plans) return false;
  const payload = currentPlanPayload(completionConfirmed);
  const snapshot = planSnapshot(payload);
  if (snapshot === lastPlanSnapshot && !completionConfirmed) return true;
  setPlanEditStatus("Guardando el cambio completo…", "saving");
  setPlanButtonsDisabled(true);
  $("#plan-error").classList.add("hidden");
  try {
    const result = await api(`/api/attention/${encodeURIComponent(state.activeEvaluation.ID)}/plan`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    state.activeEvaluation.plan = result.plan;
    state.activeEvaluation.plan_status = result.plan.status;
    lastPlanSnapshot = snapshot;
    setPlanEditStatus(`Cambio guardado a las ${new Date().toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" })}.`, "saved");
    renderPlanTabs();
    await refreshPlanHistory();
    return true;
  } catch (error) {
    $("#plan-error").textContent = error.message;
    $("#plan-error").classList.remove("hidden");
    setPlanEditStatus("No se pudo guardar el cambio.", "error");
    return false;
  } finally {
    setPlanButtonsDisabled(false);
  }
}

async function openPlan(id) {
  const item = state.evaluations.find((row) => row.ID === id);
  if (!item) return;
  state.activeEvaluation = item;
  const readOnly = state.user?.can_manage_plans === false;
  planHistoryExpanded = false;
  $("#dialog-title").textContent = readOnly ? "Detalle de la evaluación y plan" : "Gestión del plan de acción";
  $("#plan-dialog-subtitle").textContent = readOnly
    ? "Consulta la evaluación, el plan de acción y todo su historial en modo de solo lectura."
    : "Revisa los datos, completa el seguimiento y presiona Listo para registrar el cambio.";
  $("#plan-unit-code").value = item.CveUnidad || "";
  $("#plan-unit-name").value = item.Unidad || "Local sin nombre";
  $("#plan-supervisor").value = item.NomSupervisor || "Supervisor sin asignar";
  $("#plan-evaluation-date").value = formatDate(item.Fecha);
  $("#plan-classification-text").textContent = item.category || "Sin clasificación";
  $("#plan-classification").className = `crm-classification ${categoryClass(item.category)}`;
  $("#plan-original-comment").textContent = item.Comentario || "Sin comentario asociado.";
  $("#plan-text").value = item.plan?.plan_text || "";
  $("#plan-due-date").value = item.plan?.due_date || "";
  $("#plan-status").value = readOnly && !item.plan ? "sin_plan" : (item.plan?.status || "pendiente");
  $("#plan-text").disabled = readOnly;
  $("#plan-due-date").disabled = readOnly;
  $("#plan-status").disabled = readOnly;
  $("#plan-save-button").classList.toggle("hidden", readOnly);
  $("#plan-cancel-button").textContent = readOnly ? "Cerrar" : "Cancelar";
  lastPlanSnapshot = planSnapshot();
  setPlanEditStatus(
    readOnly
      ? (item.plan ? "Modo solo lectura." : "Modo solo lectura · Esta evaluación no tiene un plan registrado.")
      : "Sin cambios pendientes."
  );
  $("#plan-error").classList.add("hidden");
  $("#plan-completion-confirmation").classList.add("hidden");
  $("#plan-history").innerHTML = '<p class="history-empty">Cargando historial...</p>';
  $("#plan-dialog").showModal();
  try {
    await refreshPlanHistory();
  } catch (error) {
    $("#plan-history").innerHTML = `<p class="history-error">No se pudo cargar el historial: ${escapeHtml(error.message)}</p>`;
  }
}

async function loadUsers() {
  const data = await api("/api/admin/users");
  state.users = data.users;
  state.userRoles = data.roles;
  $("#new-user-role").innerHTML = (data.assignable_roles || data.roles).map((role) => `<option value="${escapeHtml(role.value)}">${escapeHtml(role.label)}</option>`).join("");
  $("#users-list").innerHTML = data.users.map((user) => `
    <div class="user-list-item"><div><b>${escapeHtml(user.full_name)}</b><small>${escapeHtml(user.username)}${user.scope_name ? ` · ${escapeHtml(user.scope_name)}` : ""}</small></div><div class="user-actions"><span class="user-role-tag">${escapeHtml(data.roles.find((role) => role.value === user.role)?.label || user.role)}</span><button class="button outline small user-edit-button" data-username="${escapeHtml(user.username)}">Editar</button>${user.username.toLocaleLowerCase("es-CL") === "admin" ? "" : `<button class="button danger small user-delete-button" data-username="${escapeHtml(user.username)}">Eliminar</button>`}</div></div>`).join("") || '<p class="muted">Todavía no hay cuentas.</p>';
  document.querySelectorAll(".user-edit-button").forEach((button) => button.addEventListener("click", () => openUserDialog(button.dataset.username)));
  document.querySelectorAll(".user-delete-button").forEach((button) => button.addEventListener("click", () => removeUser(button.dataset.username)));
}

function scopeLabelFor(role) {
  return {
    jefe_comercial_ventas: "Jefe comercial asignado",
    jefe_comercial_franquicias: "Jefe comercial asignado",
    supervisor_ventas: "Nombre exacto en NomSupervisor",
    supervisor_franquicias: "Nombre exacto en NomSupervisor",
    gerencia: "Gerencia a la que pertenece",
  }[role];
}

function updateEditScopeField() {
  const label = scopeLabelFor($("#edit-user-role").value);
  $("#edit-scope-label").textContent = label || "Alcance asignado";
  $("#edit-scope-field").classList.toggle("hidden", !label);
  $("#edit-user-scope").required = Boolean(label);
  if (!label) $("#edit-user-scope").value = "";
}

function openUserDialog(username) {
  const target = state.users.find((item) => item.username.toLocaleLowerCase("es-CL") === String(username).toLocaleLowerCase("es-CL"));
  if (!target) return;
  const fixedAdmin = target.username.toLocaleLowerCase("es-CL") === "admin";
  const selectableRoles = fixedAdmin ? state.userRoles : state.userRoles.filter((role) => role.value !== "admin");
  $("#edit-user-username").value = target.username;
  $("#edit-user-full-name").value = target.full_name;
  $("#edit-user-role").innerHTML = selectableRoles.map((role) => `<option value="${escapeHtml(role.value)}">${escapeHtml(role.label)}</option>`).join("");
  $("#edit-user-role").value = target.role;
  $("#edit-user-role").disabled = fixedAdmin;
  $("#edit-user-scope").value = target.scope_name || "";
  $("#edit-user-password").value = "";
  $("#edit-user-password").type = "password";
  $("#edit-user-password").disabled = false;
  $("#edit-password-help").textContent = "Déjala vacía para conservar la actual. Si cambias tu propia cuenta, deberás iniciar sesión de nuevo.";
  document.querySelector('[data-target="edit-user-password"]').textContent = "Ver";
  $("#edit-user-error").classList.add("hidden");
  updateEditScopeField();
  $("#user-dialog").showModal();
}

async function removeUser(username) {
  const target = state.users.find((item) => item.username.toLocaleLowerCase("es-CL") === String(username).toLocaleLowerCase("es-CL"));
  if (!target || target.username.toLocaleLowerCase("es-CL") === "admin") return;
  if (!window.confirm(`¿Eliminar al usuario ${target.username}? Esta acción no se puede deshacer.`)) return;
  try {
    await api(`/api/admin/users/${encodeURIComponent(target.username)}`, { method: "DELETE", body: "{}" });
    showToast("Usuario eliminado.");
    await loadUsers();
  } catch (error) {
    showToast(error.message, true);
  }
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
    event.currentTarget.reset();
    showApp(user);
  } catch (error) {
    $("#login-password").value = "";
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  }
});

$("#logout-button").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (_) { /* Clear local view anyway. */ }
  showLogin();
});
$("#tutorial-button").addEventListener("click", startTutorial);
$("#tutorial-close").addEventListener("click", closeTutorial);
$("#tutorial-previous").addEventListener("click", () => {
  if (tutorialStepIndex > 0) {
    tutorialStepIndex -= 1;
    renderTutorialStep();
  }
});
$("#tutorial-next").addEventListener("click", () => {
  if (tutorialStepIndex >= tutorialSteps.length - 1) {
    closeTutorial();
    return;
  }
  tutorialStepIndex += 1;
  renderTutorialStep();
});
$("#export-completed-plans").addEventListener("click", downloadCompletedPlans);
document.addEventListener("keydown", (event) => {
  if ($("#tutorial-overlay").classList.contains("hidden")) return;
  if (event.key === "Escape") closeTutorial();
  if (event.key === "ArrowLeft" && tutorialStepIndex > 0) {
    tutorialStepIndex -= 1;
    renderTutorialStep();
  }
  if (event.key === "ArrowRight") {
    if (tutorialStepIndex >= tutorialSteps.length - 1) closeTutorial();
    else {
      tutorialStepIndex += 1;
      renderTutorialStep();
    }
  }
});
document.querySelectorAll(".dataset-tab").forEach((button) => button.addEventListener("click", async () => {
  state.activeDatasetView = button.dataset.datasetView;
  state.activePlanTab = "todos";
  document.querySelectorAll(".dataset-tab").forEach((item) => {
    const active = item === button;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  await loadDashboard();
}));
document.querySelectorAll(".plan-tab").forEach((button) => button.addEventListener("click", () => {
  state.activePlanTab = button.dataset.planTab;
  renderEvaluations();
}));
$("#search-input").addEventListener("input", renderEvaluations);
document.querySelectorAll(".filter-buttons .filter-button").forEach((button) => button.addEventListener("click", () => {
  const group = button.closest(".filter-buttons");
  group.querySelectorAll(".filter-button").forEach((item) => {
    const active = item === button;
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", String(active));
  });
  renderEvaluations();
}));
$("#date-from-filter").addEventListener("change", renderEvaluations);
$("#date-to-filter").addEventListener("change", renderEvaluations);
$("#clear-filters").addEventListener("click", () => {
  resetFilterButtons();
  $("#date-from-filter").value = "";
  $("#date-to-filter").value = "";
  state.activePlanTab = "todos";
  $("#search-input").value = "";
  renderEvaluations();
});
document.querySelectorAll(".nav-link").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));

async function discardAndClosePlan() {
  $("#plan-completion-confirmation").classList.add("hidden");
  $("#plan-dialog").close();
  state.activeEvaluation = null;
  await loadDashboard();
}

async function handlePlanReady() {
  if (!state.user?.can_manage_plans) {
    await discardAndClosePlan();
    return;
  }
  const previousStatus = JSON.parse(lastPlanSnapshot || '{"status":"pendiente"}').status;
  if ($("#plan-status").value === "concluido" && previousStatus !== "concluido") {
    $("#plan-completion-confirmation").classList.remove("hidden");
    return;
  }
  const saved = await savePlan(false);
  if (saved) {
    showToast("Plan de acción guardado.");
    await discardAndClosePlan();
  }
}

$("#dialog-close").addEventListener("click", discardAndClosePlan);
$("#plan-cancel-button").addEventListener("click", discardAndClosePlan);
$("#plan-save-button").addEventListener("click", handlePlanReady);
$("#plan-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  if (!$("#plan-completion-confirmation").classList.contains("hidden")) {
    $("#plan-completion-confirmation").classList.add("hidden");
    return;
  }
  if (!$("#plan-save-button").disabled) discardAndClosePlan();
});
$("#plan-form").addEventListener("submit", (event) => {
  event.preventDefault();
  handlePlanReady();
});
$("#plan-text").addEventListener("input", markPlanDirty);
$("#plan-due-date").addEventListener("change", markPlanDirty);
$("#plan-status").addEventListener("change", markPlanDirty);
$("#completion-back").addEventListener("click", () => {
  $("#plan-completion-confirmation").classList.add("hidden");
});
$("#completion-confirm").addEventListener("click", async () => {
  $("#plan-completion-confirmation").classList.add("hidden");
  const saved = await savePlan(true);
  if (saved) {
    showToast("Plan concluido y registrado en el historial.");
    await discardAndClosePlan();
  }
});

$("#new-user-role").addEventListener("change", (event) => {
  const scopeLabels = {
    jefe_comercial_ventas: "Jefe comercial asignado",
    jefe_comercial_franquicias: "Jefe comercial asignado",
    supervisor_ventas: "Nombre exacto en NomSupervisor",
    supervisor_franquicias: "Nombre exacto en NomSupervisor",
    gerencia: "Gerencia a la que pertenece",
  };
  const scoped = Object.hasOwn(scopeLabels, event.target.value);
  $("#scope-label").textContent = scopeLabels[event.target.value] || "Alcance asignado";
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

$("#user-import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("#user-import-file").files[0];
  const resultBox = $("#user-import-result");
  resultBox.classList.add("hidden");
  if (!file) return;
  try {
    const result = await api("/api/admin/users/import", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, content: await file.text() }),
    });
    const details = (result.details || []).slice(0, 5)
      .map((item) => `Línea ${item.line}: ${item.reason}`).join(" · ");
    resultBox.textContent = `${result.created} usuario(s) creado(s) y ${result.skipped} omitido(s).${details ? ` ${details}` : ""}`;
    resultBox.className = "notice success";
    event.currentTarget.reset();
    await loadUsers();
  } catch (error) {
    resultBox.textContent = error.message;
    resultBox.className = "notice error";
  }
});

document.querySelectorAll(".password-toggle").forEach((button) => button.addEventListener("click", () => {
  const input = $(`#${button.dataset.target}`);
  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  button.textContent = visible ? "Ver" : "Ocultar";
}));

$("#edit-user-role").addEventListener("change", updateEditScopeField);
$("#user-dialog").addEventListener("close", () => { $("#edit-user-password").value = ""; });
$("#user-dialog-close").addEventListener("click", () => $("#user-dialog").close());
$("#user-dialog-cancel").addEventListener("click", () => $("#user-dialog").close());
$("#user-edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = $("#edit-user-username").value;
  const errorBox = $("#edit-user-error");
  const payload = {
    full_name: $("#edit-user-full-name").value.trim(),
    role: $("#edit-user-role").value,
    scope_name: $("#edit-user-scope").value.trim(),
    password: $("#edit-user-password").disabled ? null : ($("#edit-user-password").value || null),
  };
  errorBox.classList.add("hidden");
  try {
    await api(`/api/admin/users/${encodeURIComponent(username)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    $("#edit-user-password").value = "";
    $("#user-dialog").close();
    showToast("Usuario actualizado.");
    await loadUsers();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  }
});

(async function initialize() {
  try { showApp(await api("/api/me")); } catch (_) { showLogin(); }
})();
