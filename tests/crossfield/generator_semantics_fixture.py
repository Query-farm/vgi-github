"""Generate native-contract proof packages; SQLLogicTest owns execution/comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.generate_semantic_catalog import locked_inputs  # noqa: E402
from vgi_github.generation.artifacts import emit_artifacts  # noqa: E402
from vgi_github.generation.overlay import load_overlay, overlay_bytes  # noqa: E402
from vgi_github.generation.schema import compile_contract  # noqa: E402


def proof_overlay(overlay):
    result = deepcopy(overlay)
    proof = json.loads(Path(__file__).with_name("generator_semantics.overlay.json").read_text())
    entity = next(item for item in result["functions"] if item["name"] == proof["entity"])
    for key in ("dimensions", "detail_fields"):
        entity["semantics"][key] += proof[key]
    entity["semantics"]["crossfield"] = proof["crossfield"]
    return result


def fixture_packages():
    overlay = proof_overlay(load_overlay(ROOT / "generation/pilot.json"))
    specs, sdl, lock = locked_inputs(ROOT, overlay)
    contract = compile_contract(specs, sdl, overlay)
    provenance = {
        "overlay_sha256": hashlib.sha256(overlay_bytes(overlay)).hexdigest(),
        "source_lock_sha256": hashlib.sha256(
            (ROOT / "generation/sources.lock.json").read_bytes()
        ).hexdigest(),
        "rest_revision": lock["rest_revision"],
        "graphql_revision": lock["graphql_revision"],
    }
    output = {}
    for name in ("accepted", "bad-expression", "bad-policy", "bad-reference"):
        case = deepcopy(contract)
        entity = next(item for item in case["functions"] if item["name"] == "authored_pull_requests")
        native = entity["semantics"]["crossfield"]
        if name == "bad-expression":
            native["metrics"]["proof_p90_merge_hours"]["expression"] = "SUM("
        elif name == "bad-reference":
            native["fields"]["proof_title_lower"]["expression"] = (
                "LOWER(authored_pull_requests.no_such_field)"
            )
        elif name == "bad-policy":
            native["metric_semantics"]["proof_p90_merge_hours"]["missing"] = "invented"
        output[name + ".package.json"] = emit_artifacts(case, overlay, provenance)[
            "models/generated-pilot/github-generated.package.json"
        ]
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "logs/generated-semantic-fixtures")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in fixture_packages().items():
        (args.output_dir / name).write_text(content)
    print(f"Generated four native definition proof packages in {args.output_dir}")


if __name__ == "__main__":
    main()
