// Turns the parse tree from markdown.mjs into DOM nodes.
//
// This file is the only place answer text becomes elements, and it can only ever call
// createElement, createTextNode, append, setAttribute and textContent: no HTML string is built or
// parsed anywhere, so an answer cannot inject markup or script. A test renders hostile answers
// through a recording DOM and fails if any element or attribute outside a short allow-list appears.

import { parseMarkdown } from "./markdown.mjs";
import { highlight, languageFor } from "./highlight.mjs";

// Headings in an answer sit below the message label (an h2) and never skip a level: the first is an h3 whatever
// its Markdown level, and each later one is at most one level deeper than the one before. Size still follows the
// Markdown level (the md-hN class).
const headingTag = (level, options) => {
  const tag = Math.min(level + 2, options.lastHeading + 1, 6);
  options.lastHeading = tag;
  return `h${tag}`;
};

/** Copy text to the clipboard. Resolves true on success, false if the browser refused. */
export async function copyText(text, doc = document) {
  try {
    if (doc.defaultView?.navigator?.clipboard?.writeText) { await doc.defaultView.navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through to the older path */ }
  try {
    const scratch = doc.createElement("textarea");
    scratch.className = "sr-only";
    scratch.value = text;
    scratch.setAttribute("aria-hidden", "true");
    doc.body.append(scratch);
    scratch.select();
    const ok = doc.execCommand("copy");
    scratch.remove();
    return ok;
  } catch { return false; }
}

function el(doc, tag, className, text) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function inline(doc, nodes) {
  const out = [];
  for (const n of nodes) {
    if (n.t === "text") out.push(doc.createTextNode(n.v));
    else if (n.t === "br") out.push(doc.createElement("br"));
    else if (n.t === "code") out.push(el(doc, "code", "md-inline-code", n.v));
    else if (n.t === "link") {
      const a = el(doc, "a");
      a.setAttribute("href", n.href);
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer nofollow");
      a.setAttribute("referrerpolicy", "no-referrer");
      a.setAttribute("title", n.href); // the real destination is always visible on hover
      a.append(...inline(doc, n.c));
      out.push(a);
    } else {
      const tag = n.t === "strong" ? "strong" : n.t === "em" ? "em" : "del";
      const node = el(doc, tag);
      node.append(...inline(doc, n.c));
      out.push(node);
    }
  }
  return out;
}

function codeBlock(doc, block, options) {
  const wrapper = el(doc, "div", "code-block");
  const head = el(doc, "div", "code-head");
  head.append(el(doc, "span", "code-lang", block.lang || "text"));
  if (!options.streaming && block.closed) {
    const button = el(doc, "button", "code-copy", "Copy");
    button.setAttribute("type", "button");
    button.setAttribute("aria-label", "Copy code");
    const live = el(doc, "span", "sr-only");
    live.setAttribute("role", "status");
    let timer;
    button.addEventListener("click", async () => {
      const ok = await copyText(block.text, doc);
      button.textContent = ok ? "Copied" : "Copy failed";
      live.textContent = ok ? "Code copied to the clipboard." : "Copying is not available here.";
      clearTimeout(timer);
      timer = setTimeout(() => { button.textContent = "Copy"; live.textContent = ""; }, 2000);
    });
    head.append(button, live);
  }
  const pre = el(doc, "pre");
  pre.setAttribute("tabindex", "0"); // a long line scrolls with the keyboard
  pre.setAttribute("role", "region");
  pre.setAttribute("aria-label", `${block.lang || "Code"} code`);
  const code = el(doc, "code");
  if (languageFor(block.lang)) {
    for (const [type, value] of highlight(block.text, block.lang)) {
      if (type === "plain") code.append(doc.createTextNode(value));
      else code.append(el(doc, "span", `tok-${type}`, value));
    }
  } else code.textContent = block.text;
  pre.append(code);
  wrapper.append(head, pre);
  return wrapper;
}

function blocks(doc, list, options, tight = false) {
  const out = [];
  for (const b of list) {
    if (b.type === "paragraph") {
      if (tight) out.push(...inline(doc, b.children)); // inside a tight list item the text sits directly in the <li>
      else { const p = el(doc, "p"); p.append(...inline(doc, b.children)); out.push(p); }
    } else if (b.type === "heading") {
      const h = el(doc, headingTag(b.level, options), `md-h${Math.min(b.level, 4)}`);
      h.append(...inline(doc, b.children));
      out.push(h);
    } else if (b.type === "code") out.push(codeBlock(doc, b, options));
    else if (b.type === "rule") out.push(el(doc, "hr"));
    else if (b.type === "quote") { const q = el(doc, "blockquote"); q.append(...blocks(doc, b.children, options)); out.push(q); }
    else if (b.type === "list") {
      const container = el(doc, b.ordered ? "ol" : "ul");
      if (b.ordered && b.start !== 1) container.setAttribute("start", String(b.start));
      for (const item of b.items) { const li = el(doc, "li"); li.append(...blocks(doc, item, options, b.tight)); container.append(li); }
      out.push(container);
    } else if (b.type === "table") {
      const wrap = el(doc, "div", "table-wrap");
      wrap.setAttribute("tabindex", "0");
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", "Table");
      const table = el(doc, "table");
      const cell = (tag, content, align) => { const c = el(doc, tag, align ? `align-${align}` : ""); if (tag === "th") c.setAttribute("scope", "col"); c.append(...inline(doc, content)); return c; };
      const headRow = el(doc, "tr");
      b.header.forEach((content, i) => headRow.append(cell("th", content, b.align[i])));
      const thead = el(doc, "thead"); thead.append(headRow);
      const tbody = el(doc, "tbody");
      for (const row of b.rows) { const tr = el(doc, "tr"); row.forEach((content, i) => tr.append(cell("td", content, b.align[i]))); tbody.append(tr); }
      table.append(thead, tbody);
      wrap.append(table);
      out.push(wrap);
    }
  }
  return out;
}

/**
 * Markdown text -> a DocumentFragment. While `streaming`, code blocks have no Copy button yet
 * (the text is still arriving and the nodes are replaced on every update).
 */
export function renderMarkdown(source, { doc = document, streaming = false } = {}) {
  const fragment = doc.createDocumentFragment();
  fragment.append(...blocks(doc, parseMarkdown(source), { streaming, lastHeading: 2 }));
  return fragment;
}
