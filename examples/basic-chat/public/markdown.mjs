// A small, dependency-free Markdown parser for chat answers.
//
// It turns text into a plain data tree (no DOM, no HTML strings), so the same code runs in the
// browser and in the tests, and rendering can only ever create elements and text nodes.
//
// Security model: the answer is untrusted. Raw HTML is never interpreted (it stays literal text),
// there are no images (an image URL would let an answer make your browser fetch it), and a link
// survives only if it is a well-formed http(s) or mailto address. Every scan is bounded so a hostile
// or merely odd answer cannot make the page slow (see the worst-case tests).
//
// Supported: paragraphs, headings, fenced code, block quotes, lists (nested), tables, rules,
// **bold**, *italic*, ~~strike~~, `code`, links and bare http(s) addresses.

export const LIMITS = Object.freeze({
  inputChars: 100_000, depth: 6, linkText: 1_000, linkTarget: 2_000, tableRows: 200, tableColumns: 20,
});

const FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*([^\n]*)$/;
const HEADING = /^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/;
const RULE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const QUOTE = /^ {0,3}>[ ]?(.*)$/;
const ITEM = /^( {0,3})([-*+]|\d{1,9}[.)])([ \t]+|$)(.*)$/;
const DELIMITER_ROW = /^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$/;

// Whitespace, control characters, line separators and backslashes never belong in an address we will link.
function hasUnsafeCharacter(value) {
  for (const ch of value) {
    const c = ch.codePointAt(0);
    if (c <= 0x20 || (c >= 0x7f && c <= 0x9f) || c === 0x2028 || c === 0x2029 || c === 0x5c) return true;
  }
  return false;
}

/** Only these ever become links. Returns the normalised address, or null. */
export function safeHref(raw) {
  if (typeof raw !== "string") return null;
  const value = raw.trim();
  // Browsers drop tabs and newlines inside an address, so "java\nscript:" must not slip through.
  if (!value || value.length > LIMITS.linkTarget || hasUnsafeCharacter(value)) return null;
  if (!/^(?:https?:\/\/|mailto:)/i.test(value)) return null;
  try {
    const url = new URL(value);
    if (!["http:", "https:", "mailto:"].includes(url.protocol)) return null;
    if (url.protocol !== "mailto:" && (!url.hostname || url.username || url.password)) return null;
    return url.href;
  } catch { return null; }
}

// ---------- inline ----------

const PUNCT = /[!-/:-@[-`{-~]/;
const isSpace = (c) => c === undefined || /\s/.test(c);
const isWord = (c) => c !== undefined && /[\p{L}\p{N}]/u.test(c);

function inlineParser(src) {
  // `failFrom[key]`: a search for this closer found nothing from that point on, so a later
  // opener cannot find one either. This keeps unmatched markers linear instead of quadratic.
  const failFrom = Object.create(null);
  const failed = (key, from) => key in failFrom && from >= failFrom[key];
  const noteFail = (key, from) => { if (!(key in failFrom) || from < failFrom[key]) failFrom[key] = from; };

  // A closing marker follows non-space text; `_` never closes inside a word (snake_case); a lone `*` or `_`
  // is not the edge of a longer run (`**`).
  function validCloser(delim, i) {
    const before = src[i - 1];
    const after = src[i + delim.length];
    if (isSpace(before)) return false;
    if (delim[0] === "_" && isWord(after)) return false;
    if (delim.length === 1 && (src[i + 1] === delim[0] || before === delim[0])) return false;
    return true;
  }

  function findCloser(delim, from, end, name) {
    const key = `${name}:${end}`; // a miss only holds for the same search end (nested ranges end earlier)
    if (failed(key, from)) return -1;
    for (let i = from; i < end;) {
      if (src[i] === "\\") { i += 2; continue; }
      if (src[i] === "`") { // a code span hides its contents from emphasis
        let n = 0; while (src[i + n] === "`") n++;
        const close = findRun("`", n, i + n, end);
        i = close === -1 ? i + n : close + n;
        continue;
      }
      if (src.startsWith(delim, i) && validCloser(delim, i)) return i;
      i++;
    }
    noteFail(key, from);
    return -1;
  }

  function findRun(ch, length, from, end) {
    const key = `run${length}:${end}`;
    if (failed(key, from)) return -1;
    for (let i = from; i < end;) {
      if (src[i] !== ch) { i++; continue; }
      let n = 0; while (src[i + n] === ch) n++;
      if (n === length) return i;
      i += n;
    }
    noteFail(key, from);
    return -1;
  }

  function parse(start, end, depth) {
    const out = [];
    let text = "";
    const flush = () => { if (text) { out.push({ t: "text", v: text }); text = ""; } };
    let i = start;
    while (i < end) {
      const c = src[i];
      if (c === "\\" && i + 1 < end && PUNCT.test(src[i + 1])) { text += src[i + 1]; i += 2; continue; }
      if (c === "\n") { flush(); out.push({ t: "br" }); i++; continue; }
      if (c === "`") {
        let n = 0; while (src[i + n] === "`") n++;
        const close = findRun("`", n, i + n, end);
        if (close !== -1) {
          flush();
          let code = src.slice(i + n, close).replace(/\n/g, " ");
          if (code.length > 2 && code.startsWith(" ") && code.endsWith(" ") && code.trim()) code = code.slice(1, -1);
          out.push({ t: "code", v: code });
          i = close + n; continue;
        }
        text += src.slice(i, i + n); i += n; continue;
      }
      if (c === "!" && src[i + 1] === "[") { // images are never loaded; keep the description as a plain link
        const link = parseLink(i + 1, end, depth);
        if (link) { flush(); out.push(link.node.href ? link.node : { t: "text", v: link.label }); i = link.next; continue; }
      }
      if (c === "[") {
        const link = parseLink(i, end, depth);
        if (link) { flush(); out.push(link.node); i = link.next; continue; }
      }
      if (c === "<") {
        const m = /^<([^\s<>]{1,2000})>/.exec(src.slice(i, i + 2002));
        const href = m && safeHref(m[1]);
        if (href) { flush(); out.push({ t: "link", href, c: [{ t: "text", v: m[1] }] }); i += m[0].length; continue; }
      }
      if ((c === "h" || c === "H") && !isWord(src[i - 1])) {
        const m = /^https?:\/\/[^\s<>]{1,2000}/i.exec(src.slice(i, i + 2010));
        if (m) {
          let url = m[0];
          while (/[.,;:!?'"*_~]$/.test(url) || (url.endsWith(")") && (url.match(/\(/g) || []).length < (url.match(/\)/g) || []).length)) url = url.slice(0, -1);
          const href = safeHref(url);
          if (href) { flush(); out.push({ t: "link", href, c: [{ t: "text", v: url }] }); i += url.length; continue; }
        }
      }
      if (depth < LIMITS.depth && (c === "*" || c === "_" || c === "~")) {
        let delim = null;
        if (c === "~") { if (src.startsWith("~~", i)) delim = "~~"; }
        else if (src.startsWith(c.repeat(3), i)) delim = c.repeat(3);
        else if (src.startsWith(c.repeat(2), i)) delim = c.repeat(2);
        else delim = c;
        if (delim) {
          const before = src[i - 1];
          const after = src[i + delim.length];
          const openOk = !isSpace(after) && (c !== "_" || !isWord(before));
          if (openOk) {
            const close = findCloser(delim, i + delim.length, end, delim);
            if (close !== -1) {
              flush();
              const inner = parse(i + delim.length, close, depth + 1);
              out.push(delim.length === 3 ? { t: "em", c: [{ t: "strong", c: inner }] }
                : delim === "~~" ? { t: "del", c: inner } : delim.length === 2 ? { t: "strong", c: inner } : { t: "em", c: inner });
              i = close + delim.length; continue;
            }
          }
        }
        text += c; i++; continue;
      }
      text += c; i++;
    }
    flush();
    return out;
  }

  function parseLink(open, end, depth) {
    // [label](address "title")
    let level = 0, close = -1;
    const limit = Math.min(end, open + LIMITS.linkText + 2);
    for (let i = open; i < limit; i++) {
      if (src[i] === "\\") { i++; continue; }
      if (src[i] === "[") level++;
      else if (src[i] === "]" && --level === 0) { close = i; break; }
    }
    if (close === -1 || src[close + 1] !== "(") return null;
    let i = close + 2, parens = 0;
    const targetStart = i;
    const targetLimit = Math.min(end, i + LIMITS.linkTarget + 200);
    for (; i < targetLimit; i++) {
      const ch = src[i];
      if (ch === "\\") { i++; continue; }
      if (ch === "(") parens++;
      else if (ch === ")") { if (parens === 0) break; parens--; }
      else if (ch === "\n") return null;
    }
    if (i >= targetLimit || src[i] !== ")") return null;
    let target = src.slice(targetStart, i).trim();
    const title = /\s+(?:"[^"]*"|'[^']*')$/.exec(target);
    if (title) target = target.slice(0, title.index);
    if (target.startsWith("<") && target.endsWith(">")) target = target.slice(1, -1);
    const label = src.slice(open + 1, close);
    const href = safeHref(target);
    const next = i + 1;
    if (!href) return { node: { t: "text", v: label }, label, next };
    const children = depth < LIMITS.depth ? parse(open + 1, close, depth + 1) : [{ t: "text", v: label }];
    return { node: { t: "link", href, c: children.length ? children : [{ t: "text", v: href }] }, label, next };
  }

  return (start, end) => parse(start, end, 0);
}

export function parseInline(text) {
  const s = String(text).slice(0, LIMITS.inputChars);
  return inlineParser(s)(0, s.length);
}

// ---------- blocks ----------

const cells = (line) => {
  let row = line.trim();
  if (row.startsWith("|")) row = row.slice(1);
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1);
  const out = []; let cur = "";
  for (let i = 0; i < row.length; i++) {
    if (row[i] === "\\" && row[i + 1] === "|") { cur += "|"; i++; }
    else if (row[i] === "|") { out.push(cur.trim()); cur = ""; }
    else cur += row[i];
  }
  out.push(cur.trim());
  return out;
};

function startsBlock(line, next) {
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line) || startsTable(line, next) ||
    (() => { const m = ITEM.exec(line); return Boolean(m) && m[4].trim() !== "" && (m[2].length === 1 || /^1[.)]$/.test(m[2])); })();
}

function startsTable(line, next) {
  if (next === undefined || !line.includes("|") || !DELIMITER_ROW.test(next) || !next.includes("-")) return false;
  const head = cells(line), rule = cells(next);
  return head.length === rule.length && head.length >= 1 && head.length <= LIMITS.tableColumns && rule.every((c) => /^:?-+:?$/.test(c));
}

function parseBlocks(lines, depth) {
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    let m = FENCE.exec(line);
    if (m && !(m[1][0] === "`" && m[2].includes("`"))) {
      const marker = m[1], body = [];
      const lang = /^[A-Za-z0-9_+#.-]{1,20}$/.test(m[2].trim().split(/\s+/)[0] || "") ? m[2].trim().split(/\s+/)[0].toLowerCase() : "";
      let closed = false;
      for (i++; i < lines.length; i++) {
        const t = lines[i].trim();
        if (t.length >= marker.length && t[0] === marker[0] && /^(?:`+|~+)$/.test(t) && t.length >= marker.length) { closed = true; i++; break; }
        body.push(lines[i]);
      }
      blocks.push({ type: "code", lang, text: body.join("\n"), closed });
      continue;
    }
    if ((m = HEADING.exec(line))) { blocks.push({ type: "heading", level: m[1].length, children: parseInline(m[2]) }); i++; continue; }
    if (RULE.test(line)) { blocks.push({ type: "rule" }); i++; continue; }

    if (QUOTE.test(line)) {
      const inner = [];
      while (i < lines.length && (m = QUOTE.exec(lines[i]))) { inner.push(m[1]); i++; }
      blocks.push({ type: "quote", children: depth < LIMITS.depth ? parseBlocks(inner, depth + 1) : [{ type: "paragraph", children: [{ t: "text", v: inner.join("\n") }] }] });
      continue;
    }

    if (startsTable(line, lines[i + 1])) {
      const header = cells(line).map(parseInline);
      const align = cells(lines[i + 1]).map((c) => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : c.startsWith(":") ? "left" : null));
      const rows = [];
      for (i += 2; i < lines.length && lines[i].trim() && lines[i].includes("|") && rows.length < LIMITS.tableRows; i++) {
        const row = cells(lines[i]).slice(0, header.length);
        while (row.length < header.length) row.push("");
        rows.push(row.map(parseInline));
      }
      blocks.push({ type: "table", header, align, rows });
      continue;
    }

    if ((m = ITEM.exec(line)) && depth < LIMITS.depth) {
      const ordered = m[2].length > 1;
      const start = ordered ? parseInt(m[2], 10) : 1;
      const items = [];
      let loose = false, sawBlank = false;
      while (i < lines.length) {
        const im = ITEM.exec(lines[i]);
        if (!im || (im[2].length > 1) !== ordered || im[1].length > 3) break;
        const offset = im[1].length + im[2].length + Math.min(Math.max(im[3].length, 1), 4);
        const content = [im[4]];
        i++;
        let blankBefore = false;
        while (i < lines.length) {
          const l = lines[i];
          if (!l.trim()) { blankBefore = true; content.push(""); i++; continue; }
          const indent = /^ */.exec(l)[0].length;
          if (indent >= Math.min(offset, 2) && indent > 0 && indent >= im[1].length + 1) { content.push(l.slice(Math.min(indent, offset))); blankBefore = false; i++; continue; }
          break;
        }
        while (content.length && !content[content.length - 1].trim()) { content.pop(); sawBlank = true; }
        items.push(parseBlocks(content, depth + 1));
        if (blankBefore && i < lines.length && ITEM.test(lines[i])) loose = true;
      }
      blocks.push({ type: "list", ordered, start, tight: !(loose || (sawBlank && items.length > 1)), items });
      continue;
    }

    const para = [line];
    for (i++; i < lines.length && lines[i].trim() && !startsBlock(lines[i], lines[i + 1]); i++) para.push(lines[i]);
    blocks.push({ type: "paragraph", children: parseInline(para.join("\n")) });
  }
  return blocks;
}

/** Markdown text -> a list of block nodes. Never throws on input; always bounded. */
export function parseMarkdown(text) {
  const source = String(text ?? "").slice(0, LIMITS.inputChars).replace(/\r\n?/g, "\n").replaceAll(String.fromCharCode(0), String.fromCharCode(0xfffd));
  return parseBlocks(source.split("\n"), 0);
}
