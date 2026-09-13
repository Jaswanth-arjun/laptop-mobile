// WebSocket screen-stream client with automatic reconnect and adaptive quality.
// Server sends: binary JPEG frames, JSON {type:idle|sharing_disabled|capture_error}
// Client sends: JSON {type:config|pause|resume}

import { getToken } from "./api.js";

const state = {
  ws: null,
  token: null,
  status: "disconnected", // connecting | connected | disconnected
  paused: false,
  frameListeners: new Set(),
  statusListeners: new Set(),
  messageListeners: new Set(),
  reconnectDelay: 1000,
  closedByUs: false,
  quality: 60,
  scale: 0.85,
  fps: 12,
  autoAdapt: true,
  latestFrameBlob: null,
  _frames: 0,
  _adaptTimer: null,
  _lastFrameAt: 0,
};

function wsBase() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return proto + "//" + location.host;
}

function setStatus(s) {
  if (state.status !== s) {
    state.status = s;
    state.statusListeners.forEach((fn) => {
      try {
        fn(s);
      } catch {}
    });
  }
}

function connect(token) {
  if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  state.token = token;
  state.closedByUs = false;
  setStatus("connecting");
  try {
    state.ws = new WebSocket(wsBase() + "/ws/stream?token=" + encodeURIComponent(token));
  } catch {
    scheduleReconnect();
    return;
  }

  state.ws.binaryType = "blob";

  state.ws.onopen = () => {
    state.reconnectDelay = 1000;
    setStatus("connected");
    sendConfig();
    if (state.paused) send({ type: "pause" });
    startAdaptLoop();
  };

  state.ws.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      let msg = null;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      state.messageListeners.forEach((fn) => {
        try {
          fn(msg);
        } catch {}
      });
      return;
    }
    // binary JPEG frame
    state._frames += 1;
    state._lastFrameAt = performance.now();
    state.latestFrameBlob = ev.data;
    state.frameListeners.forEach((fn) => {
      try {
        fn(ev.data);
      } catch {}
    });
  };

  state.ws.onclose = (ev) => {
    stopAdaptLoop();
    setStatus("disconnected");
    state.ws = null;
    if (ev.code === 4401 || ev.code === 4403) {
      // unauthorized / revoked: notify listeners with a synthetic message
      state.messageListeners.forEach((fn) => {
        try {
          fn({ type: ev.code === 4401 ? "unauthorized" : "revoked" });
        } catch {}
      });
      return; // do not reconnect with a dead token
    }
    if (!state.closedByUs) scheduleReconnect();
  };

  state.ws.onerror = () => {
    try {
      state.ws.close();
    } catch {}
  };
}

function scheduleReconnect() {
  const delay = Math.min(state.reconnectDelay, 8000);
  state.reconnectDelay = Math.min(state.reconnectDelay * 1.7, 8000);
  setTimeout(() => {
    if (!state.closedByUs && state.token) connect(state.token);
  }, delay);
}

function send(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(obj));
  }
}

function sendConfig() {
  send({
    type: "config",
    quality: state.quality,
    scale: state.scale,
    fps: state.fps,
  });
}

// If very few frames arrive, gradually ask for a smaller stream.
function startAdaptLoop() {
  stopAdaptLoop();
  state._frames = 0;
  state._adaptTimer = setInterval(() => {
    if (!state.autoAdapt || state.paused || state.status !== "connected") {
      state._frames = 0;
      return;
    }
    const received = state._frames;
    state._frames = 0;
    if (received <= 1 && state.scale > 0.4) {
      state.scale = Math.max(0.4, Math.round((state.scale - 0.15) * 100) / 100);
      sendConfig();
    } else if (received >= 25 && state.scale < 0.9) {
      state.scale = Math.min(0.9, Math.round((state.scale + 0.1) * 100) / 100);
      sendConfig();
    }
  }, 2000);
}

function stopAdaptLoop() {
  if (state._adaptTimer) {
    clearInterval(state._adaptTimer);
    state._adaptTimer = null;
  }
}

export const stream = {
  connect: (token) => connect(token),
  disconnect() {
    state.closedByUs = true;
    stopAdaptLoop();
    if (state.ws) {
      try {
        state.ws.close();
      } catch {}
      state.ws = null;
    }
    setStatus("disconnected");
  },
  reconnect() {
    state.reconnectDelay = 500;
    if (state.ws) {
      try {
        state.ws.close();
      } catch {}
      state.ws = null;
    }
    if (state.token) connect(state.token);
  },
  pause() {
    state.paused = true;
    send({ type: "pause" });
  },
  resume() {
    state.paused = false;
    send({ type: "resume" });
  },
  setPaused(v) {
    if (v) this.pause();
    else this.resume();
  },
  isPaused() {
    return state.paused;
  },
  setConfig(cfg) {
    if (cfg.quality) state.quality = cfg.quality;
    if (cfg.scale) state.scale = cfg.scale;
    if (cfg.fps) state.fps = cfg.fps;
    if ("autoAdapt" in cfg) state.autoAdapt = !!cfg.autoAdapt;
    sendConfig();
  },
  getConfig() {
    return { ...state.configValues() };
  },
  configValues() {
    return {
      quality: state.quality,
      scale: state.scale,
      fps: state.fps,
      autoAdapt: state.autoAdapt,
    };
  },
  onFrame(fn) {
    state.frameListeners.add(fn);
    return () => state.frameListeners.delete(fn);
  },
  onStatus(fn) {
    state.statusListeners.add(fn);
    fn(state.status);
    return () => state.statusListeners.delete(fn);
  },
  onMessage(fn) {
    state.messageListeners.add(fn);
    return () => state.messageListeners.delete(fn);
  },
  getStatus() {
    return state.status;
  },
  getLatestFrameBlob() {
    return state.latestFrameBlob || null;
  },
  forceFullFrame() {
    // nudge the server: change scale slightly to force a changed frame
    sendConfig();
  },
};
