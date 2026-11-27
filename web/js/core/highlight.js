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

// Grammar M (Power Query): lexical kecil dengan token yang sama seperti DAX
// agar warna memakai aturan .token yang sudah ada. Bukan parser semantik.
(function registerM() {
  var instance = prism();
  if (!instance || !instance.languages || instance.languages.m) return;
  instance.languages.m = {
    comment: [
      { pattern: /\/\/[^\n]*/, greedy: true },
      { pattern: /\/\*[\s\S]*?(?:\*\/|$)/, greedy: true }
    ],
    string: {
      pattern: /"(?:[^"]|"")*"/,
      greedy: true
    },
    "quoted-identifier": {
      pattern: /#"(?:[^"]|"")*"/,
      alias: "property"
    },
    "hash-literal": {
      pattern: /#(?:date|datetime|datetimezone|duration|time|table|shared|sections|binary|infinity|nan)\b/i,
      alias: "constant"
    },
    function: /\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b/,
    type: {
      pattern: /\b(?:any|anynonnull|binary|date|datetime|datetimezone|duration|function|list|logical|none|null|number|record|table|text|time|type)\b/i,
      alias: "constant"
    },
    keyword: /\b(?:and|as|each|else|error|if|in|is|let|meta|not|or|otherwise|section|then|try)\b/i,
    boolean: /\b(?:true|false)\b/i,
    number: /\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/,
    operator: /[=<>+\-*\/&?@]/,
    punctuation: /[()\[\]{},;]/
  };
})();
