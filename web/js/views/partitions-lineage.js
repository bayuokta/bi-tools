import { app } from "../core/app_api.js";
import { getSelectValue, setSelectOptions } from "../core/combo.js";
import { $, $$, escapeHtml } from "../core/dom.js";
import { fmtInt } from "../core/format.js";
import { t, tr } from "../core/i18n.js";
import { state } from "../core/state.js";

  // -- Partisi ------------------------------------------------------------
  function partitionRows() {
    return (state.partitions && state.partitions.partitions) || [];
  }

  function partitionSelectedRows() {
    return partitionRows().filter(function (_row, index) {
      return Boolean(state.partitionSelected[index]);
    });
  }

  function partitionTime(value) {
    var text = String(value || "").replace("T", " ");
    return text ? text.slice(0, 19) : "-";
  }

  function partitionRefreshLabel(value) {
    var select = $("#partitionRefreshType");
    if (!select) return value;
    var option = select.options[select.selectedIndex];
    return option ? option.textContent : value;
  }

  export function partitionLoadState() {
    if (!app.apiReady()) return Promise.resolve();
    return app.api().get("/api/partitions/state").then(function (data) {
      state.partitionStateLoaded = true;
      setSelectOptions(
        "partitionWsSelect",
        (data.workspaces || []).map(function (item) {
          return { value: item.id, label: item.label, data: item };
        }),
        "Choose a workspace…"
      );
      setSelectOptions("partitionDatasetSelect", [], "Choose a semantic model…");
      var missing = data.credentials_missing || [];
      app.setChip(
        $("#partitionSourceChip"),
        missing.length ? "warn" : "idle",
        missing.length ? t("Credentials are incomplete") : t("Not loaded")
      );
      $("#partitionHint").textContent = tr(data.hint) || "";
      partitionRender();
      return data;
    }).catch(function (error) {
      app.addLog(t("Partition catalog could not be read: ") + error.message, "warn");
    });
  }

  export function partitionLoadDatasets() {
    var workspaceId = getSelectValue("partitionWsSelect");
    state.partitions = null;
    state.partitionLoaded = false;
    state.partitionSelected = {};
    if (!workspaceId || !app.apiReady()) {
      setSelectOptions("partitionDatasetSelect", [], "Choose a semantic model…");
      partitionRender();
      return Promise.resolve();
    }
    setSelectOptions("partitionDatasetSelect", [], "Loading semantic models…");
    return app.api().get(
      "/api/partitions/workspaces/" + encodeURIComponent(workspaceId) + "/datasets"
    ).then(function (data) {
      setSelectOptions(
        "partitionDatasetSelect",
        (data.datasets || []).map(function (item) {
          return { value: item.id, label: item.name, data: item };
        }),
        "Choose a semantic model…"
      );
      partitionRender();
      return data;
    }).catch(function (error) {
      setSelectOptions("partitionDatasetSelect", [], "Choose a semantic model…");
      app.reportError(error);
    });
  }

  function partitionApply(result) {
    state.partitions = result;
    state.partitionLoaded = true;
    state.partitionSelected = {};
    var rows = partitionRows();
    var tables = {};
    rows.forEach(function (row) { tables[row.table] = true; });
    var stamp = partitionTime(result.loaded_at);
    $("#partitionSummary").textContent =
      fmtInt(rows.length) + t(" partitions · ") +
      fmtInt(Object.keys(tables).length) + t(" tables · ") + stamp;
    app.setChip($("#partitionSourceChip"), "ok", t("Loaded via XMLA"));
    var warnings = result.warnings || [];
    $("#partitionHint").textContent = warnings.length
      ? warnings.map(tr).join(" · ")
      : t("Inventory loaded. Select partitions, choose a refresh type, then process.");
    partitionRender();
  }

  export function partitionRender() {
    var rows = partitionRows();
    var wrap = $("#partitionTableWrap");
    var empty = $("#partitionEmptyState");
    var count = partitionSelectedRows().length;
    $("#processSelectedPartitions").disabled = count === 0;
    $("#partitionSelectionSummary").textContent = count
      ? fmtInt(count) + t(count === 1 ? " partition selected" : " partitions selected")
      : t("No partitions selected");
    $("#partitionSelectAll").checked = rows.length > 0 && count === rows.length;
    $("#partitionSelectAll").indeterminate = count > 0 && count < rows.length;
    if (!rows.length) {
      wrap.hidden = true;
      empty.hidden = false;
      $("#partitionSummary").textContent = state.partitionLoaded
        ? t("No partitions found")
        : t("Not loaded yet");
      return;
    }
    wrap.hidden = false;
    empty.hidden = true;
    $("#partitionBody").innerHTML = rows.map(function (row, index) {
      var selected = Boolean(state.partitionSelected[index]);
      var rowsText = row.rows == null ? "-" : fmtInt(row.rows);
      var range = row.range || "-";
      var rangeTitle = row.range_source
        ? t("Range source: ") + row.range_source
        : "";
      return '<tr data-part-index="' + index + '"' +
        (selected ? ' class="is-selected"' : "") + ">" +
        '<td><input type="checkbox" class="partition-check" data-index="' + index +
        '" aria-label="' + escapeHtml(t("Select partition ") + row.table + " / " + row.partition) +
        '"' + (selected ? " checked" : "") + "></td>" +
        '<td class="cell-name" title="' + escapeHtml(row.table || "") + '">' +
        escapeHtml(row.table || "") + "</td>" +
        '<td class="cell-name" title="' + escapeHtml(row.partition || "") + '">' +
        escapeHtml(row.partition || "") + "</td>" +
        '<td class="cell-num">' + rowsText + "</td>" +
        '<td title="' + escapeHtml(rangeTitle) + '">' + escapeHtml(range) + "</td>" +
        "<td>" + escapeHtml(row.mode || "-") + "</td>" +
        "<td>" + escapeHtml(row.source_type || "-") + "</td>" +
        "<td>" + escapeHtml(row.state || "-") + "</td>" +
        "<td>" + escapeHtml(partitionTime(row.last_processed)) + "</td>" +
        "<td>" + escapeHtml(partitionTime(row.modified)) + "</td>" +
        "</tr>";
    }).join("");
    if (!state.partitionLoaded) {
      $("#partitionSummary").textContent = t("Not loaded yet");
    }
  }

  export function partitionToggleAll(checked) {
    state.partitionSelected = {};
    if (checked) {
      partitionRows().forEach(function (_row, index) {
        state.partitionSelected[index] = true;
      });
    }
    partitionRender();
  }

  export function partitionOpenConfirm() {
    var selected = partitionSelectedRows();
    if (!selected.length) {
      app.toast(t("Select at least one partition first"));
      return;
    }
    $("#partitionDialogCount").textContent =
      fmtInt(selected.length) +
      t(selected.length === 1
        ? " partition will be processed."
        : " partitions will be processed.");
    $("#partitionDialogTargets").innerHTML = selected.map(function (row) {
      return "<div>" + escapeHtml(row.table + " / " + row.partition) + "</div>";
    }).join("");
    $("#partitionDialogType").textContent =
      t("Refresh type: ") + partitionRefreshLabel(getSelectValue("partitionRefreshType"));
    $("#partitionConfirmCheck").checked = false;
    $("#partitionConfirmText").value = "";
    $("#partitionConfirmError").hidden = true;
    $("#partitionConfirmError").textContent = "";
    $("#partitionDialog").showModal();
    $("#partitionConfirmText").focus();
  }

  export function partitionCloseDialog() {
    var dialog = $("#partitionDialog");
    if (dialog.open) dialog.close();
  }

  export function partitionConfirmProcess() {
    if (!$("#partitionConfirmCheck").checked) {
      $("#partitionConfirmError").textContent =
        t("Check the acknowledgement first.");
      $("#partitionConfirmError").hidden = false;
      return;
    }
    if ($("#partitionConfirmText").value.trim().toUpperCase() !== "PROCESS") {
      $("#partitionConfirmError").textContent = t("Type PROCESS to confirm.");
      $("#partitionConfirmError").hidden = false;
      return;
    }
    var selected = partitionSelectedRows();
    if (!selected.length) {
      partitionCloseDialog();
      app.toast(t("Select at least one partition first"));
      return;
    }
    if (state.jobId) {
      app.toast(t("Another job is still running"));
      return;
    }
    partitionCloseDialog();
    state.partitionRunning = true;
    app.startJob({
      kind: "partitions-refresh",
      path: "/api/partitions/refresh",
      body: {
        workspace_id: getSelectValue("partitionWsSelect"),
        dataset_id: getSelectValue("partitionDatasetSelect"),
        refresh_type: getSelectValue("partitionRefreshType"),
        confirmation: "PROCESS",
        targets: selected.map(function (row) {
          return { table: row.table, partition: row.partition };
        })
      },
      label: t("Refresh partitions"),
      button: $("#processSelectedPartitions"),
      onDone: function (snapshot) {
        state.partitionRunning = false;
        if (snapshot.result) {
          partitionApply(snapshot.result);
          app.toast(tr((snapshot.result.refresh || {}).message) ||
            t("Partition refresh completed."));
        }
      }
    });
  }

  export function partitionLoadInventory() {
    var workspaceId = getSelectValue("partitionWsSelect");
    var datasetId = getSelectValue("partitionDatasetSelect");
    if (!workspaceId || !datasetId) {
      app.toast(t("Choose a workspace and semantic model first"));
      return;
    }
    if (state.partitionRunning || state.jobId) {
      app.toast(t("Another job is still running"));
      return;
    }
    state.partitionRunning = true;
    app.startJob({
      kind: "partitions-inventory",
      path: "/api/partitions/inventory",
      body: { workspace_id: workspaceId, dataset_id: datasetId },
      label: t("Load partition inventory"),
      button: $("#reloadPartitions"),
      onDone: function (snapshot) {
        if (snapshot.result) partitionApply(snapshot.result);
      }
    });
  }

  // -- Lineage ------------------------------------------------------------
  var NODE_HUE_BY_TYPE = {
    Database: "db",
    Datasource: "db",
    Dataflow: "flow",
    "Semantic Model": "model",
    SemanticModel: "model",
    Table: "table",
    "Tables": "table",
    Measure: "measure",
    Report: "report",
    PaginatedReport: "report",
    App: "report",
    Dashboard: "neutral",
    Workspace: "neutral"
  };

  var NODE_ICONS = {
    db: '<ellipse cx="5" cy="2.6" rx="3.6" ry="1.5"></ellipse>' +
      '<path d="M1.4 2.6v4.8c0 .83 1.61 1.5 3.6 1.5s3.6-.67 3.6-1.5V2.6"></path>',
    flow: '<path d="M1 3h4.2l1.6 1.6h2.2"></path><path d="M1 7h3.1l1.4-1.4"></path>' +
      '<path d="M7.6 2.2l1.4 2.4-1.4 2.4"></path>',
    model: '<path d="M5 1.2l3.8 1.9v3.8L5 8.8 1.2 6.9V3.1z"></path><path d="M1.2 3.1L5 5l3.8-1.9M5 5v3.8"></path>',
    table: '<rect x="1.4" y="2.2" width="7.2" height="5.6" rx="1"></rect><path d="M1.4 4.6h7.2M4.4 2.2v5.6"></path>',
    measure: '<path d="M7.8 2.4H2.4l2.7 2.6-2.7 2.6h5.4"></path>',
    report: '<path d="M2.4 1.4h3.4l2 2v5.2H2.4z"></path><path d="M5.8 1.4v2h2"></path>',
    neutral: '<circle cx="5" cy="5" r="2.2"></circle>'
  };

  function nodeHue(type) {
    return NODE_HUE_BY_TYPE[type] || "neutral";
  }

  function nodeIconMarkup(hue, x, y) {
    return '<g class="node-icon" transform="translate(' + x + " " + y + ')" fill="none" ' +
      'stroke="currentColor" stroke-width="1.1" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true">' +
      (NODE_ICONS[hue] || NODE_ICONS.neutral) + "</g>";
  }

  function clipLabel(text, max) {
    var value = String(text || "");
    return value.length > max ? value.slice(0, max - 1) + "\u2026" : value;
  }

  function nodeTypeLabel(type) {
    return String(type || "").replace(/([a-z0-9])([A-Z])/g, "$1 $2").toUpperCase();
  }
  function lineageTypeName(type) {
    return String(type || "").replace(/([a-z0-9])([A-Z])/g, "$1 $2");
  }
  export function lineageLoadState() {
    if (!app.apiReady()) return Promise.resolve();
    if (state.lineageStatePromise) return state.lineageStatePromise;
    state.lineageStatePromise = app.api().get("/api/lineage/state").then(function (data) {
      state.lineageHasDb = Boolean(data.readable);
      state.lineageStateReady = true;
      state.depth = Number(data.depth || 3);
      state.direction = data.direction || "upstream";
      var types = [{ value: "", label: t("All types") }].concat(
        (data.node_types || []).map(function (item) {
          return { value: item, label: item };
        })
      );
      setSelectOptions("lineageType", types, null);
      var nodeTypes = (data.node_types || []).map(function (item) {
        return { value: item, label: lineageTypeName(item) };
      });
      setSelectOptions(
        "lineageNodeType",
        [{ value: "", label: t("All types") }].concat(nodeTypes),
        null
      );
      state.lineageNodeType = getSelectValue("lineageNodeType") || "";
      $("#lineageSearch").disabled = !data.readable;
      $("#lineageSearchBtn").disabled = !data.readable;
      $("#lineageWorkspace").disabled = !data.readable;
      $("#lineageType").disabled = !data.readable;
      $("#lineageNodeType").disabled = !data.readable;
      $("#depthVal").textContent = state.depth + t(" levels");
      $("#depthMinus").disabled = true;
      $("#depthPlus").disabled = false;
      $("#dirUpstream").setAttribute("aria-pressed", String(state.direction === "upstream"));
      $("#dirDownstream").setAttribute("aria-pressed", String(state.direction === "downstream"));
      if (!data.readable) {
        $("#lineageResults").innerHTML =
          '<div class="empty" style="padding:18px 8px"><div class="empty-title">' + t("Database is not ready") + "</div>" +
          '<p class="empty-text">' + escapeHtml(data.status || "") + "</p></div>";
        $("#lineageCount").textContent = "";
        $("#lineageRootChip").innerHTML = '<span class="dot"></span>' + t("No root selected");
        $("#lineageDetail").innerHTML =
          '<p class="helper">' + escapeHtml(data.status || "") + "</p>";
        $("#exportCsv").disabled = true;
        $("#exportSvg").disabled = true;
        $("#exportPng").disabled = true;
        return data;
      }
      if (state.lineageQuery) {
        // Pengguna sudah mencari sebelum status selesai dimuat; jangan timpa
        // hasil/kolom pencarian yang sedang tampil.
        return data;
      }
      $("#lineageSearch").value = "";
      $("#lineageResults").innerHTML =
        '<div class="empty" style="padding:18px 8px"><div class="empty-title">' +
        t("No search yet") + '</div>' +
        '<p class="empty-text">' +
        t("Search for a report, semantic model, table, or measure.") + "</p></div>";
      $("#lineageCount").textContent =
        (data.items || 0) + " item \u00b7 " + (data.workspaces || 0) + t(" workspaces");
      $("#lineageRootChip").innerHTML = '<span class="dot"></span>' + t("No root selected");
      $("#lineageDetail").innerHTML =
        '<p class="helper">' + t("Choose a search result to view its lineage.") + "</p>";
      $("#exportCsv").disabled = true;
      $("#exportSvg").disabled = true;
      $("#exportPng").disabled = true;
      return data;
    }).catch(function (error) {
      app.addLog(t("Lineage status could not be read: ") + error.message, "warn");
    }).finally(function () {
      state.lineageStatePromise = null;
    });
    return state.lineageStatePromise;
  }

  function lineageSearchQuery(query, workspace, type) {
    if (!state.lineageHasDb) {
      app.toast(t("The lineage database is not ready; run Data sync first"));
      return Promise.resolve();
    }
    if (!query && !workspace && !type) {
      app.toast(t("Enter a keyword or filter first"));
      return Promise.resolve();
    }
    return app.api().get(
      "/api/lineage/search?q=" + encodeURIComponent(query) +
      "&workspace=" + encodeURIComponent(workspace) +
      "&type=" + encodeURIComponent(type) +
      "&limit=100"
    ).then(function (data) {
      lineageRenderResults(data.results || []);
      if (data.message) $("#lineageCount").textContent = tr(data.message);
      return data;
    }).catch(reportError);
  }

  export function lineageSearch() {
    if (!app.apiReady()) return Promise.resolve();
    var query = $("#lineageSearch").value.trim();
    var workspace = $("#lineageWorkspace").value.trim();
    var type = getSelectValue("lineageType") || "";
    // Tandai lebih dulu agar status yang datang belakangan tidak menghapus
    // kata kunci yang sedang diketik.
    state.lineageQuery = query;
    if (!state.lineageStateReady) {
      // Pengguna bisa menekan Cari sebelum /api/lineage/state selesai.
      return lineageLoadState().then(function () {
        return lineageSearchQuery(query, workspace, type);
      });
    }
    return lineageSearchQuery(query, workspace, type);
  }

  function lineageRenderResults(rows) {
    var box = $("#lineageResults");
    if (!rows.length) {
      box.innerHTML =
        '<div class="empty" style="padding:18px 8px"><div class="empty-title">' + t("No items") + "</div>" +
        '<p class="empty-text">' + t("Change the keyword or workspace filter.") + "</p></div>";
      $("#lineageCount").textContent = t("0 results");
      return;
    }
    box.innerHTML = rows.map(function (item) {
      var id = String(item.node_id || item.id || "");
      var name = item.name || id;
      var workspace = item.workspace_name || "";
      var type = item.node_type || "";
      return '<button class="result-item" type="button" data-id="' + escapeHtml(id) +
        '" aria-pressed="' + (id === state.rootId ? "true" : "false") + '">' +
        '<span class="result-name">' + escapeHtml(name) + "</span>" +
        '<span class="result-meta">' + escapeHtml(workspace) + "</span>" +
        '<span class="result-type chip chip-idle">' + escapeHtml(type) + "</span></button>";
    }).join("");
    $("#lineageCount").textContent = rows.length + t(" results");
  }

  export function lineageOpen(nodeId) {
    if (!nodeId || !app.apiReady()) return Promise.resolve();
    return app.api().get(
      "/api/lineage/node/" + encodeURIComponent(nodeId) +
      "?direction=" + encodeURIComponent(state.direction) +
      "&depth=" + encodeURIComponent(state.depth)
    ).then(function (data) {
      state.lineageData = data;
      state.lineageGraph = data.graph || null;
      state.rootId = String((data.node && data.node.node_id) || nodeId);
      state.selectedId = state.rootId;
      state.lineageNodesLive = {};
      ((data.graph && data.graph.nodes) || []).forEach(function (node) {
        state.lineageNodesLive[node.id] = node;
      });
      state.lineageZoom = 1;
      state.lineagePanX = 0;
      state.lineagePanY = 0;
      lineageRenderGraph();
      lineageRenderDetail(data.node || {});
      $("#lineageRootChip").innerHTML =
        '<span class="dot"></span>' + t("Root: ") + escapeHtml((data.node && data.node.name) || nodeId);
      $("#lineageRootChip").title =
        "Upstream " + (data.upstream_count || 0) + " item \u00b7 downstream " +
        (data.downstream_count || 0) + t(" items") +
        (data.truncated ? " \u00b7 " + data.truncated + t(" nodes truncated") : "");
      $("#depthVal").textContent = state.depth + t(" levels");
      $("#depthMinus").disabled = state.depth <= 1;
      $("#depthPlus").disabled = state.depth >= 15;
      $("#exportCsv").disabled = false;
      $("#exportSvg").disabled = false;
      $("#exportPng").disabled = false;
      $$("#lineageResults .result-item").forEach(function (item) {
        item.setAttribute("aria-pressed", String(item.dataset.id === state.rootId));
      });
      return data;
    }).catch(reportError);
  }

  export function applyLineageZoom() {
    var svg = $("#lineageSvg");
    if (!svg) return;
    var baseWidth = state.lineageBaseWidth || 780;
    var baseHeight = state.lineageBaseHeight || 280;
    var zoom = state.lineageZoom || 1;
    var width = baseWidth / zoom;
    var height = baseHeight / zoom;
    var x = (baseWidth - width) / 2 + (state.lineagePanX || 0);
    var y = (baseHeight - height) / 2 + (state.lineagePanY || 0);
    svg.setAttribute("viewBox", x + " " + y + " " + width + " " + height);
    var label = $("#lineageZoomValue");
    if (label) label.textContent = Math.round(zoom * 100) + "%";
    var out = $("#lineageZoomOut");
    var inn = $("#lineageZoomIn");
    if (out) out.disabled = zoom <= 0.6;
    if (inn) inn.disabled = zoom >= 2.5;
  }

  export function setLineageZoom(value) {
    state.lineageZoom = Math.max(0.6, Math.min(2.5, value));
    applyLineageZoom();
  }

  var LINEAGE_NODE_W = 176;
  var LINEAGE_NODE_H = 64;
  var LINEAGE_COL_GAP = 44;
  var LINEAGE_ROW_GAP = 20;

  export function lineageLayout(graph) {
    var nodes = (graph && graph.nodes) || [];
    if (!nodes.length) {
      return {
        positions: {},
        width: 780,
        height: 280,
        nodeW: LINEAGE_NODE_W,
        nodeH: LINEAGE_NODE_H
      };
    }
    var columns = nodes.map(function (node) { return Number(node.column || 0); });
    var rows = nodes.map(function (node) { return Number(node.row || 0); });
    var minCol = Math.min.apply(null, columns);
    var maxCol = Math.max.apply(null, columns);
    var minRow = Math.min.apply(null, rows);
    var maxRow = Math.max.apply(null, rows);
    var positions = {};
    nodes.forEach(function (node) {
      positions[node.id] = {
        x: 40 + (Number(node.column || 0) - minCol) * (LINEAGE_NODE_W + LINEAGE_COL_GAP),
        y: 34 + (Number(node.row || 0) - minRow) * (LINEAGE_NODE_H + LINEAGE_ROW_GAP)
      };
    });
    return {
      positions: positions,
      width: Math.max(
        780, 80 + (maxCol - minCol) * (LINEAGE_NODE_W + LINEAGE_COL_GAP) + LINEAGE_NODE_W
      ),
      height: Math.max(
        280, 68 + (maxRow - minRow) * (LINEAGE_NODE_H + LINEAGE_ROW_GAP) + LINEAGE_NODE_H
      ),
      nodeW: LINEAGE_NODE_W,
      nodeH: LINEAGE_NODE_H
    };
  }

  function lineageVisibleNodes(graph) {
    var nodes = (graph && graph.nodes) || [];
    var type = state.lineageNodeType;
    if (!type) return nodes;
    return nodes.filter(function (node) {
      return String(node.type || "") === type;
    });
  }

  function lineageRenderFilterCount(graph) {
    var label = $("#lineageFilterCount");
    if (!label) return;
    if (!state.lineageNodeType) {
      label.textContent = "";
      return;
    }
    var shown = lineageVisibleNodes(graph).length;
    var total = ((graph && graph.nodes) || []).length;
    label.textContent = fmtInt(shown) + " / " + fmtInt(total);
  }

  export function lineageRenderGraph() {
    var graph = state.lineageGraph;
    if (!graph || !(graph.nodes || []).length) {
      $("#lineageLayer").innerHTML = "";
      state.lineageLayout = null;
      state.lineageBaseWidth = 780;
      state.lineageBaseHeight = 280;
      state.lineagePanX = 0;
      state.lineagePanY = 0;
      lineageRenderFilterCount(graph);
      applyLineageZoom();
      return;
    }
    var layout = lineageLayout(graph);
    state.lineageLayout = layout;
    state.lineageBaseWidth = layout.width;
    state.lineageBaseHeight = layout.height;
    var visible = {};
    lineageVisibleNodes(graph).forEach(function (node) {
      visible[node.id] = true;
    });
    var filtered = Boolean(state.lineageNodeType);
    var nodeW = layout.nodeW;
    var nodeH = layout.nodeH;
    var edges = "";
    (graph.edges || []).forEach(function (edge, index) {
      var from = layout.positions[edge.source];
      var to = layout.positions[edge.target];
      if (!from || !to) return;
      var forward = to.x > from.x;
      var x1 = from.x + (forward ? nodeW : 0);
      var x2 = to.x + (forward ? 0 : nodeW);
      var y1 = from.y + nodeH / 2;
      var y2 = to.y + nodeH / 2;
      var mid = (x1 + x2) / 2;
      var hidden = filtered && (!visible[edge.source] || !visible[edge.target]);
      edges += '<path class="edge' + (hidden ? " is-filtered" : "") +
        '" data-edge="' + index +
        '" d="M' + x1 + " " + y1 + " C" + mid + " " + y1 + ", " + mid + " " +
        y2 + ", " + x2 + " " + y2 +
        '" fill="none" marker-end="url(#arrow)"><title>' +
        escapeHtml(edge.type || "") + "</title></path>";
    });
    var markup = "";
    (graph.nodes || []).forEach(function (node) {
      var pos = layout.positions[node.id];
      if (!pos) return;
      var name = String(node.name || node.id);
      var type = String(node.type || "");
      var workspace = String(node.workspace || "");
      var hue = nodeHue(type);
      var hidden = filtered && !visible[node.id];
      markup += '<g class="node lineage-node' + (hidden ? " is-filtered" : "") +
        '" data-hue="' + hue +
        '" data-side="' + escapeHtml(node.side || "") +
        '" tabindex="0" role="button" data-id="' + escapeHtml(node.id) +
        '" aria-current="' + (node.id === state.rootId ? "true" : "false") +
        '" aria-label="' + escapeHtml(name) + ", " + escapeHtml(type) + '">' +
        "<title>" + escapeHtml(name) + " \u00b7 " + escapeHtml(type) +
        (workspace ? " \u00b7 " + escapeHtml(workspace) : "") + "</title>" +
        '<rect class="node-halo" x="' + (pos.x - 3) + '" y="' + (pos.y - 3) +
        '" width="' + (nodeW + 6) + '" height="' + (nodeH + 6) + '" rx="10"></rect>' +
        '<rect class="node-box" x="' + pos.x + '" y="' + pos.y +
        '" width="' + nodeW + '" height="' + nodeH + '" rx="8"></rect>' +
        '<rect class="node-band" x="' + (pos.x + 1) + '" y="' + (pos.y + 1) +
        '" width="' + (nodeW - 2) + '" height="17" rx="7"></rect>' +
        '<rect class="node-band" x="' + (pos.x + 1) + '" y="' + (pos.y + 9) +
        '" width="' + (nodeW - 2) + '" height="9"></rect>' +
        '<path class="node-band-rule" d="M' + (pos.x + 1) + " " + (pos.y + 18) +
        "H" + (pos.x + nodeW - 1) + '"></path>' +
        nodeIconMarkup(hue, pos.x + 8, pos.y + 4) +
        '<text class="node-type" x="' + (pos.x + 21) + '" y="' + (pos.y + 12.6) + '">' +
        escapeHtml(nodeTypeLabel(type)) + "</text>" +
        '<text class="node-name" x="' + (pos.x + 10) + '" y="' + (pos.y + 36) + '">' +
        escapeHtml(clipLabel(name, 25)) + "</text>" +
        '<text class="node-meta" x="' + (pos.x + 10) + '" y="' + (pos.y + 51) + '">' +
        escapeHtml(clipLabel(workspace, 27)) + "</text>" +
        "</g>";
    });
    $("#lineageLayer").innerHTML = edges + markup;
    lineageRenderFilterCount(graph);
    lineageApplySelection();
    applyLineageZoom();
  }

  function lineageApplySelection() {
    var graph = state.lineageGraph;
    if (!graph) return;
    var neighbours = {};
    (graph.edges || []).forEach(function (edge, index) {
      var selected = edge.source === state.selectedId || edge.target === state.selectedId;
      if (selected) {
        neighbours[edge.source] = true;
        neighbours[edge.target] = true;
      }
      var path = document.querySelector('#lineageLayer .edge[data-edge="' + index + '"]');
      if (path) path.classList.toggle("is-selected", selected);
    });
    $$("#lineageLayer .lineage-node").forEach(function (element) {
      var id = element.getAttribute("data-id");
      var side = element.getAttribute("data-side") || "";
      element.classList.toggle("is-sel", id === state.selectedId);
      element.classList.toggle(
        "is-near", id !== state.selectedId && Boolean(neighbours[id])
      );
      element.classList.toggle(
        "is-muted", Boolean(side && side !== "root" && side !== state.direction)
      );
    });
  }

  export function lineageRenderDetail(node) {
    var selected = state.lineageNodesLive[state.selectedId] || {};
    var payload = selected.payload || node || {};
    var name = payload.name || node.name || t("(unnamed)");
    var type = payload.node_type || selected.type || node.node_type || "";
    var workspace = payload.workspace_name || selected.workspace || node.workspace_name || "";
    var neighbours = [];
    var byId = state.lineageNodesLive;
    ((state.lineageGraph && state.lineageGraph.edges) || []).forEach(function (edge) {
      if (edge.source === state.selectedId && byId[edge.target]) {
        neighbours.push(byId[edge.target]);
      } else if (edge.target === state.selectedId && byId[edge.source]) {
        neighbours.push(byId[edge.source]);
      }
    });
    var rows = [];
    function add(label, value) {
      if (value === undefined || value === null || value === "") return;
      rows.push("<dt>" + escapeHtml(label) + "</dt><dd>" + escapeHtml(String(value)) + "</dd>");
    }
    add(t("Type"), type);
    add("Workspace", workspace);
    add(t("Owner"), payload.owner);
    var modified = String(payload.last_modified_at || "").replace("T", " ").slice(0, 16);
    add(t("Modified"), modified);
    add("Endorsement", payload.endorsement && payload.endorsement !== "None" ? payload.endorsement : "");
    add(t("Sensitivity"), payload.sensitivity_label);
    add(t("Depth"), payload.depth);
    add(t("Relationships"), payload.edge_type);
    add(t("Source type"), payload.datasource_type);
    add("Server", payload.server);
    add("Database", payload.database_name);
    add("Path/URL", payload.path_or_url);
    add("Node ID", payload.node_id || state.selectedId);
    if (payload.is_active === 0 || payload.is_active === false) {
      add("Status", t("inactive (not seen in the last scan)"));
    }
    var chips = neighbours.length
      ? neighbours.map(function (item) {
          return '<button class="chip chip-idle analysis-link" type="button" data-lineage-node="' +
            escapeHtml(item.id) + '">' + escapeHtml(item.name || item.id) + "</button>";
        }).join(" ")
      : '<span class="helper">' + t("No direct relationship.") + "</span>";
    var url = "";
    if ((type || "").toLowerCase().indexOf("report") !== -1 && payload.workspace_id) {
      var reportId = payload.report_id || payload.node_id || "";
      var match = String(reportId).match(/[0-9a-f]{8}-[0-9a-f-]{27}/i);
      if (match) {
        url = "https://app.powerbi.com/groups/" + encodeURIComponent(payload.workspace_id) +
          "/reports/" + encodeURIComponent(match[0]);
      }
    }
    $("#lineageDetail").innerHTML =
      '<div class="detail-head"><div><div class="detail-name">' + escapeHtml(name) + "</div>" +
      '<div class="helper">' + escapeHtml(type) + (workspace ? " \u00b7 " + escapeHtml(workspace) : "") +
      "</div></div>" +
      '<span class="row-inline">' +
      (url ? '<a class="btn btn-sm" href="' + escapeHtml(url) +
        '" target="_blank" rel="noopener">' + t("Open report") + "</a>" : "") +
      '<button class="btn btn-sm" type="button" id="makeRoot"' +
      (state.selectedId === state.rootId ? " disabled" : "") + ">" +
      t("Make root") + "</button></span></div>" +
      '<dl class="kv">' + rows.join("") + "</dl>" +
      '<div class="dep-chips">' + chips + "</div>";
    var makeRoot = $("#makeRoot");
    if (makeRoot) {
      makeRoot.addEventListener("click", function () {
        lineageOpen(state.selectedId);
        app.toast(t("Lineage root updated"));
      });
    }
    $$("#lineageDetail [data-lineage-node]").forEach(function (button) {
      button.addEventListener("click", function () {
        lineageSelectNode(button.getAttribute("data-lineage-node"));
      });
    });
  }

  export function lineageSelectNode(nodeId) {
    if (!state.lineageNodesLive[nodeId]) return;
    state.selectedId = nodeId;
    lineageApplySelection();
    lineageRenderDetail(state.lineageNodesLive[nodeId].payload || {});
  }

  export function lineageSetDirection(direction) {
    var value = direction === "downstream" ? "downstream" : "upstream";
    if (value === state.direction) return;
    state.direction = value;
    $("#dirUpstream").setAttribute("aria-pressed", String(value === "upstream"));
    $("#dirDownstream").setAttribute("aria-pressed", String(value === "downstream"));
    if (state.rootId) lineageOpen(state.rootId);
  }

  export function lineageSetDepth(delta) {
    var value = Math.max(1, Math.min(15, state.depth + delta));
    if (value === state.depth) return;
    state.depth = value;
    $("#depthVal").textContent = state.depth + t(" levels");
    $("#depthMinus").disabled = state.depth <= 1;
    $("#depthPlus").disabled = state.depth >= 15;
    if (state.rootId) lineageOpen(state.rootId);
  }

  function lineageSvgPalette() {
    function css(name, fallback) {
      var value = getComputedStyle(document.documentElement)
        .getPropertyValue(name);
      return String(value || "").trim() || fallback;
    }
    return {
      background: css("--surface-2", "#1b212b"),
      card: css("--node-card", "#171d27"),
      border: css("--border-strong", "#3a4556"),
      text: css("--text", "#e9edf3"),
      text3: css("--text-3", "#7f8b9c"),
      arrow: css("--text-3", "#7f8b9c"),
      hues: {
        db: css("--node-db", "#f0b44c"),
        flow: css("--node-flow", "#b49bff"),
        model: css("--node-model", "#8fb3ff"),
        table: css("--node-table", "#79c9ec"),
        measure: css("--node-measure", "#6fd6c4"),
        report: css("--node-report", "#63ce9b"),
        neutral: css("--node-neutral", "#b6c1d1")
      },
      soft: {
        db: css("--node-db-soft", "rgba(240,180,76,.16)"),
        flow: css("--node-flow-soft", "rgba(180,155,255,.16)"),
        model: css("--node-model-soft", "rgba(143,179,255,.16)"),
        table: css("--node-table-soft", "rgba(121,201,236,.16)"),
        measure: css("--node-measure-soft", "rgba(111,214,196,.16)"),
        report: css("--node-report-soft", "rgba(99,206,155,.16)"),
        neutral: css("--node-neutral-soft", "rgba(182,193,209,.14)")
      }
    };
  }

  function lineageSvgDocument() {
    var graph = state.lineageGraph;
    var layout = state.lineageLayout;
    if (!graph || !layout) return "";
    var palette = lineageSvgPalette();
    var visible = {};
    lineageVisibleNodes(graph).forEach(function (node) {
      visible[node.id] = true;
    });
    var width = Math.max(1, Number(layout.width) || 1);
    var height = Math.max(1, Number(layout.height) || 1);
    var nodeW = layout.nodeW;
    var nodeH = layout.nodeH;
    var edges = (graph.edges || []).map(function (edge) {
      if (!visible[edge.source] || !visible[edge.target]) return "";
      var from = layout.positions[edge.source];
      var to = layout.positions[edge.target];
      if (!from || !to) return "";
      var forward = to.x > from.x;
      var x1 = from.x + (forward ? nodeW : 0);
      var x2 = to.x + (forward ? 0 : nodeW);
      var y1 = from.y + nodeH / 2;
      var y2 = to.y + nodeH / 2;
      var mid = (x1 + x2) / 2;
      return '<path d="M' + x1 + " " + y1 + " C" + mid + " " + y1 + ", " + mid +
        " " + y2 + ", " + x2 + " " + y2 + '" fill="none" stroke="' +
        palette.border + '" stroke-width="1.4" ' +
        'marker-end="url(#lineagePageArrow)"/>';
    }).join("");
    var nodes = (graph.nodes || []).filter(function (node) {
      return visible[node.id];
    }).map(function (node) {
      var pos = layout.positions[node.id];
      if (!pos) return "";
      var hue = nodeHue(String(node.type || ""));
      var color = palette.hues[hue] || palette.hues.neutral;
      var soft = palette.soft[hue] || palette.soft.neutral;
      var name = String(node.name || node.id);
      var workspace = String(node.workspace || "");
      return '<g transform="translate(' + pos.x + "," + pos.y + ')">' +
        '<rect width="' + nodeW + '" height="' + nodeH + '" rx="8" fill="' +
        palette.card + '" stroke="' + palette.border + '"/>' +
        '<path d="M0 18 V8 A8 8 0 0 1 8 0 H' + (nodeW - 8) +
        ' A8 8 0 0 1 ' + nodeW + ' 8 V18 Z" fill="' + soft + '"/>' +
        '<line x1="0" y1="18" x2="' + nodeW + '" y2="18" stroke="' + color +
        '" stroke-opacity="0.26"/>' +
        '<text x="10" y="12.6" font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="7.5" font-weight="600" letter-spacing="0.6" fill="' +
        color + '">' + escapeHtml(clipLabel(nodeTypeLabel(node.type), 32)) +
        "</text>" +
        '<text x="10" y="36" font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="11.5" font-weight="600" fill="' + palette.text + '">' +
        escapeHtml(clipLabel(name, 25)) + "</text>" +
        '<text x="10" y="51" font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="9" fill="' + palette.text3 + '">' +
        escapeHtml(clipLabel(workspace, 27)) + "</text>" +
        "</g>";
    }).join("");
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + width +
      '" height="' + height + '" viewBox="0 0 ' + width + " " + height + '">' +
      '<defs><marker id="lineagePageArrow" viewBox="0 0 8 8" refX="7" ' +
      'refY="4" markerWidth="6" markerHeight="6" orient="auto">' +
      '<path d="M0 0L8 4L0 8z" fill="' + palette.arrow + '"/>' +
      "</marker></defs>" +
      '<rect width="' + width + '" height="' + height + '" fill="' +
      palette.background + '"/>' +
      "<g>" + edges + "</g><g>" + nodes + "</g></svg>";
  }

  export function lineageExportImage(format) {
    if (!state.rootId) {
      app.toast(t("Choose a lineage node first"));
      return;
    }
    if (!lineageVisibleNodes(state.lineageGraph).length) {
      app.toast(t("No nodes match the current filter"));
      return;
    }
    var svg = lineageSvgDocument();
    if (!svg) {
      app.toast(t("No lineage data"));
      return;
    }
    var send = function (payload) {
      app.api().post("/api/lineage/image", {
        node_id: state.rootId,
        direction: state.direction,
        depth: state.depth,
        format: format,
        data: payload
      }).then(function (data) {
        app.toast(format.toUpperCase() + ": " + data.path);
        app.api().post("/api/files/open", { path: data.path, mode: "open" })
          .catch(function () {});
      }).catch(reportError);
    };
    if (format === "png") {
      analysisLineagePngData(svg).then(send).catch(reportError);
    } else {
      send(svg);
    }
  }

  export function lineageExport() {
    if (!state.rootId) {
      app.toast(t("Choose a lineage node first"));
      return;
    }
    app.api().post("/api/lineage/export", {
      node_id: state.rootId,
      direction: state.direction,
      depth: state.depth
    }).then(function (data) {
      app.toast("CSV: " + data.path);
      app.api().post("/api/files/open", { path: data.path, mode: "open" })
        .catch(function () {});
    }).catch(reportError);
  }

