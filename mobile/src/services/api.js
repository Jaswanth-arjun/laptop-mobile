// Small fetch wrapper around the laptop API. All calls are same-origin
// (the PWA is served by the laptop server) and authenticated with the
// pairing token stored in localStorage.

const TOKEN_KEY = "rv_token";
const NAME_KEY = "rv_device_name";
const LAPTOP_KEY = "rv_laptop_name";
const DEVICE_KEY = "rv_device_id";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setAuth({ token, device_id, laptop_name }) {
  localStorage.setItem(TOKEN_KEY, token);
  if (device_id) localStorage.setItem(DEVICE_KEY, device_id);
  if (laptop_name) localStorage.setItem(LAPTOP_KEY, laptop_name);
}
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(DEVICE_KEY);
  localStorage.removeItem(LAPTOP_KEY);
}
export function getLaptopName() {
  return localStorage.getItem(LAPTOP_KEY) || "";
}
export function getDeviceName() {
  return localStorage.getItem(NAME_KEY) || "";
}
export function setDeviceName(name) {
  localStorage.setItem(NAME_KEY, name);
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}, auth = true) {
  const headers = Object.assign({}, options.headers || {});
  if (options.body && typeof options.body === "string") {
    headers["Content-Type"] = "application/json";
  }
  if (auth) headers["Authorization"] = "Bearer " + getToken();
  let res;
  try {
    res = await fetch(path, { ...options, headers });
  } catch {
    throw new ApiError(
      "Cannot reach the laptop. Make sure RemoteView is running and both devices are on the same Wi-Fi.",
      0
    );
  }
  if (res.status === 401) {
    clearAuth();
    throw new ApiError("Your device is no longer authorized. Pair again.", 401);
  }
  if (!res.ok) {
    let detail = "Request failed (" + res.status + ")";
    try {
      const data = await res.json();
      if (data && data.detail) detail = data.detail;
    } catch {
      /* keep default */
    }
    throw new ApiError(detail, res.status);
  }
  return res;
}

export async function apiJson(path, options = {}, auth = true) {
  const res = await request(path, options, auth);
  return res.json();
}

export async function pair(code, deviceName) {
  const data = await apiJson(
    "/api/pair",
    { method: "POST", body: JSON.stringify({ code, device_name: deviceName }) },
    false
  );
  setAuth(data);
  return data;
}

export async function clientStatus() {
  return apiJson("/api/client/status");
}

export async function revokeSelf() {
  try {
    await apiJson("/api/client/revoke", { method: "POST" });
  } finally {
    clearAuth();
  }
}

import { stream } from "./stream.js";

export async function takeScreenshot() {
  const frameBlob = stream.getLatestFrameBlob();
  if (frameBlob) {
    return {
      blob: frameBlob,
      timestamp: Date.now() / 1000,
      laptop: getLaptopName() || "Laptop",
    };
  }
  const res = await request("/api/screenshot");
  const blob = await res.blob();
  return {
    blob,
    timestamp: parseFloat(res.headers.get("X-RV-Timestamp") || "0") || Date.now() / 1000,
    laptop: res.headers.get("X-RV-Laptop") || getLaptopName() || "Laptop",
  };
}

export async function aiDescribe(prompt) {
  const data = await apiJson("/api/ai/describe", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
  return data.text;
}

// AI agent chat: question + N compressed screen captures -> answer
export async function aiChat(prompt, images, history) {
  const data = await apiJson("/api/ai/chat", {
    method: "POST",
    body: JSON.stringify({ prompt, images, history }),
  });
  return data.text;
}
