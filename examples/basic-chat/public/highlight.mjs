// A small syntax highlighter for the code blocks in chat answers.
//
// It is deliberately simple: an ordered list of patterns per language, tried at each position.
// Two properties matter more than prettiness, and both are tested:
//   1. Lossless. The tokens always join back into exactly the code that went in, so what is
//      shown and what the Copy button copies can never disagree.
//   2. Linear. Every pattern consumes everything it scans (an unclosed string or comment runs
//      to its natural end), so odd or hostile code cannot make the page slow.
// Output is data ([type, text] pairs). The renderer turns it into text nodes, never HTML.

export const MAX_HIGHLIGHT_CHARS = 50_000;

const words = (list) => new RegExp(`\\b(?:${list.join("|")})\\b`);
const rule = (type, re) => ({ type, re: new RegExp(re.source, re.flags.replace("y", "") + "y") });

const DQ = /"(?:[^"\\\n]|\\.)*"?/;
const SQ = /'(?:[^'\\\n]|\\.)*'?/;
const NUMBER = /\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?n?/;
const HEX = /0[xX][\da-fA-F_]+/;
const CALL = /[A-Za-z_$][\w$]*(?=\s*\()/;

const LANGUAGES = {
  js: [
    rule("comment", /\/\/[^\n]*/), rule("comment", /\/\*[\s\S]*?(?:\*\/|$)/),
    rule("string", DQ), rule("string", SQ), rule("string", /`(?:[^`\\]|\\[\s\S])*`?/),
    rule("number", HEX), rule("number", NUMBER),
    rule("literal", words(["true", "false", "null", "undefined", "NaN", "Infinity"])),
    rule("keyword", words(["const", "let", "var", "function", "return", "if", "else", "for", "while", "do", "switch", "case", "break",
      "continue", "new", "class", "extends", "import", "export", "from", "default", "async", "await", "try", "catch", "finally", "throw",
      "typeof", "instanceof", "in", "of", "yield", "static", "this", "super", "interface", "type", "enum", "implements", "public",
      "private", "protected", "readonly", "void", "delete", "as"])),
    rule("function", CALL),
  ],
  json: [
    rule("property", /"(?:[^"\\\n]|\\.)*"(?=\s*:)/), rule("string", DQ),
    rule("number", /-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/), rule("literal", words(["true", "false", "null"])),
  ],
  python: [
    rule("comment", /#[^\n]*/),
    rule("string", /(?:[rRbBfFuU]{1,2})?"""[\s\S]*?(?:"""|$)/), rule("string", /(?:[rRbBfFuU]{1,2})?'''[\s\S]*?(?:'''|$)/),
    rule("string", /(?:[rRbBfFuU]{1,2})?"(?:[^"\\\n]|\\.)*"?/), rule("string", /(?:[rRbBfFuU]{1,2})?'(?:[^'\\\n]|\\.)*'?/),
    rule("function", /@[\w.]+/), rule("number", HEX), rule("number", NUMBER),
    rule("literal", words(["True", "False", "None"])),
    rule("keyword", words(["def", "class", "return", "if", "elif", "else", "for", "while", "in", "not", "and", "or", "is", "import",
      "from", "as", "with", "try", "except", "finally", "raise", "lambda", "yield", "pass", "break", "continue", "global", "nonlocal",
      "assert", "del", "async", "await", "match", "case"])),
    rule("function", CALL),
  ],
  bash: [
    rule("comment", /(?:^|(?<=\s))#[^\n]*/),
    rule("string", /"(?:[^"\\]|\\[\s\S])*"?/), rule("string", /'[^']*'?/),
    rule("variable", /\$(?:\w+|\{[^}\n]*\}?|[@#?$!*-])/),
    rule("attr", /(?<=\s)--?[A-Za-z][\w-]*/),
    rule("keyword", words(["if", "then", "else", "elif", "fi", "for", "while", "do", "done", "case", "esac", "in", "function", "return",
      "export", "local", "set", "unset", "source"])),
    rule("number", /\d+/),
  ],
  css: [
    rule("comment", /\/\*[\s\S]*?(?:\*\/|$)/), rule("string", DQ), rule("string", SQ),
    rule("keyword", /@[\w-]+/), rule("number", /#[\da-fA-F]{3,8}\b/),
    rule("number", /-?\d*\.?\d+(?:%|[a-zA-Z]+)?/), rule("property", /[A-Za-z-][\w-]{0,80}(?=\s*:)/),
  ],
  sql: [
    rule("comment", /--[^\n]*/), rule("comment", /\/\*[\s\S]*?(?:\*\/|$)/), rule("string", /'(?:[^']|'')*'?/),
    rule("number", NUMBER),
    rule("literal", /\b(?:true|false|null)\b/i),
    rule("keyword", new RegExp(`\\b(?:${["select", "from", "where", "join", "left", "right", "inner", "outer", "full", "on", "group", "by",
      "order", "having", "limit", "offset", "insert", "into", "values", "update", "set", "delete", "create", "table", "alter", "drop",
      "index", "primary", "key", "foreign", "references", "and", "or", "not", "in", "is", "as", "distinct", "union", "all", "case",
      "when", "then", "else", "end", "like", "between", "exists", "asc", "desc", "with", "default", "unique"].join("|")})\\b`, "i")),
    rule("function", /[A-Za-z_][\w]*(?=\s*\()/),
  ],
  yaml: [
    rule("comment", /#[^\n]*/), rule("string", DQ), rule("string", SQ),
    rule("property", /[A-Za-z_][\w.-]{0,80}(?=:(?:\s|$))/), rule("number", /-?\d+(?:\.\d+)?/),
    rule("literal", words(["true", "false", "null", "yes", "no"])),
  ],
  html: [
    rule("comment", /<!--[\s\S]*?(?:-->|$)/), rule("string", DQ), rule("string", SQ),
    rule("keyword", /<\/?[A-Za-z][\w:-]*/), rule("attr", /[A-Za-z_:][\w:.-]{0,80}(?=\s*=)/),
  ],
};

const ALIASES = {
  js: "js", javascript: "js", jsx: "js", mjs: "js", cjs: "js", node: "js", ts: "js", typescript: "js", tsx: "js",
  json: "json", jsonc: "json", json5: "json", py: "python", python: "python", python3: "python",
  sh: "bash", bash: "bash", shell: "bash", zsh: "bash", console: "bash", terminal: "bash",
  css: "css", sql: "sql", yaml: "yaml", yml: "yaml", html: "html", xml: "html", svg: "html",
};

/** The language name the highlighter understands, or null (the block is then shown as plain text). */
export function languageFor(name) {
  return ALIASES[String(name ?? "").toLowerCase()] ?? null;
}

const FILLER = /[A-Za-z_$][\w$]*|\s+|[\s\S]/y;

/** code -> [[type, text], ...]. The texts always join back into `code`. */
export function highlight(code, language) {
  const text = String(code ?? "");
  const rules = LANGUAGES[languageFor(language)];
  if (!rules) return text ? [["plain", text]] : [];
  const head = text.slice(0, MAX_HIGHLIGHT_CHARS);
  const tokens = [];
  const push = (type, value) => {
    const last = tokens[tokens.length - 1];
    if (last && last[0] === type) last[1] += value; else tokens.push([type, value]);
  };
  for (let pos = 0; pos < head.length;) {
    let matched = false;
    for (const { type, re } of rules) {
      re.lastIndex = pos;
      const m = re.exec(head);
      if (m && m[0].length > 0) { push(type, m[0]); pos += m[0].length; matched = true; break; }
    }
    if (matched) continue;
    FILLER.lastIndex = pos;
    const filler = FILLER.exec(head)[0]; // always matches at least one character
    push("plain", filler);
    pos += filler.length;
  }
  if (text.length > head.length) push("plain", text.slice(head.length));
  return tokens;
}
