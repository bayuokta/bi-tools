// Halaman Backup & Restore: definisi model/report dan pemulihannya.

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

var multi = { kind: "model", trigger: null, bound: false };

function backupState() {
  if (!state.backup) {
    state.backup = {
      loaded: false,
      workspaceId: "",
      workspaceName: "",
      workspaces: [],
      models: [],
      reports: [],
      selectedModels: {},
      selectedReports: {},
      folder: "",
      prefix: "Backup",
      history: [],
      files: [],
      result: null,
      restore: {
        files: [],
        workspaceId: "",
        overwrite: false,
        validate: true,
        targets: { models: [], reports: [] },
        result: null
      }
    };
  }
  return state.backup;
}

function backupTime(value) {
  if (!value) return "-";
  var date = new Date(value);
  if (isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function backupKey(item) {
  return item.id;
}

function backupSelectedMap(kind) {
  var data = backupState();
  return kind === "model" ? data.selectedModels : data.selectedReports;
}

function backupItems(kind) {
  var data = backupState();
  return kind === "model" ? data.models : data.reports;
}

function backupSelectedCount(kind) {
  var data = backupSelectedMap(kind);
  return backupItems(kind).filter(function (item) {
    return data[backupKey(item)];
  }).length;
}

function backupLabel(kind) {
  var items = backupItems(kind);
  var selected = backupSelectedCount(kind);
  if (!items.length) return t("No items");
  if (selected === items.length) return t("Select all");
  if (selected === 0) return t("Choose items…");
  return fmtInt(selected) + " " + t("selected");
}

function backupSelectAll(kind, value) {
  var data = backupSelectedMap(kind);
  backupItems(kind).forEach(function (item) {
    data[backupKey(item)] = value;
  });
  backupRenderScope();
}

function backupRenderScope() {
  var data = backupState();
  var total = backupSelectedCount("model") + backupSelectedCount("report");
  var all = data.models.length + data.reports.length;
  var scope = $("#bakScopeText");
  if (scope) scope.textContent = fmtInt(total) + " / " + fmtInt(all) + " " + t("selected");
  var modelLabel = $("#bakModelLabel");
  var reportLabel = $("#bakReportLabel");
  if (modelLabel) modelLabel.textContent = backupLabel("model");
  if (reportLabel) reportLabel.textContent = backupLabel("report");
}

// -- multi-select ---------------------------------------------------------
function multiItems() {
  return backupItems(multi.kind);
}

function multiSelected() {
  return backupSelectedMap(multi.kind);
}

function positionMulti() {
  var popup = $("#bakMultiPopup");
  if (!multi.trigger || popup.hidden) return;
  var rect = multi.trigger.getBoundingClientRect();
  var width = Math.min(Math.max(rect.width, 280), window.innerWidth - 24);
  popup.style.width = width + "px";
  popup.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)) + "px";
  var height = popup.offsetHeight;
  var top = rect.bottom + 6;
  if (top + height > window.innerHeight - 12 && rect.top - height - 6 > 8) {
    top = rect.top - height - 6;
  }
  popup.style.top = Math.max(8, top) + "px";
}

function renderMulti(query) {
  var box = $("#bakMultiList");
  var selected = multiSelected();
  var text = String(query || "").trim().toLowerCase();
  var items = multiItems().filter(function (item) {
    return !text || String(item.name || "").toLowerCase().indexOf(text) >= 0;
  });
  box.innerHTML = items.map(function (item) {
    var key = backupKey(item);
    return '<label class="combo-option">' +
      '<input type="checkbox" data-multi-id="' + escapeHtml(key) + '"' +
      (selected[key] ? " checked" : "") + ">" +
      '<span class="combo-label">' + escapeHtml(item.name) + "</span></label>";
  }).join("");
  $("#bakMultiEmpty").hidden = items.length > 0;
  box.scrollTop = 0;
  var count = multiItems().filter(function (item) {
    return selected[backupKey(item)];
  }).length;
  $("#bakMultiCount").textContent = fmtInt(count) + " " + t("selected");
}

function openMulti(kind) {
  var trigger = kind === "model" ? $("#bakModelTrigger") : $("#bakReportTrigger");
  if (!trigger) return;
  multi.kind = kind;
  multi.trigger = trigger;
  var popup = $("#bakMultiPopup");
  popup.hidden = false;
  trigger.setAttribute("aria-expanded", "true");
  $("#bakMultiSearch").value = "";
  renderMulti("");
  positionMulti();
  $("#bakMultiSearch").focus();
}

function closeMulti(focusTrigger) {
  var popup = $("#bakMultiPopup");
  if (!popup || popup.hidden) return;
  popup.hidden = true;
  if (multi.trigger) multi.trigger.setAttribute("aria-expanded", "false");
  if (focusTrigger && multi.trigger) multi.trigger.focus();
  multi.trigger = null;
}

function multiToggle(id, checked) {
  var selected = multiSelected();
  selected[id] = checked;
  var count = multiItems().filter(function (item) {
    return selected[backupKey(item)];
  }).length;
  $("#bakMultiCount").textContent = fmtInt(count) + " " + t("selected");
  backupRenderScope();
}

function bindMulti() {
  if (multi.bound) return;
  multi.bound = true;
  $("#bakModelTrigger").addEventListener("click", function () {
    openMulti("model");
  });
  $("#bakReportTrigger").addEventListener("click", function () {
    openMulti("report");
  });
  $("#bakMultiSearch").addEventListener("input", function (event) {
    renderMulti(event.target.value);
  });
  $("#bakMultiList").addEventListener("change", function (event) {
    var target = event.target;
    if (!target || !target.dataset || !target.dataset.multiId) return;
    multiToggle(target.dataset.multiId, target.checked);
  });
  $("#bakMultiAll").addEventListener("click", function () {
    backupSelectAll(multi.kind, true);
    renderMulti($("#bakMultiSearch").value);
  });
  $("#bakMultiClear").addEventListener("click", function () {
    backupSelectAll(multi.kind, false);
    renderMulti($("#bakMultiSearch").value);
  });
  document.addEventListener("click", function (event) {
    var popup = $("#bakMultiPopup");
    if (!popup || popup.hidden) return;
    if (popup.contains(event.target)) return;
    if (multi.trigger && multi.trigger.contains(event.target)) return;
    closeMulti();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeMulti(true);
  });
  window.addEventListener("resize", positionMulti);
  window.addEventListener("scroll", positionMulti, true);
}

// -- tabs -----------------------------------------------------------------
export function backupShowTab(name) {
  var target = name === "restore" ? "restore" : "backup";
  $("#bakPanelBackup").hidden = target !== "backup";
  $("#bakPanelRestore").hidden = target !== "restore";
  ["backup", "restore"].forEach(function (key) {
    var tab = $("#tab-" + key);
    if (!tab) return;
    tab.setAttribute("aria-selected", key === target ? "true" : "false");
    tab.tabIndex = key === target ? 0 : -1;
  });
}

// -- backup ---------------------------------------------------------------
export function backupRerender() {
  var data = backupState();
  backupRenderScope();
  backupRenderHistory();
  backupRenderSummary();
  backupRenderFiles();
  if (data.result) backupRenderResult(data.result);
  if (data.restore.result) restoreRenderResult(data.restore.result);
  restoreRenderFiles();
  restoreRenderTargets();
}

export function backupLoadState(folder) {
  if (!app.apiReady()) return Promise.resolve();
  var suffix = folder ? "?folder=" + encodeURIComponent(folder) : "";
  return app.api().get("/api/backup/state" + suffix).then(function (data) {
    backupApplyState(data);
    if (backupState().workspaceId) return backupLoadItems();
    return null;
  }).catch(app.reportError);
}

function backupApplyState(data) {
  var target = backupState();
  target.workspaces = data.workspaces || [];
  target.folder = data.folder || target.folder;
  target.prefix = data.prefix || target.prefix;
  target.history = data.history || [];
  target.files = data.files || [];
  target.loaded = true;
  setSelectOptions(
    "bakWorkspace",
    target.workspaces.map(function (row) {
      return { value: row.id, label: row.label };
    }),
    "Choose a workspace…"
  );
  setSelectOptions(
    "rstWorkspace",
    target.workspaces.map(function (row) {
      return { value: row.id, label: row.label };
    }),
    "Choose a workspace…"
  );
  if (target.workspaceId) {
    setSelectValue("bakWorkspace", target.workspaceId);
    setSelectValue("rstWorkspace", target.restore.workspaceId || target.workspaceId);
  }
  $("#bakSourceHint").textContent =
    data.hint || t("The workspace list comes from the shared catalog.");
  $("#bakFolder").value = target.folder;
  $("#bakName").value = target.prefix;
  restoreRenderFiles();
  backupRenderHistory();
  backupRenderSummary();
  backupRenderScope();
}

export function backupLoadItems() {
  var data = backupState();
  var workspaceId = getSelectValue("bakWorkspace");
  data.workspaceId = workspaceId;
  var workspace = data.workspaces.filter(function (row) {
    return row.id === workspaceId;
  })[0];
  data.workspaceName = workspace ? workspace.name : "";
  data.models = [];
  data.reports = [];
  data.selectedModels = {};
  data.selectedReports = {};
  if (!workspaceId) {
    backupRenderScope();
    return Promise.resolve();
  }
  $("#bakSourceHint").textContent = t("Loading items...");
  return app.api().get(
    "/api/backup/workspaces/" + encodeURIComponent(workspaceId) + "/items"
  ).then(function (payload) {
    data.models = payload.models || [];
    data.reports = payload.reports || [];
    data.models.forEach(function (item) {
      data.selectedModels[backupKey(item)] = true;
    });
    data.reports.forEach(function (item) {
      data.selectedReports[backupKey(item)] = true;
    });
    $("#bakSourceHint").textContent = fmtInt(data.models.length) + " " +
      t("semantic models") + " · " + fmtInt(data.reports.length) + " " + t("reports") +
      ". " + t("Click a field to search and check one or more items.");
    backupRenderScope();
  }).catch(app.reportError);
}

export function backupPayload() {
  var data = backupState();
  var workspaceId = getSelectValue("bakWorkspace");
  if (!workspaceId) {
    app.toast(t("Choose a workspace first."));
    return null;
  }
  var items = [];
  data.models.forEach(function (item) {
    if (data.selectedModels[backupKey(item)]) {
      items.push({ kind: "model", id: item.id, name: item.name, dataset_id: item.id });
    }
  });
  data.reports.forEach(function (item) {
    if (data.selectedReports[backupKey(item)]) {
      items.push({
        kind: "report",
        id: item.id,
        name: item.name,
        report_type: item.report_type || "",
        report_format: item.report_format || "",
        dataset_id: item.dataset_id || ""
      });
    }
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

function backupRenderFiles() {
  var data = backupState();
  var files = (data.result && data.result.items) || [];
  $("#bakResults").hidden = !data.result;
  if (!data.result) return;
  $("#bakFileList").innerHTML = files.map(function (item) {
    var meta = item.file
      ? escapeHtml(item.file) + " · " + sizeText(item.size)
      : escapeHtml(item.message || "-");
    return '<div class="bak-file"><div class="bak-file-main">' +
      '<span class="bak-file-name">' + escapeHtml(item.name) + "</span>" +
      backupStatusChip(item) + "</div>" +
      '<div class="helper">' + meta + "</div></div>";
  }).join("") || '<div class="empty"><p class="empty-text">' +
    escapeHtml(t("No files")) + "</p></div>";
  $("#bakFileSummary").textContent = fmtInt(data.result.ok || 0) + " " +
    t("saved") + " · " + fmtInt(data.result.failed || 0) + " " + t("failed") +
    " · " + fmtInt(data.result.skipped || 0) + " " + t("skipped");
}

function backupStatusChip(item) {
  var tone = item.status === "ok" ? "chip-ok" : (item.status === "failed" ? "chip-error" : "chip-idle");
  var label = item.status === "ok"
    ? t("Saved")
    : (item.status === "failed" ? t("Failed") : t("Skipped"));
  return '<span class="chip ' + tone + '"><span class="dot"></span>' +
    escapeHtml(label) + "</span>";
}

function backupRenderResult(result) {
  var data = backupState();
  data.result = result;
  $("#bakOutputState").className = "chip chip-ok";
  $("#bakOutputState").innerHTML = '<span class="dot"></span>' + escapeHtml(t("Done"));
  $("#bakOpenFolder").disabled = false;
  backupRenderFiles();
  backupRenderSummary();
}

function backupRenderSummary() {
  var data = backupState();
  if (!data.result) {
    $("#bakSummaryBody").hidden = true;
    $("#bakSummaryEmpty").hidden = false;
    return;
  }
  $("#bakSummaryBody").hidden = false;
  $("#bakSummaryEmpty").hidden = true;
  $("#bakStatSource").textContent = data.workspaceName || "-";
  $("#bakStatItems").textContent = fmtInt(data.result.ok) + " / " + fmtInt((data.result.items || []).length);
  $("#bakStatSize").textContent = sizeText(data.result.size);
  $("#bakStatTime").textContent = backupTime(data.result.finished_at);
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

export function backupOpenFolder() {
  var data = backupState();
  var target = (data.result && data.result.run_dir) || data.folder;
  if (!target) return;
  app.api().post("/api/files/open", { path: target, mode: "open" }).catch(app.reportError);
}

// -- restore --------------------------------------------------------------
function restoreData() {
  return backupState().restore;
}

function restoreSelectedFile() {
  var path = getSelectValue("rstFile");
  return backupState().files.filter(function (row) {
    return row.path === path;
  })[0] || null;
}

function restoreRenderFiles() {
  var data = backupState();
  var restore = restoreData();
  restore.files = data.files || [];
  setSelectOptions(
    "rstFile",
    restore.files.map(function (row) {
      var label = (row.kind === "model" ? t("Model") : t("Report")) +
        " · " + row.name + " · " + row.workspace + " · " + backupTime(row.finished_at);
      return { value: row.path, label: label };
    }),
    "Choose a backup file…"
  );
  if (restore.selectedFile) setSelectValue("rstFile", restore.selectedFile);
  restoreRenderTargets();
}

function restoreRenderTargets() {
  var data = backupState();
  var restore = restoreData();
  var overwrite = $("#rstOverwrite") && $("#rstOverwrite").checked;
  var row = $("#rstTargetRow");
  var file = restoreSelectedFile();
  if (!row) return;
  row.hidden = !overwrite;
  if (!overwrite || !file) return;
  var workspaceId = getSelectValue("rstWorkspace");
  if (!workspaceId) return;
  var items = file.kind === "model" ? restore.targets.models : restore.targets.reports;
  setSelectOptions(
    "rstTarget",
    (items || []).map(function (item) {
      return { value: item.id, label: item.name + " (" + item.id.slice(0, 8) + ")" };
    }),
    file.kind === "model" ? "Choose a semantic model…" : "Choose a report…"
  );
}

function restoreLoadTargets() {
  var restore = restoreData();
  var workspaceId = getSelectValue("rstWorkspace");
  restore.workspaceId = workspaceId;
  if (!workspaceId) {
    restore.targets = { models: [], reports: [] };
    restoreRenderTargets();
    return Promise.resolve();
  }
  return app.api().get(
    "/api/backup/restore/state?workspace_id=" + encodeURIComponent(workspaceId)
  ).then(function (data) {
    restore.targets = data.targets || { models: [], reports: [] };
    restoreRenderTargets();
  }).catch(app.reportError);
}

export function runRestore() {
  var data = backupState();
  var restore = restoreData();
  var file = restoreSelectedFile();
  if (!file) {
    app.toast(t("Choose a backup file first."));
    return;
  }
  var workspaceId = getSelectValue("rstWorkspace");
  if (!workspaceId) {
    app.toast(t("Choose a target workspace first."));
    return;
  }
  var overwrite = $("#rstOverwrite").checked;
  var targetId = overwrite ? getSelectValue("rstTarget") : "";
  if (overwrite && !targetId) {
    app.toast(t("Choose the target item to overwrite."));
    return;
  }
  if (overwrite) {
    var label = file.kind === "model" ? t("Model") : t("Report");
    if (!window.confirm(
      t("Replace the entire definition of the selected ") + label.toLowerCase() +
      "? " + t("This cannot be undone.")
    )) return;
  }
  var workspace = data.workspaces.filter(function (row) {
    return row.id === workspaceId;
  })[0];
  var targetName = "";
  if (overwrite) {
    var list = file.kind === "model" ? restore.targets.models : restore.targets.reports;
    var item = (list || []).filter(function (row) {
      return row.id === targetId;
    })[0];
    targetName = item ? item.name : "";
  }
  var payload = {
    file: file.path,
    workspace_id: workspaceId,
    workspace_name: workspace ? workspace.name : "",
    overwrite: overwrite,
    target_id: targetId,
    target_name: targetName,
    validate: $("#rstValidate").checked
  };
  $("#rstRun").hidden = false;
  $("#rstRunLabel").textContent = t("Running restore...");
  $("#rstRunPct").textContent = "0%";
  $("#rstBar").style.width = "0%";
  app.startJob({
    path: "/api/backup/restore/run",
    body: payload,
    label: t("Restore model & report"),
    button: $("#runRestore"),
    onDone: function (snapshot) {
      $("#rstRun").hidden = true;
      if (snapshot && snapshot.status === "done" && snapshot.result) {
        restoreRenderResult(snapshot.result);
        backupLoadState(data.folder);
        app.toast(t("Restore finished."));
      }
    }
  });
}

function restoreRenderResult(result) {
  var restore = restoreData();
  restore.result = result;
  $("#rstResult").hidden = false;
  $("#rstStateChip").className = "chip chip-ok";
  $("#rstStateChip").innerHTML = '<span class="dot"></span>' + escapeHtml(t("Done"));
  $("#rstResultBody").innerHTML =
    '<div class="stat-list">' +
    '<div class="stat-row"><span class="stat-key">' + escapeHtml(t("File")) +
    '</span><span class="stat-val">' + escapeHtml(result.file_name || result.file || "-") + "</span></div>" +
    '<div class="stat-row"><span class="stat-key">' + escapeHtml(t("Action")) +
    '</span><span class="stat-val">' + escapeHtml(result.action || "-") + "</span></div>" +
    '<div class="stat-row"><span class="stat-key">' + escapeHtml(t("Item")) +
    '</span><span class="stat-val">' + escapeHtml(result.name || "-") + "</span></div>" +
    '<div class="stat-row"><span class="stat-key">' + escapeHtml(t("ID")) +
    '</span><span class="stat-val mono">' + escapeHtml(result.id || "-") + "</span></div>" +
    "</div>";
  $("#rstSummaryBody").hidden = false;
  $("#rstSummaryEmpty").hidden = true;
  $("#rstStatFile").textContent = result.file_name || "-";
  $("#rstStatTarget").textContent = result.workspace_name || "-";
  $("#rstStatObjects").textContent = "1";
  $("#rstStatTime").textContent = backupTime(result.finished_at);
}

export function initBackupEvents() {
  bindMulti();
  var tabs = document.querySelectorAll("[data-bak-tab]");
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      backupShowTab(tab.dataset.bakTab);
    });
  });
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
  var file = $("#rstFile");
  if (file) {
    file.addEventListener("change", function () {
      restoreData().selectedFile = getSelectValue("rstFile");
      restoreRenderTargets();
    });
  }
  var targetWorkspace = $("#rstWorkspace");
  if (targetWorkspace) {
    targetWorkspace.addEventListener("change", function () {
      restoreLoadTargets();
    });
  }
  var overwrite = $("#rstOverwrite");
  if (overwrite) {
    overwrite.addEventListener("change", function () {
      restoreRenderTargets();
      if (overwrite.checked) restoreLoadTargets();
    });
  }
  var restoreRun = $("#runRestore");
  if (restoreRun) restoreRun.addEventListener("click", runRestore);
}
