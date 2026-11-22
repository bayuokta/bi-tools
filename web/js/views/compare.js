// Halaman Compare Semantic Model (read-only). Tidak ada aksi tulis ke target.

import { app } from "../core/app_api.js";
import {
  getSelectValue,
  setSelectOptions,
  setSelectValue
} from "../core/combo.js";
import { $, $$, escapeHtml } from "../core/dom.js";
import { fmtInt } from "../core/format.js";
import { t } from "../core/i18n.js";
import { state } from "../core/state.js";

var STATUS_LABELS = {
  same: "Same definition",
  different: "Different definition",
  source_only: "Source only",
  target_only: "Target only"
};
var STATUS_CLASSES = {
  same: "is-same",
  different: "is-diff",
  source_only: "is-source",
  target_only: "is-target"
};

function statusLabel(status) {
  return t(STATUS_LABELS[status] || status || "");
}

function sideType(side) {
  return side === "source" ? state.compareSourceType : state.compareTargetType;
}

function sidePrefix(side) {
  return side === "source" ? "cmpSource" : "cmpTarget";
}

function sideSuffix(side) {
  return side === "source" ? "source" : "target";
}

function desktopInstance(port) {
  var items = (state.compareState && state.compareState.instances) || [];
  return items.filter(function (item) {
    return String(item.port) === String(port);
  })[0] || null;
}

function setCompareType(side, type) {
  var next = type === "desktop" ? "desktop" : "dataset";
  if (side === "source") state.compareSourceType = next;
  else state.compareTargetType = next;
  var root = $("[data-cmp-side='" + side + "']");
  if (root) {
    $$("[data-cmp-type]", root).forEach(function (button) {
      button.setAttribute(
        "aria-pressed",
        button.getAttribute("data-cmp-type") === next ? "true" : "false"
      );
    });
  }
  var fields = $("[data-cmp-fields='" + side + "']");
  if (fields) {
    $$("[data-cmp-kind]", fields).forEach(function (field) {
      field.hidden = field.getAttribute("data-cmp-kind") !== next;
    });
  }
  var chip = $(side === "source" ? "#cmpSourceChip" : "#cmpTargetChip");
  if (chip) {
    chip.lastElementChild.textContent = next === "desktop" ? t("Desktop") : t("Dataset");
  }
}

function fillCompareSide(side) {
  var prefix = sidePrefix(side);
  var data = state.compareState || {};
  var workspaces = (data.workspaces || []).map(function (item) {
    return { value: item.id, label: item.label || item.name || item.id };
  });
  setSelectOptions(prefix + "Workspace", workspaces, "Choose a workspace…");
  var instances = (data.instances || []).map(function (item) {
    return {
      value: String(item.port),
      label: item.file_name
        ? item.file_name + " · localhost:" + item.port
        : item.model_name + " · localhost:" + item.port
    };
  });
  setSelectOptions(prefix + "Desktop", instances, "Choose a Desktop instance…");
  if (!instances.length) {
    setSelectOptions(prefix + "Model", [], "Choose a semantic model…");
  }
}

function loadCompareDatasets(side) {
  var prefix = sidePrefix(side);
  var workspace = getSelectValue(prefix + "Workspace");
  if (!workspace) {
    setSelectOptions(prefix + "Model", [], "Choose a semantic model…");
    return Promise.resolve();
  }
  return app.api().get(
    "/api/analysis/workspaces/" + encodeURIComponent(workspace) + "/datasets"
  ).then(function (data) {
    var options = (data.datasets || []).map(function (item) {
      return { value: item.id, label: item.label || item.name || item.id };
    });
    setSelectOptions(prefix + "Model", options, "Choose a semantic model…");
  }).catch(function (error) {
    setSelectOptions(prefix + "Model", [], "Choose a semantic model…");
    app.reportError(error);
  });
}

export function compareLoadState() {
  if (state.compareLoaded || !app.apiReady()) return Promise.resolve();
  state.compareLoaded = true;
  return app.api().get("/api/compare/state").then(function (data) {
    state.compareState = data;
    fillCompareSide("source");
    fillCompareSide("target");
    var hint = $("#cmpSourceWorkspace");
    if (hint && data.hint && !(data.workspaces || []).length) {
      app.toast(data.hint);
    }
    setCompareType("source", state.compareSourceType);
    setCompareType("target", state.compareTargetType);
    return Promise.all([loadCompareDatasets("source"), loadCompareDatasets("target")]);
  }).catch(function (error) {
    state.compareLoaded = false;
    app.reportError(error);
  });
}

function comparePayload() {
  function sidePayload(side) {
    var prefix = sidePrefix(side);
    if (sideType(side) === "desktop") {
      var instance = desktopInstance(getSelectValue(prefix + "Desktop"));
      return {
        type: "desktop",
        port: instance ? instance.port : 0,
        catalog: instance ? instance.catalog : ""
      };
    }
    return {
      type: "dataset",
      workspace_id: getSelectValue(prefix + "Workspace"),
      dataset_id: getSelectValue(prefix + "Model")
    };
  }
  return {
    source: sidePayload("source"),
    target: sidePayload("target"),
    options: {
      measures: $("#cmpOptMeasures").checked,
      relationships: $("#cmpOptRelations").checked,
      expressions: $("#cmpOptQueries").checked,
      format_string: $("#cmpOptFormat").checked,
      roles: $("#cmpOptRls").checked
    }
  };
}

function validateCompareForm(payload) {
  function validSide(side, label) {
    if (side.type === "desktop") {
      if (!side.port || !side.catalog) {
        app.toast(t("Choose a Desktop instance for ") + label + ".");
        return false;
      }
      return true;
    }
    if (!side.workspace_id || !side.dataset_id) {
      app.toast(t("Choose a workspace and semantic model for ") + label + ".");
      return false;
    }
    return true;
  }
  if (!validSide(payload.source, t("source")) || !validSide(payload.target, t("target"))) {
    return false;
  }
  if (
    payload.source.type === "dataset" &&
    payload.target.type === "dataset" &&
    payload.source.workspace_id === payload.target.workspace_id &&
    payload.source.dataset_id === payload.target.dataset_id
  ) {
    app.toast(t("Source and target must be different models."));
    return false;
  }
  if (
    payload.source.type === "desktop" &&
    payload.target.type === "desktop" &&
    String(payload.source.port) === String(payload.target.port) &&
    payload.source.catalog === payload.target.catalog
  ) {
    app.toast(t("Source and target must be different models."));
    return false;
  }
  return true;
}

export function applyCompareResult(result) {
  state.compare = result || null;
  state.compareReady = Boolean(result);
  state.compareValidated = false;
  state.compareActive = null;
  if (result && (result.items || []).length) {
    var first = result.items.filter(function (item) {
      return item.status !== "same";
    })[0] || result.items[0];
    state.compareActive = first ? first.id : null;
  }
  renderCompare();
}

export function runCompare() {
  if (state.compareRunning || !app.apiReady()) return;
  var payload = comparePayload();
  if (!validateCompareForm(payload)) return;
  state.compareRunning = true;
  state.compareReady = false;
  state.compareValidated = false;
  state.compare = null;
  $("#runCompare").disabled = true;
  $("#compareRun").hidden = false;
  $("#compareBar").style.width = "0%";
  $("#compareRunPct").textContent = "0%";
  $("#compareRunLabel").textContent = t("Preparing comparison…");
  renderCompare();
  app.startJob({
    path: "/api/compare/run",
    body: payload,
    label: t("Compare semantic model"),
    button: $("#runCompare"),
    onDone: function (snapshot) {
      state.compareRunning = false;
      $("#runCompare").disabled = false;
      $("#compareRun").hidden = true;
      applyCompareResult(snapshot.result || null);
      if (state.compare) app.toast(t("Comparison finished"));
    },
    onError: function () {
      state.compareRunning = false;
      $("#runCompare").disabled = false;
      $("#compareRun").hidden = true;
      renderCompare();
    }
  });
}

function compareItems() {
  return (state.compare && state.compare.items) || [];
}

function filteredItems() {
  var query = ($("#cmpSearch").value || "").trim().toLowerCase();
  var status = $("#cmpStatusFilter").value;
  var type = $("#cmpTypeFilter").value;
  return compareItems().filter(function (item) {
    if (state.compareOnlyDiff && item.status === "same") return false;
    if (status === "diff" && item.status !== "different") return false;
    if (status === "same" && item.status !== "same") return false;
    if (status === "source" && item.status !== "source_only") return false;
    if (status === "target" && item.status !== "target_only") return false;
    if (type !== "all" && item.type !== type) return false;
    if (!query) return true;
    return (
      (item.name + " " + item.source_name + " " + item.target_name + " " + item.parent)
        .toLowerCase()
        .indexOf(query) !== -1
    );
  });
}

function renderCompareMetrics() {
  var stats = (state.compare && state.compare.stats) || {};
  $("#cmpMetricTotal").textContent = state.compare ? fmtInt(stats.total || 0) : "—";
  $("#cmpMetricSame").textContent = state.compare ? fmtInt(stats.same || 0) : "—";
  $("#cmpMetricDiff").textContent = state.compare ? fmtInt(stats.different || 0) : "—";
  $("#cmpMetricSourceOnly").textContent = state.compare ? fmtInt(stats.source_only || 0) : "—";
  $("#cmpMetricTargetOnly").textContent = state.compare ? fmtInt(stats.target_only || 0) : "—";
  var changes = compareItems().filter(function (item) {
    return item.status !== "same";
  }).length;
  $("#cmpMetricSelected").textContent = String(changes);
  $("#cmpStatActions").textContent = String(changes);
}

function renderCompareTable() {
  var items = filteredItems();
  var wrap = $("#compareTableWrap");
  var empty = $("#cmpEmpty");
  var body = $("#compareBody");
  body.innerHTML = items.map(function (item) {
    var action = t(item.action || "Skip");
    return '<tr data-id="' + escapeHtml(item.id) + '" tabindex="0"' +
      (state.compareActive === item.id ? ' class="is-current"' : "") + ">" +
      '<td><span class="cmp-type">' + escapeHtml(item.type) + "</span></td>" +
      '<td class="name" title="' + escapeHtml(item.source_name || "—") + '">' +
        escapeHtml(item.source_name || "—") + "</td>" +
      '<td><span class="cmp-status ' + (STATUS_CLASSES[item.status] || "") + '">' +
        '<span class="dot"></span>' + escapeHtml(statusLabel(item.status)) + "</span></td>" +
      '<td class="name" title="' + escapeHtml(item.target_name || "—") + '">' +
        escapeHtml(item.target_name || "—") + "</td>" +
      "<td>" + escapeHtml(action) + "</td></tr>";
  }).join("");
  wrap.hidden = !items.length;
  empty.hidden = Boolean(items.length);
  if (!items.length) {
    $("#cmpEmptyTitle").textContent = state.compare
      ? t("No matching items")
      : t("No comparison yet");
    $("#cmpEmptyText").textContent = state.compare
      ? t("Change the keyword or filter to see other items.")
      : t("Choose source and target, then run the comparison. Results show definition differences in both models.");
    $("#cmpFromEmpty").hidden = Boolean(state.compare);
  }
  $("#cmpSummary").textContent = state.compare
    ? fmtInt(items.length) + " / " + fmtInt(compareItems().length) + " " +
      t("items shown") + " · " + fmtInt(compareItems().filter(function (item) {
        return item.status !== "same";
      }).length) + " " + t("changes")
    : t("Not compared yet");
  $("#cmpSummaryEmpty").hidden = Boolean(state.compare);
  $("#cmpSummaryBody").hidden = !state.compare;
  if (state.compare) {
    $("#cmpStatSource").textContent = (state.compare.source && state.compare.source.label) || "—";
    $("#cmpStatTarget").textContent = (state.compare.target && state.compare.target.label) || "—";
    $("#cmpStatCompared").textContent = fmtInt(compareItems().length);
    $("#cmpStatTime").textContent = state.compare.generated_at || "—";
  }
}

function renderCompareDetail() {
  var item = compareItems().filter(function (entry) {
    return entry.id === state.compareActive;
  })[0];
  if (!item) {
    $("#cmpDetail").innerHTML =
      '<p class="helper">' + escapeHtml(t("Select a row to see status, action, and expressions.")) + "</p>";
    return;
  }
  var rows = (item.properties || []).filter(function (property_) {
    return property_.source !== property_.target;
  }).map(function (property_) {
    return "<dt>" + escapeHtml(property_.name) + "</dt><dd>" +
      escapeHtml(property_.source) + " → " + escapeHtml(property_.target) + "</dd>";
  }).join("");
  $("#cmpDetail").innerHTML =
    '<div class="cmp-detail-head"><div><h3 class="cmp-detail-name">' +
      escapeHtml(item.name) + '</h3><p class="cmp-detail-sub">' +
      escapeHtml(item.type) + " · " + escapeHtml(statusLabel(item.status)) +
      '</p></div><span class="cmp-status ' + (STATUS_CLASSES[item.status] || "") +
      '"><span class="dot"></span>' + escapeHtml(statusLabel(item.status)) + "</span></div>" +
    (rows ? '<dl class="cmp-detail-kv">' + rows + "</dl>" : "") +
    '<p class="helper">' + escapeHtml(t("Suggested action")) + ": " +
      escapeHtml(t(item.action || "Skip")) + "</p>";
}

function renderDiffPane(element, meta, lines) {
  $(meta).textContent = lines.length
    ? fmtInt(lines.length) + " " + t("lines") + " · " +
      fmtInt(lines.filter(function (line) { return line.changed; }).length) + " " + t("changed")
    : t("No definition");
  $(element).innerHTML = lines.length
    ? lines.map(function (line) {
        return '<div class="diff-line' + (line.changed ? " is-changed" : "") + '">' +
          '<span class="ln">' + line.number + '</span>' +
          '<span class="lt">' + escapeHtml(line.text) + "</span></div>";
      }).join("")
    : '<div class="diff-line"><span class="lt">' + escapeHtml(t("No definition")) + "</span></div>";
}

function renderCompareDiff() {
  var item = compareItems().filter(function (entry) {
    return entry.id === state.compareActive;
  })[0];
  var panel = $("#cmpDiffPanel");
  if (!item) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("#cmpDiffName").textContent = item.name;
  var diff = item.diff || { source: [], target: [] };
  renderDiffPane("#cmpDiffSource", "#cmpDiffSourceMeta", diff.source || []);
  renderDiffPane("#cmpDiffTarget", "#cmpDiffTargetMeta", diff.target || []);
}

function syncCompareToolbar() {
  var ready = Boolean(state.compare) && !state.compareRunning;
  var changes = compareItems().filter(function (item) {
    return item.status !== "same";
  }).length;
  $("#cmpValidate").disabled = !ready || !changes;
  $("#cmpScript").disabled = !ready;
  $("#cmpExport").disabled = !ready;
  $("#cmpApply").disabled = true;
  $("#cmpApply").title = t("Comparison is read-only. Generate the script and apply it manually.");
}

export function renderCompare() {
  setCompareType("source", state.compareSourceType);
  setCompareType("target", state.compareTargetType);
  renderCompareMetrics();
  renderCompareTable();
  renderCompareDetail();
  renderCompareDiff();
  syncCompareToolbar();
}

export function selectCompareRow(id) {
  state.compareActive = id;
  $$("#compareBody tr").forEach(function (row) {
    row.classList.toggle("is-current", row.getAttribute("data-id") === id);
  });
  renderCompareDetail();
  renderCompareDiff();
}

function validateCompare() {
  if (!state.compare) return;
  var changes = compareItems().filter(function (item) {
    return item.status !== "same";
  });
  state.compareValidated = true;
  app.addLog(
    t("Validation complete") + ": " + fmtInt(changes.length) + " " + t("changes ready") + ".",
    "ok"
  );
  app.toast(t("Validation complete") + " · " + fmtInt(changes.length));
  syncCompareToolbar();
}

function exportCompare() {
  if (!state.compare || !app.apiReady()) return;
  app.api().post("/api/compare/export", {}).then(function (data) {
    app.toast("CSV: " + data.path);
    app.api().post("/api/files/open", { path: data.path, mode: "open" }).catch(function () {});
  }).catch(app.reportError);
}

function generateCompareScript() {
  if (!state.compare || !app.apiReady()) return;
  app.api().post("/api/compare/script", {}).then(function (data) {
    app.toast("Script: " + data.path);
    app.api().post("/api/files/open", { path: data.path, mode: "open" }).catch(function () {});
  }).catch(app.reportError);
}

export function initCompareEvents() {
  $$("[data-cmp-side] [data-cmp-type]").forEach(function (button) {
    button.addEventListener("click", function () {
      var side = button.closest("[data-cmp-side]").getAttribute("data-cmp-side");
      setCompareType(side, button.getAttribute("data-cmp-type"));
    });
  });
  ["source", "target"].forEach(function (side) {
    var prefix = sidePrefix(side);
    var workspace = $("#" + prefix + "Workspace");
    if (workspace) {
      workspace.addEventListener("change", function () {
        loadCompareDatasets(side);
      });
    }
  });
  $("#runCompare").addEventListener("click", runCompare);
  $("#cmpFromEmpty").addEventListener("click", runCompare);
  $("#cmpSwap").addEventListener("click", function () {
    var sourceWorkspace = getSelectValue("cmpSourceWorkspace");
    var sourceModel = getSelectValue("cmpSourceModel");
    var sourceDesktop = getSelectValue("cmpSourceDesktop");
    var sourceType = state.compareSourceType;
    setSelectValue("cmpSourceWorkspace", getSelectValue("cmpTargetWorkspace"));
    setSelectValue("cmpTargetWorkspace", sourceWorkspace);
    setSelectValue("cmpSourceModel", getSelectValue("cmpTargetModel"));
    setSelectValue("cmpTargetModel", sourceModel);
    setSelectValue("cmpSourceDesktop", getSelectValue("cmpTargetDesktop"));
    setSelectValue("cmpTargetDesktop", sourceDesktop);
    setCompareType("source", state.compareTargetType);
    setCompareType("target", sourceType);
    loadCompareDatasets("source");
    loadCompareDatasets("target");
    app.toast(t("Source and target swapped"));
  });
  $("#cmpSearch").addEventListener("input", renderCompareTable);
  $("#cmpStatusFilter").addEventListener("change", renderCompareTable);
  $("#cmpTypeFilter").addEventListener("change", renderCompareTable);
  $("#cmpOnlyDiff").addEventListener("change", function (event) {
    state.compareOnlyDiff = event.target.checked;
    renderCompareTable();
  });
  $("#compareBody").addEventListener("click", function (event) {
    var row = event.target.closest("tr[data-id]");
    if (row) selectCompareRow(row.getAttribute("data-id"));
  });
  $("#compareBody").addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var row = event.target.closest("tr[data-id]");
    if (!row) return;
    event.preventDefault();
    selectCompareRow(row.getAttribute("data-id"));
  });
  $("#cmpValidate").addEventListener("click", validateCompare);
  $("#cmpExport").addEventListener("click", exportCompare);
  $("#cmpScript").addEventListener("click", generateCompareScript);
  $("#cmpApply").addEventListener("click", function () {
    app.toast(t("Comparison is read-only. Generate the script and apply it manually."));
  });
}
