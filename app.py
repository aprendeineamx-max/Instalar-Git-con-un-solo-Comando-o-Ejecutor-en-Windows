import subprocess
from pathlib import Path
from typing import Tuple

from flask import Flask, jsonify, request, send_from_directory

from apps_store import AppsStore


BASE_DIR = Path(__file__).parent
DATA_PATH = BASE_DIR / "data" / "apps.json"

app = Flask(__name__, static_folder="static", static_url_path="")
store = AppsStore(DATA_PATH)


def run_powershell(command: str, timeout: int = 900) -> Tuple[int, str]:
    """Execute a PowerShell command and return exit code and combined output."""
    ps_command = [
        "powershell",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; {command}",
    ]
    completed = subprocess.run(
        ps_command,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
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

    if not name or not command:
        return (
            jsonify({"error": "Se requieren 'name' y 'command'."}),
            400,
        )

    new_app = store.add_app(
        name=name,
        command=command,
        description=description,
        category=category,
    )
    return jsonify(new_app), 201


@app.post("/api/install/<int:app_id>")
def install_app(app_id: int):
    app_config = store.get_app(app_id)
    if not app_config:
        return jsonify({"error": "Aplicación no encontrada."}), 404

    code, output = run_powershell(app_config["command"])
    status = "ok" if code == 0 else "error"
    return jsonify(
        {
            "status": status,
            "exit_code": code,
            "output": output,
            "app": app_config,
        }
    )


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
