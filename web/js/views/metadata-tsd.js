import { app } from "../core/app_api.js";
import { getSelectItem, getSelectValue, refreshCombo, setSelectOptions, setSelectValue } from "../core/combo.js";
import { $, $$, escapeHtml } from "../core/dom.js";
import { fmtInt } from "../core/format.js";
import { state } from "../core/state.js";

  export function loadInstances() {
    if (!app.apiReady()) return Promise.resolve();
    return app.api().get("/api/metadata/instances").then(function (data) {
      state.instances = data.instances || [];
      var select = $("#desktopInstance");
      var html = ['<option value="">' +
        (state.instances.length ? "Choose an instance…" : "No open instance") +
        "</option>"];
      state.instances.forEach(function (item) {
        html.push('<option value="' + item.port + '">' + escapeHtml(item.label) + "</option>");
      });
      select.innerHTML = html.join("");
      if (state.instances.length === 1) select.value = String(state.instances[0].port);
      refreshCombo(select);
      state.instanceHint = data.hint || "";
      $("#instanceHint").textContent = (state.instanceHint) || "";
      renderModelAvailability();
      return data;
    }).catch(function (error) {
      app.addLog("The Desktop instance could not be read: " + error.message, "warn");
    });
  }

  export function renderModelAvailability() {
    var scope = $("#scope").value;
    var supportsModel = !state.pbix || state.pbix.has_local_model;
    var needed = scope !== "report" && supportsModel;
    $("#desktopInstance").disabled = !needed;
    $("#reloadDesktop").disabled = !needed;
    if (scope === "report") {
      $("#instanceHint").textContent = "Report scope only: the Power BI Desktop instance is not used.";
    } else if (state.pbix && !state.pbix.has_local_model) {
      $("#instanceHint").textContent = "This file is a live connection; the Power BI Desktop instance is not used.";
    } else if (!state.instances.length) {
      $("#instanceHint").textContent = "No Power BI Desktop instance is open. Open a .pbix file, then Reload.";
    }
  }

  export function loadWorkspaces() {
    if (!app.apiReady()) return Promise.resolve();
    return app.api().get("/api/metadata/workspaces").then(function (data) {
      state.workspaces = data.workspaces || [];
      var options = state.workspaces.map(function (item) {
        return { value: item.id, label: item.label, data: item };
      });
      setSelectOptions("modelWorkspace", options, "Choose a model workspace…");
      setSelectOptions("reportWorkspace", options, "Choose a report workspace…");
      setSelectOptions("shotWorkspace", options, "Choose a workspace…");
      state.workspaceHint = data.hint || "";
      $("#workspaceHint").textContent = (state.workspaceHint) ||
        "Type a workspace name to filter, or open the list.";
      return data;
    }).catch(function (error) {
      app.addLog("Workspace catalog could not be read: " + error.message, "error");
    });
  }

  export function loadModelContents() {
    var workspaceId = getSelectValue("modelWorkspace");
    if (!workspaceId || !app.apiReady()) return Promise.resolve();
    $("#workspaceHint").textContent = "Loading model workspace datasets…";
    return app.api().get(
      "/api/metadata/workspaces/" + encodeURIComponent(workspaceId) +
      "/contents?datasets=true&reports=false"
    ).then(function (data) {
      state.datasets = data.datasets || [];
      $("#xmlaEndpoint").value = (data.workspace && data.workspace.endpoint) || "";
      setSelectOptions("catalog", state.datasets.map(function (item) {
        return { value: item.name, label: item.name, data: item };
      }), "Choose a dataset…");
      $("#workspaceHint").textContent = state.datasets.length
        ? ""
        : "This model workspace has no readable datasets.";
      return data;
    }).catch(function (error) {
      $("#workspaceHint").textContent = (error.message);
      app.addLog((error.message), "error");
    });
  }

  export function loadReportContents() {
    var workspaceId = getSelectValue("reportWorkspace");
    if (!workspaceId || !app.apiReady()) return Promise.resolve();
    $("#reportHint").textContent = "Loading report workspace…";
    return app.api().get(
      "/api/metadata/workspaces/" + encodeURIComponent(workspaceId) +
      "/contents?datasets=false&reports=true"
    ).then(function (data) {
      state.reports = data.reports || [];
      state.batchSelected = {};
      setSelectOptions("serviceReport", state.reports.map(function (item) {
        return { value: item.id, label: item.label, data: item };
      }), "Choose a report…");
      renderBatchReports();
      $("#reportHint").textContent = state.reports.length
        ? "Paginated (RDL) reports are marked and cannot be extracted."
        : "This report workspace has no extractable reports.";
      return data;
    }).catch(function (error) {
      $("#reportHint").textContent = (error.message);
      app.addLog((error.message), "error");
    });
  }

  export function applyReportDefaults(report) {
    if (report.is_paginated) {
      $("#reportHint").textContent =
        "Paginated (RDL) reports are not supported; choose a regular Power BI report.";
      return;
    }
    var dataset = null;
    state.datasets.forEach(function (item) {
      if (String(item.id) === String(report.dataset_id)) dataset = item;
    });
    if (dataset) {
      $("#reportHint").textContent =
        "Report uses dataset " + dataset.name +
        ". The model catalog is selected separately and may be in another workspace.";
    } else if (report.dataset_id) {
      $("#reportHint").textContent =
        "The report uses a dataset in another workspace; choose the model catalog separately.";
    } else {
      $("#reportHint").textContent = "";
    }
  }

  export function refreshPbix() {
    var path = $("#pbixPath").value.trim();
    if (!app.apiReady()) return;
    if (!path) {
      state.pbix = null;
      $("#pbixKind").textContent = "Choose the source .pbix file.";
      $("#pbixKind").title = "";
      renderModelAvailability();
      return;
    }
    $("#pbixKind").textContent = "Reading file…";
    app.api().get("/api/metadata/pbix?path=" + encodeURIComponent(path)).then(function (data) {
      state.pbix = data;
      $("#pbixKind").textContent = data.label;
      $("#pbixKind").title = data.detail || "";
      $("#pbixPath").title = data.path || "";
      renderModelAvailability();
    }).catch(function (error) {
      state.pbix = null;
      $("#pbixKind").textContent = (error.message);
      renderModelAvailability();
    });
  }

  export function batchReports() {
    return (state.reports || []).filter(function (item) {
      return !item.is_paginated;
    });
  }

  function batchSelectedIds() {
    return Object.keys(state.batchSelected).filter(function (id) {
      return state.batchSelected[id];
    });
  }

  function batchDatasetIds() {
    var ids = {};
    batchReports().forEach(function (item) {
      if (state.batchSelected[item.id] && item.dataset_id) {
        ids[item.dataset_id] = true;
      }
    });
    return Object.keys(ids);
  }

  export function renderBatchHint() {
    var selected = batchSelectedIds();
    var datasets = batchDatasetIds();
    var hint = "";
    if (selected.length && datasets.length > 1) {
      hint = "Choose reports from the same dataset only.";
    } else if (selected.length) {
      hint = fmtInt(selected.length) + " " + "reports selected";
    }
    if ($("#batchHint")) $("#batchHint").textContent = hint;
    if ($("#runExtract")) {
      $("#runExtract").disabled =
        state.batchMode && (selected.length < 2 || datasets.length > 1);
    }
  }

  function renderBatchReports() {
    var list = $("#batchReports");
    if (!list) return;
    if (!state.batchMode) {
      list.innerHTML = "";
      renderBatchHint();
      return;
    }
    var reports = batchReports();
    list.innerHTML = reports.length
      ? reports.map(function (item) {
        var checked = state.batchSelected[item.id] ? " checked" : "";
        return '<label class="check"><input type="checkbox" data-batch-id="' +
          escapeHtml(item.id) + '"' + checked + "> <span>" +
          escapeHtml(item.label || item.name || item.id) + "</span></label>";
      }).join("")
      : '<span class="helper">' + "No extractable reports." + "</span>";
    renderBatchHint();
  }

  export function setBatchMode(enabled) {
    state.batchMode = Boolean(enabled);
    if (!state.batchMode) state.batchSelected = {};
    $("#batchRow").hidden = !state.batchMode;
    renderBatchReports();
  }

  function buildMetadataPayload() {
    var payload = {
      source: state.source === "service" ? "service" : "local",
      scope: $("#scope").value,
      out_dir: $("#outFolder").value.trim()
    };
    if (payload.source === "service") {
      var modelItem = getSelectItem("modelWorkspace");
      var reportWorkspace = getSelectItem("reportWorkspace");
      var reportItem = getSelectItem("serviceReport");
      var report = reportItem ? reportItem.data : null;
      payload.model_workspace_id = getSelectValue("modelWorkspace");
      payload.model_workspace_name = modelItem ? modelItem.data.name : "";
      payload.report_workspace_id = getSelectValue("reportWorkspace");
      payload.report_workspace_name = reportWorkspace
        ? reportWorkspace.data.name
        : "";
      payload.endpoint = $("#xmlaEndpoint").value.trim();
      if (state.batchMode) {
        var selected = batchSelectedIds();
        var names = {};
        selected.forEach(function (id) {
          state.reports.forEach(function (item) {
            if (item.id === id) names[id] = item.name || item.label || "";
          });
        });
        payload.report_ids = selected;
        payload.report_names = names;
        payload.report_id = "";
        payload.report_name = "";
        payload.report_type = "";
        payload.dataset_id = "";
      } else {
        payload.report_id = getSelectValue("serviceReport");
        payload.report_name = report ? report.name : "";
        payload.report_type = report ? report.report_type : "";
        payload.dataset_id = report ? report.dataset_id : "";
      }
      payload.catalog = getSelectValue("catalog");
      payload.dataset_name = payload.catalog;
      payload.workspace_id = payload.report_workspace_id;
      payload.workspace_name = payload.report_workspace_name;
    } else {
      var instance = null;
      var chosen = $("#desktopInstance").value;
      state.instances.forEach(function (item) {
        if (String(item.port) === chosen) instance = item;
      });
      payload.pbix = $("#pbixPath").value.trim();
      payload.port = instance ? instance.port : null;
      payload.catalog = instance ? instance.catalog : "";
    }
    return payload;
  }

  function renderExtractResult(result) {
    var report = result.report || null;
    var model = result.model || null;
    var batch = result.batch || [];
    if (!report && !model && !batch.length) {
      app.setChip($("#outputState"), "idle", "No results");
      return;
    }
    state.extractReady = Boolean(result.report_out) && !batch.length;
    if (result.report_out) $("#reportWorkbook").value = result.report_out;
    if (result.model_out) $("#modelWorkbook").value = result.model_out;
    app.setChip($("#outputState"), "ok", "Done");
    $("#extractDone").hidden = false;
    var notes = [];
    if (batch.length) notes.push(batch.length + " reports");
    if (report) notes.push((report.pages || 0) + " pages");
    if (model) notes.push((model.tables || 0) + " tables");
    $("#extractDoneText").textContent = notes.join(" · ") ||
      "Workbooks saved to the output folder.";
    if (batch.length && result.summary_out) {
      $("#extractDoneText").textContent += " · " + result.summary_out;
    }
    var stepParts = [];
    if (model) {
      stepParts.push((model.tables || 0) + " tables");
      stepParts.push((model.columns || 0) + " columns");
    } else if (report) {
      stepParts.push((report.pages || 0) + " pages");
    }
    $("#stepStateExtract").textContent = "Done · " + stepParts.join(" · ");
    app.setMetaStep("extract", false);
    $("#summaryEmpty").hidden = true;
    $("#summaryBody").hidden = false;
    $("#sumTables").textContent = model ? model.tables : "—";
    $("#sumColumns").textContent = model
      ? model.columns
      : (report ? report.columns : "—");
    $("#sumMeasures").textContent = model
      ? model.measures
      : (report ? report.measures : "—");
    $("#sumPages").textContent = report
      ? report.pages
      : (batch.length
        ? batch.reduce(function (total, row) {
          return total + (Number(row.Pages) || 0);
        }, 0)
        : "-");
    $("#sumRelations").textContent = model ? model.relationships : "—";
    if (result.model_error) app.addLog("Note: " + result.model_error, "warn");
    // Workbook paths now exist; refresh TSD checklist and unlock step 2.
    inspectTsd();
  }

  export function runExtraction() {
    if (!app.apiReady()) return;
    if (state.batchMode) {
      var selected = batchSelectedIds();
      if (selected.length < 2) {
        app.toast("Choose at least two reports for a batch");
        return;
      }
      if (batchDatasetIds().length > 1) {
        app.toast("Choose reports from the same dataset only.");
        return;
      }
    }
    var payload = buildMetadataPayload();
    $("#extractDone").hidden = true;
    $("#extractRun").hidden = false;
    $("#extractBar").style.width = "6%";
    $("#extractRunPct").textContent = "";
    $("#extractRunLabel").textContent = "Preparing extraction…";
    $("#stepStateExtract").textContent = "Running…";
    app.setChip($("#outputState"), "warn", "Running");
    var progress = 6;
    state.extractTimer = window.setInterval(function () {
      progress = Math.min(92, progress + (progress < 50 ? 6 : 2));
      $("#extractBar").style.width = progress + "%";
      $("#extractRunPct").textContent = progress + "%";
    }, 800);
    app.startJob({
      kind: "metadata",
      path: "/api/metadata/run",
      body: payload,
      label: "Metadata extraction",
      button: $("#runExtract"),
      onDone: function (snapshot) {
        $("#extractBar").style.width = "100%";
        $("#extractRunPct").textContent = "100%";
        renderExtractResult(snapshot.result || {});
        app.loadOutputs();
      }
    });
  }

  // -- Generate TSD -------------------------------------------------------
  function tsdPayload() {
    return {
      report_workbook: $("#reportWorkbook").value.trim(),
      model_workbook: $("#modelWorkbook").value.trim(),
      template_path: $("#template").value.trim(),
      manual_path: state.tsdManualCustom ? $("#contextJson").value.trim() : "",
      out_dir: $("#tsdOutFolder").value.trim(),
      out_name: $("#tsdFileName").value.trim(),
      report_name: $("#reportName").value.trim(),
      report_id: getSelectValue("shotReport"),
      generated_at: $("#docDate").value,
      draft: $("#tsdDraft").checked,
      expand_all: $("#tsdExpandAll").checked,
      screenshots: $("#shotEnabled").checked,
      workspace_id: getSelectValue("shotWorkspace"),
      rls_username: $("#shotRlsUser").value.trim(),
      rls_roles: $("#shotRlsRoles").value.trim(),
      shot_scope: getSelectValue("shotScope") || "both",
      shot_scale: Number(getSelectValue("shotScale") || 1),
      shot_mobile: $("#shotMobile").checked,
      include_decorative: $("#shotDecorative").checked,
      auto_install_browser: $("#shotAutoInstall").checked,
      debug: $("#shotDebug").checked,
      manual: state.tsdManual || {}
    };
  }

  function markChecklist(chipId, textId, label, ok, okText, idleText) {
    var chip = $("#" + chipId);
    if (!chip) return;
    chip.className = "chip " + (ok ? "chip-ok" : "chip-idle");
    chip.innerHTML = '<span class="dot"></span>' + label;
    var text = $("#" + textId);
    if (text) text.textContent = ok ? okText : idleText;
  }

  export function renderTsdState(data) {
    state.tsd = data;
    var form = data.form || {};
    var status = data.status || {};
    var paths = data.paths || {};
    $("#tsdOutFolder").value = paths.out_dir || form.out_dir || "";
    $("#tsdFileName").placeholder = paths.suggested_name
      ? "Automatic: " + paths.suggested_name
      : "Automatic from the report name";

    if (!state.tsdLoaded) {
      $("#reportWorkbook").value = form.report_workbook || "";
      $("#modelWorkbook").value = form.model_workbook || "";
      $("#template").value = form.template_path || "";
      $("#reportName").value = form.report_name || "";
      $("#docDate").value = form.generated_at || "";
      $("#tsdDraft").checked = Boolean(form.draft);
      $("#tsdExpandAll").checked = Boolean(form.expand_all);
      $("#shotEnabled").checked = Boolean(form.screenshots);
      $("#shotRlsUser").value = form.rls_username || "";
      $("#shotRlsRoles").value = form.rls_roles || "";
      setSelectValue("shotScope", form.shot_scope || "both");
      setSelectValue("shotScale", String(form.shot_scale || 1));
      $("#shotMobile").checked = form.shot_mobile !== false;
      $("#shotDecorative").checked = Boolean(form.include_decorative);
      $("#shotAutoInstall").checked = form.auto_install_browser !== false;
      state.tsdManualCustom = Boolean(form.manual_path) &&
        String(form.manual_path) !== String(paths.manual_path);
      $("#contextJson").value = paths.manual_path || "";
      state.tsdLoaded = true;
    } else if (!state.tsdManualCustom) {
      $("#contextJson").value = paths.manual_path || "";
    }

    $("#reportWorkbookStatus").textContent =
      (status.report && status.report.text) || "Not selected";
    $("#modelWorkbookStatus").textContent =
      (status.model && status.model.text) || "Unused";
    $("#tsdOutputState").textContent =
      (status.output && status.output.text) || "No TSD document yet.";

    var cache = status.cache || {};
    $("#shotCacheStatus").textContent = cache.exists
      ? (cache.summary)
      : "No cache yet; screenshots are captured during generation.";
    $("#shotCachePath").textContent = cache.path || paths.assets_dir || "";
    $("#clearShotCache").disabled = !cache.exists;
    app.setChip(
      $("#shotChip"),
      $("#shotEnabled").checked ? "ok" : "idle",
      $("#shotEnabled").checked ? "Active" : "Inactive"
    );

    var checklist = data.checklist || {};
    markChecklist(
      "checkReport", "checkReportText", "Report workbook",
      Boolean(checklist.report), "tersedia", "not selected"
    );
    markChecklist(
      "checkModel", "checkModelText", "Model workbook",
      Boolean(checklist.model), "tersedia", "opsional"
    );
    markChecklist(
      "checkTemplate", "checkTemplateText", "Template",
      Boolean(checklist.template), "found", "not found"
    );
    markChecklist(
      "checkContext", "checkContextText", "Manual context",
      Boolean(checklist.manual), "tersedia", "opsional"
    );

    var output = status.output || {};
    if (output.exists) {
      state.tsdOutputPath = paths.out_file || output.path || state.tsdOutputPath;
      $("#tsdPreviewEmpty").hidden = true;
      $("#tsdPreview").hidden = false;
      $("#openTsdFile").disabled = false;
      if (!state.tsdLastResult) {
        $("#tsdTodoNote").textContent =
          "The last document is available. Run Generate TSD to refresh the statistics.";
      }
    } else if (!state.tsdLastResult) {
      $("#tsdPreviewEmpty").hidden = false;
      $("#tsdPreview").hidden = true;
      $("#openTsdFile").disabled = true;
      state.tsdOutputPath = paths.out_file || "";
    }
    app.applyMetaSteps();
  }

  export function loadTsdState() {
    if (!app.apiReady()) return Promise.resolve();
    return app.api().get("/api/tsd/state").then(function (data) {
      renderTsdState(data);
      return data;
    }).catch(function (error) {
      app.addLog("TSD status could not be read: " + error.message, "warn");
    });
  }

  export function inspectTsd() {
    if (!app.apiReady()) return Promise.resolve(null);
    return app.api().post("/api/tsd/state", tsdPayload()).then(function (data) {
      renderTsdState(data);
      return data;
    }).catch(app.reportError);
  }

  export function scheduleTsdInspect() {
    if (state.tsdInspectTimer) window.clearTimeout(state.tsdInspectTimer);
    state.tsdInspectTimer = window.setTimeout(function () {
      state.tsdInspectTimer = null;
      inspectTsd();
    }, 300);
  }

  function startTsdProgress(label) {
    state.tsdRunning = true;
    $("#stepStateTsd").textContent = "Running…";
    $("#tsdRun").hidden = false;
    $("#tsdBar").style.width = "8%";
    $("#tsdRunPct").textContent = "";
    $("#tsdRunLabel").textContent = label || "Preparing the document…";
    var progress = 8;
    if (state.tsdTimer) window.clearInterval(state.tsdTimer);
    state.tsdTimer = window.setInterval(function () {
      progress = Math.min(92, progress + (progress < 50 ? 6 : 2));
      $("#tsdBar").style.width = progress + "%";
      $("#tsdRunPct").textContent = progress + "%";
    }, 800);
  }

  function renderTsdResult(result) {
    state.tsdLastResult = result;
    if (result.state) renderTsdState(result.state);
    var pages = result.pages || 0;
    var visuals = result.visuals || 0;
    var todos = result.todos || 0;
    $("#tsdStatSections").textContent = "6";
    $("#tsdStatPages").textContent = pages;
    $("#tsdStatVisuals").textContent = visuals;
    $("#tsdStatTables").textContent = result.tables == null ? "—" : result.tables;
    $("#tsdStatMeasures").textContent = result.measures == null ? "—" : result.measures;
    $("#tsdStatTodos").textContent = todos;
    $("#tsdTodoNote").innerHTML = todos
      ? (todos + " fields are marked <strong>TODO</strong> because they are empty in the manual context.")
      : "No TODO fields in this document.";
    var hasShots = Boolean(result.screenshot_root);
    $("#tsdShotRow").hidden = !hasShots;
    if (hasShots) {
      $("#tsdShotVal").textContent =
        (result.screenshot_pages || 0) + " pages · " +
        (result.screenshot_visuals || 0) + " visuals · " +
        (result.screenshot_mobile || 0) + " mobile";
    }
    state.tsdOutputPath = result.output || state.tsdOutputPath;
    $("#tsdPreviewEmpty").hidden = true;
    $("#tsdPreview").hidden = false;
    $("#openTsdFile").disabled = false;
    $("#tsdBar").style.width = "100%";
    $("#tsdRunPct").textContent = "100%";
    state.tsdRunning = false;
    $("#stepStateTsd").textContent = "Document ready";
    app.toast("TSD dibuat: " + pages + " pages / " + visuals + " visuals");
  }

  export function runTsd() {
    if (!app.apiReady()) return;
    startTsdProgress("Preparing the TSD document…");
    app.startJob({
      kind: "tsd",
      path: "/api/tsd/run",
      body: tsdPayload(),
      label: "Generate TSD",
      button: $("#runTsd"),
      onDone: function (snapshot) {
        renderTsdResult(snapshot.result || {});
      }
    });
  }

  export function loadTsdReports() {
    var workspaceId = getSelectValue("shotWorkspace");
    if (!workspaceId || !app.apiReady()) {
      setSelectOptions("shotReport", [], "Choose a report…");
      return Promise.resolve();
    }
    return app.api().get(
      "/api/metadata/workspaces/" + encodeURIComponent(workspaceId) +
      "/contents?datasets=false&reports=true"
    ).then(function (data) {
      state.tsdReports = data.reports || [];
      setSelectOptions("shotReport", state.tsdReports.map(function (item) {
        return { value: item.id, label: item.label, data: item };
      }), "Choose a report…");
      return data;
    }).catch(app.reportError);
  }

  export function captureTsdScreenshots() {
    if (!app.apiReady()) return;
    if (!$("#shotEnabled").checked) {
      app.toast("Check 'Capture screenshots' first");
      return;
    }
    if (!getSelectValue("shotWorkspace") || !getSelectValue("shotReport")) {
      app.toast("Choose a workspace and report for screenshots");
      return;
    }
    startTsdProgress("Capturing report screenshots…");
    app.startJob({
      kind: "tsd_capture",
      path: "/api/tsd/capture",
      body: tsdPayload(),
      label: "Capture report screenshots",
      button: $("#captureScreenshots"),
      onDone: function (snapshot) {
        var result = snapshot.result || {};
        app.toast(
          "Screenshot: " + (result.pages || 0) + " pages / " +
          (result.visuals || 0) + " visuals"
        );
        inspectTsd();
      }
    });
  }

  export function clearTsdCache() {
    if (!app.apiReady()) return;
    if (!window.confirm("Clear the TSD screenshot cache for this report?")) return;
    app.api().post("/api/tsd/cache/clear", tsdPayload()).then(function (data) {
      if (data.state) renderTsdState(data.state);
      app.toast(data.removed ? "Screenshot cache cleared" : "No cache yet");
    }).catch(app.reportError);
  }

  export function openTsdDocument() {
    var path = state.tsdOutputPath ||
      (state.tsd && state.tsd.paths && state.tsd.paths.out_file) || "";
    if (!path) {
      app.toast("No TSD document yet");
      return;
    }
    window.open(
      "/api/tsd/preview?path=" + encodeURIComponent(path),
      "_blank",
      "noopener"
    );
  }

  export function openTsdFolder() {
    var path = state.tsdOutputPath ||
      (state.tsd && state.tsd.paths && state.tsd.paths.out_file) || "";
    var folder = path ? app.parentDir(path) : $("#tsdOutFolder").value.trim();
    if (!folder) {
      app.toast("Output folder not set");
      return;
    }
    app.api().post("/api/files/open", { path: folder, mode: "open" }).catch(app.reportError);
  }

  export function loadTsdManual(quiet) {
    if (!app.apiReady()) return Promise.resolve(null);
    var path = tsdManualPath();
    return app.api().get("/api/tsd/manual?path=" + encodeURIComponent(path)).then(function (data) {
      state.tsdManual = data.data || {};
      $("#contextJson").value = data.path || path;
      state.tsdManualCustom = true;
      $("#contextStatus").textContent = data.exists
        ? "Sidecar loaded."
        : "No sidecar yet; new content is written when you save.";
      if (!quiet) app.toast(data.exists ? "Manual context loaded" : "Sidecar not found");
      scheduleTsdInspect();
      return data;
    }).catch(app.reportError);
  }

  export function saveTsdManualFile(data, quiet) {
    if (!app.apiReady()) return Promise.resolve(null);
    var path = tsdManualPath();
    return app.api().put("/api/tsd/manual", {
      path: path,
      data: data || {}
    }).then(function (result) {
      state.tsdManual = result.data || {};
      state.tsdManualCustom = true;
      $("#contextJson").value = result.path || path;
      $("#contextStatus").textContent = "Sidecar saved.";
      if (!quiet) app.toast("Manual context saved");
      scheduleTsdInspect();
      return result;
    }).catch(app.reportError);
  }

  function tsdManualPath() {
    var value = $("#contextJson").value.trim();
    if (value) return value;
    return (state.tsd && state.tsd.paths && state.tsd.paths.manual_path) || "";
  }

  export function openJsonDialog() {
    if (!app.apiReady()) return;
    loadTsdManual(true).then(function () {
      $("#jsonDialogPath").textContent = tsdManualPath();
      $("#jsonEditor").value = JSON.stringify(state.tsdManual || {}, null, 2);
      $("#jsonStatus").textContent = "JSON must be an object. Save writes a sidecar at the path above.";
      $("#jsonDialog").showModal();
      $("#jsonEditor").focus();
    });
  }

  export function saveJsonDialog() {
    var text = $("#jsonEditor").value.trim();
    var data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        $("#jsonStatus").textContent = "Invalid JSON: " + error.message;
        return;
      }
    }
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
      $("#jsonStatus").textContent = "JSON content must be an object (not an array/null).";
      return;
    }
    saveTsdManualFile(data, true).then(function (result) {
      if (result) {
        $("#jsonDialog").close();
        app.toast("Manual context saved");
      }
    });
  }

  // -- Analisa Semantic Model --------------------------------------------
