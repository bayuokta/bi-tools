// Komponen combo: <select> asli disembunyikan, tombol + popup bersama dipakai.
// Semua <select> di halaman di-enhance lewat enhanceAllSelects(), kecuali yang
// berada di dalam <dialog>.

import { $, $$, escapeHtml } from "./dom.js";
import { t } from "./i18n.js";

var comboState = { select: null, trigger: null, options: [], active: -1 };
var selectData = {};

function comboLabelText(select) {
  var option = select.options[select.selectedIndex];
  return option ? option.textContent : "";
}

export function refreshCombo(select) {
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

export function enhanceAllSelects(root) {
  $$("select", root || document).forEach(enhanceSelect);
}

export function initComboEvents() {
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

export function setSelectOptions(id, items, placeholder) {
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

export function getSelectValue(id) {
  var select = $("#" + id);
  return select ? select.value : "";
}

export function setSelectValue(id, value) {
  var select = $("#" + id);
  if (!select) return;
  select.value = String(value == null ? "" : value);
  refreshCombo(select);
}

export function getSelectItem(id) {
  var select = $("#" + id);
  if (!select) return null;
  return (selectData[id] || []).filter(function (item) {
    return String(item.value) === String(select.value);
  })[0] || null;
}
