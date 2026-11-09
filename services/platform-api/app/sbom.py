"""Inventory of installed packages and a content digest of that inventory."""

import hashlib
import importlib.metadata
import json


def generate_sbom() -> dict[str, object]:
    components: list[dict[str, str]] = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        if not isinstance(name, str) or not name:
            continue
        components.append({"name": name, "version": dist.version})
    components.sort(key=lambda item: item["name"].lower())
    document: dict[str, object] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": components,
    }
    encoded = json.dumps(document, sort_keys=True).encode("utf-8")
    document["digest"] = {"algorithm": "sha256", "value": hashlib.sha256(encoded).hexdigest()}
    return document
