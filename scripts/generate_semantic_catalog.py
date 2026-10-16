"""Generate the limited typed/semantic pilot from locked, offline schema snapshots.

--extract-sources consumes an explicitly downloaded immutable upstream cache;
ordinary generation and --check never perform network access or execute SQL.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from graphql import (
    build_schema,
    get_named_type,
    is_enum_type,
    is_input_object_type,
    is_interface_type,
    is_object_type,
    is_scalar_type,
    is_union_type,
    parse,
    print_ast,
)
from graphql.language import DocumentNode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import generate_rest_catalog  # noqa: E402
from vgi_github.generation.artifacts import emit_artifacts, json_text  # noqa: E402
from vgi_github.generation.coverage import api_inventory, rest_response_shapes  # noqa: E402
from vgi_github.generation.coverage_keys import rest_contract_keys  # noqa: E402
from vgi_github.generation.overlay import load_overlay, overlay_bytes  # noqa: E402
from vgi_github.generation.schema import compile_contract, graphql_selection_paths  # noqa: E402


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _pointer(document, pointer):
    if not pointer.startswith("#/"):
        raise ValueError(f"External schema reference is outside this pilot: {pointer}")
    value = document
    for part in pointer[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def select_rest(spec, operations):
    """Copy selected GET operations and every referenced local definition."""
    selected = {"openapi": spec["openapi"], "info": copy.deepcopy(spec["info"]), "paths": {}}
    found = set()
    for path, item in spec["paths"].items():
        operation = item.get("get", {})
        if operation.get("operationId") not in operations:
            continue
        found.add(operation["operationId"])
        selected["paths"][path] = {"get": copy.deepcopy(operation)}
        if "parameters" in item:
            selected["paths"][path]["parameters"] = copy.deepcopy(item["parameters"])
    if found != set(operations):
        raise ValueError(f"Selected REST operations are missing: {sorted(set(operations) - found)}")
    copied = set()

    def refs(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference and reference not in copied:
                if not reference.startswith("#/components/"):
                    raise ValueError(f"Unsupported REST snapshot reference: {reference}")
                copied.add(reference)
                target = copy.deepcopy(_pointer(spec, reference))
                parts = [p.replace("~1", "/").replace("~0", "~") for p in reference[2:].split("/")]
                destination = selected
                for part in parts[:-1]:
                    destination = destination.setdefault(part, {})
                destination[parts[-1]] = target
                refs(target)
            for child in value.values():
                refs(child)
        elif isinstance(value, list):
            for child in value:
                refs(child)

    # Work over a copy because dependency insertion mutates selected.
    refs(copy.deepcopy(selected))
    return json_text(selected)


def select_graphql(sdl, entities):
    """Keep selected output paths and the full input/scalar/enum closure.

    Unselected output fields are omitted. Abstract parent identities retain every
    possible implementation when subtype-specific columns need runtime guards. Selected
    field signatures/descriptions and nullability come from the pinned SDL.
    This derived read-only schema is not a claim of complete GitHub coverage.
    """
    # The pinned upstream SDL contains duplicate fields in an unselected
    # Enterprise type. Resolve its type graph for selection, then strictly
    # validate the extracted closure below; selected duplicates still reject.
    schema = build_schema(sdl, assume_valid_sdl=True)
    selected_fields = {}
    selected_types = set()
    implementations = {}
    union_members = {}
    identity_members = set()

    def scalar_or_input(kind):
        kind = get_named_type(kind)
        if kind.name in selected_types:
            return
        selected_types.add(kind.name)
        if is_input_object_type(kind):
            for field in kind.fields.values():
                scalar_or_input(field.type)
        elif not (is_scalar_type(kind) or is_enum_type(kind)):
            raise ValueError(f"Unsupported GraphQL argument type {kind.name}")

    def field(parent, name):
        parent = get_named_type(parent)
        if not (is_object_type(parent) or is_interface_type(parent)) or name not in parent.fields:
            raise ValueError(f"Missing selected GraphQL path {parent.name}.{name}")
        selected_fields.setdefault(parent.name, set()).add(name)
        value = parent.fields[name]
        for argument in value.args.values():
            scalar_or_input(argument.type)
        result = get_named_type(value.type)
        if is_scalar_type(result) or is_enum_type(result):
            scalar_or_input(result)
        return result

    def concrete(parent, name):
        if not (is_interface_type(parent) or is_union_type(parent)):
            raise ValueError(f"Concrete selection requires an abstract GraphQL type: {parent.name}")
        possible = {kind.name: kind for kind in schema.get_possible_types(parent)}
        if name not in possible:
            raise ValueError(f"Invalid implementation {name} for {parent.name}")
        if is_union_type(parent):
            selected_types.add(parent.name)
            union_members.setdefault(parent.name, set()).add(name)
        else:
            implementations.setdefault(name, set()).add(parent.name)
            field(parent, next(iter(parent.fields)))
        return possible[name]

    def follow(parent, path, narrow=None):
        for name in path:
            if name.startswith("... on "):
                parent = concrete(parent, name[7:])
                continue
            if name == "__typename":
                parent = schema.get_type("String")
                scalar_or_input(parent)
                continue
            parent = field(parent, name)
            if name in (narrow or {}):
                parent = concrete(parent, narrow[name])
        return parent

    def selected_value(parent, selection=None, active=()):
        parent = get_named_type(parent)
        if is_scalar_type(parent) or is_enum_type(parent):
            if selection is not None:
                raise ValueError(f"Scalar GraphQL field {parent.name} cannot have a selection tree")
            scalar_or_input(parent)
            return
        if parent.name in active:
            raise ValueError(f"Unsupported recursive/union GraphQL selection {parent.name}")
        if not isinstance(selection, dict) or not selection:
            raise ValueError(f"GraphQL object {parent.name} needs an explicit nonempty selection tree")
        for name, child in selection.items():
            if child is not True and not isinstance(child, dict):
                raise ValueError(f"Invalid GraphQL selection for {parent.name}.{name}")
            if name == "__typename" and child is True:
                scalar_or_input(schema.get_type("String"))
            elif name.startswith("... on "):
                selected_value(concrete(parent, name[7:]), child, (*active, parent.name))
            else:
                selected_value(field(parent, name), None if child is True else child, (*active, parent.name))

    for entity in entities:
        transport = entity["transport"]
        connection = follow(schema.query_type, transport["field_path"], transport.get("field_types"))
        item = follow(connection, transport["result_path"])
        for column in entity["columns"]:
            if "path" in column:
                if "on_types" in column:
                    parent = follow(item, column["path"][:-1])
                    for possible in schema.get_possible_types(parent):
                        concrete(parent, possible.name)
                        if is_union_type(parent):
                            identity_members.add(possible.name)
                paths = graphql_selection_paths(schema, item, column["path"], on_types=column.get("on_types"))
                for _, query_path, _, _ in paths:
                    selected_value(follow(item, query_path), column.get("selection"))
        pagination = transport["pagination"]
        if pagination["kind"] == "cursor":
            page_info = follow(connection, pagination["page_info_path"])
            field(page_info, "hasNextPage")
            field(page_info, "endCursor")

    for name in sorted(identity_members - selected_fields.keys()):
        possible = schema.get_type(name)
        anchor = next(
            (
                name
                for name, value in possible.fields.items()
                if is_scalar_type(get_named_type(value.type)) or is_enum_type(get_named_type(value.type))
            ),
            None,
        )
        if anchor is None:
            raise ValueError(f"No selected identity field for abstract member {possible.name}")
        field(possible, anchor)
    for name, interfaces in implementations.items():
        for interface in interfaces:
            for common in selected_fields.get(interface, set()):
                field(schema.get_type(name), common)
    definitions = []
    for definition in parse(sdl).definitions:
        name = getattr(getattr(definition, "name", None), "value", None)
        if name not in selected_types and name not in selected_fields:
            continue
        node = copy.deepcopy(definition)
        if node.kind == "union_type_definition":
            node.types = tuple(
                value for value in node.types if value.name.value in union_members.get(name, set())
            )
        if name in selected_fields:
            node.fields = tuple(value for value in node.fields if value.name.value in selected_fields[name])
            if node.kind == "object_type_definition":
                node.interfaces = tuple(
                    value for value in node.interfaces if value.name.value in implementations.get(name, set())
                )

        # Vendor directives are metadata on the original schema; the selected
        # executable query contract retains GraphQL's field types and arguments.
        def strip_directives(value):
            if hasattr(value, "directives"):
                value.directives = ()
            for key in getattr(value, "keys", ()):
                child = getattr(value, key)
                if isinstance(child, tuple):
                    for member in child:
                        strip_directives(member)
                elif hasattr(child, "keys"):
                    strip_directives(child)

        strip_directives(node)
        definitions.append(node)
    selected = print_ast(DocumentNode(definitions=tuple(definitions))) + "\n"
    build_schema(selected)  # Reject an incomplete generated closure immediately.
    return selected


def extract_sources(cache, overlay):
    metadata = json.loads((cache / "sources.json").read_text())
    originals = {entry["file"]: entry for entry in metadata["sources"]}
    files = {}
    used = set()

    def read(name):
        if name not in originals:
            raise ValueError(f"Missing immutable upstream identity for {name}")
        source = originals[name]
        data = (cache / name).read_bytes()
        if digest(data) != source["sha256"]:
            raise ValueError(f"Upstream cache hash mismatch: {name}")
        revision = (
            metadata["graphql_revision"]
            if name in {"schema.graphql", "GRAPHQL-LICENSE"}
            else metadata["rest_revision"]
        )
        if len(revision) != 40 or f"/{revision}/" not in source["url"]:
            raise ValueError(f"Upstream source URL is not pinned to its declared revision: {name}")
        used.add(name)
        return data.decode()

    # Validate the full read surface before selecting the small executable model.
    # Otherwise an omitted API route can never appear as a coverage gap.
    manifest = json.loads((ROOT / "vgi_github/rest_manifest.json").read_text())
    if metadata["rest_revision"] != manifest["revision"]:
        raise ValueError("Full API inventory and REST manifest revisions differ")
    full_specs = {product: json.loads(read(product + ".json")) for product in generate_rest_catalog.PRODUCTS}
    rebuilt = generate_rest_catalog.build(
        cache, revision=manifest["revision"], api_version=manifest["api_version"]
    )
    if rebuilt != manifest:
        raise ValueError("REST manifest differs from the complete pinned OpenAPI contracts")
    full_sdl = read("schema.graphql")
    inventory = api_inventory(
        manifest,
        full_sdl,
        {
            product: dict(
                sorted(
                    Counter(
                        method.upper()
                        for item in spec["paths"].values()
                        for method in item
                        if method in {"put", "post", "patch", "delete", "head", "options", "trace"}
                    ).items()
                )
            )
            for product, spec in full_specs.items()
        },
        {product: rest_response_shapes(spec) for product, spec in full_specs.items()},
    )
    inventory["rest_manifest_sha256"] = digest((ROOT / "vgi_github/rest_manifest.json").read_bytes())
    inventory["rest"]["contract_keys_by_product"] = {
        product: rest_contract_keys(spec) for product, spec in full_specs.items()
    }
    inventory["graphql_revision"] = metadata["graphql_revision"]
    files["generation/sources/api-inventory.json"] = json_text(inventory)
    files["generation/sources/REST-LICENSE"] = read("REST-LICENSE")
    files["generation/sources/GRAPHQL-LICENSE"] = read("GRAPHQL-LICENSE")

    rest = [entity for entity in overlay["entities"] if entity["transport"]["kind"] == "rest"]
    products = sorted({entity["transport"].get("product", "api.github.com") for entity in rest})
    for product in products:
        operations = {
            e["transport"]["operation_id"]
            for e in rest
            if e["transport"].get("product", "api.github.com") == product
        }
        files[f"generation/sources/{product}.selected.json"] = select_rest(full_specs[product], operations)
    graphql = [entity for entity in overlay["entities"] if entity["transport"]["kind"] == "graphql"]
    if graphql:
        files["generation/sources/selected.graphql"] = select_graphql(full_sdl, graphql)
        files["generation/sources/GRAPHQL-LICENSE"] = read("GRAPHQL-LICENSE")
    if rest:
        files["generation/sources/REST-LICENSE"] = read("REST-LICENSE")
    lock = {
        "format": "vgi-github-generation-sources",
        "version": 1,
        "rest_revision": metadata["rest_revision"],
        "graphql_revision": metadata["graphql_revision"],
        "upstream": [originals[name] for name in sorted(used)],
        "products": products,
        "snapshots": [
            {"path": path, "sha256": digest(content.encode())} for path, content in sorted(files.items())
        ],
        "selection": {
            "rest_operation_ids": sorted(e["transport"]["operation_id"] for e in rest),
            "graphql_field_paths": [e["transport"]["field_path"] for e in graphql],
        },
        "modifications": "REST: selected GET paths with complete local reference closure. "
        "GraphQL: selected output fields, common interface fields and explicitly narrowed implementations, "
        "with full input/scalar/enum closure; unselected implementations and vendor directives omitted. "
        "API inventory: all REST GET contracts for both products and the full query-reachable "
        "GraphQL type graph, including abstract variants and upstream schema diagnostics. "
        "No generated metrics are inferred from upstream schemas.",
    }
    files["generation/sources.lock.json"] = json_text(lock)
    return files


def locked_inputs(root, overlay):
    lock = json.loads((root / "generation/sources.lock.json").read_text())
    if lock.get("format") != "vgi-github-generation-sources" or lock.get("version") != 1:
        raise ValueError("Unsupported generated-source lock")
    paths = set()
    for snapshot in lock["snapshots"]:
        path = snapshot["path"]
        if path in paths or not path.startswith("generation/sources/") or ".." in Path(path).parts:
            raise ValueError("Invalid or duplicated selected snapshot path")
        paths.add(path)
        if digest((root / path).read_bytes()) != snapshot["sha256"]:
            raise ValueError(f"Selected schema hash mismatch: {path}")
    rest_entities = [e for e in overlay["entities"] if e["transport"]["kind"] == "rest"]
    graphql_entities = [e for e in overlay["entities"] if e["transport"]["kind"] == "graphql"]
    if (
        sorted(e["transport"]["operation_id"] for e in rest_entities)
        != lock["selection"]["rest_operation_ids"]
    ):
        raise ValueError("Overlay REST coverage differs from selected source lock")
    if [e["transport"]["field_path"] for e in graphql_entities] != lock["selection"]["graphql_field_paths"]:
        raise ValueError("Overlay GraphQL coverage differs from selected source lock")
    expected = {f"generation/sources/{product}.selected.json" for product in lock["products"]}
    expected.update(
        {
            "generation/sources/api-inventory.json",
            "generation/sources/REST-LICENSE",
            "generation/sources/GRAPHQL-LICENSE",
        }
    )
    if graphql_entities:
        expected.update({"generation/sources/selected.graphql", "generation/sources/GRAPHQL-LICENSE"})
    if rest_entities:
        expected.add("generation/sources/REST-LICENSE")
    if paths != expected:
        raise ValueError("Selected source lock does not exactly cover schema and license inputs")
    specs = {
        product: json.loads((root / f"generation/sources/{product}.selected.json").read_text())
        for product in lock["products"]
    }
    sdl = (root / "generation/sources/selected.graphql").read_text() if graphql_entities else ""
    return specs, sdl, lock


def locked_inventory(root, lock):
    inventory = json.loads((root / "generation/sources/api-inventory.json").read_text())
    if (
        inventory["rest_manifest_sha256"] != digest((root / "vgi_github/rest_manifest.json").read_bytes())
        or inventory["rest_revision"] != lock["rest_revision"]
        or inventory["graphql_revision"] != lock["graphql_revision"]
    ):
        raise ValueError("Full API inventory is stale relative to the pinned source contracts")
    return inventory


def write_outputs(root, files, check):
    stale = []
    for name, content in files.items():
        path = root / name
        if check:
            if not path.is_file() or path.read_text() != content:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(content)
            temporary.replace(path)
    if stale:
        raise ValueError("Generated artifacts are stale: " + ", ".join(stale))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--list-outputs", action="store_true", help="List generated paths without writing files"
    )
    parser.add_argument(
        "--extract-sources", type=Path, help="Extract selected schemas from a pinned full cache"
    )
    parser.add_argument(
        "--verify-source-cache", type=Path, help="Check selected extraction against a pinned full cache"
    )
    args = parser.parse_args()
    if args.extract_sources and (args.check or args.verify_source_cache):
        parser.error("--extract-sources cannot be combined with a check mode")
    if args.list_outputs and (args.check or args.extract_sources or args.verify_source_cache):
        parser.error("--list-outputs cannot be combined with extraction or check modes")
    overlay = load_overlay(ROOT / "generation/pilot.json")
    overlay_data = overlay_bytes(overlay)
    if args.extract_sources:
        write_outputs(ROOT, extract_sources(args.extract_sources, overlay), False)
    if args.verify_source_cache:
        write_outputs(ROOT, extract_sources(args.verify_source_cache, overlay), True)
    specs, sdl, lock = locked_inputs(ROOT, overlay)
    contract = compile_contract(specs, sdl, overlay)
    provenance = {
        "overlay_sha256": digest(overlay_data),
        "source_lock_sha256": digest((ROOT / "generation/sources.lock.json").read_bytes()),
        "rest_revision": lock["rest_revision"],
        "graphql_revision": lock["graphql_revision"],
    }
    outputs = emit_artifacts(
        contract,
        overlay,
        provenance,
        api_inventory=locked_inventory(ROOT, lock),
        selected_sdl=sdl,
        coverage_policy=json.loads((ROOT / "generation/coverage-policy.json").read_text()),
    )
    if args.list_outputs:
        print(
            "\n".join(
                sorted(
                    set(outputs)
                    | {snapshot["path"] for snapshot in lock["snapshots"]}
                    | {"generation/sources.lock.json"}
                )
            )
        )
        return
    write_outputs(ROOT, outputs, args.check or bool(args.verify_source_cache))
    print(
        f"{'Checked' if args.check or args.verify_source_cache else 'Generated'} {len(outputs)} artifacts "
        f"for {len(contract.get('functions', contract['entities']))} public entities "
        f"and {len(contract['entities'])} schema-derived sources"
    )


if __name__ == "__main__":
    main()
