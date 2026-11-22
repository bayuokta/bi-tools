// Halaman Compare Semantic Model (read-only, definisi TOM/TMDL persis).

import { app } from "../core/app_api.js";
import {
  getSelectValue,
  setSelectOptions,
  setSelectValue
} from "../core/combo.js";
import { $, $$, escapeHtml } from "../core/dom.js";
import { fmtInt } from "../core/format.js";
import { compareLanguage, highlightLine } from "../core/highlight.js";
import { t } from "../core/i18n.js";
import { state, store } from "../core/state.js";

var DEFAULT_OPTIONS = {
  measures: true,
  relationships: true,
  expressions: true,
  roles: false,
  perspectives: false,
  cultures: false,
  partitions: false,
  annotations: false,
  lineage_tag: false,
  tmsl: false,
  measure_dependencies: true
};

var OPTION_IDS = {
  perspectives: "#cmpOptPerspectives",
  cultures: "#cmpOptCultures",
  roles: "#cmpOptRoles",
  tmsl: "#cmpOptTmsl",
  partitions: "#cmpOptPartitions",
  annotations: "#cmpOptAnnotations",
  lineage_tag: "#cmpOptLineage",
  measure_dependencies: "#cmpOptMeasureDeps"
};

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
var diffScrollLock = false;

var TYPE_ICONS = {
  Table: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="1.6"/><path d="M3 9h18M9 9v11"/></svg>',
  Measure: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M6 19L18 5M6 5h3M15 19h3"/></svg>',
  Relationship: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M10 13.5a4 4 0 010-5.7l2.4-2.4a4 4 0 015.7 5.7l-1.6 1.6"/><path d="M14 10.5a4 4 0 010 5.7l-2.4 2.4a4 4 0 01-5.7-5.7l1.6-1.6"/></svg>',
  Expression: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M9 7l-5 5 5 5M15 7l5 5-5 5"/></svg>',
  Role: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.5 19a5.5 5.5 0 0111 0"/><path d="M16 6h5M16 10h5M16 14h3"/></svg>',
  "Data source": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>',
  Perspective: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10"/></svg>',
  Culture: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 010 18M12 3a15 15 0 000 18"/></svg>',
  "Calculation item": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M18 4H6l6 8-6 8h12"/></svg>'
};

function loadOptions() {
  var value = {};
  try {
    value = JSON.parse(store.get("pbi-compare-options", "{}") || "{}");
  } catch (error) {
    value = {};
  }
  var options = Object.assign({}, DEFAULT_OPTIONS, value || {});
  Object.keys(DEFAULT_OPTIONS).forEach(function (key) {
    options[key] = Boolean(options[key]);
  });
  state.compareOptions = options;
}

function saveOptions() {
  store.set("pbi-compare-options", JSON.stringify(state.compareOptions || DEFAULT_OPTIONS));
}

function syncOptionControls() {
  var options = state.compareOptions || DEFAULT_OPTIONS;
  Object.keys(OPTION_IDS).forEach(function (key) {
    var element = $(OPTION_IDS[key]);
    if (element) element.checked = Boolean(options[key]);
  });
}

function readOptionControls() {
  Object.keys(OPTION_IDS).forEach(function (key) {
    var element = $(OPTION_IDS[key]);
    if (element) state.compareOptions[key] = element.checked;
  });
  saveOptions();
}

function statusLabel(status) {
  return t(STATUS_LABELS[status] || status || "");
}

function sideType(side) {
  return side === "source" ? state.compareSourceType : state.compareTargetType;
}

function sidePrefix(side) {
  return side === "source" ? "cmpSource" : "cmpTarget";
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
    if (data.hint && !(data.workspaces || []).length) app.toast(data.hint);
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
  var options = Object.assign({}, state.compareOptions || DEFAULT_OPTIONS);
  options.measures = $("#cmpOptMeasures").checked;
  options.relationships = $("#cmpOptRelations").checked;
  options.expressions = $("#cmpOptQueries").checked;
  return {
    source: sidePayload("source"),
    target: sidePayload("target"),
    options: options
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
  state.compareOpen = {};
  if (result && (result.items || []).length) {
    var first = result.items.filter(function (item) {
      return item.status !== "same";
    })[0] || result.items[0];
    state.compareActive = first ? first.id : null;
  }
  if (result && (result.warnings || []).length) {
    app.addLog(
      t("Measure dependency warnings") + ": " + fmtInt(result.warnings.length),
      "warn"
    );
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

function itemMatches(item, query, status, type) {
  if (state.compareOnlyDiff && item.status === "same") return false;
  if (status === "diff" && item.status !== "different") return false;
  if (status === "same" && item.status !== "same") return false;
  if (status === "source" && item.status !== "source_only") return false;
  if (status === "target" && item.status !== "target_only") return false;
  if (type !== "all" && item.type !== type) return false;
  if (!query) return true;
  return (
    (item.name + " " + item.source_name + " " + item.target_name + " " + item.parent + " " + item.type)
      .toLowerCase()
      .indexOf(query) !== -1
  );
}

function compareGroups() {
  var query = ($("#cmpSearch").value || "").trim().toLowerCase();
  var status = $("#cmpStatusFilter").value;
  var type = $("#cmpTypeFilter").value;
  var items = compareItems();
  var tables = items.filter(function (item) { return item.type === "Table"; });
  var consumed = {};
  var groups = [];

  tables.forEach(function (table) {
    var children = items.filter(function (item) {
      return item.type !== "Table" && item.parent === table.name;
    });
    var visibleChildren = children.filter(function (item) {
      return itemMatches(item, query, status, type);
    });
    var tableVisible = itemMatches(table, query, status, type);
    if (!tableVisible && !visibleChildren.length) return;
    consumed[table.id] = true;
    visibleChildren.forEach(function (item) { consumed[item.id] = true; });
    groups.push({
      item: table,
      children: type === "Table" ? [] : visibleChildren
    });
  });

  items.forEach(function (item) {
    if (consumed[item.id] || item.type === "Table") return;
    if (!itemMatches(item, query, status, type)) return;
    groups.push({ item: item, children: [] });
  });
  return groups;
}

function treeRow(item, level, hasChildren, open) {
  var toggle = hasChildren
    ? '<button type="button" class="cmp-tree-toggle" data-compare-toggle="' +
      escapeHtml(item.id) + '" aria-expanded="' + (open ? "true" : "false") +
      '" aria-label="' + escapeHtml(open ? t("Collapse ") : t("Expand ")) +
      escapeHtml(item.name) + '">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg></button>'
    : '<span class="cmp-tree-toggle" aria-hidden="true"></span>';
  var icon = TYPE_ICONS[item.type] || TYPE_ICONS.Expression;
  return '<tr data-id="' + escapeHtml(item.id) + '" tabindex="0"' +
    (state.compareActive === item.id ? ' class="is-current"' : "") + ">" +
    '<td><div class="cmp-object" style="--depth:' + level + '">' + toggle +
      '<span class="cmp-object-icon">' + icon + "</span>" +
      '<span class="cmp-object-name" title="' + escapeHtml(item.name) + '">' +
      escapeHtml(item.name) + "</span></div></td>" +
    '<td class="name" title="' + escapeHtml(item.source_name || "—") + '">' +
      escapeHtml(item.source_name || "—") + "</td>" +
    '<td><span class="cmp-status ' + (STATUS_CLASSES[item.status] || "") + '">' +
      '<span class="dot"></span>' + escapeHtml(statusLabel(item.status)) + "</span></td>" +
    '<td class="name" title="' + escapeHtml(item.target_name || "—") + '">' +
      escapeHtml(item.target_name || "—") + "</td>" +
    "<td>" + escapeHtml(t(item.action || "Skip")) + "</td></tr>";
}

function renderCompareTable() {
  var groups = compareGroups();
  var wrap = $("#compareTableWrap");
  var empty = $("#cmpEmpty");
  var body = $("#compareBody");
  var html = [];
  groups.forEach(function (group) {
    var item = group.item;
    var hasChildren = group.children.length > 0;
    var open = state.compareOpen[item.id];
    if (open === undefined) {
      open = hasChildren && (item.status !== "same" ||
        group.children.some(function (child) { return child.status !== "same"; }));
    }
    html.push(treeRow(item, 0, hasChildren, open));
    if (open && hasChildren) {
      group.children.forEach(function (child) {
        html.push(treeRow(child, 1, false, false));
      });
    }
  });
  body.innerHTML = html.join("");
  wrap.hidden = !groups.length;
  empty.hidden = Boolean(groups.length);
  if (!groups.length) {
    $("#cmpEmptyTitle").textContent = state.compare
      ? t("No matching items")
      : t("No comparison yet");
    $("#cmpEmptyText").textContent = state.compare
      ? t("Change the keyword or filter to see other items.")
      : t("Choose source and target, then run the comparison. Results show definition differences in both models.");
    $("#cmpFromEmpty").hidden = Boolean(state.compare);
  }
  $("#cmpSummary").textContent = state.compare
    ? fmtInt(groups.length) + " / " + fmtInt(compareItems().length) + " " +
      t("groups shown") + " · " + fmtInt(compareItems().filter(function (item) {
        return item.status !== "same";
      }).length) + " " + t("changes")
    : t("Not compared yet");
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
  $("#cmpSummaryEmpty").hidden = Boolean(state.compare);
  $("#cmpSummaryBody").hidden = !state.compare;
  if (state.compare) {
    $("#cmpStatSource").textContent = (state.compare.source && state.compare.source.label) || "—";
    $("#cmpStatTarget").textContent = (state.compare.target && state.compare.target.label) || "—";
    $("#cmpStatCompared").textContent = fmtInt(compareItems().length);
    $("#cmpStatTime").textContent = state.compare.generated_at || "—";
    var warnings = state.compare.warnings || [];
    $("#cmpStatWarnings").textContent = fmtInt(warnings.length);
    $("#cmpStatWarnings").title = warnings.map(function (item) {
      return item.measure + ": " + item.message;
    }).join("\n");
  }
}

function renderCompareDetail() {
  var item = compareItems().filter(function (entry) {
    return entry.id === state.compareActive;
  })[0];
  if (!item) {
    $("#cmpDetail").innerHTML =
      '<p class="helper">' + escapeHtml(t("Select a row to see status, action, and definitions.")) + "</p>";
    return;
  }
  $("#cmpDetail").innerHTML =
    '<div class="cmp-detail-head"><div><h3 class="cmp-detail-name">' +
      escapeHtml(item.name) + '</h3><p class="cmp-detail-sub">' +
      escapeHtml(item.type) + (item.parent ? " · " + escapeHtml(item.parent) : "") +
      " · " + escapeHtml(statusLabel(item.status)) +
      '</p></div><span class="cmp-status ' + (STATUS_CLASSES[item.status] || "") +
      '"><span class="dot"></span>' + escapeHtml(statusLabel(item.status)) + "</span></div>" +
    '<p class="helper">' + escapeHtml(t("Suggested action")) + ": " +
      escapeHtml(t(item.action || "Skip")) + "</p>";
}

function renderDiffLine(line, row, side, language, blockStart, blockEnd) {
  if (!line) {
    return '<div class="diff-line is-spacer' +
      (blockStart ? " is-block-start" : "") +
      (blockEnd ? " is-block-end" : "") +
      '"><span class="ln"></span><span class="lt"></span></div>';
  }
  var classes = ["diff-line"];
  if (row.kind === "replace") classes.push("is-replace");
  if (side === "source" && (row.kind === "delete" || row.kind === "replace")) {
    classes.push("is-source");
  }
  if (side === "target" && (row.kind === "insert" || row.kind === "replace")) {
    classes.push("is-target");
  }
  if (blockStart) classes.push("is-block-start");
  if (blockEnd) classes.push("is-block-end");
  var content;
  if (line.segments && line.segments.length) {
    content = line.segments.map(function (segment) {
      var html = highlightLine(segment.text, language);
      if (!segment.changed) return html;
      return '<span class="diff-token is-changed">' + html + "</span>";
    }).join("");
  } else {
    content = highlightLine(line.text, language);
  }
  return '<div class="' + classes.join(" ") + '">' +
    '<span class="ln">' + line.number + "</span>" +
    '<span class="lt">' + content + "</span></div>";
}

function renderDiffPane(element, meta, rows, side, language) {
  var lines = rows.map(function (row) { return row[side]; }).filter(Boolean);
  var changed = rows.filter(function (row) {
    if (side === "source") return row.kind === "delete" || row.kind === "replace";
    return row.kind === "insert" || row.kind === "replace";
  }).length;
  $(meta).textContent = lines.length
    ? fmtInt(lines.length) + " " + t("lines") + " · " +
      fmtInt(changed) + " " + t("changed")
    : t("No definition");
  $(element).innerHTML = rows.length
    ? rows.map(function (row, index) {
        var blockStart = Boolean(row.block) &&
          (index === 0 || rows[index - 1].block !== row.block);
        var blockEnd = Boolean(row.block) &&
          (index === rows.length - 1 || rows[index + 1].block !== row.block);
        return renderDiffLine(row[side], row, side, language, blockStart, blockEnd);
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
  var diff = item.diff || { rows: [], stats: {} };
  var rows = diff.rows || [];
  var language = compareLanguage(state.compare && state.compare.options);
  renderDiffPane("#cmpDiffSource", "#cmpDiffSourceMeta", rows, "source", language);
  renderDiffPane("#cmpDiffTarget", "#cmpDiffTargetMeta", rows, "target", language);
  var stats = diff.stats || {};
  $("#cmpDiffSummary").textContent = rows.length
    ? fmtInt(stats.blocks || 0) + " " + t("blocks") + " · +" +
      fmtInt(stats.added || 0) + " −" + fmtInt(stats.removed || 0) + " · " +
      fmtInt(stats.changed || 0) + " " + t("changed")
    : "";
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

function openOptionsDialog() {
  syncOptionControls();
  var dialog = $("#compareOptionsDialog");
  if (dialog && !dialog.open) dialog.showModal();
}

function closeOptionsDialog() {
  readOptionControls();
  var dialog = $("#compareOptionsDialog");
  if (dialog && dialog.open) dialog.close();
  renderCompare();
}

function bindDiffScroll(first, second) {
  function sync(source, target) {
    source.addEventListener("scroll", function () {
      if (diffScrollLock) return;
      diffScrollLock = true;
      target.scrollTop = source.scrollTop;
      window.requestAnimationFrame(function () {
        diffScrollLock = false;
      });
    }, { passive: true });
  }
  sync(first, second);
  sync(second, first);
}

export function initCompareEvents() {
  if (!state.compareOptions) loadOptions();
  syncOptionControls();
  bindDiffScroll($("#cmpDiffSource"), $("#cmpDiffTarget"));

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
  $("#compareOptions").addEventListener("click", openOptionsDialog);
  $("#closeCompareOptions").addEventListener("click", closeOptionsDialog);
  $("#doneCompareOptions").addEventListener("click", closeOptionsDialog);
  $("#resetCompareOptions").addEventListener("click", function () {
    state.compareOptions = Object.assign({}, DEFAULT_OPTIONS);
    syncOptionControls();
    saveOptions();
    app.toast(t("Comparison options reset"));
  });
  $("#compareOptionsDialog").addEventListener("click", function (event) {
    if (event.target === event.currentTarget) closeOptionsDialog();
  });
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
    var toggle = event.target.closest("[data-compare-toggle]");
    if (toggle) {
      var id = toggle.getAttribute("data-compare-toggle");
      state.compareOpen[id] = !state.compareOpen[id];
      renderCompareTable();
      return;
    }
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
