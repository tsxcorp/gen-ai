import { authHeaders } from "./client";
import type { SseEvent } from "./types";

/**
 * Minimal fetch-based SSE client (EventSource cannot send X-Access-Token).
 * Reconnects with backoff; calls `onOpen` after every (re)connect so callers can resync.
 */
export function connectEvents(
  onEvent: (e: SseEvent) => void,
  onOpen: () => void,
  onStatus: (connected: boolean) => void,
): () => void {
  let stopped = false;
  let ctrl: AbortController | null = null;

  async function loop() {
    let delay = 500;
    while (!stopped) {
      ctrl = new AbortController();
      try {
        const res = await fetch("/api/events", {
          headers: authHeaders({ Accept: "text/event-stream" }),
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`SSE HTTP ${res.status}`);
        onStatus(true);
        onOpen();
        delay = 500;
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.search(/\r?\n\r?\n/)) >= 0) {
            const raw = buf.slice(0, idx);
            buf = buf.slice(idx).replace(/^\r?\n\r?\n/, "");
            const ev = parseSseBlock(raw);
            if (ev) onEvent(ev);
          }
        }
      } catch {
        /* fall through to reconnect */
      }
      onStatus(false);
      if (stopped) return;
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 2, 8000);
    }
  }
  void loop();
  return () => {
    stopped = true;
    ctrl?.abort();
  };
}

export function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) continue; // comment / keepalive
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return null;
  const text = data.join("\n");
  try {
    return { event, data: JSON.parse(text) };
  } catch {
    return { event, data: text };
  }
}
