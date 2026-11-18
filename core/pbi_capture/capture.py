"""Screenshot page & visual Power BI lewat embedded JS client + Playwright.

REST API Power BI tidak punya endpoint daftar visual (``GET /pages/{id}/visuals``
-> 404), jadi enumerasi dilakukan lewat **powerbi-client** di browser:

1. Halaman lokal (127.0.0.1) memuat report dengan **embed token + RLS**.
2. ``report.getPages()`` -> daftar page.
3. ``page.getVisuals()`` -> nama, type, title, layout tiap visual.
4. Screenshot:
   - per page   -> elemen ``#reportContainer`` (termasuk isi iframe),
   - per visual -> elemen ``.visualContainer`` di iframe report, dipasangkan
     ke hasil ``getVisuals()`` memakai hint posisi absolut dari workbook
     (``position_x_abs``) lalu pencocokan label/ukuran yang ketat; visual yang
     tidak yakin dibiarkan tanpa gambar, lalu bookmark report dicoba satu per
     satu untuk memunculkan visual yang tersembunyi.

Port dari tool ``pbi-download-image`` (lihat AGENTS.md tool tersebut). Jangan
mengubah algoritma pairing tanpa alasan kuat: koordinat ``visual.layout`` tidak
selalu absolut untuk visual di dalam group/container.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping

try:
    from playwright.sync_api import sync_playwright
except ImportError as _exc:  # pragma: no cover - tergantung environment
    sync_playwright = None
    _PLAYWRIGHT_IMPORT_ERROR = _exc

from ..errors import ExtractionError

from .browsers import install_chromium, missing_browser

Log = Callable[[str], None]


def _silent(_message: str) -> None:
    pass


# Selector kandidat elemen visual di dalam iframe report (diuji berurutan)
_VISUAL_SELECTORS = [
    ".visualContainer",
    '[class*="visualContainer"]',
    ".visuals > div",
]

# Probe DOM: kumpulkan rect tiap kandidat visual pertama yang ditemukan
_PROBE_JS = """
() => {
  const sels = %s;
  for (const s of sels) {
    const els = Array.from(document.querySelectorAll(s));
    if (els.length) {
      return {
        selector: s,
        rects: els.map((e, i) => {
          const r = e.getBoundingClientRect();
          return {
            i: i,
            x: r.x, y: r.y, w: r.width, h: r.height,
            label: e.getAttribute('aria-label') || ''
          };
        })
      };
    }
  }
  return { selector: null, rects: [] };
}
""" % json.dumps(_VISUAL_SELECTORS)

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdnjs.cloudflare.com/ajax/libs/powerbi-client/2.19.1/powerbi.min.js"></script>
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: #fff; }
  #reportContainer { width: 100%; height: 100vh; }
</style>
</head>
<body>
<div id="reportContainer"></div>
<script>
window.__loaded = false;
window.__error = null;
(function () {
  const models = window['powerbi-client'].models;
  const report = window.powerbi.embed(document.getElementById('reportContainer'), {
    type: 'report',
    tokenType: models.TokenType.Embed,
    accessToken: __TOKEN__,
    embedUrl: __EMBED_URL__,
    id: __REPORT_ID__,
    permissions: models.Permissions.All,
    settings: {
      bars: { statusBar: { visible: false } },
      layoutType: __LAYOUT_TYPE__
    }
  });
  window.__report = report;
  report.on('loaded', function () { window.__loaded = true; });
  report.on('error', function (e) {
    window.__error = JSON.stringify((e && e.detail) || e);
  });

  // Penghitung render: event 'rendered' fire setiap report selesai render
  window.__renderCount = 0;
  report.on('rendered', function () { window.__renderCount += 1; });

  // Tunggu sampai render count >= minCount (atau timeout dlm ms)
  window.__waitRender = function (ms, minCount) {
    return new Promise(function (resolve) {
      if (window.__renderCount >= minCount) { resolve(true); return; }
      const started = Date.now();
      const timer = setInterval(function () {
        if (window.__renderCount >= minCount) {
          clearInterval(timer); resolve(true);
        } else if (Date.now() - started >= ms) {
          clearInterval(timer); resolve(false);
        }
      }, 100);
    });
  };

  // Pindah page + tunggu render; 'same' bila sudah aktif
  window.__setPage = async function (name, ms) {
    try {
      const active = await report.getActivePage();
      if (active && active.name === name) return 'same';
    } catch (e) {}
    const minCount = window.__renderCount + 1;
    await report.setPage(name);
    const ok = await window.__waitRender(ms, minCount);
    return ok ? 'rendered' : 'timeout';
  };

  window.__getPages = async function () {
    const pages = await report.getPages();
    const result = [];
    for (let i = 0; i < pages.length; i += 1) {
      const p = pages[i];
      let hasMobile = false;
      try {
        hasMobile = await p.hasLayout(models.LayoutType.MobilePortrait);
      } catch (e) {}
      result.push({
        name: p.name,
        displayName: p.displayName,
        isActive: !!p.isActive,
        mobileSize: p.mobileSize || null,
        hasMobileLayout: !!hasMobile
      });
    }
    return result;
  };

  window.__getVisuals = async function (pageName) {
    const pages = await report.getPages();
    const p = pages.find(function (x) { return x.name === pageName; })
           || pages.find(function (x) { return x.displayName === pageName; });
    if (!p) return null;
    const visuals = await p.getVisuals();
    return visuals.map(function (v) {
      return { name: v.name, type: v.type, title: v.title || null, layout: v.layout || null };
    });
  };

  // Bookmark: dipakai untuk membuka panel filter yang menyembunyikan visual.
  window.__getBookmarks = async function () {
    try {
      const list = await report.bookmarksManager.getBookmarks();
      return list.map(function (b) {
        return { name: b.name, displayName: b.displayName || b.name };
      });
    } catch (e) { return []; }
  };

  window.__applyBookmark = async function (name, ms) {
    try {
      const minCount = window.__renderCount + 1;
      await report.bookmarksManager.apply(name);
      const ok = await window.__waitRender(ms, minCount);
      return !!ok;
    } catch (e) { return false; }
  };

  // Simpan/pulihkan state supaya percobaan bookmark tidak mengubah report.
  window.__savedState = null;
  window.__saveState = async function () {
    try {
      window.__savedState = await report.bookmarksManager.capture();
      return !!window.__savedState;
    } catch (e) { window.__savedState = null; return false; }
  };

  window.__restoreState = async function (ms) {
    if (!window.__savedState) return false;
    try {
      const minCount = window.__renderCount + 1;
      await report.bookmarksManager.applyState(window.__savedState);
      return !!await window.__waitRender(ms, minCount);
    } catch (e) { return false; }
  };

  window.__getActivePage = async function () {
    try {
      const page = await report.getActivePage();
      return page && page.name ? page.name : "";
    } catch (e) { return ""; }
  };
})();
</script>
</body>
</html>
"""


# Probe bookmark: jumlah percobaan dan timeout render per percobaan.
PROBE_LIMIT = 12
PROBE_TIMEOUT_MS = 4000

# Toleransi piksel saat mencocokkan hint posisi absolut (PBIR) dengan DOM.
HINT_TOLERANCE = 3.0

# Mobile layout: ukuran canvas bawaan Power BI dan batas viewport screenshot.
MOBILE_DEFAULT_WIDTH = 375
MOBILE_DEFAULT_HEIGHT = 667
MOBILE_MIN_WIDTH = 240
MOBILE_MAX_WIDTH = 1200
MOBILE_MIN_HEIGHT = 320
MOBILE_MAX_HEIGHT = 4000


def mobile_viewport(mobile_size: dict | None) -> tuple[int, int]:
    """Ukuran viewport untuk screenshot mobile dari ``page.mobileSize``.

    Nilai yang hilang/tidak masuk akal memakai canvas mobile bawaan Power BI
    (375x667). Batas atas mencegah viewport raksasa bila metadata rusak.
    """

    def dimension(
        key: str,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        raw = (mobile_size or {}).get(key)
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            return default
        if value < minimum:
            return default
        return min(value, maximum)

    width = dimension("width", MOBILE_DEFAULT_WIDTH, MOBILE_MIN_WIDTH, MOBILE_MAX_WIDTH)
    height = dimension(
        "height", MOBILE_DEFAULT_HEIGHT, MOBILE_MIN_HEIGHT, MOBILE_MAX_HEIGHT
    )
    return width, height


class CaptureError(ExtractionError):
    """Gagal memuat/menangkap report di browser."""


# --------------------------------------------------------------------- pairing
def _norm_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str | None) -> set:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _estimate_scale(visuals: list[dict], rects: list[dict]) -> float:
    """Estimasi skala unit halaman -> piksel dari median rasio tinggi."""
    vis_h = sorted(
        [((v.get("layout") or {}).get("height") or 0) for v in visuals],
        reverse=True,
    )
    rec_h = sorted([r["h"] for r in rects], reverse=True)
    ratios = [
        rec_h[i] / vis_h[i]
        for i in range(min(len(vis_h), len(rec_h)))
        if vis_h[i] > 5 and rec_h[i] > 5
    ]
    scale = sorted(ratios)[len(ratios) // 2] if ratios else 1.0
    if not (0.2 < scale < 10.0):
        scale = 1.0
    return scale


def _same_size(first: dict, second: dict) -> bool:
    """Apakah dua visual punya ukuran layout yang praktis sama."""
    a = first.get("layout") or {}
    b = second.get("layout") or {}
    aw, ah = a.get("width") or 0, a.get("height") or 0
    bw, bh = b.get("width") or 0, b.get("height") or 0
    return abs(aw - bw) <= max(1.0, 0.01 * max(aw, bw)) and abs(
        ah - bh
    ) <= max(1.0, 0.01 * max(ah, bh))


def _hint_canvas_offset(
    visuals: list[dict],
    rects: list[dict],
    hints: Mapping[str, tuple[float, float, float, float]],
    scale: float,
) -> tuple[float, float] | None:
    """Estimasi offset canvas (px) dari hint posisi absolut.

    Hint berisi koordinat absolut halaman; DOM berada di dalam viewport yang
    memusatkan halaman, jadi selisihnya konstan. Offset diambil dari selisih
    yang paling sering muncul di antara hint yang ukurannya cocok, sehingga
    tidak bergantung pada label visual. Minimal dua visual harus sepakat:
    satu hint saja selalu bisa "menjelaskan" posisi apa pun, jadi lebih baik
    jatuh ke pencocokan label/ukuran daripada menebak.
    """
    counts: dict[tuple[int, int], int] = {}
    for visual in visuals:
        hint = hints.get(visual.get("name") or "")
        if not hint:
            continue
        hint_x, hint_y, hint_w, hint_h = hint
        pred_w, pred_h = hint_w * scale, hint_h * scale
        for rect in rects:
            if abs(rect["w"] - pred_w) > max(3.0, 0.02 * pred_w):
                continue
            if abs(rect["h"] - pred_h) > max(3.0, 0.02 * pred_h):
                continue
            key = (round(rect["x"] - hint_x * scale), round(rect["y"] - hint_y * scale))
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    (offset_x, offset_y), count = max(counts.items(), key=lambda item: item[1])
    if count < 2:
        return None
    return float(offset_x), float(offset_y)


def _hint_scale(
    visuals: list[dict],
    rects: list[dict],
    hints: Mapping[str, tuple[float, float, float, float]],
) -> float | None:
    """Estimasi skala page-unit -> px dari hint ukuran (mode rasio).

    Daftar visual API dan elemen DOM tidak selalu sama panjang (visual hidden
    tidak dirender, objek dekoratif dikecualikan), sehingga rasio median dari
    dua daftar terurut bisa melenceng. Hint ukuran memberi pasangan yang pasti.
    Minimal dua visual harus sepakat; bila tidak, pemanggil memakai estimasi
    median biasa.
    """
    counts: dict[float, int] = {}
    for visual in visuals:
        hint = hints.get(visual.get("name") or "")
        if not hint:
            continue
        hint_w, hint_h = hint[2], hint[3]
        if hint_w <= 0 or hint_h <= 0:
            continue
        for rect in rects:
            ratio_w = rect["w"] / hint_w
            ratio_h = rect["h"] / hint_h
            if abs(ratio_w - ratio_h) > 0.02 * max(ratio_w, ratio_h):
                continue
            if not 0.2 < ratio_w < 5.0:
                continue
            key = round(ratio_w, 2)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    value, count = max(counts.items(), key=lambda item: item[1])
    if count < 2:
        return None
    return float(value)


def pair_visuals_to_rects(
    visuals: list[dict],
    rects: list[dict],
    log: Log = _silent,
    *,
    scale: float | None = None,
    hints: Mapping[str, tuple[float, float, float, float]] | None = None,
) -> dict[str, dict | None]:
    """Pasangkan visual (getVisuals) dengan elemen DOM (``.visualContainer``).

    Koordinat ``layout`` dari powerbi-client TIDAK selalu absolut (visual yang
    bersarang dalam group/container memakai koordinat relatif), sehingga
    pencocokan murni-posisi tidak andal. Algoritma:

    Pass H - hint posisi absolut dari workbook report (``position_x_abs`` /
             ``position_y_abs``): offset canvas diestimasi dari hint yang
             ukurannya cocok, lalu visual dipasangkan ke elemen dengan posisi
             hampir sama (toleransi beberapa piksel). Ini menyelesaikan visual
             di dalam group tanpa menebak.
    Pass A - label: ``aria-label`` DOM mengandung judul visual (atau berbagi
             token makna, mis. "KTP" pada tombol info).
    Pass B - ukuran + posisi: estimasi skala page->px dari median tinggi
             (urut) kedua daftar; kandidat rect berukuran cocok lalu dipilih
             yang terdekat. Pasangan hanya diterima bila jaraknya wajar.
    Pass C - ukuran unik: bila ukuran visual tidak dimiliki visual lain dan
             hanya ada satu elemen tersisa berukuran itu tanpa label, pasangan
             dipakai. Ini menangani visual di dalam group (koordinat relatif)
             tanpa membaca urutan baca. Elemen berlabel (mis. logo) tidak
             dipinjam karena labelnya milik identitas lain.

    Visual yang tidak yakin dibiarkan ``None`` (mis. visual hidden yang tidak
    dirender) daripada meminjam elemen dekoratif lain.

    Mengembalikan ``{visual_name: rect | None}``. Rect yang sudah terpakai
    tidak dipakai ulang (satu elemen = satu visual).
    """
    result: dict[str, dict | None] = {v.get("name"): None for v in visuals}
    if not visuals or not rects:
        return result

    used: set = set()
    hint_map = hints or {}

    # --- estimasi skala page-unit -> pixel iframe
    # Hint ukuran dipakai lebih dulu (pasangan pasti); cadangan median pasangan
    # tinggi terurut untuk capture tanpa hint. Untuk pass kedua (setelah
    # bookmark), skala dari pass pertama harus dipakai ulang karena daftar visual
    # tinggal sebagian dan rasio median jadi melenceng.
    if scale is None and hint_map:
        scale = _hint_scale(visuals, rects, hint_map)
    if scale is None:
        scale = _estimate_scale(visuals, rects)

    def size_ok(visual: dict, rect: dict) -> bool:
        lay = visual.get("layout") or {}
        lw, lh = lay.get("width") or 0, lay.get("height") or 0
        if lw <= 0 or lh <= 0:
            return False
        pw, ph = lw * scale, lh * scale
        return abs(rect["w"] - pw) <= max(6, 0.18 * pw) and abs(
            rect["h"] - ph
        ) <= max(6, 0.18 * ph)

    # --- Pass H: hint posisi absolut (group + canvas offset)
    if hint_map:
        offset = _hint_canvas_offset(visuals, rects, hint_map, scale)
        if offset is not None:
            offset_x, offset_y = offset
            for visual in visuals:
                name = visual.get("name") or ""
                hint = hint_map.get(name)
                if not hint or result.get(name) is not None:
                    continue
                hint_x, hint_y, hint_w, hint_h = hint
                pred_x = hint_x * scale + offset_x
                pred_y = hint_y * scale + offset_y
                pred_w = hint_w * scale
                pred_h = hint_h * scale
                matches = [
                    idx
                    for idx, rect in enumerate(rects)
                    if idx not in used
                    and abs(rect["x"] - pred_x) <= HINT_TOLERANCE
                    and abs(rect["y"] - pred_y) <= HINT_TOLERANCE
                    and abs(rect["w"] - pred_w) <= max(3.0, 0.02 * pred_w)
                    and abs(rect["h"] - pred_h) <= max(3.0, 0.02 * pred_h)
                ]
                if len(matches) == 1:
                    used.add(matches[0])
                    result[name] = rects[matches[0]]

    # --- Pass A1: label sama persis (hindari "Dealer" vs "Main Dealer")
    for visual in visuals:
        title = _norm_text(visual.get("title"))
        if not title:
            continue
        for idx, rect in enumerate(rects):
            if idx in used:
                continue
            if _norm_text(rect.get("label")) != title:
                continue
            if not size_ok(visual, rect):
                continue
            used.add(idx)
            result[visual.get("name")] = rects[idx]
            break

    # --- Pass A2: cocokkan via aria-label (substring / token bersama)
    for visual in visuals:
        name = visual.get("name")
        if result.get(name) is not None:
            continue
        title = _norm_text(visual.get("title"))
        if not title:
            continue
        title_tokens = _tokens(title)
        lay = visual.get("layout") or {}
        pred_x = (lay.get("x") or 0) * scale
        pred_y = (lay.get("y") or 0) * scale
        best_idx, best_score, best_dist = None, 0, 0.0
        for idx, rect in enumerate(rects):
            if idx in used:
                continue
            label = _norm_text(rect.get("label"))
            if not label or not size_ok(visual, rect):
                continue
            if title in label or label in title:
                score = 100
            else:
                shared = title_tokens & _tokens(label)
                score = len(shared)
            if score <= 0:
                continue
            distance = abs(rect["x"] - pred_x) + abs(rect["y"] - pred_y)
            if score > best_score or (
                score == best_score and distance < best_dist
            ):
                best_idx, best_score, best_dist = idx, score, distance
        if best_idx is not None and best_score > 0:
            used.add(best_idx)
            result[name] = rects[best_idx]

    # --- Pass B: ukuran lalu posisi terdekat (hanya bila posisi wajar)
    page_w = max((r["x"] + r["w"] for r in rects), default=0)
    threshold = max(80.0, 0.12 * page_w)
    for visual in visuals:
        name = visual.get("name")
        if result.get(name) is not None:
            continue
        candidates = [
            idx
            for idx, rect in enumerate(rects)
            if idx not in used and size_ok(visual, rect)
        ]
        if not candidates:
            continue
        lay = visual.get("layout") or {}
        pred_x = (lay.get("x") or 0) * scale
        pred_y = (lay.get("y") or 0) * scale

        def dist(idx: int) -> float:
            rect = rects[idx]
            return abs(rect["x"] - pred_x) + abs(rect["y"] - pred_y)

        nearest = min(candidates, key=dist)
        # Jangan meminjam elemen dekoratif yang jauh hanya karena ukurannya
        # mirip: lebih baik visual dianggap tidak tersedia (hidden).
        if dist(nearest) > threshold:
            continue
        used.add(nearest)
        result[name] = rects[nearest]

    # --- Pass C: ukuran visual unik di halaman, tepat satu elemen tersisa
    # Layout visual di dalam group/container memakai koordinat relatif terhadap
    # group, sehingga prediksi posisi bisa meleset jauh walau elemennya ada
    # (mis. KPI card di group "Card"). Bila ukuran visual tidak dimiliki visual
    # lain dan hanya ada satu elemen tersisa dengan ukuran itu, pasangan aman
    # dipakai. Ukuran yang sama pada beberapa visual sengaja dibiarkan kosong
    # agar tidak menebak/meminjam elemen dekoratif.
    for visual in visuals:
        name = visual.get("name")
        if result.get(name) is not None:
            continue
        if any(
            other is not visual and _same_size(visual, other) for other in visuals
        ):
            continue
        candidates = [
            idx
            for idx, rect in enumerate(rects)
            if idx not in used
            and size_ok(visual, rect)
            and not str(rect.get("label") or "").strip()
        ]
        if len(candidates) != 1:
            continue
        used.add(candidates[0])
        result[name] = rects[candidates[0]]

    unmatched = sum(1 for v in result.values() if v is None)
    if unmatched:
        log(f"{unmatched} visual tidak memiliki pasangan elemen DOM.")
    return result


# ------------------------------------------------------------------- capturer
class ReportCapturer:
    """Sesi Playwright: buka embed, enumerasi, screenshot page/visual."""

    def __init__(
        self,
        report_id: str,
        workspace_id: str,
        embed_token: str,
        *,
        headless: bool = True,
        viewport_width: int = 1600,
        viewport_height: int = 1000,
        scale_factor: float = 1,
        render_timeout_ms: int = 20000,
        settle_ms: int = 800,
        debug_dir: str | None = None,
        layout_type: int = 0,
        auto_install: bool = True,
        log: Log = _silent,
    ) -> None:
        if sync_playwright is None:
            raise CaptureError(
                "Playwright belum terpasang. Dari source: 'pip install playwright' "
                "lalu 'python -m playwright install chromium'. Di aplikasi "
                "terpaket: jalankan 'bi-tools-cli install-browser' "
                f"(import error: {_PLAYWRIGHT_IMPORT_ERROR})"
            )
        self.report_id = report_id
        self.workspace_id = workspace_id
        self.embed_token = embed_token
        self.headless = headless
        self.viewport = {"width": viewport_width, "height": viewport_height}
        self.scale_factor = scale_factor
        self.render_timeout_ms = render_timeout_ms
        self.settle_ms = settle_ms
        self.debug_dir = debug_dir
        self.layout_type = int(layout_type)
        self.auto_install = bool(auto_install)
        self._log = log

        self._server: ThreadingHTTPServer | None = None
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None

    # ------------------------------------------------------------- lifecycle
    def open(self) -> "ReportCapturer":
        embed_url = (
            "https://app.powerbi.com/reportEmbed"
            f"?reportId={self.report_id}&groupId={self.workspace_id}"
            "&navContentPaneEnabled=false&filterPaneEnabled=false"
        )
        html = (
            _HTML_TEMPLATE.replace("__TOKEN__", json.dumps(self.embed_token))
            .replace("__EMBED_URL__", json.dumps(embed_url))
            .replace("__REPORT_ID__", json.dumps(self.report_id))
            .replace("__LAYOUT_TYPE__", str(self.layout_type))
        )

        handler = type("_HtmlHandler", (BaseHTTPRequestHandler,), {})
        handler.html = html.encode("utf-8")

        def _respond(srv_self):
            srv_self.send_response(200)
            srv_self.send_header("Content-Type", "text/html; charset=utf-8")
            srv_self.send_header("Content-Length", str(len(handler.html)))
            srv_self.end_headers()
            srv_self.wfile.write(handler.html)

        handler.do_GET = _respond
        handler.log_message = lambda *a, **k: None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        port = self._server.server_address[1]

        try:
            self._pw = sync_playwright().start()
            self._browser = self._launch_browser()
        except Exception as exc:  # noqa: BLE001 - pesan Playwright
            self.close()
            raise CaptureError(
                "Chromium untuk screenshot belum tersedia. Di aplikasi terpaket "
                "jalankan 'bi-tools-cli install-browser', atau dari source "
                "'python -m playwright install chromium', lalu ulangi capture. "
                f"Detail: {exc}"
            ) from exc
        self._ctx = self._browser.new_context(
            viewport=self.viewport, device_scale_factor=self.scale_factor
        )
        self._page = self._ctx.new_page()
        self._log(f"Membuka embed report (headless={self.headless}) ...")
        self._page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")

        # Tunggu loaded ATAU error dari powerbi-client
        try:
            self._page.wait_for_function(
                "window.__loaded === true || window.__error", timeout=30000
            )
        except Exception as exc:  # noqa: BLE001 - pesan Playwright
            raise CaptureError(
                f"Report gagal dimuat dalam 30 detik: {exc}"
            ) from exc
        err = self._page.evaluate("() => window.__error")
        if err:
            raise CaptureError(f"powerbi-client error saat load: {err}")

        # Render pertama: tunggu minimal 1x render selesai
        self._page.evaluate(
            "([ms]) => window.__waitRender(ms, 1)", [self.render_timeout_ms]
        )
        self._page.wait_for_timeout(self.settle_ms)
        self._log("Report siap di-capture.")
        return self

    def _launch_browser(self):
        """Launch Chromium; unduh sekali bila browser belum ada."""
        try:
            return self._pw.chromium.launch(headless=self.headless)
        except Exception as exc:  # noqa: BLE001 - pesan Playwright
            if not (self.auto_install and missing_browser(exc)):
                raise
            self._log(
                "Chromium belum tersedia; mengunduh otomatis sekali "
                "(sekitar 150 MB) ..."
            )
            install_chromium(self._log)
            self._log("Chromium terpasang; mengulang launch.")
            return self._pw.chromium.launch(headless=self.headless)

    def close(self) -> None:
        def _stop_server() -> None:
            if not self._server:
                return
            self._server.shutdown()
            # Tanpa server_close() socket tetap terbuka (ResourceWarning).
            self._server.server_close()
            self._server = None

        for closer in (
            lambda: self._ctx and self._ctx.close(),
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
            _stop_server,
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass

    def __enter__(self) -> "ReportCapturer":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------------- halaman
    def _goto_page(self, page_name: str) -> None:
        status = self._page.evaluate(
            "([name, ms]) => window.__setPage(name, ms)",
            [page_name, self.render_timeout_ms],
        )
        if status == "timeout":
            self._log(
                f"Event 'rendered' tidak datang untuk page {page_name}; "
                "lanjut setelah settle."
            )
        self._page.wait_for_timeout(self.settle_ms)

    def _report_frame(self):
        for frame in self._page.frames:
            if frame is self._page.main_frame:
                continue
            if "powerbi" in frame.url or "reportEmbed" in frame.url:
                return frame
        for frame in self._page.frames:
            if frame is not self._page.main_frame:
                return frame
        raise CaptureError("iframe report tidak ditemukan.")

    # ----------------------------------------------------------- API publik
    def list_pages(self) -> list[dict]:
        return self._page.evaluate("() => window.__getPages()")

    def inspect_page(self, page_name: str) -> list[dict]:
        """Pindah ke page lalu ambil metadata visual (tanpa screenshot)."""
        self._goto_page(page_name)
        visuals = self._page.evaluate(
            "(name) => window.__getVisuals(name)", page_name
        )
        if visuals is None:
            raise CaptureError(f"Page {page_name} tidak ditemukan di report.")
        return visuals

    def probe_visual_elements(self) -> dict:
        """Cek apakah elemen visual ada di DOM iframe (selector + rect)."""
        frame = self._report_frame()
        return frame.evaluate(_PROBE_JS)

    def get_bookmarks(self) -> list[dict]:
        """Daftar bookmark report (nama internal + display name)."""
        try:
            data = self._page.evaluate("() => window.__getBookmarks()")
        except Exception as exc:  # noqa: BLE001 - bookmark opsional
            self._log(f"Bookmark tidak bisa dibaca: {exc}")
            return []
        return [item for item in data or [] if isinstance(item, dict)]

    def apply_bookmark(self, name: str, timeout_ms: int | None = None) -> bool:
        """Terapkan bookmark lalu tunggu render berikutnya."""
        if not name:
            return False
        try:
            ok = self._page.evaluate(
                "([name, ms]) => window.__applyBookmark(name, ms)",
                [name, timeout_ms or self.render_timeout_ms],
            )
        except Exception as exc:  # noqa: BLE001 - bookmark opsional
            self._log(f"Bookmark '{name}' gagal diterapkan: {exc}")
            return False
        self._page.wait_for_timeout(self.settle_ms)
        return bool(ok)

    def save_bookmark_state(self) -> bool:
        """Simpan state report sebelum mencoba bookmark."""
        try:
            return bool(self._page.evaluate("() => window.__saveState()"))
        except Exception as exc:  # noqa: BLE001 - state opsional
            self._log(f"State report tidak bisa disimpan: {exc}")
            return False

    def restore_bookmark_state(self, timeout_ms: int | None = None) -> bool:
        """Pulihkan state report setelah percobaan bookmark."""
        try:
            ok = self._page.evaluate(
                "([ms]) => window.__restoreState(ms)",
                [timeout_ms or self.render_timeout_ms],
            )
        except Exception as exc:  # noqa: BLE001 - state opsional
            self._log(f"State report tidak bisa dipulihkan: {exc}")
            return False
        self._page.wait_for_timeout(self.settle_ms)
        return bool(ok)

    def active_page_name(self) -> str:
        """Nama internal halaman yang sedang aktif."""
        try:
            return str(self._page.evaluate("() => window.__getActivePage()") or "")
        except Exception:  # noqa: BLE001 - halaman opsional
            return ""

    def _capture_mapping(
        self,
        frame,
        selector: str,
        mapping: dict[str, dict | None],
        target: dict[str, bytes],
    ) -> int:
        """Screenshot tiap visual yang sudah punya pasangan DOM."""
        handles = frame.query_selector_all(selector)
        handle_by_index = {i: handle for i, handle in enumerate(handles)}
        captured = 0
        for visual_name, rect in mapping.items():
            if not rect:
                continue
            handle = handle_by_index.get(rect["i"])
            if handle is None:
                continue
            try:
                target[visual_name] = handle.screenshot(type="png")
                captured += 1
            except Exception as exc:  # noqa: BLE001 - lanjut visual lain
                self._log(f"Gagal screenshot visual {visual_name}: {exc}")
        return captured

    def _probe_reveal(
        self,
        page_name: str,
        missing: list[dict],
        scale: float,
        result: dict,
        hints: Mapping[str, tuple[float, float, float, float]] | None = None,
    ) -> bool:
        """Coba bookmark satu per satu sampai visual yang hilang muncul.

        Nama bookmark tidak dipakai sebagai penanda; keberhasilan dinilai dari
        munculnya elemen DOM untuk visual yang tadi tidak terpetakan. State
        report disimpan sebelum percobaan dan dipulihkan sesudahnya.
        """
        bookmarks = self.get_bookmarks()
        if not bookmarks:
            self._log("Tidak ada bookmark untuk mencoba membuka visual tersembunyi.")
            return False
        if not self.save_bookmark_state():
            self._log("State report tidak bisa disimpan; probe bookmark dilewati.")
            return False

        captured = False
        for bookmark in bookmarks[:PROBE_LIMIT]:
            name = str(bookmark.get("name") or "")
            if not name:
                continue
            self._log(
                f"Mencoba bookmark '{bookmark.get('displayName') or name}' ..."
            )
            if not self.apply_bookmark(name, PROBE_TIMEOUT_MS):
                self.restore_bookmark_state(PROBE_TIMEOUT_MS)
                continue
            if self.active_page_name() != page_name:
                self.restore_bookmark_state(PROBE_TIMEOUT_MS)
                continue
            frame = self._report_frame()
            probe = frame.evaluate(_PROBE_JS)
            rects = probe.get("rects") or []
            selector = probe.get("selector")
            if not rects or not selector:
                self.restore_bookmark_state(PROBE_TIMEOUT_MS)
                continue
            mapping = pair_visuals_to_rects(
                missing, rects, self._log, scale=scale, hints=hints
            )
            count = self._capture_mapping(
                frame, selector, mapping, result["visual_pngs"]
            )
            if count:
                result["revealed_bookmark"] = name
                self._log(
                    f"Bookmark '{bookmark.get('displayName') or name}' "
                    f"memunculkan {count} visual."
                )
                captured = True
                break
            self.restore_bookmark_state(PROBE_TIMEOUT_MS)

        self.restore_bookmark_state(PROBE_TIMEOUT_MS)
        return captured

    def capture_page(
        self,
        page_name: str,
        *,
        want_page_png: bool = True,
        want_visual_pngs: bool = True,
        exclude_types: tuple[str, ...] = (),
        reveal_bookmarks: bool = True,
        hints: Mapping[str, tuple[float, float, float, float]] | None = None,
    ) -> dict:
        """Screenshot per page dan/atau per visual pada satu page.

        ``hints`` berisi posisi absolut visual (dari workbook report) untuk
        mencocokkan elemen DOM visual di dalam group; tanpa hint dipakai
        pencocokan label/ukuran. Visual yang dikecualikan (dekoratif) tidak ikut
        pairing, sehingga tidak bisa meminjam elemen DOM visual lain. Bila masih
        ada visual tanpa pasangan (mis. slicer di panel filter yang
        disembunyikan), bookmark report dicoba satu per satu; nama bookmark
        tidak dipakai, yang dinilai adalah munculnya elemen DOM visual tersebut.

        Mengembalikan ``{page_png, visuals, visual_pngs, debug, revealed_bookmark}``.
        """
        self._goto_page(page_name)
        visuals = self._page.evaluate(
            "(name) => window.__getVisuals(name)", page_name
        )
        if visuals is None:
            raise CaptureError(f"Page {page_name} tidak ditemukan di report.")

        result: dict = {
            "page_png": None,
            "visuals": visuals,
            "visual_pngs": {},
            "debug": None,
            "revealed_bookmark": "",
        }

        if want_page_png:
            result["page_png"] = self._page.locator(
                "#reportContainer"
            ).screenshot(type="png")

        excluded = {str(item).lower() for item in exclude_types if item}
        capturable = [
            visual
            for visual in visuals
            if str(visual.get("type") or "").lower() not in excluded
        ]
        if not want_visual_pngs or not capturable:
            return result

        frame = self._report_frame()
        probe = frame.evaluate(_PROBE_JS)
        rects = probe.get("rects") or []
        if not rects:
            result["debug"] = (
                "Elemen visual tidak ditemukan di DOM iframe "
                f"(selector dicoba: {_VISUAL_SELECTORS})"
            )
            self._log(result["debug"])
            self._save_debug(page_name)
            return result

        scale = _hint_scale(visuals, rects, hints or {})
        if scale is None:
            scale = _estimate_scale(visuals, rects)
        mapping = pair_visuals_to_rects(
            capturable, rects, self._log, scale=scale, hints=hints
        )
        self._capture_mapping(
            frame, probe["selector"], mapping, result["visual_pngs"]
        )

        missing = [
            visual
            for visual in capturable
            if visual.get("name") not in result["visual_pngs"]
        ]
        if not missing:
            return result
        if not reveal_bookmarks:
            self._log(f"{len(missing)} visual tetap tanpa gambar (tidak dirender).")
            return result

        self._probe_reveal(page_name, missing, scale, result, hints)
        still_missing = [
            visual
            for visual in capturable
            if visual.get("name") not in result["visual_pngs"]
        ]
        if still_missing:
            self._log(
                f"{len(still_missing)} visual tetap tanpa gambar setelah probe "
                "bookmark (tidak ada bookmark yang memunculkannya)."
            )
        return result

    def capture_mobile_page(
        self, page_name: str, mobile_size: dict | None = None
    ) -> bytes:
        """Screenshot satu page pada mobile layout (portrait).

        Viewport disesuaikan dengan ``page.mobileSize`` supaya hasil tidak
        letterbox. Setelah resize, tunggu settle + render page sebelum ambil
        gambar.
        """
        width, height = mobile_viewport(mobile_size)
        self._page.set_viewport_size({"width": width, "height": height})
        self._page.wait_for_timeout(self.settle_ms)
        self._goto_page(page_name)
        self._page.wait_for_timeout(self.settle_ms)
        return self._page.locator("#reportContainer").screenshot(type="png")

    def _save_debug(self, page_name: str) -> None:
        if not self.debug_dir:
            return
        from pathlib import Path

        debug = Path(self.debug_dir)
        debug.mkdir(parents=True, exist_ok=True)
        try:
            (debug / f"viewport_{page_name}.png").write_bytes(
                self._page.screenshot(type="png")
            )
            frame = self._report_frame()
            (debug / f"frame_{page_name}.html").write_text(
                frame.content(), encoding="utf-8"
            )
            self._log(f"Debug capture disimpan ke {debug}.")
        except Exception as exc:  # noqa: BLE001 - best effort
            self._log(f"Gagal menyimpan debug capture: {exc}")
