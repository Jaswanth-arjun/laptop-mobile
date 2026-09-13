/**
 * RemoteView Cloud Relay Server
 *
 * A lightweight WebSocket relay that connects laptops and mobiles
 * across any network. No screen data is stored — just forwarded.
 *
 * Protocol:
 *   Laptop connects to  /host
 *   Mobile connects to  /view?code=XXXXXX
 *
 * Message types (JSON):
 *   Laptop → Relay:
 *     { type: "register", name: "LAPTOP-ABC" }
 *     { type: "ai_response", rid, text }
 *     { type: "sharing_status", sharing: true/false }
 *     Binary frame data (just raw bytes, forwarded to all viewers)
 *
 *   Mobile → Relay:
 *     { type: "config", quality, fps, scale }
 *     { type: "pause" }
 *     { type: "resume" }
 *     { type: "ai_chat", rid, prompt, images, history }
 *     { type: "screenshot_request", rid }
 *     { type: "take_screenshot", rid }
 *
 *   Relay → Mobile:
 *     { type: "joined", laptop_name, code, sharing }
 *     { type: "frame" } + binary
 *     { type: "ai_response", rid, text }
 *     { type: "screenshot_response", rid, data }  (base64 jpeg)
 *     { type: "room_closed" }
 *     { type: "error", message }
 *     { type: "idle" }
 *     { type: "sharing_disabled" }
 *
 *   Relay → Laptop:
 *     { type: "room_created", code }
 *     { type: "viewer_joined", viewer_id, device_name }
 *     { type: "viewer_left", viewer_id }
 *     { type: "config", viewer_id, quality, fps, scale }
 *     { type: "ai_chat", rid, viewer_id, prompt, images, history }
 *     { type: "screenshot_request", rid, viewer_id }
 *     { type: "pause", viewer_id }
 *     { type: "resume", viewer_id }
 */

import { createServer } from "http";
import { WebSocketServer, WebSocket } from "ws";
import { URL } from "url";
import { randomBytes } from "crypto";

const PORT = parseInt(process.env.PORT || "4000", 10);

// ──────────────────────────────────────────────── Room management
const rooms = new Map();   // code → Room
const ROOM_TTL = 12 * 60 * 60 * 1000;  // 12 hours max

function generateCode() {
  let code;
  do {
    code = String(Math.floor(100000 + Math.random() * 900000));
  } while (rooms.has(code));
  return code;
}

function generateId() {
  return randomBytes(8).toString("hex");
}

class Room {
  constructor(code, hostWs, hostName) {
    this.code = code;
    this.hostWs = hostWs;
    this.hostName = hostName || "Laptop";
    this.viewers = new Map();  // viewer_id → { ws, device_name }
    this.sharing = true;
    this.createdAt = Date.now();
    this.lastActivity = Date.now();
  }

  addViewer(ws, deviceName) {
    const id = generateId();
    this.viewers.set(id, { ws, device_name: deviceName || "Mobile" });
    this.lastActivity = Date.now();
    return id;
  }

  removeViewer(viewerId) {
    this.viewers.delete(viewerId);
    this.lastActivity = Date.now();
  }

  findViewerId(ws) {
    for (const [id, v] of this.viewers) {
      if (v.ws === ws) return id;
    }
    return null;
  }

  broadcastToViewers(data) {
    for (const [, v] of this.viewers) {
      if (v.ws.readyState === WebSocket.OPEN) {
        try { v.ws.send(data); } catch (e) { /* ignore */ }
      }
    }
  }

  sendToViewer(viewerId, data) {
    const v = this.viewers.get(viewerId);
    if (v && v.ws.readyState === WebSocket.OPEN) {
      try { v.ws.send(typeof data === "string" ? data : data); } catch (e) { /* ignore */ }
    }
  }

  sendToHost(data) {
    if (this.hostWs && this.hostWs.readyState === WebSocket.OPEN) {
      try { this.hostWs.send(typeof data === "string" ? data : data); } catch (e) { /* ignore */ }
    }
  }

  get viewerCount() { return this.viewers.size; }
}

// Cleanup stale rooms every 5 minutes
setInterval(() => {
  const now = Date.now();
  for (const [code, room] of rooms) {
    if (now - room.createdAt > ROOM_TTL) {
      room.broadcastToViewers(JSON.stringify({ type: "room_closed" }));
      rooms.delete(code);
      console.log(`[cleanup] Room ${code} expired`);
    }
  }
}, 5 * 60 * 1000);

// ──────────────────────────────────────────────── HTTP server
const httpServer = createServer((req, res) => {
  // Health check endpoint for deployment platforms
  if (req.url === "/" || req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({
      status: "ok",
      rooms: rooms.size,
      uptime: Math.floor(process.uptime()),
    }));
    return;
  }
  // Stats
  if (req.url === "/stats") {
    const stats = [];
    for (const [code, room] of rooms) {
      stats.push({
        code,
        host: room.hostName,
        viewers: room.viewerCount,
        age_min: Math.floor((Date.now() - room.createdAt) / 60000),
      });
    }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ rooms: stats }));
    return;
  }
  res.writeHead(404);
  res.end("Not found");
});

// ──────────────────────────────────────────────── WebSocket server
const wss = new WebSocketServer({ server: httpServer });

wss.on("connection", (ws, req) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;

  if (path === "/host") {
    handleHost(ws, url);
  } else if (path === "/view") {
    handleViewer(ws, url);
  } else {
    ws.close(4404, "Unknown endpoint. Use /host or /view");
  }
});

// ──────────────────────────────────────────────── Host (Laptop) handler
function handleHost(ws, url) {
  let room = null;
  let code = null;

  ws.on("message", (data, isBinary) => {
    if (isBinary) {
      // Binary = screen frame → forward to all viewers
      if (room) {
        room.lastActivity = Date.now();
        room.broadcastToViewers(data);
      }
      return;
    }

    let msg;
    try { msg = JSON.parse(data.toString()); } catch { return; }

    switch (msg.type) {
      case "register": {
        // Laptop registers itself → create room
        code = generateCode();
        room = new Room(code, ws, msg.name || "Laptop");
        rooms.set(code, room);
        ws.send(JSON.stringify({ type: "room_created", code }));
        console.log(`[host] Room ${code} created by "${room.hostName}"`);
        break;
      }

      case "ai_response": {
        // Forward AI response to the specific viewer
        if (room && msg.viewer_id) {
          room.sendToViewer(msg.viewer_id, JSON.stringify({
            type: "ai_response",
            rid: msg.rid,
            text: msg.text,
            error: msg.error || false,
          }));
        }
        break;
      }

      case "screenshot_response": {
        // Forward screenshot to specific viewer
        if (room && msg.viewer_id) {
          room.sendToViewer(msg.viewer_id, JSON.stringify({
            type: "screenshot_response",
            rid: msg.rid,
            data: msg.data,        // base64 jpeg
            timestamp: msg.timestamp,
            laptop: msg.laptop,
            width: msg.width,
            height: msg.height,
          }));
        }
        break;
      }

      case "sharing_status": {
        if (room) {
          room.sharing = !!msg.sharing;
          if (!room.sharing) {
            room.broadcastToViewers(JSON.stringify({ type: "sharing_disabled" }));
          }
        }
        break;
      }

      case "idle": {
        if (room) {
          room.broadcastToViewers(JSON.stringify({ type: "idle" }));
        }
        break;
      }

      default:
        break;
    }
  });

  ws.on("close", () => {
    if (room && code) {
      console.log(`[host] Room ${code} closed (host disconnected)`);
      room.broadcastToViewers(JSON.stringify({ type: "room_closed" }));
      rooms.delete(code);
    }
  });

  ws.on("error", (err) => {
    console.error(`[host] WebSocket error:`, err.message);
  });
}

// ──────────────────────────────────────────────── Viewer (Mobile) handler
function handleViewer(ws, url) {
  const code = url.searchParams.get("code");
  const deviceName = url.searchParams.get("name") || "Mobile";

  if (!code || !rooms.has(code)) {
    ws.send(JSON.stringify({ type: "error", message: "Invalid or expired room code." }));
    ws.close(4404, "Room not found");
    return;
  }

  const room = rooms.get(code);
  const viewerId = room.addViewer(ws, deviceName);

  // Tell mobile it joined
  ws.send(JSON.stringify({
    type: "joined",
    laptop_name: room.hostName,
    code,
    sharing: room.sharing,
  }));

  // Tell laptop a viewer joined
  room.sendToHost(JSON.stringify({
    type: "viewer_joined",
    viewer_id: viewerId,
    device_name: deviceName,
  }));

  console.log(`[view] "${deviceName}" joined room ${code} (id: ${viewerId})`);

  ws.on("message", (data, isBinary) => {
    if (isBinary) return; // Viewers don't send binary

    let msg;
    try { msg = JSON.parse(data.toString()); } catch { return; }

    switch (msg.type) {
      case "config":
      case "pause":
      case "resume": {
        // Forward control messages to laptop
        room.sendToHost(JSON.stringify({ ...msg, viewer_id: viewerId }));
        break;
      }

      case "ai_chat": {
        // Forward AI chat request to laptop
        room.sendToHost(JSON.stringify({
          type: "ai_chat",
          rid: msg.rid,
          viewer_id: viewerId,
          prompt: msg.prompt,
          images: msg.images,
          history: msg.history,
        }));
        break;
      }

      case "screenshot_request": {
        // Forward screenshot request to laptop
        room.sendToHost(JSON.stringify({
          type: "screenshot_request",
          rid: msg.rid,
          viewer_id: viewerId,
        }));
        break;
      }

      case "disconnect": {
        ws.close(1000, "Client disconnected");
        break;
      }

      default:
        break;
    }
  });

  ws.on("close", () => {
    room.removeViewer(viewerId);
    room.sendToHost(JSON.stringify({
      type: "viewer_left",
      viewer_id: viewerId,
    }));
    console.log(`[view] "${deviceName}" left room ${code}`);
  });

  ws.on("error", (err) => {
    console.error(`[view] WebSocket error (${deviceName}):`, err.message);
  });
}

// ──────────────────────────────────────────────── Start
httpServer.listen(PORT, () => {
  console.log(`RemoteView Relay running on port ${PORT}`);
  console.log(`  Health: http://localhost:${PORT}/health`);
  console.log(`  Stats:  http://localhost:${PORT}/stats`);
});
