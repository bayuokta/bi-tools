import { state, store } from "./js/core/state.js";
import { $, $$, escapeHtml } from "./js/core/dom.js";
import { i18n, t, tr, currentLanguage } from "./js/core/i18n.js";
import { decimalText, fmtInt, sizeText, fileMeta } from "./js/core/format.js";
import {
  enhanceAllSelects,
  getSelectItem,
  getSelectValue,
  initComboEvents,
  refreshCombo,
  setSelectOptions,
  setSelectValue
} from "./js/core/combo.js";

import {
  compareLoadState,
  initCompareEvents,
  renderCompare
} from "./js/views/compare.js";

import { app } from "./js/core/app_api.js";
import {
  analysisCloseMenu,
  analysisCloseSubmenu,
  analysisCopyItemJson,
  analysisExport,
  analysisExportLineageImage,
  analysisHealthOpen,
  analysisIsOpen,
  analysisItemTabs,
  analysisLineageApplySearch,
  analysisLineageApplyView,
  analysisLineageApplyZoom,
  analysisLineageClearHighlight,
  analysisLineageConsumeDragClick,
  analysisLineageDirectionButtons,
  analysisLineageDragPositions,
  analysisLineageDragScope,
  analysisLineageDragTarget,
  analysisLineageEdges,
  analysisLineageFit,
  analysisLineageMoveItems,
  analysisLineageOpen,
  analysisLineagePngData,
  analysisLineageRefreshEdges,
  analysisLineageReroot,
  analysisLineageSelect,
  analysisLineageSelectMembers,
  analysisLineageTreeEdges,
  analysisLineageViewButtons,
  analysisLineageZoomBy,
  analysisLoad,
  analysisLoadDatasets,
  analysisLoadLineage,
  analysisNote,
  analysisOpenBpRules,
  analysisOpenHealthRules,
  analysisOpenMenu,
  analysisOpenSubmenu,
  analysisPrettyJson,
  analysisReloadRawMetadata,
  analysisRender,
  analysisRenderItemDetails,
  analysisResetPreview,
  analysisResetRawMetadata,
  analysisRowTarget,
  analysisRun,
  analysisRunMenuAction,
  analysisRunPreview,
  analysisSavePrefs,
  analysisSetSort,
  analysisSetTab,
  analysisSetZoom,
  analysisStop,
  analysisSyncRelView,
  analysisSyncReportOptions,
  applyAnalysisCellTitles,
  applyAnalysisZoom,
  copyTextValue
} from "./js/views/analysis.js";
import {
  applyReportDefaults,
  batchReports,
  captureTsdScreenshots,
  clearTsdCache,
  inspectTsd,
  loadInstances,
  loadModelContents,
  loadReportContents,
  loadTsdManual,
  loadTsdReports,
  loadTsdState,
  loadWorkspaces,
  openJsonDialog,
  openTsdDocument,
  openTsdFolder,
  refreshPbix,
  renderBatchHint,
  renderModelAvailability,
  renderTsdState,
  runExtraction,
  runTsd,
  saveJsonDialog,
  saveTsdManualFile,
  scheduleTsdInspect,
  setBatchMode
} from "./js/views/metadata-tsd.js";
import {
  applyLineageZoom,
  lineageExport,
  lineageExportImage,
  lineageLayout,
  lineageLoadState,
  lineageOpen,
  lineageRenderDetail,
  lineageRenderGraph,
  lineageSearch,
  lineageSelectNode,
  lineageSetDepth,
  lineageSetDirection,
  partitionCloseDialog,
  partitionConfirmProcess,
  partitionLoadDatasets,
  partitionLoadInventory,
  partitionLoadState,
  partitionOpenConfirm,
  partitionRender,
  partitionToggleAll,
  setLineageZoom
} from "./js/views/partitions-lineage.js";

var NEWLINE = String.fromCharCode(10);


  var toastTimer = 0;
  function toast(message) {
    var box = $("#toast");
    $("#toastText").textContent = message;
    box.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      box.classList.remove("show");
    }, 2600);
  }

  function applyTheme(mode, announce) {
    state.theme = mode === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = state.theme;
    store.set("pbi-theme", state.theme);
    if (announce && state.ready && !state.applying && window.BIToolsApi) {
      window.BIToolsApi.put("/api/settings/ui", { theme: state.theme }).catch(function () {
        toast(t("Theme could not be saved to the server"));
      });
    }
    $$(".theme-card[data-theme]").forEach(function (card) {
      card.setAttribute("aria-checked", card.dataset.theme === state.theme ? "true" : "false");
    });
    if (announce) {
      toast("Tema " + (state.theme === "dark" ? "gelap" : "terang") + " diterapkan");
    }
  }

  function applyMotion(enabled, announce) {
    state.motion = Boolean(enabled);
    document.documentElement.classList.toggle("no-motion", !state.motion);
    var toggle = $("#motionToggle");
    if (toggle) toggle.checked = state.motion;
    store.set("pbi-motion", state.motion ? "on" : "off");
    if (announce && state.ready && !state.applying && window.BIToolsApi) {
      window.BIToolsApi.put("/api/settings/ui", { motion: state.motion }).catch(function () {});
    }
    if (announce) {
      toast(state.motion ? t("Interface animations enabled") : t("Interface animations disabled"));
    }
  }

  function applySidebar(collapsed, persist) {
    state.sidebarCollapsed = Boolean(collapsed);
    document.documentElement.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
    var toggle = $("#sidebarToggle");
    if (toggle) {
      var text = state.sidebarCollapsed ? t("Open sidebar") : t("Collapse sidebar");
      var label = toggle.querySelector(".label");
      toggle.setAttribute("aria-expanded", String(!state.sidebarCollapsed));
      toggle.setAttribute("aria-label", text);
      toggle.title = text;
      if (label) label.textContent = text;
    }
    if (persist) {
      store.set("pbi-sidebar", state.sidebarCollapsed ? "collapsed" : "open");
    }
  }

  function applyLanguage(language, options) {
    var opts = options || {};
    var next = language === "id" ? "id" : "en";
    state.language = next;
    store.set("pbi-lang", next);
    if (state.settings && state.settings.ui) {
      state.settings.ui.language = next;
    }
    if (i18n) i18n.setLanguage(next);
    document.documentElement.lang = next;
    $$(".theme-card[data-language]").forEach(function (card) {
      card.setAttribute("aria-checked", card.dataset.language === next ? "true" : "false");
    });
    if (opts.rerender !== false) {
      rerenderLanguage();
    }
    if (opts.persist && state.ready && !state.applying && window.BIToolsApi) {
      window.BIToolsApi.put("/api/settings/ui", { language: next }).catch(function () {
        toast(t("Language could not be saved to the server"));
      });
    }
    if (opts.announce) {
      toast(t(next === "id"
        ? "Interface language set to Indonesian"
        : "Interface language set to English"));
    }
  }

  function applyComboLanguage() {
    $$("select").forEach(function (select) {
      var key = select.dataset.i18nPlaceholder;
      var head = select.querySelector("option[value='']");
      if (key && head) head.textContent = t(key);
      refreshCombo(select);
    });
  }

  function rerenderLanguage() {
    if (state.settings) renderSettings(state.settings);
    if (state.tsd) renderTsdState(state.tsd);
    if (state.analysis !== undefined) analysisRender();
    if (state.compare) renderCompare();
    if (state.partitions !== null) partitionRender();
    applyMetaSteps();
    if (state.lineageGraph) {
      lineageRenderGraph();
      if (state.selectedId && state.lineageNodesLive[state.selectedId]) {
        lineageRenderDetail(state.lineageNodesLive[state.selectedId].payload || {});
      }
    }
    if (!state.lineageGraph && state.lineageHasDb && !state.lineageQuery) {
      $("#lineageResults").innerHTML =
        '<div class="empty" style="padding:18px 8px"><div class="empty-title">' +
        t("No search yet") + "</div>" +
        '<p class="empty-text">' +
        t("Search for a report, semantic model, table, or measure.") + "</p></div>";
    }
    if (state.system) {
      $("#appVersion").textContent = t("Version ") + state.system.version;
      $("#serverMeta").textContent = "Data: " + state.system.data_dir +
        " \u00b7 " + t("Preferences: ") + state.system.settings.path;
    }
    $("#depthVal").textContent = state.depth + t(" levels");
    $("#workspaceHint").textContent = tr(state.workspaceHint) ||
      t("Type a workspace name to filter, or open the list.");
    $("#instanceHint").textContent = tr(state.instanceHint) || "";
    var selectedReport = getSelectItem("serviceReport");
    if (selectedReport) {
      applyReportDefaults(selectedReport);
    } else {
      $("#reportHint").textContent = "";
    }
    if (!state.pbix) {
      $("#pbixKind").textContent = t("Choose the source .pbix file.");
    }
    renderModelAvailability();
    renderLog();
    if (state.ready) {
      loadCatalogStatus();
      loadOutputs();
    }
    applyComboLanguage();
    $$(".theme-card[data-language]").forEach(function (card) {
      card.setAttribute("aria-checked", card.dataset.language === state.language ? "true" : "false");
    });
  }

  function showView(name) {
    if (!name || !$("#view-" + name)) return;
    state.view = name;
    $$(".view").forEach(function (section) {
      if (section.id === "view-tsd") return;
      section.hidden = section.id !== "view-" + name;
    });
    $$(".nav-item").forEach(function (button) {
      if (button.dataset.view === name) {
        button.setAttribute("aria-current", "page");
      } else {
        button.removeAttribute("aria-current");
      }
    });
    $("#viewScroll").scrollTop = 0;
    var heading = $("#view-" + name + " .view-title");
    if (heading) heading.focus({ preventScroll: true });
    applyMetaSteps();
    if (name === "lineage" && state.lineageHasDb && !state.lineageData) {
      lineageLoadState();
    }
    if (name === "partisi" && !state.partitionStateLoaded) {
      partitionLoadState();
    }
    if (name === "compare" && !state.compareLoaded) {
      compareLoadState();
    }
  }

  function tsdUnlocked() {
    if (state.extractReady) return true;
    var checklist = (state.tsd && state.tsd.checklist) || {};
    return Boolean(checklist.report);
  }

  function applyMetaSteps() {
    var unlocked = tsdUnlocked();
    var tsdButton = $('#metaSteps [data-meta-step="tsd"]');
    if (tsdButton) {
      tsdButton.classList.toggle("is-locked", !unlocked);
      if (unlocked) tsdButton.removeAttribute("aria-disabled");
      else tsdButton.setAttribute("aria-disabled", "true");
    }
    $$("#metaSteps [data-meta-step]").forEach(function (button) {
      var active = button.dataset.metaStep === state.metaStep;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
    var lock = $("#tsdLock");
    if (lock) lock.hidden = unlocked;
    var tsdView = $("#view-tsd");
    if (tsdView) tsdView.hidden = !(state.view === "ekstraksi" && unlocked);
    var tsdState = $("#stepStateTsd");
    if (tsdState && !state.tsdRunning) {
      if (!unlocked) tsdState.textContent = t("Waiting for extraction");
      else if (state.tsdLastResult) tsdState.textContent = t("Document ready");
      else tsdState.textContent = t("Ready");
    }
  }

  function setMetaStep(name, scroll) {
    if (name === "tsd" && !tsdUnlocked()) {
      toast(t("Run the metadata extraction first"));
      return;
    }
    state.metaStep = name;
    applyMetaSteps();
    if (scroll === false) return;
    var target = name === "tsd" ? $("#view-tsd") : $("#view-ekstraksi");
    if (target && target.scrollIntoView) {
      target.scrollIntoView({
        behavior: state.motion ? "smooth" : "auto",
        block: "start"
      });
    }
    if (name === "tsd") {
      var heading = $("#titleTsd");
      if (heading) heading.focus({ preventScroll: true });
    }
  }

  function addLog(text, level) {
    var now = new Date();
    var time = now.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    state.logs.push({ time: time, text: text, level: level || "info" });
    renderLog();
  }

  function renderLog() {
    var log = $("#consoleLog");
    log.innerHTML = state.logs.map(function (entry) {
      return '<span class="log-time">[' + entry.time + "]</span> " +
        '<span class="log-' + entry.level + '">' + escapeHtml(entry.text) + "</span>";
    }).join(NEWLINE);
    var scroller = $("#consoleBody");
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
    var count = state.logs.length;
    var badge = $("#consoleCount");
    badge.textContent = String(count);
    badge.hidden = count === 0;
    $("#consolePreview").textContent = count ? state.logs[count - 1].text : t("No activity in this session yet.");
  }

  function setConsole(open) {
    $("#consoleBody").hidden = !open;
    $("#consoleToggle").setAttribute("aria-expanded", String(open));
    $("#consoleChevron").style.transform = open ? "rotate(180deg)" : "none";
    var workspace = $(".workspace");
    if (workspace) workspace.classList.toggle("console-open", open);
    if (open) {
      var scroller = $("#consoleBody");
      scroller.scrollTop = scroller.scrollHeight;
    }
  }

  function setSource(source) {
    state.source = source;
    $("#paneDesktop").hidden = source !== "desktop";
    $("#paneService").hidden = source !== "service";
    $("#srcBtnDesktop").setAttribute("aria-pressed", String(source === "desktop"));
    $("#srcBtnService").setAttribute("aria-pressed", String(source === "service"));
    if (state.ready && !state.applying && window.BIToolsApi) {
      window.BIToolsApi.put("/api/settings/extraction", {
        active_tab: source === "service" ? "service" : "local"
      }).catch(function () {});
    }
    if (state.settings) {
      var scopes = state.settings.extraction;
      $("#scope").value = source === "service" ? scopes.scope_service : scopes.scope_local;
      refreshCombo($("#scope"));
    }
  }


  function showSettingsTab(name) {
    $$("#view-pengaturan .tabs [role='tab']").forEach(function (tab) {
      tab.setAttribute("aria-selected", tab.dataset.tab === name ? "true" : "false");
    });
    $$("[role='tabpanel']", $("#view-pengaturan")).forEach(function (panel) {
      panel.hidden = panel.id !== "set-" + name;
    });
  }

  // -- integrasi server lokal -------------------------------------------
  function api() {
    return window.BIToolsApi;
  }

  function apiReady() {
    return Boolean(window.BIToolsApi);
  }

  function pendingFeature(name) {
    toast(name + t(" is planned for a later stage"));
  }

  function reportError(error) {
    var message = error && error.message ? tr(error.message) : String(error);
    addLog(message, "error");
    toast(message);
    return message;
  }

  function logLine(text) {
    var value = String(text == null ? "" : text);
    var level = "info";
    if (/^(ERROR|GAGAL)/i.test(value)) level = "error";
    else if (/^(CATATAN|PERINGATAN|WARN)/i.test(value)) level = "warn";
    addLog(value, level);
  }

  function setChip(element, tone, label) {
    if (!element) return;
    var map = { ok: "chip-ok", warn: "chip-warn", error: "chip-danger", idle: "chip-idle", info: "chip-info" };
    element.className = "chip " + (map[tone] || "chip-idle");
    element.innerHTML = '<span class="dot"></span>' + label;
  }

  function savePreference(part, payload) {
    if (!apiReady()) return Promise.resolve(null);
    return api().put("/api/settings/" + part, payload).then(function (data) {
      renderSettings(data);
      return data;
    }).catch(function (error) {
      reportError(error);
      return null;
    });
  }

  function loadSystem() {
    if (!apiReady()) return;
    api().get("/api/system/state").then(function (data) {
      state.system = data;
      $("#brandVersion").textContent = data.version;
      $("#appVersion").textContent = t("Version ") + data.version;
      $("#serverUrl").value = window.location.origin + "/";
      $("#serverMeta").textContent = "Data: " + data.data_dir + " \u00b7 " + t("Preferences: ") + data.settings.path;
      document.title = "BI Tools " + data.version + " - Metadata Power BI";
      addLog("BI Tools " + data.version + t(" ready at ") + window.location.origin, "ok");
    }).catch(function (error) {
      addLog(t("The local server did not respond: ") + error.message, "error");
    });
  }

  function loadSettings() {
    if (!apiReady()) return;
    api().get("/api/settings").then(function (data) {
      renderSettings(data);
      state.ready = true;
    }).catch(function (error) {
      addLog(t("Preferences could not be loaded: ") + error.message, "error");
    });
  }

  function renderSettings(data) {
    state.settings = data;
    state.applying = true;
    $("#clientSecret").placeholder = data.auth.has_secret
      ? t("Saved - leave blank to keep unchanged")
      : "Client secret";
    if (!state.formDirty) {
      $("#tenantId").value = data.auth.tenant_id;
      $("#clientId").value = data.auth.client_id;
      $("#clientSecret").value = "";
      $("#rlsUsername").value = data.rls.username;
      $("#rlsRoles").value = data.rls.roles;
      $("#dbPath").value = data.paths.lineage_db;
    }
    setChip(
      $("#credChip"),
      data.auth.complete ? "ok" : (data.auth.has_secret ? "warn" : "idle"),
      data.auth.complete ? t("Complete") : (data.auth.has_secret ? t("Not complete") : t("Not filled in"))
    );
    $("#connResult").textContent = tr(data.auth.status);
    $("#syncMode").value = data.catalog.mode;
    refreshCombo($("#syncMode"));
    $("#includePersonal").checked = data.catalog.include_personal;
    $("#showConsole").checked = data.ui.show_console;
    if (data.ui.language && data.ui.language !== state.language) {
      applyLanguage(data.ui.language, { rerender: false });
    } else {
      $$(".theme-card[data-language]").forEach(function (card) {
        card.setAttribute(
          "aria-checked",
          card.dataset.language === state.language ? "true" : "false"
        );
      });
    }
    if (data.ui.theme !== state.theme) applyTheme(data.ui.theme, false);
    if (data.ui.motion !== state.motion) applyMotion(data.ui.motion, false);
    setSource(data.extraction.active_tab === "service" ? "service" : "desktop");
    state.applying = false;
  }

  function renderCatalogStatus(data) {
    setChip(
      $("#syncChip"),
      data.tone === "ok" ? "ok" : (data.tone === "error" ? "error" : "idle"),
      data.tone === "ok" ? t("In sync") : (data.tone === "error" ? t("Problem") : t("Not in sync"))
    );
    $("#syncStatus").textContent = tr(data.text) || t("No saved workspace catalog");
    $("#catalogCount").textContent = data.selectable
      ? fmtInt(data.selectable)
      : (data.total ? fmtInt(data.total) : "-");
    $("#catalogCount").title = data.total
      ? data.total + t(" workspaces saved")
      : t("No catalog yet");
    $("#catalogSync").textContent = data.last_sync || "-";
  }

  function loadCatalogStatus() {
    if (!apiReady()) return;
    api().get("/api/catalog/status").then(renderCatalogStatus).catch(function (error) {
      addLog(t("Catalog status could not be read: ") + error.message, "warn");
    });
  }

  function renderOutputs(data) {
    state.outputs = data;
    $("#outFolder").value = data.folder || "";
    $("#metaReport").textContent = fileMeta(data.report);
    $("#metaModel").textContent = fileMeta(data.model);
    $("#openReport").disabled = !(data.report && data.report.exists);
    $("#openModel").disabled = !(data.model && data.model.exists);
    $("#openFolder").disabled = !data.exists;
  }

  function loadOutputs() {
    if (!apiReady()) return;
    api().get("/api/files/outputs").then(renderOutputs).catch(function (error) {
      addLog(t("Output status could not be read: ") + error.message, "warn");
    });
  }

  function openOutput(which) {
    var entry = state.outputs && state.outputs[which];
    if (!entry || !entry.exists) {
      toast(t("File not created yet"));
      return;
    }
    api().post("/api/files/open", { path: entry.path, mode: "open" }).catch(reportError);
  }

  function revealOutputFolder() {
    var folder = state.outputs && state.outputs.folder;
    if (!folder) return;
    api().post("/api/files/open", { path: folder, mode: "open" }).catch(reportError);
  }

  function finishJob(options, snapshot) {
    var status = (snapshot && snapshot.status) || "done";
    if (state.extractTimer) {
      window.clearInterval(state.extractTimer);
      state.extractTimer = null;
    }
    if (options.kind === "metadata") {
      if (status === "error") {
        setChip($("#outputState"), "error", t("Failed"));
        $("#stepStateExtract").textContent = t("Not run yet");
      } else if (status === "cancelled") {
        setChip($("#outputState"), "idle", t("Cancelled"));
        $("#stepStateExtract").textContent = t("Not run yet");
      }
      window.setTimeout(function () { $("#extractRun").hidden = true; }, 900);
    }
    if (options.kind === "analysis") {
      state.analysisRunning = false;
      $("#stopAnalyze").hidden = true;
      $("#runAnalyze").disabled = false;
    }
    if (options.kind === "partitions-inventory" || options.kind === "partitions-refresh") {
      state.partitionRunning = false;
    }
    if (options.kind === "tsd" || options.kind === "tsd_capture") {
      if (state.tsdTimer) {
        window.clearInterval(state.tsdTimer);
        state.tsdTimer = null;
      }
      if (status !== "done") state.tsdRunning = false;
      window.setTimeout(function () { $("#tsdRun").hidden = true; }, 900);
      if (status === "done") inspectTsd();
    }
    if (status === "error") {
      var message = (snapshot && snapshot.error) || t("Job failed.");
      addLog(message, "error");
      toast(message);
      if (options.onError) options.onError(snapshot || {}, message);
    } else if (status === "cancelled") {
      addLog(t("Job cancelled."), "warn");
      toast(t("Job cancelled"));
      if (options.onError) options.onError(snapshot || {}, t("Job cancelled"));
    } else if (options.onDone) {
      options.onDone(snapshot || {});
    }
    if (!options.silent) {
      loadCatalogStatus();
      loadSettings();
    }
  }

  function pollJob(jobId, options) {
    var timer = window.setInterval(function () {
      api().get("/api/jobs/" + encodeURIComponent(jobId)).then(function (snapshot) {
        if (snapshot.status === "running") return;
        window.clearInterval(timer);
        state.jobId = null;
        state.jobStream = null;
        if (options.button) options.button.disabled = false;
        (snapshot.log || []).slice(state.jobLogCount || 0).forEach(logLine);
        finishJob(options, snapshot);
      }).catch(function (error) {
        window.clearInterval(timer);
        state.jobId = null;
        state.jobStream = null;
        if (options.button) options.button.disabled = false;
        reportError(error);
      });
    }, 1500);
  }

  function startJob(options) {
    if (!apiReady()) {
      pendingFeature(options.label || t("This job"));
      return;
    }
    if (state.jobId) {
      if (options.onBusy) options.onBusy();
      else toast(t("Another job is still running"));
      return;
    }
    state.jobLogCount = 0;
    if (!options.silent) setConsole(true);
    addLog((options.label || t("Job")) + t(" started."), "info");
    if (options.button) options.button.disabled = true;
    api().post(options.path, options.body || {}).then(function (data) {
      state.jobId = data.job_id;
      state.jobStream = api().streamJob(data.job_id, {
        onLog: function (line) {
          state.jobLogCount += 1;
          logLine(line);
        },
        onState: function (snapshot) {
          state.lastJob = snapshot;
        },
        onEnd: function (end) {
          state.jobId = null;
          state.jobStream = null;
          if (options.button) options.button.disabled = false;
          var snapshot = state.lastJob || { status: end.status };
          finishJob(options, snapshot);
        },
        onError: function (error) {
          addLog(t("Live log disconnected (") + error.message + t("); switching to polling."), "warn");
          pollJob(data.job_id, options);
        }
      });
    }).catch(function (error) {
      if (options.button) options.button.disabled = false;
      var message = reportError(error);
      finishJob(options, { status: "error", error: message });
    });
  }

  function parentDir(path) {
    var text = String(path || "");
    var index = Math.max(text.lastIndexOf("\\"), text.lastIndexOf("/"));
    return index > 1 ? text.slice(0, index) : "";
  }

  function browseRow(name, target, isDir, selected) {
    return '<button class="browse-item' + (selected ? " is-selected" : "") +
      '" type="button" role="option" data-path="' + escapeHtml(target) +
      '" data-dir="' + (isDir ? "1" : "0") + '">' +
      '<span class="name">' + escapeHtml(name) + "</span>" +
      '<span class="helper">' + (isDir ? t("folder") : t("file")) + "</span></button>";
  }

  function renderBrowse(data) {
    state.pickDir = data.path || "";
    $("#folderDialogPath").textContent = data.path || t("Choose a drive");
    $("#folderPathInput").value = data.path || "";
    var choosingFile = state.pickKind === "file";
    $("#chooseFolder").textContent = choosingFile ? t("Choose this file") : t("Choose this folder");
    $("#chooseFolder").disabled = choosingFile ? !state.pickFile : !state.pickDir;
    $("#folderDialogTitle").textContent = choosingFile
      ? t("Choose file ") + (state.pickExt || "")
      : t("Choose folder");
    var html = "";
    if (data.parent) html += browseRow("..", data.parent, true, false);
    html += (data.entries || []).map(function (entry) {
      var selected = !entry.is_dir && state.pickFile === entry.path;
      return browseRow(entry.name, entry.path, entry.is_dir, selected);
    }).join("");
    if (!html) html = '<div class="browse-empty">Folder kosong.</div>';
    var list = $("#folderList");
    list.innerHTML = html;
    $$(".browse-item", list).forEach(function (button) {
      button.addEventListener("click", function () {
        if (button.dataset.dir === "1") {
          state.pickFile = null;
          browseFolder(button.dataset.path);
          return;
        }
        state.pickFile = button.dataset.path;
        $$(".browse-item", list).forEach(function (item) {
          item.classList.remove("is-selected");
        });
        button.classList.add("is-selected");
        $("#chooseFolder").disabled = false;
      });
    });
  }

  function browseFolder(target) {
    if (!apiReady()) return;
    api().get(
      "/api/files/browse?kind=" + encodeURIComponent(state.pickKind) +
      "&ext=" + encodeURIComponent(state.pickExt) +
      "&path=" + encodeURIComponent(target || "")
    ).then(renderBrowse).catch(reportError);
  }

  function openFolderPicker(start, onChoose) {
    state.pickKind = "dir";
    state.pickExt = "";
    state.pickFile = null;
    state.pickCallback = onChoose || null;
    state.pickDir = "";
    if (!$("#folderDialog").open) $("#folderDialog").showModal();
    browseFolder(start || "");
  }

  function openFilePicker(start, ext, onChoose) {
    state.pickKind = "file";
    state.pickExt = ext || "";
    state.pickFile = null;
    state.pickCallback = onChoose || null;
    state.pickDir = "";
    if (!$("#folderDialog").open) $("#folderDialog").showModal();
    browseFolder(start || "");
  }

  function bootstrap() {
    if (!apiReady()) {
      addLog("Klien API tidak termuat; antarmuka berjalan dalam mode pratinjau.", "warn");
      return;
    }
    loadSystem();
    loadSettings();
    loadCatalogStatus();
    loadOutputs();
    loadInstances();
    loadWorkspaces();
    loadTsdState();
    analysisLoad();
    partitionLoadState();
    lineageLoadState();
  }

  // -- ekstraksi metadata -------------------------------------------------
  function init() {
    initComboEvents();
    enhanceAllSelects();
    initCompareEvents();
    applyLanguage(state.language, { rerender: false });
    applyTheme(state.theme, false);
    applyMotion(state.motion, false);
    setSource(state.source);

    $$(".nav-item[data-view]").forEach(function (button) {
      button.addEventListener("click", function () {
        showView(button.dataset.view);
      });
    });

    $$(".theme-card[data-theme]").forEach(function (card) {
      card.addEventListener("click", function () {
        applyTheme(card.dataset.theme, true);
      });
      card.addEventListener("keydown", function (event) {
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          event.preventDefault();
          var next = state.theme === "dark" ? "light" : "dark";
          applyTheme(next, true);
          var target = $$(".theme-card[data-theme]").filter(function (item) { return item.dataset.theme === next; })[0];
          if (target) target.focus();
        }
      });
    });

    $("#motionToggle").addEventListener("change", function (event) {
      applyMotion(event.target.checked, true);
    });

    $$(".theme-card[data-language]").forEach(function (card) {
      card.addEventListener("click", function () {
        applyLanguage(card.dataset.language, { persist: true, announce: true });
      });
      card.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
        event.preventDefault();
        var next = state.language === "en" ? "id" : "en";
        applyLanguage(next, { persist: true });
        var target = $$(".theme-card[data-language]").filter(function (item) {
          return item.dataset.language === next;
        })[0];
        if (target) target.focus();
      });
    });

    $("#consoleToggle").addEventListener("click", function () {
      setConsole($("#consoleBody").hidden);
    });

    $("#clearLog").addEventListener("click", function () {
      state.logs = [];
      renderLog();
      toast(t("Console log cleared"));
    });

    $("#srcBtnDesktop").addEventListener("click", function () { setSource("desktop"); });
    $("#srcBtnService").addEventListener("click", function () { setSource("service"); });

    $("#reloadDesktop").addEventListener("click", function () {
      loadInstances().then(function () { toast(t("Instance list refreshed")); });
    });

    $("#reloadWorkspaces").addEventListener("click", function () {
      loadWorkspaces().then(function () {
        if (getSelectValue("modelWorkspace")) loadModelContents();
        if (getSelectValue("reportWorkspace")) loadReportContents();
        toast(t("Workspace catalog loaded"));
      });
    });

    $("#reloadReport").addEventListener("click", function () {
      if (!getSelectValue("reportWorkspace")) {
        toast(t("Choose a report workspace first"));
        return;
      }
      loadReportContents().then(function () { toast(t("Report list loaded")); });
    });

    $("#pickPbix").addEventListener("click", function () {
      openFilePicker(parentDir($("#pbixPath").value), ".pbix", function (chosen) {
        $("#pbixPath").value = chosen;
        refreshPbix();
      });
    });

    $("#desktopInstance").addEventListener("change", function () {
      renderModelAvailability();
    });

    $("#modelWorkspace").addEventListener("change", function () {
      if (!this.value) {
        $("#xmlaEndpoint").value = "";
        setSelectOptions("catalog", [], "Choose a dataset…");
        $("#workspaceHint").textContent = "";
        return;
      }
      loadModelContents();
    });

    $("#reportWorkspace").addEventListener("change", function () {
      if (!this.value) {
        setSelectOptions("serviceReport", [], "Choose a report…");
        $("#reportHint").textContent = "";
        return;
      }
      loadReportContents();
    });

    $("#catalog").addEventListener("change", function () {
      var item = getSelectItem("catalog");
      if (item && item.data) {
        $("#workspaceHint").textContent = "";
      }
    });

    $("#serviceReport").addEventListener("change", function () {
      var item = getSelectItem("serviceReport");
      if (item && item.data) applyReportDefaults(item.data);
    });

    $("#batchRow").hidden = true;
    $("#batchMode").addEventListener("change", function () {
      setBatchMode($("#batchMode").checked);
    });
    $("#batchReports").addEventListener("change", function (event) {
      var target = event.target;
      if (!target || !target.getAttribute("data-batch-id")) return;
      var id = target.getAttribute("data-batch-id");
      state.batchSelected[id] = target.checked;
      renderBatchHint();
    });
    $("#runExtract").addEventListener("click", runExtraction);
    $("#runTsd").addEventListener("click", runTsd);

    $("#goTsd").addEventListener("click", function () { setMetaStep("tsd"); });
    $("#doneToTsd").addEventListener("click", function () { setMetaStep("tsd"); });
    $("#backToExtract").addEventListener("click", function () { setMetaStep("extract"); });
    $$("#metaSteps [data-meta-step]").forEach(function (button) {
      button.addEventListener("click", function () {
        setMetaStep(button.dataset.metaStep);
      });
    });

    $("#openReport").addEventListener("click", function () { openOutput("report"); });
    $("#openModel").addEventListener("click", function () { openOutput("model"); });
    $("#openFolder").addEventListener("click", function () { revealOutputFolder(); });
    $("#openTsd").addEventListener("click", openTsdDocument);
    $("#previewOpenTsd").addEventListener("click", openTsdDocument);
    $("#pickFolder").addEventListener("click", function () {
      openFolderPicker($("#outFolder").value, function (folder) {
        savePreference("extraction", { out_dir: folder }).then(function () {
          loadOutputs();
          toast(t("Output folder saved"));
        });
      });
    });

    $("#loadContext").addEventListener("click", function () { loadTsdManual(false); });
    $("#saveContext").addEventListener("click", function () {
      saveTsdManualFile(state.tsdManual || {}, false);
    });
    $("#editContext").addEventListener("click", openJsonDialog);

    $("#pickReportWorkbook").addEventListener("click", function () {
      openFilePicker(parentDir($("#reportWorkbook").value), ".xlsx", function (chosen) {
        $("#reportWorkbook").value = chosen;
        inspectTsd();
      });
    });
    $("#pickModelWorkbook").addEventListener("click", function () {
      openFilePicker(parentDir($("#modelWorkbook").value), ".xlsx", function (chosen) {
        $("#modelWorkbook").value = chosen;
        inspectTsd();
      });
    });
    $("#pickTemplate").addEventListener("click", function () {
      openFilePicker(parentDir($("#template").value), ".html", function (chosen) {
        $("#template").value = chosen;
        inspectTsd();
      });
    });
    $("#pickContext").addEventListener("click", function () {
      openFilePicker(parentDir($("#contextJson").value), ".json", function (chosen) {
        $("#contextJson").value = chosen;
        state.tsdManualCustom = true;
        loadTsdManual(false);
      });
    });
    $("#captureScreenshots").addEventListener("click", captureTsdScreenshots);
    $("#clearShotCache").addEventListener("click", clearTsdCache);
    $("#chooseTsdFolder").addEventListener("click", function () {
      openFolderPicker($("#tsdOutFolder").value, function (folder) {
        $("#tsdOutFolder").value = folder;
        inspectTsd();
      });
    });
    $("#openTsdFile").addEventListener("click", openTsdDocument);
    $("#openTsdFolder").addEventListener("click", openTsdFolder);
    $("#reloadShotWorkspace").addEventListener("click", function () {
      loadWorkspaces().then(function () { toast(t("Workspace catalog loaded")); });
    });
    $("#reloadShotReport").addEventListener("click", function () {
      if (!getSelectValue("shotWorkspace")) {
        toast(t("Choose a screenshot workspace first"));
        return;
      }
      loadTsdReports().then(function () { toast(t("Report list loaded")); });
    });
    $("#shotEnabled").addEventListener("change", function (event) {
      setChip(
        $("#shotChip"),
        event.target.checked ? "ok" : "idle",
        event.target.checked ? t("Active") : t("Inactive")
      );
      scheduleTsdInspect();
    });

    $("#shotWorkspace").addEventListener("change", function () {
      setSelectOptions("shotReport", [], "Choose a report…");
      loadTsdReports().then(function () { scheduleTsdInspect(); });
    });
    $("#shotReport").addEventListener("change", function () {
      scheduleTsdInspect();
    });

    [
      ["#reportName", "change"],
      ["#tsdFileName", "change"],
      ["#docDate", "change"],
      ["#tsdDraft", "change"],
      ["#tsdExpandAll", "change"],
      ["#shotScope", "change"],
      ["#shotScale", "change"],
      ["#shotMobile", "change"],
      ["#shotDecorative", "change"],
      ["#shotAutoInstall", "change"],
      ["#shotDebug", "change"]
    ].forEach(function (pair) {
      var field = $(pair[0]);
      if (field) field.addEventListener(pair[1], scheduleTsdInspect);
    });

    $("#closeJsonDialog").addEventListener("click", function () { $("#jsonDialog").close(); });
    $("#cancelJsonDialog").addEventListener("click", function () { $("#jsonDialog").close(); });
    $("#saveJsonDialog").addEventListener("click", saveJsonDialog);
    $("#jsonDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) $("#jsonDialog").close();
    });

    $("#runAnalyze").addEventListener("click", analysisRun);
    $("#analyzeFromEmpty").addEventListener("click", analysisRun);
    $("#stopAnalyze").addEventListener("click", analysisStop);
    $("#reloadModelAnalisa").addEventListener("click", function () {
      if (!getSelectValue("wsSelect")) {
        toast(t("Choose a workspace first"));
        return;
      }
      analysisLoadDatasets().then(function () {
        toast(t("Semantic model list reloaded"));
      });
    });
    $("#wsSelect").addEventListener("change", function () {
      analysisLoadDatasets();
    });
    $("#modelSelect").addEventListener("change", function () {
      state.analysis = null;
      state.analysisNote = "";
      state.analysisTarget = null;
      analysisRender();
    });
    $("#includeReports").addEventListener("change", function () {
      analysisSyncReportOptions();
      analysisSavePrefs();
      if (state.analysis) {
        toast(t("Run analysis again to apply the new report usage setting."));
      }
      analysisRender();
    });
    $("#includeOther").addEventListener("change", analysisSavePrefs);
    $("#includePersonal").addEventListener("change", analysisSavePrefs);

    $("#searchAnalyze").addEventListener("input", function () {
      if (state.analysis) analysisRender();
    });
    $("#typeAnalyze").addEventListener("change", function () {
      var value = getSelectValue("typeAnalyze") || "all";
      if (["all", "columns", "measures"].includes(value)) {
        state.analysisObjectFilter = value;
        analysisSavePrefs();
      }
      if (state.analysis) analysisRender();
    });
    $("#unusedOnly").addEventListener("change", function () {
      analysisSavePrefs();
      if (state.analysis) analysisRender();
    });
    $("#expandRows").addEventListener("click", function () {
      if (!state.analysis) {
        toast(t("Run the analysis first"));
        return;
      }
      state.analysisForceOpen = true;
      state.analysisOpen = {};
      analysisRender();
    });
    $("#collapseRows").addEventListener("click", function () {
      if (!state.analysis) {
        toast(t("Run the analysis first"));
        return;
      }
      state.analysisForceOpen = false;
      state.analysisOpen = {};
      analysisRender();
    });
    $("#exportXlsx").addEventListener("click", analysisExport);

    $("#reloadPartitions").addEventListener("click", partitionLoadInventory);
    $("#partitionsFromEmpty").addEventListener("click", partitionLoadInventory);
    $("#processSelectedPartitions").addEventListener("click", partitionOpenConfirm);
    $("#reloadPartitionDatasets").addEventListener("click", function () {
      if (!getSelectValue("partitionWsSelect")) {
        toast(t("Choose a workspace first"));
        return;
      }
      partitionLoadDatasets().then(function () {
        toast(t("Semantic model list reloaded"));
      });
    });
    $("#partitionWsSelect").addEventListener("change", function () {
      partitionLoadDatasets();
    });
    $("#partitionDatasetSelect").addEventListener("change", function () {
      state.partitions = null;
      state.partitionLoaded = false;
      state.partitionSelected = {};
      partitionRender();
    });
    $("#partitionSelectAll").addEventListener("change", function () {
      partitionToggleAll(this.checked);
    });
    $("#partitionBody").addEventListener("change", function (event) {
      var input = event.target.closest(".partition-check");
      if (!input) return;
      var index = String(input.getAttribute("data-index"));
      if (input.checked) state.partitionSelected[index] = true;
      else delete state.partitionSelected[index];
      partitionRender();
    });
    $("#closePartitionDialog").addEventListener("click", partitionCloseDialog);
    $("#cancelPartitionDialog").addEventListener("click", partitionCloseDialog);
    $("#confirmPartitionDialog").addEventListener("click", partitionConfirmProcess);
    $("#partitionDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) partitionCloseDialog();
    });

    $$("#analyzeTabs [role='tab']").forEach(function (tab) {
      tab.addEventListener("click", function () {
        analysisSetTab(tab.getAttribute("data-analysis-tab"));
      });
    });
    $("#relViewSwitch").addEventListener("click", function (event) {
      var button = event.target.closest("[data-rel-view]");
      if (!button) return;
      state.relView = button.getAttribute("data-rel-view") === "table" ? "table" : "graph";
      analysisSyncRelView();
      analysisRender();
    });
    $("#relGraphSvg").addEventListener("click", function (event) {
      if (state.relJustDragged) {
        state.relJustDragged = false;
        return;
      }
      var node = event.target.closest("[data-rel-table]");
      if (node) {
        state.relSelected = { kind: "table", value: node.getAttribute("data-rel-table") };
        analysisRender();
        return;
      }
      var edge = event.target.closest("[data-rel-pair]");
      if (edge) {
        state.relSelected = { kind: "pair", value: edge.getAttribute("data-rel-pair") };
        analysisRender();
      }
    });
    $("#relGraphSvg").addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      var node = event.target.closest("[data-rel-table]");
      if (!node) return;
      event.preventDefault();
      var name = node.getAttribute("data-rel-table");
      state.relSelected = { kind: "table", value: name };
      analysisRender();
      var next = $("#relGraphSvg [data-rel-table='" + name + "']");
      if (next) next.focus();
    });
    $("#relGraphSide").addEventListener("click", function (event) {
      var back = event.target.closest("[data-rel-back]");
      if (back) {
        state.relSelected = { kind: "table", value: back.getAttribute("data-rel-back") };
        analysisRender();
        return;
      }
      var tableButton = event.target.closest("[data-rel-table]");
      if (tableButton) {
        var table = tableButton.getAttribute("data-rel-table");
        state.relSelected = { kind: "table", value: table };
        analysisRender();
        var node = $("#relGraphSvg [data-rel-table='" + table + "']");
        if (node) node.focus();
        return;
      }
      var item = event.target.closest("[data-rel-pair]");
      if (!item) return;
      state.relSelected = { kind: "pair", value: item.getAttribute("data-rel-pair") };
      analysisRender();
    });
    $("#relZoomIn").addEventListener("click", function () {
      analysisSetZoom((state.relZoom || 1) * 1.25);
    });
    $("#relZoomOut").addEventListener("click", function () {
      analysisSetZoom((state.relZoom || 1) / 1.25);
    });
    $("#relZoomReset").addEventListener("click", function () {
      state.relPanX = 0;
      state.relPanY = 0;
      analysisSetZoom(1);
    });

    var relSvg = $("#relGraphSvg");
    relSvg.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      state.relDrag = {
        x: event.clientX, y: event.clientY,
        panX: state.relPanX || 0, panY: state.relPanY || 0,
        pointerId: event.pointerId, moved: false
      };
    });
    relSvg.addEventListener("pointermove", function (event) {
      var drag = state.relDrag;
      if (!drag) return;
      var dx = event.clientX - drag.x;
      var dy = event.clientY - drag.y;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      if (!drag.moved) {
        drag.moved = true;
        relSvg.setPointerCapture(drag.pointerId);
        relSvg.classList.add("is-panning");
      }
      var rect = relSvg.getBoundingClientRect();
      var baseWidth = state.relGraphBaseWidth || 760;
      var baseHeight = state.relGraphBaseHeight || 500;
      var zoom = state.relZoom || 1;
      var scaleX = rect.width ? (baseWidth / zoom) / rect.width : 1;
      var scaleY = rect.height ? (baseHeight / zoom) / rect.height : 1;
      state.relPanX = drag.panX - dx * scaleX;
      state.relPanY = drag.panY - dy * scaleY;
      var limitX = baseWidth * 0.8;
      var limitY = baseHeight * 0.8;
      state.relPanX = Math.max(-limitX, Math.min(limitX, state.relPanX));
      state.relPanY = Math.max(-limitY, Math.min(limitY, state.relPanY));
      applyAnalysisZoom();
    });
    function endRelDrag(event) {
      if (!state.relDrag) return;
      var moved = state.relDrag.moved;
      var pointerId = state.relDrag.pointerId;
      state.relDrag = null;
      relSvg.classList.remove("is-panning");
      if (relSvg.hasPointerCapture(pointerId)) {
        relSvg.releasePointerCapture(pointerId);
      }
      if (moved) {
        state.relJustDragged = true;
        window.setTimeout(function () { state.relJustDragged = false; }, 0);
      }
    }
    relSvg.addEventListener("pointerup", endRelDrag);
    relSvg.addEventListener("pointercancel", endRelDrag);

    $("#analyzeHead").addEventListener("click", function (event) {
      var header = event.target.closest("[data-analysis-sort]");
      if (!header) return;
      analysisSetSort(header.getAttribute("data-analysis-sort"));
    });
    $("#analyzeBody").addEventListener("click", function (event) {
      var ruleInfo = event.target.closest("[data-health-rule-info]");
      if (ruleInfo) {
        event.preventDefault();
        event.stopPropagation();
        analysisOpenHealthRules(ruleInfo.getAttribute("data-health-rule-info"));
        return;
      }
      var menuButton = event.target.closest("[data-analysis-menu]");
      if (menuButton) {
        var menuRow = menuButton.closest("tr[data-item-kind]");
        if (!menuRow) return;
        event.preventDefault();
        event.stopPropagation();
        state.analysisMenuFocus = menuButton;
        var buttonRect = menuButton.getBoundingClientRect();
        analysisOpenMenu(analysisRowTarget(menuRow), {
          x: buttonRect.left,
          y: buttonRect.bottom + 4,
          above: buttonRect.top - 4,
          row: menuRow
        });
        return;
      }
      var healthRow = event.target.closest("tr[data-health-kind]");
      if (healthRow && !event.target.closest("a")) {
        event.preventDefault();
        analysisHealthOpen(healthRow);
        return;
      }
      var toggle = event.target.closest("[data-analysis-toggle]");
      if (!toggle) return;
      event.preventDefault();
      var key = toggle.getAttribute("data-analysis-toggle");
      state.analysisForceOpen = null;
      state.analysisOpen[key] = !analysisIsOpen(key, false);
      analysisRender();
    });
    $("#analyzeBody").addEventListener("contextmenu", function (event) {
      var row = event.target.closest("tr[data-item-kind]");
      if (!row) return;
      event.preventDefault();
      state.analysisMenuFocus = row;
      analysisOpenMenu(analysisRowTarget(row), {
        x: event.clientX,
        y: event.clientY,
        above: event.clientY,
        row: row
      });
    });
    $("#analyzeBody").addEventListener("keydown", function (event) {
      if ((event.key === "F10" && event.shiftKey) || event.key === "ContextMenu") {
        var menuRow = event.target.closest("tr[data-item-kind]");
        if (!menuRow) return;
        event.preventDefault();
        var rowRect = menuRow.getBoundingClientRect();
        state.analysisMenuFocus = menuRow;
        analysisOpenMenu(analysisRowTarget(menuRow), {
          x: rowRect.left + 28,
          y: rowRect.top + Math.min(rowRect.height, 28),
          above: rowRect.top,
          row: menuRow
        });
        return;
      }
      if (event.key !== "Enter" && event.key !== " ") return;
      var toggle = event.target.closest("[data-analysis-toggle]");
      if (!toggle) return;
      event.preventDefault();
      toggle.click();
    });
    $("#analysisMenu").addEventListener("click", function (event) {
      var entry = event.target.closest("[data-menu-action]");
      if (!entry || entry.getAttribute("aria-disabled") === "true") return;
      event.preventDefault();
      if (entry.hasAttribute("data-menu-submenu")) {
        analysisOpenSubmenu(entry.getAttribute("data-menu-submenu"), entry);
        return;
      }
      analysisRunMenuAction(entry.getAttribute("data-menu-action"));
    });
    $("#analysisMenu").addEventListener("mouseover", function (event) {
      var entry = event.target.closest("[data-menu-action]");
      if (!entry) return;
      if (entry.hasAttribute("data-menu-submenu")) {
        analysisOpenSubmenu(entry.getAttribute("data-menu-submenu"), entry);
      } else {
        analysisCloseSubmenu(false);
      }
    });
    $("#analysisMenu").addEventListener("keydown", function (event) {
      var items = $$("#analysisMenu [role='menuitem']:not([aria-disabled='true'])");
      if (!items.length) return;
      var index = items.indexOf(document.activeElement);
      if (event.key === "ArrowRight") {
        var current = document.activeElement;
        if (current && current.hasAttribute("data-menu-submenu")) {
          event.preventDefault();
          analysisOpenSubmenu(
            current.getAttribute("data-menu-submenu"), current
          );
        }
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        index = index < 0 ? 0 : (index + 1) % items.length;
        items[index].focus();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        index = index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length;
        items[index].focus();
      } else if (event.key === "Home") {
        event.preventDefault();
        items[0].focus();
      } else if (event.key === "End") {
        event.preventDefault();
        items[items.length - 1].focus();
      } else if (event.key === "Escape") {
        event.preventDefault();
        if (state.analysisSubmenuTarget) {
          analysisCloseSubmenu(true);
        } else {
          analysisCloseMenu(true);
        }
      } else if (event.key === "Tab") {
        analysisCloseMenu(false);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (document.activeElement) document.activeElement.click();
      }
    });
    $("#analysisSubmenu").addEventListener("click", function (event) {
      var entry = event.target.closest("[data-menu-action]");
      if (!entry) return;
      event.preventDefault();
      analysisRunMenuAction(entry.getAttribute("data-menu-action"));
    });
    $("#analysisSubmenu").addEventListener("keydown", function (event) {
      var items = $$("#analysisSubmenu [role='menuitem']");
      if (!items.length) return;
      var index = items.indexOf(document.activeElement);
      if (event.key === "ArrowDown") {
        event.preventDefault();
        index = index < 0 ? 0 : (index + 1) % items.length;
        items[index].focus();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        index = index < 0 ? items.length - 1 : (index - 1 + items.length) % items.length;
        items[index].focus();
      } else if (event.key === "Home") {
        event.preventDefault();
        items[0].focus();
      } else if (event.key === "End") {
        event.preventDefault();
        items[items.length - 1].focus();
      } else if (event.key === "Escape" || event.key === "ArrowLeft") {
        event.preventDefault();
        event.stopPropagation();
        analysisCloseSubmenu(true);
      } else if (event.key === "Tab") {
        analysisCloseMenu(false);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (document.activeElement) document.activeElement.click();
      }
    });
    document.addEventListener("pointerdown", function (event) {
      if (!state.analysisMenuTarget) return;
      if (event.target.closest("#analysisMenu")) return;
      if (event.target.closest("#analysisSubmenu")) return;
      if (event.target.closest("[data-analysis-menu]")) return;
      analysisCloseMenu(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && state.analysisMenuTarget) {
        analysisCloseMenu(true);
      }
    });
    window.addEventListener("resize", function () {
      analysisCloseMenu(false);
    });
    $("#analyzeTableWrap").addEventListener("scroll", function () {
      analysisCloseMenu(false);
    }, { passive: true });
    $("#closeAnalysisDetails").addEventListener("click", function () {
      $("#analysisDetailsDialog").close();
    });
    $("#doneAnalysisDetails").addEventListener("click", function () {
      $("#analysisDetailsDialog").close();
    });
    $("#copyAnalysisExpression").addEventListener("click", function () {
      copyTextValue(state.analysisDetailsExpression || "");
    });
    $("#analysisDetailsDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) $("#analysisDetailsDialog").close();
    });
    $("#closeLineageDialog").addEventListener("click", function () {
      $("#analysisLineageDialog").close();
    });
    $("#analysisLineageDialog").addEventListener("click", function (event) {
      if (event.target !== event.currentTarget) return;
      if (analysisLineageConsumeDragClick()) return;
      $("#analysisLineageDialog").close();
    });
    $("#analysisLineageDialog").addEventListener("close", function () {
      state.analysisLineage = null;
      state.analysisLineageTarget = null;
      state.analysisLineageHighlight = null;
      state.analysisLineageDrag = null;
      analysisCloseSubmenu(false);
      $("#analysisLineageSearch").value = "";
      $("#analysisLineageNodes").innerHTML = "";
      $("#analysisLineageEdges").innerHTML = "";
      $("#analysisLineageTreeEdges").innerHTML = "";
      $("#analysisLineageOutline").innerHTML = "";
    });
    $("#analysisRawLoad").addEventListener("click", analysisRunPreview);
    $("#closeAnalysisRaw").addEventListener("click", function () {
      $("#analysisRawDialog").close();
    });
    $("#doneAnalysisRaw").addEventListener("click", function () {
      $("#analysisRawDialog").close();
    });
    $("#analysisRawDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) $("#analysisRawDialog").close();
    });
    $("#analysisRawDialog").addEventListener("close", analysisResetPreview);
    $("#analysisItemTabs").addEventListener("click", function (event) {
      var tab = event.target.closest("[data-item-tab]");
      if (!tab) return;
      state.analysisItemTab = tab.getAttribute("data-item-tab");
      analysisItemTabs();
      analysisRenderItemDetails();
    });
    $("#analysisItemPane").addEventListener("click", function (event) {
      var retry = event.target.closest("[data-item-raw-retry]");
      if (retry) {
        state.analysisItemRaw = null;
        state.analysisItemRawError = "";
        analysisRenderItemDetails();
        return;
      }
      var dep = event.target.closest("[data-dep-kind]");
      if (!dep) return;
      $("#analysisItemDialog").close();
      analysisLineageOpen(
        {
          kind: dep.getAttribute("data-dep-kind"),
          table: dep.getAttribute("data-dep-table"),
          name: dep.getAttribute("data-dep-name")
        },
        "graph",
        "all"
      );
    });
    $("#analysisItemTabs").addEventListener("keydown", function (event) {
      var keys = ["ArrowRight", "ArrowLeft", "Home", "End"];
      if (keys.indexOf(event.key) === -1) return;
      event.preventDefault();
      var tabs = $$("#analysisItemTabs [role='tab']");
      var index = tabs.indexOf(document.activeElement);
      if (event.key === "ArrowRight") index = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") index = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") index = 0;
      else index = tabs.length - 1;
      tabs[index].focus();
      state.analysisItemTab = tabs[index].getAttribute("data-item-tab");
      analysisItemTabs();
      analysisRenderItemDetails();
    });
    $("#closeAnalysisItem").addEventListener("click", function () {
      $("#analysisItemDialog").close();
    });
    $("#doneAnalysisItem").addEventListener("click", function () {
      $("#analysisItemDialog").close();
    });
    $("#copyAnalysisItemJson").addEventListener("click", analysisCopyItemJson);
    $("#analysisItemDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) $("#analysisItemDialog").close();
    });
    $("#analysisItemDialog").addEventListener("close", function () {
      state.analysisItem = null;
      state.analysisItemTarget = null;
      state.analysisItemRaw = null;
      state.analysisItemRawError = "";
      state.analysisItemTab = "properties";
      $("#analysisItemPane").innerHTML = "";
    });
    $("#healthRulesInfo").addEventListener("click", function () {
      analysisOpenHealthRules();
    });
    $("#bpRulesInfo").addEventListener("click", analysisOpenBpRules);
    $("#closeBpRules").addEventListener("click", function () {
      $("#analysisBpRulesDialog").close();
    });
    $("#doneBpRules").addEventListener("click", function () {
      $("#analysisBpRulesDialog").close();
    });
    $("#analysisBpRulesDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) {
        $("#analysisBpRulesDialog").close();
      }
    });
    $("#closeHealthRules").addEventListener("click", function () {
      $("#analysisHealthRulesDialog").close();
    });
    $("#doneHealthRules").addEventListener("click", function () {
      $("#analysisHealthRulesDialog").close();
    });
    $("#analysisHealthRulesDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) {
        $("#analysisHealthRulesDialog").close();
      }
    });
    $("#closeAnalysisRawMeta").addEventListener("click", function () {
      $("#analysisRawMetaDialog").close();
    });
    $("#doneAnalysisRawMeta").addEventListener("click", function () {
      $("#analysisRawMetaDialog").close();
    });
    $("#copyAnalysisRawMeta").addEventListener("click", function () {
      if (state.analysisRawMeta) {
        copyTextValue(analysisPrettyJson(state.analysisRawMeta));
      }
    });
    $("#analysisRawMetaReload").addEventListener("click", analysisReloadRawMetadata);
    $("#analysisRawMetaDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) $("#analysisRawMetaDialog").close();
    });
    $("#analysisRawMetaDialog").addEventListener("close", analysisResetRawMetadata);
    $("#analysisLineageSearch").addEventListener("input", analysisLineageApplySearch);
    $("#analysisLineageZoomIn").addEventListener("click", function () {
      analysisLineageZoomBy(1.25);
    });
    $("#analysisLineageZoomOut").addEventListener("click", function () {
      analysisLineageZoomBy(1 / 1.25);
    });
    $("#analysisLineageZoomFit").addEventListener("click", analysisLineageFit);
    $("#analysisLineageExportSvg").addEventListener("click", function () {
      analysisExportLineageImage(state.analysisLineageTarget, "svg");
    });
    $("#analysisLineageExportPng").addEventListener("click", function () {
      analysisExportLineageImage(state.analysisLineageTarget, "png");
    });
    $("#analysisLineageDirection").addEventListener("click", function (event) {
      var button = event.target.closest("[data-lineage-direction]");
      if (!button) return;
      var value = button.getAttribute("data-lineage-direction");
      if (["both", "upstream", "downstream"].indexOf(value) === -1) return;
      if (value === state.analysisLineageDirection) return;
      state.analysisLineageDirection = value;
      analysisLineageDirectionButtons();
      analysisLoadLineage();
    });
    $("#analysisLineageView").addEventListener("click", function (event) {
      var button = event.target.closest("[data-lineage-view]");
      if (!button) return;
      var value = button.getAttribute("data-lineage-view");
      if (["graph", "outline"].indexOf(value) === -1) return;
      var changed = value !== state.analysisLineageView;
      state.analysisLineageView = value;
      analysisLineageApplyView();
      if (changed) {
        analysisLoadLineage();
      } else {
        analysisLineageApplySearch();
      }
    });
    $("#analysisLineageOutlineMode").addEventListener("click", function (event) {
      var button = event.target.closest("[data-outline-mode]");
      if (!button) return;
      var value = button.getAttribute("data-outline-mode");
      if (["compact", "full"].indexOf(value) === -1) return;
      if (value === state.analysisLineageOutlineMode) return;
      state.analysisLineageOutlineMode = value;
      analysisLineageViewButtons();
      analysisLoadLineage();
    });
    $("#analysisLineageCanvas").addEventListener("click", function (event) {
      if (analysisLineageConsumeDragClick()) return;
      var node = event.target.closest("[data-node-id]");
      if (node) {
        analysisLineageSelect(node.getAttribute("data-node-id"));
        return;
      }
      var group = event.target.closest(".lineage-group");
      if (group) {
        var groupId = group.getAttribute("data-group-id");
        var meta = (state.analysisLineage && state.analysisLineage.groups || [])
          .filter(function (item) { return item.id === groupId; })[0];
        if (meta) analysisLineageSelectMembers(meta.members, meta.head_id || "");
        return;
      }
      var artifact = event.target.closest(".lineage-artifact");
      if (artifact) {
        var artifactId = artifact.getAttribute("data-artifact-id");
        var owner = (state.analysisLineage && state.analysisLineage.artifacts || [])
          .filter(function (item) { return item.id === artifactId; })[0];
        if (owner) {
          analysisLineageSelectMembers(owner.members, owner.head_id || "");
        }
        return;
      }
      analysisLineageClearHighlight();
    });
    $("#analysisLineageCanvas").addEventListener("dblclick", function (event) {
      var node = event.target.closest("[data-node-id]");
      if (!node) return;
      analysisLineageReroot(
        node.getAttribute("data-node-kind"),
        node.getAttribute("data-node-table"),
        node.getAttribute("data-node-name")
      );
    });
    $("#analysisLineageOutline").addEventListener("dblclick", function (event) {
      var row = event.target.closest(".lo-row");
      if (!row) return;
      analysisLineageReroot(
        row.getAttribute("data-node-kind"),
        row.getAttribute("data-node-table"),
        row.getAttribute("data-node-name")
      );
    });
    $("#analysisLineageCanvasWrap").addEventListener("wheel", function (event) {
      if (!state.analysisLineage) return;
      event.preventDefault();
      var wrap = event.currentTarget;
      var rect = wrap.getBoundingClientRect();
      var previous = state.analysisLineageZoom;
      var next = Math.min(
        2.5, Math.max(0.12, previous * (event.deltaY < 0 ? 1.12 : 1 / 1.12))
      );
      if (next === previous) return;
      var anchorX = wrap.scrollLeft + (event.clientX - rect.left);
      var anchorY = wrap.scrollTop + (event.clientY - rect.top);
      state.analysisLineageZoom = next;
      analysisLineageApplyZoom();
      wrap.scrollLeft = anchorX * (next / previous) - (event.clientX - rect.left);
      wrap.scrollTop = anchorY * (next / previous) - (event.clientY - rect.top);
    }, { passive: false });
    $("#analysisLineageCanvasWrap").addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      var wrap = event.currentTarget;
      var target = analysisLineageDragTarget(event);
      if (target) {
        var scope = analysisLineageDragScope(target);
        if (scope) {
          state.analysisLineageItemDrag = {
            target: target,
            scope: scope,
            positions: analysisLineageDragPositions(scope),
            x: event.clientX,
            y: event.clientY,
            moved: false,
            pointerId: event.pointerId
          };
          state.analysisLineageSuppressClick = 0;
          wrap.classList.add("is-dragging-item");
          return undefined;
        }
      }
      state.analysisLineageItemDrag = null;
      state.analysisLineageDrag = {
        x: event.clientX,
        y: event.clientY,
        left: wrap.scrollLeft,
        top: wrap.scrollTop,
        moved: false,
        pointerId: event.pointerId
      };
      wrap.classList.add("is-panning");
      try {
        wrap.setPointerCapture(event.pointerId);
      } catch (error) {
        return undefined;
      }
      return undefined;
    });
    $("#analysisLineageCanvasWrap").addEventListener("pointermove", function (event) {
      var itemDrag = state.analysisLineageItemDrag;
      if (itemDrag) {
        var scale = state.analysisLineageZoom || 1;
        var itemDx = (event.clientX - itemDrag.x) / scale;
        var itemDy = (event.clientY - itemDrag.y) / scale;
        if (Math.abs(itemDx) + Math.abs(itemDy) > 3) itemDrag.moved = true;
        if (itemDrag.moved) analysisLineageMoveItems(itemDrag, itemDx, itemDy);
        return;
      }
      var drag = state.analysisLineageDrag;
      if (!drag) return;
      var wrap = event.currentTarget;
      var dx = event.clientX - drag.x;
      var dy = event.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
      wrap.scrollLeft = drag.left - dx;
      wrap.scrollTop = drag.top - dy;
    });
    function analysisLineageEndPan(event) {
      var wrap = event.currentTarget;
      var itemDrag = state.analysisLineageItemDrag;
      if (itemDrag) {
        state.analysisLineageItemDrag = null;
        wrap.classList.remove("is-dragging-item");
        try {
          if (wrap.hasPointerCapture(itemDrag.pointerId)) {
            wrap.releasePointerCapture(itemDrag.pointerId);
          }
        } catch (error) {
          return undefined;
        }
        if (itemDrag.moved) {
          state.analysisLineageSuppressClick = Date.now() + 350;
          analysisLineageRefreshEdges();
        }
        return undefined;
      }
      var drag = state.analysisLineageDrag;
      if (!drag) return;
      state.analysisLineageDrag = null;
      wrap.classList.remove("is-panning");
      try {
        if (wrap.hasPointerCapture(drag.pointerId)) {
          wrap.releasePointerCapture(drag.pointerId);
        }
      } catch (error) {
        return undefined;
      }
      if (!drag.moved) analysisLineageClearHighlight();
      return undefined;
    }
    $("#analysisLineageCanvasWrap").addEventListener("pointerup", analysisLineageEndPan);
    $("#analysisLineageCanvasWrap").addEventListener(
      "pointercancel", analysisLineageEndPan
    );
    window.addEventListener("pointerup", function () {
      var itemDrag = state.analysisLineageItemDrag;
      if (!itemDrag) return;
      state.analysisLineageItemDrag = null;
      var wrap = $("#analysisLineageCanvasWrap");
      if (wrap) wrap.classList.remove("is-dragging-item");
      if (itemDrag.moved) {
        state.analysisLineageSuppressClick = Date.now() + 350;
        analysisLineageRefreshEdges();
      }
    });
    window.addEventListener("resize", function () {
      if ($("#analysisLineageDialog").open) analysisLineageApplyZoom();
    });
    $("#analyzeTabs").addEventListener("keydown", function (event) {
      var keys = ["ArrowRight", "ArrowLeft", "Home", "End"];
      if (keys.indexOf(event.key) === -1) return;
      event.preventDefault();
      var tabs = $$("#analyzeTabs [role='tab']");
      var index = tabs.indexOf(document.activeElement);
      if (event.key === "ArrowRight") index = (index + 1 + tabs.length) % tabs.length;
      else if (event.key === "ArrowLeft") index = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") index = 0;
      else index = tabs.length - 1;
      tabs[index].focus();
      analysisSetTab(tabs[index].getAttribute("data-analysis-tab"));
    });

    $("#dirUpstream").addEventListener("click", function () {
      lineageSetDirection("upstream");
    });
    $("#dirDownstream").addEventListener("click", function () {
      lineageSetDirection("downstream");
    });
    $("#depthMinus").addEventListener("click", function () {
      lineageSetDepth(-1);
    });
    $("#depthPlus").addEventListener("click", function () {
      lineageSetDepth(1);
    });
    $("#lineageZoomIn").addEventListener("click", function () {
      setLineageZoom((state.lineageZoom || 1) * 1.25);
    });
    $("#lineageZoomOut").addEventListener("click", function () {
      setLineageZoom((state.lineageZoom || 1) / 1.25);
    });
    $("#lineageZoomReset").addEventListener("click", function () {
      state.lineagePanX = 0;
      state.lineagePanY = 0;
      setLineageZoom(1);
    });

    var lineageSvg = $("#lineageSvg");
    lineageSvg.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      state.lineageDrag = {
        x: event.clientX, y: event.clientY,
        panX: state.lineagePanX || 0, panY: state.lineagePanY || 0,
        pointerId: event.pointerId, moved: false
      };
    });
    lineageSvg.addEventListener("pointermove", function (event) {
      var drag = state.lineageDrag;
      if (!drag) return;
      var dx = event.clientX - drag.x;
      var dy = event.clientY - drag.y;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      if (!drag.moved) {
        drag.moved = true;
        lineageSvg.setPointerCapture(drag.pointerId);
        lineageSvg.classList.add("is-panning");
      }
      var rect = lineageSvg.getBoundingClientRect();
      var baseWidth = state.lineageBaseWidth || 780;
      var baseHeight = state.lineageBaseHeight || 280;
      var zoom = state.lineageZoom || 1;
      var scaleX = rect.width ? (baseWidth / zoom) / rect.width : 1;
      var scaleY = rect.height ? (baseHeight / zoom) / rect.height : 1;
      state.lineagePanX = drag.panX - dx * scaleX;
      state.lineagePanY = drag.panY - dy * scaleY;
      var limitX = baseWidth * 0.8;
      var limitY = baseHeight * 0.8;
      state.lineagePanX = Math.max(-limitX, Math.min(limitX, state.lineagePanX));
      state.lineagePanY = Math.max(-limitY, Math.min(limitY, state.lineagePanY));
      applyLineageZoom();
    });
    function endLineageDrag(event) {
      if (!state.lineageDrag) return;
      var moved = state.lineageDrag.moved;
      var pointerId = state.lineageDrag.pointerId;
      state.lineageDrag = null;
      lineageSvg.classList.remove("is-panning");
      if (lineageSvg.hasPointerCapture(pointerId)) {
        lineageSvg.releasePointerCapture(pointerId);
      }
      if (moved) {
        state.lineageJustDragged = true;
        window.setTimeout(function () { state.lineageJustDragged = false; }, 0);
      }
    }
    lineageSvg.addEventListener("pointerup", endLineageDrag);
    lineageSvg.addEventListener("pointercancel", endLineageDrag);
    $("#visualLineage").addEventListener("click", function () {
      state.visual = !state.visual;
      $("#lineageLayout").classList.toggle("is-visual", state.visual);
      $("#visualLineage").setAttribute("aria-pressed", String(state.visual));
      toast(t(state.visual ? "Lineage visual mode on" : "Lineage visual mode off"));
    });
    $("#exportCsv").addEventListener("click", lineageExport);
    $("#exportSvg").addEventListener("click", function () {
      lineageExportImage("svg");
    });
    $("#exportPng").addEventListener("click", function () {
      lineageExportImage("png");
    });
    $("#lineageNodeType").addEventListener("change", function () {
      state.lineageNodeType = getSelectValue("lineageNodeType") || "";
      lineageRenderGraph();
    });

    $("#lineageSearchBtn").addEventListener("click", lineageSearch);
    $("#lineageSearch").addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        lineageSearch();
      }
    });
    $("#lineageSearch").addEventListener("input", function () {
      if (state.lineageSearchTimer) window.clearTimeout(state.lineageSearchTimer);
      state.lineageSearchTimer = window.setTimeout(function () {
        state.lineageSearchTimer = null;
        lineageSearch();
      }, 450);
    });
    $("#lineageWorkspace").addEventListener("input", function () {
      if (state.lineageSearchTimer) window.clearTimeout(state.lineageSearchTimer);
      state.lineageSearchTimer = window.setTimeout(function () {
        state.lineageSearchTimer = null;
        lineageSearch();
      }, 450);
    });
    $("#lineageType").addEventListener("change", lineageSearch);
    $("#lineageResults").addEventListener("click", function (event) {
      var item = event.target.closest(".result-item");
      if (!item) return;
      lineageOpen(item.dataset.id);
    });
    $("#lineageLayer").addEventListener("click", function (event) {
      if (state.lineageJustDragged) {
        state.lineageJustDragged = false;
        return;
      }
      var node = event.target.closest(".node");
      if (!node) return;
      lineageSelectNode(node.dataset.id);
    });
    $("#lineageLayer").addEventListener("dblclick", function (event) {
      var node = event.target.closest(".node");
      if (!node) return;
      lineageOpen(node.dataset.id);
      toast(t("Lineage root updated"));
    });
    $("#lineageLayer").addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      var node = event.target.closest(".node");
      if (!node) return;
      event.preventDefault();
      lineageSelectNode(node.dataset.id);
    });

    $$("#view-pengaturan .tabs [role='tab']").forEach(function (tab) {
      tab.addEventListener("click", function () {
        showSettingsTab(tab.dataset.tab);
      });
    });

    $("#testConn").addEventListener("click", function () {
      $("#connResult").textContent = "Menguji koneksi...";
      startJob({
        path: "/api/settings/test-token",
        body: {},
        label: t("Power BI connection test"),
        button: $("#testConn"),
        onDone: function (snapshot) {
          var tokens = (snapshot.result && snapshot.result.tokens) || {};
          var parts = [];
          Object.keys(tokens).forEach(function (name) {
            parts.push((tokens[name].ok ? "OK " : t("FAILED ")) + name);
          });
          $("#connResult").textContent = parts.length
            ? "Hasil tes: " + parts.join(" - ")
            : t("Test finished without a token result.");
          toast(parts.join(" - ") || t("Test finished"));
        }
      });
    });

    $("#saveCreds").addEventListener("click", function () {
      var secret = $("#clientSecret").value;
      var payload = {
        tenant_id: $("#tenantId").value.trim(),
        client_id: $("#clientId").value.trim()
      };
      if (secret) payload.client_secret = secret;
      api().put("/api/settings/credentials", payload).then(function () {
        return api().put("/api/settings/rls", {
          username: $("#rlsUsername").value.trim(),
          roles: $("#rlsRoles").value
        });
      }).then(function (data) {
        state.formDirty = false;
        state.secretDirty = false;
        renderSettings(data);
        $("#clientSecret").value = "";
        addLog(t("Credentials and default RLS saved."), "ok");
        toast(t("Settings saved"));
      }).catch(reportError);
    });

    $("#syncCatalog").addEventListener("click", function () {
      startJob({
        path: "/api/catalog/sync",
        body: {},
        label: t("Sync workspace catalog"),
        button: $("#syncCatalog"),
        onDone: function (snapshot) {
          var result = snapshot.result || {};
          toast("Katalog: " + (result.workspace_count || 0) + t(" workspaces"));
        }
      });
    });

    $("#scanLineage").addEventListener("click", function () {
      startJob({
        path: "/api/catalog/scan",
        body: { full: $("#fullScan").checked },
        label: t("Power BI lineage scan"),
        button: $("#scanLineage"),
        onDone: function (snapshot) {
          var result = snapshot.result || {};
          toast("Lineage: " + (result.workspace_count || 0) + t(" workspaces, ") +
            (result.node_count || 0) + t(" nodes"));
        }
      });
    });

    $("#syncMode").addEventListener("change", function (event) {
      savePreference("catalog", {
        mode: event.target.value,
        include_personal: $("#includePersonal").checked
      });
    });
    $("#includePersonal").addEventListener("change", function (event) {
      savePreference("catalog", {
        mode: $("#syncMode").value,
        include_personal: event.target.checked
      });
    });
    $("#saveDb").addEventListener("click", function () {
      savePreference("paths", { lineage_db: $("#dbPath").value }).then(function (data) {
        if (!data) return;
        state.formDirty = false;
        renderSettings(data);
        toast(t("Database path saved"));
      });
    });
    $("#pickDb").addEventListener("click", function () {
      openFolderPicker(parentDir($("#dbPath").value), function (folder) {
        var target = folder.replace(/[\\/]+$/, "") + "\\bi_tools.db";
        $("#dbPath").value = target;
        savePreference("paths", { lineage_db: target }).then(function (data) {
          if (data) toast(t("Database path saved"));
        });
      });
    });
    ["tenantId", "clientId", "clientSecret", "rlsUsername", "rlsRoles", "dbPath"].forEach(function (id) {
      var field = $("#" + id);
      if (!field) return;
      field.addEventListener("input", function () {
        state.formDirty = true;
        if (id === "clientSecret") state.secretDirty = true;
      });
    });
    $("#showConsole").addEventListener("change", function (event) {
      savePreference("ui", { show_console: event.target.checked });
    });
    $("#scope").addEventListener("change", function (event) {
      renderModelAvailability();
      var payload = {};
      if (state.source === "service") payload.scope_service = event.target.value;
      else payload.scope_local = event.target.value;
      savePreference("extraction", payload);
    });
    $("#shutdownServer").addEventListener("click", function () {
      if (!window.confirm(t("Stop the local server? This tab cannot be used again until the application is restarted."))) return;
      api().post("/api/system/shutdown", {}).catch(function () {}).then(function () {
        window.setTimeout(function () {
          document.body.innerHTML =
            '<main style="font-family:Segoe UI,sans-serif;background:#0e1116;color:#e9edf3;' +
            'min-height:100vh;display:flex;align-items:center;justify-content:center;margin:0">' +
            '<div style="max-width:32rem;padding:2rem;border:1px solid #28303d;border-radius:8px;background:#151a22">' +
            "<h1 style=\"font-size:1.1rem;margin:0 0 .5rem\">" +
            t("Server stopped") + "</h1>" +
            '<p style="color:#b9c2d0;line-height:1.6;margin:0">' +
            t("Run BI Tools again to open the web interface.") + "</p>" +
            "</div></main>";
        }, 400);
      });
    });
    $("#copyServerUrl").addEventListener("click", function () {
      var value = $("#serverUrl").value;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(function () {
          toast(t("Server address copied"));
        }).catch(function () {
          toast("Salin manual: " + value);
        });
      } else {
        toast("Salin manual: " + value);
      }
    });

    $("#closeFolderDialog").addEventListener("click", function () { $("#folderDialog").close(); });
    $("#cancelFolder").addEventListener("click", function () { $("#folderDialog").close(); });
    $("#chooseFolder").addEventListener("click", function () {
      var choice = state.pickKind === "file" ? state.pickFile : state.pickDir;
      var callback = state.pickCallback;
      $("#folderDialog").close();
      if (callback && choice) callback(choice);
    });
    $("#folderGo").addEventListener("click", function () {
      browseFolder($("#folderPathInput").value);
    });
    $("#folderPathInput").addEventListener("keydown", function (event) {
      if (event.key !== "Enter") return;
      event.preventDefault();
      browseFolder(event.target.value);
    });
    $("#folderDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) $("#folderDialog").close();
    });

    window.addEventListener("resize", function () {
      if (state.analysis) applyAnalysisCellTitles();
    });
    applySidebar(state.sidebarCollapsed, false);
    $("#sidebarToggle").addEventListener("click", function () {
      applySidebar(!state.sidebarCollapsed, true);
    });

    renderLog();
    analysisRender();
  }

Object.assign(app, {
  addLog: addLog,
  api: api,
  apiReady: apiReady,
  reportError: reportError,
  setChip: setChip,
  showView: showView,
  startJob: startJob,
  toast: toast,
  applyMetaSteps: applyMetaSteps,
  loadOutputs: loadOutputs,
  parentDir: parentDir,
  setMetaStep: setMetaStep
});

init();

bootstrap();
