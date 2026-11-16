"""Transformasi hasil scan Power BI REST API menjadi node dan edge lineage."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def endorsement(item: dict[str, Any]) -> str:
    return (item.get("endorsementDetails") or {}).get("endorsement") or "None"


def sensitivity_label(item: dict[str, Any]) -> str | None:
    return (item.get("sensitivityLabel") or {}).get("labelId")


def datasource_id(datasource: dict[str, Any]) -> str:
    """ID stabil untuk datasource, termasuk bila API hanya memberi detail koneksi."""
    if datasource.get("datasourceId"):
        return str(datasource["datasourceId"])
    details = datasource.get("connectionDetails") or {}
    raw = "|".join(
        str(value or "")
        for value in (
            datasource.get("datasourceType"),
            details.get("server"),
            details.get("database"),
            details.get("url") or details.get("path"),
            details.get("connectionString"),
            details.get("sharePointSiteUrl"),
        )
    )
    return "ds-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def datasource_name(datasource_type: str | None, details: dict[str, Any]) -> str:
    values = [
        details.get("server"),
        details.get("database"),
        details.get("url"),
        details.get("path"),
        details.get("connectionString"),
        details.get("sharePointSiteUrl"),
        details.get("projectId"),
        details.get("projectID"),
    ]
    connection = " / ".join(
        dict.fromkeys(str(value) for value in values if value)
    )
    return f"{datasource_type or 'Datasource'}: {connection}"


def transform(scan_result: dict[str, Any]) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Ubah satu response Scanner API/member scan menjadi nodes, edges, datasources.

    Bentuk tuple mengikuti schema SQLite:
    node       = (node_id, node_type, name, workspace_id, owner,
                  endorsement, sensitivity_label, modified)
    edge       = (source_id, target_id, edge_type)
    datasource = (node_id, datasource_type, server, database_name,
                  path_or_url, gateway_id, connection_details_json)
    """
    nodes: dict[str, tuple] = {}
    edges: set[tuple[str, str, str]] = set()
    datasources: dict[str, tuple] = {}
    global_datasource_instances = (
        (scan_result.get("datasourceInstances") or [])
        + (scan_result.get("misconfiguredDatasourceInstances") or [])
    )

    def add_node(
        node_id: str | None,
        node_type: str,
        name: str | None,
        workspace_id: str | None = None,
        owner: str | None = None,
        endorsement_value: str | None = None,
        label_id: str | None = None,
        modified: str | None = None,
    ) -> None:
        if not node_id:
            return
        nodes[node_id] = (
            node_id,
            node_type,
            name,
            workspace_id,
            owner,
            endorsement_value,
            label_id,
            modified,
        )

    def add_edge(source_id: str | None, target_id: str | None, edge_type: str) -> None:
        if source_id and target_id:
            edges.add((source_id, target_id, edge_type))

    for workspace in scan_result.get("workspaces", []) or []:
        workspace_id = workspace.get("id")
        add_node(workspace_id, "Workspace", workspace.get("name"))

        instance_map: dict[str, str] = {}
        datasource_instances = (
            global_datasource_instances
            + (workspace.get("datasourceInstances") or [])
            + (workspace.get("misconfiguredDatasourceInstances") or [])
        )
        for datasource in datasource_instances:
            datasource_node_id = datasource_id(datasource)
            instance_map[datasource.get("datasourceId", datasource_node_id)] = (
                datasource_node_id
            )
            details = datasource.get("connectionDetails") or {}
            add_node(
                datasource_node_id,
                "Datasource",
                datasource_name(datasource.get("datasourceType"), details),
            )
            datasources[datasource_node_id] = (
                datasource_node_id,
                datasource.get("datasourceType"),
                details.get("server"),
                details.get("database"),
                details.get("url") or details.get("path"),
                datasource.get("gatewayId"),
                json.dumps(details, ensure_ascii=False),
            )

        def link_datasources(item: dict[str, Any]) -> None:
            usages = (
                (item.get("datasourceUsages") or [])
                + (item.get("misconfiguredDatasourceUsages") or [])
            )
            for usage in usages:
                instance_id = usage.get("datasourceInstanceId")
                add_edge(
                    instance_map.get(instance_id, instance_id),
                    item.get("id"),
                    "feeds",
                )

        for dataflow in workspace.get("dataflows", []) or []:
            dataflow_id = dataflow.get("id") or dataflow.get("objectId")
            if not dataflow_id:
                continue
            dataflow = {**dataflow, "id": dataflow_id}
            add_node(
                dataflow_id,
                "Dataflow",
                dataflow.get("name"),
                workspace_id,
                dataflow.get("configuredBy") or dataflow.get("modifiedBy"),
                endorsement(dataflow),
                sensitivity_label(dataflow),
                dataflow.get("modifiedDateTime"),
            )
            link_datasources(dataflow)
            for upstream in dataflow.get("upstreamDataflows", []) or []:
                add_edge(
                    upstream.get("targetDataflowId"),
                    dataflow_id,
                    "feeds",
                )

        for dataset in workspace.get("datasets", []) or []:
            dataset_id = dataset.get("id")
            add_node(
                dataset_id,
                "SemanticModel",
                dataset.get("name"),
                workspace_id,
                dataset.get("configuredBy"),
                endorsement(dataset),
                sensitivity_label(dataset),
                dataset.get("createdDate"),
            )
            link_datasources(dataset)
            for upstream in dataset.get("upstreamDataflows", []) or []:
                add_edge(
                    upstream.get("targetDataflowId"),
                    dataset_id,
                    "feeds",
                )
            for upstream in dataset.get("upstreamDatasets", []) or []:
                add_edge(
                    upstream.get("targetDatasetId"),
                    dataset_id,
                    "feeds",
                )

        for report in workspace.get("reports", []) or []:
            report_id = report.get("id")
            add_node(
                report_id,
                "Report",
                report.get("name"),
                workspace_id,
                report.get("modifiedBy") or report.get("createdBy"),
                endorsement(report),
                sensitivity_label(report),
                report.get("modifiedDateTime"),
            )
            add_edge(report.get("datasetId"), report_id, "uses_dataset")

        for dashboard in workspace.get("dashboards", []) or []:
            dashboard_id = dashboard.get("id")
            add_node(
                dashboard_id,
                "Dashboard",
                dashboard.get("displayName") or dashboard.get("name"),
                workspace_id,
                None,
                endorsement(dashboard),
                sensitivity_label(dashboard),
                None,
            )
            for tile in dashboard.get("tiles", []) or []:
                if tile.get("reportId"):
                    add_edge(tile["reportId"], dashboard_id, "pinned_to")
                elif tile.get("datasetId"):
                    add_edge(tile["datasetId"], dashboard_id, "pinned_to")

        for key in ("dataflows", "datasets", "reports", "dashboards"):
            for item in workspace.get(key, []) or []:
                item_id = item.get("id") or item.get("objectId")
                add_edge(workspace_id, item_id, "contains")

    return list(nodes.values()), sorted(edges), list(datasources.values())
