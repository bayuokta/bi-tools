"""Client Admin API Power BI (Scanner API dan katalog lintas workspace).

Hanya program sync yang boleh mengimpor modul ini. Aplikasi interaktif dan
``bi-tools-cli`` memakai client member di :mod:`core.lineage_api`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from core.errors import ExtractionError
from core.lineage_api import MAX_PAGES, PAGE_SIZE, LineageApiError, PowerBILineageClient

SCAN_MAX_POLLS = 120


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def safe_modified_since(hours: int = 2) -> str:
    """Timestamp lampau yang aman untuk parameter ``modifiedSince``.

    API menolak nilai di masa depan (jam mesin yang sedikit maju sudah cukup)
    dan nilai lebih tua dari 30 hari. Jendela resminya 30 menit s.d. 30 hari.
    """
    moment = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    return moment.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def clamp_modified_since(
    value: str | None,
    *,
    max_days: int = 29,
    min_minutes: int = 31,
) -> str | None:
    """Batasi watermark ke jendela yang diterima ``admin/workspaces/modified``.

    Watermark dari scan sebelumnya bisa terlalu baru (< 30 menit) atau terlalu
    lama (> 30 hari); keduanya dijawab HTTP 400 "The date should be in the last
    30 days.". ``None`` (timestamp rusak) berarti pemanggil sebaiknya full scan.
    """
    if not value:
        return None
    try:
        parsed = datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    lower = now - timedelta(days=max_days)
    upper = now - timedelta(minutes=min_minutes)
    return min(max(parsed, lower), upper).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


class AdminClient(PowerBILineageClient):
    """Client service principal untuk endpoint ``admin/*``."""

    # -- admin ------------------------------------------------------------
    def probe_admin(self) -> bool:
        try:
            self._call(
                "GET",
                "admin/workspaces/modified",
                params={
                    "excludePersonalWorkspaces": "True",
                    "modifiedSince": safe_modified_since(),
                },
            )
        except LineageApiError as exc:
            if exc.status_code in (401, 403):
                return False
            raise
        return True

    def modified_workspaces(
        self,
        modified_since: str | None = None,
        *,
        include_personal: bool = False,
    ) -> list[str]:
        """Daftar workspace yang perlu di-scan.

        ``include_personal`` mengirim ``excludePersonalWorkspaces=False`` sehingga
        My Workspace ikut di-scan; Scanner API menerima ID personal workspace
        (diverifikasi live: ``getInfo`` mengembalikan item di dalamnya).
        """
        params = {
            "excludePersonalWorkspaces": "False" if include_personal else "True"
        }
        if modified_since:
            params["modifiedSince"] = modified_since
        data = self._call("GET", "admin/workspaces/modified", params=params)
        if isinstance(data, dict):
            data = data.get("value") or []
        if not isinstance(data, list):
            return []
        return [
            str(workspace["id"])
            for workspace in data
            if isinstance(workspace, dict) and workspace.get("id")
        ]

    def admin_workspaces(self, *, page_size: int = PAGE_SIZE) -> list[dict[str, Any]]:
        """Semua workspace organisasi (Admin API), termasuk atribut katalog."""
        return self._paged("admin/groups", page_size=page_size)

    def admin_reports(self, *, page_size: int = PAGE_SIZE) -> list[dict[str, Any]]:
        """Semua report organisasi (Admin API) untuk katalog bersama."""
        return self._paged("admin/reports", page_size=page_size)

    def scan(self, workspace_ids: list[str]) -> tuple[str, dict[str, Any]]:
        params = {
            "lineage": "True",
            "datasourceDetails": "True",
            "datasetSchema": "False",
            "datasetExpressions": "False",
            "getArtifactUsers": "False",
        }
        job = self._call(
            "POST",
            "admin/workspaces/getInfo",
            params=params,
            json={"workspaces": workspace_ids},
            # Scanner API menerima permintaan dengan 202 Accepted dan body-nya
            # sudah berisi ID job; tanpa allow ini transport menganggap 202
            # sebagai kegagalan ("gagal (HTTP 202)").
            allow=(200, 202),
        )
        scan_id = str(job.get("id") or "")
        if not scan_id:
            raise ExtractionError("Scanner API tidak mengembalikan ID scan.")
        self._transport.poll_status(
            f"admin/workspaces/scanStatus/{scan_id}",
            wait=5,
            max_polls=SCAN_MAX_POLLS,
        )
        result = self._call("GET", f"admin/workspaces/scanResult/{scan_id}")
        if not isinstance(result, dict):
            raise ExtractionError("Hasil scan Power BI bukan object JSON.")
        return scan_id, result

    def reports_for_dataset(
        self, dataset_id: str, *, page_size: int = PAGE_SIZE
    ) -> list[dict[str, Any]]:
        """Semua report yang memakai satu dataset (admin API, lintas workspace).

        ``admin/reports`` mendukung ``$filter=datasetId eq '<guid>'`` sehingga
        daftar report selalu baru dan tidak bergantung pada hasil scan lineage.
        """
        dataset_id = str(dataset_id or "").strip()
        try:
            valid = str(UUID(dataset_id)) == dataset_id.lower()
        except ValueError:
            valid = False
        if not valid:
            raise ExtractionError(f"Dataset ID bukan GUID yang valid: {dataset_id!r}.")
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        skip = 0
        for _ in range(MAX_PAGES):
            data = self._call(
                "GET",
                "admin/reports",
                params={
                    "$filter": f"datasetId eq '{dataset_id}'",
                    "$top": page_size,
                    "$skip": skip,
                },
            )
            page = data.get("value") if isinstance(data, dict) else data
            if not isinstance(page, list) or not page:
                break
            fresh = 0
            for row in page:
                if not isinstance(row, dict):
                    continue
                key = str(row.get("id") or "")
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                items.append(row)
                fresh += 1
            if len(page) < page_size or fresh == 0:
                break
            skip += len(page)
        return items
