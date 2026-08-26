"""Create a clean source archive and verify its contents."""

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT_FILES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "alembic.ini",
    "CONTRIBUTING.md",
    "docker-compose.yml",
    "Dockerfile",
    "LICENSE",
    "Makefile",
    "pyproject.toml",
    "README.md",
    "requirements.lock",
    "requirements-dev.lock",
    "SECURITY.md",
}
ROOT_DIRS = {
    ".github",
    "app",
    "benchmarks",
    "config",
    "docker",
    "docs",
    "examples",
    "migrations",
    "scripts",
    "tests",
}
EXCLUDED = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}


def files(root):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(p in EXCLUDED for p in relative.parts):
            continue
        if len(relative.parts) == 1 and path.name not in ROOT_FILES:
            continue
        if len(relative.parts) > 1 and relative.parts[0] not in ROOT_DIRS:
            continue
        if path.suffix in {".pyc", ".pyo", ".db"} or path.name == ".env":
            continue
        yield path, relative


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    selected = list(files(root))
    missing = []
    for path, relative in selected:
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if "://" in target or target.startswith("#") or target.startswith("mailto:"):
                    continue
                target = target.split("#")[0]
                if target and not (path.parent / target).exists():
                    missing.append((str(relative), target))
    if missing:
        raise SystemExit(f"Broken documentation links: {missing}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, relative in selected:
            data = path.read_bytes()
            name = "ai-gateway/" + relative.as_posix()
            archive.writestr(name, data)
            manifest.append(hashlib.sha256(data).hexdigest() + "  " + relative.as_posix())
            if args.stage:
                target = args.stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        archive.writestr("ai-gateway/MANIFEST.sha256", "\n".join(manifest) + "\n")
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert "ai-gateway/.github/workflows/ci.yml" in names
        assert "ai-gateway/.env" not in names
        assert all(".. " not in name and not name.startswith("/") for name in names)
        for item in archive.infolist():
            if item.filename.endswith(".py"):
                compile(archive.read(item.filename), item.filename, "exec")
    sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".zip.sha256").write_text(sha + "  " + args.output.name + "\n")
    print(
        json.dumps(
            {
                "archive": str(args.output),
                "files": len(names),
                "bytes": args.output.stat().st_size,
                "sha256": sha,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
