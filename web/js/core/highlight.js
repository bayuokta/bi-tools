// Syntax highlight untuk DAX (Prism), JSON/TMSL (Prism), dan TMDL (grammar
// lexical kecil). Tidak mengubah teks; fallback ke escape HTML bila Prism gagal.

import { escapeHtml } from "./dom.js";

function prism() {
  return window.Prism || null;
}

function grammar(language) {
  var instance = prism();
  if (!instance || !instance.languages) return null;
  return instance.languages[language] || null;
}

function highlightWith(text, language) {
  var instance = prism();
  var lang = grammar(language);
  if (!instance || !lang) return escapeHtml(text);
  try {
    return instance.highlight(text, lang, language);
  } catch (error) {
    return escapeHtml(text);
  }
}

export function highlightCode(text, language) {
  var value = String(text == null ? "" : text);
  if (language === "tmdl") {
    // TMDL is indentation-based; highlight per line so `^` patterns work and
    // spans never cross line boundaries.
    return value.split("\n").map(function (line) {
      return highlightWith(line, "tmdl");
    }).join("\n");
  }
  return highlightWith(value, language || "dax");
}

export function highlightLine(text, language) {
  return highlightWith(String(text == null ? "" : text), language || "dax");
}

export function compareLanguage(options) {
  return options && options.tmsl ? "json" : "tmdl";
}

// Grammar TMDL: keyword/property/string/comment/number. Ini lexical, bukan
// parser semantik; definisi asli dari TOM tetap tidak diubah.
(function registerTmdl() {
  var instance = prism();
  if (!instance || !instance.languages || instance.languages.tmdl) return;
  instance.languages.tmdl = {
    comment: [
      { pattern: /\/\/.*/, greedy: true },
      { pattern: /\/\*[\s\S]*?(?:\*\/|$)/, greedy: true }
    ],
    string: {
      pattern: /'(?:''|[^'])*'|"(?:[^"\\]|\\.)*"/,
      greedy: true
    },
    changed: {
      pattern: /\bchangedProperty\b[^\n]*/,
      alias: "changed"
    },
    property: {
      pattern: /^[ \t]*[A-Za-z_][\w.]*(?=\s*:)/,
      alias: "property"
    },
    keyword: {
      pattern: /^[ \t]*(?:table|column|measure|relationship|role|expression|partition|hierarchy|calculationGroup|calculationItem|perspective|culture|model|dataSource|annotation|level|formatStringDefinition)\b/,
      alias: "keyword"
    },
    number: /\b\d+(?:\.\d+)?\b/,
    boolean: /\b(?:true|false)\b/i,
    operator: /[:=]/
  };
})();
