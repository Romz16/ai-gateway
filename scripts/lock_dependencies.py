"""Pin installed dependency versions; run in a clean, reviewed environment."""

from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement


def closure(requirements):
    found = {}
    pending = [(Requirement(value), "") for value in requirements]
    while pending:
        requirement, extra = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({"extra": extra}):
            continue
        name = requirement.name.lower().replace("_", "-")
        if name in found:
            continue
        dist = metadata.distribution(name)
        found[name] = dist.version
        for item in dist.requires or []:
            for selected_extra in ["", *requirement.extras]:
                pending.append((Requirement(item), selected_extra))
    return found


root = metadata.distribution("production-ai-gateway")
base = closure(
    [
        str(Requirement(r))
        for r in root.requires or []
        if not Requirement(r).marker or Requirement(r).marker.evaluate({"extra": ""})
    ]
)
# greenlet is required by SQLAlchemy asyncio on supported Linux runtimes.
base["greenlet"] = metadata.version("greenlet")
dev = {
    d.metadata["Name"].lower().replace("_", "-"): d.version
    for d in metadata.distributions()
    if d.metadata["Name"].lower() not in {"production-ai-gateway", "pip", "setuptools"}
}
for filename, versions in [("requirements.lock", base), ("requirements-dev.lock", dev)]:
    Path(filename).write_text(
        "# Exact tested versions; refresh with scripts/lock_dependencies.py.\n"
        + "".join(f"{name}=={version}\n" for name, version in sorted(versions.items()))
    )
