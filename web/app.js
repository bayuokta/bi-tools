(function () {
  "use strict";

  var NEWLINE = String.fromCharCode(10);

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $$(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  var store = {
    get: function (key, fallback) {
      try {
        var value = window.localStorage.getItem(key);
        return value === null ? fallback : value;
      } catch (error) {
        return fallback;
      }
    },
    set: function (key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch (error) {
        return undefined;
      }
    }
  };

  var i18n = window.BIToolsI18n || null;

  function t(text) {
    return i18n ? i18n.translate(text) : text;
  }

  function tr(text) {
    return i18n && i18n.translateServer ? i18n.translateServer(text) : text;
  }

  function currentLanguage() {
    return i18n && i18n.language === "id" ? "id" : "en";
  }

  var state = {
    view: "ekstraksi",
    theme: store.get("pbi-theme", "dark") === "light" ? "light" : "dark",
    language: store.get("pbi-lang", "en") === "id" ? "id" : "en",
    motion: store.get("pbi-motion", "on") !== "off",
    sidebarCollapsed: store.get("pbi-sidebar", "open") === "collapsed",
    source: "service",
    running: false,
    tsdRunning: false,
    metaStep: "extract",
    extractReady: false,
    tsdReady: false,
    logs: [],
    rootId: "report-sales",
    selectedId: "report-sales",
    direction: "upstream",
    depth: 3,
    visual: false,
    ready: false,
    applying: false,
    settings: null,
    system: null,
    outputs: null,
    jobId: null,
    jobStream: null,
    jobLogCount: 0,
    lastJob: null,
    pickDir: "",
    pickCallback: null,
    formDirty: false,
    secretDirty: false,
    tsd: null,
    tsdLoaded: false,
    tsdManual: {},
    tsdManualCustom: false,
    tsdLastResult: null,
    tsdOutputPath: "",
    tsdTimer: null,
    tsdInspectTimer: null,
    analysis: null,
    analysisTab: "all",
    analysisSort: "default",
    analysisSortDesc: false,
    analysisOpen: {},
    analysisForceOpen: null,
    analysisSettings: {},
    analysisRunning: false,
    analysisTimer: null,
    analysisMenuTarget: null,
    analysisMenuFocus: null,
    analysisDetailsExpression: "",
    analysisLineage: null,
    analysisLineageTarget: null,
    analysisLineageDirection: "both",
    analysisLineageView: "graph",
    analysisLineageOutlineMode: "compact",
    analysisLineageCategory: "all",
    analysisLineageZoom: 1,
    analysisLineageDrag: null,
    analysisLineageHighlight: null,
    analysisSubmenuTarget: null,
    analysisSubmenuAnchor: null,
    analysisRawTarget: null,
    analysisItem: null,
    analysisItemTarget: null,
    analysisItemTab: "properties",
    analysisItemRaw: null,
    analysisItemRawError: "",
    analysisRawMeta: null,
    analysisRawMetaTarget: null,
    reportDetail: {},
    reportLoading: {},
    partitions: null,
    partitionLoaded: false,
    partitionSelected: {},
    partitionRunning: false,
    partitionStateLoaded: false,
    relView: "graph",
    relSelected: null,
    relZoom: 1,
    relPanX: 0,
    relPanY: 0,
    relDrag: null,
    relJustDragged: false,
    relGraphBaseWidth: 760,
    relGraphBaseHeight: 500,
    lineageData: null,
    lineageGraph: null,
    lineageNodesLive: {},
    lineageHasDb: false,
    lineageQuery: "",
    lineageStateReady: false,
    lineageStatePromise: null,
    lineageSearchTimer: null,
    lineageZoom: 1,
    lineagePanX: 0,
    lineagePanY: 0,
    lineageBaseWidth: 780,
    lineageBaseHeight: 280,
    lineageDrag: null,
    lineageJustDragged: false,
    instances: [],
    workspaces: [],
    reports: [],
    datasets: [],
    pbix: null,
    endpoint: "",
    extractTimer: null,
    workspaceHint: "",
    instanceHint: "",
    pickKind: "dir",
    pickExt: "",
    pickFile: null
  };


  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

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


  // -- utilitas format angka ---------------------------------------------
  function decimalText(text) {
    return currentLanguage() === "id" ? String(text).replace(".", ",") : String(text);
  }

  function fmtInt(value) {
    return Number(value).toLocaleString(currentLanguage() === "id" ? "id-ID" : "en-US");
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

  function sizeText(bytes) {
    var value = Number(bytes || 0);
    if (!value) return "";
    if (value >= 1048576) return decimalText((value / 1048576).toFixed(1)) + " MB";
    if (value >= 1024) return Math.round(value / 1024) + " KB";
    return value + " B";
  }

  function fileMeta(entry) {
    if (!entry || !entry.exists) return t("Not created");
    var parts = [];
    if (entry.modified) parts.push(entry.modified);
    if (entry.size) parts.push(sizeText(entry.size));
    return parts.join(" \u00b7 ") || t("Ready");
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
  var comboState = { select: null, trigger: null, options: [], active: -1 };
  var selectData = {};

  function comboLabelText(select) {
    var option = select.options[select.selectedIndex];
    return option ? option.textContent : "";
  }

  function refreshCombo(select) {
    if (!select || !select.dataset.comboReady) return;
    var host = select.closest(".select");
    if (!host) return;
    var button = host.querySelector(".combo-button");
    if (!button) return;
    var label = button.querySelector(".combo-label");
    var text = comboLabelText(select);
    if (label) label.textContent = text || t("Choose…");
    button.title = text;
    var fieldLabel = select.id ? document.querySelector('label[for="' + select.id + '"]') : null;
    button.setAttribute(
      "aria-label",
      (fieldLabel ? fieldLabel.textContent.trim() + ": " : "") + (text || t("Choose"))
    );
    if (comboState.select === select) buildComboList($("#comboSearch").value);
  }

  function buildComboList(query) {
    var select = comboState.select;
    if (!select) return;
    var q = (query || "").trim().toLowerCase();
    var options = Array.prototype.map.call(select.options, function (option) {
      return { value: option.value, label: option.textContent, disabled: option.disabled };
    }).filter(function (item) {
      return !item.disabled && item.value !== "" &&
        (!q || item.label.toLowerCase().indexOf(q) !== -1);
    });
    comboState.options = options;
    comboState.active = -1;
    var selectedValue = select.value;
    var selectedIndex = -1;
    options.forEach(function (item, index) {
      if (item.value === selectedValue) selectedIndex = index;
    });
    $("#comboList").innerHTML = options.map(function (item, index) {
      return '<button type="button" class="combo-option" role="option" tabindex="-1" data-index="' + index +
        '" aria-selected="' + (item.value === selectedValue ? "true" : "false") + '">' +
        escapeHtml(item.label) + "</button>";
    }).join("");
    $("#comboList").scrollTop = 0;
    $("#comboEmpty").hidden = options.length > 0;
    if (selectedIndex >= 0) setComboActive(selectedIndex, false);
  }

  function setComboActive(index, scroll) {
    if (!comboState.options.length) {
      comboState.active = -1;
      return;
    }
    if (index < 0) index = comboState.options.length - 1;
    if (index >= comboState.options.length) index = 0;
    comboState.active = index;
    $$(".combo-option", $("#comboList")).forEach(function (option, i) {
      option.classList.toggle("is-active", i === index);
    });
    var active = $(".combo-option.is-active", $("#comboList"));
    if (active && scroll) active.scrollIntoView({ block: "nearest" });
  }

  function positionCombo() {
    if (!comboState.select || !comboState.trigger) return;
    var popup = $("#comboPopup");
    if (popup.hidden) return;
    var rect = comboState.trigger.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      closeCombo();
      return;
    }
    var width = Math.min(Math.max(rect.width, 220), window.innerWidth - 24);
    popup.style.width = width + "px";
    popup.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)) + "px";
    var height = popup.offsetHeight;
    var top = rect.bottom + 6;
    if (top + height > window.innerHeight - 12 && rect.top - height - 6 > 8) {
      top = rect.top - height - 6;
    }
    popup.style.top = Math.max(8, top) + "px";
  }

  function openCombo(select, trigger) {
    if (comboState.trigger && comboState.trigger !== trigger) {
      comboState.trigger.setAttribute("aria-expanded", "false");
    }
    comboState.select = select;
    comboState.trigger = trigger;
    var popup = $("#comboPopup");
    popup.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    $("#comboSearch").value = "";
    buildComboList("");
    $("#comboList").scrollTop = 0;
    positionCombo();
    $("#comboSearch").focus();
  }

  function closeCombo(focusTrigger) {
    var popup = $("#comboPopup");
    if (popup.hidden) return;
    popup.hidden = true;
    var trigger = comboState.trigger;
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    comboState.select = null;
    comboState.trigger = null;
    comboState.options = [];
    comboState.active = -1;
    if (focusTrigger && trigger && document.contains(trigger)) trigger.focus();
  }

  function chooseComboOption(index) {
    var item = comboState.options[index];
    if (!item || !comboState.select) return;
    var select = comboState.select;
    var trigger = comboState.trigger;
    select.value = item.value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    refreshCombo(select);
    closeCombo(false);
    if (trigger && document.contains(trigger)) trigger.focus();
  }

  function enhanceSelect(select) {
    if (!select || select.dataset.comboReady || select.closest("dialog")) return;
    var host = select.closest(".select");
    if (!host) return;
    select.dataset.comboReady = "1";
    select.classList.add("combo-native");
    select.setAttribute("tabindex", "-1");
    host.classList.add("combo-host");
    var trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "combo-button";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-controls", "comboPopup");
    trigger.setAttribute("aria-expanded", "false");
    trigger.innerHTML = '<span class="combo-label"></span>';
    host.insertBefore(trigger, select);
    trigger.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (comboState.select === select && !$("#comboPopup").hidden) closeCombo();
      else openCombo(select, trigger);
    });
    var label = select.id ? document.querySelector('label[for="' + select.id + '"]') : null;
    if (label) {
      label.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        trigger.focus();
        trigger.click();
      });
    }
    select.addEventListener("change", function () { refreshCombo(select); });
    refreshCombo(select);
  }

  function enhanceAllSelects(root) {
    $$("select", root || document).forEach(enhanceSelect);
  }

  function initComboEvents() {
    $("#comboSearch").addEventListener("input", function () {
      buildComboList(this.value);
    });
    $("#comboSearch").addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setComboActive(comboState.active < 0 ? 0 : comboState.active + 1, true);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setComboActive(
          comboState.active <= 0 ? comboState.options.length - 1 : comboState.active - 1,
          true
        );
      } else if (event.key === "Enter") {
        event.preventDefault();
        chooseComboOption(comboState.active >= 0 ? comboState.active : 0);
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeCombo(true);
      } else if (event.key === "Tab") {
        event.preventDefault();
        closeCombo(true);
      }
    });
    $("#comboList").addEventListener("click", function (event) {
      var option = event.target.closest(".combo-option");
      if (!option) return;
      chooseComboOption(Number(option.getAttribute("data-index")));
    });
    document.addEventListener("click", function (event) {
      if ($("#comboPopup").hidden) return;
      if ($("#comboPopup").contains(event.target)) return;
      if (comboState.trigger && comboState.trigger.contains(event.target)) return;
      closeCombo();
    });
    window.addEventListener("resize", positionCombo);
    window.addEventListener("scroll", positionCombo, true);
  }

  function setSelectOptions(id, items, placeholder) {
    var select = $("#" + id);
    if (!select) return;
    var current = select.value;
    select.dataset.i18nPlaceholder = placeholder || "";
    select.innerHTML = "";
    if (placeholder) {
      var head = document.createElement("option");
      head.value = "";
      head.textContent = t(placeholder);
      select.appendChild(head);
    }
    (items || []).forEach(function (item) {
      var option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      select.appendChild(option);
    });
    selectData[id] = items || [];
    var valid = (items || []).some(function (item) {
      return String(item.value) === String(current);
    });
    select.value = valid ? current : "";
    refreshCombo(select);
  }

  function getSelectValue(id) {
    var select = $("#" + id);
    return select ? select.value : "";
  }

  function setSelectValue(id, value) {
    var select = $("#" + id);
    if (!select) return;
    select.value = String(value == null ? "" : value);
    refreshCombo(select);
  }

  function getSelectItem(id) {
    var select = $("#" + id);
    if (!select) return null;
    return (selectData[id] || []).filter(function (item) {
      return String(item.value) === String(select.value);
    })[0] || null;
  }

  function loadInstances() {
    if (!apiReady()) return Promise.resolve();
    return api().get("/api/metadata/instances").then(function (data) {
      state.instances = data.instances || [];
      var select = $("#desktopInstance");
      var html = ['<option value="">' +
        (state.instances.length ? t("Choose an instance…") : t("No open instance")) +
        "</option>"];
      state.instances.forEach(function (item) {
        html.push('<option value="' + item.port + '">' + escapeHtml(item.label) + "</option>");
      });
      select.innerHTML = html.join("");
      if (state.instances.length === 1) select.value = String(state.instances[0].port);
      refreshCombo(select);
      state.instanceHint = data.hint || "";
      $("#instanceHint").textContent = tr(state.instanceHint) || "";
      renderModelAvailability();
      return data;
    }).catch(function (error) {
      addLog(t("The Desktop instance could not be read: ") + error.message, "warn");
    });
  }

  function renderModelAvailability() {
    var scope = $("#scope").value;
    var supportsModel = !state.pbix || state.pbix.has_local_model;
    var needed = scope !== "report" && supportsModel;
    $("#desktopInstance").disabled = !needed;
    $("#reloadDesktop").disabled = !needed;
    if (scope === "report") {
      $("#instanceHint").textContent = t("Report scope only: the Power BI Desktop instance is not used.");
    } else if (state.pbix && !state.pbix.has_local_model) {
      $("#instanceHint").textContent = t("This file is a live connection; the Power BI Desktop instance is not used.");
    } else if (!state.instances.length) {
      $("#instanceHint").textContent = t("No Power BI Desktop instance is open. Open a .pbix file, then Reload.");
    }
  }

  function loadWorkspaces() {
    if (!apiReady()) return Promise.resolve();
    return api().get("/api/metadata/workspaces").then(function (data) {
      state.workspaces = data.workspaces || [];
      var options = state.workspaces.map(function (item) {
        return { value: item.id, label: item.label, data: item };
      });
      setSelectOptions("modelWorkspace", options, "Choose a model workspace…");
      setSelectOptions("reportWorkspace", options, "Choose a report workspace…");
      setSelectOptions("shotWorkspace", options, "Choose a workspace…");
      state.workspaceHint = data.hint || "";
      $("#workspaceHint").textContent = tr(state.workspaceHint) ||
        t("Type a workspace name to filter, or open the list.");
      return data;
    }).catch(function (error) {
      addLog(t("Workspace catalog could not be read: ") + error.message, "error");
    });
  }

  function loadModelContents() {
    var workspaceId = getSelectValue("modelWorkspace");
    if (!workspaceId || !apiReady()) return Promise.resolve();
    $("#workspaceHint").textContent = t("Loading model workspace datasets…");
    return api().get(
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
        : t("This model workspace has no readable datasets.");
      return data;
    }).catch(function (error) {
      $("#workspaceHint").textContent = tr(error.message);
      addLog(tr(error.message), "error");
    });
  }

  function loadReportContents() {
    var workspaceId = getSelectValue("reportWorkspace");
    if (!workspaceId || !apiReady()) return Promise.resolve();
    $("#reportHint").textContent = t("Loading report workspace…");
    return api().get(
      "/api/metadata/workspaces/" + encodeURIComponent(workspaceId) +
      "/contents?datasets=false&reports=true"
    ).then(function (data) {
      state.reports = data.reports || [];
      setSelectOptions("serviceReport", state.reports.map(function (item) {
        return { value: item.id, label: item.label, data: item };
      }), "Choose a report…");
      $("#reportHint").textContent = state.reports.length
        ? t("Paginated (RDL) reports are marked and cannot be extracted.")
        : t("This report workspace has no extractable reports.");
      return data;
    }).catch(function (error) {
      $("#reportHint").textContent = tr(error.message);
      addLog(tr(error.message), "error");
    });
  }

  function applyReportDefaults(report) {
    if (report.is_paginated) {
      $("#reportHint").textContent =
        t("Paginated (RDL) reports are not supported; choose a regular Power BI report.");
      return;
    }
    var dataset = null;
    state.datasets.forEach(function (item) {
      if (String(item.id) === String(report.dataset_id)) dataset = item;
    });
    if (dataset) {
      $("#reportHint").textContent =
        t("Report uses dataset ") + dataset.name +
        t(". The model catalog is selected separately and may be in another workspace.");
    } else if (report.dataset_id) {
      $("#reportHint").textContent =
        t("The report uses a dataset in another workspace; choose the model catalog separately.");
    } else {
      $("#reportHint").textContent = "";
    }
  }

  function refreshPbix() {
    var path = $("#pbixPath").value.trim();
    if (!apiReady()) return;
    if (!path) {
      state.pbix = null;
      $("#pbixKind").textContent = t("Choose the source .pbix file.");
      $("#pbixKind").title = "";
      renderModelAvailability();
      return;
    }
    $("#pbixKind").textContent = "Membaca file…";
    api().get("/api/metadata/pbix?path=" + encodeURIComponent(path)).then(function (data) {
      state.pbix = data;
      $("#pbixKind").textContent = data.label;
      $("#pbixKind").title = data.detail || "";
      $("#pbixPath").title = data.path || "";
      renderModelAvailability();
    }).catch(function (error) {
      state.pbix = null;
      $("#pbixKind").textContent = tr(error.message);
      renderModelAvailability();
    });
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
      payload.report_id = getSelectValue("serviceReport");
      payload.report_name = report ? report.name : "";
      payload.report_type = report ? report.report_type : "";
      payload.dataset_id = report ? report.dataset_id : "";
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
    if (!report && !model) {
      setChip($("#outputState"), "idle", t("No results"));
      return;
    }
    state.extractReady = Boolean(result.report_out);
    if (result.report_out) $("#reportWorkbook").value = result.report_out;
    if (result.model_out) $("#modelWorkbook").value = result.model_out;
    setChip($("#outputState"), "ok", t("Done"));
    $("#extractDone").hidden = false;
    var notes = [];
    if (report) notes.push((report.pages || 0) + t(" pages"));
    if (model) notes.push((model.tables || 0) + t(" tables"));
    $("#extractDoneText").textContent = notes.join(" · ") ||
      t("Workbooks saved to the output folder.");
    var stepParts = [];
    if (model) {
      stepParts.push((model.tables || 0) + t(" tables"));
      stepParts.push((model.columns || 0) + t(" columns"));
    } else if (report) {
      stepParts.push((report.pages || 0) + t(" pages"));
    }
    $("#stepStateExtract").textContent = t("Done · ") + stepParts.join(" · ");
    setMetaStep("extract", false);
    $("#summaryEmpty").hidden = true;
    $("#summaryBody").hidden = false;
    $("#sumTables").textContent = model ? model.tables : "—";
    $("#sumColumns").textContent = model
      ? model.columns
      : (report ? report.columns : "—");
    $("#sumMeasures").textContent = model
      ? model.measures
      : (report ? report.measures : "—");
    $("#sumPages").textContent = report ? report.pages : "—";
    $("#sumRelations").textContent = model ? model.relationships : "—";
    if (result.model_error) addLog(t("Note: ") + result.model_error, "warn");
    // Workbook paths now exist; refresh TSD checklist and unlock step 2.
    inspectTsd();
  }

  function runExtraction() {
    if (!apiReady()) return;
    if (state.jobId) {
      toast(t("Another job is still running"));
      return;
    }
    var payload = buildMetadataPayload();
    $("#extractDone").hidden = true;
    $("#extractRun").hidden = false;
    $("#extractBar").style.width = "6%";
    $("#extractRunPct").textContent = "";
    $("#extractRunLabel").textContent = t("Preparing extraction…");
    $("#stepStateExtract").textContent = t("Running…");
    setChip($("#outputState"), "warn", t("Running"));
    var progress = 6;
    state.extractTimer = window.setInterval(function () {
      progress = Math.min(92, progress + (progress < 50 ? 6 : 2));
      $("#extractBar").style.width = progress + "%";
      $("#extractRunPct").textContent = progress + "%";
    }, 800);
    startJob({
      kind: "metadata",
      path: "/api/metadata/run",
      body: payload,
      label: t("Metadata extraction"),
      button: $("#runExtract"),
      onDone: function (snapshot) {
        $("#extractBar").style.width = "100%";
        $("#extractRunPct").textContent = "100%";
        renderExtractResult(snapshot.result || {});
        loadOutputs();
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

  function renderTsdState(data) {
    state.tsd = data;
    var form = data.form || {};
    var status = data.status || {};
    var paths = data.paths || {};
    $("#tsdOutFolder").value = paths.out_dir || form.out_dir || "";
    $("#tsdFileName").placeholder = paths.suggested_name
      ? "Otomatis: " + paths.suggested_name
      : t("Automatic from the report name");

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
      tr(status.report && status.report.text) || t("Not selected");
    $("#modelWorkbookStatus").textContent =
      tr(status.model && status.model.text) || t("Unused");
    $("#tsdOutputState").textContent =
      tr(status.output && status.output.text) || t("No TSD document yet.");

    var cache = status.cache || {};
    $("#shotCacheStatus").textContent = cache.exists
      ? tr(cache.summary)
      : t("No cache yet; screenshots are captured during generation.");
    $("#shotCachePath").textContent = cache.path || paths.assets_dir || "";
    $("#clearShotCache").disabled = !cache.exists;
    setChip(
      $("#shotChip"),
      $("#shotEnabled").checked ? "ok" : "idle",
      $("#shotEnabled").checked ? t("Active") : t("Inactive")
    );

    var checklist = data.checklist || {};
    markChecklist(
      "checkReport", "checkReportText", t("Report workbook"),
      Boolean(checklist.report), "tersedia", t("not selected")
    );
    markChecklist(
      "checkModel", "checkModelText", t("Model workbook"),
      Boolean(checklist.model), "tersedia", "opsional"
    );
    markChecklist(
      "checkTemplate", "checkTemplateText", "Template",
      Boolean(checklist.template), "ditemukan", t("not found")
    );
    markChecklist(
      "checkContext", "checkContextText", t("Manual context"),
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
          t("The last document is available. Run Generate TSD to refresh the statistics.");
      }
    } else if (!state.tsdLastResult) {
      $("#tsdPreviewEmpty").hidden = false;
      $("#tsdPreview").hidden = true;
      $("#openTsdFile").disabled = true;
      state.tsdOutputPath = paths.out_file || "";
    }
    applyMetaSteps();
  }

  function loadTsdState() {
    if (!apiReady()) return Promise.resolve();
    return api().get("/api/tsd/state").then(function (data) {
      renderTsdState(data);
      return data;
    }).catch(function (error) {
      addLog(t("TSD status could not be read: ") + error.message, "warn");
    });
  }

  function inspectTsd() {
    if (!apiReady()) return Promise.resolve(null);
    return api().post("/api/tsd/state", tsdPayload()).then(function (data) {
      renderTsdState(data);
      return data;
    }).catch(reportError);
  }

  function scheduleTsdInspect() {
    if (state.tsdInspectTimer) window.clearTimeout(state.tsdInspectTimer);
    state.tsdInspectTimer = window.setTimeout(function () {
      state.tsdInspectTimer = null;
      inspectTsd();
    }, 300);
  }

  function startTsdProgress(label) {
    state.tsdRunning = true;
    $("#stepStateTsd").textContent = t("Running…");
    $("#tsdRun").hidden = false;
    $("#tsdBar").style.width = "8%";
    $("#tsdRunPct").textContent = "";
    $("#tsdRunLabel").textContent = label || t("Preparing the document…");
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
      ? (todos + t(" fields are marked <strong>TODO</strong> because they are empty in the manual context."))
      : t("No TODO fields in this document.");
    var hasShots = Boolean(result.screenshot_root);
    $("#tsdShotRow").hidden = !hasShots;
    if (hasShots) {
      $("#tsdShotVal").textContent =
        (result.screenshot_pages || 0) + t(" pages · ") +
        (result.screenshot_visuals || 0) + t(" visuals · ") +
        (result.screenshot_mobile || 0) + " mobile";
    }
    state.tsdOutputPath = result.output || state.tsdOutputPath;
    $("#tsdPreviewEmpty").hidden = true;
    $("#tsdPreview").hidden = false;
    $("#openTsdFile").disabled = false;
    $("#tsdBar").style.width = "100%";
    $("#tsdRunPct").textContent = "100%";
    state.tsdRunning = false;
    $("#stepStateTsd").textContent = t("Document ready");
    toast("TSD dibuat: " + pages + t(" pages / ") + visuals + t(" visuals"));
  }

  function runTsd() {
    if (!apiReady()) return;
    if (state.jobId) {
      toast(t("Another job is still running"));
      return;
    }
    startTsdProgress(t("Preparing the TSD document…"));
    startJob({
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

  function loadTsdReports() {
    var workspaceId = getSelectValue("shotWorkspace");
    if (!workspaceId || !apiReady()) {
      setSelectOptions("shotReport", [], "Choose a report…");
      return Promise.resolve();
    }
    return api().get(
      "/api/metadata/workspaces/" + encodeURIComponent(workspaceId) +
      "/contents?datasets=false&reports=true"
    ).then(function (data) {
      state.tsdReports = data.reports || [];
      setSelectOptions("shotReport", state.tsdReports.map(function (item) {
        return { value: item.id, label: item.label, data: item };
      }), "Choose a report…");
      return data;
    }).catch(reportError);
  }

  function captureTsdScreenshots() {
    if (!apiReady()) return;
    if (!$("#shotEnabled").checked) {
      toast(t("Check 'Capture screenshots' first"));
      return;
    }
    if (!getSelectValue("shotWorkspace") || !getSelectValue("shotReport")) {
      toast(t("Choose a workspace and report for screenshots"));
      return;
    }
    startTsdProgress(t("Capturing report screenshots…"));
    startJob({
      kind: "tsd_capture",
      path: "/api/tsd/capture",
      body: tsdPayload(),
      label: t("Capture report screenshots"),
      button: $("#captureScreenshots"),
      onDone: function (snapshot) {
        var result = snapshot.result || {};
        toast(
          "Screenshot: " + (result.pages || 0) + t(" pages / ") +
          (result.visuals || 0) + t(" visuals")
        );
        inspectTsd();
      }
    });
  }

  function clearTsdCache() {
    if (!apiReady()) return;
    if (!window.confirm(t("Clear the TSD screenshot cache for this report?"))) return;
    api().post("/api/tsd/cache/clear", tsdPayload()).then(function (data) {
      if (data.state) renderTsdState(data.state);
      toast(data.removed ? t("Screenshot cache cleared") : t("No cache yet"));
    }).catch(reportError);
  }

  function openTsdDocument() {
    var path = state.tsdOutputPath ||
      (state.tsd && state.tsd.paths && state.tsd.paths.out_file) || "";
    if (!path) {
      toast(t("No TSD document yet"));
      return;
    }
    window.open(
      "/api/tsd/preview?path=" + encodeURIComponent(path),
      "_blank",
      "noopener"
    );
  }

  function openTsdFolder() {
    var path = state.tsdOutputPath ||
      (state.tsd && state.tsd.paths && state.tsd.paths.out_file) || "";
    var folder = path ? parentDir(path) : $("#tsdOutFolder").value.trim();
    if (!folder) {
      toast(t("Output folder not set"));
      return;
    }
    api().post("/api/files/open", { path: folder, mode: "open" }).catch(reportError);
  }

  function loadTsdManual(quiet) {
    if (!apiReady()) return Promise.resolve(null);
    var path = tsdManualPath();
    return api().get("/api/tsd/manual?path=" + encodeURIComponent(path)).then(function (data) {
      state.tsdManual = data.data || {};
      $("#contextJson").value = data.path || path;
      state.tsdManualCustom = true;
      $("#contextStatus").textContent = data.exists
        ? t("Sidecar loaded.")
        : t("No sidecar yet; new content is written when you save.");
      if (!quiet) toast(data.exists ? t("Manual context loaded") : t("Sidecar not found"));
      scheduleTsdInspect();
      return data;
    }).catch(reportError);
  }

  function saveTsdManualFile(data, quiet) {
    if (!apiReady()) return Promise.resolve(null);
    var path = tsdManualPath();
    return api().put("/api/tsd/manual", {
      path: path,
      data: data || {}
    }).then(function (result) {
      state.tsdManual = result.data || {};
      state.tsdManualCustom = true;
      $("#contextJson").value = result.path || path;
      $("#contextStatus").textContent = t("Sidecar saved.");
      if (!quiet) toast(t("Manual context saved"));
      scheduleTsdInspect();
      return result;
    }).catch(reportError);
  }

  function tsdManualPath() {
    var value = $("#contextJson").value.trim();
    if (value) return value;
    return (state.tsd && state.tsd.paths && state.tsd.paths.manual_path) || "";
  }

  function openJsonDialog() {
    if (!apiReady()) return;
    loadTsdManual(true).then(function () {
      $("#jsonDialogPath").textContent = tsdManualPath();
      $("#jsonEditor").value = JSON.stringify(state.tsdManual || {}, null, 2);
      $("#jsonStatus").textContent = t("JSON must be an object. Save writes a sidecar at the path above.");
      $("#jsonDialog").showModal();
      $("#jsonEditor").focus();
    });
  }

  function saveJsonDialog() {
    var text = $("#jsonEditor").value.trim();
    var data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        $("#jsonStatus").textContent = t("Invalid JSON: ") + error.message;
        return;
      }
    }
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
      $("#jsonStatus").textContent = t("JSON content must be an object (not an array/null).");
      return;
    }
    saveTsdManualFile(data, true).then(function (result) {
      if (result) {
        $("#jsonDialog").close();
        toast(t("Manual context saved"));
      }
    });
  }

  // -- Analisa Semantic Model --------------------------------------------
  var ANALYSIS_CHEVRON = '<svg class="od-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
  var ANALYSIS_ICONS = {
    table: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="1.6"/><path d="M3 9h18M9 9v11"/></svg>',
    group: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10"/></svg>',
    column: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1.6"/><path d="M9 4v16M15 4v16"/></svg>',
    measure: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 19L18 5"/><path d="M6 5h3M15 19h3"/></svg>',
    link: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13.5a4 4 0 0 1 0-5.7l2.4-2.4a4 4 0 0 1 5.7 5.7l-1.6 1.6"/><path d="M14 10.5a4 4 0 0 1 0 5.7l-2.4 2.4a4 4 0 0 1-5.7-5.7l1.6-1.6"/></svg>',
    code: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 7l-5 5 5 5"/><path d="M15 7l5 5-5 5"/></svg>',
    query: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>',
    page: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></svg>',
    report: '<svg class="row-ico is-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 3h9l5 5v13H5z"/><path d="M14 3v5h5"/><path d="M8 13h8M8 17h5"/></svg>',
    visual: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20V4"/><path d="M4 20h16"/><rect x="7" y="12" width="3" height="5" rx=".6"/><rect x="12" y="8" width="3" height="9" rx=".6"/><rect x="17" y="5" width="3" height="12" rx=".6"/></svg>',
    filter: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6h16l-6.4 7.4V19l-3.2-1.8v-3.8z"/></svg>',
    hidden: '<svg class="row-ico is-hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 10.6a2 2 0 002.8 2.8"/><path d="M9.4 5.3A9.5 9.5 0 0112 5c5 0 9 4.5 9 7a12 12 0 01-2.4 3.6"/><path d="M6.2 6.2A13 13 0 003 12c0 2.5 4 7 9 7a9.6 9.6 0 004.3-1"/></svg>'
  };
  var MENU_ICONS = {
    more: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="12" cy="19" r="1.7"/></svg>',
    expand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>',
    collapse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 15l6-6 6 6"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="1.8"/><path d="M15 5H6a2 2 0 00-2 2v9"/></svg>',
    sigma: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 4H6l6 8-6 8h12"/></svg>',
    lineage: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="12" r="2"/><path d="M8 5.8L16 11M8 18.2L16 13"/></svg>',
    graph: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M7 6h10M6 8l5 8M18 8l-5 8"/></svg>',
    details: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 9v11"/></svg>',
    raw: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 7l-5 5 5 5"/><path d="M15 7l5 5-5 5"/></svg>',
    dependencies: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="19" r="2"/><path d="M12 7v5M12 12l-5 5M12 12l5 5"/></svg>',
    table: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="1.8"/><path d="M3 9h18M3 14h18M9 9v11"/></svg>',
    model: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>',
    export: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v10"/><path d="M8 10l4 4 4-4"/><path d="M5 19h14"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M4.2 7.5l2.2 1.3M17.6 15.2l2.2 1.3M4.2 16.5l2.2-1.3M17.6 8.8l2.2-1.3"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>'
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
    dataflow: "Power BI Dataflow",
    file: "File",
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
      placeholder: t("Column, measure, or table name"),
      filters: [["all", t("All types")], ["columns", t("Columns")], ["measures", "Measure"]],
      unused: true,
      expandable: true
    },
    tables: {
      placeholder: t("Table, column, or measure name"),
      filters: [["all", t("All types")], ["columns", t("Columns")], ["measures", "Measure"]],
      unused: true,
      expandable: true
    },
    relationships: {
      placeholder: t("Relationship or column name"),
      filters: [["all", t("All statuses")], ["active", t("Active")], ["inactive", t("Inactive")]],
      unused: false,
      expandable: false
    },
    report: {
      placeholder: t("Report, page, or workspace name"),
      filters: [["all", t("All statuses")], ["used", t("Used")], ["unused", t("Unused")]],
      unused: false,
      expandable: true
    },
    dax: {
      placeholder: t("Measure, calculated column, or DAX expression"),
      filters: [["all", t("All types")], ["Measure", "Measure"], ["Calculated column", "Calculated column"]],
      unused: false,
      expandable: true
    },
    m: {
      placeholder: t("Query, parameter, or M expression"),
      filters: [["all", t("All types")], ["Tabel", t("Table")], ["M parameter", "M parameter"], ["Expression", "Expression"]],
      unused: false,
      expandable: true
    },
    health: {
      placeholder: t("Rule, object, or report name"),
      filters: [
        ["all", t("All severities")],
        ["critical", t("Critical")],
        ["warning", t("Warning")],
        ["info", t("Info")]
      ],
      unused: false,
      expandable: false
    }
  };
  var ANALYSIS_STATUS_ORDER = {
    "Tidak dipakai": 0,
    "Perlu dicek": 1,
    "Dipakai": 2,
    "Wajib dipertahankan": 3
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
    "Tidak dipakai": "Unused",
    "Perlu dicek": "Needs review",
    "Dipakai": "Used",
    "Wajib dipertahankan": "Must keep"
  };

  function tStatus(status) {
    var english = ANALYSIS_STATUS_LABELS[status];
    return english ? t(english) : status;
  }

  function analysisStatusChip(status) {
    var map = {
      "Tidak dipakai": "chip-danger",
      "Perlu dicek": "chip-warn",
      "Dipakai": "chip-ok",
      "Wajib dipertahankan": "chip-accent"
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
    if (result.coverage_complete) return t(" · full coverage");
    return result.coverage ? " · " + result.coverage : t(" · partial coverage");
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

  function analysisSyncReportOptions() {
    var enabled = $("#includeReports").checked;
    $("#includeOther").disabled = !enabled;
    $("#includePersonal").disabled = !enabled;
  }

  function analysisSavePrefs() {
    if (!apiReady()) return Promise.resolve(null);
    return api().post("/api/analysis/preferences", {
      object_filter: ["all", "columns", "measures"].includes(state.analysisObjectFilter)
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

  function analysisLoad() {
    if (!apiReady()) return Promise.resolve();
    return api().get("/api/analysis/state").then(function (data) {
      var options = (data.workspaces || []).map(function (item) {
        return { value: item.id, label: item.label, data: item };
      });
      setSelectOptions("wsSelect", options, "Choose a workspace…");
      analysisApplyPrefs(data.settings || {});
      var missing = data.credentials_missing || [];
      setChip(
        $("#spStatus"),
        missing.length ? "warn" : "ok",
        missing.length ? t("Credentials are incomplete") : t("Service principal ready")
      );
      $("#modelSelect") && setSelectOptions("modelSelect", [], "Choose a semantic model…");
      analysisApplyTabTools(state.analysisTab, false);
      analysisRender();
      return data;
    }).catch(function (error) {
      addLog(t("Analysis catalog could not be read: ") + error.message, "warn");
    });
  }

  function analysisLoadDatasets() {
    var workspaceId = getSelectValue("wsSelect");
    state.analysis = null;
    if (!workspaceId || !apiReady()) {
      setSelectOptions("modelSelect", [], "Choose a semantic model…");
      analysisRender();
      return Promise.resolve();
    }
    setSelectOptions("modelSelect", [], "Loading datasets…");
    $("#analyzeSummary").textContent = t("Loading semantic models…");
    return api().get(
      "/api/analysis/workspaces/" + encodeURIComponent(workspaceId) + "/datasets"
    ).then(function (data) {
      setSelectOptions("modelSelect", (data.datasets || []).map(function (item) {
        return { value: item.id, label: item.name, data: item };
      }), "Choose a semantic model…");
      $("#analyzeSummary").textContent = t("Choose a semantic model to analyze.");
      analysisRender();
      return data;
    }).catch(function (error) {
      setSelectOptions("modelSelect", [], "Choose a semantic model…");
      $("#analyzeSummary").textContent = tr(error.message);
      reportError(error);
    });
  }

  function analysisScheduleRun(delay) {
    if (state.analysisTimer) window.clearTimeout(state.analysisTimer);
    state.analysisTimer = window.setTimeout(function () {
      state.analysisTimer = null;
      analysisAutoRun();
    }, typeof delay === "number" ? delay : 750);
  }

  function analysisAutoRun() {
    if (!getSelectValue("modelSelect")) return;
    if (state.jobId) {
      $("#analyzeSummary").textContent = t(
        "Another job is still running. Try again when it finishes."
      );
      return;
    }
    analysisRun(true);
  }

  function analysisNote(result) {
    var stamp = String(result.analyzed_at || "")
      .replace("T", " ").slice(0, 16);
    var text = t("Updated ") + (stamp || "-") + ".";
    if (result.reports_included === false) {
      text = t("Model only — report usage not included.") + " " + text;
    }
    return text;
  }

  function analysisApply(result, note) {
    state.analysis = result;
    state.analysisNote = note || "";
    state.analysisOpen = {};
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
    var sizeNote = (totals.tables || 0) + t(" tables in the model");
    $("#metricSizeNote").textContent = sizeNote;
    $("#metricSizeNote").title =
      "data " + analysisFmtBytes(totals.data_bytes) +
      t(" · hierarchy ") + analysisFmtBytes(totals.hierarchy_bytes) +
      " · dictionary " + analysisFmtBytes(totals.dictionary_bytes);
    $("#metricColumns").textContent = (totals.columns || 0);
    $("#metricColumnsNote").textContent = (totals.hidden_columns || 0) + t(" hidden columns");
    $("#metricMeasures").textContent = (totals.measures || 0);
    $("#metricMeasuresNote").textContent = totals.helper_measures
      ? totals.helper_measures + t(" stored in _Measures")
      : t("measures in the model");
    $("#metricUnusedColumns").textContent = (totals.unused_columns || 0);
    var pct = totals.model_bytes
      ? Math.round((totals.unused_bytes || 0) / totals.model_bytes * 100)
      : 0;
    var unusedNote = analysisFmtBytes(totals.unused_bytes) + " · " + pct + "% dataset";
    $("#metricUnusedColumnsNote").textContent = unusedNote;
    $("#metricUnusedColumnsNote").title = unusedNote;
    $("#metricUnusedMeasures").textContent = (totals.unused_measures || 0);
    $("#metricUnusedMeasuresNote").textContent = totals.measures
      ? Math.round((totals.unused_measures || 0) / totals.measures * 100) + t("% of total measures")
      : t("not referenced");
    if (result.reports_included === false) {
      $("#metricReport").textContent = "—";
      $("#metricReportNote").textContent = t("Report usage not included");
    } else {
      $("#metricReport").textContent = (totals.reports || 0) + t(" reports");
      var reportNote = (totals.pages || 0) + t(" pages · ") +
        (totals.visuals || 0) + t(" visuals");
      $("#metricReportNote").textContent = reportNote;
      $("#metricReportNote").title = result.coverage || "";
    }
    setChip(
      $("#spStatus"),
      result.coverage_complete ? "ok" : "warn",
      result.coverage_complete
        ? t("Full coverage")
        : (result.reports_included === false
          ? t("Model only — report usage not included")
          : t("Partial coverage"))
    );
    analysisApplyTabTools(state.analysisTab, false);
    analysisRender();
  }

  function analysisApplyTabTools(name, reset) {
    var config = analysisTabConfig(name);
    $("#searchAnalyze").placeholder = config.placeholder;
    $("#toolTypeWrap").hidden = config.filters.length < 2;
    $("#toolUnusedWrap").hidden = !config.unused;
    $("#expandRows").hidden = !config.expandable;
    $("#collapseRows").hidden = !config.expandable;
    $("#relViewSwitch").hidden = name !== "relationships";
    if (name === "relationships") analysisSyncRelView();
    var options = config.filters.map(function (pair) {
      return { value: pair[0], label: pair[1] };
    });
    setSelectOptions("typeAnalyze", options, null);
    var desired = reset ? "all" : (state.analysisObjectFilter || "all");
    var valid = options.some(function (item) { return item.value === desired; });
    setSelectValue("typeAnalyze", valid ? desired : "all");
  }

  function analysisSyncRelView() {
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
      all: 0, tables: 0, relationships: 0, report: 0, dax: 0, m: 0, health: 0
    };
    if (!result) return counts;
    var totals = result.totals || {};
    counts.all = (totals.columns || 0) + (totals.measures || 0);
    counts.tables = (result.tables || []).length;
    counts.relationships = (result.relationships || []).length;
    counts.report = (result.reports || []).length;
    counts.dax = (result.measures || []).length + analysisCalculatedColumns().length;
    counts.m = (result.m_queries || []).length;
    counts.health = ((result.health && result.health.items) || []).length;
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
    $("#tabCountReport").textContent = state.analysis ? fmtInt(counts.report) : "";
    $("#tabCountDax").textContent = state.analysis ? fmtInt(counts.dax) : "";
    $("#tabCountM").textContent = state.analysis ? fmtInt(counts.m) : "";
    $("#tabCountHealth").textContent = state.analysis ? fmtInt(counts.health) : "";
  }

  function analysisNameCell(name, icon, options) {
    options = options || {};
    var html = '<div class="name-cell">';
    if (options.toggleId) {
      html += '<button type="button" class="row-toggle" data-analysis-toggle="' +
        escapeHtml(options.toggleId) + '" aria-expanded="' +
        (options.open ? "true" : "false") + '" aria-label="' +
        (options.open ? t("Collapse ") : t("Expand ")) + escapeHtml(name) + '">' +
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
        escapeHtml(t("Item actions")) + '" title="' +
        escapeHtml(t("Item actions")) + '">' + MENU_ICONS.more + "</button>";
    }
    html += "</div>";
    return html;
  }

  function analysisIsOpen(id, defaultOpen, ignoreQuery) {
    var query = ($("#searchAnalyze").value || "").trim();
    if (query && !ignoreQuery) return true;
    if (state.analysisForceOpen === true || state.analysisForceOpen === false) {
      return state.analysisForceOpen;
    }
    if (Object.prototype.hasOwnProperty.call(state.analysisOpen, id)) {
      return Boolean(state.analysisOpen[id]);
    }
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

  function analysisRowTarget(node) {
    return {
      kind: node.getAttribute("data-item-kind") || "column",
      table: node.getAttribute("data-item-table") || "",
      name: node.getAttribute("data-item-name") || ""
    };
  }

  function analysisMenuEntries(target) {
    if (target.kind === "table") {
      return [
        { id: "table-lineage", label: t("Table lineage"), icon: "graph", primary: true },
        { id: "table-details", label: t("Table details"), icon: "details" },
        { id: "table-show", label: t("Show in analysis"), icon: "table" },
        { id: "table-copy", label: t("Copy table name"), icon: "copy" },
        { divider: true },
        { id: "exports", label: t("Exports"), icon: "export", submenu: "exports" }
      ];
    }
    var item = analysisFindItem(target.kind, target.table, target.name);
    var isMeasure = target.kind === "measure";
    var hasChildren = Boolean(item && (item.children || []).length);
    var canToggle = hasChildren && state.analysisTab === "all";
    var entries = [
      {
        id: "expand",
        label: t("Expand items below"),
        icon: "expand",
        disabled: !canToggle
      },
      {
        id: "collapse",
        label: t("Collapse items below"),
        icon: "collapse",
        disabled: !canToggle
      },
      { id: "copy", label: t("Copy text"), icon: "copy" },
      { divider: true }
    ];
    if (isMeasure) {
      entries.push({ id: "dax", label: t("View DAX expression"), icon: "sigma" });
    }
    entries.push(
      { id: "lineage", label: t("View column lineage"), icon: "lineage" },
      {
        id: "lineage-graph",
        label: t("View column lineage graph"),
        icon: "graph",
        primary: true
      },
      {
        id: "details",
        label: isMeasure ? t("Measure details") : t("Column details"),
        icon: "details"
      },
      {
        id: "raw-metadata",
        label: isMeasure ? t("Measure raw data") : t("Column raw data"),
        icon: "raw"
      },
      {
        id: "preview",
        label: t("Preview values"),
        icon: "query"
      },
      {
        id: "dependencies",
        label: t("View dependencies"),
        icon: "dependencies",
        submenu: "dependencies"
      },
      {
        id: "table-options",
        label: t("Table options"),
        icon: "table",
        submenu: "table"
      },
      {
        id: "model-options",
        label: t("Model options"),
        icon: "model",
        submenu: "model"
      },
      {
        id: "exports",
        label: t("Exports"),
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
        ? '<span class="menu-badge">' + escapeHtml(t("Soon")) + "</span>"
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
        '<span class="menu-label">' + escapeHtml(t(entry.label)) + "</span></div>";
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

  function analysisOpenSubmenu(action, anchorEl) {
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

  function analysisCloseSubmenu(restoreFocus) {
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

  function analysisOpenMenu(target, anchor) {
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

  function analysisCloseMenu(restoreFocus) {
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

  function analysisRunMenuAction(action) {
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
      else showView("pengaturan");
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

  function copyTextValue(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        toast(t("Copied to clipboard"));
      }).catch(function () {
        toast(t("Copy failed"));
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
      toast(copied ? t("Copied to clipboard") : t("Copy failed"));
    } catch (error) {
      toast(t("Copy failed"));
    }
  }

  function analysisOpenInfoDialog(title, sub, html) {
    var dialog = $("#analysisDetailsDialog");
    if (!dialog) return;
    $("#analysisDetailsTitle").textContent = title;
    $("#analysisDetailsSub").textContent = sub || "";
    $("#analysisDetailsBody").innerHTML = html;
    $("#copyAnalysisExpression").hidden = true;
    if (dialog.open) dialog.close();
    dialog.showModal();
  }

  function analysisOpenTableDetails(target) {
    var info = (state.analysis.tables || []).filter(function (table) {
      return table.name === target.table;
    })[0] || {};
    var query = (state.analysis.m_queries || []).filter(function (item) {
      return item.kind === "Tabel" && item.name === target.table;
    })[0] || {};
    var rows = [
      [t("Table"), target.table],
      [t("Mode"), info.storage_mode || "\u2014"],
      [t("Partitions"), info.partition_count || 0],
      [t("Rows"), info.rows || 0],
      [t("Size"), info.size || analysisFmtBytes(info.size_bytes || 0)],
      [t("Columns"), info.column_count || 0],
      [t("Measures"), info.measure_count || 0],
      [t("Source"), query.source || "\u2014"],
      [t("Query"), query.detail || "\u2014"]
    ];
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    if (query.expression) {
      html += '<h3 class="detail-heading">' + escapeHtml(t("Expression")) +
        '</h3><pre class="detail-code">' + escapeHtml(query.expression) + "</pre>";
    }
    analysisOpenInfoDialog(t("Table details"), "'" + target.table + "'", html);
  }

  function analysisOpenModelDetails() {
    var result = state.analysis;
    if (!result) {
      toast(t("Run the analysis first"));
      return;
    }
    var dataset = result.dataset || {};
    var totals = result.totals || {};
    var rows = [
      [t("Model"), dataset.name || ""],
      [t("Workspace"), dataset.workspace_name || ""],
      [t("Dataset ID"), dataset.id || ""],
      [t("Analyzed at"), String(result.analyzed_at || "").replace("T", " ").slice(0, 19)],
      [t("Method"), result.method || ""],
      [t("Coverage"), result.coverage || ""],
      [t("Model size"), analysisFmtBytes(totals.model_bytes || 0)],
      [t("Tables"), totals.tables || 0],
      [t("Columns"), totals.columns || 0],
      [t("Measures"), totals.measures || 0],
      [t("Reports"), totals.reports || 0],
      [t("Pages"), totals.pages || 0],
      [t("Visuals"), totals.visuals || 0],
      [t("Report usage"), result.reports_included === false
        ? t("Not included") : t("Included")]
    ];
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    analysisOpenInfoDialog(t("Model details"), dataset.name || "", html);
  }

  function analysisCopyModelName() {
    var result = state.analysis;
    if (!result) {
      toast(t("Run the analysis first"));
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
    $("#searchAnalyze").value = target.table;
    analysisSetTab("all");
    var wrap = $("#analyzeTableWrap");
    if (wrap) wrap.scrollIntoView({ block: "nearest" });
  }

  function analysisExportLineage(target, format) {
    if (!apiReady()) return;
    api().post("/api/analysis/lineage/export", {
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
      toast(t("Export: ") + path);
      api().post("/api/files/open", { path: path, mode: "open" }).catch(function () {});
    }).catch(reportError);
  }

  function analysisExportDependencies(target) {
    if (!apiReady()) return;
    api().post("/api/analysis/dependencies/export", {
      dataset_id: getSelectValue("modelSelect"),
      kind: target.kind,
      table: target.table,
      name: target.name
    }).then(function (data) {
      if (!data.path) return;
      if (!data.rows) {
        toast(t("No dependencies"));
        return;
      }
      toast(t("Export: ") + data.path);
      api().post("/api/files/open", { path: data.path, mode: "open" }).catch(function () {});
    }).catch(reportError);
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
    var edges = (graph.edges || []).map(function (edge, index) {
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
    var nodes = (graph.nodes || []).map(function (node) {
      var group = node.group || "model";
      var color = palette.groups[group] || palette.borderStrong;
      var seed = node.side === "root";
      var stroke = seed ? palette.accent : palette.border;
      var strokeWidth = seed ? 2 : 1;
      var context = analysisLineageContext(node);
      var kind = t(LINEAGE_KIND_LABELS[node.kind] || "Node");
      var sub = kind + (context ? " \u00b7 " + context : "");
      var status = node.status ? String(tStatus(node.status)).toUpperCase() : "";
      var count = Number(node.count) > 1 ? String(Number(node.count)) : "";
      var title = analysisLineageSvgClip(node.label, 28);
      var detail = analysisLineageSvgClip(sub, 40);
      return '<g transform="translate(' + node.x + ',' + node.y + ')">' +
        '<rect width="' + node.w + '" height="' + node.h +
        '" rx="8" fill="' + palette.surface + '" stroke="' + stroke +
        '" stroke-width="' + strokeWidth + '"/>' +
        '<rect width="4" height="' + node.h + '" rx="2" fill="' + color + '"/>' +
        '<text x="14" y="22" font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="12.5" font-weight="600" fill="' + palette.text + '">' +
        escapeHtml(title) + '</text>' +
        '<text x="14" y="40" font-family="Segoe UI, Arial, sans-serif" ' +
        'font-size="10.5" fill="' + palette.text3 + '">' +
        escapeHtml(detail) + '</text>' +
        (status
          ? '<text x="14" y="55" font-family="Segoe UI, Arial, sans-serif" ' +
            'font-size="9.5" font-weight="600" letter-spacing="0.5" fill="' +
            palette.text3 + '">' + escapeHtml(status) + '</text>'
          : "") +
        (count
          ? '<rect x="' + (node.w - 32) + '" y="10" width="22" height="16" ' +
            'rx="8" fill="' + palette.surface3 + '"/>' +
            '<text x="' + (node.w - 21) + '" y="21" text-anchor="middle" ' +
            'font-family="Segoe UI, Arial, sans-serif" font-size="10" fill="' +
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
      '<g>' + edges + "</g><g>" + nodes + "</g></svg>";
  }

  function analysisLineagePngData(svg) {
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
        reject(new Error(t("Image export failed")));
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
    if (!datasetId || !apiReady()) {
      return Promise.reject(new Error(t("Run the analysis first")));
    }
    var path = "/api/analysis/lineage?dataset_id=" +
      encodeURIComponent(datasetId) +
      "&kind=" + encodeURIComponent(target.kind) +
      "&table=" + encodeURIComponent(target.table) +
      "&name=" + encodeURIComponent(target.name) +
      "&direction=both&category=all&outline_mode=compact&depth=4";
    return api().get(path);
  }

  function analysisExportLineageImage(target, format) {
    if (!target) return;
    var graphPromise = analysisLineageTargetMatches(target)
      ? Promise.resolve(state.analysisLineage)
      : analysisLineageFetchGraph(target);
    graphPromise.then(function (graph) {
      var svg = analysisLineageSvgDocument(graph);
      return (format === "png" ? analysisLineagePngData(svg) : Promise.resolve(svg))
        .then(function (content) {
          return api().post("/api/analysis/lineage/image", {
            table: target.table,
            name: target.name || target.table,
            format: format,
            content: content
          });
        });
    }).then(function (data) {
      if (!data || !data.path) return;
      toast(t("Export: ") + data.path);
      api().post("/api/files/open", { path: data.path, mode: "open" })
        .catch(function () {});
    }).catch(reportError);
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
    if (!apiReady()) return;
    var datasetId = getSelectValue("modelSelect");
    if (!datasetId) return;
    var path = "/api/analysis/lineage?dataset_id=" + encodeURIComponent(datasetId) +
      "&kind=" + encodeURIComponent(target.kind) +
      "&table=" + encodeURIComponent(target.table) +
      "&name=" + encodeURIComponent(target.name) +
      "&direction=both&category=all&depth=4";
    api().get(path).then(function (graph) {
      copyTextValue(analysisLineageMermaid(graph));
    }).catch(reportError);
  }

  function analysisResetPreview() {
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
    $("#analysisRawStatus").textContent = t("Not loaded");
    if (dialog.open) dialog.close();
    dialog.showModal();
  }

  function analysisRunPreview() {
    var target = state.analysisRawTarget;
    var datasetId = getSelectValue("modelSelect");
    if (!target || !datasetId) return;
    $("#analysisRawStatus").textContent = t("Loading preview…");
    startJob({
      kind: "analysis-preview",
      path: "/api/analysis/preview",
      body: {
        dataset_id: datasetId,
        kind: target.kind,
        table: target.table,
        name: target.name,
        limit: 100
      },
      label: t("Preview values"),
      button: $("#analysisRawLoad"),
      silent: true,
      onBusy: function () {
        $("#analysisRawStatus").textContent =
          t("Another job is still running. Try again.");
      },
      onDone: function (snapshot) {
        if (snapshot.result) analysisRenderPreview(snapshot.result);
      },
      onError: function (_snapshot, message) {
        $("#analysisRawStatus").textContent =
          tr(message || t("Preview could not be loaded"));
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
      ? rows.length + " " + t("rows")
      : t("No rows returned");
    if (payload.truncated) {
      status += " \u00b7 " + t("first {n} rows").replace("{n}", payload.limit);
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
      ? t("Measure details") : t("Column details");
    $("#analysisItemSub").textContent = "'" + target.table + "'[" + target.name + "]";
    $("#analysisItemPane").innerHTML =
      '<p class="helper">' + escapeHtml(t("Loading details…")) + "</p>";
    analysisItemTabs();
    if (dialog.open) dialog.close();
    dialog.showModal();
    var path = "/api/analysis/details?dataset_id=" + encodeURIComponent(datasetId) +
      "&kind=" + encodeURIComponent(target.kind) +
      "&table=" + encodeURIComponent(target.table) +
      "&name=" + encodeURIComponent(target.name);
    api().get(path).then(function (data) {
      state.analysisItem = data.details;
      analysisRenderItemDetails();
    }).catch(function (error) {
      $("#analysisItemPane").innerHTML =
        '<p class="helper">' + escapeHtml(tr(error.message)) + "</p>";
      reportError(error);
    });
  }

  function analysisItemTabs() {
    $$("#analysisItemTabs [role='tab']").forEach(function (tab) {
      var active = tab.getAttribute("data-item-tab") === state.analysisItemTab;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
    });
  }

  function analysisRenderItemDetails() {
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
        escapeHtml(t("Reload")) + "</button></p>";
    } else if (state.analysisItemRaw) {
      pane.innerHTML = '<pre class="detail-code">' +
        escapeHtml(analysisPrettyJson(state.analysisItemRaw)) + "</pre>";
    } else {
      pane.innerHTML = '<p class="helper">' +
        escapeHtml(t("Loading metadata…")) + "</p>";
      analysisLoadItemRaw();
    }
  }

  function analysisItemPropertiesMarkup(details) {
    var measure = details.type === "Measure";
    var rows = [
      [t("Name"), details.name],
      [t("Model"), details.model_name],
      [t("Table"), details.table_name],
      [t("Type"), details.type],
      [t("Data type"), details.data_type_str],
      [t("Size"), measure ? "\u2014" : analysisFmtBytes(details.size)],
      [t("Rows"), measure ? "\u2014" : details.rows],
      [t("Format string"), details.format_string],
      [t("Display folder"), details.display_folder],
      [t("Hidden"), details.is_hidden ? t("Yes") : t("No")],
      [t("Status"), tStatus(details.status)],
      [t("Reason"), tr(details.reason)],
      [t("Lineage tag"), details.lineage_tag ||
        (state.analysisItemRaw
          ? (state.analysisItemRaw.LineageTag || "\u2014")
          : t("See Raw JSON"))],
      [t("Annotation"), details.annotation]
    ];
    if (!measure) {
      rows.splice(6, 0,
        [t("Data size"), analysisFmtBytes(details.size_data)],
        [t("Hierarchy size"), analysisFmtBytes(details.size_hierarchy)],
        [t("Dictionary size"), analysisFmtBytes(details.size_dictionary)]
      );
    }
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    if (details.expression) {
      html += '<h3 class="detail-heading">' + escapeHtml(t("Expression")) +
        '</h3><pre class="detail-code">' +
        escapeHtml(details.expression) + "</pre>";
    }
    return html;
  }

  function analysisItemUsageMarkup(details) {
    var rows = [
      [t("Status"), tStatus(details.status)],
      [t("Reason"), tr(details.reason)],
      [t("Model dependencies"), (details.model_dependencies || []).length],
      [t("Relationships"), (details.relationship_dependencies || []).length],
      [t("Visuals"), (details.visual_dependencies || []).length],
      [t("Page level filters"), (details.page_level_filters_dependencies || []).length],
      [t("Report level filters"), (details.report_level_filters_dependencies || []).length]
    ];
    var flags = Object.keys(USAGE_FLAG_LABELS).filter(function (key) {
      return details[key] === true;
    });
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    html += '<h3 class="detail-heading">' + escapeHtml(t("Usage flags")) + "</h3>";
    html += '<div class="item-flags">' + (flags.length
      ? flags.map(function (key) {
        return '<span class="chip chip-ok"><span class="dot"></span>' +
          escapeHtml(t(USAGE_FLAG_LABELS[key])) + "</span>";
      }).join("")
      : '<span class="helper">' + escapeHtml(t("No usage detected")) + "</span>") +
      "</div>";
    if ((details.unsupported || []).length) {
      var unsupported = [];
      (details.unsupported || []).forEach(function (key) {
        var label = t(UNSUPPORTED_LABELS[key] || key);
        if (unsupported.indexOf(label) === -1) unsupported.push(label);
      });
      html += '<p class="item-note">' + escapeHtml(t("Not detected by this tool")) +
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
        '<section class="dep-group"><h3>' + escapeHtml(t(group[1])) +
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
              '" title="' + escapeHtml(t("Open lineage")) + '"'
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
      : '<p class="helper">' + escapeHtml(t("No dependencies")) + "</p>";
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
      entry.hidden ? t("Hidden") : ""
    ].filter(Boolean).join(" \u00b7 ");
  }

  function analysisPrettyJson(value) {
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
      state.analysisItemRawError = tr(message);
      if (state.analysisItemTab === "raw") analysisRenderItemDetails();
    });
  }

  function analysisCopyItemJson() {
    if (!state.analysisItem) return;
    copyTextValue(analysisPrettyJson(state.analysisItem));
  }

  function analysisFetchRawMetadata(target, onDone, onError) {
    var datasetId = getSelectValue("modelSelect");
    if (!datasetId) return;
    startJob({
      kind: "analysis-raw-metadata",
      path: "/api/analysis/raw-metadata",
      body: {
        dataset_id: datasetId,
        kind: target.kind,
        table: target.table,
        name: target.name
      },
      label: t("Raw data"),
      silent: true,
      onBusy: function () {
        if (onError) onError(t("Another job is still running. Try again."));
      },
      onDone: function (snapshot) {
        if (snapshot.result) onDone(snapshot.result);
        else if (onError) onError(t("Metadata could not be loaded"));
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
    $("#analysisRawMetaStatus").textContent = t("Loading metadata…");
    $("#analysisRawMetaJson").textContent = "";
    if (dialog.open) dialog.close();
    dialog.showModal();
    analysisReloadRawMetadata();
  }

  function analysisReloadRawMetadata() {
    var target = state.analysisRawMetaTarget;
    if (!target) return;
    state.analysisRawMeta = null;
    $("#analysisRawMetaStatus").textContent = t("Loading metadata…");
    $("#analysisRawMetaJson").textContent = "";
    analysisFetchRawMetadata(target, function (payload) {
      state.analysisRawMeta = payload.row;
      $("#analysisRawMetaStatus").textContent =
        payload.dmv + " \u00b7 " + payload.table + "[" + payload.name + "]";
      $("#analysisRawMetaJson").textContent =
        analysisPrettyJson(payload.row);
    }, function (message) {
      $("#analysisRawMetaStatus").textContent = tr(message);
    });
  }

  function analysisResetRawMetadata() {
    state.analysisRawMeta = null;
    state.analysisRawMetaTarget = null;
    $("#analysisRawMetaSub").textContent = "";
    $("#analysisRawMetaStatus").textContent = "";
    $("#analysisRawMetaJson").textContent = "";
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
    var hasError = item.has_error ? t("Yes") : t("No");
    if (kind === "measure") {
      rows = [
        [t("Table"), item.table],
        [t("Type"), item.is_hidden ? t("Measure") + " \u00b7 " + t("Hidden") : t("Measure")],
        [t("Data type"), item.data_type],
        [t("Format string"), item.format_string],
        [t("Display folder"), item.display_folder],
        [t("Status"), tStatus(item.status)],
        [t("Reason"), tr(item.reason)],
        [t("Uses"), item.uses],
        [t("Reports"), item.reports],
        [t("Has error"), hasError]
      ];
    } else {
      var breakdown = item.size_breakdown || {};
      rows = [
        [t("Table"), item.table],
        [t("Type"), item.is_calculated ? t("Calculated column") : t("Column")],
        [t("Data type"), item.data_type],
        [t("Size"), item.size],
        [t("Data size"), analysisFmtBytes(breakdown.data || 0)],
        [t("Hierarchy size"), analysisFmtBytes(breakdown.hierarchy || 0)],
        [t("Dictionary size"), analysisFmtBytes(breakdown.dictionary || 0)],
        [t("Rows"), item.rows],
        [t("Format string"), item.format_string],
        [t("Display folder"), item.display_folder],
        [t("Hidden"), item.is_hidden ? t("Yes") : t("No")],
        [t("Status"), tStatus(item.status)],
        [t("Reason"), tr(item.reason)],
        [t("Uses"), item.uses],
        [t("Reports"), item.reports],
        [t("Has error"), hasError]
      ];
    }
    var html = '<div class="detail-grid">' + rows.map(function (row) {
      return analysisDetailRow(row[0], row[1]);
    }).join("") + "</div>";
    if (item.expression) {
      html += '<h3 class="detail-heading">' + escapeHtml(t("Expression")) +
        '</h3><pre class="detail-code">' + escapeHtml(item.expression) + "</pre>";
    }
    return html;
  }

  function analysisOpenDetails(target, mode) {
    var item = analysisFindItem(target.kind, target.table, target.name);
    var dialog = $("#analysisDetailsDialog");
    if (!item || !dialog) return;
    var isMeasure = target.kind === "measure";
    $("#analysisDetailsTitle").textContent = mode === "dax"
      ? t("DAX expression")
      : (isMeasure ? t("Measure details") : t("Column details"));
    $("#analysisDetailsSub").textContent = analysisItemLabel(item);
    state.analysisDetailsExpression = String(item.expression || "");
    if (mode === "dax") {
      $("#analysisDetailsBody").innerHTML = item.expression
        ? '<pre class="detail-code">' + escapeHtml(item.expression) + "</pre>"
        : '<p class="detail-empty">' + escapeHtml(t("(no DAX expression)")) + "</p>";
    } else {
      $("#analysisDetailsBody").innerHTML = analysisDetailsMarkup(item, target.kind);
    }
    $("#copyAnalysisExpression").hidden = !item.expression;
    if (dialog.open) dialog.close();
    dialog.showModal();
  }

  // -- Lineage graph kolom/measure ----------------------------------------
  function analysisLineageOpen(target, view, category, outlineMode) {
    var dialog = $("#analysisLineageDialog");
    if (!dialog) return;
    state.analysisLineageTarget = {
      kind: target.kind,
      table: target.table,
      name: target.name
    };
    state.analysisLineage = null;
    state.analysisLineageHighlight = null;
    state.analysisLineageZoom = 1;
    state.analysisLineageDirection = "both";
    state.analysisLineageView = view === "outline" ? "outline" : "graph";
    state.analysisLineageOutlineMode =
      outlineMode === "full" ? "full" : "compact";
    state.analysisLineageCategory = category || "all";
    $("#analysisLineageSearch").value = "";
    $("#analysisLineageNodes").innerHTML = "";
    $("#analysisLineageEdges").innerHTML = "";
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
      if (label) text += " \u00b7 " + t(label);
    }
    return text;
  }

  function analysisLineageViewButtons() {
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

  function analysisLineageApplyView() {
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

  function analysisLineageReroot(kind, table, name) {
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

  function analysisLineageDirectionButtons() {
    $$("#analysisLineageDirection [data-lineage-direction]").forEach(function (button) {
      button.setAttribute(
        "aria-pressed",
        button.getAttribute("data-lineage-direction") === state.analysisLineageDirection
          ? "true" : "false"
      );
    });
  }

  function analysisLoadLineage() {
    var target = state.analysisLineageTarget;
    var datasetId = getSelectValue("modelSelect");
    if (!target || !datasetId || !apiReady()) return;
    $("#analysisLineageNodes").innerHTML = "";
    $("#analysisLineageEdges").innerHTML = "";
    $("#analysisLineageNotice").textContent = "";
    analysisLineageShowEmpty(t("Loading lineage…"), "");
    var path = "/api/analysis/lineage?dataset_id=" + encodeURIComponent(datasetId) +
      "&kind=" + encodeURIComponent(target.kind) +
      "&table=" + encodeURIComponent(target.table) +
      "&name=" + encodeURIComponent(target.name) +
      "&direction=" + encodeURIComponent(state.analysisLineageDirection) +
      "&category=" + encodeURIComponent(state.analysisLineageCategory) +
      "&outline_mode=" + encodeURIComponent(state.analysisLineageOutlineMode) +
      "&depth=4";
    api().get(path).then(function (data) {
      state.analysisLineage = data;
      $("#analysisLineageSub").textContent = analysisLineageSubtitle();
      analysisLineageRender();
    }).catch(function (error) {
      state.analysisLineage = null;
      analysisLineageShowEmpty(t("Lineage could not be loaded"), tr(error.message));
      reportError(error);
    });
  }

  function analysisLineageShowEmpty(title, text) {
    $("#analysisLineageEmpty").hidden = false;
    $("#analysisLineageEmptyTitle").textContent = title || t("No lineage data");
    $("#analysisLineageEmptyText").textContent = text || "";
  }

  function analysisLineageRender() {
    var graph = state.analysisLineage;
    if (!graph || !(graph.nodes || []).length) {
      analysisLineageShowEmpty(
        t("No lineage data"),
        t("No dependencies found")
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
    var routes = analysisLineageEdgeRoutes(graph);
    $("#analysisLineageEdges").innerHTML = (graph.edges || []).map(function (edge, index) {
      var source = byId[edge.from];
      var target = byId[edge.to];
      if (!source || !target) return "";
      return '<path class="lineage-edge kind-' + escapeHtml(edge.kind || "depend") +
        '" data-edge-from="' + escapeHtml(edge.from) +
        '" data-edge-to="' + escapeHtml(edge.to) +
        '" d="' + (routes[index] || analysisLineageEdgePath(source, target)) +
        '" marker-end="url(#lineageArrow)"></path>';
    }).join("");
    $("#analysisLineageNodes").innerHTML = (graph.nodes || []).map(
      analysisLineageNodeMarkup
    ).join("");
    $("#analysisLineageOutline").innerHTML = analysisLineageOutlineMarkup(graph);
    state.analysisLineageZoom = 1;
    state.analysisLineageHighlight = null;
    $("#analysisLineageNotice").textContent = analysisLineageNotice(graph);
    analysisLineageRenderM(graph.m_lineage);
    analysisLineageFocusSeed();
    analysisLineageApplyView();
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
    chip.textContent = t("M lineage") + ": " +
      t(labels[meta.status] || meta.status);
    chip.title = tr(meta.reason || "");
    var warnings = meta.warnings || [];
    $("#analysisLineageMDetails").hidden = warnings.length === 0;
    $("#analysisLineageMSummary").textContent =
      t("M warnings") + " (" + warnings.length + ")";
    $("#analysisLineageMList").innerHTML = warnings.map(function (warning) {
      var parts = [];
      if (warning.step) {
        parts.push('<span class="m-warning-step">' +
          escapeHtml(warning.step) + "</span>");
      }
      if (warning.column) parts.push(escapeHtml(warning.column));
      parts.push(escapeHtml(tr(warning.detail || warning.status || "")));
      return "<li>" + parts.join(" \u00b7 ") + "</li>";
    }).join("");
  }

  function analysisLineageContext(node) {
    var context = String(node.context || "");
    if (!context) return "";
    if (node.kind === "datasource" && LINEAGE_ORIGIN_LABELS[context]) {
      return t(LINEAGE_ORIGIN_LABELS[context]);
    }
    return context;
  }

  function analysisLineageNodeMarkup(node) {
    var iconKey = LINEAGE_KIND_ICONS[node.kind] || "group";
    var icon = ANALYSIS_ICONS[iconKey] || "";
    var kindLabel = t(LINEAGE_KIND_LABELS[node.kind] || "Node");
    var parts = [kindLabel];
    var context = analysisLineageContext(node);
    if (context) parts.push(context);
    var sub = parts.join(" \u00b7 ");
    var status = node.status
      ? '<span class="ln-status">' + escapeHtml(tStatus(node.status)) + "</span>"
      : "";
    var count = Number(node.count) > 1
      ? '<span class="ln-count">' + Number(node.count) + "</span>"
      : "";
    var title = node.label + (node.context ? " \u00b7 " + node.context : "");
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
      '<span class="ln-icon">' + icon + "</span>" +
      '<span class="ln-text"><span class="ln-title">' + escapeHtml(node.label) +
      '</span><span class="ln-sub">' + escapeHtml(sub) + "</span>" + status +
      "</span>" + count + "</button>";
  }

  function analysisLineageOutlineMarkup(graph) {
    var outline = graph.outline || {};
    var sections = [];
    if ((outline.upstream || []).length) {
      sections.push(
        '<section class="lo-section"><h3>' + t("Depends on") + "</h3>" +
        analysisLineageOutlineList(outline.upstream) + "</section>"
      );
    }
    if ((outline.downstream || []).length) {
      sections.push(
        '<section class="lo-section"><h3>' + t("Used by") + "</h3>" +
        analysisLineageOutlineList(outline.downstream) + "</section>"
      );
    }
    if (!sections.length) {
      return '<p class="helper">' + t("No dependencies found") + "</p>";
    }
    return sections.join("");
  }

  function analysisLineageOutlineList(items) {
    if (!items || !items.length) return "";
    return '<ul class="lo-list">' + items.map(function (item) {
      var icon = ANALYSIS_ICONS[LINEAGE_KIND_ICONS[item.kind] || "group"] || "";
      var kinds = [t(LINEAGE_KIND_LABELS[item.kind] || "Node")];
      var context = analysisLineageContext(item);
      if (context) kinds.push(context);
      var sub = kinds.join(" \u00b7 ");
      var status = item.status
        ? '<span class="lo-status">' + escapeHtml(tStatus(item.status)) + "</span>"
        : "";
      var count = Number(item.count) > 1
        ? '<span class="lo-count">' + Number(item.count) + "</span>"
        : "";
      var repeat = item.repeat ? '<span class="lo-repeat">\u2026</span>' : "";
      var row = '<span class="lo-row" data-node-id="' + escapeHtml(item.id) +
        '" data-node-kind="' + escapeHtml(item.kind) +
        '" data-node-table="' + escapeHtml(
          item.kind === "table" ? item.label : (item.context || "")
        ) +
        '" data-node-name="' + escapeHtml(item.label) + '">' +
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

  function analysisLineageRoutePath(x1, y1, laneX, y2, x2) {
    if (Math.abs(y2 - y1) < 1) {
      return "M" + x1 + " " + y1 + " H" + x2;
    }
    var radius = Math.min(
      10,
      Math.abs(y2 - y1) / 2,
      Math.abs(laneX - x1) / 2,
      Math.abs(x2 - laneX) / 2
    );
    var direction = y2 > y1 ? 1 : -1;
    return "M" + x1 + " " + y1 +
      " H" + (laneX - radius) +
      " Q" + laneX + " " + y1 + " " + laneX + " " + (y1 + direction * radius) +
      " V" + (y2 - direction * radius) +
      " Q" + laneX + " " + y2 + " " + (laneX + radius) + " " + y2 +
      " H" + x2;
  }

  function analysisLineageEdgeRoutes(graph) {
    var nodes = {};
    (graph.nodes || []).forEach(function (node) {
      nodes[node.id] = node;
    });
    var groups = {};
    var backward = [];
    (graph.edges || []).forEach(function (edge, index) {
      var source = nodes[edge.from];
      var target = nodes[edge.to];
      if (!source || !target) return;
      var x1 = source.x + source.w;
      var y1 = source.y + source.h / 2;
      var x2 = target.x;
      var y2 = target.y + target.h / 2;
      if (x2 > x1 + 8) {
        var key = Math.round(x1) + ":" + Math.round(x2);
        if (!groups[key]) groups[key] = [];
        groups[key].push({ index: index, x1: x1, y1: y1, x2: x2, y2: y2 });
      } else {
        backward.push({
          index: index,
          x1: x1,
          y1: y1,
          x2: target.x + target.w,
          y2: y2
        });
      }
    });
    var routes = {};
    Object.keys(groups).forEach(function (key) {
      var items = groups[key].slice().sort(function (left, right) {
        return left.y2 - right.y2 || left.y1 - right.y1;
      });
      var gap = items[0].x2 - items[0].x1;
      items.forEach(function (item, index) {
        var fraction = items.length === 1
          ? 0.5
          : 0.18 + 0.64 * (index / (items.length - 1));
        var laneX = item.x1 + gap * fraction;
        routes[item.index] = analysisLineageRoutePath(
          item.x1, item.y1, laneX, item.y2, item.x2
        );
      });
    });
    backward.forEach(function (item, index) {
      var outer = Math.max(item.x1, item.x2) + 24 + (index % 5) * 7;
      routes[item.index] = "M" + item.x1 + " " + item.y1 +
        " H" + outer + " V" + item.y2 + " H" + item.x2;
    });
    return routes;
  }

  function analysisLineageEdgePath(source, target) {
    var x1 = source.x + source.w;
    var y1 = source.y + source.h / 2;
    var x2 = target.x;
    var y2 = target.y + target.h / 2;
    if (x2 <= x1) {
      x2 = target.x + target.w;
      return "M" + x1 + " " + y1 + " C" + (x1 + 60) + " " + y1 + " " +
        (x2 + 60) + " " + y2 + " " + x2 + " " + y2;
    }
    var bend = Math.max(40, (x2 - x1) * 0.45);
    return "M" + x1 + " " + y1 + " C" + (x1 + bend) + " " + y1 + " " +
      (x2 - bend) + " " + y2 + " " + x2 + " " + y2;
  }

  function analysisLineageNotice(graph) {
    return (graph.notices || []).map(function (notice) {
      if (notice.code === "reports_excluded") {
        return t("Report usage not included");
      }
      if (notice.code === "truncated") {
        return t("Truncated: {n} nodes").replace("{n}", String(notice.count || 0));
      }
      if (notice.code === "m_steps_truncated") {
        return t("Truncated M steps: {n}").replace(
          "{n}", String(notice.count || 0)
        );
      }
      if (notice.code === "no_dependencies") {
        return t("No dependencies found");
      }
      return "";
    }).filter(Boolean).join(" \u00b7 ");
  }

  function analysisLineageApplyZoom() {
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

  function analysisLineageZoomBy(factor) {
    if (!state.analysisLineage) return;
    state.analysisLineageZoom = Math.min(
      2.5, Math.max(0.12, state.analysisLineageZoom * factor)
    );
    analysisLineageApplyZoom();
  }

  function analysisLineageFit() {
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

  function analysisLineageFocusSeed() {
    var graph = state.analysisLineage;
    var wrap = $("#analysisLineageCanvasWrap");
    if (!graph || !wrap) return;
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
    var span = Math.max(1, seed.x + seed.w - minX);
    var fit = (wrap.clientWidth - 40) / span;
    state.analysisLineageZoom = Math.max(0.12, Math.min(0.8, fit));
    analysisLineageApplyZoom();
    wrap.scrollLeft = 0;
    wrap.scrollTop = Math.max(
      0, seed.y * state.analysisLineageZoom - wrap.clientHeight / 2 + seed.h / 2
    );
  }

  function analysisLineageLineageSet(graph, start) {
    var outgoing = {};
    var incoming = {};
    (graph.edges || []).forEach(function (edge) {
      (outgoing[edge.from] || (outgoing[edge.from] = [])).push(edge.to);
      (incoming[edge.to] || (incoming[edge.to] = [])).push(edge.from);
    });
    var keep = {};
    keep[start] = true;
    var stack = [start];
    while (stack.length) {
      var current = stack.pop();
      (outgoing[current] || []).forEach(function (next) {
        if (!keep[next]) {
          keep[next] = true;
          stack.push(next);
        }
      });
    }
    stack = [start];
    while (stack.length) {
      var node = stack.pop();
      (incoming[node] || []).forEach(function (previous) {
        if (!keep[previous]) {
          keep[previous] = true;
          stack.push(previous);
        }
      });
    }
    return keep;
  }

  function analysisLineageSelect(nodeId) {
    var graph = state.analysisLineage;
    if (!graph || !nodeId) {
      analysisLineageClearHighlight();
      return;
    }
    state.analysisLineageHighlight = nodeId;
    var keep = analysisLineageLineageSet(graph, nodeId);
    $$("#analysisLineageNodes .lineage-node").forEach(function (element) {
      var id = element.getAttribute("data-node-id");
      element.classList.toggle("is-muted", !keep[id]);
      element.classList.toggle("is-hot", Boolean(keep[id]) && id !== nodeId);
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
  }

  function analysisLineageClearHighlight() {
    state.analysisLineageHighlight = null;
    $$("#analysisLineageNodes .lineage-node").forEach(function (element) {
      element.classList.remove("is-muted", "is-hot");
    });
    $$("#analysisLineageEdges .lineage-edge").forEach(function (element) {
      element.classList.remove("is-muted", "is-hot");
      element.setAttribute("marker-end", "url(#lineageArrow)");
    });
    analysisLineageApplySearch();
  }

  function analysisLineageApplySearch() {
    var query = ($("#analysisLineageSearch").value || "").trim().toLowerCase();
    $$("#analysisLineageNodes .lineage-node").forEach(function (element) {
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
    $$("#analysisLineageNodes .lineage-node").forEach(function (element) {
      var text = (
        element.getAttribute("data-node-name") + " " +
        (LINEAGE_KIND_LABELS[element.getAttribute("data-node-kind")] || "")
      ).toLowerCase();
      var hit = text.indexOf(query) !== -1;
      element.classList.toggle("is-hit", hit);
      element.classList.toggle("is-muted", !hit);
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
      t(") used</span>");
  }

  function analysisItemMatches(item, kind, query, type, unusedOnly) {
    if (type === "columns" && kind !== "column") return false;
    if (type === "measures" && kind !== "measure") return false;
    if (unusedOnly && item.status !== "Tidak dipakai") return false;
    if (!query) return true;
    return [item.name, item.table, item.data_type, item.status, item.reason,
      item.expression, kind].join(" ").toLowerCase().indexOf(query) !== -1;
  }

  function analysisTreeGroups() {
    var result = state.analysis;
    var query = ($("#searchAnalyze").value || "").trim().toLowerCase();
    var type = getSelectValue("typeAnalyze") || "all";
    var unusedOnly = $("#unusedOnly").checked;
    var map = {};
    var order = [];
    function ensure(name) {
      var key = name || t("(No table)");
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
    items = items.filter(function (item) {
      return analysisItemMatches(item.data, item.kind, query, type, unusedOnly);
    });
    if (state.analysisSort && state.analysisSort !== "default") {
      return analysisSortItems(items.map(function (item) {
        return item.data;
      })).map(function (data) {
        return {
          kind: items.some(function (item) {
            return item.kind === "measure" && item.data === data;
          }) ? "measure" : "column",
          data: data
        };
      });
    }
    var tableOrder = {};
    (result.tables || []).forEach(function (table, index) {
      tableOrder[table.name] = index;
    });
    return items.slice().sort(function (left, right) {
      var a = tableOrder[left.data.table];
      var b = tableOrder[right.data.table];
      if (a == null) a = 9999;
      if (b == null) b = 9999;
      if (a !== b) return a - b;
      if (left.kind !== right.kind) return left.kind === "column" ? -1 : 1;
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
    items.forEach(function (item) {
      if (item.kind === "measure") measureCount += 1;
      else columnCount += 1;
      var data = item.data;
      var id = "item:" + item.kind + ":" + data.table + ":" + data.name;
      var showExpression = item.kind !== "measure" && Boolean(data.expression);
      var expandable = showExpression || (data.children || []).length > 0;
      var open = expandable && analysisIsOpen(id, false, true);
      if (data.status === "Tidak dipakai") unused += 1;
      rows.push({
        level: 0,
        group: true,
        itemRow: true,
        item: { kind: item.kind, table: data.table || "", name: data.name || "" },
        cells: [
          analysisNameCell(data.name, item.kind === "measure" ? "measure" : "column", {
            level: 0, toggleId: expandable ? id : "", open: open, menu: true
          }),
          item.kind === "measure" ? "Measure" : "Kolom",
          escapeHtml(data.table || "—"),
          "Model",
          escapeHtml(data.data_type || "—"),
          item.kind === "measure" ? "0 B" : escapeHtml(data.size || "—"),
          analysisStatusChip(data.status),
          String(data.uses || 0),
          escapeHtml(data.format_string || "—"),
          data.has_error ? t("Yes") : t("No"),
          escapeHtml(data.display_folder || "—")
        ],
        cls: data.status === "Tidak dipakai" ? "row-unused" : "",
        numCols: [5, 7]
      });
      if (!open) return;
      if (showExpression) rows.push({ kind: "code", code: data.expression });
      rows = rows.concat(analysisChildGroups(data, id));
    });
    return {
      headers: analysisTreeHeaders(false),
      widths: ["24%", "7%", "9%", "6%", "7%", "7%", "13%", "7%", "8%", "5%", "7%"],
      rows: rows,
      summary: (state.analysisNote ? state.analysisNote + " " : "") + items.length +
        t(" items · ") + columnCount + t(" columns · ") + measureCount + t(" measures · ") +
        unused + t(" unused") + analysisCoverageSuffix(result)
    };
  }

  function analysisTreeHeaders(tablesMode) {
    if (tablesMode) {
      return [
        { label: t("Name") }, { label: t("Type") }, { label: t("Table") },
        { label: t("Source") }, { label: t("Data type") }, { label: t("Size"), num: true },
        { label: "Status" }, { label: t("# used"), num: true },
        { label: "Mode" }, { label: t("Partitions"), num: true }
      ];
    }
    return [
      { label: t("Name"), key: "name" }, { label: t("Type"), key: "type" },
      { label: t("Table / page"), key: "table" }, { label: t("Source") },
      { label: t("Data type"), key: "data_type" },
      { label: t("Size"), key: "size", num: true },
      { label: "Status", key: "status" },
      { label: t("# used"), key: "uses", num: true },
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
        : fallbackItems.filter(function (item) { return item.status !== "Tidak dipakai"; }).length;
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
          t("Table"), "—", "Model", "—", escapeHtml(size || "—"),
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
            if (measure.status === "Tidak dipakai") unused += 1;
            rows.push({
              level: 2,
              itemRow: true,
              item: { kind: "measure", table: measure.table || "", name: measure.name || "" },
              cells: [
                analysisNameCell(measure.name, "measure", { level: 2, menu: true }),
                "Measure", escapeHtml(group.name), "Model", "DAX", "0 B",
                analysisStatusChip(measure.status), String(measure.uses || 0), "—", "—"
              ],
              cls: measure.status === "Tidak dipakai" ? "row-unused" : "",
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
            analysisNameCell(t("Columns (") + group.visibleColumns.length + ")", "group", {
              level: 1, toggleId: columnId, open: columnOpen
            }),
            "Grup", escapeHtml(group.name), "Model", "—", "—", "—", "—", "—", "—"
          ]
        });
        if (columnOpen) {
          group.visibleColumns.forEach(function (column) {
            itemCount += 1;
            if (column.status === "Tidak dipakai") unused += 1;
            rows.push({
              level: 2,
              itemRow: true,
              item: { kind: "column", table: column.table || "", name: column.name || "" },
              cells: [
                analysisNameCell(column.name, "column", { level: 2, menu: true }),
                t("Column"), escapeHtml(group.name), "Model",
                escapeHtml(column.data_type || "—"), escapeHtml(column.size || "—"),
                analysisStatusChip(column.status), String(column.uses || 0), "—", "—"
              ],
              cls: column.status === "Tidak dipakai" ? "row-unused" : "",
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
        itemCount + t(" items · ") + groups.length + t(" tables · ") +
        unused + t(" unused") + analysisCoverageSuffix(result)
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
          analysisNameCell(rel.label || rel.name || t("(relationship)"), "link", { level: 0 }),
          escapeHtml(rel.type || "—"),
          escapeHtml(rel.cross || "—"),
          escapeHtml(rel.cardinality || "—"),
          rel.is_active
            ? '<span class="chip chip-ok"><span class="dot"></span>' + t("Active") + "</span>"
            : '<span class="chip chip-idle"><span class="dot"></span>' + t("Inactive") + "</span>",
          escapeHtml(rel.auto || t("No")),
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
        { label: t("Relationship name"), key: "label" }, { label: t("Type"), key: "type" },
        { label: "Cross filter", key: "cross" },
        { label: t("Cardinality"), key: "cardinality" },
        { label: "Status", key: "status" },
        {
          label: "Auto create", key: "auto",
          hint: t("Power BI automatic relationship (AutoDetected_ name or GUID)")
        },
        {
          label: t("# used"), key: "used", num: true,
          hint: t("Number of model objects that depend on the relationship (DMV DISCOVER_CALC_DEPENDENCY)")
        },
        { label: t("From column"), key: "from_column" },
        { label: t("To column"), key: "to_column" }
      ],
      widths: ["28%", "7%", "8%", "9%", "11%", "8%", "7%", "11%", "11%"],
      rows: rows,
      summary: items.length + t(" relationships · ") + active + t(" active · ") +
        (items.length - active) + t(" inactive") + analysisCoverageSuffix(state.analysis)
    };
  }

  function analysisReportStatus(status) {
    var map = {
      ok: ["chip-ok", t("Succeeded")],
      failed: ["chip-danger", t("Failed")],
      skipped: ["chip-idle", t("Skipped")],
      cached: ["chip-idle", t("From cache")],
      unsupported: ["chip-idle", t("Unsupported")],
      inaccessible: ["chip-warn", t("Inaccessible")],
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
    if (!datasetId || !apiReady()) return;
    state.reportLoading[reportId] = true;
    api().get(
      "/api/analysis/report-detail?dataset_id=" + encodeURIComponent(datasetId) +
      "&report_id=" + encodeURIComponent(reportId)
    ).then(function (data) {
      state.reportDetail[reportId] = data;
      state.reportLoading[reportId] = false;
      analysisRender();
    }).catch(function (error) {
      state.reportLoading[reportId] = false;
      addLog(t("Report details could not be loaded: ") + error.message, "warn");
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
    return t(HEALTH_RULES[rule] || rule);
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
        analysisNameCell(page.page_name || page.page_id || t("(page)"), "page", {
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
      rows.push({
        level: 0,
        group: true,
        cells: analysisReportCells(
          analysisNameCell(reportName, "report", {
            level: 0, toggleId: rootId, open: rootOpen,
            href: analysisReportUrl(report.workspace_id, report.report_id)
          }),
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
            (state.reportLoading[report.report_id] ? t("Loading report details…") : t("Details are not available yet.")) +
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
          html: '<span class="helper">Tidak ada halaman terbaca pada report ini.</span>'
        });
      }
    });

    return {
      headers: [
        { label: t("Name") }, { label: t("Type") }, { label: t("Source") },
        { label: t("Visuals"), num: true }, { label: t("Broken visuals"), num: true },
        { label: "Views", num: true }, { label: t("Pages"), num: true },
        { label: t("Theme") }, { label: t("Practice score") }
      ],
      widths: ["30%", "10%", "17%", "7%", "8%", "6%", "7%", "6%", "9%"],
      rows: rows,
      summary: reportCount + t(" reports · ") + pageTotal + t(" pages · ") +
        visualTotal + t(" visuals · ") + fieldTotal + t(" fields") +
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
    var unused = rows.filter(function (row) { return row.status === "Tidak dipakai"; }).length;
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
          row.has_error ? t("Yes") : t("No"),
          escapeHtml(row.source)
        ],
        numCols: [4]
      });
      if (open && row.expression) viewRows.push({ kind: "code", code: row.expression });
    });
    return {
      headers: [
        { label: t("Name / expression"), key: "name" }, { label: t("Table"), key: "table" },
        { label: t("Type"), key: "type" }, { label: "Status", key: "status" },
        { label: t("# used"), key: "uses", num: true },
        { label: "Error", key: "has_error" }, { label: t("Source"), key: "source" }
      ],
      widths: ["37%", "13%", "11%", "15%", "8%", "6%", "10%"],
      rows: viewRows,
      summary: rows.length + t(" expressions · ") + unused + t(" unused") +
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
          analysisNameCell(row.name, row.kind === "Tabel" ? "query" : "code", {
            level: 0, toggleId: row.expression ? id : "", open: open
          }),
          escapeHtml(row.kind || "—"),
          escapeHtml([row.source, row.detail].filter(Boolean).join(" · ") || "—"),
          warning
        ]
      });
      if (open && row.expression) viewRows.push({ kind: "code", code: row.expression });
    });
    return {
      headers: [
        { label: t("Name"), key: "name" }, { label: t("Type"), key: "kind" },
        { label: t("Source"), key: "source" }, { label: "Peringatan", key: "warning" }
      ],
      widths: ["35%", "13%", "37%", "15%"],
      rows: viewRows,
      summary: items.length + t(" queries · ") +
        items.filter(function (row) { return row.kind === "Tabel"; }).length +
        t(" tables") + analysisCoverageSuffix(state.analysis)
    };
  }

  function analysisHealthDetail(item) {
    var metrics = item.metrics || {};
    var parts = [];
    if (item.detail) parts.push(item.detail);
    if (item.rule === "unused_table" || item.rule === "isolated_table") {
      parts.push(fmtInt(metrics.columns || 0) + " " + t("columns") +
        " · " + fmtInt(metrics.measures || 0) + " " + t("measures"));
    } else if (item.rule === "large_dictionary") {
      parts.push(t("dictionary") + " " +
        Math.round(Number(metrics.share || 0) * 100) + "% · " +
        analysisFmtBytes(metrics.dictionary || 0));
    } else if (item.rule === "hidden_page_with_visuals") {
      parts.push(fmtInt(metrics.visuals || 0) + " " + t("visuals"));
    } else if (item.rule === "broken_visual") {
      parts.push(fmtInt(metrics.unresolved || 0) + " " + t("unmapped fields"));
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
            escapeHtml(t(severityLabel)) + "</span>",
          escapeHtml(t(item.area === "report" ? "Report" : "Model")),
          escapeHtml(analysisHealthRuleLabel(item.rule)),
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
        { label: t("Severity"), key: "severity" },
        { label: t("Area"), key: "area" },
        { label: t("Rule"), key: "rule" },
        { label: t("Object"), key: "object_name" },
        { label: t("Detail") },
        { label: t("Size"), key: "size", num: true }
      ],
      widths: ["10%", "9%", "21%", "25%", "27%", "8%"],
      rows: viewRows,
      summary: t("{n} findings · {c} critical · {w} warning · {i} info")
        .replace("{n}", fmtInt(items.length))
        .replace("{c}", fmtInt(counts.critical || 0))
        .replace("{w}", fmtInt(counts.warning || 0))
        .replace("{i}", fmtInt(counts.info || 0)) +
        analysisCoverageSuffix(state.analysis)
    };
  }

  function analysisHealthOpen(row) {
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
        a = "relasi";
        b = "relasi";
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

  function applyAnalysisCellTitles() {
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
        return '<tr class="code-row"><td colspan="' + headers.length + '"><pre>' +
          escapeHtml(row.code) + "</pre></td></tr>";
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

  function analysisRender() {
    analysisCloseMenu(false);
    var result = state.analysis;
    analysisTabCounts();
    $$("#analyzeTabs [role='tab']").forEach(function (tab) {
      var active = tab.getAttribute("data-analysis-tab") === state.analysisTab;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
    });
    $("#exportXlsx").disabled = !result;
    var tableWrap = $("#analyzeTableWrap");
    var graph = $("#relGraph");
    var empty = $("#analyzeEmpty");
    if (!result) {
      tableWrap.hidden = true;
      graph.hidden = true;
      empty.hidden = false;
      $("#analyzeSummary").textContent = t("Not analyzed yet");
      $("#analyzeEmptyTitle").textContent = t("No analysis results yet");
      $("#analyzeEmptyText").textContent =
        t("Choose a workspace and semantic model. Analysis starts automatically and only reads the model.");
      $("#analyzeFromEmpty").hidden = false;
      return;
    }
    var tab = state.analysisTab;
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
    else if (tab === "report") view = analysisReportRows();
    else if (tab === "dax") view = analysisDaxRows();
    else if (tab === "m") view = analysisMRows();
    else if (tab === "health") view = analysisHealthRows();
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
        $("#analyzeEmptyTitle").textContent = t("Report usage not included");
        $("#analyzeEmptyText").textContent = t(
          "Enable “Include report usage” and run the analysis again to see pages, visuals, and filters.");
      } else {
        $("#analyzeEmptyTitle").textContent = t("No matching items");
        $("#analyzeEmptyText").textContent =
          t("Change the keyword or filter to see other items in this tab.");
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

    return { positions: positions, width: width, height: height, names: names };
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
      analysisRelChip(tStatus(rel.status || "Dipakai"), rel.is_active ? "chip-ok" : "chip-idle") +
      analysisRelChip(rel.type || "") +
      analysisRelChip(rel.cross || "") +
      analysisRelChip(rel.cardinality || "") +
      analysisRelChip("auto: " + (rel.auto || t("No"))) +
      "</div></div>";
  }

  function analysisGraphSide(selected, allPairs, visiblePairs, names) {
    var side = $("#relGraphSide");
    if (selected && selected.kind === "pair") {
      var pair = allPairs[selected.value];
      if (!pair) {
        side.innerHTML = '<p class="helper">Relasi tidak ditemukan pada filter saat ini.</p>';
        return;
      }
      var status = analysisPairStatus(pair);
      side.innerHTML =
        '<p class="rel-side-title">' + escapeHtml(pair.from) + " → " +
        escapeHtml(pair.to) + "</p>" +
        '<p class="rel-side-sub">' + pair.rels.length + t(" relationships · ") +
        status.active + t(" active · ") + status.inactive + t(" inactive</p>") +
        '<div class="rel-side-list">' + pair.rels.map(analysisPairCard).join("") + "</div>" +
        '<button class="btn btn-sm rel-side-back" type="button" data-rel-back="' +
        escapeHtml(pair.from) + '">' + t("View all relationships ") + escapeHtml(pair.from) + "</button>";
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
        '<p class="rel-side-sub">Tabel · ' + info.column_count + t(" columns · ") +
        info.measure_count + t(" measures · ") + (info.rows || 0) + t(" rows</p>") +
        '<div class="rel-side-stats">' +
        analysisGraphStat(t("Relationships"), rels.length) +
        analysisGraphStat(t("Active"), active) +
        analysisGraphStat(t("Inactive"), rels.length - active) +
        analysisGraphStat(t("Related tables"), keys.length) +
        "</div>" +
        (keys.length
          ? '<div class="rel-side-list">' + keys.map(function (key) {
            var pair = visiblePairs[key];
            var target = pair.from === name ? pair.to : pair.from;
            var pairStatus = analysisPairStatus(pair);
            return '<button type="button" class="rel-side-item" data-rel-pair="' +
              escapeHtml(key) + '"><strong>' + escapeHtml(target) + "</strong><span>" +
              pair.rels.length + t(" relationships · ") + pairStatus.inactive +
              t(" inactive</span></button>");
          }).join("") + "</div>"
          : '<p class="rel-side-note">' + t("No relationships match the current filter.") + "</p>") +
        '<p class="rel-side-note">' + t("Click a line in the graph to see the relationship columns.") + "</p>";
      return;
    }
    side.innerHTML = '<p class="rel-side-title">Grafik relasi</p>' +
      '<p class="rel-side-sub">' + names.length + t(" tables · ") +
      Object.keys(visiblePairs).length + t(" table pairs in this filter.</p>") +
      '<p class="rel-side-note">Klik tabel atau garis untuk melihat detail relasi.</p>';
  }

  function applyAnalysisZoom() {
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

  function analysisSetZoom(value) {
    state.relZoom = Math.max(0.6, Math.min(2.5, value));
    applyAnalysisZoom();
  }

  function analysisRenderGraph() {
    var layer = $("#relGraphLayer");
    var relations = analysisFilteredRelationships();
    var allPairs = analysisRelPairs((state.analysis && state.analysis.relationships) || []);
    var visiblePairs = analysisRelPairs(relations);
    var tree = analysisRelTreeLayout();
    $("#relGraph").hidden = false;
    $("#analyzeSummary").textContent = relations.length + t(" relationships · ") +
      Object.keys(visiblePairs).length + t(" table pairs") +
      analysisCoverageSuffix(state.analysis);
    if (!relations.length) {
      layer.innerHTML = "";
      state.relGraphBaseWidth = 760;
      state.relGraphBaseHeight = 220;
      state.relPanX = 0;
      state.relPanY = 0;
      analysisSetZoom(1);
      $("#relGraphSide").innerHTML =
        '<div class="empty" style="padding:18px 8px"><div class="empty-title">Tidak ada relasi</div>' +
        '<p class="empty-text">Ubah kata kunci atau filter status untuk melihat relasi lain.</p></div>';
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
          " · " + pair.rels.length + " relasi") + "</title></path>");
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
        escapeHtml(name) + '" aria-label="' + t("Table ") + escapeHtml(name) +
        (touches ? t(", has relationships") : t(", no relationships")) + '" aria-current="' +
        (isSelected ? "true" : "false") + '">' +
        '<rect class="node-box' + (isSelected ? " sel" : "") + '" x="' + pos.x +
        '" y="' + pos.y + '" width="' + REL_NODE_W + '" height="' + REL_NODE_H +
        '" rx="6"></rect>' +
        '<text class="node-type" x="' + (pos.x + 11) + '" y="' + (pos.y + 16) +
        '">' + t("Table") + "</text>" +
        '<text class="node-name" x="' + (pos.x + 11) + '" y="' + (pos.y + 33) +
        '">' + escapeHtml(analysisTruncate(name, 20)) + "</text>" +
        '<text class="rel-node-meta" x="' + (pos.x + 11) + '" y="' + (pos.y + 48) +
        '">' + info.column_count + t(" columns · ") + info.measure_count +
        t(" measures</text></g>"));
    });

    layer.innerHTML = parts.join("");
    state.relGraphBaseWidth = tree.width;
    state.relGraphBaseHeight = tree.height;
    applyAnalysisZoom();
    analysisGraphSide(selected, allPairs, visiblePairs, names);
  }

  function analysisSetTab(name) {
    if (!ANALYSIS_TABS[name]) return;
    state.analysisTab = name;
    state.analysisForceOpen = null;
    state.relSelected = null;
    analysisApplyTabTools(name, true);
    analysisRender();
  }

  function analysisSetSort(key) {
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

  function analysisRun(auto) {
    if (!apiReady()) return;
    if (state.jobId) {
      if (!auto) toast(t("Another job is still running"));
      return;
    }
    if (!getSelectValue("wsSelect") || !getSelectValue("modelSelect")) {
      if (!auto) toast(t("Choose a workspace and semantic model first"));
      return;
    }
    state.analysisRunning = true;
    $("#stopAnalyze").hidden = false;
    $("#analyzeSummary").textContent = t("Analyzing the semantic model…");
    startJob({
      kind: "analysis",
      path: "/api/analysis/run",
      body: analysisPayload(),
      label: t("Semantic Model Analysis"),
      button: $("#runAnalyze"),
      onDone: function (snapshot) {
        state.analysisRunning = false;
        $("#stopAnalyze").hidden = true;
        if (snapshot.result) {
          analysisApply(snapshot.result, analysisNote(snapshot.result));
        }
      }
    });
  }

  function analysisStop() {
    if (!state.jobId || !apiReady()) return;
    api().post("/api/jobs/" + encodeURIComponent(state.jobId) + "/cancel", {})
      .then(function () { toast(t("Stop request sent")); })
      .catch(reportError);
  }

  function analysisExport() {
    if (!apiReady() || !getSelectValue("modelSelect")) {
      toast(t("Choose a semantic model first"));
      return;
    }
    api().post("/api/analysis/export", {
      dataset_id: getSelectValue("modelSelect")
    }).then(function (data) {
      toast(t("Export: ") + data.path);
      api().post("/api/files/open", { path: data.path, mode: "open" })
        .catch(function () {});
    }).catch(reportError);
  }

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

  function partitionLoadState() {
    if (!apiReady()) return Promise.resolve();
    return api().get("/api/partitions/state").then(function (data) {
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
      setChip(
        $("#partitionSourceChip"),
        missing.length ? "warn" : "idle",
        missing.length ? t("Credentials are incomplete") : t("Not loaded")
      );
      $("#partitionHint").textContent = tr(data.hint) || "";
      partitionRender();
      return data;
    }).catch(function (error) {
      addLog(t("Partition catalog could not be read: ") + error.message, "warn");
    });
  }

  function partitionLoadDatasets() {
    var workspaceId = getSelectValue("partitionWsSelect");
    state.partitions = null;
    state.partitionLoaded = false;
    state.partitionSelected = {};
    if (!workspaceId || !apiReady()) {
      setSelectOptions("partitionDatasetSelect", [], "Choose a semantic model…");
      partitionRender();
      return Promise.resolve();
    }
    setSelectOptions("partitionDatasetSelect", [], "Loading semantic models…");
    return api().get(
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
      reportError(error);
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
    setChip($("#partitionSourceChip"), "ok", t("Loaded via XMLA"));
    var warnings = result.warnings || [];
    $("#partitionHint").textContent = warnings.length
      ? warnings.map(tr).join(" · ")
      : t("Inventory loaded. Select partitions, choose a refresh type, then process.");
    partitionRender();
  }

  function partitionRender() {
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

  function partitionToggleAll(checked) {
    state.partitionSelected = {};
    if (checked) {
      partitionRows().forEach(function (_row, index) {
        state.partitionSelected[index] = true;
      });
    }
    partitionRender();
  }

  function partitionOpenConfirm() {
    var selected = partitionSelectedRows();
    if (!selected.length) {
      toast(t("Select at least one partition first"));
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

  function partitionCloseDialog() {
    var dialog = $("#partitionDialog");
    if (dialog.open) dialog.close();
  }

  function partitionConfirmProcess() {
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
      toast(t("Select at least one partition first"));
      return;
    }
    if (state.jobId) {
      toast(t("Another job is still running"));
      return;
    }
    partitionCloseDialog();
    state.partitionRunning = true;
    startJob({
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
          toast(tr((snapshot.result.refresh || {}).message) ||
            t("Partition refresh completed."));
        }
      }
    });
  }

  function partitionLoadInventory() {
    var workspaceId = getSelectValue("partitionWsSelect");
    var datasetId = getSelectValue("partitionDatasetSelect");
    if (!workspaceId || !datasetId) {
      toast(t("Choose a workspace and semantic model first"));
      return;
    }
    if (state.partitionRunning || state.jobId) {
      toast(t("Another job is still running"));
      return;
    }
    state.partitionRunning = true;
    startJob({
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
  function lineageLoadState() {
    if (!apiReady()) return Promise.resolve();
    if (state.lineageStatePromise) return state.lineageStatePromise;
    state.lineageStatePromise = api().get("/api/lineage/state").then(function (data) {
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
      $("#lineageSearch").disabled = !data.readable;
      $("#lineageSearchBtn").disabled = !data.readable;
      $("#lineageWorkspace").disabled = !data.readable;
      $("#lineageType").disabled = !data.readable;
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
      return data;
    }).catch(function (error) {
      addLog(t("Lineage status could not be read: ") + error.message, "warn");
    }).finally(function () {
      state.lineageStatePromise = null;
    });
    return state.lineageStatePromise;
  }

  function lineageSearchQuery(query, workspace, type) {
    if (!state.lineageHasDb) {
      toast(t("The lineage database is not ready; run Data sync first"));
      return Promise.resolve();
    }
    if (!query && !workspace && !type) {
      toast(t("Enter a keyword or filter first"));
      return Promise.resolve();
    }
    return api().get(
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

  function lineageSearch() {
    if (!apiReady()) return Promise.resolve();
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

  function lineageOpen(nodeId) {
    if (!nodeId || !apiReady()) return Promise.resolve();
    return api().get(
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
      $$("#lineageResults .result-item").forEach(function (item) {
        item.setAttribute("aria-pressed", String(item.dataset.id === state.rootId));
      });
      return data;
    }).catch(reportError);
  }

  function applyLineageZoom() {
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

  function setLineageZoom(value) {
    state.lineageZoom = Math.max(0.6, Math.min(2.5, value));
    applyLineageZoom();
  }

  function lineageRenderGraph() {
    var graph = state.lineageGraph;
    var svg = $("#lineageSvg");
    if (!graph || !(graph.nodes || []).length) {
      $("#lineageLayer").innerHTML = "";
      state.lineageBaseWidth = 780;
      state.lineageBaseHeight = 280;
      state.lineagePanX = 0;
      state.lineagePanY = 0;
      applyLineageZoom();
      return;
    }
    var nodes = graph.nodes;
    var columns = nodes.map(function (node) { return Number(node.column || 0); });
    var rows = nodes.map(function (node) { return Number(node.row || 0); });
    var minCol = Math.min.apply(null, columns);
    var maxCol = Math.max.apply(null, columns);
    var minRow = Math.min.apply(null, rows);
    var maxRow = Math.max.apply(null, rows);
    var nodeW = 176;
    var nodeH = 64;
    var colGap = 44;
    var rowGap = 20;
    var positions = {};
    nodes.forEach(function (node) {
      positions[node.id] = {
        x: 40 + (Number(node.column || 0) - minCol) * (nodeW + colGap),
        y: 34 + (Number(node.row || 0) - minRow) * (nodeH + rowGap)
      };
    });
    var width = Math.max(780, 80 + (maxCol - minCol) * (nodeW + colGap) + nodeW);
    var height = Math.max(280, 68 + (maxRow - minRow) * (nodeH + rowGap) + nodeH);
    state.lineageBaseWidth = width;
    state.lineageBaseHeight = height;
    var edges = "";
    (graph.edges || []).forEach(function (edge, index) {
      var from = positions[edge.source];
      var to = positions[edge.target];
      if (!from || !to) return;
      var forward = to.x > from.x;
      var x1 = from.x + (forward ? nodeW : 0);
      var x2 = to.x + (forward ? 0 : nodeW);
      var y1 = from.y + nodeH / 2;
      var y2 = to.y + nodeH / 2;
      var mid = (x1 + x2) / 2;
      edges += '<path class="edge" data-edge="' + index +
        '" d="M' + x1 + " " + y1 + " C" + mid + " " + y1 + ", " + mid + " " +
        y2 + ", " + x2 + " " + y2 +
        '" fill="none" marker-end="url(#arrow)"><title>' +
        escapeHtml(edge.type || "") + "</title></path>";
    });
    var markup = "";
    nodes.forEach(function (node) {
      var pos = positions[node.id];
      var name = String(node.name || node.id);
      var type = String(node.type || "");
      var workspace = String(node.workspace || "");
      var hue = nodeHue(type);
      markup += '<g class="node lineage-node" data-hue="' + hue +
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

  function lineageRenderDetail(node) {
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
        toast(t("Lineage root updated"));
      });
    }
    $$("#lineageDetail [data-lineage-node]").forEach(function (button) {
      button.addEventListener("click", function () {
        lineageSelectNode(button.getAttribute("data-lineage-node"));
      });
    });
  }

  function lineageSelectNode(nodeId) {
    if (!state.lineageNodesLive[nodeId]) return;
    state.selectedId = nodeId;
    lineageApplySelection();
    lineageRenderDetail(state.lineageNodesLive[nodeId].payload || {});
  }

  function lineageSetDirection(direction) {
    var value = direction === "downstream" ? "downstream" : "upstream";
    if (value === state.direction) return;
    state.direction = value;
    $("#dirUpstream").setAttribute("aria-pressed", String(value === "upstream"));
    $("#dirDownstream").setAttribute("aria-pressed", String(value === "downstream"));
    if (state.rootId) lineageOpen(state.rootId);
  }

  function lineageSetDepth(delta) {
    var value = Math.max(1, Math.min(15, state.depth + delta));
    if (value === state.depth) return;
    state.depth = value;
    $("#depthVal").textContent = state.depth + t(" levels");
    $("#depthMinus").disabled = state.depth <= 1;
    $("#depthPlus").disabled = state.depth >= 15;
    if (state.rootId) lineageOpen(state.rootId);
  }

  function lineageExport() {
    if (!state.rootId) {
      toast(t("Choose a lineage node first"));
      return;
    }
    api().post("/api/lineage/export", {
      node_id: state.rootId,
      direction: state.direction,
      depth: state.depth
    }).then(function (data) {
      toast("CSV: " + data.path);
      api().post("/api/files/open", { path: data.path, mode: "open" })
        .catch(function () {});
    }).catch(reportError);
  }

  function init() {
    initComboEvents();
    enhanceAllSelects();
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
      analysisRender();
      analysisScheduleRun();
    });
    $("#includeReports").addEventListener("change", function () {
      analysisSyncReportOptions();
      analysisSavePrefs();
      if (getSelectValue("modelSelect")) analysisScheduleRun();
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
      if (event.target === event.currentTarget) $("#analysisLineageDialog").close();
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
      state.analysisLineageView = value;
      analysisLineageApplyView();
      analysisLineageApplySearch();
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
    $("#analysisLineageNodes").addEventListener("click", function (event) {
      var node = event.target.closest(".lineage-node");
      if (!node) return;
      analysisLineageSelect(node.getAttribute("data-node-id"));
    });
    $("#analysisLineageNodes").addEventListener("dblclick", function (event) {
      var node = event.target.closest(".lineage-node");
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
      if (event.target.closest(".lineage-node")) return;
      var wrap = event.currentTarget;
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
      var drag = state.analysisLineageDrag;
      if (!drag) return;
      state.analysisLineageDrag = null;
      var wrap = event.currentTarget;
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
            "<h1 style=\"font-size:1.1rem;margin:0 0 .5rem\">Server dihentikan</h1>" +
            '<p style="color:#b9c2d0;line-height:1.6;margin:0">Jalankan BI Tools lagi untuk membuka antarmuka web.</p>' +
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

  init();

  bootstrap();
})();
