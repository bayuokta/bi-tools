"""Serialisasi objek TOM untuk perbandingan semantic model.

Hanya dijalankan di proses CLI anak (``bi-tools-cli compare``). Server tidak
boleh mengimpor modul ini karena memuat TOM; TOM di proses server merusak
koneksi ADOMD.
"""

from __future__ import annotations

from typing import Any, Mapping

from .errors import ExtractionError
from .model_compare import normalize_options
from .tmdl_utils import (
    clean_object_definition,
    table_definition,
)
from .tom_client import load_tom


def _tom_api() -> dict[str, Any]:
    load_tom()
    from Microsoft.AnalysisServices import CompatibilityMode
    from Microsoft.AnalysisServices.Tabular import (
        JsonSerializer,
        SerializeOptions,
        TmdlSerializer,
    )

    return {
        "CompatibilityMode": CompatibilityMode,
        "JsonSerializer": JsonSerializer,
        "SerializeOptions": SerializeOptions,
        "TmdlSerializer": TmdlSerializer,
    }


def _serialize_options(api: Mapping[str, Any]) -> Any:
    options = api["SerializeOptions"]()
    options.IgnoreInferredProperties = True
    options.IgnoreInferredObjects = True
    options.IgnoreTimestamps = True
    options.SplitMultilineStrings = True
    return options


def _serialize(
    obj: Any,
    options: Mapping[str, Any],
    api: Mapping[str, Any],
    serialize_options: Any,
    database: Any,
) -> str:
    if options.get("tmsl"):
        return api["JsonSerializer"].SerializeObject(
            obj,
            serialize_options,
            int(database.CompatibilityLevel),
            database.CompatibilityMode,
        )
    return api["TmdlSerializer"].SerializeObject(obj, False)


def _definition(
    obj: Any,
    object_type: str,
    options: Mapping[str, Any],
    api: Mapping[str, Any],
    serialize_options: Any,
    database: Any,
    *,
    calculation_group: bool = False,
) -> str:
    text = _serialize(obj, options, api, serialize_options, database)
    if object_type == "Table":
        return table_definition(
            text,
            partitions=bool(options.get("partitions")),
            annotations=bool(options.get("annotations")),
            lineage_tag=bool(options.get("lineage_tag")),
            calculation_group=calculation_group,
            tmsl=bool(options.get("tmsl")),
        )
    return clean_object_definition(
        text,
        annotations=bool(options.get("annotations")),
        lineage_tag=bool(options.get("lineage_tag")),
        tmsl=bool(options.get("tmsl")),
    )


def _relationship_name(relationship: Any) -> str:
    name = str(getattr(relationship, "Name", "") or "")
    if name:
        return name
    from_table = str(getattr(getattr(relationship, "FromTable", None), "Name", "") or "")
    from_column = str(
        getattr(getattr(relationship, "FromColumn", None), "Name", "") or ""
    )
    to_table = str(getattr(getattr(relationship, "ToTable", None), "Name", "") or "")
    to_column = str(getattr(getattr(relationship, "ToColumn", None), "Name", "") or "")
    return f"{from_table}[{from_column}] -> {to_table}[{to_column}]"


def _relationship_display(relationship: Any) -> str:
    from_table = str(getattr(getattr(relationship, "FromTable", None), "Name", "") or "")
    from_column = str(
        getattr(getattr(relationship, "FromColumn", None), "Name", "") or ""
    )
    to_table = str(getattr(getattr(relationship, "ToTable", None), "Name", "") or "")
    to_column = str(getattr(getattr(relationship, "ToColumn", None), "Name", "") or "")
    return f"'{from_table}'[{from_column}] -> '{to_table}'[{to_column}]"


def _add(
    objects: list[dict[str, Any]],
    object_type: str,
    key: str,
    name: str,
    parent: str,
    definition: str,
) -> None:
    objects.append(
        {
            "type": object_type,
            "key": key,
            "name": name,
            "parent": parent,
            "definition": definition,
        }
    )


def snapshot_from_server(
    server: Any,
    dataset: str,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot objek TOM (definisi TMDL/TMSL persis) dari server TOM."""
    settings = normalize_options(options)
    api = _tom_api()
    serialize_options = _serialize_options(api)
    try:
        database = server.Databases.GetByName(dataset)
    except Exception as exc:  # noqa: BLE001
        try:
            available = [str(item.Name) for item in server.Databases]
        except Exception:  # noqa: BLE001
            available = []
        detail = f" Dataset tersedia: {', '.join(available)}." if available else ""
        raise ExtractionError(
            f"Dataset '{dataset}' tidak ditemukan di server TOM.{detail}"
        ) from exc

    model = database.Model
    objects: list[dict[str, Any]] = []

    # Data source (ALM membandingkan data source secara terpisah).
    try:
        for data_source in model.DataSources:
            name = str(data_source.Name)
            _add(
                objects,
                "Data source",
                name,
                name,
                "",
                _definition(data_source, "Data source", settings, api, serialize_options, database),
            )
    except Exception as exc:  # noqa: BLE001 - engine lama bisa tanpa DataSources
        raise ExtractionError(f"Data source model tidak bisa dibaca: {exc}") from exc

    for table in model.Tables:
        table_name = str(table.Name)
        calculation_group = getattr(table, "CalculationGroup", None) is not None
        _add(
            objects,
            "Table",
            table_name,
            table_name,
            "",
            _definition(
                table,
                "Table",
                settings,
                api,
                serialize_options,
                database,
                calculation_group=calculation_group,
            ),
        )
        if settings["measures"]:
            for measure in table.Measures:
                name = str(measure.Name)
                key = f"{table_name}|{name}"
                _add(
                    objects,
                    "Measure",
                    key,
                    name,
                    table_name,
                    _definition(measure, "Measure", settings, api, serialize_options, database),
                )
        if calculation_group:
            try:
                items = table.CalculationGroup.CalculationItems
            except Exception:  # noqa: BLE001
                items = []
            for item in items:
                name = str(item.Name)
                key = f"{table_name}|{name}"
                _add(
                    objects,
                    "Calculation item",
                    key,
                    name,
                    table_name,
                    _definition(
                        item,
                        "Calculation item",
                        settings,
                        api,
                        serialize_options,
                        database,
                    ),
                )

    if settings["relationships"]:
        for relationship in model.Relationships:
            key = _relationship_name(relationship)
            parent = str(getattr(getattr(relationship, "FromTable", None), "Name", "") or "")
            _add(
                objects,
                "Relationship",
                key,
                _relationship_display(relationship),
                parent,
                _definition(
                    relationship, "Relationship", settings, api, serialize_options, database
                ),
            )

    if settings["expressions"]:
        for expression in model.Expressions:
            name = str(expression.Name)
            _add(
                objects,
                "Expression",
                name,
                name,
                "",
                _definition(expression, "Expression", settings, api, serialize_options, database),
            )

    if settings["roles"]:
        for role in model.Roles:
            name = str(role.Name)
            _add(
                objects,
                "Role",
                name,
                name,
                "",
                _definition(role, "Role", settings, api, serialize_options, database),
            )

    if settings["perspectives"]:
        for perspective in model.Perspectives:
            name = str(perspective.Name)
            _add(
                objects,
                "Perspective",
                name,
                name,
                "",
                _definition(
                    perspective, "Perspective", settings, api, serialize_options, database
                ),
            )

    if settings["cultures"]:
        for culture in model.Cultures:
            name = str(culture.Name)
            _add(
                objects,
                "Culture",
                name,
                name,
                "",
                _definition(culture, "Culture", settings, api, serialize_options, database),
            )

    objects.sort(
        key=lambda item: (
            item["type"].casefold(),
            item["parent"].casefold(),
            item["name"].casefold(),
        )
    )
    return {
        "catalog": dataset,
        "model": {
            "name": str(getattr(model, "Name", "") or dataset),
            "compatibility_level": int(database.CompatibilityLevel),
            "compatibility_mode": str(database.CompatibilityMode),
        },
        "objects": objects,
    }


def serialize_snapshot(server: Any, dataset: str, options: Mapping[str, Any] | None = None) -> str:
    """Snapshot sebagai JSON (ASCII aman untuk pipe Windows)."""
    import json

    return json.dumps(
        snapshot_from_server(server, dataset, options),
        ensure_ascii=True,
        default=str,
    )
