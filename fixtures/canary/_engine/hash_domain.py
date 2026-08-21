"""Read the hash-domain registry out of docs/contract/effective_config.md.

The registry has one authority: that document. Copying the key list into code
would create a second one, and a divergence between them would be exactly the
recurring failure the project has already recorded three times — a declared
standard and an enforced standard drifting apart. So the code parses the
document instead of restating it, and the tests fail if the two disagree.
"""

from __future__ import annotations

import os
import re

from _engine.canonical import digest

REGISTRY_DOC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "docs", "contract", "effective_config.md")

_MARKER = re.compile(
    r"<!--\s*registry:(?P<name>[a-z_]+)\s+version=(?P<version>\d+)\s*-->")


def _clean(cell: str) -> str:
    cell = cell.strip()
    cell = re.sub(r"\*\*[^*]*\*\*", "", cell)          # drop bold annotations
    match = re.search(r"`([^`]+)`", cell)
    return match.group(1) if match else cell.strip()


def load_registry(path: str = REGISTRY_DOC) -> dict[str, dict]:
    """{registry_name: {"version": int, "keys": [...], "rows": [[cells]]}}"""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    out: dict[str, dict] = {}
    for index, line in enumerate(lines):
        match = _MARKER.search(line)
        if not match:
            continue
        rows, seen_header = [], False
        for candidate in lines[index + 1:]:
            stripped = candidate.strip()
            if not stripped:
                if rows:
                    break
                continue
            if not stripped.startswith("|"):
                break
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not seen_header:
                seen_header = True
                continue
            if set("".join(cells)) <= set("-: "):
                continue
            rows.append(cells)
        out[match.group("name")] = {
            "version": int(match.group("version")),
            "keys": [_clean(r[0]) for r in rows],
            "rows": rows,
        }
    return out


def fingerprint_values(manifest: dict, keys: list[str]) -> dict[str, str]:
    """Project a RunManifest v2 onto a hash domain.

    A registered key is looked up first as a top-level field, then in the
    `environment` map. That order matters: `rng_algorithm` is a top-level
    typed field (Q2) and must not be silently satisfied by a same-named
    environment entry.
    """
    values = {}
    for key in keys:
        if key in manifest:
            values[key] = manifest[key]
        elif key in manifest.get("environment", {}):
            values[key] = manifest["environment"][key]
        else:
            raise KeyError(f"registered domain key not present in manifest: {key}")
    return values


def environment_fingerprint_digest(manifest: dict, registry: dict) -> str:
    domain = registry["runtime_fingerprint_domain"]
    if manifest["runtime_fingerprint_domain_version"] != domain["version"]:
        raise ValueError(
            "manifest declares runtime_fingerprint_domain_version="
            f"{manifest['runtime_fingerprint_domain_version']} but the registry "
            f"is at version {domain['version']}; the two must agree or the "
            "digest describes a domain nobody registered")
    return digest(fingerprint_values(manifest, domain["keys"]), "effective_config")
