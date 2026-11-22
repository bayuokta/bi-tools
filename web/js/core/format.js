// Utilitas format angka dan ukuran. Bahasa mengikuti preferensi UI.

import { currentLanguage, t } from "./i18n.js";

export function decimalText(text) {
  return currentLanguage() === "id" ? String(text).replace(".", ",") : String(text);
}

export function fmtInt(value) {
  return Number(value).toLocaleString(currentLanguage() === "id" ? "id-ID" : "en-US");
}

export function sizeText(bytes) {
  var value = Number(bytes || 0);
  if (!value) return "";
  if (value >= 1048576) return decimalText((value / 1048576).toFixed(1)) + " MB";
  if (value >= 1024) return Math.round(value / 1024) + " KB";
  return value + " B";
}

export function fileMeta(entry) {
  if (!entry || !entry.exists) return t("Not created");
  var parts = [];
  if (entry.modified) parts.push(entry.modified);
  if (entry.size) parts.push(sizeText(entry.size));
  return parts.join(" \u00b7 ") || t("Ready");
}
