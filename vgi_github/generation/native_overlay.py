"""Merge author-owned Crossfield definitions without interpreting their SQL.

Generated API contracts remain owned by the source compiler. Native fragments
add fields, stages, metrics, policy and callable input configuration. Crossfield's
schemas and native binder remain the semantic validators.
"""

from __future__ import annotations

import json
from copy import deepcopy

NATIVE_SECTIONS = {"invocations", "metrics", "policy", "semantic_query", "relationships"}


def _record_origins(value, path, source, origins):
    origins[path] = source
    if isinstance(value, dict):
        for key, child in value.items():
            _record_origins(child, (*path, key), source, origins)


def _definition(path):
    return (
        len(path) == 2
        and path[0] == "metrics"
        or len(path) == 3
        and path[:2]
        in {
            ("invocations", "derived_datasets"),
            ("invocations", "input_contracts"),
            ("policy", "local_time_fields"),
            ("policy", "metric_semantics"),
            ("policy", "field_semantics"),
            ("semantic_query", "parameters"),
        }
        or len(path) == 6
        and path[:2] == ("invocations", "sources")
        and path[3:5] == ("dataset", "fields")
    )


def _named(item):
    name = item.get("name") if isinstance(item, dict) else None
    return name.casefold() if isinstance(name, str) else None


def merge_native(target, additions, *, source, origins=None, path=(), generated=False):
    """Merge with explicit ownership and domain locations on collisions.

    Domains cannot replace one another. Applying the composed fragment to the
    generated model permits identical approvals; different values cannot
    overwrite generated source or policy meaning.
    """
    if not isinstance(additions, dict):
        raise ValueError(f"{source}: crossfield definitions must be an object")
    if not path and set(additions) - NATIVE_SECTIONS:
        unknown = sorted(set(additions) - NATIVE_SECTIONS)
        raise ValueError(f"{source}: unsupported native Crossfield sections {unknown}")
    origins = {} if origins is None else origins
    for key, value in additions.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{source}: native definition names must be nonempty strings")
        location = (*path, key)
        existing = next((name for name in target if name.casefold() == key.casefold()), None)
        if existing is None:
            target[key] = deepcopy(value)
            _record_origins(value, location, source, origins)
            continue
        old = target[existing]
        label = "crossfield." + ".".join(location)
        first = origins.get((*path, existing), "the generated model" if generated else "an earlier domain")
        if existing != key or (_definition(location) and not generated):
            raise ValueError(f"{source}: duplicate native definition {label}; first declared in {first}")
        if isinstance(old, dict) and isinstance(value, dict):
            merge_native(old, value, source=source, origins=origins, path=location, generated=generated)
        elif isinstance(old, list) and isinstance(value, list):
            signatures = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in old}
            names = {_named(item) for item in old} - {None}
            for item in value:
                signature = json.dumps(item, sort_keys=True, ensure_ascii=False)
                duplicate = signature in signatures
                name = _named(item)
                if name in names and not (generated and duplicate):
                    raise ValueError(f"{source}: duplicate named declaration in {label}")
                if duplicate:
                    if generated:
                        continue
                    raise ValueError(f"{source}: duplicate declaration in {label}; first declared in {first}")
                old.append(deepcopy(item))
                signatures.add(signature)
                if name is not None:
                    names.add(name)
        elif not (generated and type(old) is type(value) and old == value):
            raise ValueError(f"{source}: conflicting native definition {label}; first declared in {first}")


def apply_native_overlay(model, fragment):
    """Preserve emitted provider wire contracts while adding native definitions."""
    if not isinstance(fragment, dict):
        raise ValueError("crossfield must be a native manifest fragment")
    for section in NATIVE_SECTIONS - {"relationships"}:
        if section in fragment and not isinstance(fragment[section], dict):
            raise ValueError(f"crossfield.{section} must be an object")
    invocations = fragment.get("invocations", {})
    if set(invocations) - {"derived_datasets", "input_contracts", "sources"}:
        raise ValueError("Native invocations may add derived datasets, input contracts and modeled source fields")
    sources = invocations.get("sources", {})
    if not isinstance(sources, dict):
        raise ValueError("crossfield.invocations.sources must be an object")
    for name, extension in sources.items():
        if name not in model["invocations"]["sources"]:
            raise ValueError(f"Native source fields reference unknown generated dataset {name!r}")
        if (
            not isinstance(extension, dict)
            or set(extension) != {"dataset"}
            or not isinstance(extension["dataset"], dict)
            or set(extension["dataset"]) != {"fields"}
            or not isinstance(extension["dataset"]["fields"], dict)
        ):
            raise ValueError(
                f"Native source {name!r} may add dataset.fields only; provider contracts are generated"
            )
        existing = model["invocations"]["sources"][name]["dataset"]["fields"]
        for field in extension["dataset"]["fields"]:
            if any(field.casefold() == prior.casefold() for prior in existing):
                raise ValueError(f"Native field {name}.{field} collides with a generated field")
    for name in fragment.get("metrics", {}):
        if any(name.casefold() == prior.casefold() for prior in model.get("metrics", {})):
            raise ValueError(f"Native metrics definition {name!r} collides with a generated definition")
    merge_native(model, fragment, source="native Crossfield domain", generated=True)
    return model
