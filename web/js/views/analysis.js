import { app } from "../core/app_api.js";
import { getSelectValue, setSelectOptions, setSelectValue } from "../core/combo.js";
import { $, $$, escapeHtml } from "../core/dom.js";
import { decimalText, fileMeta, fmtInt, sizeText } from "../core/format.js";
import { highlightCode } from "../core/highlight.js";
import { icon } from "../core/icons.js";
import { state } from "../core/state.js";

  var ANALYSIS_CHEVRON = icon("chevron-right", "od-icon", 2);
  var ANALYSIS_ICONS = {
    table: icon("table", "row-ico", 1.6),
    group: icon("rows-3", "row-ico", 1.6),
    column: icon("table-columns-split", "row-ico", 1.6),
    measure: icon("sigma", "row-ico", 1.7),
    link: icon("link-2", "row-ico", 1.6),
    code: icon("code-xml", "row-ico", 1.7),
    query: icon("database", "row-ico", 1.6),
    page: icon("file", "row-ico", 1.6),
    report: icon("file-chart-column", "row-ico is-accent", 1.6),
    visual: icon("chart-column", "row-ico", 1.6),
    filter: icon("filter", "row-ico", 1.6),
    hidden: icon("eye-off", "row-ico is-hidden", 1.6)
  };
  var MENU_ICONS = {
    more: icon("ellipsis-vertical", "", 2),
    expand: icon("chevron-down", "", 1.8),
    collapse: icon("chevron-up", "", 1.8),
    copy: icon("copy", "", 1.7),
    sigma: icon("square-function", "", 1.8),
    lineage: icon("git-branch", "", 1.6),
    graph: icon("network", "", 1.6),
    details: icon("table-properties", "", 1.6),
    raw: icon("braces", "", 1.7),
    dependencies: icon("git-fork", "", 1.6),
    table: icon("table", "", 1.6),
    model: icon("box", "", 1.6),
    export: icon("download", "", 1.7),
    refresh: icon("refresh-cw", "", 1.7),
    settings: icon("settings", "", 1.6),
    chevron: icon("chevron-right", "", 1.8)
  };
  var LINEAGE_KIND_LABELS = {
    column: "Column",
    measure: "Measure",
    table: "Table",
    report: "Report",
    page: "Page",
    visual: "Visual",
    filter: "Filter",
    sort: "Sort",
    relationship: "Relationship",
    hierarchy: "Hierarchy",
    security: "Security",
    "field-parameter": "Field parameter",
    calculation: "Calculation",
    kpi: "KPI",
    mquery: "M query",
    mstep: "M step",
    datasource: "Datasource",
    more: "More",
    usage: "Usage"
  };
  var LINEAGE_KIND_ICONS = {
    column: "column",
    measure: "measure",
    table: "table",
    report: "report",
    page: "page",
    visual: "visual",
    filter: "filter",
    sort: "group",
    relationship: "link",
    hierarchy: "group",
    security: "filter",
    "field-parameter": "group",
    calculation: "code",
    kpi: "measure",
    mquery: "query",
    mstep: "query",
    datasource: "query",
    more: "group",
    usage: "group"
  };
  var LINEAGE_CATEGORIES = [
    ["all", "All dependencies"],
    ["measures", "Measures"],
    ["columns", "Columns"],
    ["relationships", "Relationships"],
    ["sorting", "Sorting"],
    ["security", "Security"],
    ["field-parameters", "Field parameters"],
    ["reports", "Reports & visuals"],
    ["calculations", "Calculations"]
  ];
  var LINEAGE_ORIGIN_LABELS = {
    sql: "SQL Server",
    "analysis services": "Analysis Services",
    bigquery: "BigQuery",
    snowflake: "Snowflake",
    postgresql: "PostgreSQL",
    mysql: "MySQL",
    oracle: "Oracle",
    teradata: "Teradata",
    db2: "DB2",
    "sap hana": "SAP HANA",
    "sap bw": "SAP BW",
    sybase: "Sybase",
    informix: "Informix",
    odbc: "ODBC",
    dataverse: "Dataverse",
    dataflow: "Power BI Dataflow",
    dataset: "Dataset",
    "usage metrics": "Usage Metrics",
    file: "File",
    googlesheets: "Google Sheets",
    "azure storage": "Azure Storage",
    web: "Web",
    odata: "OData",
    sharepoint: "SharePoint",
    inline: "Inline table",
    table: "Table"
  };
  var DETAIL_GROUPS = [
    ["model_dependencies", "Model dependencies"],
    ["relationship_dependencies", "Relationships"],
    ["sorting_dependencies", "Sorting"],
    ["sort_dependencies", "Sort usage"],
    ["hierarchy_dependencies", "Hierarchy"],
    ["field_parameter_dependencies", "Field parameters"],
    ["calculation_item_dependencies", "Calculation items"],
    ["calc_table_dependencies", "Calculated tables"],
    ["calc_table_column_dependencies", "Calculated table columns"],
    ["row_level_security_dependencies", "Row level security"],
    ["key_column_dependencies", "Key columns"],
    ["kpi_dependencies", "KPIs"],
    ["power_query_dependencies", "Power Query"],
    ["visual_dependencies", "Visuals"],
    ["visual_level_filters_dependencies", "Visual level filters"],
    ["page_level_filters_dependencies", "Page level filters"],
    ["report_level_filters_dependencies", "Report level filters"]
  ];
  var USAGE_FLAG_LABELS = {
    is_used_model: "Model",
    is_used_relationships: "Relationships",
    is_used_sorting: "Sorting",
    is_used_calc_tables: "Calc tables",
    is_used_hierarchy: "Hierarchy",
    is_used_field_parameters: "Field parameters",
    is_used_calculation_items: "Calculation items",
    is_used_visuals: "Visuals",
    is_used_visual_level_filters: "Visual filters",
    is_used_page_level_filters: "Page filters",
    is_used_report_level_filters: "Report filters",
    is_used_row_level_security: "Row level security",
    is_used_kpis: "KPIs",
    is_used_power_query: "Power Query",
    is_used_key: "Key column"
  };
  var UNSUPPORTED_LABELS = {
    is_used_default_label: "Default label",
    is_used_visual_calculations: "Visual calculations",
    is_used_mobile: "Mobile layout",
    is_used_paginated: "Paginated reports",
    is_used_excel: "Excel",
    is_used_dynamic_param: "Dynamic parameters",
    is_used_change_detection: "Change detection",
    is_used_udf: "User-defined functions",
    is_used_calendars: "Calendars",
    is_used_group_by_columns: "Group-by columns",
    is_used_model_extension: "Model extension",
    ignored_in_build_dependencies: "Build dependency ignore",
    default_label_dependencies: "Default label",
    mobile_layout_dependencies: "Mobile layout",
    visual_calculations_dependencies: "Visual calculations",
    dynamic_param_dependencies: "Dynamic parameters",
    change_detection_dependencies: "Change detection",
    udf_dependencies: "User-defined functions",
    calendar_dependencies: "Calendars",
    group_by_columns_dependencies: "Group-by columns",
    model_extension_dependencies: "Model extension"
  };
  var ANALYSIS_TABS = {
    all: {
      placeholder: "Column, measure, or table name",
      filters: [["all", "All types"], ["columns", "Columns"], ["measures", "Measure"], ["hierarchies", "Hierarchies"], ["functions", "Functions"]],
      unused: true,
      expandable: true
    },
    tables: {
      placeholder: "Table, column, or measure name",
      filters: [["all", "All types"], ["columns", "Columns"], ["measures", "Measure"]],
      unused: true,
      expandable: true
    },
    relationships: {
      placeholder: "Relationship or column name",
      filters: [["all", "All statuses"], ["active", "Active"], ["inactive", "Inactive"]],
      unused: false,
      expandable: false
    },
    roles: {
      placeholder: "Role or member name",
      filters: [["all", "All types"], ["Role", "Role"], ["Member", "Member"]],
      unused: false,
      expandable: true
    },
    report: {
      placeholder: "Report, page, or workspace name",
      filters: [["all", "All statuses"], ["used", "Used"], ["unused", "Unused"]],
      unused: false,
      expandable: true
    },
    dax: {
      placeholder: "Measure, calculated column, or DAX expression",
      filters: [["all", "All types"], ["Measure", "Measure"], ["Calculated column", "Calculated column"]],
      unused: false,
      expandable: true
    },
    m: {
      placeholder: "Query, parameter, or M expression",
      filters: [["all", "All types"], ["Table", "Table"], ["M parameter", "M parameter"], ["Expression", "Expression"]],
      unused: false,
      expandable: true
    },
    health: {
      placeholder: "Rule, object, or report name",
      filters: [
        ["all", "All severities"],
        ["critical", "Critical"],
        ["warning", "Warning"],
        ["info", "Info"]
      ],
      unused: false,
      expandable: false
    },
    bestpractice: {
      placeholder: "Rule, object, or category",
      filters: [
        ["all", "All categories"],
        ["Performance", "Performance"],
        ["DAX Expressions", "DAX Expressions"],
        ["Error Prevention", "Error Prevention"],
        ["Maintenance", "Maintenance"],
        ["Formatting", "Formatting"],
        ["Naming Conventions", "Naming Conventions"]
      ],
      unused: false,
      expandable: true
    }
  };
  var ANALYSIS_STATUS_ORDER = {
    "Unused": 0,
    "Needs review": 1,
    "Used": 2,
    "Must keep": 3
  };

  function analysisPayload() {
    return {
      workspace_id: getSelectValue("wsSelect"),
      dataset_id: getSelectValue("modelSelect"),
      include_reports: $("#includeReports").checked,
      include_other_workspaces: $("#includeOther").checked,
      include_personal: $("#includePersonal").checked
    };
  }

  function analysisFmtBytes(bytes) {
    var value = Number(bytes || 0);
    if (!value) return "0 B";
    var mb = value / 1048576;
    if (mb >= 1024) return decimalText((mb / 1024).toFixed(2)) + " GB";
    if (mb >= 1) return decimalText(mb.toFixed(1)) + " MB";
    return (value / 1024).toFixed(0) + " KB";
  }

  var ANALYSIS_STATUS_LABELS = {
    "Unused": "Unused",
    "Needs review": "Needs review",
    "Used": "Used",
    "Must keep": "Must keep"
  };

  function tStatus(status) {
    var english = ANALYSIS_STATUS_LABELS[status];
    return english ? (english) : status;
  }

  function analysisStatusChip(status) {
    var map = {
      "Unused": "chip-danger",
      "Needs review": "chip-warn",
      "Used": "chip-ok",
      "Must keep": "chip-accent"
    };
    return '<span class="chip ' + (map[status] || "chip-idle") +
      '"><span class="dot"></span>' + escapeHtml(tStatus(status) || "-") + "</span>";
  }

  function analysisReportUrl(workspaceId, reportId) {
    if (!workspaceId || !reportId) return "";
    return "https://app.powerbi.com/groups/" + encodeURIComponent(workspaceId) +
      "/reports/" + encodeURIComponent(reportId);
  }

  function analysisCoverageSuffix(result) {
    if (!result) return "";
    if (result.coverage_complete) return " · full coverage";
    return result.coverage ? " · " + result.coverage : " · partial coverage";
  }

  function analysisTabConfig(name) {
    return ANALYSIS_TABS[name] || ANALYSIS_TABS.all;
  }

  function analysisApplyPrefs(settings) {
    state.analysisSettings = settings || {};
    state.analysisObjectFilter = settings.object_filter || "all";
    $("#unusedOnly").checked = Boolean(settings.unused_only);
    $("#includeReports").checked = settings.include_reports !== false;
    $("#includeOther").checked = settings.include_other_workspaces !== false;
    $("#includePersonal").checked = Boolean(settings.include_personal);
    analysisSyncReportOptions();
    state.analysisSort = settings.sort_column || "default";
    state.analysisSortDesc = Boolean(settings.sort_desc);
  }

  export function analysisSyncReportOptions() {
    // Opsi workspace tetap bisa diubah walau pemakaian report dimatikan; server
    // mengabaikannya saat include_reports=False. Hint menjelaskan hal itu.
    $("#includeOther").disabled = false;
    $("#includePersonal").disabled = false;
    var hint = $("#analysisReportHint");
    if (hint) hint.hidden = $("#includeReports").checked;
  }

  export function analysisSavePrefs() {
    if (!app.apiReady()) return Promise.resolve(null);
    return app.api().post("/api/analysis/preferences", {
      object_filter: ["all", "columns", "measures", "hierarchies", "functions"].includes(state.analysisObjectFilter)
        ? state.analysisObjectFilter : "all",
      unused_only: $("#unusedOnly").checked,
      include_reports: $("#includeReports").checked,
      include_other_workspaces: $("#includeOther").checked,
      include_personal: $("#includePersonal").checked,
      sort_column: state.analysisSort,
      sort_desc: state.analysisSortDesc
    }).then(function (data) {
      state.analysisSettings = data;
      return data;
    }).catch(function () {
      return null;
    });
  }

  export function analysisLoad() {
    if (!app.apiReady()) return Promise.resolve();
    return app.api().get("/api/analysis/state").then(function (data) {
      var options = (data.workspaces || []).map(function (item) {
        return { value: item.id, label: item.label, data: item };
      });
      setSelectOptions("wsSelect", options, "Choose a workspace…");
      analysisApplyPrefs(data.settings || {});
      var missing = data.credentials_missing || [];
      app.setChip(
        $("#spStatus"),
        missing.length ? "warn" : "ok",
        missing.length
          ? "Not signed in"
          : "Signed in"
      );
      $("#modelSelect") && setSelectOptions("modelSelect", [], "Choose a semantic model…");
      analysisApplyTabTools(state.analysisTab, false);
      analysisRender();
      return data;
    }).catch(function (error) {
      app.addLog("Analysis catalog could not be read: " + error.message, "warn");
    });
  }

  export function analysisLoadDatasets() {
    var workspaceId = getSelectValue("wsSelect");
    state.analysis = null;
    if (!workspaceId || !app.apiReady()) {
      setSelectOptions("modelSelect", [], "Choose a semantic model…");
      analysisRender();
      return Promise.resolve();
    }
    setSelectOptions("modelSelect", [], "Loading datasets…");
    $("#analyzeSummary").textContent = "Loading semantic models…";
    return app.api().get(
      "/api/analysis/workspaces/" + encodeURIComponent(workspaceId) + "/datasets"
    ).then(function (data) {
      setSelectOptions("modelSelect", (data.datasets || []).map(function (item) {
        return { value: item.id, label: item.name, data: item };
      }), "Choose a semantic model…");
      $("#analyzeSummary").textContent = "Choose a semantic model to analyze.";
      analysisRender();
      return data;
    }).catch(function (error) {
      setSelectOptions("modelSelect", [], "Choose a semantic model…");
      $("#analyzeSummary").textContent = (error.message);
      app.reportError(error);
    });
  }

  export function analysisNote(result) {
    var stamp = String(result.analyzed_at || "")
      .replace("T", " ").slice(0, 16);
    var text = "Updated " + (stamp || "-") + ".";
    if (result.reports_included === false) {
      text = "Model only — report usage not included." + " " + text;
    }
    return text;
  }

  function analysisApply(result, note) {
    state.analysis = result;
    state.analysisNote = note || "";
    state.analysisOpen = {};
    state.analysisQueries = {};
    state.relNodeOffset = {};
    state.relNodeDrag = null;
    state.reportDetail = {};
    state.reportLoading = {};
    (result.tables || []).forEach(function (table) {
      state.analysisOpen["tbl:" + table.name] = true;
      state.analysisOpen["tbl:" + table.name + ":m"] = true;
      state.analysisOpen["tbl:" + table.name + ":c"] = true;
    });
    state.analysisForceOpen = null;
    state.relSelected = null;
    var totals = result.totals || {};
    $("#metricSize").textContent = analysisFmtBytes(totals.model_bytes);
    var sizeNote = (totals.tables || 0) + " tables in the model";
    $("#metricSizeNote").textContent = sizeNote;
    $("#metricSizeNote").title =
      "data " + analysisFmtBytes(totals.data_bytes) +
      " · hierarchy " + analysisFmtBytes(totals.hierarchy_bytes) +
      " · dictionary " + analysisFmtBytes(totals.dictionary_bytes);
    $("#metricColumns").textContent = (totals.columns || 0);
    $("#metricColumnsNote").textContent = (totals.hidden_columns || 0) + " hidden columns";
    $("#metricMeasures").textContent = (totals.measures || 0);
    $("#metricMeasuresNote").textContent = totals.helper_measures
      ? totals.helper_measures + " stored in _Measures"
      : "measures in the model";
    $("#metricUnusedColumns").textContent = (totals.unused_columns || 0);
    var pct = totals.model_bytes
      ? Math.round((totals.unused_bytes || 0) / totals.model_bytes * 100)
      : 0;
    var unusedNote = analysisFmtBytes(totals.unused_bytes) + " · " + pct + "% dataset";
    $("#metricUnusedColumnsNote").textContent = unusedNote;
    $("#metricUnusedColumnsNote").title = unusedNote;
    $("#metricUnusedMeasures").textContent = (totals.unused_measures || 0);
    $("#metricUnusedMeasuresNote").textContent = totals.measures
      ? Math.round((totals.unused_measures || 0) / totals.measures * 100) + "% of total measures"
      : "not referenced";
    if (result.reports_included === false) {
      $("#metricReport").textContent = "—";
      $("#metricReportNote").textContent = "Report usage not included";
    } else {
      $("#metricReport").textContent = (totals.reports || 0) + " reports";
      var reportNote = (totals.pages || 0) + " pages · " +
        (totals.visuals || 0) + " visuals";
      $("#metricReportNote").textContent = reportNote;
      $("#metricReportNote").title = result.coverage || "";
    }
    app.setChip(
      $("#spStatus"),
      result.coverage_complete ? "ok" : "warn",
      result.coverage_complete
        ? "Full coverage"
        : (result.reports_included === false
          ? "Model only — report usage not included"
          : "Partial coverage")
    );
    analysisApplyTabTools(state.analysisTab, false);
    analysisRender();
  }

  function analysisExportState() {
    var button = $("#exportXlsx");
    if (!button) return;
    var canExport = state.analysisTab === "all";
    button.disabled = !state.analysis || !canExport;
    button.textContent = (canExport ? "Export Result" : "Export (coming soon)");
    button.title = canExport ? "Export Result" : "Coming soon";
    button.setAttribute(
      "aria-disabled",
      state.analysis && canExport ? "false" : "true"
    );
  }

  function analysisApplyTabTools(name, reset) {
    var config = analysisTabConfig(name);
    $("#searchAnalyze").placeholder = config.placeholder;
    $("#toolTypeWrap").hidden = config.filters.length < 2;
    $("#toolUnusedWrap").hidden = !config.unused;
    $("#expandRows").hidden = !config.expandable;
    $("#collapseRows").hidden = !config.expandable;
    $("#relViewSwitch").hidden = name !== "relationships";
    $("#healthRulesInfo").hidden = name !== "health";
    $("#bpRulesInfo").hidden = name !== "bestpractice";
    analysisExportState();
    if (name === "relationships") analysisSyncRelView();
    var options = config.filters.map(function (pair) {
      return { value: pair[0], label: pair[1] };
    });
    setSelectOptions("typeAnalyze", options, null);
    var desired = reset ? "all" : (state.analysisObjectFilter || "all");
    var valid = options.some(function (item) { return item.value === desired; });
    setSelectValue("typeAnalyze", valid ? desired : "all");
  }

  export function analysisSyncRelView() {
    $$("#relViewSwitch [data-rel-view]").forEach(function (button) {
      button.setAttribute(
        "aria-pressed",
        button.getAttribute("data-rel-view") === state.relView ? "true" : "false"
      );
    });
  }

  function analysisCounts() {
    var result = state.analysis;
    var counts = {
      all: 0, tables: 0, relationships: 0, roles: 0, report: 0, dax: 0, m: 0, health: 0,
      bestpractice: 0
    };
    if (!result) return counts;
    var totals = result.totals || {};
    counts.all = (totals.columns || 0) + (totals.measures || 0) + (totals.hierarchies || 0) + (totals.functions || 0);
    counts.tables = (result.tables || []).length;
    counts.relationships = (result.relationships || []).length;
    counts.roles = (result.roles || []).length;
    counts.report = (result.reports || []).length;
    counts.dax = (result.measures || []).length + analysisCalculatedColumns().length;
    counts.m = (result.m_queries || []).length;
    counts.health = ((result.health && result.health.items) || []).length;
    counts.bestpractice = ((result.best_practice && result.best_practice.items) || []).length;
    return counts;
  }

  function analysisCalculatedColumns() {
    return ((state.analysis && state.analysis.columns) || []).filter(function (column) {
      return Boolean(column.expression) && Boolean(column.is_calculated);
    });
  }

  function analysisTabCounts() {
    var counts = analysisCounts();
    $("#tabCountAll").textContent = state.analysis ? fmtInt(counts.all) : "";
    $("#tabCountTables").textContent = state.analysis ? fmtInt(counts.tables) : "";
    $("#tabCountRelationships").textContent = state.analysis ? fmtInt(counts.relationships) : "";
    $("#tabCountRoles").textContent = state.analysis ? fmtInt(counts.roles) : "";
    $("#tabCountReport").textContent = state.analysis ? fmtInt(counts.report) : "";
    $("#tabCountDax").textContent = state.analysis ? fmtInt(counts.dax) : "";
    $("#tabCountM").textContent = state.analysis ? fmtInt(counts.m) : "";
    $("#tabCountHealth").textContent = state.analysis ? fmtInt(counts.health) : "";
    $("#tabCountBestPractice").textContent = state.analysis
      ? fmtInt(counts.bestpractice) : "";
  }

  function analysisNameCell(name, icon, options) {
    options = options || {};
    var html = '<div class="name-cell">';
    if (options.toggleId) {
      html += '<button type="button" class="row-toggle" data-analysis-toggle="' +
        escapeHtml(options.toggleId) + '" aria-expanded="' +
        (options.open ? "true" : "false") + '" aria-label="' +
        (options.open ? "Collapse " : "Expand ") + escapeHtml(name) + '">' +
        ANALYSIS_CHEVRON + "</button>";
    } else if (options.level) {
      html += '<span class="row-toggle" aria-hidden="true"></span>';
    }
    if (icon && ANALYSIS_ICONS[icon]) html += ANALYSIS_ICONS[icon];
    if (options.hidden && ANALYSIS_ICONS.hidden) html += ANALYSIS_ICONS.hidden;
    var label = options.href
      ? '<a class="analysis-link" href="' + escapeHtml(options.href) +
        '" target="_blank" rel="noopener">' + escapeHtml(name) + "</a>"
      : escapeHtml(name);
    html += '<span class="name-text" title="' + escapeHtml(name) + '">' +
      label + "</span>";
    if (options.menu) {
      html += '<button type="button" class="row-menu-btn" data-analysis-menu ' +
        'aria-haspopup="menu" aria-expanded="false" aria-label="' +
        escapeHtml("Item actions") + '" title="' +
        escapeHtml("Item actions") + '">' + MENU_ICONS.more + "</button>";
    }
    html += "</div>";
    return html;
  }

  export function analysisIsOpen(id, defaultOpen, ignoreQuery) {
    // Tombol Expand/Collapse all menang, lalu pilihan eksplisit pengguna pada
    // baris itu. Dengan begitu baris tetap bisa ditutup saat ada kata kunci.
    if (state.analysisForceOpen === true || state.analysisForceOpen === false) {
      return state.analysisForceOpen;
    }
    if (Object.prototype.hasOwnProperty.call(state.analysisOpen, id)) {
      return Boolean(state.analysisOpen[id]);
    }
    var query = ($("#searchAnalyze").value || "").trim();
    if (query && !ignoreQuery) return true;
    return Boolean(defaultOpen);
  }

  // -- Menu konteks baris analisa -----------------------------------------
  function analysisFindItem(kind, table, name) {
    var result = state.analysis;
    if (!result) return null;
    var list = kind === "measure" ? (result.measures || []) : (result.columns || []);
    var wantTable = String(table || "").toLowerCase();
    var wantName = String(name || "").toLowerCase();
    for (var index = 0; index < list.length; index += 1) {
      var item = list[index];
      if (String(item.table || "").toLowerCase() === wantTable &&
          String(item.name || "").toLowerCase() === wantName) {
        return item;
      }
    }
    return null;
  }

  function analysisItemLabel(item) {
    return "'" + item.table + "'[" + item.name + "]";
  }

  export function analysisRowTarget(node) {
    return {
      kind: node.getAttribute("data-item-kind") || "column",
      table: node.getAttribute("data-item-table") || "",
      name: node.getAttribute("data-item-name") || ""
    };
  }

  function analysisMenuEntries(target) {
    if (target.kind === "table") {
      return [
        { id: "table-lineage", label: "Table lineage", icon: "graph", primary: true },
        { id: "table-details", label: "Table details", icon: "details" },
        { id: "table-show", label: "Show in analysis", icon: "table" },
        { id: "table-copy", label: "Copy table name", icon: "copy" },
        { divider: true },
        { id: "exports", label: "Exports", icon: "export", submenu: "exports" }
      ];
    }
    var item = analysisFindItem(target.kind, target.table, target.name);
    var isMeasure = target.kind === "measure";
    var hasChildren = Boolean(item && (item.children || []).length);
    var canToggle = hasChildren && state.analysisTab === "all";
    var entries = [
      {
        id: "expand",
        label: "Expand items below",
        icon: "expand",
        disabled: !canToggle
      },
      {
        id: "collapse",
        label: "Collapse items below",
        icon: "collapse",
        disabled: !canToggle
      },
      { id: "copy", label: "Copy text", icon: "copy" },
      { divider: true }
    ];
    if (isMeasure) {
      entries.push({ id: "dax", label: "View DAX expression", icon: "sigma" });
    }
    entries.push(
      { id: "lineage", label: "View column lineage", icon: "lineage" },
      {
        id: "lineage-graph",
        label: "View column lineage graph",
        icon: "graph",
        primary: true
      },
      {
        id: "details",
        label: isMeasure ? "Measure details" : "Column details",
        icon: "details"
      },
      {
        id: "raw-metadata",
        label: isMeasure ? "Measure raw data" : "Column raw data",
        icon: "raw"
      },
      {
        id: "preview",
        label: "Preview values",
        icon: "query"
      },
      {
        id: "dependencies",
        label: "View dependencies",
        icon: "dependencies",
        submenu: "dependencies"
      },
      {
        id: "table-options",
        label: "Table options",
        icon: "table",
        submenu: "table"
      },
      {
        id: "model-options",
        label: "Model options",
        icon: "model",
        submenu: "model"
      },
      {
        id: "exports",
        label: "Exports",
        icon: "export",
        submenu: "exports"
      }
    );
    return entries;
  }

  function analysisMenuMarkup(entries) {
    return entries.map(function (entry) {
      if (entry.divider) {
        return '<div class="menu-divider" role="separator"></div>';
      }
      var classes = ["menu-item"];
      var disabled = Boolean(entry.soon || entry.disabled);
      if (entry.primary) classes.push("is-primary");
      if (disabled) classes.push("is-disabled");
      var attrs = ' role="menuitem" tabindex="-1" data-menu-action="' +
        escapeHtml(entry.id) + '"';
      if (entry.submenu) {
        attrs += ' data-menu-submenu="' + escapeHtml(entry.submenu) + '"';
      }
      if (disabled) attrs += ' aria-disabled="true"';
      var icon = MENU_ICONS[entry.icon] || "";
      var badge = entry.soon
        ? '<span class="menu-badge">' + escapeHtml("Soon") + "</span>"
        : "";
      var arrow = entry.submenu
        ? '<span class="menu-arrow">' + MENU_ICONS.chevron + "</span>"
        : "";
      return '<div class="' + classes.join(" ") + '"' + attrs + ">" +
        '<span class="menu-icon">' + icon + "</span>" +
        '<span class="menu-label">' + escapeHtml(entry.label) + "</span>" +
        badge + arrow + "</div>";
    }).join("");
  }

  function analysisSubmenuEntries(action) {
    if (action === "dependencies") {
      return LINEAGE_CATEGORIES.map(function (item) {
        return {
          action: "lineage-graph:" + item[0],
          label: item[1],
          icon: "graph"
        };
      });
    }
    if (action === "table") {
      return [
        { action: "table-details", label: "Table details", icon: "details" },
        { action: "table-lineage", label: "Table lineage", icon: "graph" },
        { action: "table-show", label: "Show in analysis", icon: "table" },
        { action: "table-copy", label: "Copy table name", icon: "copy" }
      ];
    }
    if (action === "model") {
      return [
        { action: "model-details", label: "Model details", icon: "details" },
        { action: "model-copy", label: "Copy model name", icon: "copy" },
        { action: "model-rerun", label: "Run analysis again", icon: "refresh" },
        { action: "model-settings", label: "Open settings", icon: "settings" }
      ];
    }
    if (action === "exports") {
      return [
        {
          action: "export-lineage-svg",
          label: "Lineage graph (SVG)",
          icon: "export"
        },
        {
          action: "export-lineage-png",
          label: "Lineage graph (PNG)",
          icon: "export"
        },
        {
          action: "export-lineage-csv",
          label: "Lineage nodes & edges (CSV)",
          icon: "export"
        },
        {
          action: "export-lineage-json",
          label: "Lineage JSON",
          icon: "code"
        },
        {
          action: "copy-lineage-mermaid",
          label: "Copy as Mermaid",
          icon: "copy"
        },
        {
          action: "export-dependencies-csv",
          label: "Dependencies (CSV)",
          icon: "table"
        }
      ];
    }
    return [];
  }

  function analysisSubmenuMarkup(action) {
    return analysisSubmenuEntries(action).map(function (entry) {
      return '<div class="menu-item" role="menuitem" tabindex="-1" data-menu-action="' +
        escapeHtml(entry.action) + '">' +
        '<span class="menu-icon">' + (MENU_ICONS[entry.icon] || "") + "</span>" +
        '<span class="menu-label">' + escapeHtml((entry.label)) + "</span></div>";
    }).join("");
  }

  function analysisSubmenuPlace(anchorEl) {
    var submenu = $("#analysisSubmenu");
    if (!submenu) return;
    var anchor = anchorEl.getBoundingClientRect();
    submenu.hidden = false;
    submenu.style.visibility = "hidden";
    submenu.style.left = "0px";
    submenu.style.top = "0px";
    var rect = submenu.getBoundingClientRect();
    var left = anchor.right - 4;
    if (left + rect.width > window.innerWidth - 8) {
      left = anchor.left - rect.width + 4;
    }
    var top = anchor.top - 6;
    left = Math.max(8, left);
    top = Math.min(Math.max(8, top), window.innerHeight - rect.height - 8);
    submenu.style.left = left + "px";
    submenu.style.top = top + "px";
    submenu.style.visibility = "";
  }

  export function analysisOpenSubmenu(action, anchorEl) {
    var submenu = $("#analysisSubmenu");
    if (!submenu || !analysisSubmenuEntries(action).length || !anchorEl) {
      return;
    }
    state.analysisSubmenuTarget = action;
    state.analysisSubmenuAnchor = anchorEl;
    submenu.innerHTML = analysisSubmenuMarkup(action);
    analysisSubmenuPlace(anchorEl);
    var first = submenu.querySelector("[role='menuitem']");
    if (first) first.focus({ preventScroll: true });
  }

  export function analysisCloseSubmenu(restoreFocus) {
    var submenu = $("#analysisSubmenu");
    var anchor = state.analysisSubmenuAnchor;
    state.analysisSubmenuAnchor = null;
    if (!submenu || submenu.hidden) return;
    submenu.hidden = true;
    submenu.innerHTML = "";
    state.analysisSubmenuTarget = null;
    if (restoreFocus && anchor && document.contains(anchor)) {
      anchor.focus({ preventScroll: true });
    }
  }

  function analysisMenuPlace(anchor) {
    var menu = $("#analysisMenu");
    if (!menu) return;
    menu.hidden = false;
    menu.style.visibility = "hidden";
    menu.style.left = "0px";
    menu.style.top = "0px";
    var rect = menu.getBoundingClientRect();
    var left = anchor.x;
    var top = anchor.y;
    if (anchor.above != null && top + rect.height > window.innerHeight - 8) {
      top = anchor.above - rect.height;
    }
    left = Math.min(Math.max(8, left), window.innerWidth - rect.width - 8);
    top = Math.min(Math.max(8, top), window.innerHeight - rect.height - 8);
    menu.style.left = left + "px";
    menu.style.top = top + "px";
    menu.style.visibility = "";
  }

  export function analysisOpenMenu(target, anchor) {
    var menu = $("#analysisMenu");
    if (!menu) return;
    var item = analysisFindItem(target.kind, target.table, target.name);
    if (target.kind !== "table" && !item) return;
    state.analysisMenuTarget = {
      kind: target.kind,
      table: target.kind === "table" ? target.table : item.table,
      name: target.kind === "table" ? target.name : item.name
    };
    if (!state.analysisMenuFocus || !document.contains(state.analysisMenuFocus)) {
      state.analysisMenuFocus = document.activeElement;
    }
    menu.innerHTML = analysisMenuMarkup(analysisMenuEntries(target));
    analysisMenuPlace(anchor || { x: 24, y: 24 });
    if (anchor && anchor.row) {
      anchor.row.classList.add("is-menu-open");
      var button = anchor.row.querySelector("[data-analysis-menu]");
      if (button) button.setAttribute("aria-expanded", "true");
    }
    var first = menu.querySelector("[role='menuitem']:not([aria-disabled='true'])");
    if (first) first.focus({ preventScroll: true });
  }

  export function analysisCloseMenu(restoreFocus) {
    analysisCloseSubmenu(false);
    var menu = $("#analysisMenu");
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    menu.innerHTML = "";
    $$("tr.is-menu-open").forEach(function (row) {
      row.classList.remove("is-menu-open");
      var button = row.querySelector("[data-analysis-menu]");
      if (button) button.setAttribute("aria-expanded", "false");
    });
    state.analysisMenuTarget = null;
    var focus = state.analysisMenuFocus;
    state.analysisMenuFocus = null;
    if (restoreFocus && focus && document.contains(focus)) {
      var target = focus.tagName === "TR" ?
        focus.querySelector("[data-analysis-menu]") : focus;
      if (target) target.focus({ preventScroll: true });
    }
  }

  function analysisSetSubtree(target, open) {
    var item = analysisFindItem(target.kind, target.table, target.name);
    if (!item) return;
    var id = "item:" + target.kind + ":" + item.table + ":" + item.name;
    state.analysisForceOpen = null;
    state.analysisOpen[id] = open;
    (item.children || []).forEach(function (_group, index) {
      state.analysisOpen[id + ":g" + index] = open;
    });
    analysisRender();
  }

  export function analysisRunMenuAction(action) {
    var target = state.analysisMenuTarget;
    if (!target) return;
    var item = analysisFindItem(target.kind, target.table, target.name);
    if (!item && target.kind !== "table") {
      analysisCloseMenu(false);
      return;
    }
    if (action === "expand" || action === "collapse") {
      analysisSetSubtree(target, action === "expand");
      return;
    }
    if (action === "copy") {
      copyTextValue(analysisItemLabel(item));
      analysisCloseMenu(true);
      return;
    }
    if (action === "details") {
      analysisCloseMenu(false);
      analysisOpenItemDetails(target);
      return;
    }
    if (action === "dax") {
      analysisCloseMenu(false);
      analysisOpenDetails(target, "dax");
      return;
    }
    if (action === "lineage" || action === "lineage-graph" ||
        action.indexOf("lineage-graph:") === 0) {
      var category = "all";
      var view = action === "lineage" ? "outline" : "graph";
      if (action.indexOf("lineage-graph:") === 0) {
        category = action.slice("lineage-graph:".length);
      }
      analysisCloseMenu(false);
      analysisLineageOpen(target, view, category);
      return;
    }
    if (action === "raw-metadata") {
      analysisCloseMenu(false);
      analysisOpenRawMetadata(target);
      return;
    }
    if (action === "preview") {
      analysisCloseMenu(false);
      analysisOpenPreview(target);
      return;
    }
    if (action === "table-details" || action === "table-show" ||
        action === "table-copy" || action === "table-lineage") {
      analysisCloseMenu(action === "table-copy");
      if (action === "table-details") analysisOpenTableDetails(target);
      else if (action === "table-show") analysisShowTable(target);
      else if (action === "table-copy") copyTextValue(target.table);
      else {
        analysisLineageOpen(
          { kind: "table", table: target.table, name: target.table },
          "graph",
          "all"
        );
      }
      return;
    }
    if (action === "model-details" || action === "model-copy" ||
        action === "model-rerun" || action === "model-settings") {
      analysisCloseMenu(false);
      if (action === "model-details") analysisOpenModelDetails();
      else if (action === "model-copy") analysisCopyModelName();
      else if (action === "model-rerun") analysisRun();
      else app.showView("pengaturan");
      return;
    }
    if (action === "export-lineage-svg" || action === "export-lineage-png") {
      analysisCloseMenu(false);
      analysisExportLineageImage(
        target,
        action === "export-lineage-png" ? "png" : "svg"
      );
      return;
    }
    if (action === "export-lineage-csv" || action === "export-lineage-json") {
      analysisCloseMenu(false);
      analysisExportLineage(target, action === "export-lineage-json" ? "json" : "csv");
      return;
    }
    if (action === "copy-lineage-mermaid") {
      analysisCloseMenu(false);
      analysisCopyMermaid(target);
      return;
    }
    if (action === "export-dependencies-csv") {
      analysisCloseMenu(false);
      analysisExportDependencies(target);
      return;
    }
    analysisCloseMenu(true);
  }

  export function copyTextValue(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        app.toast("Copied to clipboard");
      }).catch(function () {
        app.toast("Copy failed");
      });
      return;
    }
    try {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      var copied = document.execCommand("copy");
      document.body.removeChild(area);
      app.toast(copied ? "Copied to clipboard" : "Copy failed");
    } catch (error) {
      app.toast("Copy failed");
    }
  }

  function analysisOpenInfoDialog(title, sub, html, options) {
    var dialog = $("#analysisDetailsDialog");
    if (!dialog) return;
    $("#analysisDetailsTitle").textContent = title;
    $("#analysisDetailsSub").textContent = sub || "";
    $("#analysisDetailsBody").innerHTML = html;
    var copyText = options && options.copyText ? String(options.copyText) : "";
    state.analysisDetailsExpression = copyText;
    $("#copyAnalysisExpression").hidden = !copyText;
    if (dialog.open) dialog.close();
    dialog.showModal();
  }

  function analysisOpenTableDetails(target) {
    var info = (state.analysis.tables || []).filter(function (table) {
      return table.name === target.table;
    })[0] || {};
    var query = (state.analysis.m_queries || []).filter(function (item) {
      return item.kind === "Table" && item.name === target.table;
    })[0] || {};
    var rows = [
      ["Table", target.table],
      ["Mode", info.storage_mode || "\u2014"],
      ["Partitions", info.partition_count || 0],
      ["Rows", info.rows || 0],
      ["Size", info.size || analysisFmtBytes(info.size_bytes || 0)],
      ["Columns", info.column_count || 0],
      ["Measures", info.measure_count || 0],
      ["Source", query.source || "\u2014"],
      ["Query", query.detail || "\u2014"]
    ];
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    if (query.expression) {
      html += '<h3 class="detail-heading">' + escapeHtml("Expression") +
        "</h3>" + analysisExpressionMarkup(query.expression, "m");
    }
    analysisOpenInfoDialog("Table details", "'" + target.table + "'", html, {
      copyText: query.expression || ""
    });
  }

  function analysisOpenModelDetails() {
    var result = state.analysis;
    if (!result) {
      app.toast("Run the analysis first");
      return;
    }
    var dataset = result.dataset || {};
    var totals = result.totals || {};
    var rows = [
      ["Model", dataset.name || ""],
      ["Workspace", dataset.workspace_name || ""],
      ["Dataset ID", dataset.id || ""],
      ["Analyzed at", String(result.analyzed_at || "").replace("T", " ").slice(0, 19)],
      ["Method", result.method || ""],
      ["Coverage", result.coverage || ""],
      ["Model size", analysisFmtBytes(totals.model_bytes || 0)],
      ["Tables", totals.tables || 0],
      ["Columns", totals.columns || 0],
      ["Measures", totals.measures || 0],
      ["Reports", totals.reports || 0],
      ["Pages", totals.pages || 0],
      ["Visuals", totals.visuals || 0],
      ["Report usage", result.reports_included === false
        ? "Not included" : "Included"]
    ];
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    analysisOpenInfoDialog("Model details", dataset.name || "", html);
  }

  function analysisCopyModelName() {
    var result = state.analysis;
    if (!result) {
      app.toast("Run the analysis first");
      return;
    }
    var dataset = result.dataset || {};
    copyTextValue(
      "'" + (dataset.workspace_name || "") + "' / '" + (dataset.name || "") + "'"
    );
  }

  function analysisShowTable(target) {
    if (!state.analysis) return;
    state.analysisObjectFilter = "all";
    var type = $("#typeAnalyze");
    if (type) type.value = "all";
    $("#unusedOnly").checked = false;
    state.analysisQueries["all"] = target.table;
    analysisSetTab("all");
    var wrap = $("#analyzeTableWrap");
    if (wrap) wrap.scrollIntoView({ block: "nearest" });
  }

  function analysisExportLineage(target, format) {
    if (!app.apiReady()) return;
    app.api().post("/api/analysis/lineage/export", {
      dataset_id: getSelectValue("modelSelect"),
      kind: target.kind,
      table: target.table,
      name: target.name,
      direction: "both",
      category: "all",
      format: format === "json" ? "json" : "csv"
    }).then(function (data) {
      var paths = data.paths || [];
      var path = paths.filter(function (item) {
        return format === "json"
          ? /\.json$/i.test(item) : /_nodes\.csv$/i.test(item);
      })[0] || paths[0];
      if (!path) return;
      app.toast("Export: " + path);
      app.api().post("/api/files/open", { path: path, mode: "open" }).catch(function () {});
    }).catch(app.reportError);
  }

  function analysisExportDependencies(target) {
    if (!app.apiReady()) return;
    app.api().post("/api/analysis/dependencies/export", {
      dataset_id: getSelectValue("modelSelect"),
      kind: target.kind,
      table: target.table,
      name: target.name
    }).then(function (data) {
      if (!data.path) return;
      if (!data.rows) {
        app.toast("No dependencies");
        return;
      }
      app.toast("Export: " + data.path);
      app.api().post("/api/files/open", { path: data.path, mode: "open" }).catch(function () {});
    }).catch(app.reportError);
  }

  function analysisLineageSvgPalette() {
    function css(name, fallback) {
      var value = getComputedStyle(document.documentElement)
        .getPropertyValue(name);
      return String(value || "").trim() || fallback;
    }
    return {
      background: css("--surface-2", "#1b212b"),
      surface: css("--surface", "#151a22"),
      surface3: css("--surface-3", "#222a36"),
      border: css("--border", "#28303d"),
      borderStrong: css("--border-strong", "#3a4556"),
      text: css("--text", "#e9edf3"),
      text3: css("--text-3", "#7f8b9c"),
      accent: css("--accent", "#f2c811"),
      warn: css("--warn", "#f0b44c"),
      groups: {
        mquery: css("--node-flow", "#b49bff"),
        model: css("--node-model", "#8fb3ff"),
        report: css("--node-report", "#63ce9b"),
        page: css("--node-table", "#79c9ec"),
        usage: css("--node-neutral", "#b6c1d1"),
        more: css("--text-3", "#7f8b9c"),
        datasource: css("--node-flow", "#b49bff"),
        selected: css("--accent", "#f2c811")
      },
      edges: {
        usage: css("--node-report", "#63ce9b"),
        page: css("--node-report", "#63ce9b"),
        visual: css("--node-report", "#63ce9b"),
        filter: css("--warn", "#f0b44c"),
        sort: css("--node-table", "#79c9ec")
      }
    };
  }

  function analysisLineageSvgClip(value, maxChars) {
    var text = String(value == null ? "" : value);
    if (text.length <= maxChars) return text;
    return text.slice(0, Math.max(1, maxChars - 1)) + "\u2026";
  }

  function analysisLineageSvgDocument(graph) {
    var palette = analysisLineageSvgPalette();
    var width = Math.max(1, Number(graph.width) || 1);
    var height = Math.max(1, Number(graph.height) || 1);
    var routes = analysisLineageEdgeRoutes(graph);
    var edges = analysisLineageEdges(graph).map(function (edge, index) {
      var path = routes[index];
      if (!path) return "";
      var stroke = palette.edges[edge.kind] || palette.borderStrong;
      var dash = edge.kind === "filter"
        ? ' stroke-dasharray="5 4"'
        : (edge.kind === "sort" ? ' stroke-dasharray="3 3"' : "");
      return '<path d="' + path + '" fill="none" stroke="' + stroke +
        '" stroke-width="1.4"' + dash +
        ' marker-end="url(#lineageExportArrow)"/>';
    }).join("");
    var exportById = {};
    (graph.nodes || []).forEach(function (node) { exportById[node.id] = node; });
    var treeEdges = analysisLineageTreeEdges(graph).map(function (edge) {
      var source = exportById[edge.from];
      var target = exportById[edge.to];
      if (!source || !target) return "";
      return '<path d="' + analysisLineageTreePath(source, target) +
        '" fill="none" stroke="' + palette.borderStrong +
        '" stroke-width="1.1" stroke-opacity="0.7"/>';
    }).join("");
    function header(x, y, meta, color) {
      var title = analysisLineageTitle(meta);
      return '<g transform="translate(' + x + ',' + y + ')">' +
        '<rect width="4" height="18" rx="2" fill="' + color + '"/>' +
        '<text x="12" y="13" font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="12" font-weight="600" fill="' + palette.text + '">' +
        escapeHtml(analysisLineageSvgClip(title.label, 46)) + '</text>' +
        '<text x="12" y="27" font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="10" fill="' + palette.text3 + '">' +
        escapeHtml(analysisLineageSvgClip(title.sub, 52)) + '</text></g>';
    }
    var artifacts = (graph.artifacts || []).map(function (artifact) {
      var color = palette.groups[artifact.kind] || palette.borderStrong;
      return '<g><rect x="' + artifact.x + '" y="' + artifact.y +
        '" width="' + artifact.w + '" height="' + artifact.h +
        '" rx="12" fill="' + color + '" fill-opacity="0.06" stroke="' +
        color + '" stroke-opacity="0.45"/>' +
        header(
          artifact.x + 18, artifact.y + 12, artifact,
          color
        ) + "</g>";
    }).join("");
    var groups = (graph.groups || []).map(function (group) {
      var color = palette.groups[group.kind] || palette.borderStrong;
      return '<g><rect x="' + group.x + '" y="' + group.y +
        '" width="' + group.w + '" height="' + group.h +
        '" rx="10" fill="' + color + '" fill-opacity="0.04" stroke="' +
        color + '" stroke-opacity="0.55" stroke-dasharray="5 4"/>' +
        header(
          group.x + 16, group.y + 8, group,
          color
        ) + "</g>";
    }).join("");
    var cards = (graph.nodes || []).filter(function (node) {
      return !node.role || node.role === "card";
    }).map(function (node) {
      var group = node.group || "model";
      var color = palette.groups[group] || palette.borderStrong;
      var seed = node.side === "root";
      var stroke = seed ? palette.accent : palette.border;
      var strokeWidth = seed ? 2 : 1;
      var text = analysisLineageCardText(node);
      var statusColor = text.status === "Unused"
        ? "#c42b1c"
        : text.status === "Must keep"
          ? "#d4a017"
          : text.status === "Needs review"
            ? "#d67500"
            : text.status
              ? "#107c10"
              : "";
      var count = Number(node.count) > 1 ? String(Number(node.count)) : "";
      var step = Number(node.step) > 0
        ? String(Number(node.step)).padStart(2, "0")
        : "";
      var titleChars = Math.max(18, Math.floor((Number(node.w) || 230) / 7.6));
      var title = analysisLineageSvgClip(text.title, titleChars);
      var detail = analysisLineageSvgClip(text.sub, titleChars + 10);
      var note = analysisLineageSvgClip(text.note, titleChars + 10);
      return '<g transform="translate(' + node.x + ',' + node.y + ')">' +
        '<rect width="' + node.w + '" height="' + node.h +
        '" rx="8" fill="' + palette.surface + '" stroke="' + stroke +
        '" stroke-width="' + strokeWidth + '"/>' +
        '<rect width="4" height="' + node.h + '" rx="2" fill="' + color + '"/>' +
        (step
          ? '<rect x="12" y="10" width="24" height="15" rx="7" fill="' +
            palette.surface3 + '"/>' +
            '<text x="24" y="21" text-anchor="middle" ' +
            'font-family="Segoe UI, Arial, sans-serif" font-size="9" ' +
            'font-weight="600" fill="' + palette.text3 + '">' +
            escapeHtml(step) + "</text>"
          : "") +
        '<text x="' + (step ? 44 : 14) + '" y="22" ' +
        'font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="12.5" font-weight="600" fill="' + palette.text + '">' +
        escapeHtml(title) + '</text>' +
        '<text x="14" y="39" font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="10.5" fill="' + palette.text3 + '">' +
        escapeHtml(detail) + '</text>' +
        (note
          ? '<text x="14" y="53" font-family="Segoe UI, Arial, sans-serif" ' +
            'font-size="10" fill="' + palette.text3 + '">' +
            escapeHtml(note) + '</text>'
          : "") +
        (statusColor
          ? '<circle cx="' + (node.w - 12) + '" cy="14" r="4" fill="' +
            statusColor + '"/>'
          : "") +
        (count
          ? '<rect x="' + (node.w - 36) + '" y="10" width="20" height="15" ' +
            'rx="7" fill="' + palette.surface3 + '"/>' +
            '<text x="' + (node.w - 26) + '" y="21" text-anchor="middle" ' +
            'font-family="Segoe UI, Arial, sans-serif" font-size="9.5" fill="' +
            palette.text3 + '">' + escapeHtml(count) + '</text>'
          : "") +
        "</g>";
    }).join("");
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + width +
      '" height="' + height + '" viewBox="0 0 ' + width + " " + height + '">' +
      '<defs><marker id="lineageExportArrow" viewBox="0 0 8 8" refX="7" ' +
      'refY="4" markerWidth="6" markerHeight="6" orient="auto">' +
      '<path d="M0 0L8 4L0 8z" fill="' + palette.borderStrong + '"/>' +
      "</marker></defs>" +
      '<rect width="' + width + '" height="' + height + '" fill="' +
      palette.background + '"/>' +
      "<g>" + artifacts + groups + "</g><g>" + treeEdges + edges +
      "</g><g>" + cards + "</g></svg>";
  }

  export function analysisLineagePngData(svg) {
    return new Promise(function (resolve, reject) {
      var blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var image = new Image();
      image.onload = function () {
        try {
          var longest = Math.max(image.width, image.height, 1);
          var scale = Math.max(0.5, Math.min(2, 8000 / longest));
          var canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(image.width * scale));
          canvas.height = Math.max(1, Math.round(image.height * scale));
          var context = canvas.getContext("2d");
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          URL.revokeObjectURL(url);
          resolve(canvas.toDataURL("image/png"));
        } catch (error) {
          URL.revokeObjectURL(url);
          reject(error);
        }
      };
      image.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("Image export failed"));
      };
      image.src = url;
    });
  }

  function analysisLineageTargetMatches(target) {
    var current = state.analysisLineageTarget;
    return Boolean(
      current && state.analysisLineage &&
      current.kind === target.kind &&
      current.table === target.table &&
      current.name === target.name
    );
  }

  function analysisLineageFetchGraph(target) {
    var datasetId = getSelectValue("modelSelect");
    if (!datasetId || !app.apiReady()) {
      return Promise.reject(new Error("Run the analysis first"));
    }
    var path = "/api/analysis/lineage?dataset_id=" +
      encodeURIComponent(datasetId) +
      "&kind=" + encodeURIComponent(target.kind) +
      "&table=" + encodeURIComponent(target.table) +
      "&name=" + encodeURIComponent(target.name) +
      "&direction=both&category=all&outline_mode=compact&depth=4";
    return app.api().get(path);
  }

  export function analysisExportLineageImage(target, format) {
    if (!target) return;
    var graphPromise = analysisLineageTargetMatches(target)
      ? Promise.resolve(state.analysisLineage)
      : analysisLineageFetchGraph(target);
    graphPromise.then(function (graph) {
      var svg = analysisLineageSvgDocument(graph);
      return (format === "png" ? analysisLineagePngData(svg) : Promise.resolve(svg))
        .then(function (content) {
          return app.api().post("/api/analysis/lineage/image", {
            table: target.table,
            name: target.name || target.table,
            format: format,
            content: content
          });
        });
    }).then(function (data) {
      if (!data || !data.path) return;
      app.toast("Export: " + data.path);
      app.api().post("/api/files/open", { path: data.path, mode: "open" })
        .catch(function () {});
    }).catch(app.reportError);
  }

  function analysisLineageMermaid(graph) {
    var ids = {};
    var lines = ["flowchart LR"];
    (graph.nodes || []).forEach(function (node, index) {
      var id = "n" + index;
      ids[node.id] = id;
      var label = String(node.label || "");
      var context = analysisLineageContext(node);
      if (context) label += " (" + context + ")";
      lines.push('  ' + id + '["' + label.replace(/"/g, "#quot;") + '"]');
    });
    (graph.edges || []).forEach(function (edge) {
      var from = ids[edge.from];
      var to = ids[edge.to];
      if (from && to) lines.push("  " + from + " --> " + to);
    });
    return lines.join("\n");
  }

  function analysisCopyMermaid(target) {
    if (!app.apiReady()) return;
    var datasetId = getSelectValue("modelSelect");
    if (!datasetId) return;
    var path = "/api/analysis/lineage?dataset_id=" + encodeURIComponent(datasetId) +
      "&kind=" + encodeURIComponent(target.kind) +
      "&table=" + encodeURIComponent(target.table) +
      "&name=" + encodeURIComponent(target.name) +
      "&direction=both&category=all&depth=4";
    app.api().get(path).then(function (graph) {
      copyTextValue(analysisLineageMermaid(graph));
    }).catch(app.reportError);
  }

  export function analysisResetPreview() {
    state.analysisRawTarget = null;
    $("#analysisRawSub").textContent = "";
    $("#analysisRawStatus").textContent = "";
    $("#analysisRawTableWrap").hidden = true;
    $("#analysisRawQueryWrap").hidden = true;
    $("#analysisRawQuery").textContent = "";
    $("#analysisRawHead").innerHTML = "";
    $("#analysisRawBody").innerHTML = "";
    $("#analysisRawLoad").disabled = false;
  }

  function analysisOpenPreview(target) {
    var dialog = $("#analysisRawDialog");
    if (!dialog) return;
    analysisResetPreview();
    state.analysisRawTarget = {
      kind: target.kind,
      table: target.table,
      name: target.name
    };
    $("#analysisRawSub").textContent = "'" + target.table + "'[" + target.name + "]";
    $("#analysisRawStatus").textContent = "Not loaded";
    if (dialog.open) dialog.close();
    dialog.showModal();
  }

  export function analysisRunPreview() {
    var target = state.analysisRawTarget;
    var datasetId = getSelectValue("modelSelect");
    if (!target || !datasetId) return;
    $("#analysisRawStatus").textContent = "Loading preview…";
    app.startJob({
      kind: "analysis-preview",
      path: "/api/analysis/preview",
      body: {
        dataset_id: datasetId,
        kind: target.kind,
        table: target.table,
        name: target.name,
        limit: 100
      },
      label: "Preview values",
      button: $("#analysisRawLoad"),
      silent: true,
      onBusy: function () {
        $("#analysisRawStatus").textContent =
          "Another job is still running. Try again.";
      },
      onDone: function (snapshot) {
        if (snapshot.result) analysisRenderPreview(snapshot.result);
      },
      onError: function (_snapshot, message) {
        $("#analysisRawStatus").textContent =
          (message || "Preview could not be loaded");
      }
    });
  }

  function analysisRenderPreview(payload) {
    var rows = payload.rows || [];
    var columns = payload.columns || [];
    $("#analysisRawHead").innerHTML = columns.length
      ? "<tr>" + columns.map(function (column) {
        return "<th>" + escapeHtml(column) + "</th>";
      }).join("") + "</tr>"
      : "";
    $("#analysisRawBody").innerHTML = rows.map(function (row) {
      return "<tr>" + columns.map(function (_column, index) {
        var value = row[index];
        var empty = value === "" || value === null || value === undefined;
        return '<td' + (empty ? ' class="cell-null"' : "") + ">" +
          escapeHtml(empty ? "\u2014" : String(value)) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    $("#analysisRawTableWrap").hidden = rows.length === 0;
    var status = rows.length
      ? rows.length + " " + "rows"
      : "No rows returned";
    if (payload.truncated) {
      status += " \u00b7 " + "first {n} rows".replace("{n}", payload.limit);
    }
    $("#analysisRawStatus").textContent = status;
    $("#analysisRawQueryWrap").hidden = !payload.query;
    $("#analysisRawQuery").textContent = payload.query || "";
  }

  function analysisOpenItemDetails(target) {
    var datasetId = getSelectValue("modelSelect");
    var dialog = $("#analysisItemDialog");
    if (!datasetId || !dialog) return;
    state.analysisItemTarget = {
      kind: target.kind,
      table: target.table,
      name: target.name
    };
    state.analysisItem = null;
    state.analysisItemRaw = null;
    state.analysisItemRawError = "";
    state.analysisItemTab = "properties";
    $("#analysisItemTitle").textContent = target.kind === "measure"
      ? "Measure details" : "Column details";
    $("#analysisItemSub").textContent = "'" + target.table + "'[" + target.name + "]";
    $("#analysisItemPane").innerHTML =
      '<p class="helper">' + escapeHtml("Loading details…") + "</p>";
    analysisItemTabs();
    if (dialog.open) dialog.close();
    dialog.showModal();
    var path = "/api/analysis/details?dataset_id=" + encodeURIComponent(datasetId) +
      "&kind=" + encodeURIComponent(target.kind) +
      "&table=" + encodeURIComponent(target.table) +
      "&name=" + encodeURIComponent(target.name);
    app.api().get(path).then(function (data) {
      state.analysisItem = data.details;
      analysisRenderItemDetails();
    }).catch(function (error) {
      $("#analysisItemPane").innerHTML =
        '<p class="helper">' + escapeHtml((error.message)) + "</p>";
      app.reportError(error);
    });
  }

  export function analysisItemTabs() {
    $$("#analysisItemTabs [role='tab']").forEach(function (tab) {
      var active = tab.getAttribute("data-item-tab") === state.analysisItemTab;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
    });
  }

  export function analysisRenderItemDetails() {
    var details = state.analysisItem;
    if (!details) return;
    var pane = $("#analysisItemPane");
    if (state.analysisItemTab === "properties") {
      pane.innerHTML = analysisItemPropertiesMarkup(details);
    } else if (state.analysisItemTab === "usage") {
      pane.innerHTML = analysisItemUsageMarkup(details);
    } else if (state.analysisItemTab === "dependencies") {
      pane.innerHTML = analysisItemDependenciesMarkup(details);
    } else if (state.analysisItemRawError) {
      pane.innerHTML = '<p class="helper">' +
        escapeHtml(state.analysisItemRawError) + "</p>" +
        '<p><button class="btn btn-sm" type="button" data-item-raw-retry>' +
        escapeHtml("Reload") + "</button></p>";
    } else if (state.analysisItemRaw) {
      pane.innerHTML = '<pre class="detail-code">' +
        highlightCode(analysisPrettyJson(state.analysisItemRaw), "json") + "</pre>";
    } else {
      pane.innerHTML = '<p class="helper">' +
        escapeHtml("Loading metadata…") + "</p>";
      analysisLoadItemRaw();
    }
  }

  function analysisItemPropertiesMarkup(details) {
    var measure = details.type === "Measure";
    var rows = [
      ["Name", details.name],
      ["Model", details.model_name],
      ["Table", details.table_name],
      ["Type", details.type],
      ["Data type", details.data_type_str],
      ["Size", measure ? "\u2014" : analysisFmtBytes(details.size)],
      ["Rows", measure ? "\u2014" : details.rows],
      ["Format string", details.format_string],
      ["Display folder", details.display_folder],
      ["Hidden", details.is_hidden ? "Yes" : "No"],
      ["Status", tStatus(details.status)],
      ["Reason", (details.reason)],
      ["Lineage tag", details.lineage_tag ||
        (state.analysisItemRaw
          ? (state.analysisItemRaw.LineageTag || "\u2014")
          : "See Raw JSON")],
      ["Annotation", details.annotation]
    ];
    if (!measure) {
      rows.splice(6, 0,
        ["Cardinality", details.cardinality ? fmtInt(details.cardinality) : "—"],
        ["Data size", analysisFmtBytes(details.size_data)],
        ["Hierarchy size", analysisFmtBytes(details.size_hierarchy)],
        ["Dictionary size", analysisFmtBytes(details.size_dictionary)]
      );
    }
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    if (details.expression) {
      html += '<h3 class="detail-heading">' + escapeHtml("Expression") +
        "</h3>" + analysisExpressionMarkup(details.expression, "dax");
    }
    return html;
  }

  function analysisItemUsageMarkup(details) {
    var rows = [
      ["Status", tStatus(details.status)],
      ["Reason", (details.reason)],
      ["Model dependencies", (details.model_dependencies || []).length],
      ["Relationships", (details.relationship_dependencies || []).length],
      ["Visuals", (details.visual_dependencies || []).length],
      ["Page level filters", (details.page_level_filters_dependencies || []).length],
      ["Report level filters", (details.report_level_filters_dependencies || []).length]
    ];
    var flags = Object.keys(USAGE_FLAG_LABELS).filter(function (key) {
      return details[key] === true;
    });
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    html += '<h3 class="detail-heading">' + escapeHtml("Usage flags") + "</h3>";
    html += '<div class="item-flags">' + (flags.length
      ? flags.map(function (key) {
        return '<span class="chip chip-ok"><span class="dot"></span>' +
          escapeHtml((USAGE_FLAG_LABELS[key])) + "</span>";
      }).join("")
      : '<span class="helper">' + escapeHtml("No usage detected") + "</span>") +
      "</div>";
    if ((details.unsupported || []).length) {
      var unsupported = [];
      (details.unsupported || []).forEach(function (key) {
        var label = (UNSUPPORTED_LABELS[key] || key);
        if (unsupported.indexOf(label) === -1) unsupported.push(label);
      });
      html += '<p class="item-note">' + escapeHtml("Not detected by this tool") +
        ": " + escapeHtml(unsupported.join(", ")) + "</p>";
    }
    return html;
  }

  function analysisItemDependenciesMarkup(details) {
    var sections = [];
    DETAIL_GROUPS.forEach(function (group) {
      var rows = details[group[0]];
      if (!rows || !rows.length) return;
      sections.push(
        '<section class="dep-group"><h3>' + escapeHtml((group[1])) +
        "</h3><ul class=\"dep-list\">" + rows.map(function (entry) {
          var text = analysisDependencyText(entry);
          var sub = analysisDependencySub(entry);
          var clickable = Boolean(
            entry.target_kind && entry.target_table && entry.target_name
          );
          var attrs = clickable
            ? ' class="dep-click" data-dep-kind="' + escapeHtml(entry.target_kind) +
              '" data-dep-table="' + escapeHtml(entry.target_table) +
              '" data-dep-name="' + escapeHtml(entry.target_name) +
              '" title="' + escapeHtml("Open lineage") + '"'
            : "";
          return "<li" + attrs + "><span class=\"dep-kind\">" +
            escapeHtml(String(entry.kind || entry.type || "")) + "</span>" +
            escapeHtml(text) +
            (sub ? '<span class="dep-sub">' + escapeHtml(sub) + "</span>" : "") +
            "</li>";
        }).join("") + "</ul></section>"
      );
    });
    return sections.length
      ? sections.join("")
      : '<p class="helper">' + escapeHtml("No dependencies") + "</p>";
  }

  function analysisDependencyText(entry) {
    if (!entry || typeof entry !== "object") return String(entry || "");
    if (entry.table1 || entry.table2) {
      return (entry.table1 || "") + "[" + (entry.column1 || "") + "] \u2192 " +
        (entry.table2 || "") + "[" + (entry.column2 || "") + "]";
    }
    if (entry.object) return entry.object;
    if (entry.report || entry.page || entry.visual) {
      return [entry.report, entry.page, entry.visual].filter(Boolean).join(" \u00b7 ");
    }
    if (entry.table) {
      return entry.table + (entry.column ? "[" + entry.column + "]" : "");
    }
    return analysisPrettyJson(entry);
  }

  function analysisDependencySub(entry) {
    if (!entry || typeof entry !== "object") return "";
    var detail = String(entry.detail || "");
    if (detail && entry.object && detail.indexOf(entry.object) !== -1) {
      detail = "";
    }
    return [
      entry.relationship_type,
      entry.type,
      detail,
      entry.hidden ? "Hidden" : ""
    ].filter(Boolean).join(" \u00b7 ");
  }

  export function analysisPrettyJson(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  }

  function analysisLoadItemRaw() {
    var target = state.analysisItemTarget;
    if (!target || state.analysisItemRaw) return;
    state.analysisItemRawError = "";
    analysisFetchRawMetadata(target, function (payload) {
      state.analysisItemRaw = payload.row;
      if (state.analysisItemTab === "raw") analysisRenderItemDetails();
    }, function (message) {
      state.analysisItemRawError = (message);
      if (state.analysisItemTab === "raw") analysisRenderItemDetails();
    });
  }

  export function analysisCopyItemJson() {
    if (!state.analysisItem) return;
    copyTextValue(analysisPrettyJson(state.analysisItem));
  }

  function analysisFetchRawMetadata(target, onDone, onError) {
    var datasetId = getSelectValue("modelSelect");
    if (!datasetId) return;
    app.startJob({
      kind: "analysis-raw-metadata",
      path: "/api/analysis/raw-metadata",
      body: {
        dataset_id: datasetId,
        kind: target.kind,
        table: target.table,
        name: target.name
      },
      label: "Raw data",
      silent: true,
      onBusy: function () {
        if (onError) onError("Another job is still running. Try again.");
      },
      onDone: function (snapshot) {
        if (snapshot.result) onDone(snapshot.result);
        else if (onError) onError("Metadata could not be loaded");
      },
      onError: function (_snapshot, message) {
        if (onError) onError(message);
      }
    });
  }

  function analysisOpenRawMetadata(target) {
    var dialog = $("#analysisRawMetaDialog");
    if (!dialog) return;
    state.analysisRawMeta = null;
    state.analysisRawMetaTarget = {
      kind: target.kind,
      table: target.table,
      name: target.name
    };
    $("#analysisRawMetaSub").textContent = "'" + target.table + "'[" + target.name + "]";
    $("#analysisRawMetaStatus").textContent = "Loading metadata…";
    $("#analysisRawMetaJson").textContent = "";
    if (dialog.open) dialog.close();
    dialog.showModal();
    analysisReloadRawMetadata();
  }

  export function analysisReloadRawMetadata() {
    var target = state.analysisRawMetaTarget;
    if (!target) return;
    state.analysisRawMeta = null;
    $("#analysisRawMetaStatus").textContent = "Loading metadata…";
    $("#analysisRawMetaJson").textContent = "";
    analysisFetchRawMetadata(target, function (payload) {
      state.analysisRawMeta = payload.row;
      $("#analysisRawMetaStatus").textContent =
        payload.dmv + " \u00b7 " + payload.table + "[" + payload.name + "]";
      $("#analysisRawMetaJson").textContent =
        analysisPrettyJson(payload.row);
    }, function (message) {
      $("#analysisRawMetaStatus").textContent = (message);
    });
  }

  export function analysisResetRawMetadata() {
    state.analysisRawMeta = null;
    state.analysisRawMetaTarget = null;
    $("#analysisRawMetaSub").textContent = "";
    $("#analysisRawMetaStatus").textContent = "";
    $("#analysisRawMetaJson").textContent = "";
  }

  function analysisExpressionMarkup(expression, language) {
    var copyLabel = escapeHtml("Copy code");
    return '<div class="code-cell detail-code-cell">' +
      '<button type="button" class="code-copy" data-copy-code aria-label="' +
      copyLabel + '" title="' + copyLabel + '">' + MENU_ICONS.copy +
      '</button><pre class="detail-code">' +
      highlightCode(expression, language || "dax") + "</pre></div>";
  }

  function analysisDetailRow(label, value) {
    var text = (value === undefined || value === null || value === "") ?
      "\u2014" : String(value);
    return '<div class="detail-row"><span class="detail-key">' +
      escapeHtml(label) + '</span><span class="detail-value">' +
      escapeHtml(text) + "</span></div>";
  }

  function analysisDetailsMarkup(item, kind) {
    var rows;
    var hasError = item.has_error ? "Yes" : "No";
    if (kind === "measure") {
      rows = [
        ["Table", item.table],
        ["Type", item.is_hidden ? "Measure" + " \u00b7 " + "Hidden" : "Measure"],
        ["Data type", item.data_type],
        ["Format string", item.format_string],
        ["Display folder", item.display_folder],
        ["Status", tStatus(item.status)],
        ["Reason", (item.reason)],
        ["Uses", item.uses],
        ["Reports", item.reports],
        ["Has error", hasError]
      ];
    } else {
      var breakdown = item.size_breakdown || {};
      rows = [
        ["Table", item.table],
        ["Type", item.is_calculated ? "Calculated column" : "Column"],
        ["Data type", item.data_type],
        ["Size", item.size],
        ["Data size", analysisFmtBytes(breakdown.data || 0)],
        ["Hierarchy size", analysisFmtBytes(breakdown.hierarchy || 0)],
        ["Dictionary size", analysisFmtBytes(breakdown.dictionary || 0)],
        ["Rows", item.rows],
        ["Format string", item.format_string],
        ["Display folder", item.display_folder],
        ["Hidden", item.is_hidden ? "Yes" : "No"],
        ["Status", tStatus(item.status)],
        ["Reason", (item.reason)],
        ["Uses", item.uses],
        ["Reports", item.reports],
        ["Has error", hasError]
      ];
    }
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    if (item.expression) {
      html += '<h3 class="detail-heading">' + escapeHtml("Expression") +
        "</h3>" + analysisExpressionMarkup(item.expression, "dax");
    }
    return html;
  }

  function analysisOpenDetails(target, mode) {
    var item = analysisFindItem(target.kind, target.table, target.name);
    var dialog = $("#analysisDetailsDialog");
    if (!item || !dialog) return;
    var isMeasure = target.kind === "measure";
    $("#analysisDetailsTitle").textContent = mode === "dax"
      ? "DAX expression"
      : (isMeasure ? "Measure details" : "Column details");
    $("#analysisDetailsSub").textContent = analysisItemLabel(item);
    state.analysisDetailsExpression = String(item.expression || "");
    if (mode === "dax") {
      $("#analysisDetailsBody").innerHTML = item.expression
        ? analysisExpressionMarkup(item.expression, "dax")
        : '<p class="detail-empty">' + escapeHtml("(no DAX expression)") + "</p>";
    } else {
      $("#analysisDetailsBody").innerHTML = analysisDetailsMarkup(item, target.kind);
    }
    $("#copyAnalysisExpression").hidden = !item.expression;
    if (dialog.open) dialog.close();
    dialog.showModal();
  }

  // -- Lineage graph kolom/measure ----------------------------------------
  export function analysisLineageOpen(target, view, category, outlineMode) {
    var dialog = $("#analysisLineageDialog");
    if (!dialog) return;
    state.analysisLineageTarget = {
      kind: target.kind,
      table: target.table,
      name: target.name
    };
    state.analysisLineage = null;
    state.analysisLineageHighlight = null;
    state.analysisLineageItemDrag = null;
    state.analysisLineageSuppressClick = 0;
    state.analysisLineageZoom = 1;
    state.analysisLineageDirection = "both";
    state.analysisLineageView = view === "outline" ? "outline" : "graph";
    state.analysisLineageOutlineMode =
      outlineMode === "full" ? "full" : "compact";
    state.analysisLineageCategory = category || "all";
    $("#analysisLineageSearch").value = "";
    $("#analysisLineageNodes").innerHTML = "";
    $("#analysisLineageEdges").innerHTML = "";
    $("#analysisLineageTreeEdges").innerHTML = "";
    $("#analysisLineageArtifacts").innerHTML = "";
    $("#analysisLineageGroups").innerHTML = "";
    $("#analysisLineageOutline").innerHTML = "";
    $("#analysisLineageNotice").textContent = "";
    $("#analysisLineageM").hidden = true;
    $("#analysisLineageMDetails").hidden = true;
    $("#analysisLineageMList").innerHTML = "";
    $("#analysisLineageSub").textContent = analysisLineageSubtitle();
    analysisLineageDirectionButtons();
    analysisLineageViewButtons();
    analysisLineageApplyView();
    if (dialog.open) dialog.close();
    dialog.showModal();
    analysisLoadLineage();
  }

  function analysisLineageSubtitle() {
    var target = state.analysisLineageTarget;
    if (!target) return "";
    var text = target.kind === "table"
      ? target.table
      : "'" + target.table + "'[" + target.name + "]";
    if (state.analysisLineageCategory !== "all") {
      var label = "";
      LINEAGE_CATEGORIES.forEach(function (item) {
        if (item[0] === state.analysisLineageCategory) label = item[1];
      });
      if (label) text += " \u00b7 " + (label);
    }
    return text;
  }

  export function analysisLineageViewButtons() {
    $$("#analysisLineageView [data-lineage-view]").forEach(function (button) {
      button.setAttribute(
        "aria-pressed",
        button.getAttribute("data-lineage-view") === state.analysisLineageView
          ? "true" : "false"
      );
    });
    $$("#analysisLineageOutlineMode [data-outline-mode]").forEach(function (button) {
      button.setAttribute(
        "aria-pressed",
        button.getAttribute("data-outline-mode") ===
          state.analysisLineageOutlineMode ? "true" : "false"
      );
    });
  }

  export function analysisLineageApplyView() {
    var outline = state.analysisLineageView === "outline";
    $("#analysisLineageCanvasWrap").hidden = outline;
    $("#analysisLineageOutline").hidden = !outline;
    $("#analysisLineageOutlineMode").hidden = !outline;
    var zoom = $("#analysisLineageZoomOut");
    if (zoom) zoom.closest(".graph-zoom").hidden = outline;
    var exportGroup = $("#analysisLineageExport");
    if (exportGroup) exportGroup.hidden = outline;
    analysisLineageViewButtons();
  }

  export function analysisLineageReroot(kind, table, name) {
    if (kind === "table") {
      if (!table) return;
      state.analysisLineageTarget = { kind: "table", table: table, name: table };
    } else if (kind === "column" || kind === "measure") {
      if (!table || !name) return;
      state.analysisLineageTarget = { kind: kind, table: table, name: name };
    } else {
      return;
    }
    state.analysisLineageHighlight = null;
    $("#analysisLineageSub").textContent = analysisLineageSubtitle();
    analysisLoadLineage();
  }

  export function analysisLineageDirectionButtons() {
    $$("#analysisLineageDirection [data-lineage-direction]").forEach(function (button) {
      button.setAttribute(
        "aria-pressed",
        button.getAttribute("data-lineage-direction") === state.analysisLineageDirection
          ? "true" : "false"
      );
    });
  }

  export function analysisLoadLineage() {
    var target = state.analysisLineageTarget;
    var datasetId = getSelectValue("modelSelect");
    if (!target || !datasetId || !app.apiReady()) return;
    $("#analysisLineageNodes").innerHTML = "";
    $("#analysisLineageEdges").innerHTML = "";
    $("#analysisLineageTreeEdges").innerHTML = "";
    $("#analysisLineageNotice").textContent = "";
    analysisLineageShowEmpty("Loading lineage…", "");
    var depth = state.analysisLineageView === "outline" ? 6 : 4;
    var path = "/api/analysis/lineage?dataset_id=" + encodeURIComponent(datasetId) +
      "&kind=" + encodeURIComponent(target.kind) +
      "&table=" + encodeURIComponent(target.table) +
      "&name=" + encodeURIComponent(target.name) +
      "&direction=" + encodeURIComponent(state.analysisLineageDirection) +
      "&category=" + encodeURIComponent(state.analysisLineageCategory) +
      "&outline_mode=" + encodeURIComponent(state.analysisLineageOutlineMode) +
      "&depth=" + depth;
    app.api().get(path).then(function (data) {
      state.analysisLineage = data;
      $("#analysisLineageSub").textContent = analysisLineageSubtitle();
      analysisLineageRender();
    }).catch(function (error) {
      state.analysisLineage = null;
      analysisLineageShowEmpty("Lineage could not be loaded", (error.message));
      app.reportError(error);
    });
  }

  function analysisLineageShowEmpty(title, text) {
    $("#analysisLineageEmpty").hidden = false;
    $("#analysisLineageEmptyTitle").textContent = title || "No lineage data";
    $("#analysisLineageEmptyText").textContent = text || "";
  }

  export function analysisLineageEdges(graph) {
    return (graph && (graph.canvas_edges || graph.edges)) || [];
  }

  export function analysisLineageTreeEdges(graph) {
    return (graph && graph.tree_edges) || [];
  }

  function analysisLineageTreePath(parent, child) {
    var px = Number(parent.x) || 0;
    var py = Number(parent.y) || 0;
    var pw = Number(parent.w) || 0;
    var ph = Number(parent.h) || 0;
    var cx = Number(child.x) || 0;
    var cy = Number(child.y) || 0;
    var cw = Number(child.w) || 0;
    var ch = Number(child.h) || 0;
    var childCenterY = cy + ch / 2;
    var childCenterX = cx + cw / 2;
    if (cy >= py + ph - 1) {
      // Anak di bawah header: spine vertikal di padding grup.
      var spineX = Math.max(4, px - 8);
      return "M" + px + " " + (py + ph / 2) +
        " H" + spineX + " V" + childCenterY + " H" + cx;
    }
    if (cx >= px + pw - 1) {
      // Anak di kanan parent.
      var midX = px + pw + Math.max(10, (cx - px - pw) / 2);
      return "M" + (px + pw) + " " + (py + ph / 2) +
        " H" + midX + " V" + childCenterY + " H" + cx;
    }
    return "M" + (px + pw / 2) + " " + (py + ph / 2) +
      " L" + childCenterX + " " + childCenterY;
  }

  function analysisLineageTreeMarkup(graph, byId) {
    return analysisLineageTreeEdges(graph).map(function (edge) {
      var source = byId[edge.from];
      var target = byId[edge.to];
      if (!source || !target) return "";
      return '<path class="lineage-tree-edge" data-tree-from="' +
        escapeHtml(edge.from) + '" data-tree-to="' + escapeHtml(edge.to) +
        '" d="' + analysisLineageTreePath(source, target) + '"></path>';
    }).join("");
  }

  function analysisLineageResizeCanvas() {
    var graph = state.analysisLineage;
    if (!graph) return;
    var width = Math.max(1, Number(graph.width) || 1);
    var height = Math.max(1, Number(graph.height) || 1);
    var canvas = $("#analysisLineageCanvas");
    var svg = $("#analysisLineageSvg");
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    analysisLineageApplyZoom();
  }

  function analysisLineageRender() {
    var graph = state.analysisLineage;
    if (!graph || !(graph.nodes || []).length) {
      analysisLineageShowEmpty(
        "No lineage data",
        "No dependencies found"
      );
      return;
    }
    $("#analysisLineageEmpty").hidden = true;
    var width = Math.max(1, Number(graph.width) || 1);
    var height = Math.max(1, Number(graph.height) || 1);
    var canvas = $("#analysisLineageCanvas");
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    var svg = $("#analysisLineageSvg");
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    var byId = {};
    (graph.nodes || []).forEach(function (node) {
      byId[node.id] = node;
    });
    var edges = analysisLineageEdges(graph);
    var routes = analysisLineageEdgeRoutes(graph);
    $("#analysisLineageTreeEdges").innerHTML = analysisLineageTreeMarkup(graph, byId);
    $("#analysisLineageEdges").innerHTML = edges.map(function (edge, index) {
      var source = byId[edge.from];
      var target = byId[edge.to];
      if (!source || !target) return "";
      return '<path class="lineage-edge kind-' + escapeHtml(edge.kind || "depend") +
        '" data-edge-from="' + escapeHtml(edge.from) +
        '" data-edge-to="' + escapeHtml(edge.to) +
        '" d="' + (routes[index] || analysisLineageEdgePath(source, target)) +
        '" marker-end="url(#lineageArrow)"></path>';
    }).join("");
    $("#analysisLineageArtifacts").innerHTML = (graph.artifacts || []).map(
      analysisLineageArtifactMarkup
    ).join("");
    $("#analysisLineageGroups").innerHTML = (graph.groups || []).map(
      analysisLineageGroupMarkup
    ).join("");
    $("#analysisLineageNodes").innerHTML = (graph.nodes || [])
      .filter(function (node) {
        return !node.role || node.role === "card";
      })
      .map(analysisLineageNodeMarkup)
      .join("");
    $("#analysisLineageOutline").innerHTML = analysisLineageOutlineMarkup(graph);
    state.analysisLineageZoom = 1;
    state.analysisLineageHighlight = null;
    state.analysisLineageItemDrag = null;
    state.analysisLineageSuppressClick = 0;
    $("#analysisLineageNotice").textContent = analysisLineageNotice(graph);
    analysisLineageRenderM(graph.m_lineage);
    analysisLineageFocusSeed();
    analysisLineageApplyView();
    analysisLineageAutoFit();
  }

  function analysisLineageAutoFit() {
    if (state.analysisLineageView !== "graph") return;
    var graph = state.analysisLineage;
    var wrap = $("#analysisLineageCanvasWrap");
    if (!graph || !wrap) return;
    var width = Number(graph.width) || 0;
    var height = Number(graph.height) || 0;
    if (
      width > Math.max(240, wrap.clientWidth - 32) ||
      height > Math.max(160, wrap.clientHeight - 32)
    ) {
      analysisLineageFit();
    }
  }

  function analysisLineageRenderM(meta) {
    var box = $("#analysisLineageM");
    if (!box) return;
    if (!meta || !meta.status) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    var labels = {
      complete: "Complete",
      partial: "Partial",
      unavailable: "Unavailable"
    };
    var classes = {
      complete: "chip-ok",
      partial: "chip-warn",
      unavailable: "chip-danger"
    };
    var chip = $("#analysisLineageMStatus");
    chip.className = "chip " + (classes[meta.status] || "chip-idle");
    chip.textContent = "M lineage" + ": " +
      (labels[meta.status] || meta.status);
    chip.title = (meta.reason || "");
    var source = $("#analysisLineageMSource");
    if (source) {
      var parts = [];
      if (meta.source) parts.push(String(meta.source));
      if (meta.origin) {
        parts.push((LINEAGE_ORIGIN_LABELS[meta.origin] || meta.origin));
      }
      if (meta.native) parts.push("Native query");
      if (meta.params && meta.params.length) {
        parts.push("Parameters" + ": " + meta.params.join(", "));
      }
      if (meta.references && meta.references.length) {
        parts.push("Query refs" + ": " + meta.references.join(", "));
      }
      source.textContent = parts.join(" \u00b7 ");
      source.title = String(meta.detail || "");
      source.hidden = parts.length === 0;
    }
    var warnings = meta.warnings || [];
    $("#analysisLineageMDetails").hidden = warnings.length === 0;
    $("#analysisLineageMSummary").textContent =
      "M warnings" + " (" + warnings.length + ")";
    $("#analysisLineageMList").innerHTML = warnings.map(function (warning) {
      var parts = [];
      if (warning.step) {
        parts.push('<span class="m-warning-step">' +
          escapeHtml(warning.step) + "</span>");
      }
      if (warning.column) parts.push(escapeHtml(warning.column));
      parts.push(escapeHtml((warning.detail || warning.status || "")));
      return "<li>" + parts.join(" \u00b7 ") + "</li>";
    }).join("");
  }

  function analysisLineageContext(node) {
    var context = String(node.context || "");
    if (!context) return "";
    if (node.kind === "datasource" && LINEAGE_ORIGIN_LABELS[context]) {
      return (LINEAGE_ORIGIN_LABELS[context]);
    }
    return context;
  }

  function analysisLineageTitle(meta) {
    var label = String(meta.label || "");
    if (!label && meta.label_key) label = (meta.label_key);
    var sub = meta.sub_key ? (meta.sub_key) : "";
    var detail = String(meta.sub || "");
    if (detail && detail === label) detail = "";
    if (detail) sub = sub ? sub + " \u00b7 " + detail : detail;
    return { label: label, sub: sub };
  }

  function analysisLineageIcon(kind) {
    var iconKey = LINEAGE_KIND_ICONS[kind];
    if (!iconKey) iconKey = kind === "model" ? "table" : "group";
    return ANALYSIS_ICONS[iconKey] || ANALYSIS_ICONS.group;
  }

  function analysisLineageHeaderMarkup(meta, headId, headKind, className) {
    var title = analysisLineageTitle(meta);
    var head = headId
      ? ' data-node-id="' + escapeHtml(headId) +
        '" data-node-kind="' + escapeHtml(headKind || meta.kind || "") +
        '" data-node-table="' + escapeHtml(meta.label || "") +
        '" data-node-name="' + escapeHtml(title.label) + '"'
      : "";
    return '<div class="' + className + (headId ? " has-node" : "") + '"' + head +
      ' data-search="' + escapeHtml((title.label + " " + title.sub).toLowerCase()) + '">' +
      '<span class="lg-icon">' + analysisLineageIcon(meta.kind) + "</span>" +
      '<span class="lg-text"><span class="lg-title">' + escapeHtml(title.label) +
      '</span><span class="lg-sub">' + escapeHtml(title.sub) + "</span></span></div>";
  }

  function analysisLineageArtifactMarkup(artifact) {
    return '<div class="lineage-artifact group-' +
      escapeHtml(artifact.kind || "model") + '" data-artifact-id="' +
      escapeHtml(artifact.id || "") + '" style="left:' + artifact.x + "px;top:" +
      artifact.y + "px;width:" + artifact.w + "px;height:" + artifact.h + 'px">' +
      '<div class="la-head" style="left:' + (artifact.head_x - artifact.x) +
      "px;top:" + (artifact.head_y - artifact.y) + "px;width:" + artifact.head_w +
      "px;height:" + artifact.head_h + 'px">' +
      analysisLineageHeaderMarkup(
        artifact, artifact.head_id, artifact.kind, "la-titlebar"
      ) + "</div></div>";
  }

  function analysisLineageGroupMarkup(group) {
    return '<div class="lineage-group group-' +
      escapeHtml(group.kind || "model") + '" data-group-id="' +
      escapeHtml(group.id || "") + '" style="left:' + group.x + "px;top:" +
      group.y + "px;width:" + group.w + "px;height:" + group.h + 'px">' +
      '<div class="lg-head" style="left:' + (group.head_x - group.x) +
      "px;top:" + (group.head_y - group.y) + "px;width:" + group.head_w +
      "px;height:" + group.head_h + 'px">' +
      analysisLineageHeaderMarkup(
        group, group.head_id, group.kind === "page" ? "page" : group.kind,
        "lg-titlebar"
      ) + "</div></div>";
  }

  function analysisLineageCardText(node) {
    var kindLabel = (LINEAGE_KIND_LABELS[node.kind] || "Node");
    var context = analysisLineageContext(node);
    var detail = String(node.detail || "").trim();
    var title = String(node.label || "");
    var sub = kindLabel;
    var note = "";
    if (node.kind === "mstep") {
      title = String(node.detail || node.label || "");
      sub = String(node.context || kindLabel);
      note = String(node.label || "");
      if (note === title) note = "";
    } else if (node.kind === "mquery") {
      sub = "M query";
      note = context;
    } else if (node.kind === "datasource") {
      sub = kindLabel;
      note = [context, detail].filter(Boolean).join(" \u00b7 ");
    } else if (node.group === "usage" || node.group === "more") {
      sub = "Used in" + " " + kindLabel.toLowerCase() +
        (detail ? " (" + detail + ")" : "");
    } else if (
      context && (
        node.kind === "column" || node.kind === "measure" ||
        node.kind === "table" || node.kind === "datasource"
      )
    ) {
      note = context;
    } else if (context) {
      sub = kindLabel + " \u00b7 " + context;
    }
    return {
      title: title,
      sub: sub,
      note: note,
      status: String(node.status || "")
    };
  }

  function analysisLineageStatusClass(status) {
    if (status === "Unused") return "is-unused";
    if (status === "Must keep") return "is-blocker";
    if (status === "Needs review") return "is-check";
    return "is-used";
  }

  function analysisLineageNodeMarkup(node) {
    var iconKey = LINEAGE_KIND_ICONS[node.kind] || "group";
    var icon = ANALYSIS_ICONS[iconKey] || "";
    var text = analysisLineageCardText(node);
    var status = text.status
      ? '<span class="ln-status ' + analysisLineageStatusClass(text.status) +
        '" title="' + escapeHtml(tStatus(text.status)) + '"></span>'
      : "";
    var count = Number(node.count) > 1
      ? '<span class="ln-count">' + Number(node.count) + "</span>"
      : "";
    var step = Number(node.step) > 0
      ? '<span class="ln-step">' + String(Number(node.step)).padStart(2, "0") + "</span>"
      : "";
    var title = text.title + (node.context ? " \u00b7 " + node.context : "");
    var classes = ["lineage-node", "group-" + (node.group || "model")];
    if (node.side === "root") classes.push("is-seed");
    return '<button type="button" class="' + classes.join(" ") + '"' +
      ' data-node-id="' + escapeHtml(node.id) + '"' +
      ' data-node-kind="' + escapeHtml(node.kind) + '"' +
      ' data-node-table="' + escapeHtml(
        node.kind === "table" ? node.label : (node.context || "")
      ) + '"' +
      ' data-node-name="' + escapeHtml(node.label) + '"' +
      ' style="left:' + node.x + "px;top:" + node.y + "px;width:" + node.w +
      "px;height:" + node.h + 'px"' +
      ' title="' + escapeHtml(title) + '">' +
      step + '<span class="ln-icon">' + icon + "</span>" +
      '<span class="ln-text"><span class="ln-title">' + escapeHtml(text.title) +
      '</span><span class="ln-sub">' + escapeHtml(text.sub) + "</span>" +
      (text.note
        ? '<span class="ln-note">' + escapeHtml(text.note) + "</span>"
        : "") +
      '</span><span class="ln-flags">' + status + count + "</span></button>";
  }

  function analysisLineageOutlineMarkup(graph) {
    var outline = graph.outline || {};
    var sections = [];
    if ((outline.upstream || []).length) {
      sections.push(
        '<section class="lo-section"><h3>' + "Depends on" + "</h3>" +
        analysisLineageOutlineList(outline.upstream) + "</section>"
      );
    }
    if ((outline.downstream || []).length) {
      sections.push(
        '<section class="lo-section"><h3>' + "Used by" + "</h3>" +
        analysisLineageOutlineList(outline.downstream) + "</section>"
      );
    }
    if (!sections.length) {
      return '<p class="helper">' + "No dependencies found" + "</p>";
    }
    return sections.join("");
  }

  function analysisLineageOutlineUsage(item) {
    var kind = String(item.usage_kind || "");
    var detail = String(item.detail || "").trim();
    var text = "";
    if (kind === "field") text = "Used in visual";
    else if (kind === "filter-visual") text = "Visual level filter";
    else if (kind === "filter-page") text = "Page level filter";
    else if (kind === "filter-report") text = "Report level filter";
    else if (kind === "filter-query") text = "Visual filter";
    else if (kind === "sort") text = "Sort";
    else if (kind === "format") text = "Formatting";
    if (!text) return "";
    return detail ? text + " (" + detail + ")" : text;
  }

  function analysisLineageOutlineSource(item) {
    if (item.kind !== "datasource") return "";
    var parts = String(item.detail || "").split(" \u00b7 ");
    var keep = [];
    parts.forEach(function (part) {
      var text = String(part || "").trim();
      if (!text) return;
      if (text.indexOf("ref:") === 0 || text.indexOf("param:") === 0) {
        keep.push(text);
      } else if (text === "native query") {
        keep.push("Native query");
      }
    });
    return keep.join(" \u00b7 ");
  }

  function analysisLineageOutlineList(items) {
    if (!items || !items.length) return "";
    return '<ul class="lo-list">' + items.map(function (item) {
      var icon = ANALYSIS_ICONS[LINEAGE_KIND_ICONS[item.kind] || "group"] || "";
      var kinds = [(LINEAGE_KIND_LABELS[item.kind] || "Node")];
      var usage = analysisLineageOutlineUsage(item);
      if (usage) kinds.push(usage);
      if (item.visual_title && item.visual_title !== item.label) {
        kinds.push(item.visual_title);
      }
      if (item.visual_type) kinds.push(item.visual_type);
      if (item.hidden) kinds.push("Hidden");
      var context = analysisLineageContext(item);
      if (context) kinds.push(context);
      var source = analysisLineageOutlineSource(item);
      if (source) kinds.push(source);
      var sub = kinds.join(" \u00b7 ");
      var statusClass = item.status
        ? " " + analysisLineageStatusClass(item.status)
        : "";
      var status = item.status
        ? '<span class="lo-status' + statusClass + '">' +
          escapeHtml(tStatus(item.status)) + "</span>"
        : "";
      var count = Number(item.count) > 1
        ? '<span class="lo-count">' + Number(item.count) + "</span>"
        : "";
      var repeat = item.repeat ? '<span class="lo-repeat">\u2026</span>' : "";
      var rowClass = "lo-row" +
        (item.status === "Unused" ? " is-unused" : "");
      var titleText = item.label + (sub ? " \u00b7 " + sub : "");
      if (item.kind === "datasource" && item.detail) {
        titleText += " \u00b7 " + item.detail;
      }
      var row = '<span class="' + rowClass + '" data-node-id="' + escapeHtml(item.id) +
        '" data-node-kind="' + escapeHtml(item.kind) +
        '" data-node-table="' + escapeHtml(
          item.kind === "table" ? item.label : (item.context || "")
        ) +
        '" data-node-name="' + escapeHtml(item.label) +
        '" title="' + escapeHtml(titleText) + '">' +
        '<span class="lo-icon">' + icon + "</span>" +
        '<span class="lo-text"><span class="lo-title">' + escapeHtml(item.label) +
        '</span><span class="lo-sub">' + escapeHtml(sub) +
        "</span></span>" + status + count + repeat + "</span>";
      var children = analysisLineageOutlineList(item.children);
      if (!children) return "<li>" + row + "</li>";
      return '<li><details class="lo-branch" open><summary>' + row +
        "</summary>" + children + "</details></li>";
    }).join("") + "</ul>";
  }

  function analysisLineageEdgePath(source, target) {
    var x1 = source.x + source.w;
    var y1 = source.y + source.h / 2;
    var x2 = target.x;
    var y2 = target.y + target.h / 2;
    var bend = Math.max(36, Math.abs(x2 - x1) * 0.45);
    return "M" + x1 + " " + y1 +
      " C" + (x1 + bend) + " " + y1 + " " + (x2 - bend) + " " + y2 +
      " " + x2 + " " + y2;
  }

  function analysisLineageEdgeRoutes(graph) {
    var byId = {};
    (graph.nodes || []).forEach(function (node) {
      byId[node.id] = node;
    });
    var artifacts = graph.artifacts || [];
    var byArtifact = {};
    artifacts.forEach(function (artifact) {
      byArtifact[artifact.id] = artifact;
    });
    var reports = artifacts.filter(function (artifact) {
      return artifact.kind === "report";
    }).slice().sort(function (left, right) {
      return left.x - right.x;
    });
    var reportIndex = {};
    reports.forEach(function (report, index) {
      reportIndex[report.id] = index;
    });
    var topY = reports.length
      ? Math.max(8, Math.min.apply(null, reports.map(function (report) {
        return report.y;
      })) - 18)
      : 8;
    var routes = {};
    analysisLineageEdges(graph).forEach(function (edge, index) {
      var source = byId[edge.from];
      var target = byId[edge.to];
      if (!source || !target) return;
      var targetArtifact = byArtifact[target.container_id];
      var sourceArtifact = byArtifact[source.container_id];
      var targetIsReportHead = target.role === "artifact-head" ||
        target.kind === "report";
      var needsCorridor = targetArtifact && targetArtifact.kind === "report" &&
        (targetIsReportHead || reportIndex[targetArtifact.id] > 0) &&
        (!sourceArtifact || sourceArtifact.id !== targetArtifact.id);
      if (needsCorridor) {
        var x1 = source.x + source.w;
        var y1 = source.y + source.h / 2;
        var x2 = target.x;
        var y2 = target.y + target.h / 2;
        var laneX = x1 + 20;
        var targetLane = targetArtifact.x - 14;
        if (targetLane > laneX) {
          routes[index] = "M" + x1 + " " + y1 +
            " H" + laneX + " V" + topY +
            " H" + targetLane + " V" + y2 + " H" + x2;
          return;
        }
      }
      routes[index] = analysisLineageEdgePath(source, target);
    });
    return routes;
  }

  function analysisLineageNotice(graph) {
    return (graph.notices || []).map(function (notice) {
      if (notice.code === "reports_excluded") {
        return "Report usage not included";
      }
      if (notice.code === "truncated") {
        return "Truncated: {n} nodes".replace("{n}", String(notice.count || 0));
      }
      if (notice.code === "m_steps_truncated") {
        return "Truncated M steps: {n}".replace(
          "{n}", String(notice.count || 0)
        );
      }
      if (notice.code === "m_columns_truncated") {
        return "M chains limited to {n} columns".replace(
          "{n}", String(notice.count || 0)
        );
      }
      if (notice.code === "edges_collapsed") {
        if (notice.level === "report") {
          return "Graph simplified: edges point to reports";
        }
        return "Graph simplified: edges point to pages";
      }
      if (notice.code === "no_dependencies") {
        return "No dependencies found";
      }
      return "";
    }).filter(Boolean).join(" \u00b7 ");
  }

  export function analysisLineageApplyZoom() {
    var graph = state.analysisLineage;
    var canvas = $("#analysisLineageCanvas");
    var wrap = $("#analysisLineageCanvasWrap");
    if (!graph || !canvas || !wrap) return;
    var scale = state.analysisLineageZoom;
    canvas.style.transform = "scale(" + scale + ")";
    var tailX = Math.max(0, wrap.clientWidth - 230 * scale - 60);
    var tailY = Math.max(0, wrap.clientHeight - 90);
    $("#analysisLineageSizer").style.width =
      (Number(graph.width || 0) * scale + tailX) + "px";
    $("#analysisLineageSizer").style.height =
      (Number(graph.height || 0) * scale + tailY) + "px";
    $("#analysisLineageZoomValue").textContent = Math.round(scale * 100) + "%";
  }

  export function analysisLineageZoomBy(factor) {
    if (!state.analysisLineage) return;
    state.analysisLineageZoom = Math.min(
      2.5, Math.max(0.12, state.analysisLineageZoom * factor)
    );
    analysisLineageApplyZoom();
  }

  export function analysisLineageFit() {
    var graph = state.analysisLineage;
    var wrap = $("#analysisLineageCanvasWrap");
    if (!graph || !wrap) return;
    var availableW = Math.max(240, wrap.clientWidth - 32);
    var availableH = Math.max(160, wrap.clientHeight - 32);
    var scale = Math.min(
      availableW / Math.max(1, Number(graph.width) || 1),
      availableH / Math.max(1, Number(graph.height) || 1),
      1
    );
    state.analysisLineageZoom = Math.max(0.12, scale);
    analysisLineageApplyZoom();
    wrap.scrollLeft = 0;
    wrap.scrollTop = 0;
  }

  export function analysisLineageDragTarget(event) {
    var head = event.target.closest(".lg-head, .la-head");
    if (head) {
      var group = head.closest(".lineage-group");
      if (group) {
        return { type: "group", id: group.getAttribute("data-group-id") };
      }
      var artifact = head.closest(".lineage-artifact");
      if (artifact) {
        return { type: "artifact", id: artifact.getAttribute("data-artifact-id") };
      }
    }
    var card = event.target.closest(".lineage-node");
    if (card) {
      return { type: "card", id: card.getAttribute("data-node-id") };
    }
    var groupBox = event.target.closest(".lineage-group");
    if (groupBox) {
      return { type: "group", id: groupBox.getAttribute("data-group-id") };
    }
    var artifactBox = event.target.closest(".lineage-artifact");
    if (artifactBox) {
      return {
        type: "artifact",
        id: artifactBox.getAttribute("data-artifact-id")
      };
    }
    return null;
  }

  export function analysisLineageDragScope(target) {
    var graph = state.analysisLineage;
    if (!graph) return null;
    var byId = {};
    (graph.nodes || []).forEach(function (node) { byId[node.id] = node; });
    var scope = { nodes: {}, groups: {}, artifacts: {} };
    function addNode(id) {
      var node = byId[id];
      if (node && (!node.role || node.role === "card")) scope.nodes[id] = node;
    }
    function addGroup(group) {
      if (!group) return;
      scope.groups[group.id] = group;
      (group.members || []).forEach(addNode);
    }
    if (target.type === "card") {
      if (!byId[target.id]) return null;
      scope.nodes[target.id] = byId[target.id];
      return scope;
    }
    if (target.type === "group") {
      var group = (graph.groups || []).filter(function (item) {
        return item.id === target.id;
      })[0];
      if (!group) return null;
      addGroup(group);
      return scope;
    }
    var artifact = (graph.artifacts || []).filter(function (item) {
      return item.id === target.id;
    })[0];
    if (!artifact) return null;
    scope.artifacts[artifact.id] = artifact;
    (graph.groups || []).forEach(function (item) {
      if (item.container === artifact.id) addGroup(item);
    });
    (artifact.members || []).forEach(addNode);
    return scope;
  }

  export function analysisLineageDragPositions(scope) {
    var positions = { nodes: {}, groups: {}, artifacts: {} };
    ["nodes", "groups", "artifacts"].forEach(function (key) {
      Object.keys(scope[key]).forEach(function (id) {
        var item = scope[key][id];
        positions[key][id] = {
          x: Number(item.x) || 0,
          y: Number(item.y) || 0,
          headX: Number(item.head_x),
          headY: Number(item.head_y)
        };
      });
    });
    return positions;
  }

  export function analysisLineageMoveItems(drag, dx, dy) {
    var graph = state.analysisLineage;
    if (!graph) return;
    var bounds = { minX: 0, minY: 0, maxX: 0, maxY: 0 };
    var first = true;
    function measure(item) {
      var x = Number(item.x) || 0;
      var y = Number(item.y) || 0;
      var w = Number(item.w) || 0;
      var h = Number(item.h) || 0;
      if (first) {
        bounds.minX = x; bounds.minY = y;
        bounds.maxX = x + w; bounds.maxY = y + h;
        first = false;
        return;
      }
      bounds.minX = Math.min(bounds.minX, x);
      bounds.minY = Math.min(bounds.minY, y);
      bounds.maxX = Math.max(bounds.maxX, x + w);
      bounds.maxY = Math.max(bounds.maxY, y + h);
    }
    ["nodes", "groups", "artifacts"].forEach(function (key) {
      Object.keys(drag.scope[key]).forEach(function (id) {
        measure(drag.positions[key][id]);
      });
    });
    var limitX = Math.max(0, Number(graph.width) || 0);
    var limitY = Math.max(0, Number(graph.height) || 0);
    var moveX = Math.max(-bounds.minX, dx);
    var moveY = Math.max(-bounds.minY, dy);
    ["nodes", "groups", "artifacts"].forEach(function (key) {
      Object.keys(drag.scope[key]).forEach(function (id) {
        var item = drag.scope[key][id];
        var base = drag.positions[key][id];
        item.x = Math.round(base.x + moveX);
        item.y = Math.round(base.y + moveY);
      });
    });
    Object.keys(drag.scope.groups).forEach(function (id) {
      var group = drag.scope.groups[id];
      var base = drag.positions.groups[id];
      group.head_x = Math.round(base.headX + moveX);
      group.head_y = Math.round(base.headY + moveY);
    });
    Object.keys(drag.scope.artifacts).forEach(function (id) {
      var artifact = drag.scope.artifacts[id];
      var base = drag.positions.artifacts[id];
      artifact.head_x = Math.round(base.headX + moveX);
      artifact.head_y = Math.round(base.headY + moveY);
    });
    var neededX = 0;
    var neededY = 0;
    ["nodes", "groups", "artifacts"].forEach(function (key) {
      Object.keys(drag.scope[key]).forEach(function (id) {
        var item = drag.scope[key][id];
        neededX = Math.max(neededX, (Number(item.x) || 0) + (Number(item.w) || 0));
        neededY = Math.max(neededY, (Number(item.y) || 0) + (Number(item.h) || 0));
      });
    });
    if (neededX + 48 > limitX || neededY + 48 > limitY) {
      graph.width = Math.max(limitX, Math.ceil(neededX + 48));
      graph.height = Math.max(limitY, Math.ceil(neededY + 48));
      analysisLineageResizeCanvas();
    }
    analysisLineageApplyPositions();
    analysisLineageRefreshEdges();
  }

  function analysisLineageApplyPositions() {
    var graph = state.analysisLineage;
    if (!graph) return;
    var byId = {};
    (graph.nodes || []).forEach(function (node) { byId[node.id] = node; });
    var groupById = {};
    (graph.groups || []).forEach(function (group) { groupById[group.id] = group; });
    var artifactById = {};
    (graph.artifacts || []).forEach(function (artifact) {
      artifactById[artifact.id] = artifact;
    });
    $$("#analysisLineageNodes .lineage-node").forEach(function (element) {
      var node = byId[element.getAttribute("data-node-id")];
      if (!node) return;
      element.style.left = node.x + "px";
      element.style.top = node.y + "px";
    });
    $$("#analysisLineageGroups .lineage-group").forEach(function (element) {
      var group = groupById[element.getAttribute("data-group-id")];
      if (!group) return;
      element.style.left = group.x + "px";
      element.style.top = group.y + "px";
    });
    $$("#analysisLineageArtifacts .lineage-artifact").forEach(function (element) {
      var artifact = artifactById[element.getAttribute("data-artifact-id")];
      if (!artifact) return;
      element.style.left = artifact.x + "px";
      element.style.top = artifact.y + "px";
    });
  }

  export function analysisLineageRefreshEdges() {
    var graph = state.analysisLineage;
    if (!graph) return;
    var routes = analysisLineageEdgeRoutes(graph);
    $$("#analysisLineageEdges .lineage-edge").forEach(function (element, index) {
      if (routes[index]) element.setAttribute("d", routes[index]);
    });
    analysisLineageRefreshTreeEdges();
  }

  function analysisLineageRefreshTreeEdges() {
    var graph = state.analysisLineage;
    if (!graph) return;
    var byId = {};
    (graph.nodes || []).forEach(function (node) { byId[node.id] = node; });
    $$("#analysisLineageTreeEdges .lineage-tree-edge").forEach(function (element) {
      var source = byId[element.getAttribute("data-tree-from")];
      var target = byId[element.getAttribute("data-tree-to")];
      if (source && target) {
        element.setAttribute("d", analysisLineageTreePath(source, target));
      }
    });
  }

  function analysisLineageFocusSeed() {
    var graph = state.analysisLineage;
    var wrap = $("#analysisLineageCanvasWrap");
    if (!graph || !wrap) return;
    var graphWidth = Math.max(1, Number(graph.width) || 1);
    var seed = null;
    var minX = Infinity;
    (graph.nodes || []).forEach(function (node) {
      if (node.side === "root") seed = node;
      if (Number(node.x) < minX) minX = Number(node.x);
    });
    if (!seed || !isFinite(minX)) {
      state.analysisLineageZoom = 0.8;
      analysisLineageApplyZoom();
      return;
    }
    if (graphWidth <= 2200) {
      state.analysisLineageZoom = Math.max(
        0.35,
        Math.min(0.8, (wrap.clientWidth - 40) / graphWidth)
      );
    } else {
      var span = Math.max(1, seed.x + seed.w - minX);
      var fit = (wrap.clientWidth - 40) / span;
      state.analysisLineageZoom = Math.max(0.12, Math.min(0.8, fit));
    }
    analysisLineageApplyZoom();
    wrap.scrollLeft = 0;
    wrap.scrollTop = Math.max(
      0, seed.y * state.analysisLineageZoom - wrap.clientHeight / 2 + seed.h / 2
    );
  }

  export function analysisLineageConsumeDragClick() {
    if (!state.analysisLineageSuppressClick) return false;
    var active = Date.now() <= state.analysisLineageSuppressClick;
    state.analysisLineageSuppressClick = 0;
    return active;
  }

  function analysisLineageLineageSet(graph, start) {
    var edges = graph.highlight_edges || graph.canvas_edges || graph.edges || [];
    var outgoing = {};
    var incoming = {};
    edges.forEach(function (edge) {
      (outgoing[edge.from] || (outgoing[edge.from] = [])).push(edge.to);
      (incoming[edge.to] || (incoming[edge.to] = [])).push(edge.from);
    });
    var byId = {};
    (graph.nodes || []).forEach(function (node) { byId[node.id] = node; });
    var startNode = byId[start] || {};
    var startKind = String(startNode.kind || "");
    // Kartu pemakaian (visual/filter/sort) hanya menyorot sumbernya, bukan
    // semua visual lain yang memakai measure yang sama.
    var usageLeaf = ["visual", "filter", "sort", "more"].indexOf(startKind) !== -1;
    var keep = {};
    keep[start] = true;
    var stack = [start];
    while (stack.length) {
      var node = stack.pop();
      (incoming[node] || []).forEach(function (previous) {
        if (!keep[previous]) {
          keep[previous] = true;
          stack.push(previous);
        }
      });
    }
    if (!usageLeaf) {
      stack = [start];
      while (stack.length) {
        var current = stack.pop();
        (outgoing[current] || []).forEach(function (next) {
          if (!keep[next]) {
            keep[next] = true;
            stack.push(next);
          }
        });
      }
    }
    return keep;
  }

  function analysisLineageHeadMembers(graph, nodeId) {
    var group = (graph.groups || []).filter(function (item) {
      return item.head_id === nodeId;
    })[0];
    if (group) return (group.members || []).slice();
    var artifact = (graph.artifacts || []).filter(function (item) {
      return item.head_id === nodeId;
    })[0];
    if (artifact) return (artifact.members || []).slice();
    return null;
  }

  function analysisLineageContextHeads(graph, keep) {
    var byId = {};
    (graph.nodes || []).forEach(function (node) {
      byId[node.id] = node;
    });
    var changed = true;
    while (changed) {
      changed = false;
      (graph.edges || []).forEach(function (edge) {
        if (!keep[edge.to] || keep[edge.from]) return;
        var source = byId[edge.from];
        if (!source) return;
        if (source.role !== "group-head" && source.role !== "artifact-head") {
          return;
        }
        keep[edge.from] = true;
        changed = true;
      });
    }
  }

  function analysisLineageApplySelection(keep, selectedId) {
    var graph = state.analysisLineage;
    if (!graph) return;
    analysisLineageContextHeads(graph, keep);
    keep[selectedId] = true;
    $$("#analysisLineageCanvas [data-node-id]").forEach(function (element) {
      var id = element.getAttribute("data-node-id");
      element.classList.toggle("is-muted", !keep[id]);
      element.classList.toggle("is-hot", Boolean(keep[id]) && id !== selectedId);
    });
    var groupMembers = {};
    (graph.groups || []).forEach(function (group) {
      groupMembers[group.id] = group.members || [];
    });
    var artifactMembers = {};
    (graph.artifacts || []).forEach(function (artifact) {
      artifactMembers[artifact.id] = artifact.members || [];
    });
    function anyKept(ids) {
      return (ids || []).some(function (id) { return Boolean(keep[id]); });
    }
    $$("#analysisLineageGroups .lineage-group").forEach(function (element) {
      element.classList.toggle(
        "is-muted",
        !anyKept(groupMembers[element.getAttribute("data-group-id")])
      );
    });
    $$("#analysisLineageArtifacts .lineage-artifact").forEach(function (element) {
      element.classList.toggle(
        "is-muted",
        !anyKept(artifactMembers[element.getAttribute("data-artifact-id")])
      );
    });
    $$("#analysisLineageEdges .lineage-edge").forEach(function (element) {
      var on = Boolean(
        keep[element.getAttribute("data-edge-from")] &&
        keep[element.getAttribute("data-edge-to")]
      );
      element.classList.toggle("is-hot", on);
      element.classList.toggle("is-muted", !on);
      element.setAttribute(
        "marker-end", on ? "url(#lineageArrowHot)" : "url(#lineageArrow)"
      );
    });
    $$("#analysisLineageTreeEdges .lineage-tree-edge").forEach(function (element) {
      var on = Boolean(
        keep[element.getAttribute("data-tree-from")] &&
        keep[element.getAttribute("data-tree-to")]
      );
      element.classList.toggle("is-hot", on);
      element.classList.toggle("is-muted", !on);
    });
  }

  export function analysisLineageSelect(nodeId) {
    var graph = state.analysisLineage;
    if (!graph || !nodeId) {
      analysisLineageClearHighlight();
      return;
    }
    state.analysisLineageHighlight = nodeId;
    var members = analysisLineageHeadMembers(graph, nodeId);
    var starts = members ? members.slice() : [nodeId];
    var keep = {};
    starts.forEach(function (start) {
      var branch = analysisLineageLineageSet(graph, start);
      Object.keys(branch).forEach(function (id) {
        keep[id] = true;
      });
    });
    if (members) {
      members.forEach(function (id) { keep[id] = true; });
    }
    analysisLineageApplySelection(keep, nodeId);
  }

  export function analysisLineageSelectMembers(ids, selectedId) {
    if (!state.analysisLineage) return;
    state.analysisLineageHighlight = selectedId || "";
    var keep = {};
    (ids || []).forEach(function (id) { keep[id] = true; });
    analysisLineageApplySelection(keep, selectedId || "");
  }

  export function analysisLineageClearHighlight() {
    state.analysisLineageHighlight = null;
    $$("#analysisLineageCanvas [data-node-id]").forEach(function (element) {
      element.classList.remove("is-muted", "is-hot");
    });
    $$("#analysisLineageGroups .lineage-group, #analysisLineageArtifacts .lineage-artifact")
      .forEach(function (element) {
        element.classList.remove("is-muted");
      });
    $$("#analysisLineageEdges .lineage-edge").forEach(function (element) {
      element.classList.remove("is-muted", "is-hot");
      element.setAttribute("marker-end", "url(#lineageArrow)");
    });
    $$("#analysisLineageTreeEdges .lineage-tree-edge").forEach(function (element) {
      element.classList.remove("is-muted", "is-hot");
    });
    analysisLineageApplySearch();
  }

  export function analysisLineageApplySearch() {
    var query = ($("#analysisLineageSearch").value || "").trim().toLowerCase();
    $$("#analysisLineageCanvas [data-node-id]").forEach(function (element) {
      element.classList.remove("is-hit", "is-muted");
    });
    $$("#analysisLineageGroups .lineage-group, #analysisLineageArtifacts .lineage-artifact")
      .forEach(function (element) {
        element.classList.remove("is-hit", "is-muted");
      });
    $$("#analysisLineageOutline .lo-row").forEach(function (element) {
      element.classList.remove("is-hit", "is-muted");
    });
    if (!query) {
      if (state.analysisLineageHighlight) {
        analysisLineageSelect(state.analysisLineageHighlight);
      }
      return;
    }
    $$("#analysisLineageCanvas [data-node-id]").forEach(function (element) {
      var text = (
        element.getAttribute("data-node-name") + " " +
        (LINEAGE_KIND_LABELS[element.getAttribute("data-node-kind")] || "")
      ).toLowerCase();
      var hit = text.indexOf(query) !== -1;
      element.classList.toggle("is-hit", hit);
    });
    $$("#analysisLineageArtifacts [data-search], #analysisLineageGroups [data-search]")
      .forEach(function (element) {
        element.classList.toggle(
          "is-hit",
          element.getAttribute("data-search").indexOf(query) !== -1
        );
      });
    $$("#analysisLineageOutline .lo-row").forEach(function (element) {
      var text = (
        element.getAttribute("data-node-name") + " " +
        (LINEAGE_KIND_LABELS[element.getAttribute("data-node-kind")] || "")
      ).toLowerCase();
      var hit = text.indexOf(query) !== -1;
      element.classList.toggle("is-hit", hit);
      element.classList.toggle("is-muted", !hit);
    });
  }

  function analysisTableSummary(used, total, statuses) {
    var percent = total ? Math.round(used / total * 100) : 100;
    var cls = used === total ? "chip-ok" : "chip-warn";
    var detail = Object.keys(statuses || {}).map(function (key) {
      return statuses[key] + " " + key;
    }).join(" · ");
    return '<span class="chip ' + cls + '" title="' + escapeHtml(detail) +
      '"><span class="dot"></span>' + percent + "% (" + used + "/" + total +
      ") used</span>";
  }

  function analysisItemMatches(item, kind, query, type, unusedOnly) {
    if (type === "columns" && kind !== "column") return false;
    if (type === "measures" && kind !== "measure") return false;
    if (type === "hierarchies" && kind !== "hierarchy") return false;
    if (type === "functions" && kind !== "function") return false;
    if (unusedOnly && item.status !== "Unused") return false;
    if (!query) return true;
    return [item.name, item.table, item.data_type, item.status, item.reason,
      item.expression, item.levels, kind].join(" ").toLowerCase().indexOf(query) !== -1;
  }

  function analysisTreeGroups() {
    var result = state.analysis;
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var type = getSelectValue("typeAnalyze") || "all";
    var unusedOnly = $("#unusedOnly").checked;
    var map = {};
    var order = [];
    function ensure(name) {
      var key = name || "(No table)";
      if (!map[key]) {
        map[key] = { name: key, columns: [], measures: [], info: null };
        order.push(key);
      }
      return map[key];
    }
    (result.tables || []).forEach(function (table) {
      var group = ensure(table.name);
      group.info = table;
      order = order.filter(function (name) { return name !== group.name; });
      order.push(group.name);
    });
    (result.columns || []).forEach(function (column) {
      ensure(column.table).columns.push(column);
    });
    (result.measures || []).forEach(function (measure) {
      ensure(measure.table).measures.push(measure);
    });
    var groups = order.map(function (name) { return map[name]; });
    groups.forEach(function (group) {
      group.visibleColumns = (type === "measures" ? [] : group.columns.filter(function (column) {
        return analysisItemMatches(column, "column", query, type, unusedOnly);
      }));
      group.visibleMeasures = (type === "columns" ? [] : group.measures.filter(function (measure) {
        return analysisItemMatches(measure, "measure", query, type, unusedOnly);
      }));
    });
    return groups.filter(function (group) {
      return group.visibleColumns.length || group.visibleMeasures.length;
    });
  }

  function analysisChildGroups(item, itemId) {
    var rows = [];
    (item.children || []).forEach(function (group, index) {
      var groupId = itemId + ":g" + index;
      var open = analysisIsOpen(groupId, false, true);
      var groupCells = [];
      for (var i = 0; i < 11; i += 1) groupCells.push("");
      groupCells[0] = analysisNameCell(group.label + " (" + group.count + ")", group.icon || "group", {
        level: 1, toggleId: groupId, open: open
      });
      rows.push({ level: 1, group: true, cells: groupCells });
      if (!open) return;
      (group.rows || []).forEach(function (child) {
        var cells = [];
        for (var j = 0; j < 11; j += 1) cells.push("");
        Object.keys(child.cells || {}).forEach(function (key) {
          cells[Number(key)] = escapeHtml(child.cells[key]);
        });
        cells[0] = analysisNameCell(child.name || "—", child.icon || "group", {
          level: 2, href: child.href || ""
        });
        rows.push({ level: 2, cells: cells });
      });
    });
    return rows;
  }

  function analysisFlatItems() {
    var result = state.analysis;
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var type = getSelectValue("typeAnalyze") || "all";
    var unusedOnly = $("#unusedOnly").checked;
    var items = [];
    (result.columns || []).forEach(function (column) {
      items.push({ kind: "column", data: column });
    });
    (result.measures || []).forEach(function (measure) {
      items.push({ kind: "measure", data: measure });
    });
    (result.hierarchies || []).forEach(function (hierarchy) {
      items.push({ kind: "hierarchy", data: hierarchy });
    });
    (result.functions || []).forEach(function (fn) {
      items.push({ kind: "function", data: fn });
    });
    items = items.filter(function (item) {
      return analysisItemMatches(item.data, item.kind, query, type, unusedOnly);
    });
    var kindByData = new Map();
    items.forEach(function (item) {
      kindByData.set(item.data, item.kind);
    });
    if (state.analysisSort && state.analysisSort !== "default") {
      return analysisSortItems(items.map(function (item) {
        return item.data;
      })).map(function (data) {
        return { kind: kindByData.get(data) || "column", data: data };
      });
    }
    var tableOrder = {};
    (result.tables || []).forEach(function (table, index) {
      tableOrder[table.name] = index;
    });
    var kindOrder = { column: 0, hierarchy: 1, measure: 2, function: 3 };
    return items.slice().sort(function (left, right) {
      var a = tableOrder[left.data.table];
      var b = tableOrder[right.data.table];
      if (a == null) a = 9999;
      if (b == null) b = 9999;
      if (a !== b) return a - b;
      if (left.kind !== right.kind) {
        return (kindOrder[left.kind] || 0) - (kindOrder[right.kind] || 0);
      }
      return 0;
    });
  }

  function analysisFlatRows() {
    var result = state.analysis;
    var items = analysisFlatItems();
    var rows = [];
    var unused = 0;
    var columnCount = 0;
    var measureCount = 0;
    var hierarchyCount = 0;
    var functionCount = 0;
    items.forEach(function (item) {
      if (item.kind === "measure") measureCount += 1;
      else if (item.kind === "hierarchy") hierarchyCount += 1;
      else if (item.kind === "function") functionCount += 1;
      else columnCount += 1;
      var data = item.data;
      var id = "item:" + item.kind + ":" + data.table + ":" + data.name;
      var showExpression = (item.kind === "column" || item.kind === "function") &&
        Boolean(data.expression);
      var expandable = showExpression || (data.children || []).length > 0;
      var open = expandable && analysisIsOpen(id, false, true);
      if (data.status === "Unused") unused += 1;
      rows.push({
        level: 0,
        group: true,
        itemRow: true,
        item: { kind: item.kind, table: data.table || "", name: data.name || "" },
        cells: [
          analysisNameCell(data.name, item.kind === "measure" ? "measure"
            : (item.kind === "hierarchy" ? "group"
              : (item.kind === "function" ? "code" : "column")), {
            level: 0, toggleId: expandable ? id : "", open: open,
            menu: item.kind !== "hierarchy" && item.kind !== "function"
          }),
          item.kind === "measure"
            ? "Measure"
            : (item.kind === "hierarchy"
              ? "Hierarchy"
              : (item.kind === "function"
                ? "User-defined function"
                : (data.type === "Field parameter"
                  ? "Field parameter"
                  : "Column"))),
          escapeHtml(data.table || "—"),
          "Model",
          escapeHtml(data.data_type || "—"),
          item.kind === "measure" ? "0 B" : escapeHtml(data.size || "—"),
          analysisStatusChip(data.status),
          String(data.uses || 0),
          escapeHtml(data.format_string || "—"),
          data.has_error ? "Yes" : "No",
          escapeHtml(data.display_folder || "—")
        ],
        cls: data.status === "Unused" ? "row-unused" : "",
        numCols: [5, 7]
      });
      if (!open) return;
      if (showExpression) rows.push({ kind: "code", code: data.expression, language: "dax" });
      rows = rows.concat(analysisChildGroups(data, id));
    });
    return {
      headers: analysisTreeHeaders(false),
      widths: ["24%", "7%", "9%", "6%", "7%", "7%", "13%", "7%", "8%", "5%", "7%"],
      rows: rows,
      summary: (state.analysisNote ? state.analysisNote + " " : "") + items.length +
        " items · " + columnCount + " columns · " + hierarchyCount +
        " hierarchies · " + measureCount + " measures · " + functionCount +
        " functions · " + unused + " unused" + analysisCoverageSuffix(result)
    };
  }

  function analysisRoleRows() {
    var result = state.analysis || {};
    var roles = result.roles || [];
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var typeFilter = getSelectValue("typeAnalyze") || "all";
    var rows = [];
    var memberCount = 0;
    var permissionCount = 0;

    function roleMatches(role) {
      if (typeFilter === "Member") return false;
      return !query || (role.name + " " + (role.model_permission || "")).toLowerCase().indexOf(query) !== -1;
    }

    function memberMatches(role, member) {
      if (typeFilter === "Role") return false;
      return !query || (
        member.name + " " + (member.member_id || "") + " " + (member.provider || "")
      ).toLowerCase().indexOf(query) !== -1 ||
        (role.name + " " + (role.id || "")).toLowerCase().indexOf(query) !== -1;
    }

    roles.forEach(function (role) {
      var members = (role.members || []).filter(function (member) {
        return memberMatches(role, member);
      });
      if (!roleMatches(role) && !members.length) return;
      var groupId = "role:" + (role.id || role.name);
      var open = analysisIsOpen(groupId, false);
      var status = (role.members || []).length || (role.permissions || []).length
        ? "Active" : "No members";
      rows.push({
        id: groupId,
        level: 0,
        group: true,
        numCols: [7],
        cells: [
          analysisNameCell(role.name, "group", {
            toggleId: groupId,
            open: open,
            level: 0
          }),
          "Role",
          "Model",
          "RLS",
          "—",
          "—",
          status,
          fmtInt((role.members || []).length),
          "—",
          "—",
          escapeHtml(role.model_permission || "—")
        ]
      });
      if (!open) return;
      members.forEach(function (member) {
        memberCount += 1;
        rows.push({
          id: groupId + ":member:" + (member.member_id || member.name),
          level: 1,
          cells: [
            analysisNameCell(member.name, "group", { level: 1 }),
            "Member",
            "Role " + role.name,
            escapeHtml(member.provider || "—"),
            escapeHtml(member.member_type || "—"),
            "—",
            "—",
            "—",
            escapeHtml(member.member_id || "—"),
            "—",
            escapeHtml(member.modified || "—")
          ]
        });
      });
      (role.permissions || []).forEach(function (permission) {
        permissionCount += 1;
        rows.push({
          id: groupId + ":permission:" + (permission.table || ""),
          level: 1,
          cells: [
            analysisNameCell(permission.table || "—", "table", { level: 1 }),
            "Table permission",
            "Role " + role.name,
            "RLS",
            "—",
            "—",
            permission.has_ols ? "OLS" : "—",
            "—",
            escapeHtml(analysisTruncate(permission.expression || "—", 90)),
            "—",
            "—"
          ]
        });
      });
    });

    return {
      headers: analysisTreeHeaders(false),
      widths: ["24%", "7%", "9%", "6%", "7%", "7%", "13%", "7%", "8%", "5%", "7%"],
      rows: rows,
      summary: fmtInt(roles.length) + " " + "roles" + " · " +
        fmtInt(memberCount) + " " + "members shown" + " · " +
        fmtInt(permissionCount) + " " + "table permissions"
    };
  }

  function analysisTreeHeaders(tablesMode) {
    if (tablesMode) {
      return [
        { label: "Name" }, { label: "Type" }, { label: "Table" },
        { label: "Source" }, { label: "Data type" }, { label: "Size", num: true },
        { label: "Status" }, { label: "# used", num: true },
        { label: "Mode" }, { label: "Partitions", num: true }
      ];
    }
    return [
      { label: "Name", key: "name" }, { label: "Type", key: "type" },
      { label: "Table / page", key: "table" }, { label: "Source" },
      { label: "Data type", key: "data_type" },
      { label: "Size", key: "size", num: true },
      { label: "Status", key: "status" },
      { label: "# used", key: "uses", num: true },
      { label: "Format string", key: "format_string" },
      { label: "Has error", key: "has_error" },
      { label: "Display folder", key: "display_folder" }
    ];
  }

  function analysisTreeView() {
    var result = state.analysis;
    var groups = analysisTreeGroups();
    var rows = [];
    var itemCount = 0;
    var unused = 0;
    groups.forEach(function (group) {
      var info = group.info || {};
      var fallbackItems = group.columns.concat(group.measures);
      var totalItems = info.total_items != null
        ? info.total_items : fallbackItems.length;
      var usedItems = info.used_items != null
        ? info.used_items
        : fallbackItems.filter(function (item) { return item.status !== "Unused"; }).length;
      var statuses = info.statuses || fallbackItems.reduce(function (acc, item) {
        acc[item.status] = (acc[item.status] || 0) + 1;
        return acc;
      }, {});
      var size = info.size || analysisFmtBytes(info.size_bytes || 0);
      var tableId = "tbl:" + group.name;
      var tableOpen = analysisIsOpen(tableId, false);
      rows.push({
        level: 0,
        group: true,
        item: { kind: "table", table: group.name, name: group.name },
        cells: [
          analysisNameCell(group.name, "table", {
            level: 0, toggleId: tableId, open: tableOpen, menu: true
          }),
          "Table", "—", "Model", "—", escapeHtml(size || "—"),
          analysisTableSummary(usedItems, totalItems, statuses), String(usedItems),
          escapeHtml(info.storage_mode || "—"), String(info.partition_count || 0)
        ],
        numCols: [5, 7, 9]
      });
      if (!tableOpen) return;
      if (group.visibleMeasures.length) {
        var measureId = tableId + ":m";
        var measureOpen = analysisIsOpen(measureId, false);
        rows.push({
          level: 1,
          group: true,
          cells: [
            analysisNameCell("Measure (" + group.visibleMeasures.length + ")", "group", {
              level: 1, toggleId: measureId, open: measureOpen
            }),
            "Grup", escapeHtml(group.name), "Model", "—", "—", "—", "—", "—", "—"
          ]
        });
        if (measureOpen) {
          group.visibleMeasures.forEach(function (measure) {
            itemCount += 1;
            if (measure.status === "Unused") unused += 1;
            rows.push({
              level: 2,
              itemRow: true,
              item: { kind: "measure", table: measure.table || "", name: measure.name || "" },
              cells: [
                analysisNameCell(measure.name, "measure", { level: 2, menu: true }),
                "Measure", escapeHtml(group.name), "Model", "DAX", "0 B",
                analysisStatusChip(measure.status), String(measure.uses || 0), "—", "—"
              ],
              cls: measure.status === "Unused" ? "row-unused" : "",
              numCols: [5, 7]
            });
          });
        }
      }
      if (group.visibleColumns.length) {
        var columnId = tableId + ":c";
        var columnOpen = analysisIsOpen(columnId, false);
        rows.push({
          level: 1,
          group: true,
          cells: [
            analysisNameCell("Columns (" + group.visibleColumns.length + ")", "group", {
              level: 1, toggleId: columnId, open: columnOpen
            }),
            "Grup", escapeHtml(group.name), "Model", "—", "—", "—", "—", "—", "—"
          ]
        });
        if (columnOpen) {
          group.visibleColumns.forEach(function (column) {
            itemCount += 1;
            if (column.status === "Unused") unused += 1;
            rows.push({
              level: 2,
              itemRow: true,
              item: { kind: "column", table: column.table || "", name: column.name || "" },
              cells: [
                analysisNameCell(column.name, "column", { level: 2, menu: true }),
                "Column", escapeHtml(group.name), "Model",
                escapeHtml(column.data_type || "—"), escapeHtml(column.size || "—"),
                analysisStatusChip(column.status), String(column.uses || 0), "—", "—"
              ],
              cls: column.status === "Unused" ? "row-unused" : "",
              numCols: [5, 7]
            });
          });
        }
      }
    });
    return {
      headers: analysisTreeHeaders(true),
      widths: ["27%", "7%", "8%", "8%", "8%", "6%", "15%", "7%", "7%", "7%"],
      rows: rows,
      summary: (state.analysisNote ? state.analysisNote + " " : "") +
        itemCount + " items · " + groups.length + " tables · " +
        unused + " unused" + analysisCoverageSuffix(result)
    };
  }

  function analysisFilteredRelationships() {
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var type = getSelectValue("typeAnalyze") || "all";
    return ((state.analysis && state.analysis.relationships) || []).filter(function (rel) {
      if (type === "active" && !rel.is_active) return false;
      if (type === "inactive" && rel.is_active) return false;
      if (!query) return true;
      return [rel.name, rel.label, rel.from_table, rel.from_column, rel.to_table,
        rel.to_column, rel.type, rel.cross, rel.cardinality, rel.auto, rel.status]
        .join(" ").toLowerCase().indexOf(query) !== -1;
    });
  }

  function analysisRelationshipRows() {
    var items = analysisSortItems(analysisFilteredRelationships());
    var rows = items.map(function (rel) {
      var fromText = (rel.from_table || "—") + "[" + (rel.from_column || "—") + "]";
      var toText = (rel.to_table || "—") + "[" + (rel.to_column || "—") + "]";
      return {
        level: 0,
        cls: rel.is_active ? "" : "row-unused",
        cells: [
          analysisNameCell(rel.label || rel.name || "(relationship)", "link", { level: 0 }),
          escapeHtml(rel.type || "—"),
          escapeHtml(rel.cross || "—"),
          escapeHtml(rel.cardinality || "—"),
          rel.is_active
            ? '<span class="chip chip-ok"><span class="dot"></span>' + "Active" + "</span>"
            : '<span class="chip chip-idle"><span class="dot"></span>' + "Inactive" + "</span>",
          escapeHtml(rel.auto || "No"),
          String(rel.used || 0),
          '<span class="mono-trunc" title="' + escapeHtml(fromText) + '">' +
            escapeHtml(fromText) + "</span>",
          '<span class="mono-trunc" title="' + escapeHtml(toText) + '">' +
            escapeHtml(toText) + "</span>"
        ],
        numCols: [6]
      };
    });
    var active = items.filter(function (rel) { return rel.is_active; }).length;
    return {
      headers: [
        { label: "Relationship name", key: "label" }, { label: "Type", key: "type" },
        { label: "Cross filter", key: "cross" },
        { label: "Cardinality", key: "cardinality" },
        { label: "Status", key: "status" },
        {
          label: "Auto create", key: "auto",
          hint: "Power BI automatic relationship (AutoDetected_ name or GUID)"
        },
        {
          label: "# used", key: "used", num: true,
          hint: "Number of model objects that depend on the relationship (DMV DISCOVER_CALC_DEPENDENCY)"
        },
        { label: "From column", key: "from_column" },
        { label: "To column", key: "to_column" }
      ],
      widths: ["28%", "7%", "8%", "9%", "11%", "8%", "7%", "11%", "11%"],
      rows: rows,
      summary: items.length + " relationships · " + active + " active · " +
        (items.length - active) + " inactive" + analysisCoverageSuffix(state.analysis)
    };
  }

  function analysisReportStatus(status) {
    var map = {
      ok: ["chip-ok", "Succeeded"],
      failed: ["chip-danger", "Failed"],
      skipped: ["chip-idle", "Skipped"],
      cached: ["chip-idle", "From cache"],
      unsupported: ["chip-idle", "Unsupported"],
      inaccessible: ["chip-warn", "Inaccessible"],
      personal: ["chip-warn", "Personal"],
      app: ["chip-warn", "App"]
    };
    var item = map[status] || ["chip-idle", status || "—"];
    return '<span class="chip ' + item[0] + '"><span class="dot"></span>' +
      escapeHtml(item[1]) + "</span>";
  }

  function analysisLoadReportDetail(reportId) {
    if (!reportId || state.reportDetail[reportId] || state.reportLoading[reportId]) return;
    var datasetId = getSelectValue("modelSelect");
    if (!datasetId || !app.apiReady()) return;
    state.reportLoading[reportId] = true;
    app.api().get(
      "/api/analysis/report-detail?dataset_id=" + encodeURIComponent(datasetId) +
      "&report_id=" + encodeURIComponent(reportId)
    ).then(function (data) {
      state.reportDetail[reportId] = data;
      state.reportLoading[reportId] = false;
      analysisRender();
    }).catch(function (error) {
      state.reportLoading[reportId] = false;
      app.addLog("Report details could not be loaded: " + error.message, "warn");
      analysisRender();
    });
  }

  function analysisReportCells(
    nameHtml, type, source, visual, pages, theme, hidden, extra
  ) {
    extra = extra || {};
    var broken = extra.broken == null ? "-" : fmtInt(extra.broken);
    var score = "-";
    if (extra.score != null) {
      var scoreClass = extra.score >= 80 ? "is-good"
        : (extra.score >= 50 ? "is-warn" : "is-low");
      var title = extra.scoreTitle
        ? ' title="' + escapeHtml(extra.scoreTitle) + '"' : "";
      score = '<span class="health-score ' + scoreClass + '"' + title + ">" +
        fmtInt(extra.score) + "</span>";
    }
    return [
      nameHtml,
      escapeHtml(type || "") +
        (hidden ? ' <span class="chip chip-idle">Hidden</span>' : ""),
      escapeHtml(source || ""),
      visual == null ? "" : String(visual),
      broken,
      "-",
      pages == null ? "-" : String(pages),
      theme ? '<span title="' + escapeHtml(theme) + '">' + escapeHtml(theme) + "</span>" : "-",
      score
    ];
  }

  var HEALTH_RULES = {
    column_error: "Column has an error",
    measure_error: "Measure has an error",
    unused_table: "Unused table",
    isolated_table: "Table has no relationship",
    bidirectional_relationship: "Bidirectional relationship",
    many_to_many_relationship: "Many-to-many relationship",
    inactive_relationship: "Inactive relationship",
    auto_relationship: "Auto-detected relationship",
    large_dictionary: "Large column dictionary",
    unused_calculated_column: "Unused calculated column",
    page_without_visuals: "Page has no visuals",
    hidden_page_with_visuals: "Hidden page with visuals",
    missing_theme: "Report has no theme",
    broken_visual: "Visual has unmapped fields"
  };

  function analysisHealthRuleLabel(rule) {
    return (HEALTH_RULES[rule] || rule);
  }

  var HEALTH_RULE_HELP = [
    {
      rule: "column_error",
      severity: "critical",
      description: "The model reports an error for this column.",
      source: "TMSCHEMA_COLUMNS (ErrorMessage)",
      action: "Open Column details and fix the DAX or data type error in Power BI Desktop, then run the analysis again."
    },
    {
      rule: "measure_error",
      severity: "critical",
      description: "The model reports an error for this measure.",
      source: "TMSCHEMA_MEASURES (ErrorMessage)",
      action: "Open Measure details and fix the DAX expression in Power BI Desktop, then run the analysis again."
    },
    {
      rule: "unused_table",
      severity: "warning",
      description: "Every column and measure in this table has the status Not used.",
      source: "Column and measure verdicts from this analysis",
      action: "Confirm the table is not needed by any report or model object before removing it."
    },
    {
      rule: "isolated_table",
      severity: "warning",
      description: "This table has no relationship to any other table.",
      source: "TMSCHEMA_RELATIONSHIPS",
      action: "Check whether the table should be connected to the model or is intentionally standalone."
    },
    {
      rule: "bidirectional_relationship",
      severity: "warning",
      description: "This relationship filters in both directions.",
      source: "TMSCHEMA_RELATIONSHIPS (CrossFilteringBehavior)",
      action: "Keep bidirectional filtering only where required; otherwise switch it to a single direction."
    },
    {
      rule: "many_to_many_relationship",
      severity: "warning",
      description: "Both sides of this relationship have many-side cardinality.",
      source: "TMSCHEMA_RELATIONSHIPS (FromCardinality and ToCardinality)",
      action: "Review the model design; many-to-many relationships often need a bridge table."
    },
    {
      rule: "inactive_relationship",
      severity: "info",
      description: "This relationship is inactive.",
      source: "TMSCHEMA_RELATIONSHIPS (IsActive)",
      action: "Confirm it is used with USERELATIONSHIP; remove it if it is no longer needed."
    },
    {
      rule: "auto_relationship",
      severity: "info",
      description: "Power BI created this relationship automatically.",
      source: "Relationship name or RelationshipIsAuto",
      action: "Review the name, columns, and cardinality; recreate it explicitly if it should be part of the model."
    },
    {
      rule: "large_dictionary",
      severity: "warning",
      description: "The column dictionary takes at least half of the column size.",
      source: "DISCOVER_STORAGE_TABLE_COLUMNS (DICTIONARY_SIZE)",
      threshold: "At least 50% of column size and at least 1 MB.",
      action: "Confirm the column is required; reduce distinct text values, change the data type, or hide it from report authors."
    },
    {
      rule: "unused_calculated_column",
      severity: "info",
      description: "This calculated column is not used and still consumes memory.",
      source: "Column verdict and VertiPaq storage sizes",
      action: "Remove the calculated column if no report, relationship, or model object needs it."
    },
    {
      rule: "page_without_visuals",
      severity: "warning",
      description: "This report page has no visuals.",
      source: "Report definition (usage_page.visual_count)",
      action: "Remove the empty page or add the missing content."
    },
    {
      rule: "hidden_page_with_visuals",
      severity: "info",
      description: "This page is hidden but still contains visuals.",
      source: "Report definition (page visibility)",
      action: "Confirm it is a tooltip or navigation page; otherwise unhide or remove it."
    },
    {
      rule: "missing_theme",
      severity: "info",
      description: "The report does not use a custom theme.",
      source: "Report definition (theme)",
      action: "Optional: apply a theme for consistent formatting. This is informational only."
    },
    {
      rule: "broken_visual",
      severity: "critical",
      description: "The visual references fields that cannot be mapped to the model.",
      source: "Report scan (usage_unresolved)",
      action: "Open Report results, inspect the visual, and fix or remove the broken field references."
    }
  ];

  function analysisHealthRulesMarkup() {
    var groups = [
      ["critical", "Critical"],
      ["warning", "Warning"],
      ["info", "Info"]
    ];
    var parts = [];
    groups.forEach(function (group) {
      var items = HEALTH_RULE_HELP.filter(function (item) {
        return item.severity === group[0];
      });
      if (!items.length) return;
      var chipClass = group[0] === "critical" ? "chip-danger"
        : (group[0] === "warning" ? "chip-warn" : "chip-info");
      parts.push(
        '<section class="health-rule-group"><h3 class="health-rule-group-title">' +
        '<span class="chip ' + chipClass + '"><span class="dot"></span>' +
        escapeHtml((group[1])) + "</span>" +
        '<span class="helper">' + fmtInt(items.length) + " " + "rules" +
        "</span></h3>"
      );
      items.forEach(function (item) {
        parts.push(
          '<article class="health-rule" id="healthRule-' + escapeHtml(item.rule) +
          '"><div class="health-rule-head"><h4>' +
          escapeHtml(analysisHealthRuleLabel(item.rule)) + "</h4></div>" +
          '<p class="health-rule-desc">' + escapeHtml((item.description)) + "</p>" +
          '<dl class="health-rule-meta">' +
          "<dt>" + escapeHtml("Source") + "</dt><dd>" +
          escapeHtml((item.source)) + "</dd>" +
          (item.threshold
            ? "<dt>" + escapeHtml("Threshold") + "</dt><dd>" +
              escapeHtml((item.threshold)) + "</dd>"
            : "") +
          "<dt>" + escapeHtml("Suggested action") + "</dt><dd>" +
          escapeHtml((item.action)) + "</dd></dl></article>"
        );
      });
      parts.push("</section>");
    });
    parts.push(
      '<section class="health-rule-group health-rule-group--score">' +
      '<h3 class="health-rule-group-title"><span class="chip chip-accent">' +
      escapeHtml("Practice score") + "</span></h3>" +
      '<p class="health-rule-desc">' +
      escapeHtml("Score starts at 100 for reports with status ok and subtracts:") +
      "</p><ul class=\"health-rule-formula\">" +
      "<li>" + escapeHtml("5 points per visual with unmapped fields (max 30).") + "</li>" +
      "<li>" + escapeHtml("3 points per page without visuals (max 15).") + "</li>" +
      "<li>" + escapeHtml("1 point per unmapped field (max 20).") + "</li>" +
      "</ul><p class=\"health-rule-desc\">" +
      escapeHtml("Theme and hidden pages do not reduce the score because both can be intentional.") +
      "</p></section>"
    );
    return parts.join("");
  }

  export function analysisOpenHealthRules(rule) {
    var dialog = $("#analysisHealthRulesDialog");
    if (!dialog) return;
    $("#analysisHealthRulesBody").innerHTML = analysisHealthRulesMarkup();
    var target = rule ? $("#healthRule-" + rule) : null;
    if (target) {
      target.classList.add("is-highlight");
      target.scrollIntoView({ block: "start" });
    }
    if (dialog.open) dialog.close();
    dialog.showModal();
    if (target) {
      window.setTimeout(function () { target.scrollIntoView({ block: "start" }); }, 0);
    }
  }

  function analysisPracticeTitle(report) {
    var practice = ((state.analysis && state.analysis.health) || {}).practice || {};
    var entry = report && report.report_id ? practice[report.report_id] : null;
    if (!entry || !entry.checks || !entry.checks.length) return "";
    return entry.checks.map(function (check) {
      return analysisHealthRuleLabel(check.rule) + ": " + check.count +
        " (-" + check.points + ")";
    }).join(" · ");
  }

  function analysisFilterRows(entry, baseId, level, sourceName, detail) {
    var rows = [];
    var filterId = baseId + ":filter";
    var open = analysisIsOpen(filterId, false, true);
    var hasColumns = (entry.columns || []).length > 0;
    rows.push({
      level: level,
      group: hasColumns,
      cells: analysisReportCells(
        analysisNameCell(entry.name || entry.detail || "Filter", "filter", {
          level: level, toggleId: hasColumns ? filterId : "", open: open
        }),
        entry.type || "Filter",
        sourceName,
        null, null, null
      )
    });
    if (!hasColumns || !open) return rows;
    var columnsId = filterId + ":columns";
    var columnsOpen = analysisIsOpen(columnsId, false, true);
    rows.push({
      level: level + 1,
      group: true,
      cells: analysisReportCells(
        analysisNameCell("Columns used (" + entry.columns.length + ")", "table", {
          level: level + 1, toggleId: columnsId, open: columnsOpen
        }),
        "", "", null, null, null
      )
    });
    if (!columnsOpen) return rows;
    entry.columns.forEach(function (column) {
      rows.push({
        level: level + 2,
        cells: analysisReportCells(
          analysisNameCell(
            (column.table ? column.table + "[" + column.field + "]" : column.field),
            "column", { level: level + 2 }
          ),
          "Column", column.table || "—", null, null, null
        )
      });
    });
    return rows;
  }

  function analysisPageRows(page, reportName, baseId, level) {
    var rows = [];
    var pageId = baseId + ":page:" + (page.page_id || page.page_name);
    var open = analysisIsOpen(pageId, false, true);
    rows.push({
      level: level,
      group: true,
      cells: analysisReportCells(
        analysisNameCell(page.page_name || page.page_id || "(page)", "page", {
          level: level, toggleId: pageId, open: open, hidden: Boolean(page.is_hidden)
        }),
        "Page", reportName, page.visual_count || 0, null, null, Boolean(page.is_hidden)
      )
    });
    if (!open) return rows;

    var visuals = page.visuals || [];
    var visualsId = pageId + ":visuals";
    var visualsOpen = analysisIsOpen(visualsId, false, true);
    if (visuals.length) {
      rows.push({
        level: level + 1,
        group: true,
        cells: analysisReportCells(
          analysisNameCell("Visuals (" + visuals.length + ")", "visual", {
            level: level + 1, toggleId: visualsId, open: visualsOpen
          }),
          "", "", null, null, null
        )
      });
      if (visualsOpen) {
        visuals.forEach(function (visual) {
          var visualId = visualsId + ":" + (visual.visual_id || visual.visual_title);
          var visualOpen = analysisIsOpen(visualId, false, true);
          var expandable = (visual.artifacts || []).length > 0 ||
            (visual.filters || []).length > 0;
          rows.push({
            level: level + 2,
            group: expandable,
            cells: analysisReportCells(
              analysisNameCell(visual.visual_title || visual.visual_id || "(visual)", "visual", {
                level: level + 2, toggleId: expandable ? visualId : "", open: visualOpen,
                hidden: Boolean(visual.is_hidden)
              }),
              visual.visual_type || "visual",
              page.page_name || reportName, null, null, null, Boolean(visual.is_hidden)
            )
          });
          if (!expandable || !visualOpen) return;
          var artifacts = visual.artifacts || [];
          if (artifacts.length) {
            var artifactsId = visualId + ":artifacts";
            var artifactsOpen = analysisIsOpen(artifactsId, false, true);
            rows.push({
              level: level + 3,
              group: true,
              cells: analysisReportCells(
                analysisNameCell("Artifacts used (" + artifacts.length + ")", "table", {
                  level: level + 3, toggleId: artifactsId, open: artifactsOpen
                }),
                "", "", null, null, null
              )
            });
            if (artifactsOpen) {
              artifacts.forEach(function (artifact) {
                rows.push({
                  level: level + 4,
                  cells: analysisReportCells(
                    analysisNameCell(
                      artifact.table
                        ? artifact.table + "[" + artifact.field + "]"
                        : artifact.field,
                      artifact.kind === "Measure" ? "measure" : "column",
                      { level: level + 4 }
                    ),
                    artifact.kind || "Column",
                    artifact.table || "—", null, null, null
                  )
                });
              });
            }
          }
          var filters = visual.filters || [];
          if (filters.length) {
            var filtersId = visualId + ":filters";
            var filtersOpen = analysisIsOpen(filtersId, false, true);
            rows.push({
              level: level + 3,
              group: true,
              cells: analysisReportCells(
                analysisNameCell("Visual level filters (" + filters.length + ")", "filter", {
                  level: level + 3, toggleId: filtersId, open: filtersOpen
                }),
                "", "", null, null, null
              )
            });
            if (filtersOpen) {
              filters.forEach(function (entry) {
                rows = rows.concat(
                  analysisFilterRows(entry, filtersId, level + 4, page.page_name || reportName)
                );
              });
            }
          }
        });
      }
    }

    var pageFilters = page.page_filters || [];
    if (pageFilters.length) {
      var pageFiltersId = pageId + ":pagefilters";
      var pageFiltersOpen = analysisIsOpen(pageFiltersId, false, true);
      rows.push({
        level: level + 1,
        group: true,
        cells: analysisReportCells(
          analysisNameCell("Page level filters (" + pageFilters.length + ")", "filter", {
            level: level + 1, toggleId: pageFiltersId, open: pageFiltersOpen
          }),
          "", "", null, null, null
        )
      });
      if (pageFiltersOpen) {
        pageFilters.forEach(function (entry) {
          rows = rows.concat(
            analysisFilterRows(entry, pageFiltersId, level + 2, page.page_name || reportName)
          );
        });
      }
    }
    return rows;
  }

  function analysisReportRows() {
    var result = state.analysis;
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var type = getSelectValue("typeAnalyze") || "all";
    var rows = [];
    var reportCount = 0;
    var pageTotal = 0;
    var visualTotal = 0;
    var fieldTotal = 0;

    ((result && result.reports) || []).forEach(function (report, index) {
      var reportId = report.report_id || String(index);
      var reportName = report.report_name || report.report_id || "(report)";
      var allPages = report.pages || [];
      var rootMatch = !query || [
        reportName, report.workspace_name, report.format, report.status, report.message
      ].join(" ").toLowerCase().indexOf(query) !== -1;
      var visiblePages = allPages.filter(function (page) {
        var used = (page.field_count || 0) > 0 || (page.visual_count || 0) > 0;
        if (type === "used" && !used) return false;
        if (type === "unused" && used) return false;
        if (!query) return true;
        return [page.page_name, reportName, report.workspace_name]
          .join(" ").toLowerCase().indexOf(query) !== -1;
      });
      if (query && !rootMatch && !visiblePages.length) return;
      if ((type === "used" || type === "unused") && !visiblePages.length) return;

      reportCount += 1;
      visiblePages.forEach(function (page) {
        pageTotal += 1;
        visualTotal += page.visual_count || 0;
        fieldTotal += page.field_count || 0;
      });

      var rootId = "report:" + reportId;
      var rootOpen = analysisIsOpen(rootId, false, true);
      var isApp = /\[App\]/i.test(reportName);
      var reportCell = analysisNameCell(reportName, "report", {
        level: 0, toggleId: rootId, open: rootOpen,
        href: analysisReportUrl(report.workspace_id, report.report_id)
      });
      rows.push({
        level: 0,
        group: true,
        cells: analysisReportCells(
          reportCell,
          isApp ? "Apps" : "Local report", report.format || report.workspace_name || "—",
          report.visual_count || 0, report.page_count || 0, report.theme || "—",
          undefined,
          {
            broken: report.status === "ok" ? report.broken_visuals : null,
            score: report.health_score,
            scoreTitle: analysisPracticeTitle(report)
          }
        )
      });
      if (!rootOpen) return;
      analysisLoadReportDetail(report.report_id);
      var detail = state.reportDetail[report.report_id];
      if (!detail) {
        rows.push({
          kind: "html",
          cls: "analysis-sub",
          html: '<span class="helper">' +
            (state.reportLoading[report.report_id] ? "Loading report details…" : "Details are not available yet.") +
            "</span>"
        });
        return;
      }
      var detailPages = null;
      var detailById = {};
      (detail.pages || []).forEach(function (page) {
        detailById[page.page_id] = page;
      });
      detailPages = visiblePages.map(function (page) {
        return detailById[page.page_id] || page;
      });

      var hiddenPages = detailPages.filter(function (page) { return page.is_hidden; });
      var normalPages = detailPages.filter(function (page) { return !page.is_hidden; });

      if (hiddenPages.length) {
        var hiddenId = rootId + ":hidden";
        var hiddenOpen = analysisIsOpen(hiddenId, false, true);
        var hiddenVisuals = hiddenPages.reduce(function (sum, page) {
          return sum + (page.visual_count || 0);
        }, 0);
        rows.push({
          level: 1,
          group: true,
          cells: analysisReportCells(
            analysisNameCell("Hidden pages", "hidden", {
              level: 1, toggleId: hiddenId, open: hiddenOpen
            }),
            "", "", null, null, null
          )
        });
        if (hiddenOpen) {
          hiddenPages.forEach(function (page) {
            rows = rows.concat(analysisPageRows(page, reportName, hiddenId, 2));
          });
        }
      }

      var pagesId = rootId + ":pages";
      var pagesOpen = analysisIsOpen(pagesId, false, true);
      var normalVisuals = normalPages.reduce(function (sum, page) {
        return sum + (page.visual_count || 0);
      }, 0);
      rows.push({
        level: 1,
        group: true,
        cells: analysisReportCells(
          analysisNameCell("Pages", "group", {
            level: 1, toggleId: pagesId, open: pagesOpen
          }),
          "", "", null, null, null
        )
      });
      if (pagesOpen) {
        normalPages.forEach(function (page) {
          rows = rows.concat(analysisPageRows(page, reportName, pagesId, 2));
        });
      }

      var reportFilters = detail.report_filters || [];
      if (reportFilters.length) {
        var reportFiltersId = rootId + ":reportfilters";
        var reportFiltersOpen = analysisIsOpen(reportFiltersId, false, true);
        rows.push({
          level: 1,
          group: true,
          cells: analysisReportCells(
            analysisNameCell("Report level filters (" + reportFilters.length + ")", "filter", {
              level: 1, toggleId: reportFiltersId, open: reportFiltersOpen
            }),
            "", "", null, null, null
          )
        });
        if (reportFiltersOpen) {
          reportFilters.forEach(function (entry) {
            rows = rows.concat(
              analysisFilterRows(entry, reportFiltersId, 2, reportName)
            );
          });
        }
      }
      if (!normalPages.length && !hiddenPages.length) {
        rows.push({
          kind: "html",
          cls: "analysis-sub",
          html: '<span class="helper">' +
            "No pages could be read from this report." + "</span>"
        });
      }
    });

    return {
      headers: [
        { label: "Name" }, { label: "Type" }, { label: "Source" },
        { label: "Visuals", num: true }, { label: "Broken visuals", num: true },
        { label: "Views", num: true }, { label: "Pages", num: true },
        { label: "Theme" }, { label: "Practice score" }
      ],
      widths: ["30%", "10%", "17%", "7%", "8%", "6%", "7%", "6%", "9%"],
      rows: rows,
      summary: reportCount + " reports · " + pageTotal + " pages · " +
        visualTotal + " visuals · " + fieldTotal + " fields" +
        analysisCoverageSuffix(result)
    };
  }

  function analysisDaxRows() {
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var type = getSelectValue("typeAnalyze") || "all";
    var rows = [];
    ((state.analysis && state.analysis.measures) || []).forEach(function (measure) {
      rows.push({
        kind: "measure",
        name: measure.name,
        table: measure.table,
        type: measure.is_hidden ? "Measure (hidden)" : "Measure",
        status: measure.status,
        uses: measure.uses || 0,
        has_error: Boolean(measure.has_error),
        source: "Measure",
        expression: measure.expression || "",
        reason: measure.reason || ""
      });
    });
    analysisCalculatedColumns().forEach(function (column) {
      rows.push({
        kind: "column",
        name: column.name,
        table: column.table,
        type: "Calculated column",
        status: column.status,
        uses: column.uses || 0,
        has_error: Boolean(column.has_error),
        source: "Column",
        expression: column.expression || "",
        reason: column.reason || ""
      });
    });
    if (type !== "all") {
      rows = rows.filter(function (row) {
        return row.type === type || row.type.indexOf(type + " ") === 0;
      });
    }
    if (query) {
      rows = rows.filter(function (row) {
        return [row.name, row.table, row.type, row.status, row.expression]
          .join(" ").toLowerCase().indexOf(query) !== -1;
      });
    }
    var unused = rows.filter(function (row) { return row.status === "Unused"; }).length;
    rows = analysisSortItems(rows);
    var viewRows = [];
    rows.forEach(function (row) {
      var id = "dax:" + row.kind + ":" + row.table + ":" + row.name;
      var open = analysisIsOpen(id, false);
      viewRows.push({
        cells: [
          analysisNameCell(row.name, row.kind === "measure" ? "measure" : "column", {
            level: 0, toggleId: row.expression ? id : "", open: open
          }),
          escapeHtml(row.table),
          escapeHtml(row.type),
          analysisStatusChip(row.status),
          String(row.uses),
          row.has_error ? "Yes" : "No",
          escapeHtml(row.source)
        ],
        numCols: [4]
      });
      if (open && row.expression) viewRows.push({ kind: "code", code: row.expression, language: "dax" });
    });
    return {
      headers: [
        { label: "Name / expression", key: "name" }, { label: "Table", key: "table" },
        { label: "Type", key: "type" }, { label: "Status", key: "status" },
        { label: "# used", key: "uses", num: true },
        { label: "Error", key: "has_error" }, { label: "Source", key: "source" }
      ],
      widths: ["37%", "13%", "11%", "15%", "8%", "6%", "10%"],
      rows: viewRows,
      summary: rows.length + " expressions · " + unused + " unused" +
        analysisCoverageSuffix(state.analysis)
    };
  }

  function analysisMRows() {
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var type = getSelectValue("typeAnalyze") || "all";
    var items = ((state.analysis && state.analysis.m_queries) || []).filter(function (row) {
      if (type !== "all" && row.kind !== type) return false;
      if (!query) return true;
      return [row.name, row.kind, row.source, row.expression, row.detail]
        .join(" ").toLowerCase().indexOf(query) !== -1;
    });
    items = analysisSortItems(items);
    var viewRows = [];
    items.forEach(function (row) {
      var id = "m:" + row.kind + ":" + row.name;
      var open = analysisIsOpen(id, false);
      var warning = row.warning
        ? '<span class="chip chip-warn"><span class="dot"></span>' + escapeHtml(row.warning) + "</span>"
        : "—";
      viewRows.push({
        cells: [
          analysisNameCell(row.name, row.kind === "Table" ? "query" : "code", {
            level: 0, toggleId: row.expression ? id : "", open: open
          }),
          escapeHtml(row.kind || "—"),
          escapeHtml([row.source, row.detail].filter(Boolean).join(" · ") || "—"),
          warning
        ]
      });
      if (open && row.expression) viewRows.push({ kind: "code", code: row.expression, language: "m" });
    });
    return {
      headers: [
        { label: "Name", key: "name" }, { label: "Type", key: "kind" },
        { label: "Source", key: "source" }, { label: "Warning", key: "warning" }
      ],
      widths: ["35%", "13%", "37%", "15%"],
      rows: viewRows,
      summary: items.length + " queries · " +
        items.filter(function (row) { return row.kind === "Table"; }).length +
        " tables" + analysisCoverageSuffix(state.analysis)
    };
  }

  function analysisHealthDetail(item) {
    var metrics = item.metrics || {};
    var parts = [];
    if (item.detail) parts.push(item.detail);
    if (item.rule === "unused_table" || item.rule === "isolated_table") {
      parts.push(fmtInt(metrics.columns || 0) + " " + "columns" +
        " · " + fmtInt(metrics.measures || 0) + " " + "measures");
    } else if (item.rule === "large_dictionary") {
      parts.push("dictionary" + " " +
        Math.round(Number(metrics.share || 0) * 100) + "% · " +
        analysisFmtBytes(metrics.dictionary || 0));
    } else if (item.rule === "hidden_page_with_visuals") {
      parts.push(fmtInt(metrics.visuals || 0) + " " + "visuals");
    } else if (item.rule === "broken_visual") {
      parts.push(fmtInt(metrics.unresolved || 0) + " " + "unmapped fields");
    }
    return parts.filter(Boolean).join(" · ") || "—";
  }

  function analysisHealthRows() {
    var health = ((state.analysis && state.analysis.health) || {});
    var items = health.items || [];
    var counts = health.counts || {};
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var severity = getSelectValue("typeAnalyze") || "all";
    items = items.filter(function (item) {
      if (severity !== "all" && item.severity !== severity) return false;
      if (!query) return true;
      return [
        item.rule, analysisHealthRuleLabel(item.rule), item.object, item.detail,
        item.report_name, item.page_name, item.table, item.name
      ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
    items = analysisSortItems(items);
    var viewRows = items.map(function (item) {
      var severityClass = item.severity === "critical" ? "chip-danger"
        : (item.severity === "warning" ? "chip-warn" : "chip-info");
      var severityLabel = item.severity === "critical" ? "Critical"
        : (item.severity === "warning" ? "Warning" : "Info");
      var icons = {
        column: "column", measure: "measure", table: "table", report: "report",
        page: "page", visual: "visual", relationship: "link"
      };
      var isModelItem = item.kind === "column" || item.kind === "measure" ||
        item.kind === "table";
      var isTable = item.kind === "table";
      var row = {
        level: 0,
        cells: [
          '<span class="chip ' + severityClass + '"><span class="dot"></span>' +
            escapeHtml((severityLabel)) + "</span>",
          escapeHtml((item.area === "report" ? "Report" : "Model")),
          '<span class="health-rule-cell">' +
            escapeHtml(analysisHealthRuleLabel(item.rule)) +
            '<button type="button" class="health-rule-info" data-health-rule-info="' +
            escapeHtml(item.rule) + '" title="' + escapeHtml("About this rule") +
            '" aria-label="' + escapeHtml("About this rule") + '">i</button>' +
          "</span>",
          analysisNameCell(item.object || "—", icons[item.kind] || "group", {
            level: 0, menu: isModelItem
          }),
          escapeHtml(analysisHealthDetail(item)),
          item.size_bytes
            ? '<span title="' + escapeHtml(analysisFmtBytes(item.size_bytes)) + '">' +
              escapeHtml(analysisFmtBytes(item.size_bytes)) + "</span>"
            : "—"
        ],
        healthTarget: item.target || {},
        severity_rank: item.severity_rank,
        size_bytes: item.size_bytes || 0,
        rule: item.rule,
        area: item.area,
        object_name: item.object || ""
      };
      if (isModelItem) {
        row.item = {
          kind: item.kind,
          table: item.table || "",
          name: isTable ? item.table : (item.name || "")
        };
      }
      return row;
    });
    return {
      headers: [
        { label: "Severity", key: "severity" },
        { label: "Area", key: "area" },
        { label: "Rule", key: "rule" },
        { label: "Object", key: "object_name" },
        { label: "Detail" },
        { label: "Size", key: "size", num: true }
      ],
      widths: ["10%", "9%", "21%", "25%", "27%", "8%"],
      rows: viewRows,
      summary: "{n} findings · {c} critical · {w} warning · {i} info"
        .replace("{n}", fmtInt(items.length))
        .replace("{c}", fmtInt(counts.critical || 0))
        .replace("{w}", fmtInt(counts.warning || 0))
        .replace("{i}", fmtInt(counts.info || 0)) +
        analysisCoverageSuffix(state.analysis)
    };
  }

  export function analysisHealthOpen(row) {
    var kind = row.getAttribute("data-health-kind") || "";
    var table = row.getAttribute("data-health-table") || "";
    var name = row.getAttribute("data-health-name") || "";
    if (kind === "column" || kind === "measure") {
      if (name) analysisOpenItemDetails({ kind: kind, table: table, name: name });
      return;
    }
    if (kind === "table") {
      var tableName = table || name;
      if (tableName) {
        analysisLineageOpen(
          { kind: "table", table: tableName, name: tableName }, "graph", "all"
        );
      }
      return;
    }
    if (kind === "report") {
      var reportId = row.getAttribute("data-health-report_id") || "";
      state.analysisTab = "report";
      state.analysisForceOpen = null;
      if (reportId) state.analysisOpen["report:" + reportId] = true;
      analysisApplyTabTools("report", true);
      analysisRender();
      return;
    }
    if (kind === "relationship") {
      state.analysisTab = "relationships";
      state.analysisForceOpen = null;
      analysisApplyTabTools("relationships", true);
      analysisRender();
    }
  }

  function analysisBestPracticeIcon(kind) {
    var icons = {
      column: "column", measure: "measure", table: "table", relationship: "link",
      expression: "code", model: "group"
    };
    return icons[kind] || "group";
  }

  function analysisBestPracticeSeverity(severity) {
    var value = Number(severity) || 1;
    var cls = value >= 3 ? "chip-danger" : (value === 2 ? "chip-warn" : "chip-info");
    var label = value >= 3 ? "High" : (value === 2 ? "Medium" : "Low");
    return '<span class="chip ' + cls + '"><span class="dot"></span>' +
      escapeHtml((label)) + "</span>";
  }

  function analysisRenderBestPracticeSummary() {
    var bp = ((state.analysis && state.analysis.best_practice) || {});
    if (!$("#bpSummary")) return;
    $("#bpScore").textContent = bp.available === false
      ? "—" : fmtInt(bp.score || 0);
    var verdict = $("#bpVerdict");
    verdict.setAttribute("data-verdict", bp.verdict_key || "pro");
    $("#bpVerdictText").textContent = bp.available === false
      ? "Catalog unavailable" : (bp.verdict || "—");
    var counts = bp.counts || {};
    $("#bpMeta").textContent = bp.available === false
      ? (bp.error || "")
      : "{v} violations · {r} rules with findings · {e}/{n} evaluated · {u} not evaluated"
        .replace("{v}", fmtInt(counts.violations || 0))
        .replace("{r}", fmtInt(counts.rules || 0))
        .replace("{e}", fmtInt(bp.evaluated || 0))
        .replace("{n}", fmtInt(bp.rule_count || 0))
        .replace("{u}", fmtInt(bp.not_evaluated || 0));
  }

  function analysisBestPracticeRows() {
    var bp = ((state.analysis && state.analysis.best_practice) || {});
    var items = bp.items || [];
    var rules = bp.rules || [];
    if (bp.available === false) {
      return { headers: [], widths: [], rows: [], summary: (bp.error || "") };
    }
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var category = getSelectValue("typeAnalyze") || "all";
    var byRule = {};
    items.forEach(function (item) {
      var filtered = category === "all" || item.category === category;
      if (!filtered) return;
      if (query) {
        var haystack = [
          item.rule_name, item.object, item.detail, item.category, item.table,
          item.name
        ].join(" ").toLowerCase();
        if (haystack.indexOf(query) === -1) return;
      }
      var key = item.rule_id;
      if (!byRule[key]) byRule[key] = [];
      byRule[key].push(item);
    });
    var ruleMap = {};
    rules.forEach(function (rule) { ruleMap[rule.id] = rule; });
    var rows = [];
    Object.keys(byRule).sort(function (left, right) {
      var a = ruleMap[left] || {};
      var b = ruleMap[right] || {};
      return (b.score || 0) - (a.score || 0) ||
        String(a.name || "").localeCompare(String(b.name || ""));
    }).forEach(function (ruleId) {
      var rule = ruleMap[ruleId] || { id: ruleId, name: ruleId, severity: 1 };
      var groupId = "bp:" + ruleId;
      var open = analysisIsOpen(groupId, false, true);
      var findings = byRule[ruleId];
      rows.push({
        level: 0,
        group: true,
        cells: [
          analysisNameCell(rule.name, "group", {
            level: 0, toggleId: groupId, open: open
          }),
          fmtInt(rule.score || 0),
          analysisBestPracticeSeverity(rule.severity),
          fmtInt(findings.length)
        ],
        numCols: [1, 3]
      });
      if (!open) return;
      findings.forEach(function (item) {
        var isModel = item.kind === "column" || item.kind === "measure" ||
          item.kind === "table";
        var nameCell = analysisNameCell(
          item.object || "—", analysisBestPracticeIcon(item.kind), { level: 1 }
        );
        if (item.detail) {
          nameCell += ' <span class="helper">' + escapeHtml(item.detail) + "</span>";
        }
        var row = {
          level: 1,
          cells: [nameCell, "", "", ""],
          healthTarget: item.target || {}
        };
        if (isModel) {
          row.item = {
            kind: item.kind,
            table: item.table || "",
            name: item.kind === "table" ? (item.table || "") : (item.name || "")
          };
        }
        rows.push(row);
      });
    });
    return {
      headers: [
        { label: "Rule" },
        { label: "Violation score" },
        { label: "Severity" },
        { label: "Objects" }
      ],
      widths: ["55%", "13%", "14%", "18%"],
      rows: rows,
      summary: "{v} violations · {r} rules with findings · {e}/{n} evaluated · {u} not evaluated"
        .replace("{v}", fmtInt((bp.counts || {}).violations || 0))
        .replace("{r}", fmtInt((bp.counts || {}).rules || 0))
        .replace("{e}", fmtInt(bp.evaluated || 0))
        .replace("{n}", fmtInt(bp.rule_count || 0))
        .replace("{u}", fmtInt(bp.not_evaluated || 0))
    };
  }

  var BP_STATUS_LABELS = {
    violation: "Violation",
    pass: "Pass",
    not_evaluated: "Not evaluated",
    needs_coverage: "Needs coverage"
  };

  function analysisBpRulesMarkup() {
    var bp = ((state.analysis && state.analysis.best_practice) || {});
    var rules = bp.rules || [];
    var categories = [];
    rules.forEach(function (rule) {
      if (categories.indexOf(rule.category) === -1) categories.push(rule.category);
    });
    categories.sort();
    var parts = [];
    categories.forEach(function (category) {
      var groupRows = rules.filter(function (rule) {
        return rule.category === category;
      }).sort(function (left, right) {
        return (right.score || 0) - (left.score || 0) ||
          String(left.name).localeCompare(String(right.name));
      });
      parts.push(
        '<section class="health-rule-group"><h3 class="health-rule-group-title">' +
        '<span class="chip chip-idle">' + escapeHtml((category)) + "</span>" +
        '<span class="helper">' + fmtInt(groupRows.length) + " " + "rules" +
        "</span></h3>"
      );
      groupRows.forEach(function (rule) {
        var status = String(rule.status || "");
        var cls = status === "violation" ? "chip-danger"
          : (status === "pass" ? "chip-ok" : "chip-idle");
        parts.push(
          '<article class="health-rule"><div class="health-rule-head"><h4>' +
          escapeHtml(rule.name) + "</h4>" +
          '<span class="chip ' + cls + '"><span class="dot"></span>' +
          escapeHtml((BP_STATUS_LABELS[status] || status)) + "</span>" +
          '<span class="helper">' + fmtInt(rule.score || 0) + "</span></div>" +
          '<p class="health-rule-desc">' + escapeHtml(rule.description || "") + "</p>" +
          '<dl class="health-rule-meta">' +
          "<dt>" + escapeHtml("Severity") + "</dt><dd>" +
          escapeHtml((rule.severity_label || "")) + "</dd>" +
          (rule.expression
            ? "<dt>" + escapeHtml("Expression") + "</dt><dd><code>" +
              escapeHtml(rule.expression) + "</code></dd>"
            : "") +
          (rule.fix_expression
            ? "<dt>" + escapeHtml("Suggested fix") + "</dt><dd><code>" +
              escapeHtml(rule.fix_expression) + "</code></dd>"
            : "") +
          (rule.reason
            ? "<dt>" + escapeHtml("Reason") + "</dt><dd>" +
              escapeHtml((rule.reason)) + "</dd>"
            : "") +
          "</dl></article>"
        );
      });
      parts.push("</section>");
    });
    return parts.join("");
  }

  export function analysisOpenBpRules() {
    var dialog = $("#analysisBpRulesDialog");
    if (!dialog) return;
    $("#analysisBpRulesBody").innerHTML = analysisBpRulesMarkup();
    if (dialog.open) dialog.close();
    dialog.showModal();
  }

  function analysisSortItems(items) {
    if (!state.analysisSort || state.analysisSort === "default") return items.slice();
    var key = state.analysisSort;
    var desc = state.analysisSortDesc;
    return items.slice().sort(function (left, right) {
      var a = left[key];
      var b = right[key];
      if (key === "size") {
        a = Number(left.size_bytes || 0);
        b = Number(right.size_bytes || 0);
      } else if (["uses", "pages", "visuals", "fields", "unresolved", "used"].includes(key)) {
        a = Number(a || 0);
        b = Number(b || 0);
      } else if (key === "status") {
        a = ANALYSIS_STATUS_ORDER[left.status] == null ? 99 : ANALYSIS_STATUS_ORDER[left.status];
        b = ANALYSIS_STATUS_ORDER[right.status] == null ? 99 : ANALYSIS_STATUS_ORDER[right.status];
      } else if (key === "severity") {
        a = Number(left.severity_rank == null ? 99 : left.severity_rank);
        b = Number(right.severity_rank == null ? 99 : right.severity_rank);
      } else if (key === "has_error" || key === "is_active") {
        a = left[key] ? 1 : 0;
        b = right[key] ? 1 : 0;
      } else if (key === "type" && left.type == null) {
        a = "relationship";
        b = "relationship";
      } else {
        a = String(a == null ? "" : a).toLowerCase();
        b = String(b == null ? "" : b).toLowerCase();
      }
      if (a < b) return desc ? 1 : -1;
      if (a > b) return desc ? -1 : 1;
      return 0;
    });
  }

  function analysisHead(headers) {
    return "<tr>" + headers.map(function (header) {
      var cls = header.num ? ' class="num"' : "";
      var sort = header.key ? ' data-analysis-sort="' + escapeHtml(header.key) + '"' : "";
      var arrow = header.key && state.analysisSort === header.key
        ? (state.analysisSortDesc ? " \u25bc" : " \u25b2") : "";
      return "<th scope=\"col\"" + cls + sort + ' title="' +
        escapeHtml(header.hint || header.label) + '">' + header.label + arrow + "</th>";
    }).join("") + "</tr>";
  }

  export function applyAnalysisCellTitles() {
    $$("#analyzeBody td").forEach(function (cell) {
      var nameText = cell.querySelector(".name-text");
      var clipped = cell.scrollWidth > cell.clientWidth + 1;
      var nameClipped = Boolean(
        nameText && nameText.scrollWidth > nameText.clientWidth + 1
      );
      if (nameClipped) {
        var longName = (nameText.textContent || "").trim();
        if (longName) cell.title = longName;
      } else if (clipped) {
        var text = (cell.innerText || "").trim();
        if (text) cell.title = text;
      } else if (cell.title) {
        cell.removeAttribute("title");
      }
    });
  }

  function analysisBody(headers, rows) {
    return rows.map(function (row) {
      if (row.kind === "subhead") {
        return '<tr class="subhead-row">' + headers.map(function (header, index) {
          var label = row.labels && row.labels[index] ? row.labels[index] : "";
          return "<td>" + escapeHtml(label) + "</td>";
        }).join("") + "</tr>";
      }
      if (row.kind === "detail") {
        return '<tr class="detail-row"><td colspan="' + headers.length + '">' +
          escapeHtml(row.text) + "</td></tr>";
      }
      if (row.kind === "code") {
        var codeHtml = row.language === "plain"
          ? escapeHtml(row.code)
          : highlightCode(row.code, row.language || "dax");
        var copyLabel = escapeHtml("Copy code");
        return '<tr class="code-row"><td colspan="' + headers.length +
          '"><div class="code-cell"><button type="button" class="code-copy" data-copy-code aria-label="' +
          copyLabel + '" title="' + copyLabel + '">' + MENU_ICONS.copy +
          "</button><pre>" + codeHtml + "</pre></div></td></tr>";
      }
      if (row.kind === "html") {
        return '<tr class="' + (row.cls || "analysis-sub") + '"><td colspan="' +
          headers.length + '">' + row.html + "</td></tr>";
      }
      var numeric = row.numCols || [];
      var level = row.level || 0;
      var classes = [];
      if (row.group) classes.push("group-row");
      if (row.itemRow) classes.push("item-row");
      if (row.cls) classes.push(row.cls);
      var attrs = classes.length ? ' class="' + classes.join(" ") + '"' : "";
      if (row.group) attrs += ' data-level="' + level + '"';
      if (row.item) {
        attrs += ' data-item-kind="' + escapeHtml(row.item.kind) +
          '" data-item-table="' + escapeHtml(row.item.table) +
          '" data-item-name="' + escapeHtml(row.item.name) + '"';
      }
      if (row.healthTarget) {
        Object.keys(row.healthTarget).forEach(function (key) {
          var value = row.healthTarget[key];
          if (value == null || value === "") return;
          attrs += " data-health-" + escapeHtml(key) + '="' +
            escapeHtml(value) + '"';
        });
      }
      var html = row.cells.map(function (cell, index) {
        var tdClasses = [];
        if (index === 0) tdClasses.push("cell-name");
        if (numeric.indexOf(index) !== -1) tdClasses.push("num");
        var style = index === 0 ? ' style="--depth:' + level + '"' : "";
        var cls = tdClasses.length ? ' class="' + tdClasses.join(" ") + '"' : "";
        return "<td" + cls + style + ">" + cell + "</td>";
      }).join("");
      return "<tr" + attrs + ">" + html + "</tr>";
    }).join("");
  }

  export function analysisRender() {
    analysisCloseMenu(false);
    var result = state.analysis;
    analysisTabCounts();
    $$("#analyzeTabs [role='tab']").forEach(function (tab) {
      var active = tab.getAttribute("data-analysis-tab") === state.analysisTab;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
    });
    analysisExportState();
    var tableWrap = $("#analyzeTableWrap");
    var graph = $("#relGraph");
    var empty = $("#analyzeEmpty");
    var bpSummary = $("#bpSummary");
    if (!result) {
      tableWrap.hidden = true;
      graph.hidden = true;
      if (bpSummary) bpSummary.hidden = true;
      empty.hidden = false;
      var hasModel = Boolean(getSelectValue("modelSelect"));
      $("#analyzeSummary").textContent = hasModel
        ? "Ready to analyze" : "Not analyzed yet";
      $("#analyzeEmptyTitle").textContent = hasModel
        ? "Ready to analyze" : "No analysis results yet";
      $("#analyzeEmptyText").textContent = hasModel
        ? "Press Analyze now or Analysis to start. Only reads the model."
        : "Choose a workspace and semantic model, then press Analyze now.";
      $("#analyzeFromEmpty").hidden = !hasModel;
      return;
    }
    var tab = state.analysisTab;
    if (bpSummary) bpSummary.hidden = tab !== "bestpractice";
    if (tab === "bestpractice") analysisRenderBestPracticeSummary();
    if (tab === "relationships" && state.relView === "graph") {
      tableWrap.hidden = true;
      $("#analyzeHead").innerHTML = "";
      $("#analyzeBody").innerHTML = "";
      analysisRenderGraph();
      empty.hidden = true;
      return;
    }
    graph.hidden = true;
    var view;
    if (tab === "all") view = analysisFlatRows();
    else if (tab === "tables") view = analysisTreeView();
    else if (tab === "relationships") view = analysisRelationshipRows();
    else if (tab === "roles") view = analysisRoleRows();
    else if (tab === "report") view = analysisReportRows();
    else if (tab === "dax") view = analysisDaxRows();
    else if (tab === "m") view = analysisMRows();
    else if (tab === "health") view = analysisHealthRows();
    else if (tab === "bestpractice") view = analysisBestPracticeRows();
    else view = analysisFlatRows();
    $("#analyzeCols").innerHTML = (view.widths || []).map(function (width) {
      return '<col style="width:' + width + '">';
    }).join("");
    $("#analyzeHead").innerHTML = analysisHead(view.headers);
    $("#analyzeBody").innerHTML = analysisBody(view.headers, view.rows);
    $("#analyzeSummary").textContent = view.summary;
    if (!view.rows.length) {
      tableWrap.hidden = true;
      empty.hidden = false;
      if (tab === "report" && result.reports_included === false) {
        $("#analyzeEmptyTitle").textContent = "Report usage not included";
        $("#analyzeEmptyText").textContent = "Enable “Include report usage” and run the analysis again to see pages, visuals, and filters.";
      } else if (tab === "bestpractice") {
        if (result.best_practice && result.best_practice.available === false) {
          $("#analyzeEmptyTitle").textContent = "Catalog unavailable";
          $("#analyzeEmptyText").textContent =
            (result.best_practice.error || "");
        } else {
          $("#analyzeEmptyTitle").textContent = "No best practice violations";
          $("#analyzeEmptyText").textContent = "Every evaluated rule passed. Open Rules to review the full catalog and unsupported rules.";
        }
      } else {
        $("#analyzeEmptyTitle").textContent = "No matching items";
        $("#analyzeEmptyText").textContent =
          "Change the keyword or filter to see other items in this tab.";
      }
      $("#analyzeFromEmpty").hidden = true;
    } else {
      tableWrap.hidden = false;
      empty.hidden = true;
    }
    if (!tableWrap.hidden) {
      window.requestAnimationFrame(applyAnalysisCellTitles);
    }
  }

  function analysisTableInfo(name) {
    var tables = (state.analysis && state.analysis.tables) || [];
    return tables.filter(function (table) { return table.name === name; })[0] || {
      name: name, column_count: 0, measure_count: 0, size_bytes: 0,
      storage_mode: "", partition_count: 0, total_items: 0
    };
  }

  function analysisTruncate(text, size) {
    var value = String(text || "");
    return value.length > size ? value.slice(0, size - 1) + "…" : value;
  }

  var REL_NODE_W = 152;
  var REL_NODE_H = 58;
  var REL_COL_GAP = 88;
  var REL_ROW_GAP = 22;
  var REL_PAD = 30;
  var REL_LANE_STEPS = [0, -12, 12, -24, 24, -36, 36, -48, 48, -60, 60, -72, 72, -90, 90, -108, 108, -126, 126];

  function analysisRelPairs(list) {
    var pairs = {};
    list.forEach(function (rel) {
      var key = (rel.from_table || "") + "|" + (rel.to_table || "");
      if (!pairs[key]) {
        pairs[key] = { key: key, from: rel.from_table, to: rel.to_table, rels: [] };
      }
      pairs[key].rels.push(rel);
    });
    return pairs;
  }

  function analysisPairStatus(pair) {
    var active = pair.rels.filter(function (rel) { return rel.is_active; }).length;
    return { active: active, inactive: pair.rels.length - active };
  }

  function analysisRelTreeLayout() {
    var tables = (state.analysis && state.analysis.tables) || [];
    var names = tables.map(function (table) { return table.name; });
    var outgoing = {};
    var incoming = {};
    names.forEach(function (name) {
      outgoing[name] = [];
      incoming[name] = [];
    });
    ((state.analysis && state.analysis.relationships) || []).forEach(function (rel) {
      var a = rel.from_table;
      var b = rel.to_table;
      if (!a || !b || a === b) return;
      if (!outgoing[a] || !incoming[b]) return;
      if (outgoing[a].indexOf(b) === -1) outgoing[a].push(b);
      if (incoming[b].indexOf(a) === -1) incoming[b].push(a);
    });

    var level = {};
    names.forEach(function (name) { level[name] = 0; });
    var guard = names.length * 2;
    var changed = true;
    while (changed && guard > 0) {
      changed = false;
      guard -= 1;
      names.forEach(function (name) {
        incoming[name].forEach(function (parent) {
          if (level[parent] + 1 > level[name] && level[parent] + 1 < names.length) {
            level[name] = level[parent] + 1;
            changed = true;
          }
        });
      });
    }

    var columns = [];
    names.forEach(function (name) {
      var index = level[name];
      if (!columns[index]) columns[index] = [];
      columns[index].push(name);
    });

    var maxRows = 1;
    columns.forEach(function (column) { maxRows = Math.max(maxRows, column.length); });
    var contentHeight = maxRows * REL_NODE_H + (maxRows - 1) * REL_ROW_GAP;
    var height = Math.max(340, contentHeight + REL_PAD * 2);
    var width = REL_PAD * 2 + columns.length * REL_NODE_W +
      Math.max(0, columns.length - 1) * REL_COL_GAP;
    var positions = {};

    columns.forEach(function (column, columnIndex) {
      var total = column.length * REL_NODE_H + (column.length - 1) * REL_ROW_GAP;
      var startY = (height - total) / 2;
      column.forEach(function (name, rowIndex) {
        positions[name] = {
          level: columnIndex,
          x: REL_PAD + columnIndex * (REL_NODE_W + REL_COL_GAP),
          y: startY + rowIndex * (REL_NODE_H + REL_ROW_GAP)
        };
      });
    });

    var offsets = state.relNodeOffset || {};
    var right = width;
    var bottom = height;
    Object.keys(positions).forEach(function (name) {
      var offset = offsets[name];
      if (!offset) return;
      positions[name].x += offset.dx || 0;
      positions[name].y += offset.dy || 0;
      right = Math.max(right, positions[name].x + REL_NODE_W + REL_PAD);
      bottom = Math.max(bottom, positions[name].y + REL_NODE_H + REL_PAD);
    });

    return { positions: positions, width: right, height: bottom, names: names };
  }

  export function analysisBeginRelNodeDrag(name, rect) {
    var offsets = state.relNodeOffset || (state.relNodeOffset = {});
    var offset = offsets[name] || { dx: 0, dy: 0 };
    var dx = offset.dx || 0;
    var dy = offset.dy || 0;
    state.relNodeDrag = {
      name: name,
      baseDx: dx,
      baseDy: dy,
      baseX: ((rect && rect.x) || 0) - dx,
      baseY: ((rect && rect.y) || 0) - dy
    };
  }

  export function analysisMoveRelNode(name, dx, dy) {
    var drag = state.relNodeDrag;
    if (!drag || drag.name !== name) return;
    var offsets = state.relNodeOffset || (state.relNodeOffset = {});
    var nextX = drag.baseDx + dx;
    var nextY = drag.baseDy + dy;
    if (drag.baseX + nextX < REL_PAD) nextX = REL_PAD - drag.baseX;
    if (drag.baseY + nextY < REL_PAD) nextY = REL_PAD - drag.baseY;
    offsets[name] = {
      dx: Math.min(nextX, 2400),
      dy: Math.min(nextY, 2400)
    };
    if (!state.relDragFrame) {
      state.relDragFrame = window.requestAnimationFrame(function () {
        state.relDragFrame = 0;
        if (state.analysisTab === "relationships") analysisRenderGraph(true);
      });
    }
  }

  export function analysisEndRelNodeDrag() {
    state.relNodeDrag = null;
    if (state.relDragFrame) {
      window.cancelAnimationFrame(state.relDragFrame);
      state.relDragFrame = 0;
    }
  }

  function analysisRelRoutePath(x1, y1, x2, y2, laneY) {
    var g1 = x1 + REL_COL_GAP / 2;
    var g2 = x2 - REL_COL_GAP / 2;
    return "M" + x1 + " " + y1 +
      "C" + (x1 + (g1 - x1) * 0.7) + " " + y1 + ", " + (g1 - 12) + " " + laneY +
      ", " + g1 + " " + laneY +
      "L" + g2 + " " + laneY +
      "C" + (g2 + 12) + " " + laneY + ", " + (g2 + (x2 - g2) * 0.4) + " " + y2 +
      ", " + x2 + " " + y2;
  }

  function analysisLaneClear(positions, from, to, y) {
    for (var column = from.level + 1; column < to.level; column += 1) {
      var blocked = Object.keys(positions).some(function (name) {
        var pos = positions[name];
        return pos.level === column && y > pos.y - 8 && y < pos.y + REL_NODE_H + 8;
      });
      if (blocked) return false;
    }
    return true;
  }

  function analysisLaneY(positions, from, to, y2, usedLanes, limit) {
    for (var i = 0; i < REL_LANE_STEPS.length; i += 1) {
      var candidate = y2 + REL_LANE_STEPS[i];
      if (candidate < 12 || candidate > limit - 12) continue;
      if (!analysisLaneClear(positions, from, to, candidate)) continue;
      var taken = usedLanes.some(function (value) {
        return Math.abs(value - candidate) < 7;
      });
      if (taken) continue;
      return candidate;
    }
    return 16;
  }

  function analysisGraphStat(label, value) {
    return '<div class="rel-side-stat"><b>' + escapeHtml(String(value)) +
      "</b><span>" + escapeHtml(label) + "</span></div>";
  }

  function analysisRelChip(label, cls) {
    return '<span class="chip ' + (cls || "chip-idle") + '">' + escapeHtml(label) + "</span>";
  }

  function analysisPairCard(rel) {
    return '<div class="rel-side-rel"><code>' +
      escapeHtml((rel.from_table || "") + "[" + (rel.from_column || "") + "]") + " → " +
      escapeHtml((rel.to_table || "") + "[" + (rel.to_column || "") + "]") + "</code>" +
      '<div class="rel-meta">' +
      analysisRelChip(tStatus(rel.status || "Used"), rel.is_active ? "chip-ok" : "chip-idle") +
      analysisRelChip(rel.type || "") +
      analysisRelChip(rel.cross || "") +
      analysisRelChip(rel.cardinality || "") +
      analysisRelChip("auto: " + (rel.auto || "No")) +
      "</div></div>";
  }

  function analysisGraphSide(selected, allPairs, visiblePairs, names) {
    var side = $("#relGraphSide");
    if (selected && selected.kind === "pair") {
      var pair = allPairs[selected.value];
      if (!pair) {
        side.innerHTML = '<p class="helper">' +
        "No relationships match the current filter." + "</p>";
        return;
      }
      var status = analysisPairStatus(pair);
      side.innerHTML =
        '<p class="rel-side-title">' + escapeHtml(pair.from) + " → " +
        escapeHtml(pair.to) + "</p>" +
        '<p class="rel-side-sub">' + pair.rels.length + " relationships · " +
        status.active + " active · " + status.inactive + " inactive</p>" +
        '<div class="rel-side-list">' + pair.rels.map(analysisPairCard).join("") + "</div>" +
        '<button class="btn btn-sm rel-side-back" type="button" data-rel-back="' +
        escapeHtml(pair.from) + '">' + "View all relationships " + escapeHtml(pair.from) + "</button>";
      return;
    }
    if (selected && selected.kind === "table") {
      var name = selected.value;
      var info = analysisTableInfo(name);
      var keys = Object.keys(visiblePairs).filter(function (key) {
        return visiblePairs[key].from === name || visiblePairs[key].to === name;
      });
      var rels = [];
      keys.forEach(function (key) { rels = rels.concat(visiblePairs[key].rels); });
      var active = rels.filter(function (rel) { return rel.is_active; }).length;
      side.innerHTML =
        '<p class="rel-side-title">' + escapeHtml(name) + "</p>" +
        '<p class="rel-side-sub">Table · ' + info.column_count + " columns · " +
        info.measure_count + " measures · " + (info.rows || 0) + " rows</p>" +
        '<div class="rel-side-stats">' +
        analysisGraphStat("Relationships", rels.length) +
        analysisGraphStat("Active", active) +
        analysisGraphStat("Inactive", rels.length - active) +
        analysisGraphStat("Related tables", keys.length) +
        "</div>" +
        (keys.length
          ? '<div class="rel-side-list">' + keys.map(function (key) {
            var pair = visiblePairs[key];
            var target = pair.from === name ? pair.to : pair.from;
            var pairStatus = analysisPairStatus(pair);
            return '<button type="button" class="rel-side-item" data-rel-pair="' +
              escapeHtml(key) + '"><strong>' + escapeHtml(target) + "</strong><span>" +
              pair.rels.length + " relationships · " + pairStatus.inactive +
              " inactive</span></button>";
          }).join("") + "</div>"
          : '<p class="rel-side-note">' + "No relationships match the current filter." + "</p>") +
        '<p class="rel-side-note">' + "Click a line in the graph to see the relationship columns." + "</p>";
      return;
    }
    side.innerHTML = '<p class="rel-side-title">' + "Relationship graph" + "</p>" +
      '<p class="rel-side-sub">' + names.length + " tables · " +
      Object.keys(visiblePairs).length + " table pairs in this filter.</p>" +
      '<p class="rel-side-note">' +
      "Click a table or line to see relationship details." + "</p>";
  }

  export function applyAnalysisZoom() {
    var svg = $("#relGraphSvg");
    if (!svg) return;
    var baseWidth = state.relGraphBaseWidth || 760;
    var baseHeight = state.relGraphBaseHeight || 500;
    var zoom = state.relZoom || 1;
    var width = baseWidth / zoom;
    var height = baseHeight / zoom;
    var x = (baseWidth - width) / 2 + (state.relPanX || 0);
    var y = (baseHeight - height) / 2 + (state.relPanY || 0);
    svg.setAttribute(
      "viewBox",
      x + " " + y + " " + width + " " + height
    );
    var label = $("#relZoomValue");
    if (label) label.textContent = Math.round(zoom * 100) + "%";
    var out = $("#relZoomOut");
    var inn = $("#relZoomIn");
    if (out) out.disabled = zoom <= 0.6;
    if (inn) inn.disabled = zoom >= 2.5;
  }

  export function analysisSetZoom(value) {
    state.relZoom = Math.max(0.6, Math.min(2.5, value));
    applyAnalysisZoom();
  }

  function analysisRenderGraph(keepSide) {
    var layer = $("#relGraphLayer");
    var relations = analysisFilteredRelationships();
    var allPairs = analysisRelPairs((state.analysis && state.analysis.relationships) || []);
    var visiblePairs = analysisRelPairs(relations);
    var tree = analysisRelTreeLayout();
    $("#relGraph").hidden = false;
    $("#analyzeSummary").textContent = relations.length + " relationships · " +
      Object.keys(visiblePairs).length + " table pairs" +
      analysisCoverageSuffix(state.analysis);
    if (!relations.length) {
      layer.innerHTML = "";
      state.relGraphBaseWidth = 760;
      state.relGraphBaseHeight = 220;
      state.relPanX = 0;
      state.relPanY = 0;
      analysisSetZoom(1);
      $("#relGraphSide").innerHTML =
        '<div class="empty" style="padding:18px 8px"><div class="empty-title">' +
        "No relationships" + "</div>" +
        '<p class="empty-text">' +
        "Change the keyword or status filter to see other relationships." +
        "</p></div>";
      return;
    }

    var names = tree.names;
    var selected = state.relSelected;
    if (selected && selected.kind === "table" && !tree.positions[selected.value]) {
      selected = null;
    }
    if (selected && selected.kind === "pair" && !visiblePairs[selected.value]) {
      selected = null;
    }
    if (!selected) {
      selected = { kind: "table", value: names[0] };
    }
    state.relSelected = selected;
    var selectedPair = selected.kind === "pair" ? selected.value : "";
    var selectedTable = selected.kind === "table" ? selected.value : "";

    var parts = [];
    var usedLanes = [];
    Object.keys(visiblePairs).forEach(function (key) {
      var pair = visiblePairs[key];
      var from = tree.positions[pair.from];
      var to = tree.positions[pair.to];
      if (!from || !to) return;
      var x1 = from.x + REL_NODE_W;
      var y1 = from.y + REL_NODE_H / 2;
      var x2 = to.x;
      var y2 = to.y + REL_NODE_H / 2;
      if (x2 <= x1 + 6) {
        x1 = from.x;
        x2 = to.x + REL_NODE_W;
      }
      var path;
      var badgeX;
      var badgeY;
      if (to.level - from.level > 1) {
        var laneY = analysisLaneY(tree.positions, from, to, y2, usedLanes, tree.height);
        usedLanes.push(laneY);
        path = analysisRelRoutePath(x1, y1, x2, y2, laneY);
        badgeX = (x1 + x2) / 2;
        badgeY = laneY;
      } else {
        var mid = x1 + (x2 - x1) / 2;
        path = "M" + x1 + " " + y1 + "C" + mid + " " + y1 + ", " + mid + " " +
          y2 + ", " + x2 + " " + y2;
        badgeX = (x1 + x2) / 2;
        badgeY = (y1 + y2) / 2;
      }
      var status = analysisPairStatus(pair);
      var isSelected = selectedPair === key;
      var hot = isSelected ||
        (selectedTable && (pair.from === selectedTable || pair.to === selectedTable));
      var dim = !hot;
      var cls = "rel-edge" + (status.active ? "" : " is-inactive") +
        (hot ? " is-selected" : "");
      parts.push('<path class="' + cls + '" d="' + path + '"' +
        (dim ? ' opacity=".45"' : "") + ' marker-end="url(#' +
        (hot ? "relArrowActive" : "relArrow") + ')" data-rel-pair="' +
        escapeHtml(key) + '"><title>' + escapeHtml(pair.from + " → " + pair.to +
          " · " + pair.rels.length + " relationships") + "</title></path>");
      parts.push('<path class="rel-edge-hit" d="' + path + '" data-rel-pair="' +
        escapeHtml(key) + '"></path>');
      if (pair.rels.length > 1) {
        parts.push('<g class="rel-edge-badge" aria-hidden="true">' +
          '<rect x="' + (badgeX - 10) + '" y="' + (badgeY - 8) +
          '" width="20" height="16" rx="8"></rect>' +
          '<text x="' + badgeX + '" y="' + (badgeY + 3) + '">' +
          pair.rels.length + "</text></g>");
      }
    });

    Object.keys(tree.positions).forEach(function (name) {
      var pos = tree.positions[name];
      var info = analysisTableInfo(name);
      var touches = Object.keys(visiblePairs).some(function (key) {
        return visiblePairs[key].from === name || visiblePairs[key].to === name;
      });
      var isSelected = selectedTable === name;
      var cls = "node rel-node" + (touches ? "" : " is-dim");
      parts.push('<g class="' + cls + '" tabindex="0" role="button" data-rel-table="' +
        escapeHtml(name) + '" aria-label="' + "Table " + escapeHtml(name) +
        (touches ? ", has relationships" : ", no relationships") + '" aria-current="' +
        (isSelected ? "true" : "false") + '">' +
        '<rect class="node-box' + (isSelected ? " sel" : "") + '" x="' + pos.x +
        '" y="' + pos.y + '" width="' + REL_NODE_W + '" height="' + REL_NODE_H +
        '" rx="6"></rect>' +
        '<text class="node-type" x="' + (pos.x + 11) + '" y="' + (pos.y + 16) +
        '">' + "Table" + "</text>" +
        '<text class="node-name" x="' + (pos.x + 11) + '" y="' + (pos.y + 33) +
        '">' + escapeHtml(analysisTruncate(name, 20)) + "</text>" +
        '<text class="rel-node-meta" x="' + (pos.x + 11) + '" y="' + (pos.y + 48) +
        '">' + info.column_count + " columns · " + info.measure_count +
        " measures</text></g>");
    });

    layer.innerHTML = parts.join("");
    if (!keepSide) {
      state.relGraphBaseWidth = tree.width;
      state.relGraphBaseHeight = tree.height;
    }
    applyAnalysisZoom();
    if (!keepSide) {
      analysisGraphSide(selected, allPairs, visiblePairs, names);
    }
  }

  export function analysisSetTab(name) {
    if (!ANALYSIS_TABS[name]) return;
    var previous = state.analysisTab;
    if (previous && previous !== name) {
      state.analysisQueries[previous] = $("#searchAnalyze").value || "";
    }
    state.analysisTab = name;
    $("#searchAnalyze").value = state.analysisQueries[name] || "";
    state.analysisForceOpen = null;
    state.analysisOpen = {};
    state.relSelected = null;
    analysisApplyTabTools(name, true);
    analysisRender();
  }

  export function analysisSetSort(key) {
    if (!key) return;
    if (key === state.analysisSort) {
      state.analysisSortDesc = !state.analysisSortDesc;
    } else {
      state.analysisSort = key;
      state.analysisSortDesc = ["size", "uses", "has_error", "pages", "visuals",
        "fields", "unresolved", "is_active", "used"].includes(key);
    }
    analysisSavePrefs();
    analysisRender();
  }

  export function analysisRun() {
    if (!app.apiReady()) return;
    if (!getSelectValue("wsSelect") || !getSelectValue("modelSelect")) {
      app.toast("Choose a workspace and semantic model first");
      return;
    }
    state.analysisRunning = true;
    state.analysisTarget = getSelectValue("modelSelect");
    var target = state.analysisTarget;
    $("#stopAnalyze").hidden = false;
    $("#analyzeSummary").textContent = "Analyzing the semantic model…";
    app.startJob({
      kind: "analysis",
      path: "/api/analysis/run",
      body: analysisPayload(),
      label: "Semantic Model Analysis",
      button: $("#runAnalyze"),
      onDone: function (snapshot) {
        state.analysisRunning = false;
        $("#stopAnalyze").hidden = true;
        var same = target === getSelectValue("modelSelect");
        state.analysisTarget = null;
        if (!same) {
          app.toast("Analysis finished for a previous model and was not applied.");
          analysisRender();
          return;
        }
        if (snapshot.result) {
          analysisApply(snapshot.result, analysisNote(snapshot.result));
        }
      },
      onError: function () {
        state.analysisRunning = false;
        $("#stopAnalyze").hidden = true;
        state.analysisTarget = null;
        analysisRender();
      }
    });
  }

  export function analysisStop() {
    if (!state.jobId || !app.apiReady()) return;
    app.api().post("/api/jobs/" + encodeURIComponent(state.jobId) + "/cancel", {})
      .then(function () { app.toast("Stop request sent"); })
      .catch(app.reportError);
  }

  export function analysisExport() {
    if (!app.apiReady() || !getSelectValue("modelSelect")) {
      app.toast("Choose a semantic model first");
      return;
    }
    var tab = state.analysisTab || "all";
    if (tab !== "all") {
      app.toast("Coming soon");
      return;
    }
    app.api().post("/api/analysis/export", {
      dataset_id: getSelectValue("modelSelect"),
      tab: "all"
    }).then(function (data) {
      app.toast("Export: " + data.path);
      app.api().post("/api/files/open", { path: data.path, mode: "open" })
        .catch(function () {});
    }).catch(app.reportError);
  }

