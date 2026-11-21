import { LIMITS, recentHistory } from "./conversation.mjs";
import { renderMarkdown, copyText } from "./render.mjs";
import { advance } from "./typing.mjs";

const $ = (selector) => document.querySelector(selector);
const form = $("#composer");
const input = $("#message");
const transcript = $("#transcript");
const empty = $("#empty");
const chat = $(".chat");
const suggestions = $("#suggestions");
const status = $("#status");
const error = $("#error");
const announcer = $("#announce");
const send = $("#send");
const stop = $("#stop");
const jump = $("#jump");
const streaming = $("#streaming");
const effortSelect = $("#effort");
const lengthSelect = $("#max-tokens");
const searchBox = $("#web-search");

const DEFAULTS = Object.freeze({ effort: "auto", maxTokens: 800, webSearch: false, streaming: true });
const EFFORT_NAMES = { auto: "Auto", low: "Low", medium: "Medium", high: "High" };
const LENGTH_NAMES = { 400: "Short", 800: "Standard", 1600: "Long" };
// Effort is a ceiling on reasoning. It promises nothing about how many models or perspectives are used,
// and it is not a length or price control (the SDK documents it that way).
const EFFORT_HELP = {
  auto: "Aivana determines the appropriate intelligence effort for each request.",
  low: "Sets a lower ceiling on reasoning. This can reduce response time on simpler questions.",
  medium: "Sets a balanced ceiling on reasoning.",
  high: "Allows deeper reasoning for more demanding questions. Responses may take longer.",
};

// The saved conversation: only complete answers ever enter it.
let history = [];
let context = {};
// The request in progress, or the failed/stopped one still on screen. Never part of `history`.
// { user, state: "thinking" | "streaming" | "interrupted" | "stopped", text, shown, complete }
// `text` is everything that has arrived; `shown` is how much of it the typing animation has revealed so far.
let turn = null;
let active; // the AbortController of the request in flight
let ready = false;
let historyMode = "session";
let blueprintLoaded = false;
let live = null; // the on-screen nodes of the turn being drawn
let frame = 0;
let lastTick = 0; // the time of the previous animation frame
let revealWaiter = null; // resolves when the display has caught up with the text that arrived
let stick = true; // follow the newest text unless the person scrolls up to read

// ---------- theme ----------

const themeButton = $("#theme");
const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
let chosenTheme;
function themeLabel() {
  const dark = chosenTheme ? chosenTheme === "dark" : systemTheme.matches;
  themeButton.textContent = dark ? "Light" : "Dark";
  themeButton.setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} theme`);
}
themeButton.addEventListener("click", () => {
  chosenTheme = (chosenTheme ? chosenTheme === "dark" : systemTheme.matches) ? "light" : "dark";
  document.documentElement.dataset.theme = chosenTheme;
  themeLabel();
});
systemTheme.addEventListener("change", themeLabel);
themeLabel();

// ---------- small helpers ----------

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function announce(text) {
  announcer.textContent = text;
  setTimeout(() => { if (announcer.textContent === text) announcer.textContent = ""; }, 3000);
}

function busy(value) {
  send.disabled = value || !ready;
  send.hidden = value; // Stop takes the Send button's place, so it is always under the thumb
  stop.hidden = !value;
  input.disabled = value || !ready;
  $("#reset").disabled = !ready;
  suggestions.querySelectorAll("button").forEach((button) => { button.disabled = value || !ready; });
  document.querySelectorAll("[data-action='regenerate'], [data-action='retry']").forEach((button) => { button.disabled = value; });
  form.setAttribute("aria-busy", String(value));
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
}
input.addEventListener("input", resizeInput);

// ---------- scrolling: follow the answer, unless the person scrolls up ----------

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const nearBottom = () => transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 64;
const overflowing = () => transcript.scrollHeight > transcript.clientHeight + 8;
function updateJump() { jump.hidden = stick || !overflowing(); }
function followLatest(force = false) {
  if (force) stick = true;
  if (stick) transcript.scrollTop = transcript.scrollHeight;
  updateJump();
}
transcript.addEventListener("scroll", () => { stick = nearBottom(); updateJump(); }, { passive: true });
jump.addEventListener("click", () => {
  stick = true;
  // While text is still arriving the jump is instant: a smooth scroll reports "not at the bottom" on its way,
  // which would switch following off again and leave the page behind the answer.
  transcript.scrollTo({ top: transcript.scrollHeight, behavior: reduceMotion.matches || active ? "auto" : "smooth" });
  updateJump();
});

// ---------- messages ----------

function actionButton(label, action, onClick, describedBy) {
  const button = node("button", "action", label);
  button.type = "button";
  button.dataset.action = action;
  if (describedBy) button.setAttribute("aria-describedby", describedBy);
  button.disabled = Boolean(active) && action !== "copy";
  button.addEventListener("click", onClick);
  return button;
}

function copyButton(getText) {
  const button = actionButton("Copy", "copy", async () => {
    const ok = await copyText(getText());
    button.textContent = ok ? "Copied" : "Copy failed";
    announce(ok ? "Response copied to the clipboard." : "Copying is not available here.");
    setTimeout(() => { button.textContent = "Copy"; }, 2000);
  });
  button.setAttribute("aria-label", "Copy response");
  return button;
}

function userNode(content) {
  const article = node("article", "message user");
  article.append(node("h2", "", "You"), node("p", "", content));
  return article;
}

function completedNode(item, isLatest) {
  const article = node("article", "message assistant");
  const body = node("div", "markdown-body");
  body.append(renderMarkdown(item.content)); // Copy below uses item.content: the original Markdown, not the rendering
  const actions = node("div", "message-actions");
  actions.setAttribute("role", "group");
  actions.setAttribute("aria-label", "Response actions");
  actions.append(copyButton(() => item.content));
  if (isLatest) {
    const note = node("span", "action-note", "Sends a new request · uses credit");
    note.id = "regen-note";
    const regen = actionButton("Regenerate", "regenerate", regenerate, "regen-note");
    regen.title = "Replaces this answer with a new one. Sends a new request that uses credit.";
    actions.append(regen, note);
  }
  article.append(node("h2", "", "Aivana"), body, actions);
  return article;
}

function thinkingNode() {
  const wrap = node("div", "thinking");
  const dots = node("span", "dots");
  dots.setAttribute("aria-hidden", "true");
  dots.append(node("i"), node("i"), node("i"));
  wrap.append(node("span", "", "Thinking"), dots);
  return wrap;
}

function turnNode() {
  const article = node("article", `message assistant live is-${turn.state}`);
  const heading = node("h2", "", "Aivana");
  const body = node("div", "markdown-body");
  article.append(heading);
  live = { article, body, thinking: null };
  if (turn.state === "thinking") {
    live.thinking = thinkingNode();
    article.append(live.thinking);
  } else {
    body.append(renderMarkdown(turn.state === "streaming" ? turn.text.slice(0, turn.shown) : turn.text, { streaming: turn.state === "streaming" }));
    article.append(body);
  }
  if (turn.state === "interrupted" || turn.state === "stopped") {
    const interrupted = turn.state === "interrupted";
    heading.append(" ", node("span", `state-chip ${turn.state}`, interrupted ? "Interrupted" : "Stopped"));
    const note = node("div", "turn-note");
    note.append(node("span", "", turn.text.trim()
      ? `${interrupted ? "The response was interrupted" : "You stopped the response"}. This partial answer was not saved to the conversation.`
      : "No response was received."));
    if (interrupted) {
      const retryNote = node("span", "action-note", "Sends a new request · uses credit");
      retryNote.id = "retry-note";
      note.append(actionButton("Retry", "retry", retry, "retry-note"), retryNote);
    }
    article.append(note);
  }
  return article;
}

function renderTranscript() {
  const hasMessages = Boolean(turn || history.length);
  chat.classList.toggle("has-messages", hasMessages);
  suggestions.hidden = hasMessages || blueprintLoaded;
  live = null;
  const nodes = history.map((item, index) => (item.role === "user" ? userNode(item.content) : completedNode(item, index === history.length - 1)));
  if (turn) nodes.push(userNode(turn.user), turnNode());
  if (!hasMessages) nodes.push(empty);
  transcript.replaceChildren(...nodes);
  if (turn?.state === "streaming") appendCaret(live.body);
  followLatest();
}

// A blinking caret at the end of the text that is still arriving.
function appendCaret(body) {
  let host = body;
  while (host.lastElementChild) {
    const last = host.lastElementChild;
    if (last.matches("p, h3, h4, h5, h6")) { host = last; break; }
    if (last.matches("ul, ol, li, blockquote")) { host = last; continue; }
    break;
  }
  const caret = node("span", "caret");
  caret.setAttribute("aria-hidden", "true");
  host.append(caret);
}

// The typing animation: text that has arrived is revealed a little each frame, by words, quickly while far
// behind and gently when nearly caught up (see typing.mjs). People who prefer reduced motion see it at once.
function scheduleLive() { if (!frame) frame = requestAnimationFrame(paintLive); }
function paintLive(timestamp) {
  frame = 0;
  if (!turn || !live || !["thinking", "streaming"].includes(turn.state)) return;
  const received = turn.text.length;
  const before = turn.shown;
  const next = reduceMotion.matches ? received
    : advance({ text: turn.text, shown: before, dt: lastTick ? timestamp - lastTick : 16, complete: turn.complete });
  lastTick = timestamp;
  if (turn.state === "thinking") {
    // Keep "Thinking" until there is something to show (text may arrive that is only the start of an unfinished span).
    if (!turn.text.trim() || next === 0) { lastTick = 0; return; }
    turn.state = "streaming"; // first text: swap "Thinking" for the answer
    live.article.classList.replace("is-thinking", "is-streaming");
    live.thinking.replaceWith(live.body);
    live.body.classList.add("reveal");
    live.thinking = null;
  }
  turn.shown = next;
  if (next !== before || !live.body.firstChild) {
    live.body.replaceChildren(renderMarkdown(turn.text.slice(0, turn.shown), { streaming: true }));
    appendCaret(live.body);
  }
  followLatest();
  if (turn.shown < received) {
    if (turn.shown > before) { scheduleLive(); return; } // still catching up
    lastTick = 0; // holding back an unfinished **span**: the next piece of text (or the end of the stream) wakes this up
    return;
  }
  lastTick = 0;
  const waiter = revealWaiter;
  revealWaiter = null;
  waiter?.();
}

// After the last piece arrives, let the display finish catching up before the answer is saved and drawn whole.
// Stop and New chat end the wait at once, and a background tab (which runs no frames) is never waited on for long.
function finishReveal(signal) {
  return new Promise((resolve) => {
    if (!turn || signal.aborted || !turn.text.trim() || (turn.state === "streaming" && turn.shown >= turn.text.length)) return resolve();
    const done = () => { if (revealWaiter === done) revealWaiter = null; clearTimeout(timer); signal.removeEventListener("abort", done); resolve(); };
    const timer = setTimeout(done, 2500);
    signal.addEventListener("abort", done, { once: true });
    revealWaiter = done;
    scheduleLive();
  });
}

// ---------- requests ----------

class Refused extends Error {} // the server answered with an error before any answer began

async function ask(message, { restore } = {}) {
  if (active || !ready) return;
  const displayHistory = recentHistory(history, message);
  const sentHistory = historyMode === "session" ? displayHistory : [];
  const settings = blueprintLoaded ? {} : { effort: effortSelect.value, webSearch: searchBox.checked, maxTokens: Number(lengthSelect.value) };
  const useStream = streaming.checked;
  const controller = new AbortController();
  active = controller;
  error.hidden = true;
  turn = { user: message, state: "thinking", text: "", shown: 0, complete: false };
  busy(true);
  status.textContent = "Aivana is working…";
  renderTranscript();
  followLatest(true);
  const keepStopped = () => {
    if (turn?.text.trim()) turn.state = "stopped";
    else { turn = null; if (restore) history = restore; }
    renderTranscript();
  };
  try {
    const response = await fetch(useStream ? "/api/chat/stream" : "/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: sentHistory, context: historyMode === "session" ? context : {}, settings }), signal: controller.signal,
    });
    if (!response.ok) {
      const result = await response.json();
      throw new Refused(result.error?.message || "The request could not be completed.");
    }
    let answer = "", nextContext = {}, usage = {};
    if (useStream) {
      if (!response.body) throw new Error("Streaming is unavailable.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "", complete = false;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, newline);
          buffer = buffer.slice(newline + 1);
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.event === "delta") {
            answer += event.data.text;
            if (turn) { turn.text = answer; scheduleLive(); }
          } else if (event.event === "done") {
            complete = true;
            if (turn) turn.complete = true; // from here nothing is held back waiting for more text
            nextContext = event.data.context ?? {};
            usage = event.data.usage ?? {};
          } else if (event.event === "error") {
            throw new Error(event.data.message || "Streaming failed.");
          }
        }
      }
      if (!complete || !answer.trim()) throw new Error("The response ended before completion.");
      await finishReveal(controller.signal); // the animation finishes before the answer is saved
    } else {
      const result = await response.json();
      if (typeof result.answer !== "string") throw new Error("The app received an unexpected response.");
      answer = result.answer;
      nextContext = result.context ?? {};
      usage = result.usage ?? {};
    }
    if (controller.signal.aborted) { if (controller.stopped) keepStopped(); return; }
    if (frame) { cancelAnimationFrame(frame); frame = 0; }
    history = recentHistory([...displayHistory, { role: "user", content: message }, { role: "assistant", content: answer }]);
    context = nextContext;
    turn = null;
    if (input.value.trim() === message) { input.value = ""; resizeInput(); } // keep anything typed since
    status.textContent = "";
    showUsage(usage);
    renderTranscript();
    // The transcript is rebuilt as a whole, so it is not a live region; the new reply is announced once, here.
    const reply = transcript.querySelector(".message.assistant:last-child .markdown-body")?.textContent ?? "";
    announce(`Aivana replied. ${reply.slice(0, 2000)}`);
  } catch (failure) {
    if (frame) { cancelAnimationFrame(frame); frame = 0; }
    revealWaiter = null;
    if (controller.signal.aborted) { if (controller.stopped) keepStopped(); return; }
    const refused = failure instanceof Refused;
    error.textContent = refused ? failure.message
      : failure instanceof TypeError ? "The connection was interrupted. Aivana may have accepted the request, and it was not sent again automatically." : failure.message;
    error.hidden = false;
    status.textContent = "";
    // Before an answer began: nothing to keep. After: keep the partial text, labelled, with a Retry. Either way nothing is saved.
    if (refused) { turn = null; if (restore) history = restore; } else turn.state = "interrupted";
    renderTranscript();
  } finally {
    if (active === controller) {
      active = undefined;
      busy(false);
      input.focus();
    }
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || message.length > LIMITS.messageChars) return;
  ask(message);
});

// Retry resends the same message; the failed attempt was never saved, so history is unchanged.
function retry() {
  if (active || !turn) return;
  const message = turn.user;
  turn = null;
  ask(message);
}

// Regenerate discards the latest answer and asks again with the current settings. It is a second, billed request.
function regenerate() {
  if (active || !ready || history.length < 2 || history.at(-1).role !== "assistant") return;
  const previous = history;
  const message = history.at(-2).content;
  history = history.slice(0, -2);
  ask(message, { restore: previous }); // if the server refuses, the earlier answer comes back
}

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

stop.addEventListener("click", () => {
  // The request settles as cancelled and ask() redraws, keeping any text that had already arrived.
  if (active) active.stopped = true;
  active?.abort();
  status.textContent = "Stopped waiting. An accepted request may still use credit.";
});

$("#reset").addEventListener("click", () => {
  active?.abort();
  history = [];
  context = {};
  turn = null;
  input.value = "";
  resizeInput();
  error.hidden = true;
  $("#session-details").hidden = true;
  status.textContent = "New chat. Earlier messages will not be sent again.";
  renderTranscript();
  followLatest(true);
  if (!active) input.focus();
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    if (active || !ready) return;
    input.value = button.dataset.prompt;
    resizeInput();
    input.focus();
  });
});
window.addEventListener("pagehide", () => active?.abort());

// ---------- session details: only what the response really carried ----------

function formatTime(ms) { return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`; }
function showUsage(usage) {
  const rows = [];
  if (Number.isInteger(usage.inputTokens)) rows.push(["Input tokens", usage.inputTokens.toLocaleString("en-US")]);
  if (Number.isInteger(usage.outputTokens)) rows.push(["Output tokens", usage.outputTokens.toLocaleString("en-US")]);
  if (Number.isFinite(usage.latencyMs)) rows.push(["Response time", formatTime(usage.latencyMs)]);
  const list = $("#session-list");
  list.replaceChildren(...rows.map(([name, value]) => {
    const row = node("div");
    row.append(node("dt", "", name), node("dd", "", value));
    return row;
  }));
  $("#session-details").hidden = rows.length === 0; // nothing reported, nothing shown
}

// ---------- settings ----------

function describeSettings() {
  $("#effort-help").textContent = EFFORT_HELP[effortSelect.value];
  const parts = [];
  if (!blueprintLoaded) {
    if (effortSelect.value !== DEFAULTS.effort) parts.push(`${EFFORT_NAMES[effortSelect.value]} effort`);
    if (Number(lengthSelect.value) !== DEFAULTS.maxTokens) parts.push(`${LENGTH_NAMES[lengthSelect.value]} answers`);
    if (searchBox.checked) parts.push("Web search");
  } else parts.push("Blueprint");
  if (!streaming.checked) parts.push("No streaming");
  $("#settings-summary").textContent = parts.length ? `· ${parts.join(" · ")}` : "";
}
[effortSelect, lengthSelect, searchBox, streaming].forEach((control) => control.addEventListener("change", describeSettings));
$("#settings-reset").addEventListener("click", () => {
  effortSelect.value = DEFAULTS.effort;
  lengthSelect.value = String(DEFAULTS.maxTokens);
  searchBox.checked = DEFAULTS.webSearch;
  streaming.checked = DEFAULTS.streaming;
  describeSettings();
  announce("Settings reset to defaults.");
});
describeSettings();

function applyBlueprint(config) {
  blueprintLoaded = true;
  const details = config.blueprint ?? {};
  $("#chat-settings").hidden = true;
  $("#settings-reset").hidden = true;
  $("#blueprint-settings").hidden = false;
  $("#bp-effort").textContent = EFFORT_NAMES[details.effort] ?? "Set by Blueprint";
  $("#bp-length").textContent = Number.isInteger(details.maxTokens) ? `Up to ${details.maxTokens.toLocaleString("en-US")} tokens` : "Engine default";
  $("#bp-search").textContent = config.webSearch ? "Allowed" : "Off";
  // The Blueprint export has a purpose but no name, so the welcome shows the purpose, says where it came from, and uses
  // the local AIVANA_BLUEPRINT_NAME (when set) as its title.
  $("#empty-kicker-text").textContent = "Loaded from Agent Kit";
  const name = typeof details.name === "string" ? details.name.trim() : "";
  $("#empty-title").textContent = name || "Chat with your Blueprint.";
  if (name) document.title = `${name} · Aivana`;
  $("#empty-text").textContent = typeof details.purpose === "string" && details.purpose ? details.purpose : "Your Agent Kit Blueprint is loaded.";
  suggestions.hidden = true; // generic starter prompts would not suit a purpose-built assistant
  describeSettings();
}

// ---------- start ----------

busy(false);
status.textContent = "Loading chat settings…";
try {
  const response = await fetch("/api/config");
  const config = await response.json();
  if (!response.ok || typeof config.blueprintLoaded !== "boolean" || typeof config.webSearch !== "boolean" || !["session", "none"].includes(config.history)) {
    throw new Error("Invalid settings response");
  }
  historyMode = config.history;
  const note = $("#configuration-note");
  if (config.blueprintLoaded) {
    applyBlueprint(config);
    note.hidden = false;
    note.textContent = `Blueprint loaded · Web search ${config.webSearch ? "allowed" : "off"}. ${historyMode === "none" ? "Each message is answered independently; earlier messages are not sent." : "Recent messages are included with follow-ups."}`;
  }
  ready = true;
  status.textContent = "";
} catch {
  status.textContent = "";
  error.hidden = false;
  error.textContent = "Chat settings could not be loaded. Check the starter server and reload this page before sending.";
} finally { busy(false); }
