"""Client Power BI REST API untuk scan lineage workspace dan item."""

from __future__ import annotations

import time
from typing import Any, Callable

from .api import ApiError, Transport
from .auth import EntraTokens, POWERBI_SCOPE, ServicePrincipal
from .errors import ExtractionError
from .lineage_transform import datasource_id

API = "https://api.powerbi.com/v1.0/myorg"
MAX_RETRIES = 8
# Endpoint admin mendukung sampai 5000 baris per halaman ($top) dan memakai
# $skip untuk halaman berikutnya; tenant dengan 865 workspace cukup satu halaman.
PAGE_SIZE = 5000
MAX_PAGES = 200

Log = Callable[[str], None]


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


# Nama lama dipertahankan agar pemanggil yang menangkap error ini tetap jalan;
# ``status_code`` sekarang berasal dari :class:`core.api.ApiError`.
LineageApiError = ApiError


class PowerBILineageClient:
    """Client service principal untuk Scanner API dan endpoint member."""

    def __init__(
        self,
        principal: ServicePrincipal,
        *,
        session: Any | None = None,
        msal_app: Any | None = None,
        log: Log = _silent,
        sleep: Callable[[float], None] = time.sleep,
        timeout: int = 120,
    ) -> None:
        principal.validate()
        self.settings = principal
        self._log = log
        self._tokens = EntraTokens(principal, msal_app=msal_app)
        self._transport = Transport(
            self._tokens.provider(POWERBI_SCOPE),
            API,
            session=session,
            sleep=sleep,
            max_retries=MAX_RETRIES,
            timeout=timeout,
            # 5xx tidak diulang di sini: probe_admin butuh status asli untuk
            # memutuskan fallback ke endpoint member.
            retry_status=(429,),
            log=log,
        )

    # -- HTTP -------------------------------------------------------------
    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "PowerBILineageClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        if str(method or "").strip().upper() == "DELETE":
            raise ExtractionError(
                "Metode HTTP DELETE dilarang di tool ini. Gunakan POST "
                "(mis. .../clear atau .../cancel)."
            )
        return self._transport.json(method, path, **kwargs)

    def _try(self, path: str, **kwargs: Any) -> list[Any]:
        """Endpoint opsional: kegagalan HTTP dicatat lalu menghasilkan list kosong."""
        try:
            data = self._call("GET", path, **kwargs)
        except LineageApiError as exc:
            self._log(f"Lewati endpoint {path}: {exc}")
            return []
        if isinstance(data, dict):
            value = data.get("value")
            return value if isinstance(value, list) else []
        return data if isinstance(data, list) else []

    def _list(self, path: str) -> list[dict[str, Any]]:
        """Ambil satu daftar item; kegagalan HTTP diteruskan ke pemanggil."""
        data = self._call("GET", path)
        if isinstance(data, dict):
            data = data.get("value")
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _paged(
        self,
        path: str,
        *,
        page_size: int = PAGE_SIZE,
        max_pages: int = MAX_PAGES,
    ) -> list[dict[str, Any]]:
        """Iterasi endpoint admin berbasis ``$top``/``$skip``.

        Berhenti saat halaman lebih pendek dari ``page_size``, saat tidak ada ID
        baru (endpoint mengabaikan ``$skip``), atau setelah ``max_pages``.
        """
        page_size = max(1, int(page_size))
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        skip = 0
        for _ in range(max(1, int(max_pages))):
            data = self._call(
                "GET", path, params={"$top": page_size, "$skip": skip}
            )
            page = data.get("value") if isinstance(data, dict) else data
            if not isinstance(page, list) or not page:
                break
            rows = [item for item in page if isinstance(item, dict)]
            fresh = 0
            for row in rows:
                key = str(row.get("id") or row.get("objectId") or "")
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                fresh += 1
                items.append(row)
            if len(page) < page_size or fresh == 0:
                break
            skip += page_size
        return items


    # -- member -----------------------------------------------------------
    def member_workspaces(self, *, page_size: int = PAGE_SIZE) -> list[tuple[str, str]]:
        groups = self._paged("groups", page_size=page_size)
        return [
            (str(group["id"]), group.get("name") or "")
            for group in groups
            if group.get("id")
        ]

    def datasets_in_group(self, workspace_id: str) -> list[dict[str, Any]]:
        """Semantic model di satu workspace (untuk pilihan catalog)."""
        return self._list(f"groups/{workspace_id}/datasets")

    def reports_in_group(self, workspace_id: str) -> list[dict[str, Any]]:
        """Report di satu workspace (untuk pilihan sumber report)."""
        return self._list(f"groups/{workspace_id}/reports")

    def report_subscriptions(self, report_id: str) -> list[dict[str, Any]]:
        """Subscription satu report (Admin REST, butuh Fabric administrator).

        Kuota endpoint ini 200 request/jam; pemanggil wajib membatasi jumlah
        report dan menyimpan cache. Kegagalan HTTP diteruskan sebagai
        :class:`ApiError` supaya pemanggil bisa membedakan 401/403/429.
        """
        data = self._call(
            "GET", f"admin/reports/{str(report_id).strip()}/subscriptions"
        )
        value = data.get("value") if isinstance(data, dict) else data
        if not isinstance(value, list):
            return []
        return [row for row in value if isinstance(row, dict)]

    def member_scan(self, workspace_id: str, workspace_name: str) -> dict[str, Any]:
        workspace_path = f"groups/{workspace_id}"
        instances: dict[str, dict[str, Any]] = {}

        def usages(kind: str, item_id: str) -> list[dict[str, str]]:
            output: list[dict[str, str]] = []
            for datasource in self._try(
                f"{workspace_path}/{kind}/{item_id}/datasources"
            ):
                if not isinstance(datasource, dict):
                    continue
                key = datasource_id(datasource)
                instances[key] = {**datasource, "datasourceId": key}
                output.append({"datasourceInstanceId": key})
            return output

        datasets: list[dict[str, Any]] = []
        for dataset in self._try(f"{workspace_path}/datasets"):
            if not isinstance(dataset, dict) or not dataset.get("id"):
                continue
            datasets.append(
                {
                    **dataset,
                    "datasourceUsages": usages("datasets", str(dataset["id"])),
                }
            )

        dataflows: list[dict[str, Any]] = []
        for dataflow in self._try(f"{workspace_path}/dataflows"):
            if not isinstance(dataflow, dict):
                continue
            dataflow_id = dataflow.get("objectId") or dataflow.get("id")
            if not dataflow_id:
                continue
            dataflows.append(
                {
                    **dataflow,
                    "id": dataflow_id,
                    "datasourceUsages": usages("dataflows", str(dataflow_id)),
                    "upstreamDataflows": self._try(
                        f"{workspace_path}/dataflows/{dataflow_id}/upstreamDataflows"
                    ),
                }
            )

        dashboards: list[dict[str, Any]] = []
        for dashboard in self._try(f"{workspace_path}/dashboards"):
            if not isinstance(dashboard, dict) or not dashboard.get("id"):
                continue
            dashboards.append(
                {
                    **dashboard,
                    "tiles": self._try(
                        f"{workspace_path}/dashboards/{dashboard['id']}/tiles"
                    ),
                }
            )

        return {
            "id": workspace_id,
            "name": workspace_name,
            "datasets": datasets,
            "dataflows": dataflows,
            "reports": [
                report
                for report in self._try(f"{workspace_path}/reports")
                if isinstance(report, dict)
            ],
            "dashboards": dashboards,
            "datasourceInstances": list(instances.values()),
        }
