"""Validate machine-readable repository artifacts."""

import json
from pathlib import Path

import yaml

from app.main import create_app

root = Path(__file__).resolve().parents[1]
for path in root.rglob("*.json"):
    if not any(part.startswith(".") for part in path.relative_to(root).parts):
        json.loads(path.read_text(encoding="utf-8"))
for path in [
    root / "docker-compose.yml",
    *list((root / "docker").rglob("*.yml")),
    *list((root / ".github").rglob("*.yml")),
]:
    yaml.safe_load(path.read_text(encoding="utf-8"))
schema = create_app().openapi()
(root / "docs" / "openapi.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
print("JSON, YAML and OpenAPI validation passed.")
