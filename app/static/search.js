/* VesperaSearch — WebSocket-клиент для /ws/search + mock-режим для прототипа/теста.
 *
 * Протокол сервера (/ws/search):
 *   клиент → {"type": "username"|"email"|"phone"|"social"|"photo"|"metadata", "value": "...", "modules": [...]?}
 *   сервер → {"type": "log"|"result"|"error", ...}
 */
(() => {
  "use strict";

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /** Mock поиск — имитация бэкенда (2 сек), для офлайн-прототипирования. */
  function mockSearch(type, value, onLog, onResult) {
    const sites = [
      { name: "GitHub", icon: "🧑", url: "https://github.com" },
      { name: "VK", icon: "🟦", url: "https://vk.com" },
      { name: "Telegram", icon: "✈️", url: "https://t.me" },
      { name: "X/Twitter", icon: "𝕏", url: "https://twitter.com" },
      { name: "Instagram", icon: "📷", url: "https://instagram.com" },
      { name: "Steam", icon: "🎮", url: "https://steamcommunity.com" },
      { name: "Twitch", icon: "🟣", url: "https://twitch.tv" },
    ];
    let i = 0;
    const t0 = Date.now();
    const interval = setInterval(async () => {
      const site = sites[i];
      if (!site) {
        clearInterval(interval);
        const results = sites.map((s, idx) => ({
          type,
          source: s.name,
          url: `${s.url}/user_${value || "ray228a"}_${idx}`,
          title: `${s.name} — ${value || "ray228a"}`,
          snippet: `Профиль найден на ${s.name}. Это mock-данные.`,
          confidence: ["high", "medium", "low"][idx % 3],
          verified: idx % 2 === 0,
        }));
        onResult({
          id: "mock-" + Date.now(),
          timestamp: new Date().toISOString(),
          query: { type, value },
          results,
          errors: [],
          summary: { total_found: results.length, sources_used: sites.length, high_confidence: results.filter((r) => r.confidence === "high").length },
        });
        return;
      }
      i++;
      onLog && onLog({ module: site.name, status: i === 1 ? "start" : "ok", detail: `${Date.now() - t0}ms` });
      await sleep(120);
      onLog && onLog({ module: site.name, status: "ok", detail: `+${Math.round((i / sites.length) * 100)}%` });
    }, 120);
    return { close: () => clearInterval(interval) };
  }

  /**
   * connect(type, value, callbacks) → {ws, close}
   * callbacks: onLog(ev), onResult(resultEnvelope), onError(ev), onClose(opened)
   */
  function connect(type, value, callbacks = {}) {
    const { onLog, onResult, onError, onClose } = callbacks;
    const ws = new WebSocket(`ws://${location.host}/ws/search`);
    let opened = false;

    ws.onopen = () => {
      opened = true;
      try { ws.send(JSON.stringify({ type, value })); } catch { /* ignore */ }
    };
    ws.onmessage = (ev) => {
      let d;
      try { d = JSON.parse(ev.data); } catch { return; }
      if (d.type === "log") onLog && onLog(d);
      else if (d.type === "result") onResult && onResult(d.result);
      else if (d.type === "error") onError && onError(d);
    };
    ws.onerror = () => onError && onError({ type: "error", message: "Ошибка соединения с сервером" });
    ws.onclose = () => onClose && onClose(opened);
    return { ws, close: () => { try { ws.close(); } catch { /* ignore */ } } };
  }

  window.VesperaSearch = { connect, mockSearch };
})();
