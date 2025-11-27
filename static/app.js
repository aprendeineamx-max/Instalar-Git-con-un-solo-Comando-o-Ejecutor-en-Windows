const api = {
  apps: "/api/apps",
  add: "/api/apps",
  check: "/api/check-installations",
  version: (id) => `/api/version/${id}`,
  installStream: (id) => `/api/install/${id}/stream?ts=${Date.now()}`,
  open: (id) => `/api/open/${id}`,
};

const toastEl = document.getElementById("toast");
const appCount = document.getElementById("appCount");
const appsGrid = document.getElementById("appsGrid");
const searchInput = document.getElementById("search");
const categoryFilter = document.getElementById("categoryFilter");
const addForm = document.getElementById("addForm");
const logList = document.getElementById("logList");
const navLinks = document.querySelectorAll(".nav-link");

let apps = [];
let logs = [];
const statusMap = new Map(); // id -> {state, progress}
const liveLogs = new Map(); // id -> text
const versionsMap = new Map(); // id -> {current_version, latest_version, update_available}
const openingSet = new Set(); // ids being opened

function showToast(message) {
  toastEl.textContent = message;
  toastEl.classList.add("show");
  setTimeout(() => toastEl.classList.remove("show"), 2500);
}

async function fetchApps() {
  const res = await fetch(api.apps);
  apps = await res.json();
  apps.forEach((app) => {
    if (app.installed) {
      statusMap.set(app.id, { state: "done", progress: 100 });
    }
  });
  updateCategories();
  appCount.textContent = apps.length;
  renderCards();
  // Cargar versiones en background para no bloquear UI
  fetchVersions().then(renderCards).catch(() => {});
}

async function refreshAll() {
  await fetchApps();
  await checkInstallations();
}

function renderCards() {
  const query = (searchInput.value || "").toLowerCase();
  const category = categoryFilter.value || "";
  const filtered = apps.filter(
    (a) =>
      (a.name.toLowerCase().includes(query) ||
        (a.category || "").toLowerCase().includes(query)) &&
      (category ? (a.category || "").toLowerCase() === category : true)
  );

  appsGrid.innerHTML = "";
  if (!filtered.length) {
    appsGrid.innerHTML =
      '<p class="muted" style="grid-column: 1/-1;">Sin resultados</p>';
    return;
  }

  filtered.forEach((app) => {
    const defaultState = app.installed
      ? { state: "done", progress: 100 }
      : { state: "idle", progress: 0 };
    const state = statusMap.get(app.id) || defaultState;
    const versions = versionsMap.get(app.id) || {
      current_version: "desconocida",
      latest_version: "desconocida",
      update_available: false,
    };
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="card-top">
        <div class="pill">${app.category || "General"}</div>
        ${
          state.state === "done"
            ? `<div class="status-badge success">Instalado</div>`
            : state.state === "error"
            ? `<div class="status-badge danger">Fallo</div>`
            : ""
        }
      </div>
      <div class="title-row">
        ${
          isImageIcon(app.icon)
            ? `<div class="app-icon img"><img src="${app.icon}" alt="${app.name}" loading="lazy"/></div>`
            : `<div class="app-icon">${app.icon || "⬢"}</div>`
        }
        <h3>${app.name}</h3>
      </div>
      <p>${app.description || "Sin descripcion"}</p>
      <div class="versions">
        <span>Instalada: <strong>${versions.current_version}</strong></span>
        <span>Disponible: <strong>${versions.latest_version}</strong></span>
      </div>
      <div class="links">
        ${
          app.homepage
            ? `<a href="${app.homepage}" target="_blank" rel="noreferrer">Sitio oficial</a>`
            : ""
        }
        ${
          app.download
            ? `<a href="${app.download}" target="_blank" rel="noreferrer">Descargar instalador</a>`
            : ""
        }
      </div>
      <div class="command">${app.command}</div>
      <div class="actions">
        <button class="btn primary" data-install="${app.id}" ${
          state.state === "installing" ? "disabled" : ""
        }>
          ${
            state.state === "installing"
              ? "Instalando..."
              : state.state === "done"
              ? "Reinstalar"
              : "Instalar"
          }
        </button>
        ${
          state.state === "done"
            ? `<button class="btn ghost" data-open="${app.id}" ${
                openingSet.has(app.id) ? "disabled" : ""
              }>${openingSet.has(app.id) ? "Abriendo..." : "Abrir"}</button>`
            : ""
        }
        ${
          versions.update_available
            ? `<button class="btn ghost" data-update="${app.id}">Actualizar</button>`
            : ""
        }
      </div>
      ${
        state.state === "installing"
          ? `<div class="progress">
              <div class="progress-bar" style="width:${state.progress}%"></div>
              <span class="progress-text">${Math.floor(state.progress)}%</span>
            </div>`
          : state.state === "done"
          ? `<div class="progress complete">
              <div class="progress-bar" style="width:100%"></div>
              <span class="progress-text">100% Instalado</span>
            </div>`
          : ""
      }
    `;
    appsGrid.appendChild(card);

    card.querySelector("[data-install]").addEventListener("click", () =>
      installApp(app)
    );
    const openBtn = card.querySelector("[data-open]");
    if (openBtn) {
      openBtn.addEventListener("click", () => openApp(app));
    }
    const updateBtn = card.querySelector("[data-update]");
    if (updateBtn) {
      updateBtn.addEventListener("click", () => installApp(app));
    }
  });
}

function appendLiveLog(appId, line) {
  const previous = liveLogs.get(appId) || "";
  const next = previous ? `${previous}\n${line}` : line;
  // Client-side cap to avoid huge DOM content if server cap changes.
  liveLogs.set(appId, next.slice(-12000));
}

function installApp(app) {
  if (statusMap.get(app.id)?.state === "installing") return;
  setStatus(app.id, "installing", 1);
  liveLogs.set(app.id, "");
  showToast(`Ejecutando ${app.name}...`);

  const es = new EventSource(api.installStream(app.id));

  es.addEventListener("progress", (evt) => {
    const data = JSON.parse(evt.data || "{}");
    if (typeof data.progress === "number") {
      setStatus(app.id, "installing", data.progress);
    }
  });

  es.addEventListener("log", (evt) => {
    const data = JSON.parse(evt.data || "{}");
    if (data.line) appendLiveLog(app.id, data.line);
  });

  es.addEventListener("truncate", (evt) => {
    const data = JSON.parse(evt.data || "{}");
    appendLiveLog(app.id, `--- salida truncada a ${data.limit} chars ---`);
  });

  es.addEventListener("done", (evt) => {
    const data = JSON.parse(evt.data || "{}");
    const status = data.status || "error";
    const output =
      data.output ||
      liveLogs.get(app.id) ||
      "Sin salida de la instalacion (modo silencioso).";
    logs.unshift({
      id: Date.now(),
      app: app.name,
      status,
      command: app.command,
      output,
      exit: data.exit_code,
    });
    renderLogs();
    setStatus(
      app.id,
      status === "ok" ? "done" : "error",
      status === "ok" ? 100 : 0
    );
    showToast(`${status === "ok" ? "Listo" : "Fallo"} ${app.name}`);
    es.close();
    fetchApps(); // refresh installed flag persisted
    liveLogs.delete(app.id);
  });

  es.addEventListener("start", () => {
    setStatus(app.id, "installing", 1);
  });

  es.onerror = () => {
    showToast("Error recibiendo progreso");
    setStatus(app.id, "error", 0);
    es.close();
  };
}

function renderLogs() {
  logList.innerHTML = "";
  if (!logs.length) {
    logList.innerHTML =
      '<p class="muted">Sin ejecuciones aun. Instala algo para ver el historial.</p>';
    return;
  }
  logs.slice(0, 6).forEach((log) => {
    const item = document.createElement("div");
    item.className = "log-item";
    item.innerHTML = `
      <header>
        <span class="status-chip ${log.status}">${log.status.toUpperCase()}</span>
        <strong>${log.app}</strong>
        <span class="muted">Exit ${log.exit}</span>
      </header>
      <div class="command">${log.command}</div>
      <pre class="muted" style="white-space: pre-wrap;">${(log.output || "").trim() || "Sin salida"}</pre>
    `;
    logList.appendChild(item);
  });
}

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const formData = new FormData(addForm);
  const payload = Object.fromEntries(formData.entries());
  if (!payload.name || !payload.command) {
    showToast("Completa nombre y comando");
    return;
  }
  const res = await fetch(api.add, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    showToast("App agregada");
    addForm.reset();
    fetchApps();
  } else {
    const err = await res.json();
    showToast(err.error || "Error al guardar");
  }
});

navLinks.forEach((link) => {
  link.addEventListener("click", (e) => {
    navLinks.forEach((l) => l.classList.remove("active"));
    e.currentTarget.classList.add("active");
  });
});

searchInput.addEventListener("input", renderCards);
categoryFilter.addEventListener("change", renderCards);
document.getElementById("refresh").addEventListener("click", refreshAll);
document.getElementById("scrollNew").addEventListener("click", () => {
  document.getElementById("nuevo").scrollIntoView({ behavior: "smooth" });
});

refreshAll();

function setStatus(id, state, progress) {
  statusMap.set(id, { state, progress });
  renderCards();
}

async function checkInstallations() {
  try {
    const res = await fetch(api.check);
    const data = await res.json();
    data.forEach((entry) => {
      const installed = !!entry.installed;
      apps = apps.map((app) =>
        app.id === entry.id ? { ...app, installed } : app
      );
      statusMap.set(entry.id, {
        state: installed ? "done" : "idle",
        progress: installed ? 100 : 0,
      });
    });
    renderCards();
    fetchApps(); // recarga catálogo con installed persistido
    showToast("Catalogo sincronizado con apps instaladas");
  } catch (err) {
    console.error(err);
    showToast("No se pudo verificar instalaciones");
  }
}

function updateCategories() {
  const existing = new Set();
  const sorted = [...new Set(apps.map((a) => (a.category || "").trim()))]
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b));
  // preserve "Todas" option
  categoryFilter.innerHTML = `<option value="">Todas las categorías</option>`;
  sorted.forEach((cat) => {
    const option = document.createElement("option");
    option.value = cat.toLowerCase();
    option.textContent = cat;
    categoryFilter.appendChild(option);
    existing.add(cat.toLowerCase());
  });
}

function isImageIcon(icon) {
  if (!icon) return false;
  return (
    icon.startsWith("http://") ||
    icon.startsWith("https://") ||
    icon.startsWith("data:") ||
    icon.startsWith("/") ||
    icon.startsWith("icons/")
  );
}

async function openApp(app) {
  openingSet.add(app.id);
  renderCards();
  try {
    const res = await fetch(api.open(app.id), { method: "POST" });
    const data = await res.json();
    if (res.ok && data.status === "ok") {
      showToast(`Abriendo ${app.name}...`);
    } else {
      showToast(data.error || data.output || "No se pudo abrir");
    }
  } catch (err) {
    console.error(err);
    showToast("No se pudo abrir");
  } finally {
    openingSet.delete(app.id);
    renderCards();
  }
}

async function fetchVersions() {
  try {
    const tasks = apps.map((app) =>
      fetch(api.version(app.id))
        .then((r) => (r.ok ? r.json() : {}))
        .then((data) => versionsMap.set(app.id, data))
        .catch(() => versionsMap.set(app.id, {}))
    );
    await Promise.all(tasks);
  } catch (err) {
    console.error(err);
  }
}
