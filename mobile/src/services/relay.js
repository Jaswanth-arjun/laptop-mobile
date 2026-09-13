/**
 * Relay WebSocket client for mobile.
 *
 * Connects to the cloud relay server and provides:
 * - Screen streaming (binary frames)
 * - AI chat (request/response via relay)
 * - Screenshots (request/response via relay)
 *
 * The mobile enters a room code to connect to a laptop.
 */

let ws = null;
let roomCode = null;
let laptopName = "";
let status = "disconnected"; // connecting | connected | disconnected
let reconnectDelay = 1000;
let closedByUs = false;

const frameListeners = new Set();
const statusListeners = new Set();
const messageListeners = new Set();
const pendingRequests = new Map(); // rid → { resolve, reject, timeout }

// ─── Config ───
const RELAY_URL_KEY = "rv_relay_url";
const ROOM_CODE_KEY = "rv_room_code";

export function getRelayUrl() {
  return localStorage.getItem(RELAY_URL_KEY) || "";
}

export function setRelayUrl(url) {
  localStorage.setItem(RELAY_URL_KEY, url);
}

export function getRoomCode() {
  return localStorage.getItem(ROOM_CODE_KEY) || "";
}

export function setRoomCode(code) {
  localStorage.setItem(ROOM_CODE_KEY, code);
  roomCode = code;
}

export function getLaptopName() {
  return laptopName;
}

export function isRelayMode() {
  return !!getRelayUrl() && !!getRoomCode();
}

export function clearRelay() {
  localStorage.removeItem(RELAY_URL_KEY);
  localStorage.removeItem(ROOM_CODE_KEY);
  roomCode = null;
  laptopName = "";
}

// ─── Connection ───
function generateRid() {
  return "r_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
}

function setStatus(s) {
  if (status !== s) {
    status = s;
    statusListeners.forEach((fn) => { try { fn(s); } catch {} });
  }
}

export function connectRelay(relayUrl, code, deviceName) {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  roomCode = code;
  closedByUs = false;
  setStatus("connecting");

  const proto = relayUrl.startsWith("https") ? "wss" : relayUrl.startsWith("http") ? "ws" : relayUrl.startsWith("wss") ? "wss" : "ws";
  const host = relayUrl.replace(/^https?:\/\//, "").replace(/^wss?:\/\//, "").replace(/\/$/, "");
  const url = `${proto}://${host}/view?code=${encodeURIComponent(code)}&name=${encodeURIComponent(deviceName || "Mobile")}`;

  try {
    ws = new WebSocket(url);
  } catch {
    scheduleReconnect(relayUrl, code, deviceName);
    return;
  }

  ws.binaryType = "blob";

  ws.onopen = () => {
    reconnectDelay = 1000;
  };

  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") {
      // Binary = screen frame
      frameListeners.forEach((fn) => { try { fn(ev.data); } catch {} });
      return;
    }

    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }

    switch (msg.type) {
      case "joined":
        laptopName = msg.laptop_name || "Laptop";
        setRelayUrl(relayUrl);
        setRoomCode(code);
        setStatus("connected");
        messageListeners.forEach((fn) => { try { fn(msg); } catch {} });
        break;

      case "ai_response": {
        const pending = pendingRequests.get(msg.rid);
        if (pending) {
          pendingRequests.delete(msg.rid);
          clearTimeout(pending.timeout);
          if (msg.error) {
            pending.reject(new Error(msg.text || "AI error"));
          } else {
            pending.resolve(msg.text);
          }
        }
        break;
      }

      case "screenshot_response": {
        const pending2 = pendingRequests.get(msg.rid);
        if (pending2) {
          pendingRequests.delete(msg.rid);
          clearTimeout(pending2.timeout);
          pending2.resolve(msg);
        }
        break;
      }

      case "room_closed":
        setStatus("disconnected");
        messageListeners.forEach((fn) => { try { fn({ type: "room_closed" }); } catch {} });
        break;

      case "sharing_disabled":
        messageListeners.forEach((fn) => { try { fn({ type: "sharing_disabled" }); } catch {} });
        break;

      case "idle":
        messageListeners.forEach((fn) => { try { fn({ type: "idle" }); } catch {} });
        break;

      case "error":
        messageListeners.forEach((fn) => { try { fn(msg); } catch {} });
        break;

      default:
        messageListeners.forEach((fn) => { try { fn(msg); } catch {} });
    }
  };

  ws.onclose = (ev) => {
    ws = null;
    setStatus("disconnected");
    if (ev.code === 4404) {
      // Room not found
      messageListeners.forEach((fn) => { try { fn({ type: "error", message: "Room not found or expired. Check the code." }); } catch {} });
      return;
    }
    if (!closedByUs) scheduleReconnect(relayUrl, code, deviceName);
  };

  ws.onerror = () => {
    try { ws.close(); } catch {}
  };
}

function scheduleReconnect(relayUrl, code, deviceName) {
  const delay = Math.min(reconnectDelay, 8000);
  reconnectDelay = Math.min(reconnectDelay * 1.7, 8000);
  setTimeout(() => {
    if (!closedByUs && roomCode) connectRelay(relayUrl, code, deviceName);
  }, delay);
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

// ─── API methods (via relay) ───

export function relayAiChat(prompt, images, history) {
  return new Promise((resolve, reject) => {
    const rid = generateRid();
    const timeout = setTimeout(() => {
      pendingRequests.delete(rid);
      reject(new Error("AI request timed out (3 minutes)"));
    }, 180000);
    pendingRequests.set(rid, { resolve, reject, timeout });
    send({ type: "ai_chat", rid, prompt, images, history });
  });
}

export function relayTakeScreenshot() {
  return new Promise((resolve, reject) => {
    const rid = generateRid();
    const timeout = setTimeout(() => {
      pendingRequests.delete(rid);
      reject(new Error("Screenshot request timed out"));
    }, 30000);
    pendingRequests.set(rid, {
      resolve: (msg) => {
        // Convert base64 data URL to blob
        const dataUrl = msg.data || "";
        fetch(dataUrl)
          .then((r) => r.blob())
          .then((blob) => {
            resolve({
              blob,
              timestamp: msg.timestamp || Date.now() / 1000,
              laptop: msg.laptop || laptopName || "Laptop",
            });
          })
          .catch(() => reject(new Error("Failed to decode screenshot")));
      },
      reject,
      timeout,
    });
    send({ type: "screenshot_request", rid });
  });
}

export function relaySendConfig(cfg) {
  send({ type: "config", ...cfg });
}

export function relayPause() {
  send({ type: "pause" });
}

export function relayResume() {
  send({ type: "resume" });
}

// ─── Event listeners ───

export const relay = {
  connect: connectRelay,
  disconnect() {
    closedByUs = true;
    if (ws) { try { ws.close(); } catch {} ws = null; }
    setStatus("disconnected");
  },
  reconnect() {
    reconnectDelay = 500;
    if (ws) { try { ws.close(); } catch {} ws = null; }
    const url = getRelayUrl();
    const code = getRoomCode();
    if (url && code) connectRelay(url, code, "Mobile");
  },
  pause: relayPause,
  resume: relayResume,
  setPaused(v) { if (v) relayPause(); else relayResume(); },
  isPaused() { return false; },
  setConfig(cfg) { relaySendConfig(cfg); },
  onFrame(fn) { frameListeners.add(fn); return () => frameListeners.delete(fn); },
  onStatus(fn) { statusListeners.add(fn); fn(status); return () => statusListeners.delete(fn); },
  onMessage(fn) { messageListeners.add(fn); return () => messageListeners.delete(fn); },
  getStatus() { return status; },
  getLatestFrameBlob() { return null; },
  forceFullFrame() { relaySendConfig({}); },
};
