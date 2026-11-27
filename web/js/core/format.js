// Number and size formatting (English).


export function decimalText(text) {
  return String(text);
}

export function fmtInt(value) {
  return Number(value).toLocaleString("en-US");
}

export function sizeText(bytes) {
  var value = Number(bytes || 0);
  if (!value) return "";
  if (value >= 1048576) return decimalText((value / 1048576).toFixed(1)) + " MB";
  if (value >= 1024) return Math.round(value / 1024) + " KB";
  return value + " B";
}

export function fileMeta(entry) {
  if (!entry || !entry.exists) return "Not created";
  var parts = [];
  if (entry.modified) parts.push(entry.modified);
  if (entry.size) parts.push(sizeText(entry.size));
  return parts.join(" \u00b7 ") || "Ready";
}
