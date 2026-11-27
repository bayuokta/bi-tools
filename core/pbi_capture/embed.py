"""Embed token Power BI dengan identitas RLS untuk capture screenshot.

Alur (port dari ``pbi-download-image``/``portal-pbi-v2``):
1. Token service principal (scope Power BI) dari :class:`core.auth.EntraTokens`.
2. GET report  -> datasetId + datasetWorkspaceId.
3. GET dataset -> ``isEffectiveIdentityRolesRequired``.
4. POST GenerateToken (composite) dengan identitas RLS bila dibutuhkan.

Token hanya disimpan di memori proses dan tidak pernah ditulis ke cache,
sidecar, atau log.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from ..errors import ExtractionError
from .client import PowerBIClient
from .credentials import CaptureCredentials, split_roles

Log = Callable[[str], None]


def _silent(_message: str) -> None:
    pass


class EmbedError(ExtractionError):
    """Gagal memperoleh embed token."""


class EmbedTokenProvider:
    """Pembangkit embed token (service principal) + identitas RLS."""

    def __init__(
        self,
        token_provider: Any,
        credentials: CaptureCredentials | None = None,
        *,
        request_timeout: int = 30,
        max_retries: int = 6,
        log: Log = _silent,
    ) -> None:
        self.credentials = credentials or CaptureCredentials()
        self._log = log
        self._token_provider = token_provider
        self.rls_username = self.credentials.rls_username or ""
        self.rls_roles = list(split_roles(self.credentials.rls_roles))
        self._client = PowerBIClient(
            token_provider,
            timeout=request_timeout,
            max_retries=max_retries,
            log=log,
        )

    # ------------------------------------------------------------ sumber token
    def _resource_token(self) -> str:
        """Token untuk report/dataset/GenerateToken (scope Power BI)."""
        if self._token_provider is None:
            raise EmbedError(
                "Service principal credentials are not ready for screenshot "
                "capture (Tenant ID / Client ID / Client Secret)."
            )
        return str(self._token_provider.get_token())

    # ---------------------------------------------------------------- token
    def get_embed_token(
        self,
        workspace_id: str,
        report_id: str,
        extra_dataset_ids: Iterable[str] | None = None,
    ) -> str:
        """Bangun composite embed token untuk satu report, termasuk RLS."""
        self._resource_token()  # gagal cepat bila kredensial salah

        report = self._client.get_report(workspace_id, report_id)
        if not report:
            raise EmbedError(f"Report {report_id} was not found in the workspace.")
        dataset_id = report.get("datasetId")
        dataset_ws = report.get("datasetWorkspaceId") or workspace_id
        if not dataset_id:
            raise EmbedError("The report response has no datasetId.")

        dataset = self._client.get_dataset(dataset_ws, dataset_id) or {}
        roles_required = bool(dataset.get("isEffectiveIdentityRolesRequired"))
        self._log(
            f"Dataset {dataset_id}: RLS roles {'required' if roles_required else 'not required'}."
        )

        datasets = [{"id": dataset_id, "xmlaPermissions": "ReadOnly"}]
        for extra in extra_dataset_ids or ():
            if extra and extra != dataset_id:
                datasets.append({"id": extra, "xmlaPermissions": "ReadOnly"})

        body: dict = {
            "datasets": datasets,
            "reports": [{"id": report_id}],
            "targetWorkspaces": [{"id": workspace_id}],
        }

        if roles_required:
            if not self.rls_username:
                raise EmbedError(
                    "The dataset requires RLS roles, but the RLS username is not set."
                )
            if not self.rls_roles:
                raise EmbedError(
                    "The dataset requires RLS roles, but the role list is empty."
                )
            identity_datasets = [item["id"] for item in datasets]
            body["identities"] = [
                {
                    "username": self.rls_username,
                    "roles": self.rls_roles,
                    "datasets": identity_datasets,
                }
            ]
            self._log(
                f"Identitas RLS: {self.rls_username} "
                f"({', '.join(self.rls_roles)})."
            )
        elif self.rls_username:
            body["identities"] = [
                {
                    "username": self.rls_username,
                    "roles": self.rls_roles,
                    "datasets": [],
                }
            ]

        embed_token = self._client.generate_embed_token(body)
        self._log(f"Embed token received ({len(embed_token)} karakter).")
        return embed_token
