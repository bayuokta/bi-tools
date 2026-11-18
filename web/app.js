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

  var state = {
    view: "ekstraksi",
    theme: store.get("pbi-theme", "dark") === "light" ? "light" : "dark",
    motion: store.get("pbi-motion", "on") !== "off",
    source: "service",
    running: false,
    tsdRunning: false,
    extractReady: false,
    tsdReady: false,
    logs: [],
    analyzed: false,
    analyzeTab: "all",
    openGroups: {},
    relView: "graph",
    relSelected: "tbl:Fact Sales",
    partitionTable: "Fact Sales",
    partitionSelected: {},
    partitionDetail: null,
    partitionFilter: "all",
    partitionBusy: false,
    partitionDialogTrigger: null,
    typeFilter: "all",
    unusedOnly: false,
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
    instances: [],
    workspaces: [],
    reports: [],
    datasets: [],
    pbix: null,
    endpoint: "",
    extractTimer: null,
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
        toast("Tema tidak bisa disimpan ke server");
      });
    }
    $$(".theme-card").forEach(function (card) {
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
      toast(state.motion ? "Animasi antarmuka aktif" : "Animasi antarmuka dimatikan");
    }
  }

  function showView(name) {
    state.view = name;
    $$(".view").forEach(function (section) {
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
    if (name === "lineage") {
      renderLineage();
      renderResults();
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
    $("#consolePreview").textContent = count ? state.logs[count - 1].text : "Belum ada aktivitas pada sesi ini.";
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
    }
  }

  function runTsd() {
    if (state.tsdRunning) return;
    state.tsdRunning = true;
    $("#runTsd").disabled = true;
    $("#tsdRun").hidden = false;
    $("#tsdBar").style.width = "0%";
    $("#tsdRunPct").textContent = "0%";
    $("#tsdRunLabel").textContent = "Membaca workbook…";
    $("#metaTsd").textContent = "Sedang dibuat…";
    setConsole(true);
    addLog("=== Generate TSD ===", "info");
    addLog("Template: templates/tsd.template.html", "info");

    var steps = [
      { pct: 30, label: "Menggabungkan metadata…", log: "Metadata report dan model digabungkan." },
      { pct: 62, label: "Merender bagian dokumen…", log: "6 bagian · 4 halaman report · 12 tabel." },
      { pct: 88, label: "Menandai field kosong…", log: "7 field kosong ditandai TODO (mode draft)." },
      { pct: 100, label: "Selesai", log: "TSD_Report.html ditulis ke folder output." }
    ];

    var index = 0;
    var timer = window.setInterval(function () {
      if (index >= steps.length) {
        window.clearInterval(timer);
        finishTsd();
        return;
      }
      var step = steps[index];
      index += 1;
      $("#tsdBar").style.width = step.pct + "%";
      $("#tsdRunPct").textContent = step.pct + "%";
      $("#tsdRunLabel").textContent = step.label;
      addLog(step.log, "info");
    }, 600);
  }

  function finishTsd() {
    state.tsdRunning = false;
    state.tsdReady = true;
    var time = new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
    $("#runTsd").disabled = false;
    $("#tsdRun").hidden = true;
    $("#tsdPreviewEmpty").hidden = true;
    $("#tsdPreview").hidden = false;
    $("#metaTsd").textContent = "Siap · " + time + " · 412 KB";
    $("#openTsd").disabled = false;
    addLog("TSD_Report.html siap dibuka.", "ok");
    toast("Dokumen TSD selesai");
  }

  var modelTables = [
    {
      name: "Fact Sales", storage: "Import", rows: 1248930,
      columns: [
        { n: "Sales Order No", t: "Text", mb: 18.4, u: 4, h: true },
        { n: "Sales Order Line", t: "Integer", mb: 6.2, u: 1 },
        { n: "Order Date Key", t: "Integer", mb: 5.8, u: 1 },
        { n: "Ship Date Key", t: "Integer", mb: 5.8, u: 1 },
        { n: "Customer Key", t: "Integer", mb: 6.1, u: 1, h: true },
        { n: "Product Key", t: "Integer", mb: 6.1, u: 1 },
        { n: "Geography Key", t: "Integer", mb: 5.2, u: 1 },
        { n: "Sales Amount", t: "Decimal", mb: 12.6, u: 12 },
        { n: "Cost Amount", t: "Decimal", mb: 12.4, u: 6 },
        { n: "Quantity", t: "Integer", mb: 7.3, u: 7 },
        { n: "Discount Amount", t: "Decimal", mb: 11.2, u: 2 },
        { n: "Ship City", t: "Text", mb: 92.8, u: 0 }
      ],
      measures: [
        { n: "Total Revenue", dax: "SUM ( 'Fact Sales'[Sales Amount] )", u: 12, f: "#,0" },
        { n: "Total Cost", dax: "SUM ( 'Fact Sales'[Cost Amount] )", u: 8, f: "#,0" },
        { n: "Gross Margin", dax: "[Total Revenue] - [Total Cost]", u: 5, f: "#,0", v: 1 },
        { n: "Gross Margin %", dax: "DIVIDE ( [Gross Margin], [Total Revenue] )", u: 0, f: "0.0%" },
        { n: "Total Quantity", dax: "SUM ( 'Fact Sales'[Quantity] )", u: 6, f: "#,0" },
        { n: "Avg Order Value", dax: "DIVIDE ( [Total Revenue], DISTINCTCOUNT ( 'Fact Sales'[Sales Order No] ) )", u: 4, f: "#,0" },
        { n: "Discount %", dax: "DIVIDE ( SUM ( 'Fact Sales'[Discount Amount] ), [Total Revenue] )", u: 2, f: "0.0%" },
        { n: "Return Rate", dax: "DIVIDE ( [Total Returns], [Total Quantity] )", u: 1, f: "0.0%", v: 1 }
      ]
    },
    {
      name: "Fact Budget", storage: "Import", rows: 96400,
      columns: [
        { n: "Budget Month Key", t: "Integer", mb: 4.2, u: 1 },
        { n: "Cost Center Key", t: "Integer", mb: 3.8, u: 1 },
        { n: "Account Key", t: "Integer", mb: 3.9, u: 1 },
        { n: "Budget Amount", t: "Decimal", mb: 14.2, u: 6 },
        { n: "Forecast Amount", t: "Decimal", mb: 13.6, u: 3 },
        { n: "Budget Comment", t: "Text", mb: 55.8, u: 0 },
        { n: "Version", t: "Text", mb: 0.7, u: 1 }
      ],
      measures: [
        { n: "Total Budget", dax: "SUM ( 'Fact Budget'[Budget Amount] )", u: 5, f: "#,0" },
        { n: "Total Forecast", dax: "SUM ( 'Fact Budget'[Forecast Amount] )", u: 3, f: "#,0" },
        { n: "Budget Variance", dax: "[Total Revenue] - [Total Budget]", u: 4, f: "#,0" },
        { n: "Budget Variance %", dax: "DIVIDE ( [Budget Variance], [Total Budget] )", u: 2, f: "0.0%" }
      ]
    },
    {
      name: "Stock Level", storage: "Import", rows: 412870,
      columns: [
        { n: "Product Key", t: "Integer", mb: 6.4, u: 1 },
        { n: "Warehouse Key", t: "Integer", mb: 4.1, u: 1 },
        { n: "Snapshot Date Key", t: "Integer", mb: 5.3, u: 1 },
        { n: "Quantity Stock", t: "Integer", mb: 9.8, u: 5 },
        { n: "Stock Value", t: "Decimal", mb: 11.4, u: 4 },
        { n: "Reorder Point", t: "Integer", mb: 7.9, u: 1 },
        { n: "Legacy Stock Code", t: "Text", mb: 42.2, u: 0 },
        { n: "Period Date Key", t: "Integer", mb: 1.2, u: 0 }
      ],
      measures: [
        { n: "Stock Quantity", dax: "SUM ( 'Stock Level'[Quantity Stock] )", u: 7, f: "#,0" },
        { n: "Stock Value", dax: "SUM ( 'Stock Level'[Stock Value] )", u: 5, f: "#,0" },
        { n: "Stock Turnover", dax: "DIVIDE ( [Total Cost], [Stock Value] )", u: 2, f: "0.0" },
        { n: "Days of Supply", dax: "DIVIDE ( [Stock Quantity], DIVIDE ( [Total Quantity], 365 ) )", u: 1, f: "#,0" }
      ]
    },
    {
      name: "Fact Returns", storage: "Import", rows: 38240,
      columns: [
        { n: "Return Order No", t: "Text", mb: 12.8, u: 1 },
        { n: "Return Date Key", t: "Integer", mb: 5.1, u: 1 },
        { n: "Product Key", t: "Integer", mb: 4.6, u: 1 },
        { n: "Customer Key", t: "Integer", mb: 4.4, u: 1 },
        { n: "Return Qty", t: "Integer", mb: 6.9, u: 3 },
        { n: "Return Reason Detail", t: "Text", mb: 21.0, u: 0 }
      ],
      measures: [
        { n: "Total Returns", dax: "SUM ( 'Fact Returns'[Return Qty] )", u: 4, f: "#,0" },
        { n: "Return Qty %", dax: "DIVIDE ( [Total Returns], [Total Quantity] )", u: 0, f: "0.0%" }
      ]
    },
    {
      name: "Dim Customer", storage: "Import", rows: 12840,
      columns: [
        { n: "Customer Key", t: "Integer", mb: 1.6, u: 1 },
        { n: "Customer Code", t: "Text", mb: 2.4, u: 1 },
        { n: "Customer Name", t: "Text", mb: 4.8, u: 7 },
        { n: "Segment", t: "Text", mb: 1.9, u: 3 },
        { n: "Channel", t: "Text", mb: 1.8, u: 2 },
        { n: "City", t: "Text", mb: 2.9, u: 2 },
        { n: "Email", t: "Text", mb: 3.6, u: 0 },
        { n: "Loyalty Tier", t: "Text", mb: 1.4, u: 0 },
        { n: "Created At", t: "DateTime", mb: 1.2, u: 0 }
      ],
      measures: [
        { n: "Active Customers", dax: "DISTINCTCOUNT ( 'Fact Sales'[Customer Key] )", u: 6, f: "#,0" },
        { n: "Customers (PY)", dax: "CALCULATE ( [Active Customers], SAMEPERIODLASTYEAR ( 'Dim Date'[Date] ) )", u: 2, f: "#,0" }
      ]
    },
    {
      name: "Dim Product", storage: "Import", rows: 3120,
      columns: [
        { n: "Product Key", t: "Integer", mb: 1.8, u: 1 },
        { n: "SKU", t: "Text", mb: 2.6, u: 2 },
        { n: "Product Name", t: "Text", mb: 3.7, u: 6 },
        { n: "Category", t: "Text", mb: 1.6, u: 4 },
        { n: "Subcategory", t: "Text", mb: 1.9, u: 3 },
        { n: "Brand", t: "Text", mb: 1.4, u: 2 },
        { n: "Color", t: "Text", mb: 2.2, u: 0 },
        { n: "Size", t: "Text", mb: 1.3, u: 1 },
        { n: "Launch Date", t: "Date", mb: 1.2, u: 0 },
        { n: "Weight Kg", t: "Decimal", mb: 1.2, u: 0 }
      ],
      measures: [
        { n: "Products Sold", dax: "DISTINCTCOUNT ( 'Fact Sales'[Product Key] )", u: 5, f: "#,0" },
        { n: "Distinct Products", dax: "DISTINCTCOUNT ( 'Dim Product'[Product Key] )", u: 3, f: "#,0" },
        { n: "New Products", dax: "CALCULATE ( [Products Sold], 'Dim Product'[Launch Date] >= [Selected Period] )", u: 0, f: "#,0" }
      ]
    },
    {
      name: "Dim Geography", storage: "Import", rows: 18400,
      columns: [
        { n: "Geography Key", t: "Integer", mb: 0.9, u: 1 },
        { n: "Country", t: "Text", mb: 1.0, u: 3 },
        { n: "Region", t: "Text", mb: 0.8, u: 2 },
        { n: "City", t: "Text", mb: 0.6, u: 2 },
        { n: "Postal Code", t: "Text", mb: 0.5, u: 0 },
        { n: "Latitude", t: "Decimal", mb: 0.25, u: 0 },
        { n: "Longitude", t: "Decimal", mb: 0.25, u: 0 }
      ],
      measures: [
        { n: "Countries Covered", dax: "DISTINCTCOUNT ( 'Dim Geography'[Country] )", u: 0, f: "#,0" }
      ]
    },
    {
      name: "Dim Date", storage: "Import", rows: 2192,
      columns: [
        { n: "Date", t: "Date", mb: 0.5, u: 9 },
        { n: "Date Key", t: "Integer", mb: 0.4, u: 1 },
        { n: "Year", t: "Integer", mb: 0.1, u: 2 },
        { n: "Quarter", t: "Text", mb: 0.1, u: 2 },
        { n: "Month", t: "Text", mb: 0.2, u: 3 },
        { n: "Month Year", t: "Text", mb: 0.2, u: 4 },
        { n: "Week", t: "Integer", mb: 0.1, u: 0 },
        { n: "Is Weekend", t: "Boolean", mb: 0.1, u: 0 },
        { n: "Fiscal Period", t: "Text", mb: 0.4, u: 0 }
      ],
      measures: [
        { n: "Revenue YTD", dax: "TOTALYTD ( [Total Revenue], 'Dim Date'[Date] )", u: 4, f: "#,0" },
        { n: "Revenue PY", dax: "CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( 'Dim Date'[Date] ) )", u: 3, f: "#,0" },
        { n: "Revenue MTD", dax: "TOTALMTD ( [Total Revenue], 'Dim Date'[Date] )", u: 2, f: "#,0" },
        { n: "Revenue QoQ", dax: "[Total Revenue] - CALCULATE ( [Total Revenue], PREVIOUSQUARTER ( 'Dim Date'[Date] ) )", u: 1, f: "#,0" },
        { n: "Sales Y-1", dax: "CALCULATE ( [Total Quantity], SAMEPERIODLASTYEAR ( 'Dim Date'[Date] ) )", u: 1, f: "#,0" },
        { n: "Budget Y-1", dax: "CALCULATE ( [Total Budget], SAMEPERIODLASTYEAR ( 'Dim Date'[Date] ) )", u: 1, f: "#,0" },
        { n: "Stock Value Y-1", dax: "CALCULATE ( [Stock Value], SAMEPERIODLASTYEAR ( 'Dim Date'[Date] ) )", u: 1, f: "#,0" },
        { n: "Month Label", dax: "FORMAT ( SELECTEDVALUE ( 'Dim Date'[Date] ), \"MMM YYYY\" )", u: 2 },
        { n: "Max Period", dax: "CALCULATE ( MAX ( 'Dim Date'[Date] ), ALLSELECTED ( 'Dim Date' ) )", u: 3 }
      ]
    },
    {
      name: "_Measures", storage: "Import", rows: 0,
      columns: [],
      measures: [
        { n: "Row Count Sales", dax: "COUNTROWS ( 'Fact Sales' )", u: 2, f: "#,0" },
        { n: "Row Count Budget", dax: "COUNTROWS ( 'Fact Budget' )", u: 1, f: "#,0" },
        { n: "Row Count Returns", dax: "COUNTROWS ( 'Fact Returns' )", u: 1, f: "#,0" },
        { n: "Avg Unit Price", dax: "DIVIDE ( [Total Revenue], [Total Quantity] )", u: 1, f: "#,0" },
        { n: "Margin per Customer", dax: "DIVIDE ( [Gross Margin], [Active Customers] )", u: 2, f: "#,0" },
        { n: "Top Customer Revenue", dax: "MAXX ( TOPN ( 1, 'Dim Customer', [Total Revenue] ), [Total Revenue] )", u: 1, f: "#,0", v: 1 },
        { n: "Share of Total", dax: "DIVIDE ( [Total Revenue], CALCULATE ( [Total Revenue], ALLSELECTED ( 'Dim Product' ) ) )", u: 3, f: "0.0%" },
        { n: "Selected Period", dax: "SELECTEDVALUE ( 'Dim Date'[Month Year] )", u: 4 },
        { n: "KPI Card", dax: "IF ( [Budget Variance] < 0, \"Di bawah target\", \"Sesuai target\" )", u: 2 },
        { n: "RLS Enabled", dax: "IF ( [Row Count Sales] > 0, 1, 0 )", u: 1 },
        { n: "Page Count", dax: "COUNTROWS ( 'Pages' )", u: 1, f: "#,0" },
        { n: "Visual Count", dax: "SUM ( 'Pages'[Visual Count] )", u: 1, f: "#,0" },
        { n: "Refresh Duration", dax: "DATEDIFF ( [Refresh Start], [Refresh End], SECOND )", u: 0, f: "#,0" },
        { n: "Unused Placeholder", dax: "BLANK ()", u: 0 }
      ]
    },
    {
      name: "Report Config", storage: "Import", rows: 12,
      columns: [
        { n: "Config Key", t: "Text", mb: 0.3, u: 1 },
        { n: "Config Value", t: "Text", mb: 0.6, u: 1 },
        { n: "Updated At", t: "DateTime", mb: 0.3, u: 0 },
        { n: "Owner", t: "Text", mb: 0.2, u: 0 }
      ],
      measures: []
    }
  ];

  var relationshipRows = [
    { name: "Fact Sales[Order Date Key] → Dim Date[Date Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Sales[Order Date Key]", to: "Dim Date[Date Key]" },
    { name: "Fact Sales[Ship Date Key] → Dim Date[Date Key]", type: "Tidak aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 0, from: "Fact Sales[Ship Date Key]", to: "Dim Date[Date Key]" },
    { name: "Fact Sales[Customer Key] → Dim Customer[Customer Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Sales[Customer Key]", to: "Dim Customer[Customer Key]" },
    { name: "Fact Sales[Product Key] → Dim Product[Product Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Sales[Product Key]", to: "Dim Product[Product Key]" },
    { name: "Fact Sales[Geography Key] → Dim Geography[Geography Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Sales[Geography Key]", to: "Dim Geography[Geography Key]" },
    { name: "Fact Sales[Sales Order No] → Fact Returns[Return Order No]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Sales[Sales Order No]", to: "Fact Returns[Return Order No]" },
    { name: "Fact Returns[Return Date Key] → Dim Date[Date Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Returns[Return Date Key]", to: "Dim Date[Date Key]" },
    { name: "Fact Returns[Product Key] → Dim Product[Product Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Returns[Product Key]", to: "Dim Product[Product Key]" },
    { name: "Fact Returns[Customer Key] → Dim Customer[Customer Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Returns[Customer Key]", to: "Dim Customer[Customer Key]" },
    { name: "Fact Budget[Budget Month Key] → Dim Date[Date Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Fact Budget[Budget Month Key]", to: "Dim Date[Date Key]" },
    { name: "Fact Budget[Version] → Report Config[Config Key]", type: "Aktif", cross: "Single", card: "1-1", auto: "Tidak", uses: 1, from: "Fact Budget[Version]", to: "Report Config[Config Key]" },
    { name: "Stock Level[Product Key] → Dim Product[Product Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Stock Level[Product Key]", to: "Dim Product[Product Key]" },
    { name: "Stock Level[Snapshot Date Key] → Dim Date[Date Key]", type: "Aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 1, from: "Stock Level[Snapshot Date Key]", to: "Dim Date[Date Key]" },
    { name: "Stock Level[Period Date Key] → Dim Date[Date Key]", type: "Tidak aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 0, from: "Stock Level[Period Date Key]", to: "Dim Date[Date Key]" },
    { name: "Dim Customer[City] → Dim Geography[City]", type: "Aktif", cross: "Both", card: "N-1", auto: "Ya", uses: 1, from: "Dim Customer[City]", to: "Dim Geography[City]" },
    { name: "Dim Date[Fiscal Period] → Report Config[Config Key]", type: "Tidak aktif", cross: "Single", card: "N-1", auto: "Tidak", uses: 0, from: "Dim Date[Fiscal Period]", to: "Report Config[Config Key]" }
  ];

  var reportModel = {
    name: "Sales Performance", theme: "Corporate", score: 96,
    pages: [
      { n: "Ringkasan", vis: 12, broken: 0, filters: 2, views: "12.480", used: true },
      { n: "Tren", vis: 8, broken: 1, filters: 1, views: "4.210", used: true },
      { n: "Detail Produk", vis: 16, broken: 0, filters: 2, views: "—", used: false },
      { n: "Analisa Pelanggan", vis: 12, broken: 0, filters: 1, views: "1.842", used: true }
    ],
    hiddenPages: [
      { n: "Catatan internal", vis: 3, broken: 0, filters: 0 },
      { n: "Arsip 2024", vis: 5, broken: 0, filters: 1 }
    ],
    filters: ["Channel", "Tahun fiskal", "Region"]
  };

  var mQueries = [
    { n: "Fact Sales", type: "Tabel", warn: 2, code: "let\n    Source = Sql.Database ( \"sql-dw-finance\", \"SalesDW\" ),\n    FactSales = Source{[Schema=\"dbo\",Item=\"FactSales\"]}[Data],\n    Removed = Table.SelectColumns ( FactSales, { \"SalesOrderNo\", \"OrderDateKey\", \"SalesAmount\", \"Quantity\" } )\nin\n    Removed" },
    { n: "Fact Budget", type: "Tabel", warn: 0, code: "let\n    Source = Excel.Workbook ( File.Contents ( \"\\\\finance\\budget\\Budget_2026.xlsx\" ), null, true ),\n    Budget = Source{[Item=\"Budget\",Kind=\"Table\"]}[Data],\n    Changed = Table.TransformColumnTypes ( Budget, { { \"Budget Amount\", type number } } )\nin\n    Changed" },
    { n: "Stock Level", type: "Tabel", warn: 1, code: "let\n    Source = Sql.Database ( \"sql-dw-finance\", \"InventoryDW\" ),\n    Stock = Source{[Schema=\"dbo\",Item=\"StockSnapshot\"]}[Data],\n    Removed = Table.RemoveColumns ( Stock, { \"LegacyStockCode\" } )\nin\n    Removed" },
    { n: "Fact Returns", type: "Tabel", warn: 0, code: "let\n    Source = Sql.Database ( \"sql-dw-finance\", \"SalesDW\" ),\n    Returns = Source{[Schema=\"dbo\",Item=\"ReturnLines\"]}[Data],\n    Filtered = Table.SelectRows ( Returns, each [ReturnQty] > 0 )\nin\n    Filtered" },
    { n: "Dim Customer", type: "Tabel", warn: 0, code: "let\n    Source = Sql.Database ( \"sql-crm-apac\", \"CRM\" ),\n    Customer = Source{[Schema=\"dbo\",Item=\"Customer\"]}[Data],\n    Renamed = Table.RenameColumns ( Customer, { { \"CustName\", \"Customer Name\" } } )\nin\n    Renamed" },
    { n: "Dim Product", type: "Tabel", warn: 0, code: "let\n    Source = Sql.Database ( \"sql-dw-finance\", \"ProductDW\" ),\n    Product = Source{[Schema=\"dbo\",Item=\"Product\"]}[Data],\n    Typed = Table.TransformColumnTypes ( Product, { { \"WeightKg\", type number } } )\nin\n    Typed" },
    { n: "Dim Geography", type: "Tabel", warn: 0, code: "let\n    Source = Sql.Database ( \"sql-dw-finance\", \"SalesDW\" ),\n    Geography = Source{[Schema=\"dbo\",Item=\"Geography\"]}[Data]\nin\n    Geography" },
    { n: "Dim Date", type: "Tabel", warn: 0, code: "let\n    Source = List.Dates ( #date ( 2020, 1, 1 ), 2192, #duration ( 1, 0, 0, 0 ) ),\n    ToTable = Table.FromList ( Source, Splitter.SplitByNothing ( ), { \"Date\" } )\nin\n    ToTable" },
    { n: "RLS Main Dealer", type: "Tabel", warn: 0, code: "let\n    Source = PowerPlatform.Dataflows ( null ),\n    Workspaces = Source{[Id=\"Workspaces\"]}[Data],\n    RLS = Workspaces{[workspaceId=\"d562196e-c989-4308-8360-bc19f43cf379\"]}[Data],\n    Removed = Table.SelectColumns ( RLS, { \"MainDealerCode\", \"Email\" } ),\n    Renamed = Table.RenameColumns ( Removed, { { \"MainDealerCode\", \"Main Dealer Code\" } } )\nin\n    Renamed" },
    { n: "Report Config", type: "Tabel", warn: 0, code: "let\n    Source = Json.Document ( Web.Contents ( \"https://config.internal/sales/theme.json\" ) ),\n    ToTable = Record.ToTable ( Source )\nin\n    ToTable" },
    { n: "RangeStart", type: "M parameter", warn: 0, code: "#datetime ( 2025, 1, 1, 0, 0, 0 ) meta [\n    IsParameterQuery = true,\n    Type = \"DateTime\"\n]" },
    { n: "RangeEnd", type: "M parameter", warn: 0, code: "#datetime ( 2026, 12, 31, 0, 0, 0 ) meta [\n    IsParameterQuery = true,\n    Type = \"DateTime\"\n]" }
  ];

  function tableSizeMb(table) {
    return table.columns.reduce(function (sum, column) { return sum + column.mb; }, 0);
  }

  function fmtDecimal(value, digits) {
    return Number(value).toLocaleString("id-ID", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function fmtInt(value) {
    return Number(value).toLocaleString("id-ID");
  }

  function fmtSize(mb) {
    if (!mb) return "0 B";
    if (mb < 1) return fmtDecimal(mb * 1024, 0) + " KB";
    return fmtDecimal(mb, 1) + " MB";
  }

  function statusOf(item) {
    if (item.u > 0) return item.h ? "Tersembunyi" : "Dipakai";
    return "Tidak dipakai";
  }

  function analysisTotals() {
    var totals = {
      columns: 0, measures: 0, hidden: 0, size: 0, unusedColumns: 0,
      unusedMeasures: 0, unusedColumnSize: 0, helperMeasures: 0, visuals: 0,
      pageCount: reportModel.pages.length, relationshipCount: relationshipRows.length
    };
    modelTables.forEach(function (table) {
      table.columns.forEach(function (column) {
        totals.columns += 1;
        totals.size += column.mb;
        if (column.h) totals.hidden += 1;
        if (column.u === 0) { totals.unusedColumns += 1; totals.unusedColumnSize += column.mb; }
      });
      table.measures.forEach(function (measure) {
        totals.measures += 1;
        if (measure.u === 0) totals.unusedMeasures += 1;
        if (table.name === "_Measures") totals.helperMeasures += 1;
      });
    });
    reportModel.pages.forEach(function (page) { totals.visuals += page.vis; });
    return totals;
  }

  var ANALYSIS_HEADERS = {
    all: ["Nama", "Tipe", "Tabel / halaman", "Sumber", "Tipe data", "Ukuran", "Status", "# dipakai", "Format string", "Has error", "Display folder"],
    tables: ["Nama", "Tipe", "Tabel", "Sumber", "Tipe data", "Ukuran", "Status", "# dipakai", "Mode", "Format"],
    relationships: ["Nama relasi", "Tipe", "Cross filter", "Kardinalitas", "Status", "Auto create", "Dipakai", "Dari kolom", "Ke kolom"],
    report: ["Nama", "Tipe", "Sumber", "Visual", "Visual rusak", "Views", "Halaman", "Tema", "Skor praktik", "Status"],
    dax: ["Nama / ekspresi", "Tabel", "Tipe", "Error", "Pelanggaran", "Dipakai", "Sumber", "Tipe sumber"],
    m: ["Nama", "Tipe", "Sumber", "Peringatan"]
  };

  var ANALYSIS_TABS = {
    all: {
      placeholder: "Nama kolom, measure, atau tabel",
      filters: [["all", "Semua tipe"], ["Kolom", "Kolom"], ["Measure", "Measure"], ["Halaman", "Halaman"]],
      unused: true, expandable: true
    },
    tables: {
      placeholder: "Nama tabel, kolom, atau measure",
      filters: [["all", "Semua tipe"], ["Kolom", "Kolom"], ["Measure", "Measure"]],
      unused: true, expandable: true
    },
    relationships: {
      placeholder: "Nama relasi atau kolom",
      filters: [["all", "Semua status"], ["Aktif", "Aktif"], ["Tidak aktif", "Tidak aktif"]],
      unused: false, expandable: false
    },
    report: {
      placeholder: "Nama halaman, filter, atau visual",
      filters: [["all", "Semua status"], ["Dipakai", "Dipakai"], ["Tidak dipakai", "Tidak dipakai"]],
      unused: false, expandable: true
    },
    dax: {
      placeholder: "Nama measure atau isi ekspresi",
      filters: [["all", "Semua measure"], ["Dipakai", "Dipakai"], ["Tidak dipakai", "Tidak dipakai"]],
      unused: false, expandable: true
    },
    m: {
      placeholder: "Nama kueri atau isi M",
      filters: [["all", "Semua kueri"], ["Tabel", "Tabel"], ["M parameter", "M parameter"]],
      unused: false, expandable: true
    }
  };

  var CHEVRON = '<svg class="od-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';

  var ROW_ICONS = {
    table: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="1.6"/><path d="M3 9h18M9 9v11"/></svg>',
    group: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10"/></svg>',
    column: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1.6"/><path d="M9 4v16M15 4v16"/></svg>',
    measure: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 19L18 5"/><path d="M6 5h3M15 19h3"/></svg>',
    page: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></svg>',
    link: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13.5a4 4 0 0 1 0-5.7l2.4-2.4a4 4 0 0 1 5.7 5.7l-1.6 1.6"/><path d="M14 10.5a4 4 0 0 1 0 5.7l-2.4 2.4a4 4 0 0 1-5.7-5.7l1.6-1.6"/></svg>',
    code: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 7l-5 5 5 5"/><path d="M15 7l5 5-5 5"/></svg>',
    query: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>',
    filter: '<svg class="row-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6h16l-6.4 7.4V19l-3.2-1.8v-3.8z"/></svg>'
  };

  function currentQuery() {
    return ($("#searchAnalyze").value || "").trim().toLowerCase();
  }

  function statusChip(status) {
    var cls = status === "Dipakai" ? "chip-ok" : (status === "Tersembunyi" ? "chip-warn" : "chip-danger");
    return '<span class="chip ' + cls + '"><span class="dot"></span>' + escapeHtml(status) + "</span>";
  }

  function nameCell(text, icon, options) {
    options = options || {};
    var html = '<div class="name-cell">';
    if (options.group) {
      html += '<button type="button" class="row-toggle" data-group="' + escapeHtml(options.group) + '" aria-expanded="' +
        (options.open ? "true" : "false") + '" aria-label="' + (options.open ? "Ciutkan " : "Bentangkan ") +
        escapeHtml(text) + '">' + CHEVRON + "</button>";
    } else if (options.level) {
      html += '<span class="row-toggle" aria-hidden="true"></span>';
    }
    if (icon && ROW_ICONS[icon]) html += ROW_ICONS[icon];
    html += '<span class="name-text" title="' + escapeHtml(text) + '">' + escapeHtml(text) + "</span></div>";
    return html;
  }

  function headersMarkup(tab) {
    var numeric = { all: [5, 7], tables: [5, 7], relationships: [6], report: [3, 4, 6, 8], dax: [4, 5], m: [] }[tab] || [];
    return "<tr>" + ANALYSIS_HEADERS[tab].map(function (label, index) {
      return "<th scope=\"col\"" + (numeric.indexOf(index) !== -1 ? ' class="num"' : "") + ">" + label + "</th>";
    }).join("") + "</tr>";
  }

  function rowMarkup(row, open) {
    var cells = row.cells;
    if (row.group) {
      cells = [nameCell(row.name, row.icon, { group: row.id, open: open, level: row.level })].concat(row.rest);
    }
    var numeric = row.numCols || [];
    var html = cells.map(function (cell, index) {
      var classes = [];
      if (index === 0) classes.push("cell-name");
      if (numeric.indexOf(index) !== -1) classes.push("num");
      var style = index === 0 ? ' style="--depth:' + (row.level || 0) + '"' : "";
      return "<td" + (classes.length ? ' class="' + classes.join(" ") + '"' : "") + style + ">" + cell + "</td>";
    }).join("");
    var rowClasses = [];
    if (row.group) rowClasses.push("group-row");
    if (row.cls) rowClasses.push(row.cls);
    var attrs = rowClasses.length ? ' class="' + rowClasses.join(" ") + '"' : "";
    if (row.group) attrs += ' data-level="' + (row.level || 0) + '"';
    if (row.id) attrs += ' data-id="' + escapeHtml(row.id) + '"';
    if (!row.group && row.id) attrs += ' tabindex="0"';
    return "<tr" + attrs + ">" + html + "</tr>";
  }

  function emitRows(rows, forceOpen) {
    var html = "";
    var stack = [];
    rows.forEach(function (row) {
      var level = row.level || 0;
      if (row.kind === "detail") {
        html += '<tr class="detail-row"><td colspan="' + (row.cols || 4) + '">' + escapeHtml(row.text) + "</td></tr>";
        return;
      }
      var parentOpen = level === 0 ? true : !!stack[level - 1];
      if (!parentOpen) return;
      if (row.kind === "code") {
        html += '<tr class="code-row"><td colspan="' + (row.cols || 4) + '"><pre>' + escapeHtml(row.code) + "</pre></td></tr>";
        return;
      }
      var open = row.group ? (forceOpen || isOpen(row.id)) : false;
      stack[level] = open;
      stack.length = level + 1;
      html += rowMarkup(row, open);
    });
    return html;
  }

  function isOpen(id) {
    return !!(state.openGroups && state.openGroups[id]);
  }

  function initOpenGroups() {
    state.openGroups = {};
    modelTables.forEach(function (table) {
      state.openGroups["tbl:" + table.name] = true;
      state.openGroups["tbl:" + table.name + ":m"] = true;
      state.openGroups["tbl:" + table.name + ":c"] = true;
      state.openGroups["all:table:" + table.name] = true;
      state.openGroups["all:table:" + table.name + ":m"] = true;
      state.openGroups["all:table:" + table.name + ":c"] = true;
    });
    state.openGroups.rep = true;
    state.openGroups["rep:pages"] = true;
    state.openGroups["all:report"] = true;
    state.openGroups["all:report:pages"] = true;
  }

  function groupIdsFor(tab) {
    var ids = [];
    if (tab === "all") {
      modelTables.forEach(function (table) {
        var tableId = "all:table:" + table.name;
        ids.push(tableId, tableId + ":m", tableId + ":c");
        table.columns.forEach(function (column) {
          var itemId = tableId + ":c:" + column.n;
          ids.push(itemId, itemId + ":rel", itemId + ":msr");
        });
      });
      ids.push("all:report", "all:report:pages");
    } else if (tab === "tables") {
      modelTables.forEach(function (table) {
        ids.push("tbl:" + table.name, "tbl:" + table.name + ":m", "tbl:" + table.name + ":c");
      });
    } else if (tab === "report") {
      ids.push("rep", "rep:hidden", "rep:pages", "rep:filters");
      reportModel.pages.forEach(function (page) { ids.push("rep:page:" + page.n); });
      reportModel.hiddenPages.forEach(function (page) { ids.push("rep:page:" + page.n); });
    } else if (tab === "dax") {
      modelTables.forEach(function (table) {
        table.measures.forEach(function (measure) { ids.push("dax:" + table.name + ":" + measure.n); });
      });
    } else if (tab === "m") {
      mQueries.forEach(function (query) { ids.push("m:" + query.n); });
    }
    return ids;
  }

  function updateMetrics() {
    var totals = analysisTotals();
    $("#metricSize").textContent = fmtSize(totals.size);
    $("#metricSizeNote").textContent = modelTables.length + " tabel dalam model";
    $("#metricColumns").textContent = fmtInt(totals.columns);
    $("#metricColumnsNote").textContent = totals.hidden + " kolom tersembunyi";
    $("#metricMeasures").textContent = fmtInt(totals.measures);
    $("#metricMeasuresNote").textContent = totals.helperMeasures + " tersimpan di _Measures";
    $("#metricUnusedColumns").textContent = fmtInt(totals.unusedColumns);
    $("#metricUnusedColumnsNote").textContent = fmtSize(totals.unusedColumnSize) + " · " +
      Math.round(totals.unusedColumnSize / totals.size * 100) + "% dataset";
    $("#metricUnusedMeasures").textContent = fmtInt(totals.unusedMeasures);
    $("#metricUnusedMeasuresNote").textContent = Math.round(totals.unusedMeasures / totals.measures * 100) + "% dari total measure";
    $("#metricReport").textContent = "1 report";
    $("#metricReportNote").textContent = totals.pageCount + " halaman · " + fmtInt(totals.visuals) + " visual";
  }

  function updateTabCounts() {
    var totals = analysisTotals();
    $("#tabCountAll").textContent = fmtInt(totals.columns + totals.measures + totals.pageCount);
    $("#tabCountTables").textContent = fmtInt(modelTables.length);
    $("#tabCountRelationships").textContent = fmtInt(totals.relationshipCount);
    $("#tabCountReport").textContent = fmtInt(totals.pageCount);
    $("#tabCountDax").textContent = fmtInt(totals.measures);
    $("#tabCountM").textContent = fmtInt(mQueries.length);
  }

  function syncRelViewSwitch() {
    $$("#relViewSwitch [data-rel-view]").forEach(function (button) {
      button.setAttribute("aria-pressed", button.getAttribute("data-rel-view") === state.relView ? "true" : "false");
    });
  }

  function applyTabTools(name) {
    var config = ANALYSIS_TABS[name];
    $("#searchAnalyze").placeholder = config.placeholder;
    $("#toolTypeWrap").hidden = config.filters.length < 2;
    $("#toolUnusedWrap").hidden = !config.unused;
    $("#expandRows").hidden = !config.expandable;
    $("#collapseRows").hidden = !config.expandable;
    $("#relViewSwitch").hidden = name !== "relationships";
    if (name === "relationships") syncRelViewSwitch();
    var select = $("#typeAnalyze");
    select.innerHTML = config.filters.map(function (pair) {
      return '<option value="' + escapeHtml(pair[0]) + '">' + escapeHtml(pair[1]) + "</option>";
    }).join("");
    select.value = "all";
  }

  function setAnalysisTab(name) {
    if (!state.analyzed) { toast("Jalankan analisa lebih dulu"); return; }
    if (!ANALYSIS_TABS[name]) return;
    state.analyzeTab = name;
    state.typeFilter = "all";
    $$("#analyzeTabs [role='tab']").forEach(function (tab) {
      var active = tab.dataset.analyzeTab === name;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
    });
    $("#analyzePanel").setAttribute("aria-labelledby", "tab-" + name);
    applyTabTools(name);
    renderAnalysis();
  }

  function errorChip() {
    return '<span class="chip chip-ok"><span class="dot"></span>Tidak</span>';
  }

  function relTypeChip(type) {
    return '<span class="chip ' + (type === "Aktif" ? "chip-ok" : "chip-idle") + '"><span class="dot"></span>' +
      escapeHtml(type) + "</span>";
  }

  function columnFormat(column) {
    return column.t === "Date" || column.t === "DateTime" ? "General Date" : "—";
  }

  function allGroupRest(type, tableName) {
    return [type, tableName, "Model", "—", "—", "—", "—", "—", "—", "—"];
  }

  function relColumnName(reference) {
    var start = reference.indexOf("[");
    return reference.slice(start + 1, reference.lastIndexOf("]"));
  }

  function relationshipsForColumn(tableName, columnName) {
    return relationshipRows.filter(function (rel) {
      return (relationshipTableName(rel.from) === tableName && relColumnName(rel.from) === columnName) ||
        (relationshipTableName(rel.to) === tableName && relColumnName(rel.to) === columnName);
    });
  }

  function measuresForColumn(tableName, columnName) {
    var needle = "'" + tableName + "'[" + columnName + "]";
    var list = [];
    modelTables.forEach(function (table) {
      table.measures.forEach(function (measure) {
        if (measure.dax && measure.dax.indexOf(needle) !== -1) {
          list.push({ table: table.name, measure: measure });
        }
      });
    });
    return list;
  }

  function renderAll() {
    var query = currentQuery();
    var rows = [];
    var shown = 0;
    var groupsShown = 0;
    var unused = 0;

    function matches(name, extra, uses) {
      if (state.unusedOnly && uses !== 0) return false;
      return !query || (name + " " + extra).toLowerCase().indexOf(query) !== -1;
    }

    modelTables.forEach(function (table) {
      var columns = state.typeFilter === "Measure" || state.typeFilter === "Halaman" ? [] : table.columns.filter(function (column) {
        return matches(column.n, table.name + " " + column.t, column.u);
      });
      var measures = state.typeFilter === "Kolom" || state.typeFilter === "Halaman" ? [] : table.measures.filter(function (measure) {
        return matches(measure.n, table.name + " " + (measure.dax || ""), measure.u);
      });
      if (!columns.length && !measures.length) return;

      groupsShown += 1;
      var tableId = "all:table:" + table.name;
      var allItems = table.columns.concat(table.measures);
      var usedItems = allItems.filter(function (item) { return item.u > 0; }).length;
      var percent = allItems.length ? Math.round(usedItems / allItems.length * 100) : 100;
      rows.push({
        id: tableId, level: 0, group: true, name: table.name, icon: "table",
        rest: [
          "Tabel", "—", "Model", "—", fmtSize(tableSizeMb(table)),
          '<span class="chip ' + (usedItems === allItems.length ? "chip-ok" : "chip-warn") + '"><span class="dot"></span>' +
            percent + "% (" + usedItems + "/" + allItems.length + ") dipakai</span>",
          fmtInt(usedItems), "—", errorChip(), "—"
        ]
      });

      if (measures.length) {
        var measureGroup = tableId + ":m";
        rows.push({
          id: measureGroup, level: 1, group: true, name: "Measure (" + measures.length + ")", icon: "group",
          rest: allGroupRest("Grup", table.name)
        });
        measures.forEach(function (measure) {
          rows.push({
            id: measureGroup + ":" + measure.n, level: 2, numCols: [5, 7],
            cls: measure.u === 0 ? "row-unused" : "",
            cells: [
              nameCell(measure.n, "measure", { level: 2 }),
              "Measure", escapeHtml(table.name), "Model", "DAX", "0 B",
              statusChip(statusOf(measure)), fmtInt(measure.u),
              escapeHtml(measure.f || "—"), errorChip(),
              table.name === "_Measures" ? "_Measures" : "—"
            ]
          });
          shown += 1;
          if (measure.u === 0) unused += 1;
        });
      }

      if (columns.length) {
        var columnGroup = tableId + ":c";
        rows.push({
          id: columnGroup, level: 1, group: true, name: "Kolom (" + columns.length + ")", icon: "group",
          rest: allGroupRest("Grup", table.name)
        });
        columns.forEach(function (column) {
          var rels = relationshipsForColumn(table.name, column.n);
          var usedMeasures = measuresForColumn(table.name, column.n);
          var itemId = columnGroup + ":" + column.n;
          var expandable = rels.length > 0 || usedMeasures.length > 0 || column.u > 0;
          var rest = [
            "Kolom", escapeHtml(table.name), "Model", escapeHtml(column.t), fmtSize(column.mb),
            statusChip(statusOf(column)), fmtInt(column.u), columnFormat(column), errorChip(), "—"
          ];

          if (expandable) {
            rows.push({
              id: itemId, level: 2, group: true, name: column.n, icon: "column", numCols: [5, 7],
              cls: column.u === 0 ? "row-unused" : "", rest: rest
            });
          } else {
            rows.push({
              id: itemId, level: 2, numCols: [5, 7],
              cls: column.u === 0 ? "row-unused" : "",
              cells: [nameCell(column.n, "column", { level: 2 })].concat(rest)
            });
          }
          shown += 1;
          if (column.u === 0) unused += 1;

          if (!expandable) return;

          if (rels.length) {
            var relGroup = itemId + ":rel";
            rows.push({
              id: relGroup, level: 3, group: true, name: "Digunakan di relasi (" + rels.length + ")", icon: "group",
              rest: allGroupRest("Grup", table.name)
            });
            rels.forEach(function (rel) {
              rows.push({
                level: 4, numCols: [7],
                cells: [
                  nameCell(rel.name, "link", { level: 4 }),
                  "Relasi", "—", "Model", "—", "—", relTypeChip(rel.type),
                  fmtInt(rel.uses), "—", errorChip(), "—"
                ]
              });
            });
          }

          if (usedMeasures.length) {
            var measureUseGroup = itemId + ":msr";
            rows.push({
              id: measureUseGroup, level: 3, group: true, name: "Digunakan di measure (" + usedMeasures.length + ")", icon: "group",
              rest: allGroupRest("Grup", table.name)
            });
            usedMeasures.forEach(function (entry) {
              rows.push({
                level: 4, numCols: [5, 7],
                cells: [
                  nameCell(entry.measure.n, "measure", { level: 4 }),
                  "Measure", escapeHtml(entry.table), "Model", "DAX", "0 B",
                  statusChip(statusOf(entry.measure)), fmtInt(entry.measure.u),
                  escapeHtml(entry.measure.f || "—"), errorChip(),
                  entry.table === "_Measures" ? "_Measures" : "—"
                ]
              });
            });
          }

          if (column.u > 0) {
            rows.push({
              level: 3, numCols: [7],
              cells: [
                nameCell(column.u + " visual di " + reportModel.name, "page", { level: 3 }),
                "Visual", reportModel.name, "Report", "—", "—",
                statusChip("Dipakai"), fmtInt(column.u), "—", errorChip(), "—"
              ]
            });
          }
        });
      }
    });

    if (state.typeFilter === "all" || state.typeFilter === "Halaman") {
      var pages = reportModel.pages.filter(function (page) {
        if (state.unusedOnly && page.used) return false;
        return !query || (page.n + " Halaman " + reportModel.name).toLowerCase().indexOf(query) !== -1;
      });
      if (pages.length) {
        groupsShown += 1;
        var reportId = "all:report";
        var reportVisuals = reportModel.pages.reduce(function (sum, page) { return sum + page.vis; }, 0);
        rows.push({
          id: reportId, level: 0, group: true, name: reportModel.name, icon: "page",
          rest: [
            "Report", "—", "Report", "—", reportModel.pages.length + " halaman",
            statusChip("Dipakai"), fmtInt(reportVisuals), "—", errorChip(), "—"
          ]
        });
        var pageGroup = reportId + ":pages";
        rows.push({
          id: pageGroup, level: 1, group: true, name: "Halaman (" + pages.length + ")", icon: "group",
          rest: allGroupRest("Grup", reportModel.name)
        });
        pages.forEach(function (page) {
          rows.push({
            id: "all:page:" + page.n, level: 2, numCols: [7],
            cls: page.used ? "" : "row-unused",
            cells: [
              nameCell(page.n, "page", { level: 2 }),
              "Halaman", reportModel.name, "Report", "—", "—",
              statusChip(page.used ? "Dipakai" : "Tidak dipakai"), fmtInt(page.vis), "—", errorChip(), "—"
            ]
          });
          shown += 1;
          if (!page.used) unused += 1;
        });
      }
    }

    return {
      head: headersMarkup("all"),
      body: emitRows(rows, !!query),
      count: shown,
      summary: fmtInt(shown) + " item · " + groupsShown + " tabel/report · " + unused + " tidak dipakai"
    };
  }

  function tableGroupRest(table) {
    var items = table.columns.concat(table.measures);
    var used = items.filter(function (item) { return item.u > 0; }).length;
    var percent = items.length ? Math.round(used / items.length * 100) : 100;
    return [
      "Tabel",
      "—",
      "Sales Model",
      "—",
      fmtSize(tableSizeMb(table)),
      '<span class="chip ' + (used === items.length ? "chip-ok" : "chip-warn") + '"><span class="dot"></span>' +
        percent + "% (" + used + "/" + items.length + ") dipakai</span>",
      fmtInt(used),
      table.storage,
      "—"
    ];
  }

  function tableSubGroupRest(label, table) {
    return [label, table.name, "Model", "—", "—", "—", "—", "—", "—"];
  }

  function renderTables() {
    var query = currentQuery();
    var rows = [];
    var shown = 0;
    var shownColumns = 0;
    var shownMeasures = 0;
    var shownUnused = 0;
    modelTables.forEach(function (table) {
      var measures = table.measures.filter(function (measure) {
        if (state.typeFilter === "Kolom") return false;
        if (state.unusedOnly && measure.u !== 0) return false;
        return !query || (table.name + " " + measure.n + " " + measure.dax).toLowerCase().indexOf(query) !== -1;
      });
      var columns = table.columns.filter(function (column) {
        if (state.typeFilter === "Measure") return false;
        if (state.unusedOnly && column.u !== 0) return false;
        return !query || (table.name + " " + column.n + " " + column.t).toLowerCase().indexOf(query) !== -1;
      });
      if (!measures.length && !columns.length) return;
      var tableId = "tbl:" + table.name;
      rows.push({ id: tableId, level: 0, group: true, name: table.name, icon: "table", rest: tableGroupRest(table) });

      if (measures.length) {
        var measureGroup = tableId + ":m";
        rows.push({ id: measureGroup, level: 1, group: true, name: "Measure (" + measures.length + ")", icon: "group", rest: tableSubGroupRest("Grup", table) });
        measures.forEach(function (measure) {
          rows.push({
            id: measureGroup + ":" + measure.n, level: 2, numCols: [5, 7],
            cls: measure.u === 0 ? "row-unused" : "",
            cells: [
              nameCell(measure.n, "measure", { level: 2 }),
              "Measure",
              escapeHtml(table.name),
              "Model",
              "DAX",
              "0 B",
              statusChip(statusOf(measure)),
              fmtInt(measure.u),
              "—",
              escapeHtml(measure.f || "—")
            ]
          });
          shown += 1;
          shownMeasures += 1;
          if (measure.u === 0) shownUnused += 1;
        });
      }

      if (columns.length) {
        var columnGroup = tableId + ":c";
        rows.push({ id: columnGroup, level: 1, group: true, name: "Kolom (" + columns.length + ")", icon: "group", rest: tableSubGroupRest("Grup", table) });
        columns.forEach(function (column) {
          rows.push({
            id: columnGroup + ":" + column.n, level: 2, numCols: [5, 7],
            cls: column.u === 0 ? "row-unused" : "",
            cells: [
              nameCell(column.n, "column", { level: 2 }),
              "Kolom",
              escapeHtml(table.name),
              "Model",
              escapeHtml(column.t),
              fmtSize(column.mb),
              statusChip(statusOf(column)),
              fmtInt(column.u),
              table.storage,
              "—"
            ]
          });
          shown += 1;
          shownColumns += 1;
          if (column.u === 0) shownUnused += 1;
        });
      }
    });
    return {
      head: headersMarkup("tables"),
      body: emitRows(rows, !!query),
      count: shown,
      summary: fmtInt(shownColumns) + " kolom · " + fmtInt(shownMeasures) + " measure · " +
        shownUnused + " tidak dipakai · " + modelTables.length + " tabel"
    };
  }

  function filteredRelationships() {
    var query = currentQuery();
    return relationshipRows.filter(function (rel) {
      if (state.typeFilter !== "all" && rel.type !== state.typeFilter) return false;
      return !query || (rel.name + " " + rel.from + " " + rel.to).toLowerCase().indexOf(query) !== -1;
    });
  }

  function renderRelationships() {
    var list = filteredRelationships();
    var rows = list.map(function (rel, index) {
      return {
        id: "rel-" + index, level: 0, numCols: [6],
        cls: rel.uses === 0 ? "row-unused" : "",
        cells: [
          nameCell(rel.name, "link", { level: 0 }),
          escapeHtml(rel.type),
          escapeHtml(rel.cross),
          escapeHtml(rel.card),
          statusChip(rel.uses > 0 ? "Dipakai" : "Tidak dipakai"),
          escapeHtml(rel.auto),
          fmtInt(rel.uses),
          '<span class="mono-trunc" title="' + escapeHtml(rel.from) + '">' + escapeHtml(rel.from) + "</span>",
          '<span class="mono-trunc" title="' + escapeHtml(rel.to) + '">' + escapeHtml(rel.to) + "</span>"
        ]
      };
    });
    var active = list.filter(function (rel) { return rel.type === "Aktif"; }).length;
    var unused = list.filter(function (rel) { return rel.uses === 0; }).length;
    return {
      head: headersMarkup("relationships"),
      body: emitRows(rows, false),
      count: list.length,
      summary: fmtInt(list.length) + " relasi · " + active + " aktif · " + unused + " tidak dipakai"
    };
  }

  var REL_LAYOUT = {
    "Dim Customer": [95, 70],
    "Dim Product": [95, 190],
    "Dim Geography": [95, 310],
    "Dim Date": [95, 430],
    "Fact Sales": [380, 250],
    "Fact Budget": [665, 80],
    "Stock Level": [665, 210],
    "Fact Returns": [665, 340],
    "Report Config": [665, 460]
  };

  function relTableInfo(name) {
    for (var i = 0; i < modelTables.length; i += 1) {
      if (modelTables[i].name === name) return modelTables[i];
    }
    return null;
  }

  function relKindLabel(name) {
    if (name.indexOf("Dim ") === 0) return "Tabel dimensi";
    if (name === "Report Config") return "Tabel konfigurasi";
    return "Tabel fakta";
  }

  function relationshipTableName(reference) {
    return reference.split("[")[0];
  }

  function groupRelPairs(list) {
    var pairs = {};
    list.forEach(function (rel) {
      var a = relationshipTableName(rel.from);
      var b = relationshipTableName(rel.to);
      var key = a + "|" + b;
      if (!pairs[key]) pairs[key] = { key: key, a: a, b: b, rels: [] };
      pairs[key].rels.push(rel);
    });
    return pairs;
  }

  function relPairStatus(pair) {
    var active = pair.rels.filter(function (rel) { return rel.type === "Aktif"; }).length;
    return { active: active, inactive: pair.rels.length - active };
  }

  function relEdgePoint(cx, cy, tx, ty) {
    var dx = tx - cx;
    var dy = ty - cy;
    var scaleX = Math.abs(dx) < 0.001 ? Infinity : 75 / Math.abs(dx);
    var scaleY = Math.abs(dy) < 0.001 ? Infinity : 29 / Math.abs(dy);
    var scale = Math.min(scaleX, scaleY);
    if (!isFinite(scale)) scale = 1;
    return { x: cx + dx * scale, y: cy + dy * scale };
  }

  function relStatBlock(label, value) {
    return '<div class="rel-side-stat"><b>' + escapeHtml(String(value)) + "</b><span>" + escapeHtml(label) + "</span></div>";
  }

  function relTableSide(name, visiblePairs) {
    var info = relTableInfo(name) || { columns: [], measures: [], rows: 0 };
    var keys = Object.keys(visiblePairs).filter(function (key) {
      var pair = visiblePairs[key];
      return pair.a === name || pair.b === name;
    });
    var rels = [];
    keys.forEach(function (key) { rels = rels.concat(visiblePairs[key].rels); });
    var active = rels.filter(function (rel) { return rel.type === "Aktif"; }).length;
    var items = keys.map(function (key) {
      var pair = visiblePairs[key];
      var target = pair.a === name ? pair.b : pair.a;
      var status = relPairStatus(pair);
      return '<button type="button" class="rel-side-item" data-rel-pair="' + escapeHtml(pair.key) + '">' +
        "<strong>" + escapeHtml(target) + "</strong>" +
        "<span>" + pair.rels.length + " relasi · " + status.inactive + " tidak aktif</span></button>";
    }).join("");

    return '<p class="rel-side-title">' + escapeHtml(name) + "</p>" +
      '<p class="rel-side-sub">' + relKindLabel(name) + " · " + info.columns.length + " kolom · " +
      info.measures.length + " measure · " + fmtInt(info.rows) + " baris</p>" +
      '<div class="rel-side-stats">' +
        relStatBlock("Relasi", rels.length) +
        relStatBlock("Aktif", active) +
        relStatBlock("Tidak aktif", rels.length - active) +
        relStatBlock("Tabel terkait", keys.length) +
      "</div>" +
      (keys.length
        ? '<div class="rel-side-list">' + items + "</div>"
        : '<p class="rel-side-note">Tidak ada relasi yang cocok dengan filter saat ini.</p>') +
      '<p class="rel-side-note">Klik garis pada grafik untuk melihat kolom relasi.</p>';
  }

  function relPairSide(pair) {
    var status = relPairStatus(pair);
    var cards = pair.rels.map(function (rel) {
      return '<div class="rel-side-rel"><code>' + escapeHtml(rel.from) + " → " + escapeHtml(rel.to) + "</code>" +
        '<div class="rel-meta">' + statusChip(rel.uses > 0 ? "Dipakai" : "Tidak dipakai") +
        '<span class="chip chip-idle">' + escapeHtml(rel.type) + "</span>" +
        '<span class="chip chip-idle">' + escapeHtml(rel.cross) + "</span>" +
        '<span class="chip chip-idle">' + escapeHtml(rel.card) + "</span>" +
        '<span class="chip chip-idle">auto: ' + escapeHtml(rel.auto) + "</span></div></div>";
    }).join("");

    return '<p class="rel-side-title">' + escapeHtml(pair.a) + " → " + escapeHtml(pair.b) + "</p>" +
      '<p class="rel-side-sub">' + pair.rels.length + " relasi · " + status.active + " aktif · " +
      status.inactive + " tidak aktif</p>" +
      '<div class="rel-side-list">' + cards + "</div>" +
      '<button type="button" class="btn btn-sm rel-side-back" data-rel-table="' + escapeHtml(pair.a) + '">' +
      "Lihat semua relasi " + escapeHtml(pair.a) + "</button>";
  }

  function renderRelationshipGraphSide(selected, allPairs, visiblePairs) {
    if (selected.indexOf("pair:") === 0) {
      var pair = allPairs[selected.slice(5)];
      if (pair) return relPairSide(pair);
    }
    return relTableSide(selected.slice(4), visiblePairs);
  }

  function renderRelationshipGraph() {
    var allPairs = groupRelPairs(relationshipRows);
    var visiblePairs = groupRelPairs(filteredRelationships());
    var selected = state.relSelected || "tbl:Fact Sales";

    if (selected.indexOf("pair:") === 0 && !allPairs[selected.slice(5)]) selected = "tbl:Fact Sales";
    if (selected.indexOf("tbl:") === 0 && !REL_LAYOUT[selected.slice(4)]) selected = "tbl:Fact Sales";
    state.relSelected = selected;

    var isTableSelection = selected.indexOf("tbl:") === 0;
    var selectedTable = isTableSelection ? selected.slice(4) : "";

    var edges = "";
    Object.keys(visiblePairs).forEach(function (key) {
      var pair = visiblePairs[key];
      var from = REL_LAYOUT[pair.a];
      var to = REL_LAYOUT[pair.b];
      if (!from || !to) return;
      var start = relEdgePoint(from[0], from[1], to[0], to[1]);
      var end = relEdgePoint(to[0], to[1], from[0], from[1]);
      var dx = end.x - start.x;
      var dy = end.y - start.y;
      var length = Math.sqrt(dx * dx + dy * dy) || 1;
      if (length > 40) {
        end.x -= (dx / length) * 9;
        end.y -= (dy / length) * 9;
      }
      var status = relPairStatus(pair);
      var inactive = status.active === 0;
      var isPair = selected === "pair:" + key;
      var hot = isPair || (isTableSelection && (pair.a === selectedTable || pair.b === selectedTable));
      var classes = "edge rel-edge" + (inactive ? " is-inactive" : "") + (hot ? " is-selected" : "");
      var path = "M" + start.x + " " + start.y + "L" + end.x + " " + end.y;
      edges += '<path class="rel-edge-hit" d="' + path + '" data-pair="' + escapeHtml(key) + '"></path>';
      edges += '<path class="' + classes + '" d="' + path + '" data-pair="' + escapeHtml(key) +
        '" marker-end="url(#' + (hot ? "relArrowActive" : "relArrow") + ')">' +
        "<title>" + escapeHtml(pair.a + " → " + pair.b + " · " + pair.rels.length + " relasi") + "</title></path>";
      if (pair.rels.length > 1) {
        var mx = (start.x + end.x) / 2;
        var my = (start.y + end.y) / 2;
        edges += '<g class="rel-edge-badge" aria-hidden="true">' +
          '<rect x="' + (mx - 10) + '" y="' + (my - 8) + '" width="20" height="16" rx="8"></rect>' +
          '<text x="' + mx + '" y="' + (my + 3) + '">' + pair.rels.length + "</text></g>";
      }
    });

    var nodes = "";
    Object.keys(REL_LAYOUT).forEach(function (name) {
      var center = REL_LAYOUT[name];
      var info = relTableInfo(name) || { columns: [], measures: [], rows: 0 };
      var width = 150;
      var height = 58;
      var x = center[0] - width / 2;
      var y = center[1] - height / 2;
      var touches = Object.keys(visiblePairs).some(function (key) {
        return visiblePairs[key].a === name || visiblePairs[key].b === name;
      });
      var isSelected = isTableSelection && selectedTable === name;
      var classes = "node rel-node" + (touches ? "" : " is-dim");
      nodes += '<g class="' + classes + '" tabindex="0" role="button" data-table="' + escapeHtml(name) +
        '" aria-label="' + escapeHtml(name + ", " + relKindLabel(name) + (touches ? ", memiliki relasi" : ", tanpa relasi")) +
        '" aria-current="' + (isSelected ? "true" : "false") + '">' +
        '<rect class="node-box' + (isSelected ? " sel" : "") + '" x="' + x + '" y="' + y +
        '" width="' + width + '" height="' + height + '" rx="6"></rect>' +
        '<text class="node-type" x="' + (x + 11) + '" y="' + (y + 16) + '">' + escapeHtml(relKindLabel(name)) + "</text>" +
        '<text class="node-name" x="' + (x + 11) + '" y="' + (y + 33) + '">' + escapeHtml(name) + "</text>" +
        '<text class="rel-node-meta" x="' + (x + 11) + '" y="' + (y + 48) + '">' +
        info.columns.length + " kolom · " + info.measures.length + " measure</text></g>";
    });

    var layer = $("#relGraphLayer");
    if (layer) layer.innerHTML = edges + nodes;
    $("#relGraphSide").innerHTML = renderRelationshipGraphSide(selected, allPairs, visiblePairs);
  }

  function brokenChip(count) {
    return '<span class="chip ' + (count ? "chip-danger" : "chip-ok") + '"><span class="dot"></span>' + count + "</span>";
  }

  function renderReport() {
    var query = currentQuery();
    var pages = reportModel.pages.filter(function (page) {
      if (state.typeFilter !== "all") {
        if (state.typeFilter === "Dipakai" && !page.used) return false;
        if (state.typeFilter === "Tidak dipakai" && page.used) return false;
      }
      return !query || (page.n + " Halaman " + reportModel.name).toLowerCase().indexOf(query) !== -1;
    });
    var hidden = reportModel.hiddenPages.filter(function (page) {
      if (state.typeFilter === "Dipakai") return false;
      return !query || (page.n + " Halaman tersembunyi").toLowerCase().indexOf(query) !== -1;
    });
    var filters = reportModel.filters.filter(function (name) {
      if (state.typeFilter === "Tidak dipakai") return false;
      return !query || (name + " Filter level report").toLowerCase().indexOf(query) !== -1;
    });
    var hiddenVisuals = reportModel.hiddenPages.reduce(function (sum, page) { return sum + page.vis; }, 0);
    var totalVisuals = reportModel.pages.reduce(function (sum, page) { return sum + page.vis; }, 0);
    var broken = reportModel.pages.reduce(function (sum, page) { return sum + page.broken; }, 0);
    var rows = [];

    if (pages.length || hidden.length || filters.length || !query) {
      rows.push({
        id: "rep", level: 0, group: true, name: reportModel.name, icon: "page",
        numCols: [],
        rest: [
          "Local report", "File", fmtInt(totalVisuals), brokenChip(broken), "—",
          String(reportModel.pages.length), reportModel.theme, reportModel.score + " (Baik)", statusChip("Dipakai")
        ]
      });
    }

    if (hidden.length) {
      rows.push({
        id: "rep:hidden", level: 1, group: true, name: "Halaman tersembunyi", icon: "group",
        rest: ["Grup", "File", fmtInt(hiddenVisuals), brokenChip(0), "—", String(hidden.length), "—", "—", "—"]
      });
      hidden.forEach(function (page) {
        rows.push({
          id: "rep:hidden:" + page.n, level: 2, numCols: [3, 4, 5],
          cls: "row-unused",
          cells: [
            nameCell(page.n, "page", { level: 2 }), "Halaman", "File", fmtInt(page.vis),
            brokenChip(page.broken), "—", "—", "—", "—", statusChip("Tidak dipakai")
          ]
        });
      });
    }

    if (pages.length) {
      rows.push({
        id: "rep:pages", level: 1, group: true, name: "Halaman", icon: "group",
        rest: ["Grup", "File", fmtInt(totalVisuals), brokenChip(broken), "—", String(reportModel.pages.length), "—", "—", "—"]
      });
      pages.forEach(function (page) {
        rows.push({
          id: "rep:page:" + page.n, level: 2, group: true, name: page.n, icon: "page",
          rest: [
            "Halaman", "File", fmtInt(page.vis), brokenChip(page.broken), page.views,
            "—", "—", "—", statusChip(page.used ? "Dipakai" : "Tidak dipakai")
          ]
        });
        rows.push({
          id: "rep:page:" + page.n + ":vis", level: 3, numCols: [3, 4],
          cells: [
            nameCell("Visual", "page", { level: 3 }), "Visual", page.n, fmtInt(page.vis),
            brokenChip(page.broken), "—", "—", "—", "—", "—"
          ]
        });
        rows.push({
          id: "rep:page:" + page.n + ":filter", level: 3, numCols: [],
          cells: [
            nameCell("Filter level halaman (" + page.filters + ")", "filter", { level: 3 }), "Filter", page.n, "—",
            "—", "—", "—", "—", "—", "—"
          ]
        });
      });
    }

    if (filters.length) {
      rows.push({
        id: "rep:filters", level: 1, group: true, name: "Filter level report", icon: "group",
        rest: ["Grup", "File", "—", "—", "—", "—", "—", "—", "—"]
      });
      filters.forEach(function (name) {
        rows.push({
          id: "rep:filter:" + name, level: 2, numCols: [6],
          cells: [
            nameCell(name, "filter", { level: 2 }), "Filter kategorikal", "File", "—",
            "—", "—", "—", "—", "—", statusChip("Dipakai")
          ]
        });
      });
    }

    return {
      head: headersMarkup("report"),
      body: emitRows(rows, !!query),
      count: rows.length,
      summary: "1 report · " + reportModel.pages.length + " halaman · " + fmtInt(totalVisuals) +
        " visual · " + broken + " visual rusak · " + reportModel.filters.length + " filter"
    };
  }

  function daxEntries() {
    var entries = [];
    modelTables.forEach(function (table) {
      table.measures.forEach(function (measure) {
        entries.push({ id: "dax:" + table.name + ":" + measure.n, table: table.name, measure: measure });
      });
    });
    return entries;
  }

  function renderDax() {
    var query = currentQuery();
    var list = daxEntries().filter(function (entry) {
      var measure = entry.measure;
      if (state.typeFilter === "Dipakai" && measure.u === 0) return false;
      if (state.typeFilter === "Tidak dipakai" && measure.u > 0) return false;
      return !query || (measure.n + " " + measure.dax + " " + entry.table).toLowerCase().indexOf(query) !== -1;
    });
    var rows = [];
    list.forEach(function (entry) {
      var measure = entry.measure;
      rows.push({
        id: entry.id, level: 0, group: true, name: measure.n, icon: "code", numCols: [4, 5],
        rest: [
          entry.table,
          "Measure",
          '<span class="chip chip-ok"><span class="dot"></span>Tidak</span>',
          fmtInt(measure.v || 0),
          fmtInt(measure.u),
          '<span class="mono-trunc" title="Sales Model (APAC)">Sales Model (APAC)</span>',
          "Semantic model"
        ]
      });
      rows.push({ kind: "code", level: 1, cols: 8, code: measure.dax });
    });
    var violations = list.reduce(function (sum, entry) { return sum + (entry.measure.v || 0); }, 0);
    var unused = list.filter(function (entry) { return entry.measure.u === 0; }).length;
    return {
      head: headersMarkup("dax"),
      body: emitRows(rows, false),
      count: list.length,
      summary: fmtInt(list.length) + " measure · " + unused + " tidak dipakai · " + violations + " pelanggaran praktik"
    };
  }

  function renderM() {
    var query = currentQuery();
    var list = mQueries.filter(function (item) {
      if (state.typeFilter !== "all" && item.type !== state.typeFilter) return false;
      return !query || (item.n + " " + item.code).toLowerCase().indexOf(query) !== -1;
    });
    var rows = [];
    list.forEach(function (item) {
      rows.push({
        id: "m:" + item.n, level: 0, group: true, name: item.n, icon: "query",
        rest: [
          item.type,
          "Sales Model (APAC)",
          item.warn ? '<span class="chip chip-warn"><span class="dot"></span>' + item.warn + " peringatan</span>"
            : '<span class="chip chip-ok"><span class="dot"></span>Tidak ada</span>'
        ]
      });
      rows.push({ kind: "code", level: 1, cols: 4, code: item.code });
    });
    var warnings = list.reduce(function (sum, item) { return sum + item.warn; }, 0);
    var parameters = list.filter(function (item) { return item.type === "M parameter"; }).length;
    return {
      head: headersMarkup("m"),
      body: emitRows(rows, false),
      count: list.length,
      summary: fmtInt(list.length) + " kueri · " + (list.length - parameters) + " tabel · " + parameters + " parameter · " + warnings + " peringatan"
    };
  }

  function renderAnalysis() {
    var wrap = $("#analyzeTableWrap");
    var empty = $("#analyzeEmpty");

    if (!state.analyzed) {
      wrap.hidden = true;
      $("#relGraph").hidden = true;
      empty.hidden = false;
      $("#analyzeFromEmpty").hidden = false;
      $("#analyzeEmptyTitle").textContent = "Belum ada hasil analisa";
      $("#analyzeEmptyText").textContent = "Pilih workspace dan semantic model, lalu tekan Analisa. Hasil muncul di sini tanpa mengubah model.";
      $("#analyzeSummary").textContent = "Belum dianalisis";
      return;
    }

    var graphMode = state.analyzeTab === "relationships" && state.relView === "graph";
    $("#relGraph").hidden = !graphMode;
    if (graphMode) {
      var relResult = renderRelationships();
      $("#analyzeHead").innerHTML = "";
      $("#analyzeBody").innerHTML = "";
      wrap.hidden = true;
      empty.hidden = true;
      $("#analyzeSummary").textContent = relResult.summary;
      renderRelationshipGraph();
      return;
    }

    var result;
    if (state.analyzeTab === "tables") result = renderTables();
    else if (state.analyzeTab === "relationships") result = renderRelationships();
    else if (state.analyzeTab === "report") result = renderReport();
    else if (state.analyzeTab === "dax") result = renderDax();
    else if (state.analyzeTab === "m") result = renderM();
    else result = renderAll();

    $("#analyzeHead").innerHTML = result.head;
    $("#analyzeBody").innerHTML = result.body;
    $("#analyzeSummary").textContent = result.summary;

    if (!result.count) {
      wrap.hidden = true;
      empty.hidden = false;
      $("#analyzeFromEmpty").hidden = true;
      $("#analyzeEmptyTitle").textContent = "Tidak ada item yang cocok";
      $("#analyzeEmptyText").textContent = "Ubah kata kunci atau filter untuk melihat item lain pada tab ini.";
    } else {
      wrap.hidden = false;
      empty.hidden = true;
    }
  }

  function runAnalysis() {
    if (state.analyzing) return;
    state.analyzing = true;
    $("#runAnalyze").disabled = true;
    $("#analyzeEmpty").hidden = true;
    $("#analyzeTableWrap").hidden = false;
    $("#analyzeHead").innerHTML = headersMarkup(state.analyzeTab);
    $("#analyzeBody").innerHTML = new Array(6).fill('<tr class="skeleton"><td colspan="' +
      ANALYSIS_HEADERS[state.analyzeTab].length + '"><span class="sk"></span></td></tr>').join("");
    setConsole(true);
    addLog("Membaca semantic model: Sales Model (APAC)…", "info");
    window.setTimeout(function () {
      state.analyzed = true;
      state.analyzing = false;
      $("#runAnalyze").disabled = false;
      $$("#analyzeTabs [role='tab']").forEach(function (tab) { tab.disabled = false; });
      updateMetrics();
      updateTabCounts();
      initOpenGroups();
      state.typeFilter = "all";
      applyTabTools(state.analyzeTab);
      renderAnalysis();
      var totals = analysisTotals();
      addLog("Analisa selesai: " + fmtInt(totals.columns + totals.measures + totals.pageCount) +
        " item, " + (totals.unusedColumns + totals.unusedMeasures) + " kolom & measure tidak dipakai.", "ok");
      addLog("Dataset " + fmtSize(totals.size) + " · " + totals.columns + " kolom · " +
        totals.measures + " measure · " + totals.relationshipCount + " relasi.", "info");
      toast("Analisa selesai");
    }, 720);
  }

  var partitionTables = {
    "Fact Sales": {
      mode: "Import", sourceTable: "FactSales", dateColumn: "OrderDate",
      partitions: [
        { name: "2023", range: "1 Jan 2023 – 31 Des 2023", start: "2023-01-01", end: "2024-01-01", rows: 1632274, last: "2 Jul 2026 16.57" },
        { name: "2024", range: "1 Jan 2024 – 31 Des 2024", start: "2024-01-01", end: "2025-01-01", rows: 1677669, last: "2 Jul 2026 16.58" },
        { name: "2025", range: "1 Jan 2025 – 31 Des 2025", start: "2025-01-01", end: "2026-01-01", rows: 1666367, last: "2 Jul 2026 16.58" },
        { name: "2026Q1", range: "1 Jan 2026 – 31 Mar 2026", start: "2026-01-01", end: "2026-04-01", rows: 445183, last: "2 Jul 2026 16.56" },
        { name: "2026Q2", range: "1 Apr 2026 – 30 Jun 2026", start: "2026-04-01", end: "2026-07-01", rows: 421084, last: "2 Jul 2026 16.56" },
        { name: "2026Q410", range: "1 Jul 2026 – 31 Jul 2026", start: "2026-07-01", end: "2026-08-01", rows: 145211, last: "6 Jul 2026 16.41" },
        { name: "2026Q3", range: "1 Agu 2026 – 31 Okt 2026", start: "2026-08-01", end: "2026-11-01", rows: 451243, last: "—" },
        { name: "2026Q411", range: "1 Nov 2026 – 30 Nov 2026", start: "2026-11-01", end: "2026-12-01", rows: 73566, last: "18 Nov 2026 06.50" }
      ]
    },
    "Fact Budget": {
      mode: "Import", sourceTable: "FactBudget", dateColumn: "BudgetMonth",
      partitions: [
        { name: "FY2023", range: "1 Jan 2023 – 31 Des 2023", start: "2023-01-01", end: "2024-01-01", rows: 28240, last: "2 Jul 2026 16.40" },
        { name: "FY2024", range: "1 Jan 2024 – 31 Des 2024", start: "2024-01-01", end: "2025-01-01", rows: 30112, last: "2 Jul 2026 16.41" },
        { name: "FY2025", range: "1 Jan 2025 – 31 Des 2025", start: "2025-01-01", end: "2026-01-01", rows: 31840, last: "2 Jul 2026 16.42" },
        { name: "FY2026", range: "1 Jan 2026 – 31 Des 2026", start: "2026-01-01", end: "2027-01-01", rows: 22180, last: "—" }
      ]
    },
    "Stock Level": {
      mode: "Import", sourceTable: "StockLevel", dateColumn: "SnapshotDate",
      partitions: [
        { name: "2024", range: "1 Jan 2024 – 31 Des 2024", start: "2024-01-01", end: "2025-01-01", rows: 98420, last: "17 Nov 2026 04.06" },
        { name: "2025", range: "1 Jan 2025 – 31 Des 2025", start: "2025-01-01", end: "2026-01-01", rows: 104760, last: "17 Nov 2026 04.06" },
        { name: "2026Q1", range: "1 Jan 2026 – 31 Mar 2026", start: "2026-01-01", end: "2026-04-01", rows: 101220, last: "17 Nov 2026 04.10" },
        { name: "2026Q2", range: "1 Apr 2026 – 30 Jun 2026", start: "2026-04-01", end: "2026-07-01", rows: 108470, last: "—" }
      ]
    },
    "Fact Returns": {
      mode: "Import", sourceTable: "FactReturns", dateColumn: "ReturnDate",
      partitions: [
        { name: "2023", range: "1 Jan 2023 – 31 Des 2023", start: "2023-01-01", end: "2024-01-01", rows: 8940, last: "17 Nov 2026 04.06" },
        { name: "2024", range: "1 Jan 2024 – 31 Des 2024", start: "2024-01-01", end: "2025-01-01", rows: 9860, last: "17 Nov 2026 04.06" },
        { name: "2025", range: "1 Jan 2025 – 31 Des 2025", start: "2025-01-01", end: "2026-01-01", rows: 10240, last: "17 Nov 2026 04.06" },
        { name: "2026", range: "1 Jan 2026 – 31 Des 2026", start: "2026-01-01", end: "2027-01-01", rows: 9200, last: "—" }
      ]
    }
  };

  var PARTITION_MODES = {
    default: { label: "Process Default", help: "Memproses partisi yang belum diproses dan memperbarui dependensi." },
    full: { label: "Process Full", help: "Menghapus data partisi lalu memuat ulang seluruh isinya." },
    data: { label: "Process Data", help: "Memuat ulang data partisi tanpa mengubah struktur tabel." },
    clear: { label: "Process Clear", help: "Mengosongkan data partisi tanpa menghapus definisinya." },
    add: { label: "Process Add", help: "Menambahkan data baru ke partisi yang sudah ada." }
  };

  function partitionInfo() {
    return partitionTables[state.partitionTable];
  }

  function partitionStatus(partition) {
    if (partition.rows === 0) return "Kosong";
    return partition.last === "—" ? "Belum diproses" : "Diproses";
  }

  function partitionStatusChip(status) {
    var cls = status === "Diproses" ? "chip-ok" : (status === "Belum diproses" ? "chip-warn" : "chip-idle");
    return '<span class="chip ' + cls + '"><span class="dot"></span>' + escapeHtml(status) + "</span>";
  }

  function filteredPartitions() {
    var info = partitionInfo();
    var query = ($("#partitionSearch").value || "").trim().toLowerCase();
    return info.partitions.filter(function (partition) {
      var status = partitionStatus(partition);
      if (state.partitionFilter === "processed" && status !== "Diproses") return false;
      if (state.partitionFilter === "unprocessed" && status !== "Belum diproses") return false;
      if (state.partitionFilter === "empty" && status !== "Kosong") return false;
      return !query || (partition.name + " " + partition.range).toLowerCase().indexOf(query) !== -1;
    });
  }

  function partitionExpression(tableName, partition) {
    var info = partitionTables[tableName];
    var start = partition.start.split("-");
    var end = partition.end.split("-");
    return "let\n    Source = Sql.Database ( \"sql-dw-finance\", \"SalesDW\" ),\n    Data = Source{[Schema=\"dbo\",Item=\"" + info.sourceTable + "\"]}[Data],\n    Filtered = Table.SelectRows ( Data, each [" + info.dateColumn + "] >= #date(" +
      Number(start[0]) + ", " + Number(start[1]) + ", " + Number(start[2]) + ") and [" + info.dateColumn + "] < #date(" +
      Number(end[0]) + ", " + Number(end[1]) + ", " + Number(end[2]) + ") )\nin\n    Filtered";
  }

  function selectedPartitionNames() {
    return partitionInfo().partitions.filter(function (partition) {
      return !!state.partitionSelected[partition.name];
    }).map(function (partition) { return partition.name; });
  }

  function syncPartitionSelection() {
    var names = selectedPartitionNames();
    var button = $("#processSelectedPartitions");
    button.disabled = state.partitionBusy || names.length === 0;
    button.textContent = names.length ? "Proses terpilih (" + names.length + ")" : "Proses terpilih";
    $("#partitionSelectionSummary").textContent = names.length + " dipilih · " + partitionInfo().partitions.length + " partisi";
    var rows = filteredPartitions();
    var allChecked = rows.length > 0 && rows.every(function (partition) { return state.partitionSelected[partition.name]; });
    var someChecked = rows.some(function (partition) { return state.partitionSelected[partition.name]; });
    var selectAll = $("#partitionSelectAll");
    if (selectAll) {
      selectAll.checked = allChecked;
      selectAll.indeterminate = someChecked && !allChecked;
    }
  }

  function renderPartitionDetail() {
    var box = $("#partitionDetail");
    var info = partitionInfo();
    var partition = info.partitions.filter(function (item) { return item.name === state.partitionDetail; })[0];
    if (!partition) {
      state.partitionDetail = null;
      box.innerHTML = '<div class="empty" style="padding:24px 6px">' +
        '<span class="empty-icon" aria-hidden="true"><svg class="od-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4-8 4-8-4 8-4Z"/><path d="M4 11l8 4 8-4"/><path d="M4 15l8 4 8-4"/></svg></span>' +
        '<div class="empty-title">Pilih partisi</div>' +
        '<p class="empty-text">Klik salah satu baris untuk melihat rentang, status, dan ekspresi sumbernya.</p></div>';
      return;
    }
    var status = partitionStatus(partition);
    box.innerHTML = '<div class="partition-detail-head"><div>' +
      '<p class="partition-detail-name">' + escapeHtml(partition.name) + "</p>" +
      '<p class="partition-detail-meta">' + escapeHtml(state.partitionTable) + " · " + escapeHtml(partition.range) + "</p></div>" +
      partitionStatusChip(status) + "</div>" +
      '<dl class="partition-kv">' +
        "<dt>Tabel</dt><dd>" + escapeHtml(state.partitionTable) + "</dd>" +
        "<dt>Baris</dt><dd>" + fmtInt(partition.rows) + "</dd>" +
        "<dt>Diproses</dt><dd>" + escapeHtml(partition.last) + "</dd>" +
        "<dt>Mode</dt><dd>" + escapeHtml(info.mode) + "</dd>" +
        "<dt>Sumber</dt><dd>M query</dd>" +
      "</dl>" +
      '<div class="partition-code-label"><span>Ekspresi sumber</span>' +
      '<button class="btn btn-ghost btn-sm" id="copyPartitionSource" type="button">Salin</button></div>' +
      '<div class="partition-code"><pre>' + escapeHtml(partitionExpression(state.partitionTable, partition)) + "</pre></div>" +
      '<div class="partition-detail-actions">' +
      '<button class="btn btn-sm btn-primary" id="processPartitionDetail" type="button">Proses partisi ini</button></div>';
  }

  function renderPartitions() {
    var info = partitionInfo();
    var all = info.partitions;
    var rows = filteredPartitions();
    var totalRows = all.reduce(function (sum, partition) { return sum + partition.rows; }, 0);
    var unprocessed = all.filter(function (partition) { return partitionStatus(partition) === "Belum diproses"; }).length;
    var empty = all.filter(function (partition) { return partition.rows === 0; }).length;

    $("#partitionCount").textContent = fmtInt(all.length);
    $("#partitionCountNote").textContent = state.partitionTable;
    $("#partitionRows").textContent = fmtInt(totalRows);
    $("#partitionRowsNote").textContent = all.length + " partisi";
    $("#partitionUnprocessed").textContent = fmtInt(unprocessed);
    $("#partitionEmpty").textContent = fmtInt(empty);
    $("#partitionListTitle").textContent = "Partisi · " + state.partitionTable;
    $("#partitionCountChip").textContent = all.length + " partisi";

    $("#partitionHead").innerHTML = "<tr>" +
      '<th scope="col"><input type="checkbox" id="partitionSelectAll" class="partition-check" aria-label="Pilih semua partisi"></th>' +
      '<th scope="col">Partisi</th><th scope="col">Rentang</th>' +
      '<th scope="col" class="num"># baris</th><th scope="col">Status</th>' +
      '<th scope="col">Diproses terakhir</th></tr>';

    $("#partitionBody").innerHTML = rows.map(function (partition) {
      var status = partitionStatus(partition);
      var selected = !!state.partitionSelected[partition.name];
      return '<tr tabindex="0" data-partition="' + escapeHtml(partition.name) + '"' +
        (state.partitionDetail === partition.name ? ' class="is-detail"' : "") + ">" +
        '<td class="cell-check"><input type="checkbox" class="partition-check" data-partition-check="' + escapeHtml(partition.name) +
        '" aria-label="Pilih partisi ' + escapeHtml(partition.name) + '"' + (selected ? " checked" : "") + "></td>" +
        '<td class="name">' + escapeHtml(partition.name) + "</td>" +
        "<td>" + escapeHtml(partition.range) + "</td>" +
        '<td class="num">' + fmtInt(partition.rows) + "</td>" +
        "<td>" + partitionStatusChip(status) + "</td>" +
        '<td class="num">' + escapeHtml(partition.last) + "</td></tr>";
    }).join("");

    if (rows.length) {
      $("#partitionTableWrap").hidden = false;
      $("#partitionEmpty").hidden = true;
    } else {
      $("#partitionTableWrap").hidden = true;
      $("#partitionEmpty").hidden = false;
    }

    syncPartitionSelection();
    renderPartitionDetail();
  }

  function nowPartitionLabel() {
    var now = new Date();
    return now.toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" }) + " " +
      now.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  }

  function loadPartitions() {
    if (state.partitionBusy) return;
    state.partitionBusy = true;
    state.partitionSelected = {};
    state.partitionDetail = null;
    $("#partitionListTitle").textContent = "Partisi · " + state.partitionTable;
    $("#partitionRun").hidden = false;
    $("#partitionRunLabel").textContent = "Membaca partisi " + state.partitionTable + "…";
    $("#partitionRunPct").textContent = "0%";
    $("#partitionBar").style.width = "0%";
    $("#partitionTableWrap").hidden = false;
    $("#partitionEmpty").hidden = true;
    $("#partitionBody").innerHTML = new Array(5).fill('<tr class="skeleton"><td colspan="6"><span class="sk"></span></td></tr>').join("");
    syncPartitionSelection();
    setConsole(true);
    addLog("Membaca partisi " + state.partitionTable + " dari Power BI Service…", "info");
    window.setTimeout(function () {
      state.partitionBusy = false;
      $("#partitionRun").hidden = true;
      renderPartitions();
      addLog("Partisi dimuat: " + partitionInfo().partitions.length + " partisi.", "ok");
      toast("Partisi dimuat");
    }, 560);
  }

  function processPartitions(names, mode) {
    if (state.partitionBusy) return;
    var info = partitionInfo();
    var valid = names.filter(function (name) {
      return info.partitions.some(function (partition) { return partition.name === name; });
    });
    if (!valid.length) return;
    var modeInfo = PARTITION_MODES[mode] || PARTITION_MODES.default;
    state.partitionBusy = true;
    $("#partitionRun").hidden = false;
    $("#partitionRunLabel").textContent = modeInfo.label + " · " + valid.length + " partisi…";
    $("#partitionRunPct").textContent = "0%";
    $("#partitionBar").style.width = "0%";
    syncPartitionSelection();
    setConsole(true);
    addLog("Proses " + modeInfo.label + ": " + valid.join(", "), "info");
    var pct = 0;
    var timer = window.setInterval(function () {
      pct += 25;
      if (pct > 100) pct = 100;
      $("#partitionBar").style.width = pct + "%";
      $("#partitionRunPct").textContent = pct + "%";
      if (pct < 100) return;
      window.clearInterval(timer);
      var stamp = nowPartitionLabel();
      valid.forEach(function (name) {
        var partition = info.partitions.filter(function (item) { return item.name === name; })[0];
        if (!partition) return;
        partition.last = stamp;
        if (mode === "clear") partition.rows = 0;
        if (mode === "add") partition.rows += 2500;
      });
      state.partitionBusy = false;
      $("#partitionRun").hidden = true;
      renderPartitions();
      addLog("Selesai: " + valid.length + " partisi · " + modeInfo.label + ".", "ok");
      toast(modeInfo.label + " selesai");
    }, 120);
  }

  function updatePartitionModeHelp() {
    var modeInfo = PARTITION_MODES[$("#partitionMode").value] || PARTITION_MODES.default;
    $("#partitionModeHelp").textContent = modeInfo.help;
  }

  function openPartitionDialog(names) {
    if (state.partitionBusy) return;
    var info = partitionInfo();
    var preselect = {};
    (names || []).forEach(function (name) { preselect[name] = true; });
    if (!(names || []).length) {
      preselect[state.partitionDetail || info.partitions[0].name] = true;
    }
    state.partitionDialogTrigger = document.activeElement;
    $("#partitionDialogSub").textContent = info.partitions.length + " partisi · " + state.partitionTable;
    $("#partitionChecklist").innerHTML = info.partitions.map(function (partition) {
      return '<label class="partition-check-item"><input type="checkbox" class="partition-dialog-check" value="' +
        escapeHtml(partition.name) + '"' + (preselect[partition.name] ? " checked" : "") + ">" +
        "<span>" + escapeHtml(partition.name) + '</span><span class="partition-check-rows">' +
        fmtInt(partition.rows) + " baris</span></label>";
    }).join("");
    $("#partitionMode").value = "default";
    updatePartitionModeHelp();
    $("#runPartitionProcess").disabled = false;
    var dialog = $("#partitionDialog");
    if (!dialog.open) dialog.showModal();
    $("#partitionMode").focus();
  }

  function closePartitionDialog() {
    var dialog = $("#partitionDialog");
    if (dialog.open) dialog.close();
  }

  var lineageNodes = {
    "report-sales": { name: "Sales Performance", type: "Report", workspace: "Sales Analytics", owner: "Budi Santoso", refresh: "17 Nov 2026 04:06", size: "4 halaman" },
    "model-sales": { name: "Sales Model (APAC)", type: "Semantic model", workspace: "Sales Analytics", owner: "Budi Santoso", refresh: "17 Nov 2026 04:06", size: "42 measure" },
    "table-fact": { name: "Fact Sales", type: "Tabel", workspace: "Sales Analytics", owner: "Budi Santoso", refresh: "17 Nov 2026 04:06", size: "1,2 jt baris" },
    "table-cust": { name: "Dim Customer", type: "Tabel", workspace: "Sales Analytics", owner: "Budi Santoso", refresh: "16 Nov 2026 22:10", size: "48 rb baris" },
    "table-prod": { name: "Dim Product", type: "Tabel", workspace: "Sales Analytics", owner: "Budi Santoso", refresh: "16 Nov 2026 22:10", size: "12 rb baris" },
    "measure-rev": { name: "Total Revenue", type: "Measure", workspace: "Sales Analytics", owner: "Sari Wulandari", refresh: "17 Nov 2026 04:06", size: "DAX" },
    "dataflow": { name: "Sales Ingest", type: "Dataflow", workspace: "Data Platform", owner: "Sari Wulandari", refresh: "17 Nov 2026 02:00", size: "harian" },
    "sql": { name: "SQL DW Finance", type: "Database", workspace: "Data Platform", owner: "Andi Pratama", refresh: "17 Nov 2026 01:30", size: "on-prem" },
    "app": { name: "Sales App", type: "App", workspace: "Sales Analytics", owner: "Budi Santoso", refresh: "17 Nov 2026 04:06", size: "3 audiens" },
    "dashboard": { name: "Revenue Overview", type: "Dashboard", workspace: "Sales Analytics", owner: "Sari Wulandari", refresh: "17 Nov 2026 04:06", size: "6 tile" },
    "sub": { name: "Monthly exec", type: "Subscription", workspace: "Sales Analytics", owner: "Budi Santoso", refresh: "setiap 1 bulan", size: "email" },
    "team-com": { name: "Tim Commercial", type: "Grup akses", workspace: "Sales Analytics", owner: "IT Ops", refresh: "—", size: "18 anggota" },
    "team-fin": { name: "Tim Finance", type: "Grup akses", workspace: "Sales Analytics", owner: "IT Ops", refresh: "—", size: "9 anggota" }
  };

  var lineageEdges = [
    ["model-sales", "report-sales"],
    ["table-fact", "model-sales"],
    ["table-cust", "model-sales"],
    ["table-prod", "model-sales"],
    ["measure-rev", "model-sales"],
    ["dataflow", "table-fact"],
    ["sql", "table-fact"],
    ["dataflow", "table-cust"],
    ["dataflow", "table-prod"],
    ["report-sales", "app"],
    ["report-sales", "dashboard"],
    ["report-sales", "sub"],
    ["app", "team-com"],
    ["dashboard", "team-com"],
    ["sub", "team-fin"]
  ];

  function levelsFor(rootId, direction, depth) {
    var levels = [[rootId]];
    var seen = {};
    seen[rootId] = true;
    for (var d = 0; d < depth; d += 1) {
      var frontier = levels[levels.length - 1];
      var next = [];
      frontier.forEach(function (id) {
        lineageEdges.forEach(function (edge) {
          var candidate = direction === "upstream"
            ? (edge[1] === id ? edge[0] : null)
            : (edge[0] === id ? edge[1] : null);
          if (candidate && !seen[candidate]) {
            seen[candidate] = true;
            next.push(candidate);
          }
        });
      });
      if (!next.length) break;
      levels.push(next);
    }
    return levels;
  }

  function renderLineage() {
    var levels = levelsFor(state.rootId, state.direction, state.depth);
    var nodeW = 150;
    var nodeH = 44;
    var colGap = 34;
    var rowGap = 18;
    var width = Math.max(640, 198 + (levels.length - 1) * (nodeW + colGap));
    var maxNodes = 1;
    levels.forEach(function (ids) { maxNodes = Math.max(maxNodes, ids.length); });
    var height = Math.max(280, maxNodes * (nodeH + rowGap) + 56);
    var positions = {};

    levels.forEach(function (ids, level) {
      var total = ids.length * nodeH + (ids.length - 1) * rowGap;
      var startY = (height - total) / 2;
      ids.forEach(function (id, index) {
        var x = state.direction === "upstream"
          ? width - 24 - nodeW - level * (nodeW + colGap)
          : 24 + level * (nodeW + colGap);
        positions[id] = { x: x, y: startY + index * (nodeH + rowGap) };
      });
    });

    var edges = "";
    lineageEdges.forEach(function (edge) {
      var from = positions[edge[0]];
      var to = positions[edge[1]];
      if (!from || !to) return;
      var x1 = from.x + nodeW;
      var y1 = from.y + nodeH / 2;
      var x2 = to.x;
      var y2 = to.y + nodeH / 2;
      if (x2 <= x1) return;
      var mid = (x1 + x2) / 2;
      edges += '<path class="edge" d="M' + x1 + " " + y1 + " C" + mid + " " + y1 + ", " + mid + " " + y2 + ", " + x2 + " " + y2 + '" marker-end="url(#arrow)"></path>';
    });

    var nodes = "";
    levels.forEach(function (ids) {
      ids.forEach(function (id) {
        var node = lineageNodes[id];
        var pos = positions[id];
        var selected = id === state.selectedId ? " sel" : "";
        var current = id === state.rootId ? "true" : "false";
        var label = node.name.length > 21 ? node.name.slice(0, 20) + "…" : node.name;
        nodes += '<g class="node" tabindex="0" role="button" data-id="' + id + '" aria-label="' + escapeHtml(node.name) + ", " + escapeHtml(node.type) + '" aria-current="' + current + '">' +
          '<rect class="node-box' + selected + '" x="' + pos.x + '" y="' + pos.y + '" width="' + nodeW + '" height="' + nodeH + '" rx="6"></rect>' +
          '<text x="' + (pos.x + 12) + '" y="' + (pos.y + 15) + '" class="node-type">' + escapeHtml(node.type) + "</text>" +
          '<text x="' + (pos.x + 12) + '" y="' + (pos.y + 32) + '" class="node-name">' + escapeHtml(label) + "</text>" +
          "</g>";
      });
    });

    var svg = $("#lineageSvg");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    $("#lineageLayer").innerHTML = edges + nodes;
    $("#depthVal").textContent = state.depth + " level";
    $("#depthMinus").disabled = state.depth <= 1;
    $("#depthPlus").disabled = state.depth >= 3;
    $("#lineageRootChip").innerHTML = '<span class="dot"></span>Akar: ' + escapeHtml(lineageNodes[state.rootId].name);
    renderDetail();
  }

  function renderDetail() {
    var node = lineageNodes[state.selectedId];
    var deps = [];
    lineageEdges.forEach(function (edge) {
      if (edge[0] === state.selectedId) deps.push(lineageNodes[edge[1]]);
      if (edge[1] === state.selectedId) deps.push(lineageNodes[edge[0]]);
    });
    var chips = deps.length
      ? deps.map(function (dep) { return '<span class="chip">' + escapeHtml(dep.name) + "</span>"; }).join("")
      : '<span class="helper">Tidak ada relasi langsung.</span>';

    $("#lineageDetail").innerHTML =
      '<div class="detail-head">' +
        "<div>" +
          '<div class="detail-name">' + escapeHtml(node.name) + "</div>" +
          '<div class="helper">' + escapeHtml(node.type) + " · " + escapeHtml(node.workspace) + "</div>" +
        "</div>" +
        '<button class="btn btn-sm" type="button" id="makeRoot"' + (state.selectedId === state.rootId ? " disabled" : "") + ">Jadikan akar</button>" +
      "</div>" +
      '<dl class="kv">' +
        "<dt>Pemilik</dt><dd>" + escapeHtml(node.owner) + "</dd>" +
        "<dt>Refresh</dt><dd>" + escapeHtml(node.refresh) + "</dd>" +
        "<dt>Ukuran</dt><dd>" + escapeHtml(node.size) + "</dd>" +
        "<dt>Relasi</dt><dd>" + deps.length + " item</dd>" +
      "</dl>" +
      '<div class="dep-chips">' + chips + "</div>";

    var makeRoot = $("#makeRoot");
    if (makeRoot) {
      makeRoot.addEventListener("click", function () {
        state.rootId = state.selectedId;
        renderLineage();
        renderResults();
        addLog("Akar lineage diubah ke " + lineageNodes[state.rootId].name + ".", "info");
        toast("Akar lineage diperbarui");
      });
    }
  }

  function selectNode(id) {
    if (!lineageNodes[id]) return;
    state.selectedId = id;
    renderLineage();
  }

  function renderResults() {
    var query = ($("#lineageSearch").value || "").trim().toLowerCase();
    var workspace = ($("#lineageWorkspace").value || "").trim().toLowerCase();
    var type = $("#lineageType").value;
    var items = Object.keys(lineageNodes).map(function (id) {
      return { id: id, node: lineageNodes[id] };
    }).filter(function (item) {
      var matchQuery = !query || item.node.name.toLowerCase().indexOf(query) !== -1;
      var matchWorkspace = !workspace || item.node.workspace.toLowerCase().indexOf(workspace) !== -1;
      var matchType = type === "all" || item.node.type === type;
      return matchQuery && matchWorkspace && matchType;
    });

    var box = $("#lineageResults");
    if (!items.length) {
      box.innerHTML = '<div class="empty" style="padding:18px 8px"><div class="empty-title">Tidak ada item</div><p class="empty-text">Ubah kata kunci atau filter workspace.</p></div>';
    } else {
      box.innerHTML = items.map(function (item) {
        return '<button class="result-item" type="button" data-id="' + item.id + '" aria-pressed="' + (item.id === state.rootId ? "true" : "false") + '">' +
          '<span class="result-name">' + escapeHtml(item.node.name) + "</span>" +
          '<span class="result-meta">' + escapeHtml(item.node.workspace) + "</span>" +
          '<span class="result-type chip chip-idle">' + escapeHtml(item.node.type) + "</span>" +
          "</button>";
      }).join("");
    }
    $("#lineageCount").textContent = items.length + " item";
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
    toast(name + " disiapkan pada tahap berikutnya");
  }

  function reportError(error) {
    var message = error && error.message ? error.message : String(error);
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
    if (value >= 1048576) return (value / 1048576).toFixed(1) + " MB";
    if (value >= 1024) return Math.round(value / 1024) + " KB";
    return value + " B";
  }

  function fileMeta(entry) {
    if (!entry || !entry.exists) return "Belum dibuat";
    var parts = [];
    if (entry.modified) parts.push(entry.modified);
    if (entry.size) parts.push(sizeText(entry.size));
    return parts.join(" \u00b7 ") || "Siap";
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
      $("#appVersion").textContent = "Versi " + data.version;
      $("#serverUrl").value = window.location.origin + "/";
      $("#serverMeta").textContent = "Data: " + data.data_dir + " \u00b7 Preferensi: " + data.settings.path;
      document.title = "BI Tools " + data.version + " - Metadata Power BI";
      addLog("BI Tools " + data.version + " siap di " + window.location.origin, "ok");
    }).catch(function (error) {
      addLog("Server lokal tidak menjawab: " + error.message, "error");
    });
  }

  function loadSettings() {
    if (!apiReady()) return;
    api().get("/api/settings").then(function (data) {
      renderSettings(data);
      state.ready = true;
    }).catch(function (error) {
      addLog("Preferensi tidak bisa dimuat: " + error.message, "error");
    });
  }

  function renderSettings(data) {
    state.settings = data;
    state.applying = true;
    $("#clientSecret").placeholder = data.auth.has_secret
      ? "Tersimpan - kosongkan bila tidak diubah"
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
      data.auth.complete ? "Lengkap" : (data.auth.has_secret ? "Belum lengkap" : "Belum diisi")
    );
    $("#connResult").textContent = data.auth.status;
    $("#syncMode").value = data.catalog.mode;
    $("#includePersonal").checked = data.catalog.include_personal;
    $("#showConsole").checked = data.ui.show_console;
    if (data.ui.theme !== state.theme) applyTheme(data.ui.theme, false);
    if (data.ui.motion !== state.motion) applyMotion(data.ui.motion, false);
    setSource(data.extraction.active_tab === "service" ? "service" : "desktop");
    state.applying = false;
  }

  function renderCatalogStatus(data) {
    setChip(
      $("#syncChip"),
      data.tone === "ok" ? "ok" : (data.tone === "error" ? "error" : "idle"),
      data.tone === "ok" ? "Tersinkron" : (data.tone === "error" ? "Bermasalah" : "Belum sinkron")
    );
    $("#syncStatus").textContent = data.text || "Belum ada katalog workspace tersimpan";
    $("#catalogCount").textContent = data.selectable
      ? fmtInt(data.selectable)
      : (data.total ? fmtInt(data.total) : "-");
    $("#catalogCount").title = data.total
      ? data.total + " workspace tersimpan"
      : "Belum ada katalog";
    $("#catalogSync").textContent = data.last_sync || "-";
  }

  function loadCatalogStatus() {
    if (!apiReady()) return;
    api().get("/api/catalog/status").then(renderCatalogStatus).catch(function (error) {
      addLog("Status katalog tidak bisa dibaca: " + error.message, "warn");
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
      addLog("Status output tidak bisa dibaca: " + error.message, "warn");
    });
  }

  function openOutput(which) {
    var entry = state.outputs && state.outputs[which];
    if (!entry || !entry.exists) {
      toast("Berkas belum dibuat");
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
      if (status === "error") setChip($("#outputState"), "error", "Gagal");
      else if (status === "cancelled") setChip($("#outputState"), "idle", "Dibatalkan");
      window.setTimeout(function () { $("#extractRun").hidden = true; }, 900);
    }
    if (status === "error") {
      var message = (snapshot && snapshot.error) || "Pekerjaan gagal.";
      addLog(message, "error");
      toast(message);
    } else if (status === "cancelled") {
      addLog("Pekerjaan dibatalkan.", "warn");
      toast("Pekerjaan dibatalkan");
    } else if (options.onDone) {
      options.onDone(snapshot || {});
    }
    loadCatalogStatus();
    loadSettings();
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
      pendingFeature(options.label || "Pekerjaan ini");
      return;
    }
    if (state.jobId) {
      toast("Pekerjaan lain masih berjalan");
      return;
    }
    state.jobLogCount = 0;
    setConsole(true);
    addLog((options.label || "Pekerjaan") + " dimulai.", "info");
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
          addLog("Log live terputus (" + error.message + "); beralih ke polling.", "warn");
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
      '<span class="helper">' + (isDir ? "folder" : "berkas") + "</span></button>";
  }

  function renderBrowse(data) {
    state.pickDir = data.path || "";
    $("#folderDialogPath").textContent = data.path || "Pilih drive";
    $("#folderPathInput").value = data.path || "";
    var choosingFile = state.pickKind === "file";
    $("#chooseFolder").textContent = choosingFile ? "Pilih berkas ini" : "Pilih folder ini";
    $("#chooseFolder").disabled = choosingFile ? !state.pickFile : !state.pickDir;
    $("#folderDialogTitle").textContent = choosingFile
      ? "Pilih berkas " + (state.pickExt || "")
      : "Pilih folder";
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
  }

  // -- ekstraksi metadata -------------------------------------------------
  var combos = {};

  function setupCombo(id, onChange) {
    var root = $("#" + id);
    if (!root) return null;
    var input = $(".combo-input", root);
    var toggle = $(".combo-toggle", root);
    var pop = $(".combo-pop", root);
    var list = $(".combo-list", root);
    if (!input || !pop || !list) return null;
    var combo = {
      id: id, root: root, input: input, toggle: toggle, pop: pop, list: list,
      options: [], visible: [], value: "", active: -1, onChange: onChange || null
    };
    combos[id] = combo;

    input.addEventListener("input", function () {
      combo.value = "";
      input.dataset.value = "";
      combo.active = -1;
      renderCombo(combo, input.value);
      openCombo(combo);
      if (combo.onChange) combo.onChange(null);
    });
    input.addEventListener("focus", function () {
      renderCombo(combo, "");
      openCombo(combo);
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (combo.pop.hidden) {
          renderCombo(combo, "");
          openCombo(combo);
        }
        moveCombo(combo, event.key === "ArrowDown" ? 1 : -1);
      } else if (event.key === "Enter") {
        if (!combo.pop.hidden && combo.active >= 0) {
          event.preventDefault();
          chooseCombo(combo, combo.visible[combo.active]);
        }
      } else if (event.key === "Escape") {
        closeCombo(combo);
        input.blur();
      }
    });
    input.addEventListener("blur", function () {
      window.setTimeout(function () {
        closeCombo(combo);
        if (combo.value) return;
        var typed = input.value.trim().toLowerCase();
        if (!typed) return;
        var match = combo.options.filter(function (item) {
          return item.label.toLowerCase() === typed;
        })[0];
        if (match) chooseCombo(combo, match);
        else input.value = "";
      }, 120);
    });
    if (toggle) {
      toggle.addEventListener("mousedown", function (event) {
        event.preventDefault();
        if (combo.pop.hidden) {
          renderCombo(combo, "");
          openCombo(combo);
          input.focus();
        } else {
          closeCombo(combo);
          input.blur();
        }
      });
    }
    document.addEventListener("click", function (event) {
      if (!root.contains(event.target)) closeCombo(combo);
    });
    return combo;
  }

  function openCombo(combo) {
    combo.pop.hidden = false;
    combo.input.setAttribute("aria-expanded", "true");
  }

  function closeCombo(combo) {
    combo.pop.hidden = true;
    combo.input.setAttribute("aria-expanded", "false");
  }

  function renderCombo(combo, query) {
    var text = String(query || "").trim().toLowerCase();
    combo.visible = combo.options.filter(function (item) {
      return !text || item.label.toLowerCase().indexOf(text) !== -1;
    });
    if (combo.active >= combo.visible.length) combo.active = combo.visible.length - 1;
    var html = combo.visible.map(function (item, index) {
      return '<div class="combo-item' + (index === combo.active ? " is-active" : "") +
        '" role="option" data-value="' + escapeHtml(item.value) +
        '" aria-selected="' + (String(item.value) === String(combo.value) ? "true" : "false") + '">' +
        escapeHtml(item.label) + "</div>";
    }).join("");
    if (!html) html = '<div class="combo-empty">Tidak ada item yang cocok.</div>';
    combo.list.innerHTML = html;
    $$(".combo-item", combo.list).forEach(function (node) {
      node.addEventListener("mousedown", function (event) {
        event.preventDefault();
        chooseCombo(combo, itemByValue(combo, node.dataset.value));
      });
    });
  }

  function itemByValue(combo, value) {
    for (var index = 0; index < combo.options.length; index += 1) {
      if (String(combo.options[index].value) === String(value)) return combo.options[index];
    }
    return null;
  }

  function moveCombo(combo, delta) {
    if (!combo.visible.length) return;
    combo.active = (combo.active + delta + combo.visible.length) % combo.visible.length;
    renderCombo(combo, "");
    var active = $(".combo-item.is-active", combo.list);
    if (active) active.scrollIntoView({ block: "nearest" });
  }

  function chooseCombo(combo, item) {
    if (!item) return;
    combo.value = item.value;
    combo.input.value = item.label;
    combo.input.dataset.value = item.value;
    closeCombo(combo);
    if (combo.onChange) combo.onChange(item);
  }

  function setComboOptions(id, options) {
    var combo = combos[id];
    if (!combo) return;
    combo.options = (options || []).map(function (item) {
      return { value: item.value, label: item.label, data: item.data };
    });
    combo.visible = combo.options.slice();
    if (combo.value && !itemByValue(combo, combo.value)) {
      combo.value = "";
      combo.input.value = "";
      combo.input.dataset.value = "";
    }
    renderCombo(combo, "");
  }

  function getComboValue(id) {
    return combos[id] ? combos[id].value : "";
  }

  function getComboItem(id) {
    var combo = combos[id];
    return combo ? itemByValue(combo, combo.value) : null;
  }

  function loadInstances() {
    if (!apiReady()) return Promise.resolve();
    return api().get("/api/metadata/instances").then(function (data) {
      state.instances = data.instances || [];
      var select = $("#desktopInstance");
      var html = ['<option value="">' +
        (state.instances.length ? "Pilih instance…" : "Tidak ada instance terbuka") +
        "</option>"];
      state.instances.forEach(function (item) {
        html.push('<option value="' + item.port + '">' + escapeHtml(item.label) + "</option>");
      });
      select.innerHTML = html.join("");
      if (state.instances.length === 1) select.value = String(state.instances[0].port);
      $("#instanceHint").textContent = data.hint || "";
      renderModelAvailability();
      return data;
    }).catch(function (error) {
      addLog("Instance Desktop tidak bisa dibaca: " + error.message, "warn");
    });
  }

  function renderModelAvailability() {
    var scope = $("#scope").value;
    var supportsModel = !state.pbix || state.pbix.has_local_model;
    var needed = scope !== "report" && supportsModel;
    $("#desktopInstance").disabled = !needed;
    $("#reloadDesktop").disabled = !needed;
    if (scope === "report") {
      $("#instanceHint").textContent = "Cakupan report saja: instance Power BI Desktop tidak dipakai.";
    } else if (state.pbix && !state.pbix.has_local_model) {
      $("#instanceHint").textContent = "File ini live connection; instance Power BI Desktop tidak dipakai.";
    } else if (!state.instances.length) {
      $("#instanceHint").textContent = "Tidak ada instance Power BI Desktop terbuka. Buka file .pbix lalu Muat ulang.";
    }
  }

  function loadWorkspaces() {
    if (!apiReady()) return Promise.resolve();
    return api().get("/api/metadata/workspaces").then(function (data) {
      state.workspaces = data.workspaces || [];
      var options = state.workspaces.map(function (item) {
        return { value: item.id, label: item.label, data: item };
      });
      setComboOptions("modelWorkspaceCombo", options);
      setComboOptions("reportWorkspaceCombo", options);
      $("#workspaceHint").textContent = data.hint ||
        "Ketik nama workspace untuk memfilter, atau buka daftar.";
      return data;
    }).catch(function (error) {
      addLog("Katalog workspace tidak bisa dibaca: " + error.message, "error");
    });
  }

  function loadModelContents() {
    var workspaceId = getComboValue("modelWorkspaceCombo");
    if (!workspaceId || !apiReady()) return Promise.resolve();
    $("#workspaceHint").textContent = "Memuat dataset workspace model…";
    return api().get(
      "/api/metadata/workspaces/" + encodeURIComponent(workspaceId) +
      "/contents?datasets=true&reports=false"
    ).then(function (data) {
      state.datasets = data.datasets || [];
      $("#xmlaEndpoint").value = (data.workspace && data.workspace.endpoint) || "";
      setComboOptions("catalogCombo", state.datasets.map(function (item) {
        return { value: item.name, label: item.name, data: item };
      }));
      $("#workspaceHint").textContent = state.datasets.length
        ? "Endpoint XMLA diturunkan dari workspace model; pilih dataset untuk catalog."
        : "Workspace model ini tidak punya dataset yang bisa dibaca.";
      return data;
    }).catch(function (error) {
      $("#workspaceHint").textContent = error.message;
      addLog(error.message, "error");
    });
  }

  function loadReportContents() {
    var workspaceId = getComboValue("reportWorkspaceCombo");
    if (!workspaceId || !apiReady()) return Promise.resolve();
    $("#reportHint").textContent = "Memuat report workspace…";
    return api().get(
      "/api/metadata/workspaces/" + encodeURIComponent(workspaceId) +
      "/contents?datasets=false&reports=true"
    ).then(function (data) {
      state.reports = data.reports || [];
      setComboOptions("reportCombo", state.reports.map(function (item) {
        return { value: item.id, label: item.label, data: item };
      }));
      $("#reportHint").textContent = state.reports.length
        ? "Report paginated (RDL) ditandai dan tidak bisa diekstrak."
        : "Workspace report ini tidak punya report yang bisa diekstrak.";
      return data;
    }).catch(function (error) {
      $("#reportHint").textContent = error.message;
      addLog(error.message, "error");
    });
  }

  function applyReportDefaults(report) {
    if (report.is_paginated) {
      $("#reportHint").textContent =
        "Report paginated (RDL) tidak didukung; pilih report Power BI biasa.";
      return;
    }
    var dataset = null;
    state.datasets.forEach(function (item) {
      if (String(item.id) === String(report.dataset_id)) dataset = item;
    });
    if (dataset) {
      $("#reportHint").textContent =
        "Report memakai dataset " + dataset.name +
        ". Catalog model dipilih terpisah dan boleh berbeda workspace.";
    } else if (report.dataset_id) {
      $("#reportHint").textContent =
        "Report memakai dataset di workspace lain; pilih catalog model secara terpisah.";
    } else {
      $("#reportHint").textContent = "";
    }
  }

  function refreshPbix() {
    var path = $("#pbixPath").value.trim();
    if (!apiReady()) return;
    if (!path) {
      state.pbix = null;
      $("#pbixKind").textContent = "Pilih file .pbix sumber.";
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
      $("#pbixKind").textContent = error.message;
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
      var modelItem = getComboItem("modelWorkspaceCombo");
      var reportWorkspace = getComboItem("reportWorkspaceCombo");
      var reportItem = getComboItem("reportCombo");
      var report = reportItem ? reportItem.data : null;
      payload.model_workspace_id = getComboValue("modelWorkspaceCombo");
      payload.model_workspace_name = modelItem ? modelItem.data.name : "";
      payload.report_workspace_id = getComboValue("reportWorkspaceCombo");
      payload.report_workspace_name = reportWorkspace
        ? reportWorkspace.data.name
        : "";
      payload.endpoint = $("#xmlaEndpoint").value.trim();
      payload.report_id = getComboValue("reportCombo");
      payload.report_name = report ? report.name : "";
      payload.report_type = report ? report.report_type : "";
      payload.dataset_id = report ? report.dataset_id : "";
      payload.catalog = getComboValue("catalogCombo");
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
      setChip($("#outputState"), "idle", "Tidak ada hasil");
      return;
    }
    setChip($("#outputState"), "ok", "Selesai");
    $("#extractDone").hidden = false;
    var notes = [];
    if (report) notes.push((report.pages || 0) + " halaman");
    if (model) notes.push((model.tables || 0) + " tabel");
    $("#extractDoneText").textContent = notes.join(" · ") ||
      "Workbook tersimpan di folder tujuan.";
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
    if (result.model_error) addLog("Catatan: " + result.model_error, "warn");
  }

  function runExtraction() {
    if (!apiReady()) return;
    if (state.jobId) {
      toast("Pekerjaan lain masih berjalan");
      return;
    }
    var payload = buildMetadataPayload();
    $("#extractDone").hidden = true;
    $("#extractRun").hidden = false;
    $("#extractBar").style.width = "6%";
    $("#extractRunPct").textContent = "";
    $("#extractRunLabel").textContent = "Menyiapkan ekstraksi…";
    setChip($("#outputState"), "warn", "Berjalan");
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
      label: "Ekstraksi metadata",
      button: $("#runExtract"),
      onDone: function (snapshot) {
        $("#extractBar").style.width = "100%";
        $("#extractRunPct").textContent = "100%";
        renderExtractResult(snapshot.result || {});
        loadOutputs();
      }
    });
  }

  function init() {
    applyTheme(state.theme, false);
    applyMotion(state.motion, false);
    setSource(state.source);

    $$(".nav-item").forEach(function (button) {
      button.addEventListener("click", function () {
        showView(button.dataset.view);
      });
    });

    $$(".theme-card").forEach(function (card) {
      card.addEventListener("click", function () {
        applyTheme(card.dataset.theme, true);
      });
      card.addEventListener("keydown", function (event) {
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
          event.preventDefault();
          var next = state.theme === "dark" ? "light" : "dark";
          applyTheme(next, true);
          var target = $$(".theme-card").filter(function (item) { return item.dataset.theme === next; })[0];
          if (target) target.focus();
        }
      });
    });

    $("#motionToggle").addEventListener("change", function (event) {
      applyMotion(event.target.checked, true);
    });

    $("#consoleToggle").addEventListener("click", function () {
      setConsole($("#consoleBody").hidden);
    });

    $("#clearLog").addEventListener("click", function () {
      state.logs = [];
      renderLog();
      toast("Log konsol dibersihkan");
    });

    $("#srcBtnDesktop").addEventListener("click", function () { setSource("desktop"); });
    $("#srcBtnService").addEventListener("click", function () { setSource("service"); });

    $("#reloadDesktop").addEventListener("click", function () {
      loadInstances().then(function () { toast("Daftar instance diperbarui"); });
    });

    $("#reloadWorkspaces").addEventListener("click", function () {
      loadWorkspaces().then(function () {
        if (getComboValue("modelWorkspaceCombo")) loadModelContents();
        if (getComboValue("reportWorkspaceCombo")) loadReportContents();
        toast("Katalog workspace dimuat");
      });
    });

    $("#reloadReport").addEventListener("click", function () {
      if (!getComboValue("reportWorkspaceCombo")) {
        toast("Pilih workspace report lebih dulu");
        return;
      }
      loadReportContents().then(function () { toast("Daftar report dimuat"); });
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

    setupCombo("modelWorkspaceCombo", function (item) {
      if (!item) {
        $("#xmlaEndpoint").value = "";
        setComboOptions("catalogCombo", []);
        $("#workspaceHint").textContent = "";
        return;
      }
      loadModelContents();
    });

    setupCombo("reportWorkspaceCombo", function (item) {
      if (!item) {
        setComboOptions("reportCombo", []);
        $("#reportHint").textContent = "";
        return;
      }
      loadReportContents();
    });

    setupCombo("catalogCombo", function (item) {
      if (item && item.data) {
        $("#workspaceHint").textContent =
          "Catalog " + item.data.name + " dipakai dari workspace model ini.";
      }
    });
    setupCombo("reportCombo", function (item) {
      if (item && item.data) applyReportDefaults(item.data);
    });

    $("#runExtract").addEventListener("click", runExtraction);
    $("#runTsd").addEventListener("click", function () { pendingFeature("Generate TSD"); });

    $("#goTsd").addEventListener("click", function () { showView("tsd"); });
    $("#sideToTsd").addEventListener("click", function () { showView("tsd"); });
    $("#doneToTsd").addEventListener("click", function () { showView("tsd"); });

    $("#openReport").addEventListener("click", function () { openOutput("report"); });
    $("#openModel").addEventListener("click", function () { openOutput("model"); });
    $("#openFolder").addEventListener("click", function () { revealOutputFolder(); });
    $("#openTsd").addEventListener("click", function () { pendingFeature("Pratinjau TSD"); });
    $("#previewOpenTsd").addEventListener("click", function () { pendingFeature("Pratinjau TSD"); });
    $("#pickFolder").addEventListener("click", function () {
      openFolderPicker($("#outFolder").value, function (folder) {
        savePreference("extraction", { out_dir: folder }).then(function () {
          loadOutputs();
          toast("Folder tujuan disimpan");
        });
      });
    });

    $("#loadContext").addEventListener("click", function () { pendingFeature("Konteks manual TSD"); });
    $("#saveContext").addEventListener("click", function () { pendingFeature("Konteks manual TSD"); });
    $("#editContext").addEventListener("click", function () { pendingFeature("Editor JSON TSD"); });

    $("#runAnalyze").addEventListener("click", function () { pendingFeature("Analisa semantic model"); });
    $("#analyzeFromEmpty").addEventListener("click", function () { pendingFeature("Analisa semantic model"); });
    $("#reloadWsAnalisa").addEventListener("click", function () {
      addLog("Daftar workspace untuk analisa dimuat ulang.", "info");
      toast("Workspace dimuat ulang");
    });

    $("#searchAnalyze").addEventListener("input", function () {
      if (state.analyzed) renderAnalysis();
    });
    $("#typeAnalyze").addEventListener("change", function (event) {
      state.typeFilter = event.target.value;
      if (state.analyzed) renderAnalysis();
    });
    $("#unusedOnly").addEventListener("change", function (event) {
      state.unusedOnly = event.target.checked;
      if (state.analyzed) renderAnalysis();
    });
    $("#expandRows").addEventListener("click", function () {
      if (!state.analyzed) {
        toast("Jalankan analisa lebih dulu");
        return;
      }
      state.openGroups = {};
      groupIdsFor(state.analyzeTab).forEach(function (id) { state.openGroups[id] = true; });
      renderAnalysis();
    });
    $("#collapseRows").addEventListener("click", function () {
      if (!state.analyzed) {
        toast("Jalankan analisa lebih dulu");
        return;
      }
      state.openGroups = {};
      renderAnalysis();
    });
    $("#exportXlsx").addEventListener("click", function () { pendingFeature("Ekspor analisa"); });

    $$("#analyzeTabs [role='tab']").forEach(function (tab) {
      tab.addEventListener("click", function () {
        setAnalysisTab(tab.dataset.analyzeTab);
      });
    });
    $("#relViewSwitch").addEventListener("click", function (event) {
      var button = event.target.closest("[data-rel-view]");
      if (!button) return;
      state.relView = button.getAttribute("data-rel-view") === "table" ? "table" : "graph";
      syncRelViewSwitch();
      if (state.analyzed) renderAnalysis();
    });
    $("#relGraphSvg").addEventListener("click", function (event) {
      var node = event.target.closest("[data-table]");
      if (node) {
        state.relSelected = "tbl:" + node.getAttribute("data-table");
        renderRelationshipGraph();
        return;
      }
      var edge = event.target.closest("[data-pair]");
      if (edge) {
        state.relSelected = "pair:" + edge.getAttribute("data-pair");
        renderRelationshipGraph();
      }
    });
    $("#relGraphSvg").addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      var node = event.target.closest("[data-table]");
      if (!node) return;
      event.preventDefault();
      var name = node.getAttribute("data-table");
      state.relSelected = "tbl:" + name;
      renderRelationshipGraph();
      var next = $("#relGraphSvg [data-table='" + name + "']");
      if (next) next.focus();
    });
    $("#relGraphSide").addEventListener("click", function (event) {
      var back = event.target.closest("[data-rel-table]");
      if (back) {
        var table = back.getAttribute("data-rel-table");
        state.relSelected = "tbl:" + table;
        renderRelationshipGraph();
        var node = $("#relGraphSvg [data-table='" + table + "']");
        if (node) node.focus();
        return;
      }
      var item = event.target.closest("[data-rel-pair]");
      if (!item) return;
      var key = item.getAttribute("data-rel-pair");
      state.relSelected = "pair:" + key;
      renderRelationshipGraph();
      var next = $("#relGraphSide [data-rel-pair='" + key + "']");
      if (next) next.focus();
    });
    $("#analyzeTabs").addEventListener("keydown", function (event) {
      var keys = ["ArrowRight", "ArrowLeft", "Home", "End"];
      if (keys.indexOf(event.key) === -1) return;
      var tabs = $$("#analyzeTabs [role='tab']:not([disabled])");
      if (!tabs.length) return;
      var index = tabs.indexOf(document.activeElement);
      if (index === -1) index = 0;
      event.preventDefault();
      if (event.key === "ArrowRight") index = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") index = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") index = 0;
      if (event.key === "End") index = tabs.length - 1;
      tabs[index].focus();
      setAnalysisTab(tabs[index].dataset.analyzeTab);
    });

    $("#analyzeBody").addEventListener("click", function (event) {
      var toggle = event.target.closest("[data-group]");
      if (toggle) {
        event.preventDefault();
        var key = toggle.getAttribute("data-group");
        state.openGroups[key] = !state.openGroups[key];
        renderAnalysis();
        return;
      }
      var row = event.target.closest("tr[data-id]");
      if (!row) return;
      $$("tr.selected", $("#analyzeBody")).forEach(function (item) { item.classList.remove("selected"); });
      row.classList.add("selected");
    });
    $("#analyzeBody").addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      var row = event.target.closest("tr[data-id]");
      if (!row) return;
      event.preventDefault();
      $$("tr.selected", $("#analyzeBody")).forEach(function (item) { item.classList.remove("selected"); });
      row.classList.add("selected");
    });

    $("#dirUpstream").addEventListener("click", function () {
      state.direction = "upstream";
      $("#dirUpstream").setAttribute("aria-pressed", "true");
      $("#dirDownstream").setAttribute("aria-pressed", "false");
      renderLineage();
    });
    $("#dirDownstream").addEventListener("click", function () {
      state.direction = "downstream";
      $("#dirUpstream").setAttribute("aria-pressed", "false");
      $("#dirDownstream").setAttribute("aria-pressed", "true");
      renderLineage();
    });
    $("#depthMinus").addEventListener("click", function () {
      state.depth = Math.max(1, state.depth - 1);
      renderLineage();
    });
    $("#depthPlus").addEventListener("click", function () {
      state.depth = Math.min(3, state.depth + 1);
      renderLineage();
    });
    $("#visualLineage").addEventListener("click", function () {
      state.visual = !state.visual;
      $("#lineageLayout").classList.toggle("is-visual", state.visual);
      $("#visualLineage").setAttribute("aria-pressed", String(state.visual));
      toast(state.visual ? "Mode visual lineage aktif" : "Mode visual lineage nonaktif");
    });
    $("#exportCsv").addEventListener("click", function () { pendingFeature("Ekspor lineage"); });

    $("#lineageSearchBtn").addEventListener("click", function () {
      renderResults();
      addLog("Pencarian lineage: " + ($("#lineageSearch").value || "(kosong)"), "info");
    });
    $("#lineageSearch").addEventListener("input", renderResults);
    $("#lineageWorkspace").addEventListener("input", renderResults);
    $("#lineageType").addEventListener("change", renderResults);
    $("#lineageResults").addEventListener("click", function (event) {
      var item = event.target.closest(".result-item");
      if (!item) return;
      state.rootId = item.dataset.id;
      state.selectedId = item.dataset.id;
      renderLineage();
      renderResults();
      addLog("Item lineage dipilih: " + lineageNodes[state.rootId].name, "info");
    });
    $("#lineageLayer").addEventListener("click", function (event) {
      var node = event.target.closest(".node");
      if (node) selectNode(node.dataset.id);
    });
    $("#lineageLayer").addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      var node = event.target.closest(".node");
      if (!node) return;
      event.preventDefault();
      selectNode(node.dataset.id);
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
        label: "Tes koneksi Power BI",
        button: $("#testConn"),
        onDone: function (snapshot) {
          var tokens = (snapshot.result && snapshot.result.tokens) || {};
          var parts = [];
          Object.keys(tokens).forEach(function (name) {
            parts.push((tokens[name].ok ? "OK " : "GAGAL ") + name);
          });
          $("#connResult").textContent = parts.length
            ? "Hasil tes: " + parts.join(" - ")
            : "Tes selesai tanpa hasil token.";
          toast(parts.join(" - ") || "Tes selesai");
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
        addLog("Kredensial dan RLS default disimpan.", "ok");
        toast("Pengaturan disimpan");
      }).catch(reportError);
    });

    $("#syncCatalog").addEventListener("click", function () {
      startJob({
        path: "/api/catalog/sync",
        body: {},
        label: "Sinkronisasi katalog workspace",
        button: $("#syncCatalog"),
        onDone: function (snapshot) {
          var result = snapshot.result || {};
          toast("Katalog: " + (result.workspace_count || 0) + " workspace");
        }
      });
    });

    $("#scanLineage").addEventListener("click", function () {
      startJob({
        path: "/api/catalog/scan",
        body: { full: $("#fullScan").checked },
        label: "Scan lineage Power BI",
        button: $("#scanLineage"),
        onDone: function (snapshot) {
          var result = snapshot.result || {};
          toast("Lineage: " + (result.workspace_count || 0) + " workspace, " +
            (result.node_count || 0) + " node");
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
        toast("Path database disimpan");
      });
    });
    $("#pickDb").addEventListener("click", function () {
      openFolderPicker(parentDir($("#dbPath").value), function (folder) {
        var target = folder.replace(/[\\/]+$/, "") + "\\bi_tools.db";
        $("#dbPath").value = target;
        savePreference("paths", { lineage_db: target }).then(function (data) {
          if (data) toast("Path database disimpan");
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
      if (!window.confirm("Hentikan server lokal? Tab ini tidak bisa dipakai lagi sampai aplikasi dijalankan ulang.")) return;
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
          toast("Alamat server disalin");
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

    $("#partitionTable").addEventListener("change", function (event) {
      if (state.partitionBusy) {
        event.target.value = state.partitionTable;
        return;
      }
      state.partitionTable = event.target.value;
      state.partitionSelected = {};
      state.partitionDetail = null;
      loadPartitions();
    });
    $("#loadPartitions").addEventListener("click", loadPartitions);
    $("#reloadPartitions").addEventListener("click", loadPartitions);
    $("#partitionSearch").addEventListener("input", function () {
      if (!state.partitionBusy) renderPartitions();
    });
    $("#partitionFilter").addEventListener("change", function (event) {
      state.partitionFilter = event.target.value;
      if (!state.partitionBusy) renderPartitions();
    });
    $("#exportPartitions").addEventListener("click", function () {
      pendingFeature("Ekspor CSV partisi");
    });
    $("#partitionWorkspace").addEventListener("change", function () {
      addLog("Workspace partisi diubah.", "info");
      toast("Workspace diperbarui");
    });
    $("#partitionModel").addEventListener("change", function () {
      addLog("Semantic model partisi diubah.", "info");
      toast("Model diperbarui");
    });

    $("#partitionTableWrap").addEventListener("change", function (event) {
      var target = event.target;
      if (target.id === "partitionSelectAll") {
        filteredPartitions().forEach(function (partition) {
          state.partitionSelected[partition.name] = target.checked;
        });
        renderPartitions();
        return;
      }
      if (target.classList.contains("partition-check") && target.getAttribute("data-partition-check")) {
        var name = target.getAttribute("data-partition-check");
        if (target.checked) state.partitionSelected[name] = true;
        else delete state.partitionSelected[name];
        syncPartitionSelection();
      }
    });

    function selectPartitionRow(row) {
      var name = row.getAttribute("data-partition");
      state.partitionDetail = name;
      renderPartitions();
      var next = $("#partitionBody tr[data-partition='" + name + "']");
      if (next) next.focus();
    }

    $("#partitionBody").addEventListener("click", function (event) {
      if (event.target.closest("input")) return;
      var row = event.target.closest("tr[data-partition]");
      if (row) selectPartitionRow(row);
    });
    $("#partitionBody").addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (event.target.closest("input")) return;
      var row = event.target.closest("tr[data-partition]");
      if (!row) return;
      event.preventDefault();
      selectPartitionRow(row);
    });

    $("#partitionDetail").addEventListener("click", function (event) {
      if (event.target.closest("#processPartitionDetail")) {
        openPartitionDialog([state.partitionDetail]);
        return;
      }
      if (event.target.closest("#copyPartitionSource")) {
        var partition = partitionInfo().partitions.filter(function (item) {
          return item.name === state.partitionDetail;
        })[0];
        if (!partition) return;
        var text = partitionExpression(state.partitionTable, partition);
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).catch(function () {});
        }
        toast("Ekspresi sumber disalin");
      }
    });

    $("#processSelectedPartitions").addEventListener("click", function () {
      var names = selectedPartitionNames();
      if (names.length) openPartitionDialog(names);
    });
    $("#closePartitionDialog").addEventListener("click", closePartitionDialog);
    $("#cancelPartitionProcess").addEventListener("click", closePartitionDialog);
    $("#partitionMode").addEventListener("change", updatePartitionModeHelp);
    $("#partitionChecklist").addEventListener("change", function () {
      var any = $$(".partition-dialog-check", $("#partitionChecklist")).some(function (input) {
        return input.checked;
      });
      $("#runPartitionProcess").disabled = !any;
    });
    $("#runPartitionProcess").addEventListener("click", function () {
      var names = $$(".partition-dialog-check", $("#partitionChecklist")).filter(function (input) {
        return input.checked;
      }).map(function (input) {
        return input.value;
      });
      if (!names.length) {
        toast("Pilih minimal satu partisi");
        return;
      }
      var mode = $("#partitionMode").value;
      closePartitionDialog();
      processPartitions(names, mode);
    });
    $("#partitionDialog").addEventListener("close", function () {
      var trigger = state.partitionDialogTrigger;
      if (trigger && document.contains(trigger)) trigger.focus();
    });
    $("#partitionDialog").addEventListener("click", function (event) {
      if (event.target === event.currentTarget) closePartitionDialog();
    });

    renderLog();
    renderResults();
    renderLineage();
    renderAnalysis();
    renderPartitions();
  }

  init();

  bootstrap();
})();
