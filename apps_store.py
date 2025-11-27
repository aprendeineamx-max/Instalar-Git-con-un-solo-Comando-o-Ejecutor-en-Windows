import json
import threading
from pathlib import Path
from typing import Dict, List, Optional


class AppsStore:
    """Thread-safe JSON store for installable apps."""

    def __init__(self, json_path: Path) -> None:
        self.json_path = json_path
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.json_path.exists():
            default = [
                {
                    "id": 1,
                    "name": "Git",
                    "command": "winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements --silent",
                    "description": "Cliente Git oficial por winget para clonar y contribuir a repos (instalacion silenciosa).",
                    "category": "Control de versiones",
                    "installed": False,
                    "launch": "",
                    "icon": "⬢",
                    "homepage": "",
                    "download": "",
                    "pfn": "",
                }
            ]
            self._write(default)

    def _read(self) -> List[Dict]:
        with self.json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for app in data:
            app.setdefault("installed", False)
            app.setdefault("launch", "")
            app.setdefault("icon", "⬢")
            app.setdefault("homepage", "")
            app.setdefault("download", "")
            app.setdefault("pfn", "")
        return data

    def _write(self, data: List[Dict]) -> None:
        with self.json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_apps(self) -> List[Dict]:
        with self._lock:
            return self._read()

    def add_app(
        self,
        name: str,
        command: str,
        description: str = "",
        category: str = "Otros",
        launch: str = "",
        icon: str = "⬢",
        homepage: str = "",
        download: str = "",
        pfn: str = "",
    ) -> Dict:
        with self._lock:
            apps = self._read()
            next_id = max([app["id"] for app in apps], default=0) + 1
            new_app = {
                "id": next_id,
                "name": name.strip(),
                "command": command.strip(),
                "description": description.strip(),
                "category": category.strip() or "Otros",
                "installed": False,
                "launch": launch.strip(),
                "icon": icon.strip() or "⬢",
                "homepage": homepage.strip(),
                "download": download.strip(),
                "pfn": pfn.strip(),
            }
            apps.append(new_app)
            self._write(apps)
            return new_app

    def get_app(self, app_id: int) -> Optional[Dict]:
        with self._lock:
            apps = self._read()
            return next((app for app in apps if app.get("id") == app_id), None)

    def update_app(
        self,
        app_id: int,
        *,
        command: Optional[str] = None,
        launch: Optional[str] = None,
        homepage: Optional[str] = None,
        download: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> Optional[Dict]:
        with self._lock:
            apps = self._read()
            target = next((app for app in apps if app.get("id") == app_id), None)
            if not target:
                return None
            if command is not None:
                target["command"] = command
            if launch is not None:
                target["launch"] = launch
            if homepage is not None:
                target["homepage"] = homepage
            if download is not None:
                target["download"] = download
            if icon is not None:
                target["icon"] = icon
            self._write(apps)
            return target

    def mark_installed(self, app_id: int, installed: bool) -> Optional[Dict]:
        with self._lock:
            apps = self._read()
            target = next((app for app in apps if app.get("id") == app_id), None)
            if not target:
                return None
            target["installed"] = installed
            self._write(apps)
            return target
