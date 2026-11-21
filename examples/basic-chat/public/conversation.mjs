// One bounded context policy shared by the browser and server. Nothing is persisted.
export const LIMITS = Object.freeze({ messageChars: 4_000, historyMessages: 16, contextChars: 24_000 });

export function recentHistory(history, nextMessage = "") {
  const recent = history.map(({ role, content }) => ({ role, content }));
  let chars = recent.reduce((total, item) => total + item.content.length, nextMessage.length);
  while (recent.length && (recent.length > LIMITS.historyMessages || chars > LIMITS.contextChars)) {
    const removed = recent.splice(0, 2);
    chars -= removed.reduce((total, item) => total + item.content.length, 0);
  }
  return recent;
}
