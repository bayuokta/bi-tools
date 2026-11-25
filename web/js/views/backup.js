// Halaman Backup: definisi semantic model (TMDL/TMSL) dan report (PBIR).

import { app } from "../core/app_api.js";
import {
  getSelectValue,
  setSelectOptions,
  setSelectValue
} from "../core/combo.js";
import { $, escapeHtml } from "../core/dom.js";
import { fmtInt, sizeText } from "../core/format.js";
import { t } from "../core/i18n.js";
import { state } from "../core/state.js";

function backupState() {
  if (!state.backup) {
    state.backup = {
      loaded: false,
      workspaceId: "",
      workspaces: [],
      items: [],
      selected: {},
      folder: "",
      prefix: "Backup",
      history: [],
      result: null
    };
  }
  return state.backup;
}

function backupKey(item) {
  return item.kind + ":" + item.id;
}

function backupIsVisible(item) {
  if (item.kind === "model") return $("#bakModelOpt").checked;
  return $("#bakReportOpt").checked;
}

function backupVisibleItems() {
  return backupState().items.filter(backupIsVisible);
}

function backupSelectedItems() {
  var data = backupState();
  return backupVisibleItems().filter(function (item) {
    return data.selected[backupKey(item)];
  });
}

function backupTime(value) {
  if (!value) return "-";
  var date = new Date(value);
  if (isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function backupStatusChip(item) {
  var tone = item.status === "ok" ? "chip-ok" : (item.status === "failed" ? "chip-error" : "chip-idle");
  var label = item.status === "ok"
    ? t("Saved")
    : (item.status === "failed" ? t("Failed") : t("Skipped"));
  return '<span class="chip ' + tone + '"><span class="dot"></span>' + escapeHtml(label) + "</span>";
}

function backupScopeLabel() {
  var selected = backupSelectedItems().length;
  var visible = backupVisibleItems().length;
  return fmtInt(selected) + " / " + fmtInt(visible) + " " + t("selected");
}

function backupRenderItems() {
  var data = backupState();
  var box = $("#bakItems");
  if (!box) return;
  var items = backupVisibleItems();
  if (!data.workspaceId) {
    box.innerHTML = "";
    $("#bakItemsHint").textContent = t("Select a workspace to load items.");
    $("#bakScopeChip .dot").className = "dot";
    $("#bakScopeText").textContent = "0 " + t("selected");
    return;
  }
  if (!items.length) {
    box.innerHTML = "";
    $("#bakItemsHint").textContent = t("No semantic models or reports in this workspace.");
    $("#bakScopeText").textContent = "0 " + t("selected");
    return;
  }
  $("#bakItemsHint").textContent = "";
  box.innerHTML = items.map(function (item) {
    var key = backupKey(item);
    var checked = data.selected[key] ? " checked" : "";
    var kind = item.kind === "model" ? t("Semantic model") : t("Report");
    var extra = item.kind === "report" && item.report_type === "PaginatedReport"
      ? ' <span class="chip chip-idle"><span class="dot"></span>' + t("Paginated (skipped)") + "</span>"
      : "";
    return '<label class="check bak-item">' +
      '<input type="checkbox" data-bak-key="' + escapeHtml(key) + '"' + checked + ">" +
      '<span class="bak-item-name">' + escapeHtml(item.name) + "</span>" +
      '<span class="helper">' + escapeHtml(kind) + "</span>" + extra +
      "</label>";
  }).join("");
  $("#bakScopeText").textContent = backupScopeLabel();
}

function backupRenderSummary() {
  var data = backupState();
  var result = data.result;
  if (!result) {
    $("#bakSummaryBody").hidden = true;
    $("#bakSummaryEmpty").hidden = false;
    return;
  }
  $("#bakSummaryBody").hidden = false;
  $("#bakSummaryEmpty").hidden = true;
  $("#bakStatSource").textContent = data.workspaceName || "-";
  $("#bakStatItems").textContent = fmtInt(result.ok) + " / " + fmtInt(result.items.length);
  $("#bakStatSize").textContent = sizeText(result.size);
  $("#bakStatTime").textContent = backupTime(result.finished_at);
}

function backupRenderResult(result) {
  var data = backupState();
  data.result = result;
  $("#bakResults").hidden = false;
  $("#bakRun").hidden = true;
  $("#bakOutputState").className = "chip chip-ok";
  $("#bakOutputState").innerHTML = '<span class="dot"></span>' + escapeHtml(t("Done"));
  $("#bakOpenFolder").disabled = false;
  $("#bakFileList").innerHTML = (result.items || []).map(function (item) {
    var meta = item.file
      ? escapeHtml(item.file) + " · " + sizeText(item.size)
      : escapeHtml(item.message || "-");
    return '<div class="bak-file">' +
      '<div class="bak-file-main"><span class="bak-file-name">' + escapeHtml(item.name) + "</span>" +
      backupStatusChip(item) + "</div>" +
      '<div class="helper">' + meta + "</div></div>";
  }).join("") || '<div class="empty"><p class="empty-text">' + escapeHtml(t("No files")) + "</p></div>";
  $("#bakFileSummary").textContent = fmtInt(result.ok || 0) + " " + t("saved") +
    " · " + fmtInt(result.failed || 0) + " " + t("failed") +
    " · " + fmtInt(result.skipped || 0) + " " + t("skipped");
  backupRenderSummary();
}

function backupRenderHistory() {
  var data = backupState();
  var box = $("#bakHistory");
  if (!box) return;
  if (!data.history.length) {
    box.innerHTML = '<div class="empty" style="padding:6px 2px"><p class="empty-text">' +
      escapeHtml(t("No backup history.")) + "</p></div>";
    return;
  }
  box.innerHTML = data.history.map(function (row) {
    var summary = fmtInt(row.ok) + " " + t("saved") + " · " + sizeText(row.size);
    if (row.failed) summary += " · " + fmtInt(row.failed) + " " + t("failed");
    return '<button class="bak-history-row" type="button" data-path="' + escapeHtml(row.path) + '">' +
      '<span class="bak-history-time">' + escapeHtml(backupTime(row.finished_at)) + "</span>" +
      '<span class="helper">' + escapeHtml(summary) + "</span></button>";
  }).join("");
}

function backupApplyState(data) {
  var target = backupState();
  target.workspaces = data.workspaces || [];
  target.folder = data.folder || target.folder;
  target.prefix = data.prefix || target.prefix;
  target.history = data.history || [];
  target.loaded = true;
  setSelectOptions(
    "bakWorkspace",
    target.workspaces.map(function (row) {
      return { value: row.id, label: row.label };
    }),
    "Choose a workspace"
  );
  if (target.workspaceId) setSelectValue("bakWorkspace", target.workspaceId);
  $("#bakSourceHint").textContent = data.hint || t("Workspace list comes from the shared catalog.");
  $("#bakFolder").value = target.folder;
  $("#bakName").value = target.prefix;
  backupRenderHistory();
  backupRenderSummary();
  backupRenderItems();
}

export function backupRerender() {
  var data = backupState();
  backupRenderItems();
  backupRenderHistory();
  backupRenderSummary();
  if (data.result) backupRenderResult(data.result);
}

export function backupLoadState(folder) {
  if (!app.apiReady()) return Promise.resolve();
  var suffix = folder ? "?folder=" + encodeURIComponent(folder) : "";
  return app.api().get("/api/backup/state" + suffix).then(function (data) {
    backupApplyState(data);
    var data2 = backupState();
    if (data2.workspaceId) return backupLoadItems();
    return null;
  }).catch(app.reportError);
}

export function backupLoadItems() {
  var data = backupState();
  var workspaceId = getSelectValue("bakWorkspace");
  data.workspaceId = workspaceId;
  var workspace = data.workspaces.filter(function (row) {
    return row.id === workspaceId;
  })[0];
  data.workspaceName = workspace ? workspace.name : "";
  data.selected = {};
  data.items = [];
  if (!workspaceId) {
    backupRenderItems();
    return Promise.resolve();
  }
  $("#bakItemsHint").textContent = t("Loading items...");
  return app.api().get(
    "/api/backup/workspaces/" + encodeURIComponent(workspaceId) + "/items"
  ).then(function (payload) {
    data.items = payload.items || [];
    data.selected = {};
    data.items.forEach(function (item) {
      data.selected[backupKey(item)] = true;
    });
    backupRenderItems();
  }).catch(app.reportError);
}

export function backupPayload() {
  var data = backupState();
  var workspaceId = getSelectValue("bakWorkspace");
  if (!workspaceId) {
    app.toast(t("Choose a workspace first."));
    return null;
  }
  var items = backupSelectedItems().map(function (item) {
    return {
      kind: item.kind,
      id: item.id,
      name: item.name,
      report_type: item.report_type || "",
      report_format: item.report_format || "",
      dataset_id: item.dataset_id || ""
    };
  });
  if (!items.length) {
    app.toast(t("Select at least one item."));
    return null;
  }
  var folder = $("#bakFolder").value.trim();
  if (!folder) {
    app.toast(t("Choose a destination folder."));
    return null;
  }
  var workspace = data.workspaces.filter(function (row) {
    return row.id === workspaceId;
  })[0];
  return {
    workspace_id: workspaceId,
    workspace_name: workspace ? workspace.name : "",
    items: items,
    folder: folder,
    prefix: $("#bakName").value.trim() || "Backup"
  };
}

export function runBackup() {
  var payload = backupPayload();
  if (!payload) return;
  $("#bakRun").hidden = false;
  $("#bakRunLabel").textContent = t("Running backup...");
  $("#bakRunPct").textContent = "0%";
  $("#bakBar").style.width = "0%";
  app.startJob({
    path: "/api/backup/run",
    body: payload,
    label: t("Backup model & report"),
    button: $("#runBackup"),
    onDone: function (snapshot) {
      $("#bakRun").hidden = true;
      if (snapshot && snapshot.status === "done" && snapshot.result) {
        backupRenderResult(snapshot.result);
        backupLoadState(payload.folder);
        app.toast(t("Backup finished."));
      }
    }
  });
}

export function backupOpenFolder() {
  var data = backupState();
  var target = data.result && data.result.run_dir;
  if (!target) return;
  app.api().post("/api/files/open", { path: target, mode: "open" }).catch(app.reportError);
}

export function initBackupEvents() {
  var workspace = $("#bakWorkspace");
  if (workspace) {
    workspace.addEventListener("change", function () {
      backupLoadItems();
    });
  }
  var reload = $("#bakReload");
  if (reload) {
    reload.addEventListener("click", function () {
      backupLoadState();
    });
  }
  ["bakModelOpt", "bakReportOpt"].forEach(function (id) {
    var box = $("#" + id);
    if (!box) return;
    box.addEventListener("change", backupRenderItems);
  });
  var items = $("#bakItems");
  if (items) {
    items.addEventListener("change", function (event) {
      var target = event.target;
      if (!target || !target.dataset || !target.dataset.bakKey) return;
      backupState().selected[target.dataset.bakKey] = target.checked;
      $("#bakScopeText").textContent = backupScopeLabel();
    });
  }
  var pick = $("#bakPickFolder");
  if (pick) {
    pick.addEventListener("click", function () {
      var data = backupState();
      app.openFolderPicker(app.parentDir(data.folder), function (path) {
        data.folder = path;
        $("#bakFolder").value = path;
        backupLoadState(path);
      });
    });
  }
  var run = $("#runBackup");
  if (run) run.addEventListener("click", runBackup);
  var open = $("#bakOpenFolder");
  if (open) open.addEventListener("click", backupOpenFolder);
  var history = $("#bakHistory");
  if (history) {
    history.addEventListener("click", function (event) {
      var target = event.target.closest("[data-path]");
      if (!target) return;
      app.api().post("/api/files/open", {
        path: target.dataset.path,
        mode: "open"
      }).catch(app.reportError);
    });
  }
}
