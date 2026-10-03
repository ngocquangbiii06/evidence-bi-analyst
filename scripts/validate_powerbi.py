"""Offline Power BI schema, model/report reference, and static parity checks."""

import argparse
import base64
import binascii
import copy
import json
import re
import uuid
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _duplicate_semantic_table_names(tables: list[dict]) -> list[str]:
    seen = set()
    duplicates = set()
    for table in tables:
        name = table.get("name")
        if not isinstance(name, str):
            continue
        folded = name.casefold()
        if folded in seen:
            duplicates.add(name)
        seen.add(folded)
    return sorted(duplicates, key=str.casefold)


def validate_project(project: Path) -> dict:
    """Validate Microsoft JSON schemas only; this does not execute DAX or render."""
    root = Path(__file__).resolve().parents[1] / "vendor" / "microsoft-schemas"
    base = "https://developer.microsoft.com/json-schemas/"
    resources = []
    for path in root.rglob("*.json"):
        data = _read_json(path)
        resources.append((base + path.relative_to(root).as_posix(), Resource.from_contents(data)))
    registry = Registry().with_resources(resources)
    checked = []
    failures = []
    for path in sorted(project.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".pbip", ".pbir", ".pbism"}:
            continue
        data = _read_json(path)
        if not isinstance(data, dict) or "$schema" not in data:
            continue
        validator = Draft7Validator({"$ref": data["$schema"]}, registry=registry)
        errors = list(validator.iter_errors(data))
        checked.append(str(path.relative_to(project)))
        for error in errors:
            failures.append(
                {
                    "file": str(path.relative_to(project)),
                    "path": "/".join(map(str, error.absolute_path)),
                    "message": error.message,
                }
            )
    return {
        "schema_files_checked": len(checked),
        "files": checked,
        "failures": failures,
        "scope": "JSON schema only; DAX execution and rendering not checked",
    }


def validate_references(project: Path) -> dict:
    """Check actual DAX and visual bindings against the exported model catalog."""
    failures = []
    model_path = project / "EvidenceBI.SemanticModel/model.bim"
    model = _read_json(model_path)
    tables = model["model"]["tables"]
    duplicate_names = _duplicate_semantic_table_names(tables)
    if duplicate_names:
        return {
            "failures": [f"duplicate semantic table name: {name}" for name in duplicate_names],
            "tables": len(tables),
            "relationships": len(model["model"].get("relationships", [])),
            "measures": sum(len(table.get("measures", [])) for table in tables),
            "visual_bindings_checked": 0,
            "scope": "duplicate model names rejected before reference catalog construction",
        }
    table_names = {table["name"] for table in tables}
    columns = {
        table["name"]: {column["name"] for column in table.get("columns", [])} for table in tables
    }
    measures = {
        table["name"]: {measure["name"] for measure in table.get("measures", [])}
        for table in tables
    }
    all_measure_names = {name for names in measures.values() for name in names}
    for relation in model["model"].get("relationships", []):
        for side in ("from", "to"):
            table_name = relation.get(side + "Table")
            column_name = relation.get(side + "Column")
            if table_name not in columns or column_name not in columns[table_name]:
                failures.append(
                    f"relationship {relation.get('name')} has unresolved {side} endpoint "
                    f"{table_name}[{column_name}]"
                )

    qualified_ref = re.compile(r"'([^']+)'\[([^\]]+)\]|(?<!['\w])([A-Za-z_][\w ]*)\[([^\]]+)\]")
    unqualified_measure_ref = re.compile(r"(?<!['A-Za-z0-9_\]])\[([^\]]+)\]")
    for table in tables:
        for measure in table.get("measures", []):
            expression = measure.get("expression", "")
            for name in re.findall(r"'([^']+)'", expression):
                if name not in table_names:
                    failures.append(f"measure {table['name']}[{measure['name']}] references unknown table {name!r}")
            for match in qualified_ref.finditer(expression):
                entity = match.group(1) or match.group(3).strip()
                member = match.group(2) or match.group(4)
                if entity not in table_names:
                    failures.append(
                        f"measure {table['name']}[{measure['name']}] references unknown table {entity!r}"
                    )
                elif member not in columns[entity] and member not in measures[entity]:
                    failures.append(
                        f"measure {table['name']}[{measure['name']}] references unknown member {entity}[{member}]"
                    )
            for match in unqualified_measure_ref.finditer(expression):
                member = match.group(1)
                prefix = expression[: match.start()]
                if prefix.endswith("'") or (prefix and prefix[-1].isalnum()):
                    continue
                if member not in all_measure_names:
                    failures.append(
                        f"measure {table['name']}[{measure['name']}] references unknown measure [{member}]"
                    )

    report_definition = project / "EvidenceBI.Report/definition"
    pages = _read_json(report_definition / "pages/pages.json")
    for page_id in pages.get("pageOrder", []):
        page_dir = report_definition / "pages" / page_id
        page = _read_json(page_dir / "page.json")
        if page.get("name") != page_id:
            failures.append(f"page folder/name mismatch for {page_id}")
        for visual_file in sorted((page_dir / "visuals").glob("*/visual.json")):
            visual_id = visual_file.parent.name
            visual = _read_json(visual_file)
            if visual.get("name") != visual_id:
                failures.append(f"visual folder/name mismatch for {visual_id}")
            for role_name, role in visual.get("visual", {}).get("query", {}).get("queryState", {}).items():
                for projection in role.get("projections", []):
                    field = projection.get("field", {})
                    member_type = "Measure" if "Measure" in field else "Column" if "Column" in field else None
                    if member_type is None:
                        failures.append(f"visual {visual_id} role {role_name} has unsupported field binding")
                        continue
                    binding = field[member_type]
                    entity = binding.get("Expression", {}).get("SourceRef", {}).get("Entity")
                    member = binding.get("Property")
                    catalog = measures if member_type == "Measure" else columns
                    if entity not in catalog or member not in catalog.get(entity, set()):
                        failures.append(
                            f"visual {visual_id} binds {member_type.lower()} {entity}[{member}] outside the model"
                        )
    return {
        "failures": failures,
        "tables": len(tables),
        "relationships": len(model["model"].get("relationships", [])),
        "measures": sum(len(table.get("measures", [])) for table in tables),
        "visual_bindings_checked": sum(
            1
            for visual in (report_definition / "pages").glob("*/visuals/*/visual.json")
            for _ in _read_json(visual)
                .get("visual", {})
                .get("query", {})
                .get("queryState", {})
                .values()
        ),
        "scope": "model references and report bindings only; DAX execution not checked",
    }


def _static_signature(project: Path) -> dict:
    report_root = project / "EvidenceBI.Report"
    definition = report_root / "definition"
    pages_doc = _read_json(definition / "pages/pages.json")
    pages = []
    visuals = []
    for page_id in pages_doc["pageOrder"]:
        page = _read_json(definition / "pages" / page_id / "page.json")
        pages.append(
            {
                "id": page_id,
                "page": {key: page.get(key) for key in ("name", "displayName", "displayOption", "width", "height")},
            }
        )
        page_dir = definition / "pages" / page_id
        for path in sorted((page_dir / "visuals").glob("*/visual.json")):
            visual = _read_json(path)
            content = visual.get("visual", {})
            visuals.append(
                {
                    "page_id": page_id,
                    "id": path.parent.name,
                    "name": visual.get("name"),
                    "type": content.get("visualType"),
                    "position": visual.get("position"),
                    "bindings": content.get("query", {}).get("queryState", {}),
                }
            )
    model = _read_json(project / "EvidenceBI.SemanticModel/model.bim")["model"]
    tables = []
    dax_templates = []
    for table in model["tables"]:
        tables.append(
            {
                "name": table["name"],
                "columns": [
                    (column.get("name"), column.get("dataType")) for column in table.get("columns", [])
                ],
            }
        )
        for measure in table.get("measures", []):
            dax_templates.append(
                (table["name"], measure.get("name"), measure.get("expression"), measure.get("formatString"))
            )
    platform = _read_json(report_root / ".platform")
    logical_id = platform.get("config", {}).get("logicalId")
    try:
        uuid.UUID(logical_id)
    except (TypeError, ValueError, AttributeError):
        logical_id = "invalid"
    return {
        "pbir": _read_json(report_root / "definition.pbir"),
        "definition_version": _read_json(definition / "version.json"),
        "platform": {
            "$schema": platform.get("$schema"),
            "metadata": platform.get("metadata"),
            "version": platform.get("config", {}).get("version"),
            "logical_id_valid": logical_id != "invalid",
        },
        "page_order": pages_doc.get("pageOrder"),
        "active_page": pages_doc.get("activePageName"),
        "pages": pages,
        "visuals": visuals,
        "tables": tables,
        "relationships": model.get("relationships", []),
        "dax_templates": dax_templates,
    }


def compare_powerbi_projects(baseline: Path, candidate: Path) -> dict:
    """Compare frozen PBIR identity/layout/bindings and static model/DAX templates."""
    expected = _static_signature(baseline)
    actual = _static_signature(candidate)
    duplicate_failures = [
        f"{side} contains duplicate semantic table name {name!r}"
        for side, signature in (("baseline", expected), ("candidate", actual))
        for name in _duplicate_semantic_table_names(signature["tables"])
    ]
    if duplicate_failures:
        return {
            "baseline": str(baseline),
            "candidate": str(candidate),
            "pages": len(actual["pages"] or []),
            "visuals": len(actual["visuals"] or []),
            "failures": duplicate_failures,
            "scope": "static parity rejected duplicate semantic table names before catalog comparison",
        }
    failures = []
    expected_tables = {table["name"]: table["columns"] for table in expected["tables"]}
    actual_tables = {table["name"]: table["columns"] for table in actual["tables"]}
    table_shapes_match = set(expected_tables) == set(actual_tables)
    if table_shapes_match:
        for name, old_columns in expected_tables.items():
            new_columns = actual_tables[name]
            if name == "Evidence":
                # T14 intentionally added accepted-artifact scope/validation evidence
                # columns while preserving the prior catalog exactly.
                allowed_additions = {"ScopeJSON", "ValidationJSON"}
                projected_columns = [
                    column for column in new_columns if column[0] not in allowed_additions
                ]
                additions = [column for column in new_columns if column[0] in allowed_additions]
                addition_names = {column[0] for column in additions}
                additions_are_exact_strings = (
                    len(additions) == len(allowed_additions)
                    and addition_names == allowed_additions
                    and all(column[1] == "string" for column in additions)
                )
                if projected_columns != old_columns or not additions_are_exact_strings:
                    table_shapes_match = False
            elif old_columns != new_columns:
                table_shapes_match = False
    for key, label in (
        ("pbir", "PBIR definition/version/dataset reference"),
        ("definition_version", "PBIR definition version"),
        ("platform", ".platform type/display/version and logical ID validity"),
        ("page_order", "page IDs/order"),
        ("active_page", "active page"),
        ("pages", "page identities and dimensions"),
        ("visuals", "visual IDs/types/positions/bindings"),
        ("relationships", "semantic relationships"),
        ("dax_templates", "DAX measure templates"),
    ):
        if expected[key] != actual[key]:
            failures.append(f"{label} differ from PowerBI_Demo_Current")
    if not table_shapes_match:
        failures.append("semantic table/column structure differs outside the accepted T14 Evidence additions")
    if len(actual["pages"] or []) != 2:
        failures.append(f"expected 2 pages, found {len(actual['pages'] or [])}")
    if len(actual["visuals"] or []) != 9:
        failures.append(f"expected 9 visuals, found {len(actual['visuals'] or [])}")
    if not actual["platform"]["logical_id_valid"]:
        failures.append("candidate .platform logicalId is not a UUID")
    return {
        "baseline": str(baseline),
        "candidate": str(candidate),
        "pages": len(actual["pages"] or []),
        "visuals": len(actual["visuals"] or []),
        "failures": failures,
        "scope": "static PBIR/model parity only; Power BI execution/rendering not checked",
    }


def compare_powerbi_projects_exact(baseline: Path, candidate: Path) -> dict:
    """Compare a generated project with a tracked post-T14 baseline exactly.

    ``compare_powerbi_projects`` intentionally projects the two T14 Evidence
    columns out of the candidate side so it can compare a pre-T14 Current
    artifact with a post-T14 candidate.  That compatibility rule is not valid
    when the public baseline is itself the post-T14 Candidate.  This checker
    keeps the full model column list and compares the PBIR identities, roles,
    layout, relationships, and DAX templates without that legacy exception.
    """
    expected = _static_signature(baseline)
    actual = _static_signature(candidate)
    duplicate_failures = [
        f"{side} contains duplicate semantic table name {name!r}"
        for side, signature in (("baseline", expected), ("candidate", actual))
        for name in _duplicate_semantic_table_names(signature["tables"])
    ]
    failures = list(duplicate_failures)
    if not duplicate_failures:
        for key, label in (
            ("pbir", "PBIR definition/version/dataset reference"),
            ("definition_version", "PBIR definition version"),
            ("platform", ".platform type/display/version and logical ID validity"),
            ("page_order", "page IDs/order"),
            ("active_page", "active page"),
            ("pages", "page identities and dimensions"),
            ("visuals", "visual IDs/types/positions/roles/bindings"),
            ("tables", "semantic model table/column schema"),
            ("relationships", "semantic relationships"),
            ("dax_templates", "DAX measure templates"),
        ):
            if expected[key] != actual[key]:
                failures.append(f"{label} differ from tracked post-T14 baseline")
    return {
        "baseline": str(baseline),
        "candidate": str(candidate),
        "pages": len(actual["pages"] or []),
        "visuals": len(actual["visuals"] or []),
        "failures": failures,
        "scope": (
            "exact static PBIR/model parity against tracked post-T14 baseline; "
            "Power BI execution/rendering not checked"
        ),
    }


def _visual_inventory(project: Path) -> dict[str, dict]:
    definition = project / "EvidenceBI.Report/definition"
    pages = _read_json(definition / "pages/pages.json")
    inventory = {}
    for page_id in pages["pageOrder"]:
        visual_root = definition / "pages" / page_id / "visuals"
        for path in sorted(visual_root.glob("*/visual.json")):
            document = _read_json(path)
            inventory[document["name"]] = {
                "page_id": page_id,
                "document": document,
            }
    return inventory


def _binding_name(projection: dict) -> str | None:
    field = projection.get("field", {})
    for kind in ("Column", "Measure"):
        binding = field.get(kind)
        if isinstance(binding, dict):
            entity = binding.get("Expression", {}).get("SourceRef", {}).get("Entity")
            prop = binding.get("Property")
            if isinstance(entity, str) and isinstance(prop, str):
                return f"{entity}.{prop}"
    return None


def _visual_roles(document: dict) -> dict[str, list[str | None]]:
    query_state = document.get("visual", {}).get("query", {}).get("queryState", {})
    return {
        role: [_binding_name(projection) for projection in state.get("projections", [])]
        for role, state in query_state.items()
    }


def _table_rows(table: dict) -> list[list]:
    partitions = table.get("partitions", [])
    if len(partitions) != 1:
        raise ValueError(f"table {table.get('name')} does not have exactly one partition")
    expression = partitions[0].get("source", {}).get("expression")
    if not isinstance(expression, list):
        raise ValueError(f"table {table.get('name')} does not have a generated M expression")
    match = re.search(
        r'Binary\.FromText\("([A-Za-z0-9+/=]+)"',
        "\n".join(str(line) for line in expression),
    )
    if match is None:
        raise ValueError(f"table {table.get('name')} does not contain embedded rows")
    return json.loads(base64.b64decode(match.group(1)).decode("utf-8"))


def _m_text(value: str) -> str:
    return '"' + value.replace('"', '""').replace("#(", "#(#)(") + '"'


def _generated_table_expression(columns: list[dict], rows: list[list]) -> list[str]:
    """Recreate the deterministic embedded-table M expression for comparison."""
    m_types = {"string": "type text", "int64": "Int64.Type", "dateTime": "type date"}
    try:
        names = "{" + ", ".join(_m_text(column["name"]) for column in columns) + "}"
        types = (
            "{"
            + ", ".join(
                "{" + _m_text(column["name"]) + ", " + m_types[column["dataType"]] + "}"
                for column in columns
            )
            + "}"
        )
    except (KeyError, TypeError) as error:
        raise ValueError("embedded table has unsupported column metadata") from error
    encoded = base64.b64encode(
        json.dumps(
            rows,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).decode()
    return [
        "let",
        f'    Rows = Json.Document(Binary.FromText("{encoded}", BinaryEncoding.Base64)),',
        f"    Source = Table.FromRows(Rows, {names}),",
        f'    Typed = Table.TransformColumnTypes(Source, {types}, "en-US")',
        "in",
        "    Typed",
    ]


def _scope_label_from_evidence(candidate: dict, root_scope: dict) -> str:
    scope = candidate["scope"]

    def display(value):
        if value is None:
            return "(Thiếu giá trị)"
        if value == "":
            return "(Chuỗi rỗng)"
        return str(value)

    filters = scope.get("filters", {})
    if filters:
        filter_text = "; ".join(
            f"{display(dimension)} = " + ", ".join(display(value) for value in values)
            for dimension, values in sorted(filters.items())
        )
    else:
        filter_text = "Tất cả trong phạm vi dữ liệu đã xuất"
    parts = [
        f"Chỉ số: {display(scope.get('metric_id'))} | Đơn vị: {display(scope.get('unit'))} "
        f"| Scale: {scope.get('scale')}",
        f"Kỳ trước: [{scope['previous']['start']}, {scope['previous']['end']})",
        f"Kỳ hiện tại: [{scope['current']['start']}, {scope['current']['end']})",
        f"Bộ lọc: {filter_text}",
        (
            "Phạm vi gốc"
            if json.dumps(scope, sort_keys=True, separators=(",", ":"))
            == json.dumps(root_scope, sort_keys=True, separators=(",", ":"))
            else "Phạm vi finding đã xác thực"
        ),
    ]
    if scope.get("dimension") is not None:
        parts.append(
            f"Nhóm: {display(scope['dimension'])} = {display(candidate.get('label'))}"
        )
    return "\n".join(parts)


def _rectangles_overlap(first: dict, second: dict) -> bool:
    return not (
        first["x"] + first["width"] <= second["x"]
        or second["x"] + second["width"] <= first["x"]
        or first["y"] + first["height"] <= second["y"]
        or second["y"] + second["height"] <= first["y"]
    )


def _interaction_contract_failures(
    raw_interactions: object,
    required_sources: set[str],
    required_targets: set[str],
    required_type: str | None,
) -> list[str]:
    """Validate exact static interaction coverage independently of map size."""

    if not isinstance(raw_interactions, list):
        return ["overview visualInteractions is missing or not a list"]
    if not required_type:
        return ["interaction contract is missing filter type"]
    expected_pairs = {
        (source, target, required_type)
        for source in required_sources
        for target in required_targets
        if source != target
    }
    actual_pairs: list[tuple[object, object, object]] = []
    failures: list[str] = []
    for item in raw_interactions:
        if not isinstance(item, dict):
            failures.append("overview visualInteractions contains a non-object")
            continue
        actual_pairs.append((item.get("source"), item.get("target"), item.get("type")))
    if len(actual_pairs) != len(set(actual_pairs)):
        failures.append("overview visualInteractions contains duplicate pairs")
    actual_set = set(actual_pairs)
    if actual_set != expected_pairs:
        missing = expected_pairs - actual_set
        unexpected = actual_set - expected_pairs
        failures.append(
            "overview visualInteractions does not match the exact contract "
            f"(missing={len(missing)}, unexpected={len(unexpected)})"
        )
    return failures


def compare_powerbi_projects_refresh(
    baseline: Path,
    candidate: Path,
    *,
    layout_manifest: Path | None = None,
) -> dict:
    """Validate the explicit dashboard-refresh presentation allowlist.

    The v1 exact comparator remains unchanged. This v2 comparator admits only
    the locked report-presentation changes, the exact Evidence.ScopeLabel
    column/values, and the current authoritative-artifact fingerprint in the
    otherwise frozen AnalysisInfo table. All other semantic-model structure
    remains byte-for-byte equivalent after those normalizations. It does not
    execute DAX, exercise interactions, or render in Desktop.
    """
    manifest_path = layout_manifest or (
        Path(__file__).resolve().parents[1]
        / "docs/design/dashboard_refresh_layout.json"
    )
    manifest = _read_json(manifest_path)
    expected = _static_signature(baseline)
    actual = _static_signature(candidate)
    failures = []

    for key, label in (
        ("pbir", "PBIR definition/version/dataset reference"),
        ("definition_version", "PBIR definition version"),
        ("platform", ".platform type/display/version and logical ID validity"),
        ("page_order", "page IDs/order"),
        ("active_page", "active page"),
        ("relationships", "semantic relationships"),
        ("dax_templates", "DAX measure templates"),
    ):
        if expected[key] != actual[key]:
            failures.append(f"{label} differ outside the dashboard-refresh allowlist")

    expected_pages = [
        {
            "id": page["id"],
            "page": {
                "name": page["id"],
                "displayName": page["display_name"],
                "displayOption": "FitToPage",
                "width": manifest["canvas"]["width"],
                "height": manifest["canvas"]["height"],
            },
        }
        for page in manifest["pages"]
    ]
    if actual["pages"] != expected_pages:
        failures.append("page identities, names, order, or dimensions differ from the manifest")

    candidate_artifact_fingerprint = None
    try:
        fingerprint_sources = {
            "evidence.json": _read_json(candidate / "evidence.json")[
                "validated_analysis_fingerprint"
            ],
            "export_manifest.json": _read_json(candidate / "export_manifest.json")[
                "validated_analysis_fingerprint"
            ],
            "bi_spec.json": _read_json(candidate / "bi_spec.json")["analysis_artifact"][
                "fingerprint"
            ],
            "business_case_summary.json": _read_json(
                candidate / "business_case_summary.json"
            )["analysis_artifact_fingerprint"],
        }
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        failures.append(f"authoritative artifact fingerprint metadata cannot be checked: {error}")
    else:
        fingerprint_values = list(fingerprint_sources.values())
        if not all(isinstance(value, str) and value for value in fingerprint_values):
            failures.append("authoritative artifact fingerprint metadata is missing or invalid")
        elif len(set(fingerprint_values)) != 1:
            failures.append(
                "authoritative artifact fingerprint metadata disagrees across exported files"
            )
        else:
            candidate_artifact_fingerprint = fingerprint_values[0]

    baseline_model = _read_json(baseline / "EvidenceBI.SemanticModel/model.bim")["model"]
    candidate_model = _read_json(candidate / "EvidenceBI.SemanticModel/model.bim")["model"]
    normalized_model = copy.deepcopy(candidate_model)
    baseline_table_list = baseline_model.get("tables", [])
    candidate_table_list = candidate_model.get("tables", [])
    normalized_table_list = normalized_model.get("tables", [])
    duplicate_names = [
        f"{side} contains duplicate semantic table name {name!r}"
        for side, tables in (
            ("baseline", baseline_table_list),
            ("candidate", candidate_table_list),
        )
        for name in _duplicate_semantic_table_names(tables)
    ]
    failures.extend(duplicate_names)
    baseline_names = [table.get("name") for table in baseline_table_list]
    candidate_names = [table.get("name") for table in candidate_table_list]
    if baseline_names != candidate_names:
        failures.append("semantic table inventory or order differs")

    if not duplicate_names and baseline_names == candidate_names and "Evidence" in baseline_names:
        evidence_index = baseline_names.index("Evidence")
        old = baseline_table_list[evidence_index]
        new = candidate_table_list[evidence_index]
        normalized = normalized_table_list[evidence_index]
        old_columns = old.get("columns", [])
        new_columns = new.get("columns", [])
        scope_indexes = [
            index
            for index, column in enumerate(new_columns)
            if column.get("name") == "ScopeLabel"
        ]
        scope_index = scope_indexes[0] if len(scope_indexes) == 1 else None
        expected_scope_column = {
            "name": "ScopeLabel",
            "dataType": "string",
            "sourceColumn": "ScopeLabel",
            "summarizeBy": "none",
        }
        normalized_columns = [
            column
            for index, column in enumerate(new_columns)
            if index != scope_index
        ]
        if (
            scope_index is None
            or new_columns[scope_index] != expected_scope_column
            or normalized_columns != old_columns
        ):
            failures.append(
                "Evidence column metadata differs outside the exact ScopeLabel:string addition"
            )
        try:
            old_rows = _table_rows(old)
            new_rows = _table_rows(new)
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            binascii.Error,
            UnicodeDecodeError,
        ) as error:
            failures.append(f"Evidence embedded rows cannot be checked: {error}")
        else:
            normalized_rows = [
                [value for index, value in enumerate(row) if index != scope_index]
                for row in new_rows
            ]
            if scope_index is None or normalized_rows != old_rows:
                failures.append("Evidence rows changed outside ScopeLabel values")
            try:
                evidence = _read_json(candidate / "evidence.json")
                expected_labels = {
                    record["candidate"]["finding_id"]: _scope_label_from_evidence(
                        record["candidate"], evidence["root_scope"]
                    )
                    for record in evidence["findings"]
                }
                finding_index = next(
                    index
                    for index, column in enumerate(new_columns)
                    if column.get("name") == "FindingID"
                )
                actual_labels = {
                    row[finding_index]: row[scope_index]
                    for row in new_rows
                }
                if actual_labels != expected_labels:
                    failures.append(
                        "Evidence.ScopeLabel values do not match candidate scope/label"
                    )
            except (
                KeyError,
                IndexError,
                StopIteration,
                TypeError,
                json.JSONDecodeError,
            ) as error:
                failures.append(f"Evidence.ScopeLabel provenance cannot be checked: {error}")
            try:
                partitions = new["partitions"]
                expression = partitions[0]["source"]["expression"]
                if len(partitions) != 1 or expression != _generated_table_expression(
                    new_columns, new_rows
                ):
                    failures.append(
                        "Evidence M expression differs outside the generated ScopeLabel addition"
                    )
            except (KeyError, IndexError, TypeError, ValueError) as error:
                failures.append(f"Evidence M expression cannot be checked: {error}")

        normalized["columns"] = copy.deepcopy(old_columns)
        try:
            normalized["partitions"][0]["source"]["expression"] = copy.deepcopy(
                old["partitions"][0]["source"]["expression"]
            )
        except (KeyError, IndexError, TypeError):
            pass

    if (
        not duplicate_names
        and baseline_names == candidate_names
        and "AnalysisInfo" in baseline_names
    ):
        info_index = baseline_names.index("AnalysisInfo")
        old_info = baseline_table_list[info_index]
        new_info = candidate_table_list[info_index]
        normalized_info = normalized_table_list[info_index]
        try:
            old_info_rows = _table_rows(old_info)
            new_info_rows = _table_rows(new_info)
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            binascii.Error,
            UnicodeDecodeError,
        ) as error:
            failures.append(f"AnalysisInfo embedded rows cannot be checked: {error}")
        else:
            old_properties = [row[0] for row in old_info_rows]
            new_properties = [row[0] for row in new_info_rows]
            fingerprint_indexes = [
                index
                for index, row in enumerate(new_info_rows)
                if len(row) == 2 and row[0] == "Validated analysis fingerprint"
            ]
            fingerprint_index = (
                fingerprint_indexes[0] if len(fingerprint_indexes) == 1 else None
            )
            normalized_info_rows = copy.deepcopy(new_info_rows)
            if old_properties != new_properties or fingerprint_index is None:
                failures.append("AnalysisInfo row inventory or order differs from v1")
            else:
                for index, (old_row, new_row) in enumerate(
                    zip(old_info_rows, new_info_rows, strict=True)
                ):
                    if index != fingerprint_index and new_row != old_row:
                        failures.append(
                            "AnalysisInfo rows/values differ outside the current artifact fingerprint"
                        )
                        break
                model_fingerprint = new_info_rows[fingerprint_index][1]
                if (
                    candidate_artifact_fingerprint is None
                    or model_fingerprint != candidate_artifact_fingerprint
                ):
                    failures.append(
                        "AnalysisInfo validated fingerprint does not match the authoritative artifact"
                    )
                normalized_info_rows[fingerprint_index][1] = old_info_rows[
                    fingerprint_index
                ][1]
            try:
                partitions = new_info["partitions"]
                expression = partitions[0]["source"]["expression"]
                if len(partitions) != 1 or expression != _generated_table_expression(
                    new_info.get("columns", []), new_info_rows
                ):
                    failures.append("AnalysisInfo M expression differs from generated rows")
            except (KeyError, IndexError, TypeError, ValueError) as error:
                failures.append(f"AnalysisInfo M expression cannot be checked: {error}")

            if fingerprint_index is not None:
                try:
                    normalized_info["partitions"][0]["source"]["expression"] = (
                        _generated_table_expression(
                            normalized_info.get("columns", []), normalized_info_rows
                        )
                    )
                except (KeyError, IndexError, TypeError, ValueError):
                    pass

    if normalized_model != baseline_model:
        failures.append(
            "semantic model structure differs outside Evidence.ScopeLabel and current artifact provenance"
        )

    try:
        old_evidence = _read_json(baseline / "evidence.json")
        new_evidence = _read_json(candidate / "evidence.json")
        for key in (
            "sufficiency_status",
            "root_scope",
            "accepted_finding_ids",
            "accepted_evidence_ids",
            "findings",
            "evidence_registry",
        ):
            if old_evidence.get(key) != new_evidence.get(key):
                failures.append(f"authoritative exported evidence field {key} changed")
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"exported evidence cannot be compared: {error}")

    baseline_visuals = _visual_inventory(baseline)
    candidate_visuals = _visual_inventory(candidate)
    expected_objects = [
        {**item, "page_id": page["id"]}
        for page in manifest["pages"]
        for item in page["objects"]
    ]
    interaction_contract = manifest.get("interactions", {})
    required_sources = set(interaction_contract.get("sources", []))
    required_targets = set(interaction_contract.get("targets", []))
    required_type = interaction_contract.get("filter_type")
    overview_id = next(
        (page["id"] for page in manifest["pages"] if page.get("key") == "overview"),
        None,
    )
    if not overview_id or not required_type:
        failures.append("interaction contract is missing overview page or filter type")
    else:
        try:
            interaction_page = _read_json(
                candidate / "EvidenceBI.Report/definition/pages" / overview_id / "page.json"
            )
            failures.extend(
                _interaction_contract_failures(
                    interaction_page.get("visualInteractions"),
                    required_sources,
                    required_targets,
                    required_type,
                )
            )
        except (OSError, json.JSONDecodeError, TypeError) as error:
            failures.append(f"overview visualInteractions cannot be checked: {error}")
    expected_ids = {item["id"] for item in expected_objects}
    if set(candidate_visuals) != expected_ids:
        failures.append("visual IDs/inventory do not match the locked refresh manifest")
    baseline_ids = set(baseline_visuals)
    data_ids = {item["id"] for item in expected_objects if item["kind"] == "data"}
    text_ids = {item["id"] for item in expected_objects if item["kind"] == "text"}
    if data_ids != baseline_ids:
        failures.append("the nine v1 data visual IDs were not preserved exactly")
    if len(data_ids) != manifest["inventory"]["data_visuals"]:
        failures.append("data visual count differs from the locked manifest")
    if len(text_ids) != manifest["inventory"]["text_objects"]:
        failures.append("text object count differs from the locked manifest")

    for item in expected_objects:
        actual_item = candidate_visuals.get(item["id"])
        if actual_item is None:
            continue
        document = actual_item["document"]
        visual = document.get("visual", {})
        if actual_item["page_id"] != item["page_id"]:
            failures.append(f"visual {item['key']} is on the wrong page")
        if visual.get("visualType") != item["type"]:
            failures.append(f"visual {item['key']} has the wrong type")
        actual_rectangle = {
            key: document.get("position", {}).get(key)
            for key in ("x", "y", "width", "height")
        }
        if actual_rectangle != item["rectangle"]:
            failures.append(f"visual {item['key']} has the wrong rectangle")
        if _visual_roles(document) != item["roles"]:
            failures.append(f"visual {item['key']} has roles/bindings outside the manifest")
        if item["kind"] == "text" and "query" in visual:
            failures.append(f"text object {item['key']} unexpectedly has a query")

    for page in manifest["pages"]:
        objects = page["objects"]
        for item in objects:
            rectangle = item["rectangle"]
            if (
                rectangle["x"] < 0
                or rectangle["y"] < 0
                or rectangle["x"] + rectangle["width"] > manifest["canvas"]["width"]
                or rectangle["y"] + rectangle["height"] > manifest["canvas"]["height"]
            ):
                failures.append(f"visual {item['key']} exceeds the page bounds")
        for index, first in enumerate(objects):
            for second in objects[index + 1 :]:
                if _rectangles_overlap(first["rectangle"], second["rectangle"]):
                    failures.append(
                        f"visual rectangles overlap on {page['key']}: {first['key']}/{second['key']}"
                    )

    scope_id = next(
        (item["id"] for item in expected_objects if item["key"] == "S01"), None
    )
    for visual_id in baseline_ids & set(candidate_visuals):
        old_document = baseline_visuals[visual_id]["document"]
        new_document = candidate_visuals[visual_id]["document"]
        old_roles = _visual_roles(old_document)
        new_roles = _visual_roles(new_document)
        finding_id = next(
            (item["id"] for item in expected_objects if item["key"] == "E01"), None
        )
        if visual_id == finding_id:
            expected_roles = {
                "Values": [
                    "Evidence.FindingID",
                    "Evidence.Finding",
                    "Evidence.ScopeLabel",
                    "Evidence.Status",
                ]
            }
            if new_roles != expected_roles:
                failures.append("E01 projection differs outside EvidenceID-to-ScopeLabel")
        elif old_roles != new_roles:
            failures.append(f"data visual {visual_id} changed query roles/bindings")
        # The refresh contract intentionally changes the legacy default from
        # cross-filtering to NoFilter.  Keep this allowlisted change narrow:
        # every data visual must explicitly disable drill filtering.
        if new_document.get("visual", {}).get("drillFilterOtherVisuals") is not False:
            failures.append(
                f"data visual {visual_id} does not disable drill interaction behavior"
            )
        if visual_id == scope_id:
            try:
                scope_filter = new_document["filterConfig"]["filters"][0]
                inversion = scope_filter["objects"]["general"][0]["properties"]
                inversion = inversion["isInvertedSelectionMode"]["expr"]["Literal"]["Value"]
                excluded = {
                    value[0]["Literal"]["Value"]
                    for value in scope_filter["filter"]["Where"][0]["Condition"]["Not"]
                    ["Expression"]["In"]["Values"]
                }
            except (IndexError, KeyError, TypeError):
                failures.append("S01 lacks the locked technical-row exclusion filter")
            else:
                if inversion != "true" or excluded != {
                    "'Dataset'",
                    "'Validated analysis fingerprint'",
                    "'Root analysis scope'",
                }:
                    failures.append("S01 technical-row exclusion filter differs from contract")

    return {
        "baseline": str(baseline),
        "candidate": str(candidate),
        "layout_manifest": str(manifest_path),
        "pages": len(actual["pages"] or []),
        "data_visuals": len(data_ids),
        "text_objects": len(text_ids),
        "failures": failures,
        "interaction_status": manifest["interactions"]["static_status"],
        "scope": (
            "dashboard-refresh static allowlist only; DAX execution, native interactions, "
            "reconciliation, and rendering not checked"
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    schema = validate_project(args.project)
    references = validate_references(args.project)
    result = {"schema": schema, "references": references}
    if args.baseline:
        result["static_parity"] = compare_powerbi_projects(args.baseline, args.project)
    print(json.dumps(result, indent=2))
    raise SystemExit(
        1
        if schema["failures"]
        or references["failures"]
        or (args.baseline and result["static_parity"]["failures"])
        else 0
    )
