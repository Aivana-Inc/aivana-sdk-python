// Pacing for the typing animation.
//
// The API delivers an answer in a few large pieces. Showing each piece the moment it arrives makes the
// text jump, so the page keeps two numbers: how much text has ARRIVED and how much is SHOWN. Every frame
// it asks `advance` how far to move the second towards the first. Nothing is ever delayed for its own sake:
// the further behind the display is, the faster it moves, so it always catches up within about a second
// or two, and a slow stream is simply followed as it arrives.
//
// One exception, for looks only: an unfinished **bold**, ~~strike~~, `code` or [link](address) is not shown
// half-typed (its markers would flash as raw characters, then vanish when the end arrives). The span is
// revealed as one unit once its end has arrived, or held back at its start while the end has not. That wait
// is bounded, never applies inside fenced code, and is released the moment the stream completes.
//
// This file only decides numbers. It never touches the page, so it can be tested exactly.

export const TYPING = Object.freeze({
  minCps: 120,      // never slower than this many characters a second, so the tail always finishes
  catchUp: 3,       // otherwise move at (backlog x this) characters a second: it closes about two thirds of the gap each third of a second
  maxDtMs: 100,     // a long pause between frames (a busy or background tab) counts as at most this much time
  maxSnap: 24,      // finish the current word if it ends within this many characters, so text grows by words
  maxSpan: 120,     // reveal an unfinished span as one unit if its end is within this many characters
  maxHold: 240,     // hold a span whose end has not arrived for at most this many characters of text, then show it as it is
});

const isHighSurrogate = (code) => code >= 0xd800 && code <= 0xdbff;
const isSpace = (char) => char === " " || char === "\n" || char === "\t" || char === "\r";
const FENCE = /^ {0,3}(?:`{3,}|~{3,})/;

// Is `index` inside a fenced code block, or on a fence line? (Code is shown exactly as typed, markers and all.)
function inFencedCode(text, index) {
  let fences = 0, onFence = false;
  for (let start = 0; start < index;) {
    let end = text.indexOf("\n", start);
    if (end === -1) end = text.length;
    if (FENCE.test(text.slice(start, Math.min(end, index)))) { fences++; onFence = end >= index; }
    start = end + 1;
  }
  return fences % 2 === 1 || onFence;
}

/**
 * If the text up to `target` ends inside an unfinished inline span on the current line, say where the
 * outermost one began and where it ends (just after its closing marker), or -1 if the end has not arrived
 * on this line. Returns null when the text does not end inside a span.
 */
export function openSpan(text, target) {
  if (inFencedCode(text, target)) return null;
  const lineStart = text.lastIndexOf("\n", target - 1) + 1;
  let lineEnd = text.indexOf("\n", target);
  if (lineEnd === -1) lineEnd = text.length;
  let code = null, bold = -1, strike = -1, bracket = -1, url = -1;
  for (let i = lineStart; i < target;) {
    const c = text[i];
    if (c === "\\") { i += 2; continue; }
    if (c === "`") {
      let n = 1;
      while (text[i + n] === "`") n++; // the whole run, even past `target`, so a run being typed is read the same each frame
      if (code) { if (n === code.n) code = null; } else code = { start: i, n };
      i += n;
      continue;
    }
    if (code) { i++; continue; }
    if (url >= 0) { if (c === ")") url = -1; i++; continue; }
    if (c === "*" && text[i + 1] === "*") { bold = bold < 0 ? i : -1; i += 2; continue; }
    if (c === "~" && text[i + 1] === "~") { strike = strike < 0 ? i : -1; i += 2; continue; }
    if (c === "[" && bracket < 0) { bracket = i; i++; continue; }
    if (c === "]" && bracket >= 0) {
      if (text[i + 1] === "(") { url = bracket; i += 2; } else i++;
      bracket = -1;
      continue;
    }
    i++;
  }
  const open = [];
  const closer = (needle, from) => { const at = text.indexOf(needle, from); return at === -1 || at >= lineEnd ? -1 : at + needle.length; };
  if (code) open.push({ start: code.start, end: closer("`".repeat(code.n), target) });
  if (bold >= 0) open.push({ start: bold, end: closer("**", target) });
  if (strike >= 0) open.push({ start: strike, end: closer("~~", target) });
  if (url >= 0) open.push({ start: url, end: closer(")", target) });
  if (bracket >= 0) {
    const mid = text.indexOf("](", target);
    open.push({ start: bracket, end: mid === -1 || mid >= lineEnd ? -1 : closer(")", mid + 2) });
  }
  if (!open.length) return null;
  return open.reduce((first, span) => (span.start < first.start ? span : first)); // the outermost
}

/**
 * How many characters of `text` to show after `dt` more milliseconds, given that `shown` are showing now.
 * Never more than `text.length` and never backwards. While `complete` is false it may return `shown` unchanged
 * to hold back an unfinished span; once the stream is complete it always moves at least one character.
 */
export function advance({ text, shown, dt, complete = false }) {
  const length = text.length;
  if (shown >= length) return length;
  const backlog = length - shown;
  const rate = Math.max(TYPING.minCps, backlog * TYPING.catchUp);
  const seconds = Math.min(Math.max(dt, 0), TYPING.maxDtMs) / 1000;
  let target = Math.min(length, shown + Math.max(1, Math.round(rate * seconds)));
  if (target < length) {
    // Stop at the end of a word, not in the middle of one (a very long word, such as an address, is cut anyway).
    const limit = Math.min(length, target + TYPING.maxSnap);
    while (target < limit && !isSpace(text[target])) target++;
    // Never end between the two halves of a character such as an emoji.
    if (target < length && isHighSurrogate(text.charCodeAt(target - 1))) target++;
  }
  const span = openSpan(text, target);
  if (span) {
    if (span.end !== -1 && span.end - target <= TYPING.maxSpan) target = span.end; // show the whole span at once
    else if (!complete && length - span.start <= TYPING.maxHold) {
      // Its end has not arrived (or is far away): show only the text before it, and wait for more.
      return span.start > shown ? span.start : shown;
    }
  }
  return Math.min(target, length);
}
