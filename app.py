import json
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Generator, Tuple

from flask import (
    Flask,
    Response,
    jsonify,
    request,
    send_from_directory,
    stream_with_context,
)

from apps_store import AppsStore


BASE_DIR = Path(__file__).parent
DATA_PATH = BASE_DIR / "data" / "apps.json"
LOG_CHAR_LIMIT = 12_000

app = Flask(__name__, static_folder="static", static_url_path="")
store = AppsStore(DATA_PATH)


def build_ps_command(command: str) -> list:
    return [
        "powershell",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; {command}",
    ]


def sanitize_line(line: str) -> str:
    cleaned = line.replace("\r", "")
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
    return cleaned


def parse_progress(text: str) -> int:
    matches = re.findall(r"(\d{1,3})%", text)
    if not matches:
        return -1
    return min(100, max(int(m) for m in matches))


def is_already_installed(text: str) -> bool:
    normalized = text.lower()
    signals = [
        "ya instalado",
        "ya se encuentra instalado",
        "no se ha encontrado ninguna actualización disponible",
        "no hay versiones más recientes",
        "paquete existente ya instalado",
        "already installed",
        "no applicable update",
        "no updates available",
        "no update available",
        "latest version already installed",
        "nenhuma atualização disponível",
        "já está instalado",
        "keine aktualisierung verfügbar",
        "bereits installiert",
        "paket bereits installiert",
        "pas de mise à jour disponible",
        "déjà installé",
    ]
    return any(sig in normalized for sig in signals)


def extract_package_id(command: str) -> str:
    match = re.search(r"--id\s+([\w\.\-]+)", command, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def find_appx_pfn(app_name: str) -> str:
    """Try to discover Package Family Name from installed Appx packages using a fuzzy name match."""
    pattern = re.sub(r"[^A-Za-z0-9]", "", app_name)
    if not pattern:
        return ""
    cmd = (
        f"(Get-AppxPackage -Name '*{pattern}*' | Select-Object -First 1).PackageFamilyName"
    )
    code, output = run_powershell(cmd, timeout=30)
    if code != 0:
        return ""
    pfn = (output or "").strip().splitlines()[0] if output else ""
    return pfn.strip()


def _detect_source(app_config: dict) -> str:
    cmd = app_config.get("command", "").lower()
    if "--source msstore" in cmd:
        return "--source msstore"
    return ""


def check_app_installed(app_config: dict) -> bool:
    pkg_id = extract_package_id(app_config.get("command", ""))
    name = app_config.get("name", "").strip()
    if not pkg_id and not name:
        return False

    not_installed_signals = [
        "no se encuentra ningun paquete instalado",
        "no se encuentra ningún paquete instalado",
        "no se encuentra ningun paquete instalado que coincida con los criterios de entrada",
        "no se encuentra ningún paquete instalado que coincida con los criterios de entrada",
        "no installed package found",
        "no installed package found matching input criteria",
        "no packages found",
        "no package found",
        "no se encontró el paquete",
    ]

    def matches(norm_text: str) -> bool:
        base = pkg_id.lower()
        alt = f"{base}.exe" if not base.endswith(".exe") else base
        name_l = name.lower()
        base_nodots = base.replace(".", "")
        name_clean = re.sub(r"[^a-z0-9]", "", name_l)
        keywords = {
            base,
            alt,
            base_nodots,
            name_l,
            name_clean,
        }
        if "chrome" in base or "chrome" in name_l:
            keywords.update({"google chrome", "chrome", "chromedev"})
        if "chatgpt" in base or "chatgpt" in name_l:
            keywords.update(
                {
                    "chatgpt",
                    "openai.chatgpt",
                    "chatgptdesktop",
                    "chatgpt-desktop",
                    "openai.chatgpt-desktop",
                }
            )
        return is_already_installed(norm_text) or any(
            kw for kw in keywords if kw and kw in norm_text
        )

    source = _detect_source(app_config)
    search_terms = []
    if pkg_id:
        search_terms.append(f"winget list --id {pkg_id} --exact {source}".strip())
    if name:
        search_terms.append(f'winget list "{name}" {source}'.strip())
    if "chatgpt" in name.lower() and f'winget list "ChatGPT"' not in search_terms:
        search_terms.append(f'winget list "ChatGPT" {source}'.strip())

    for cmd in search_terms:
        code, output = run_powershell(cmd, timeout=120)
        norm = output.lower()
        if matches(norm):
            if re.search(r"\b[0-9][0-9a-zA-Z\.\-\+]+\b", output):
                return True
        if any(sig in norm for sig in not_installed_signals):
            continue
    return False


def get_versions(app_config: dict) -> Dict[str, str]:
    """Return current and latest version via winget."""
    pkg_id = extract_package_id(app_config.get("command", "")) or app_config.get("name", "")
    source = _detect_source(app_config)
    current = "desconocida"
    latest = "desconocida"

    # Installed version
    code_list, out_list = run_powershell(f"winget list --id {pkg_id} --exact {source}".strip())
    out_clean = out_list.replace("\r", "")
    m_inst = re.search(rf"(?im)^\s*.*?\s{re.escape(pkg_id)}\s+([0-9][0-9A-Za-z\.\-\+]+)", out_clean)
    if not m_inst:
        m_inst = re.search(r"(?im)\b([0-9][0-9A-Za-z\.\-\+]+)\b", out_clean)
    if m_inst and code_list == 0:
        current = m_inst.group(1)

    # Latest version
    code_show, out_show = run_powershell(f"winget show --id {pkg_id} --exact {source}".strip())
    m_show = re.search(r"(?i)Version:\s*([0-9a-zA-Z\.\-\+]+)", out_show)
    if m_show:
        latest = m_show.group(1)

    def parse_v(v: str) -> Tuple:
        return tuple(int(x) for x in re.split(r"[^\d]", v) if x.isdigit())

    update_available = False
    if current != "desconocida" and latest != "desconocida":
        try:
            update_available = parse_v(current) < parse_v(latest)
        except Exception:
            update_available = current != latest

    return {
        "current_version": current,
        "latest_version": latest,
        "update_available": update_available,
    }


@app.post("/api/open/<int:app_id>")
def open_app(app_id: int):
    app_config = store.get_app(app_id)
    if not app_config:
        return jsonify({"error": "Aplicacion no encontrada."}), 404
    launch_cmd = app_config.get("launch") or app_config.get("name")
    if not launch_cmd:
        return jsonify({"error": "No hay comando de apertura definido."}), 400

    # Primer intento con el comando provisto
    code, output = run_powershell(f'Start-Process "{launch_cmd}"')
    if code == 0:
        return jsonify({"status": "ok", "exit_code": code, "output": output})

    # Fallback para apps de Microsoft Store: abrir por Package Family Name
    pfn = app_config.get("pfn") or find_appx_pfn(app_config.get("name", ""))
    if pfn:
        fallback_cmd = f'Start-Process "shell:AppsFolder\\{pfn}!App"'
        code2, output2 = run_powershell(fallback_cmd)
        status = "ok" if code2 == 0 else "error"
        return jsonify(
            {
                "status": status,
                "exit_code": code2,
                "output": output2 or output,
                "pfn": pfn,
            }
        )

    return jsonify({"status": "error", "exit_code": code, "output": output})


def sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def run_powershell(command: str, timeout: int = 900) -> Tuple[int, str]:
    """Execute a PowerShell command and return exit code and combined output."""
    ps_command = build_ps_command(command)
    completed = subprocess.run(
        ps_command,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    output = sanitize_line((completed.stdout or "") + (completed.stderr or ""))
    if len(output) > LOG_CHAR_LIMIT:
        output = output[:LOG_CHAR_LIMIT] + "\n... salida truncada ..."
    return completed.returncode, output


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/apps")
def get_apps():
    return jsonify(store.list_apps())


@app.post("/api/apps")
def add_app():
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    command = (payload.get("command") or "").strip()
    description = (payload.get("description") or "").strip()
    category = (payload.get("category") or "").strip() or "Otros"
    launch = (payload.get("launch") or "").strip()
    icon = (payload.get("icon") or "").strip()
    homepage = (payload.get("homepage") or "").strip()
    download = (payload.get("download") or "").strip()

    if not name or not command:
        return jsonify({"error": "Se requieren 'name' y 'command'."}), 400

    new_app = store.add_app(
        name=name,
        command=command,
        description=description,
        category=category,
        launch=launch,
        icon=icon,
        homepage=homepage,
        download=download,
    )
    return jsonify(new_app), 201


@app.get("/api/install/<int:app_id>/stream")
def install_app_stream(app_id: int):
    app_config = store.get_app(app_id)
    if not app_config:
        return jsonify({"error": "Aplicacion no encontrada."}), 404

    def generate() -> Generator[str, None, None]:
        yield sse("start", {"app": app_config})
        ps_command = build_ps_command(app_config["command"])
        proc = subprocess.Popen(
            ps_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log_buffer: list[str] = []
        truncated = False
        current_progress = 1
        start_time = time.time()
        while True:
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                break
            if line == "":
                time.sleep(0.05)
                continue

            clean = sanitize_line(line).strip()
            if not clean:
                continue

            maybe_progress = parse_progress(clean)
            if maybe_progress >= 0 and maybe_progress > current_progress:
                current_progress = min(maybe_progress, 100)
                yield sse("progress", {"progress": current_progress})

            if not truncated:
                log_buffer.append(clean)
                if sum(len(item) + 1 for item in log_buffer) > LOG_CHAR_LIMIT:
                    truncated = True
                    log_buffer.append("... salida truncada ...")
                    yield sse("truncate", {"limit": LOG_CHAR_LIMIT})
            yield sse("log", {"line": clean})

            if time.time() - start_time > 900:
                proc.kill()
                break

        code = proc.wait()
        output = "\n".join(log_buffer)
        status = "ok" if code == 0 or is_already_installed(output) else "error"
        store.mark_installed(app_id, status == "ok")
        yield sse(
            "done",
            {
                "status": status,
                "exit_code": code,
                "output": output,
                "app": store.get_app(app_id),
            },
        )

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.post("/api/install/<int:app_id>")
def install_app(app_id: int):
    app_config = store.get_app(app_id)
    if not app_config:
        return jsonify({"error": "Aplicacion no encontrada."}), 404

    code, output = run_powershell(app_config["command"])
    status = "ok" if code == 0 or is_already_installed(output) else "error"
    store.mark_installed(app_id, status == "ok")
    return jsonify(
        {
            "status": status,
            "exit_code": code,
            "output": output,
            "app": store.get_app(app_id),
        }
    )


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/check-installations")
def check_installations():
    apps = store.list_apps()
    results = []
    for app_cfg in apps:
        installed = check_app_installed(app_cfg)
        store.mark_installed(app_cfg["id"], installed)
        results.append(
            {
                "id": app_cfg["id"],
                "name": app_cfg["name"],
                "installed": installed,
            }
        )
    return jsonify(results)


@app.get("/api/version/<int:app_id>")
def version_info(app_id: int):
    app_cfg = store.get_app(app_id)
    if not app_cfg:
        return jsonify({"error": "Aplicacion no encontrada."}), 404
    versions = get_versions(app_cfg)
    return jsonify(versions)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
