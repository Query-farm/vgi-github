"""Emit an isolated typed-overload slice; never rewrite the generated model.

The canonical source descriptors, fields, metric expressions and relationship
are copied from the current generated model. Only public retrieval signatures
are authored here. SQLLogicTest owns execution and independent expectations.
The retained full provider signatures bind every unexposed input to typed NULL;
they are not shortened to match this pilot's small public API.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASETS = {"pull_requests", "repositories"}
METRICS = {"pull_request_count", "merged_prs", "median_merge_hours", "repository_count"}
RELATIONSHIP = "pull_requests_to_repositories"


def selected_field(name):
    return name.split(".", 1)[0] in DATASETS


def fixture_model():
    original = json.loads((ROOT / "models/generated-pilot/github-generated.crossfield.json").read_text())
    sources = {
        name: deepcopy(source)
        for name, source in original["invocations"]["sources"].items()
        if source["dataset"]["name"] in DATASETS
    }
    assert set(sources) == DATASETS, "The pilot needs the two canonical generated source descriptors"
    policy = original["policy"]
    model = {
        "crossfield": original["crossfield"],
        "id": "queryfarm.github.fixture/typed-overloads",
        "name": "github",
        "invocations": {"version": 1, "sources": sources, "input_contracts": {}},
        "metrics": {name: deepcopy(original["metrics"][name]) for name in sorted(METRICS)},
        "relationships": [deepcopy(item) for item in original["relationships"] if item["name"] == RELATIONSHIP],
        "policy": {
            "policy_version": policy["policy_version"],
            "timezone": policy["timezone"],
            "allow_semantic_joins": policy["allow_semantic_joins"],
            "metrics": sorted(METRICS),
            "metric_semantics": {name: deepcopy(policy["metric_semantics"][name]) for name in sorted(METRICS)},
            "invocation_sources": sorted(DATASETS),
            "relationships": [RELATIONSHIP],
            "relationship_semantics": {RELATIONSHIP: deepcopy(policy["relationship_semantics"][RELATIONSHIP])},
            "dataset_semantics": {name: deepcopy(policy["dataset_semantics"][name]) for name in sorted(DATASETS)},
        },
    }
    for key in ("dimensions", "filter_dimensions", "detail_fields"):
        model["policy"][key] = [name for name in policy[key] if selected_field(name)]
    for key in ("field_semantics", "local_time_fields"):
        model["policy"][key] = {name: deepcopy(value) for name, value in policy.get(key, {}).items() if selected_field(name)}

    overloads = []
    for scope, calling, example in (("repository", "positional_or_named", "example/alpha"),
                                    ("organization", "keyword_only", "example")):
        exposed = {scope, "user"}
        bindings = {}
        for name, source in sources.items():
            arguments = {}
            for argument in source["function"]["arguments"]:
                key = argument["id"]
                if key in exposed:
                    arguments[key] = {"parameter": key}
                else:
                    assert argument["nullable"], f"New required physical argument needs explicit pilot meaning: {name}.{key}"
                    arguments[key] = {"literal": None}
            bindings[source["dataset"]["name"]] = {"arguments": arguments}
        overloads.append({
            "id": scope,
            "comment": f"Canonical repositories and PRs selected by {scope}; optional user intersects the PR authors.",
            "parameters": [
                {"name": scope, "type": "VARCHAR", "calling": calling, "nullable": False,
                 "non_empty": True, "example": example},
                {"name": "user", "type": "VARCHAR", "calling": "keyword_only", "nullable": True,
                 "default": None, "non_empty": True, "example": "alice"},
            ],
            "request": {"version": 1, "source_bindings": bindings},
        })
    model["semantic_query"] = {"overloads": overloads}
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / "github-overloads.crossfield.json"
    target.write_text(json.dumps(fixture_model(), indent=2, sort_keys=True) + "\n")
    print(f"Generated isolated overload fixture: {target}")


if __name__ == "__main__":
    main()
