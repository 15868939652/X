from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


class ConfigManager:
    def __init__(self) -> None:
        self.data_dir = _runtime_root() / "launcher_data"
        self.data_dir.mkdir(exist_ok=True)
        self.templates_path = self.data_dir / "templates.json"
        self.last_config_path = self.data_dir / "last_config.json"

    def _read_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _write_json(self, path: Path, payload) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_last_config(self) -> dict:
        return self._read_json(self.last_config_path, {})

    def save_last_config(self, payload: dict) -> None:
        self._write_json(self.last_config_path, payload)

    def list_templates(self) -> list[dict]:
        payload = self._read_json(self.templates_path, {"templates": []})
        return list(payload.get("templates", []))

    def save_template(self, name: str, payload: dict) -> str:
        clean_name = re.sub(r"\s+", " ", name).strip()
        if not clean_name:
            raise ValueError("模板名称不能为空")
        templates = self.list_templates()
        filtered = [item for item in templates if item.get("name") != clean_name]
        filtered.append({"name": clean_name, **payload})
        filtered.sort(key=lambda item: item["name"])
        self._write_json(self.templates_path, {"templates": filtered})
        return clean_name

    def load_template(self, name: str) -> dict | None:
        for item in self.list_templates():
            if item.get("name") == name:
                return item
        return None

    def delete_template(self, name: str) -> bool:
        templates = self.list_templates()
        filtered = [item for item in templates if item.get("name") != name]
        if len(filtered) == len(templates):
            return False
        self._write_json(self.templates_path, {"templates": filtered})
        return True
