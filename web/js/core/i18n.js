// Terjemahan dasar. `locales.js` (classic script) harus dimuat sebelum modul ini.

export const i18n = window.BIToolsI18n || null;

export function t(text) {
  return i18n ? i18n.translate(text) : text;
}

export function tr(text) {
  return i18n && i18n.translateServer ? i18n.translateServer(text) : text;
}

export function currentLanguage() {
  return i18n && i18n.language === "id" ? "id" : "en";
}
