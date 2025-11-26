const api = {
  apps: "/api/apps",
  add: "/api/apps",
  install: (id) => `/api/install/${id}`,
};

const toastEl = document.getElementById("toast");
const appCount = document.getElementById("appCount");
const appsGrid = document.getElementById("appsGrid");
const searchInput = document.getElementById("search");
const addForm = document.getElementById("addForm");
const logList = document.getElementById("logList");
const navLinks = document.querySelectorAll(".nav-link");

let apps = [];
let logs = [];
let installingIds = new Set();
const statusMap = new Map(); // id -> {state, progress}
const progressTimers = new Map();

function showToast(message) {
  toastEl.textContent = message;
  toastEl.classList.add("show");
  setTimeout(() => toastEl.classList.remove("show"), 2500);
}

async function fetchApps() {
  const res = await fetch(api.apps);
  apps = await res.json();
  appCount.textContent = apps.length;
  renderCards();
}

function renderCards() {
  const query = (searchInput.value || "").toLowerCase();
  const filtered = apps.filter(
    (a) =>
      a.name.toLowerCase().includes(query) ||
      (a.category || "").toLowerCase().includes(query)
  );

  appsGrid.innerHTML = "";
  if (!filtered.length) {
    appsGrid.innerHTML =
      '<p class="muted" style="grid-column: 1/-1;">Sin resultados</p>';
    return;
  }

  filtered.forEach((app) => {
    const state = statusMap.get(app.id) || { state: "idle", progress: 0 };
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="pill">${app.category || "General"}</div>
      <h3>${app.name}</h3>
      <p>${app.description || "Sin descripción"}</p>
      <div class="command">${app.command}</div>
      <div class="actions">
        ${
          state.state === "done"
            ? `<div class="status-pill success">Instalado</div>`
            : state.state === "error"
            ? `<div class="status-pill danger">Falló</div>`
            : ""
        }
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
              <span class="progress-text">100% • Instalado</span>
            </div>`
          : ""
      }
    `;
    appsGrid.appendChild(card);

    card.querySelector("[data-install]").addEventListener("click", () =>
      installApp(app)
    );
  });
}

async function installApp(app) {
  installingIds.add(app.id);
  setStatus(app.id, "installing", 1);
  showToast(`Ejecutando ${app.name}...`);
  try {
    const res = await fetch(api.install(app.id), { method: "POST" });
    const data = await res.json();
    logs.unshift({
      id: Date.now(),
      app: app.name,
      status: data.status,
      command: app.command,
      output: data.output || "",
      exit: data.exit_code,
    });
    renderLogs();
    const status = data.status === "ok" ? "✔️" : "⚠️";
    showToast(`${status} ${app.name}: ${data.status}`);
    setStatus(
      app.id,
      data.status === "ok" ? "done" : "error",
      data.status === "ok" ? 100 : 0
    );
  } catch (err) {
    console.error(err);
    showToast("Error al instalar");
    setStatus(app.id, "error", 0);
  } finally {
    installingIds.delete(app.id);
  }
}

function renderLogs() {
  logList.innerHTML = "";
  if (!logs.length) {
    logList.innerHTML =
      '<p class="muted">Sin ejecuciones aún. Instala algo para ver el historial.</p>';
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
      <pre class="muted" style="white-space: pre-wrap;">${log.output.trim().slice(0, 2000) || "Sin salida"}</pre>
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
document.getElementById("refresh").addEventListener("click", fetchApps);
document.getElementById("scrollNew").addEventListener("click", () => {
  document.getElementById("nuevo").scrollIntoView({ behavior: "smooth" });
});

fetchApps();

function setStatus(id, state, progress) {
  statusMap.set(id, { state, progress });
  if (state === "installing") {
    startProgress(id);
  } else {
    stopProgress(id);
  }
  renderCards();
}

function startProgress(id) {
  stopProgress(id);
  let current = statusMap.get(id)?.progress || 1;
  const timer = setInterval(() => {
    current = Math.min(current + Math.random() * 8, 90);
    statusMap.set(id, { state: "installing", progress: current });
    renderCards();
  }, 600);
  progressTimers.set(id, timer);
}

function stopProgress(id) {
  if (progressTimers.has(id)) {
    clearInterval(progressTimers.get(id));
    progressTimers.delete(id);
  }
}
