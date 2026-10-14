"""Rebuild the read-only operation manifest from pinned official GitHub OpenAPI files.

Usage: python scripts/generate_rest_catalog.py [--check | --check-upstream | --revision latest]
Only the generator downloads specifications; importing the worker never does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

from vgi_github.generation.schema import closure_hash

PRODUCTS = ("api.github.com", "ghec")
OUTPUT = Path(__file__).resolve().parents[1] / "vgi_github" / "rest_manifest.json"


def resolve(spec: dict, value: dict) -> dict:
    seen = set()
    while "$ref" in value:
        ref = value["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"External reference: {ref}")
        if ref in seen:
            raise ValueError(f"Circular reference: {ref}")
        seen.add(ref)
        value = spec
        for part in ref[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def resolve_revision(revision: str) -> str:
    """Resolve latest once, so both products come from the same immutable commit."""
    if revision == "latest":
        request = urllib.request.Request(
            "https://api.github.com/repos/github/rest-api-description/commits/main",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "vgi-github-catalog-check"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            revision = json.load(response)["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("revision must be a full commit SHA or 'latest'")
    return revision


def build(source_dir: Path | None = None, *, revision: str, api_version: str) -> dict:
    operations: dict[str, dict] = {}
    product_parameters: dict[str, dict[str, list]] = {}
    sources = []
    for product in PRODUCTS:
        url = (
            f"https://raw.githubusercontent.com/github/rest-api-description/{revision}/"
            f"descriptions/{product}/{product}.json"
        )
        if source_dir:
            data = (source_dir / f"{product}.json").read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        spec = json.loads(data)
        count = 0
        for path, item in sorted(spec["paths"].items()):
            if "get" not in item:
                continue
            count += 1
            operation = item["get"]
            identity = operation["operationId"]
            parameters = {}
            for raw in [*item.get("parameters", []), *operation.get("parameters", [])]:
                parameter = resolve(spec, raw)
                parameters[parameter["in"], parameter["name"]] = {
                    key: value for key, value in parameter.items() if key != "examples"
                }
                if "schema" in parameter:
                    parameters[parameter["in"], parameter["name"]]["schema"] = resolve(
                        spec, parameter["schema"]
                    )
            # GHEC has the superset of the shared operations' parameters.
            existing = operations.get(identity)
            if existing and existing["path"] != path:
                raise ValueError(f"Operation {identity} has conflicting paths")
            product_parameters.setdefault(identity, {})[product] = list(parameters.values())
            operations[identity] = {
                "operation_id": identity,
                "function_name": re.sub(r"[^a-z0-9_]", "_", identity.lower()),
                "method": "GET",
                "path": path,
                "summary": operation["summary"],
                "description": operation.get("description", ""),
                "category": operation.get("tags", [identity.split("/")[0]])[0],
                "documentation_url": operation.get("externalDocs", {}).get("url", ""),
                "parameters": list(parameters.values()),
                "response_schema_sha256": {
                    **(existing["response_schema_sha256"] if existing else {}),
                    product: closure_hash(spec, operation.get("responses", {})),
                },
                "products": [*(existing["products"] if existing else []), product],
                "deprecated": operation.get("deprecated", False),
            }
        sources.append(
            {
                "product": product,
                "url": url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "get_operations": count,
            }
        )
    # The existing parameters list remains the canonical runtime contract. Product
    # entries override that list only where it differs, avoiding duplicate copies.
    for identity, variants in product_parameters.items():
        canonical = operations[identity]["parameters"]
        overrides = {product: value for product, value in variants.items() if value != canonical}
        if overrides:
            operations[identity]["parameters_by_product"] = overrides
    names = [op["function_name"] for op in operations.values()]
    if len(names) != len(set(names)):
        raise ValueError("Generated function names collide")
    return {
        "revision": revision,
        "api_version": api_version,
        "sources": sources,
        "operations": [operations[key] for key in sorted(operations)],
    }


def operation_diff(before: dict, after: dict) -> dict[str, list[str]]:
    """Compare the generated read surface, ignoring source hashes and commit-only changes."""
    old = {op["operation_id"]: op for op in before["operations"]}
    new = {op["operation_id"]: op for op in after["operations"]}
    return {
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "changed": sorted(key for key in old.keys() & new.keys() if old[key] != new[key]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Verify the pinned catalog without writing")
    mode.add_argument(
        "--check-upstream", action="store_true", help="Fail on upstream GET coverage drift; no writes"
    )
    parser.add_argument(
        "--revision", help="Commit SHA or latest; regenerates the local catalog unless checking"
    )
    parser.add_argument(
        "--api-version", help="Explicitly change the request API version after reviewing GitHub's changes"
    )
    args = parser.parse_args()
    if args.check_upstream and (args.source_dir or args.revision or args.api_version):
        parser.error(
            "--check-upstream cannot be combined with local sources, revision or API version overrides"
        )
    current = json.loads(OUTPUT.read_text())
    revision = resolve_revision("latest" if args.check_upstream else args.revision or current["revision"])
    updated = build(
        args.source_dir, revision=revision, api_version=args.api_version or current["api_version"]
    )
    delta = operation_diff(current, updated)
    if args.check_upstream or args.revision:
        print(f"REST catalog: {current['revision']} -> {revision}")
        for kind, operations in delta.items():
            print(f"{kind}: {len(operations)}")
            for operation in operations:
                print(f"  {operation}")
    if args.check_upstream:
        if any(delta.values()):
            raise SystemExit("Upstream GET coverage changed; run --revision latest, review the diff and test")
        print("No upstream GET coverage changes")
        return
    result = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if OUTPUT.read_text() != result:
            raise SystemExit("REST catalog is stale; regenerate it")
    else:
        OUTPUT.write_text(result)


if __name__ == "__main__":
    main()
