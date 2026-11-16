"""Penyimpanan dan pembacaan graph lineage di SQLite."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import ExtractionError
from .lineage_transform import datasource_name
from .pbix import ROOT

DATA_DIR = ROOT / "data"
DEFAULT_DB = DATA_DIR / "bi_tools.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_run (
  scan_id TEXT PRIMARY KEY,
  started_at TEXT, finished_at TEXT,
  mode TEXT, workspace_count INTEGER, status TEXT
);
CREATE TABLE IF NOT EXISTS nodes (
  node_id TEXT PRIMARY KEY,
  node_type TEXT, name TEXT, workspace_id TEXT, owner TEXT,
  endorsement TEXT, sensitivity_label TEXT,
  last_refresh_at TEXT, last_modified_at TEXT,
  is_active INTEGER DEFAULT 1,
  first_seen_scan TEXT, last_seen_scan TEXT
);
CREATE TABLE IF NOT EXISTS edges (
  source_id TEXT, target_id TEXT, edge_type TEXT,
  is_active INTEGER DEFAULT 1,
  first_seen_scan TEXT, last_seen_scan TEXT,
  PRIMARY KEY (source_id, target_id, edge_type)
);
CREATE TABLE IF NOT EXISTS datasource_detail (
  node_id TEXT PRIMARY KEY,
  datasource_type TEXT, server TEXT, database_name TEXT,
  path_or_url TEXT, gateway_id TEXT, connection_details_json TEXT
);
CREATE TABLE IF NOT EXISTS workspace (
  workspace_id TEXT PRIMARY KEY,
  name TEXT, state TEXT, type TEXT,
  capacity_id TEXT,
  is_on_dedicated_capacity INTEGER,
  is_read_only INTEGER,
  pipeline_id TEXT, description TEXT,
  payload_json TEXT,
  first_seen_sync TEXT, last_seen_sync TEXT,
  is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS workspace_sync_run (
  sync_id TEXT PRIMARY KEY,
  started_at TEXT, finished_at TEXT,
  mode TEXT, workspace_count INTEGER, active_count INTEGER,
  status TEXT, message TEXT
);
CREATE INDEX IF NOT EXISTS ix_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS ix_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS ix_nodes_ws ON nodes(workspace_id);
CREATE INDEX IF NOT EXISTS ix_workspace_name ON workspace(name);
"""

NODE_SQL = """
SELECT n.node_id, n.node_type, n.name, n.workspace_id, w.name AS workspace_name,
       n.owner, n.endorsement, n.sensitivity_label, n.last_modified_at, n.is_active,
       d.datasource_type, d.server, d.database_name, d.path_or_url, d.gateway_id,
       d.connection_details_json
  FROM nodes n LEFT JOIN nodes w ON w.node_id = n.workspace_id
  LEFT JOIN datasource_detail d ON d.node_id = n.node_id
"""


def connect(database: Path | str, *, read_only: bool = False) -> sqlite3.Connection:
    path = Path(database).expanduser()
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
    else:
        conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(datasource_detail)")
    }
    if "connection_details_json" not in columns:
        conn.execute(
            "ALTER TABLE datasource_detail ADD COLUMN connection_details_json TEXT"
        )
        conn.commit()


def save(
    conn: sqlite3.Connection,
    scan_id: str,
    scanned_ws_ids: Iterable[str],
    nodes: list[tuple],
    edges: list[tuple],
    datasources: list[tuple],
) -> None:
    """Simpan satu batch hasil scan, menonaktifkan item lama di workspace yang dipindai."""
    cur = conn.cursor()
    scanned = list(scanned_ws_ids)

    if scanned:
        marks = ",".join("?" * len(scanned))
        cur.execute(
            f"UPDATE nodes SET is_active=0 WHERE workspace_id IN ({marks})",
            scanned,
        )
        cur.execute(
            f"""UPDATE edges SET is_active=0
                WHERE target_id IN (
                    SELECT node_id FROM nodes WHERE workspace_id IN ({marks})
                )""",
            scanned,
        )

    merged_datasources: list[tuple] = []
    datasource_names: dict[str, tuple] = {}
    for datasource in datasources:
        existing = cur.execute(
            "SELECT connection_details_json FROM datasource_detail WHERE node_id=?",
            (datasource[0],),
        ).fetchone()
        existing_details: dict[str, Any] = {}
        if existing and existing["connection_details_json"]:
            try:
                existing_details = json.loads(existing["connection_details_json"])
            except json.JSONDecodeError:
                existing_details = {}
        try:
            scanned_details = json.loads(datasource[6]) if datasource[6] else {}
        except json.JSONDecodeError:
            scanned_details = {}
        merged_details = {
            **existing_details,
            **{
                key: value
                for key, value in scanned_details.items()
                if value not in (None, "")
            },
        }
        datasource_names[datasource[0]] = (datasource[1], merged_details)
        merged_datasources.append(
            datasource[:6] + (json.dumps(merged_details, ensure_ascii=False),)
        )

    if datasource_names:
        nodes = [
            node[:2]
            + (datasource_name(*datasource_names[node[0]]),)
            + node[3:]
            if node[0] in datasource_names
            else node
            for node in nodes
        ]

    cur.executemany(
        """INSERT INTO nodes (node_id,node_type,name,workspace_id,owner,endorsement,
                              sensitivity_label,last_modified_at,is_active,
                              first_seen_scan,last_seen_scan)
           VALUES (?,?,?,?,?,?,?,?,1,?,?)
           ON CONFLICT(node_id) DO UPDATE SET
             node_type=excluded.node_type, name=excluded.name,
             workspace_id=excluded.workspace_id, owner=excluded.owner,
             endorsement=excluded.endorsement,
             sensitivity_label=excluded.sensitivity_label,
             last_modified_at=excluded.last_modified_at,
             is_active=1, last_seen_scan=excluded.last_seen_scan""",
        [node + (scan_id, scan_id) for node in nodes],
    )
    cur.executemany(
        """INSERT INTO edges (source_id,target_id,edge_type,is_active,
                              first_seen_scan,last_seen_scan)
           VALUES (?,?,?,1,?,?)
           ON CONFLICT(source_id,target_id,edge_type) DO UPDATE SET
             is_active=1, last_seen_scan=excluded.last_seen_scan""",
        [edge + (scan_id, scan_id) for edge in edges],
    )
    cur.executemany(
        """INSERT INTO datasource_detail
           (node_id,datasource_type,server,database_name,path_or_url,gateway_id,
            connection_details_json)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(node_id) DO UPDATE SET
             datasource_type=COALESCE(excluded.datasource_type,datasource_detail.datasource_type),
             server=COALESCE(excluded.server,datasource_detail.server),
             database_name=COALESCE(excluded.database_name,datasource_detail.database_name),
             path_or_url=COALESCE(excluded.path_or_url,datasource_detail.path_or_url),
             gateway_id=COALESCE(excluded.gateway_id,datasource_detail.gateway_id),
             connection_details_json=excluded.connection_details_json""",
        merged_datasources,
    )
    conn.commit()


# --------------------------------------------------------------- workspace
WORKSPACE_COLUMNS = """
workspace_id, name, state, type, capacity_id, is_on_dedicated_capacity,
is_read_only, pipeline_id, description, payload_json, first_seen_sync,
last_seen_sync, is_active
"""

# Tipe dari Admin API yang bukan workspace bersama; tidak ditampilkan di picker
# kecuali diminta eksplisit.
PERSONAL_GROUP_TYPES = ("PersonalGroup", "Personal", "AdminWorkspace")


def _flag(value: Any) -> int:
    return 1 if value else 0


def workspace_is_active(row: Mapping[str, Any]) -> int:
    """Workspace dianggap aktif kecuali API menyebut state lain (mis. Deleted)."""
    state = str(row.get("state") or "").strip().lower()
    return 0 if state and state != "active" else 1


def save_workspaces(
    conn: sqlite3.Connection,
    sync_id: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    full: bool = False,
) -> tuple[int, int]:
    """Simpan daftar workspace; kembalikan ``(jumlah baru, jumlah diperbarui)``.

    ``full`` menonaktifkan workspace yang tidak muncul lagi pada daftar lengkap
    (mode admin). Mode member bersifat parsial, jadi tidak boleh menonaktifkan
    apa pun. Tabel ``nodes`` hanya di-upsert supaya status aktif milik scan
    lineage tidak tertimpa.
    """
    cur = conn.cursor()
    if full:
        cur.execute("UPDATE workspace SET is_active = 0")
    existing = {
        str(row["workspace_id"]) for row in cur.execute("SELECT workspace_id FROM workspace")
    }

    values: list[tuple] = []
    nodes: list[tuple] = []
    added = 0
    for row in rows:
        workspace_id = str(row.get("id") or row.get("workspace_id") or "").strip()
        if not workspace_id:
            continue
        name = str(row.get("name") or "")
        active = workspace_is_active(row)
        if workspace_id not in existing:
            added += 1
        values.append(
            (
                workspace_id,
                name,
                row.get("state"),
                row.get("type"),
                row.get("capacityId"),
                _flag(row.get("isOnDedicatedCapacity")),
                _flag(row.get("isReadOnly")),
                row.get("pipelineId"),
                row.get("description"),
                json.dumps(dict(row), ensure_ascii=False, default=str),
                sync_id,
                sync_id,
                active,
            )
        )
        nodes.append((workspace_id, name, active))

    cur.executemany(
        """INSERT INTO workspace (workspace_id,name,state,type,capacity_id,
                                  is_on_dedicated_capacity,is_read_only,pipeline_id,
                                  description,payload_json,first_seen_sync,
                                  last_seen_sync,is_active)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(workspace_id) DO UPDATE SET
             name=excluded.name, state=excluded.state, type=excluded.type,
             capacity_id=excluded.capacity_id,
             is_on_dedicated_capacity=excluded.is_on_dedicated_capacity,
             is_read_only=excluded.is_read_only,
             pipeline_id=excluded.pipeline_id,
             description=excluded.description,
             payload_json=excluded.payload_json,
             last_seen_sync=excluded.last_seen_sync,
             is_active=excluded.is_active""",
        values,
    )
    cur.executemany(
        """INSERT INTO nodes (node_id,node_type,name,workspace_id,is_active)
           VALUES (?,'Workspace',?,NULL,?)
           ON CONFLICT(node_id) DO UPDATE SET
             node_type='Workspace', name=excluded.name""",
        nodes,
    )
    conn.commit()
    return added, len(values) - added


def save_workspace_sync_run(
    conn: sqlite3.Connection,
    sync_id: str,
    *,
    started_at: str,
    finished_at: str,
    mode: str,
    workspace_count: int,
    active_count: int,
    status: str,
    message: str = "",
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO workspace_sync_run VALUES (?,?,?,?,?,?,?,?)",
        (
            sync_id,
            started_at,
            finished_at,
            mode,
            int(workspace_count),
            int(active_count),
            status,
            message,
        ),
    )
    conn.commit()


def workspace_list(
    conn: sqlite3.Connection,
    *,
    active_only: bool = True,
    include_personal: bool = False,
) -> list[dict[str, Any]]:
    """Daftar workspace untuk picker, urut nama (tanpa membedakan huruf)."""
    conditions: list[str] = []
    if active_only:
        conditions.append("is_active = 1")
    if not include_personal:
        marks = ",".join("?" * len(PERSONAL_GROUP_TYPES))
        conditions.append(f"(type IS NULL OR type NOT IN ({marks}))")
    query = f"SELECT {WORKSPACE_COLUMNS} FROM workspace"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY name COLLATE NOCASE"
    params: tuple[Any, ...] = () if include_personal else PERSONAL_GROUP_TYPES
    return [dict(row) for row in conn.execute(query, params)]


def workspace_by_name(
    conn: sqlite3.Connection, name: str
) -> list[dict[str, Any]]:
    """Cari workspace berdasarkan nama; bisa lebih dari satu bila duplikat."""
    query = (
        f"SELECT {WORKSPACE_COLUMNS} FROM workspace WHERE name = ? "
        "ORDER BY is_active DESC, workspace_id"
    )
    return [dict(row) for row in conn.execute(query, (str(name or ""),))]


def workspace_by_id(
    conn: sqlite3.Connection, workspace_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {WORKSPACE_COLUMNS} FROM workspace WHERE workspace_id = ?",
        (str(workspace_id or ""),),
    ).fetchone()
    return dict(row) if row else None


def workspace_sync_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) FROM workspace").fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM workspace WHERE is_active = 1"
    ).fetchone()[0]
    last = conn.execute(
        "SELECT mode, finished_at FROM workspace_sync_run "
        "WHERE status='Succeeded' ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    return {
        "total": int(total or 0),
        "active": int(active or 0),
        "selectable": workspace_selectable_count(conn),
        "last_sync": str(last["finished_at"] or "") if last else "",
        "last_mode": str(last["mode"] or "") if last else "",
    }


def workspace_selectable_count(conn: sqlite3.Connection) -> int:
    """Jumlah workspace yang benar-benar muncul di picker (filter default)."""
    marks = ",".join("?" * len(PERSONAL_GROUP_TYPES))
    row = conn.execute(
        f"""SELECT COUNT(*) FROM workspace
             WHERE is_active = 1
               AND (type IS NULL OR type NOT IN ({marks}))""",
        PERSONAL_GROUP_TYPES,
    ).fetchone()
    return int(row[0] or 0)


def traverse(
    conn: sqlite3.Connection,
    node_id: str,
    direction: str = "downstream",
    max_depth: int = 10,
) -> list[sqlite3.Row]:
    """Daftar item pada satu arah lineage, dipakai CLI impact/upstream."""
    start, nxt = (
        ("source_id", "target_id")
        if direction == "downstream"
        else ("target_id", "source_id")
    )
    sql = f"""
    WITH RECURSIVE walk(node_id, depth) AS (
      SELECT {nxt}, 1 FROM edges
       WHERE {start} = ? AND is_active = 1 AND edge_type <> 'contains'
      UNION
      SELECT e.{nxt}, w.depth + 1 FROM edges e JOIN walk w ON e.{start} = w.node_id
       WHERE e.is_active = 1 AND e.edge_type <> 'contains' AND w.depth < ?
    )
    SELECT n.node_type, n.name, n.owner, n.workspace_id, MIN(w.depth) AS depth
      FROM walk w JOIN nodes n ON n.node_id = w.node_id
     GROUP BY n.node_id ORDER BY depth, n.node_type, n.name"""
    return conn.execute(sql, (node_id, max_depth)).fetchall()


def search(
    conn: sqlite3.Connection,
    query: str = "",
    workspace: str = "",
    node_type: str = "",
    limit: int = 300,
) -> list[dict[str, Any]]:
    sql = NODE_SQL + " WHERE n.is_active = 1 AND n.node_type <> 'Workspace'"
    params: list[Any] = []
    if query:
        sql += " AND (n.name LIKE ? OR n.node_id = ?)"
        params.extend((f"%{query}%", query))
    if workspace:
        sql += " AND w.name LIKE ?"
        params.append(f"%{workspace}%")
    if node_type:
        sql += " AND n.node_type = ?"
        params.append(node_type)
    sql += " ORDER BY n.name COLLATE NOCASE, w.name COLLATE NOCASE LIMIT ?"
    params.append(limit)
    return [dict(row) for row in conn.execute(sql, params)]


def node_info(conn: sqlite3.Connection, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    values = list(ids)
    for offset in range(0, len(values), 500):
        chunk = values[offset : offset + 500]
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(NODE_SQL + f" WHERE n.node_id IN ({marks})", chunk)
        for row in rows:
            node = dict(row)
            raw_details = node.pop("connection_details_json", None)
            try:
                node["connection_details"] = (
                    json.loads(raw_details) if raw_details else {}
                )
            except json.JSONDecodeError:
                node["connection_details"] = {}
            result[node["node_id"]] = node
    return result


def lineage(
    conn: sqlite3.Connection,
    node_id: str,
    direction: str = "downstream",
    max_depth: int = 15,
) -> dict[str, Any] | None:
    """Telusuri lineage satu arah. Setiap node menyimpan satu parent (jalur terpendek)."""
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    rows = conn.execute(
        """SELECT source_id, target_id, edge_type FROM edges
           WHERE is_active = 1 AND edge_type <> 'contains'"""
    )
    for row in rows:
        if direction == "downstream":
            adjacency[row["source_id"]].append((row["target_id"], row["edge_type"]))
        else:
            adjacency[row["target_id"]].append((row["source_id"], row["edge_type"]))

    depth: dict[str, int] = {node_id: 0}
    parent: dict[str | None, str | None] = {node_id: None}
    via: dict[str, str] = {}
    queue: deque[str] = deque([node_id])
    while queue:
        current = queue.popleft()
        if depth[current] >= max_depth:
            continue
        for next_id, edge_type in adjacency.get(current, ()):
            if next_id not in depth:
                depth[next_id] = depth[current] + 1
                parent[next_id] = current
                via[next_id] = edge_type
                queue.append(next_id)

    info = node_info(conn, depth)
    if node_id not in info:
        return None

    nodes: list[dict[str, Any]] = []
    for current, distance in depth.items():
        if current == node_id:
            continue
        row = info.get(current) or {
            "node_id": current,
            "node_type": "Unknown",
            "name": "(tidak ada di tabel nodes)",
            "workspace_name": None,
            "owner": None,
            "last_modified_at": None,
            "is_active": 1,
        }
        nodes.append(
            {
                **row,
                "depth": distance,
                "parent": parent[current],
                "edge_type": via.get(current),
            }
        )
    return {"root": info[node_id], "direction": direction, "nodes": nodes}


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    types = [
        dict(row)
        for row in conn.execute(
            """SELECT node_type, COUNT(*) AS n FROM nodes
               WHERE is_active = 1 GROUP BY node_type ORDER BY n DESC"""
        )
    ]
    last_scan = conn.execute("SELECT MAX(finished_at) FROM scan_run").fetchone()[0]
    return {"types": types, "last_scan": last_scan}


def active_counts(conn: sqlite3.Connection) -> tuple[int, int]:
    nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE is_active = 1").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM edges WHERE is_active = 1").fetchone()[0]
    return int(nodes), int(edges)


def unresolved_feed_sources(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """SELECT COUNT(DISTINCT e.source_id)
             FROM edges e
             LEFT JOIN nodes n ON n.node_id = e.source_id
            WHERE e.is_active = 1
              AND e.edge_type = 'feeds'
              AND n.node_id IS NULL"""
    ).fetchone()
    return int(row[0] or 0)


def diagnostics(conn: sqlite3.Connection) -> dict[str, Any]:
    """Ringkasan integritas edge dan riwayat scan untuk perintah --check."""
    edge_rows = [
        {
            "edge_type": row["edge_type"],
            "total": int(row["total"] or 0),
            "source_missing": int(row["source_missing"] or 0),
            "target_missing": int(row["target_missing"] or 0),
        }
        for row in conn.execute(
            """SELECT e.edge_type,
                      COUNT(*) AS total,
                      SUM(e.source_id NOT IN (SELECT node_id FROM nodes)) AS source_missing,
                      SUM(e.target_id NOT IN (SELECT node_id FROM nodes)) AS target_missing
                 FROM edges e WHERE e.is_active = 1 GROUP BY e.edge_type
                ORDER BY e.edge_type"""
        )
    ]
    missing = [
        dict(row)
        for row in conn.execute(
            """SELECT edge_type, 'source' AS side, source_id AS node_id FROM edges
                 WHERE is_active = 1 AND source_id NOT IN (SELECT node_id FROM nodes)
               UNION ALL
               SELECT edge_type, 'target', target_id FROM edges
                 WHERE is_active = 1 AND target_id NOT IN (SELECT node_id FROM nodes)
               LIMIT 15"""
        )
    ]
    scans = [
        dict(row)
        for row in conn.execute(
            """SELECT scan_id, started_at, finished_at, mode, workspace_count, status
                 FROM scan_run ORDER BY started_at DESC LIMIT 10"""
        )
    ]
    return {
        "edges": edge_rows,
        "missing_samples": missing,
        "unresolved_feed_sources": unresolved_feed_sources(conn),
        "scans": scans,
    }


def require_database(path: Path | str) -> Path:
    database = Path(path).expanduser()
    if not database.exists():
        raise ExtractionError(f"Database lineage tidak ditemukan: {database}")
    return database


def open_read_only(path: Path | str) -> sqlite3.Connection:
    """Buka database yang sudah ada untuk pencarian; schema tidak diubah."""
    database = require_database(path)
    conn: sqlite3.Connection | None = None
    try:
        conn = connect(database, read_only=True)
        conn.execute("SELECT 1 FROM nodes LIMIT 1")
    except sqlite3.Error as exc:
        if conn is not None:
            close_quietly(conn)
        raise ExtractionError(
            f"Database lineage tidak bisa dibaca: {database} ({exc})"
        ) from exc
    return conn


def close_quietly(conn: sqlite3.Connection) -> None:
    with closing(conn):
        pass
