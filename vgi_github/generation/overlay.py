"""Compose explicitly listed semantic domains before the existing compiler runs.

This is concatenation with collision checks, not an override or import language.
Domains may reference each other; the assembled model has one validation boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

from vgi_github.generation.native_overlay import merge_native

LIST_SECTIONS = ("entities", "functions", "relationships")
MAP_SECTIONS = ("scopes", "shared_dimensions", "cohorts")


def overlay_bytes(overlay: dict) -> bytes:
    """Hash the assembled definitions, including every domain, in declared order."""
    return (json.dumps(overlay, indent=2, ensure_ascii=False) + "\n").encode()


def _read(path: Path) -> dict:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        document = json.loads(path.read_text(), object_pairs_hook=unique_keys)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read semantic definitions {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return document


def load_overlay(path: Path) -> dict:
    """Read a model manifest and its ordered, non-recursive domain files.

    All paths are relative to the manifest, remain under its directory, and must
    identify different files. Duplicate declarations fail rather than overwrite.
    Type, reference, relationship and expression checks remain in the existing
    generator and Crossfield validators.
    """
    path = Path(path).resolve()
    manifest = _read(path)
    if set(manifest) != {"format", "version", "model", "domains"}:
        raise ValueError(f"{path}: manifest requires only format, version, model and domains")
    if manifest["format"] != "vgi-github-semantic-overlay" or manifest["version"] != 1:
        raise ValueError(f"{path}: unsupported semantic overlay format/version")
    domains = manifest["domains"]
    if not isinstance(domains, list) or not domains:
        raise ValueError(f"{path}: domains must be a nonempty ordered list of JSON paths")
    overlay = {key: manifest[key] for key in ("format", "version", "model")}
    overlay.update({key: [] for key in LIST_SECTIONS})
    overlay.update({key: {} for key in MAP_SECTIONS})
    origins = {key: {} for key in (*LIST_SECTIONS, *MAP_SECTIONS)}
    native_origins = {}
    files = set()
    for relative in domains:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError(f"{path}: domain paths must be nonempty relative JSON paths")
        source = (path.parent / relative).resolve()
        if not source.is_relative_to(path.parent) or source.suffix != ".json":
            raise ValueError(f"{path}: domain {relative!r} must be a JSON file under {path.parent}")
        if source == path or source in files:
            raise ValueError(f"{path}: duplicate or recursive domain file {relative!r}")
        files.add(source)
        fragment = _read(source)
        unknown = set(fragment) - set(origins) - {"crossfield"}
        if unknown or not fragment:
            raise ValueError(f"{source}: expected domain sections, unknown keys {sorted(unknown)}")
        for section, definitions in fragment.items():
            if section == "crossfield":
                merge_native(
                    overlay.setdefault("crossfield", {}),
                    definitions,
                    source=str(source),
                    origins=native_origins,
                )
                continue
            if section in LIST_SECTIONS:
                if not isinstance(definitions, list):
                    raise ValueError(f"{source}: {section} must be a list")
                entries = []
                for definition in definitions:
                    if not isinstance(definition, dict):
                        raise ValueError(f"{source}: each {section} declaration must be an object")
                    entries.append((definition.get("name"), definition))
            else:
                if not isinstance(definitions, dict):
                    raise ValueError(f"{source}: {section} must be a named object")
                entries = list(definitions.items())
            for name, definition in entries:
                if not isinstance(name, str) or not name:
                    raise ValueError(f"{source}: {section} declarations require nonempty names")
                key = name.lower()
                if key in origins[section]:
                    raise ValueError(
                        f"{source}: duplicate {section} name {name!r}; "
                        f"first declared in {origins[section][key]}"
                    )
                origins[section][key] = source
                if section in LIST_SECTIONS:
                    overlay[section].append(definition)
                else:
                    overlay[section][name] = definition
    return overlay
