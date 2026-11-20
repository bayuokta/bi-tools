"""Deteksi subscription report via Power BI Admin REST (read-only).

Endpoint ``GET admin/reports/{reportId}/subscriptions`` dipakai untuk
mengetahui report yang masih dikirim lewat email. Datanya **bukan** pemetaan
field; nilainya adalah bukti bahwa report (termasuk RDL/personal yang tidak
bisa dipindai) masih dipakai, sehingga kolom tanpa referensi tidak boleh
langsung dilaporkan "Tidak dipakai".

Batasan yang disengaja:

- Hanya untuk report yang tidak bisa dipindai (RDL, personal, inaccessible).
  Kuota endpoint ini 200 request/jam, jadi pemanggilan massal tidak aman.
- Hasil di-cache (``SUBSCRIPTION_TTL_HOURS``) oleh ``core.usage_store``.
- Data alert **tidak** terdeteksi karena tidak ada admin API untuk alert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

SUBSCRIPTION_TTL_HOURS = 24
MAX_SUBSCRIPTION_REPORTS = 25


@dataclass(frozen=True)
class SubscriptionInfo:
    """Satu subscription report dari Admin REST."""

    report_id: str
    subscription_id: str
    title: str = ""
    artifact_type: str = ""
    page_name: str = ""
    frequency: str = ""
    is_enabled: bool = False
    attachment_format: str = ""
    start_date: str = ""
    end_date: str = ""
    receivers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def receiver_count(self) -> int:
        return len(self.receivers)

    def payload(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "subscription_id": self.subscription_id,
            "title": self.title,
            "artifact_type": self.artifact_type,
            "page_name": self.page_name,
            "frequency": self.frequency,
            "is_enabled": bool(self.is_enabled),
            "attachment_format": self.attachment_format,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "receiver_count": self.receiver_count,
            "receivers": list(self.receivers),
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _receivers(row: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for user in row.get("users") or []:
        if not isinstance(user, Mapping):
            continue
        label = _text(user.get("emailAddress")) or _text(user.get("identifier"))
        if label:
            values.append(label)
    return tuple(values)


def parse_subscriptions(
    report_id: str, rows: Iterable[Any] | None
) -> list[SubscriptionInfo]:
    """Ubah ``value[]`` Admin REST menjadi daftar :class:`SubscriptionInfo`."""
    items: list[SubscriptionInfo] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        subscription_id = _text(row.get("id"))
        if not subscription_id:
            continue
        items.append(
            SubscriptionInfo(
                report_id=str(report_id),
                subscription_id=subscription_id,
                title=_text(row.get("title")),
                artifact_type=_text(row.get("artifactType")),
                # Admin API hanya memberi nama halaman, bukan page id.
                page_name=_text(row.get("subArtifactDisplayName")),
                frequency=_text(row.get("frequency")),
                is_enabled=bool(row.get("isEnabled")),
                attachment_format=_text(row.get("attachmentFormat")),
                start_date=_text(row.get("startDate")),
                end_date=_text(row.get("endDate")),
                receivers=_receivers(row),
            )
        )
    return items


def has_enabled(items: Iterable[SubscriptionInfo]) -> bool:
    """True bila ada subscription yang masih aktif."""
    return any(item.is_enabled for item in items)


def unmapped_reports(
    candidates: Iterable[str], by_report: Mapping[str, list[SubscriptionInfo]]
) -> int:
    """Jumlah report tak terpindai yang punya subscription aktif."""
    return sum(
        1
        for report_id in candidates
        if has_enabled(by_report.get(report_id, []))
    )
