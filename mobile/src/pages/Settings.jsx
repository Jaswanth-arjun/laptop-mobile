import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import BottomNav from "../components/BottomNav.jsx";
import { ToastHost, useToast } from "../components/Toast.jsx";
import { clientStatus, getLaptopName, revokeSelf, setDeviceName } from "../services/api.js";
import { stream } from "../services/stream.js";

export default function Settings() {
  const navigate = useNavigate();
  const { toasts, show } = useToast();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [autoAdapt, setAutoAdapt] = useState(localStorage.getItem("rv_auto_adapt") !== "off");
  const [quality, setQuality] = useState(parseInt(localStorage.getItem("rv_quality") || "0", 10) || 60);
  const [name, setName] = useState(localStorage.getItem("rv_device_name") || "");

  useEffect(() => {
    clientStatus()
      .then(setInfo)
      .catch((e) => setError(e.message));
  }, []);

  const reconnect = () => {
    stream.reconnect();
    show("Reconnecting to laptop…");
  };

  const removeDevice = async () => {
    try {
      await revokeSelf();
    } catch {
      // token may already be invalid; clear locally regardless
    }
    stream.disconnect();
    show("Device removed from laptop", "success");
    navigate("/home", { replace: true });
  };

  const saveStreaming = () => {
    localStorage.setItem("rv_auto_adapt", autoAdapt ? "on" : "off");
    localStorage.setItem("rv_quality", String(quality));
    stream.setConfig({ autoAdapt, quality });
    show("Streaming preferences applied", "success");
  };

  const saveName = () => {
    setDeviceName(name.trim() || "My phone");
    show("Phone name saved (used next time you pair)", "success");
  };

  return (
    <div className="page">
      <h1 style={{ fontSize: 20, marginBottom: 16 }}>Settings</h1>

      {error && <div className="banner red">{error}</div>}

      <div className="card">
        <h2>Connected laptop</h2>
        <div className="kv"><span>Laptop name</span><span>{info?.laptop_name || getLaptopName() || "—"}</span></div>
        <div className="kv"><span>Resolution</span><span>{info?.resolution ? info.resolution.width + " × " + info.resolution.height : "—"}</span></div>
        <div className="kv"><span>Screen sharing</span><span className={"pill " + (info?.sharing ? "on" : "off")}>{info?.sharing ? "active" : "off"}</span></div>
        <div className="kv"><span>Devices connected</span><span>{info?.connected_devices ?? "—"}</span></div>
        <div style={{ height: 12 }} />
        <button className="btn secondary" onClick={reconnect}>Reconnect now</button>
      </div>

      <div className="card">
        <h2>Streaming preferences</h2>
        <label style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 0 }}>
          <input
            type="checkbox"
            checked={autoAdapt}
            onChange={(e) => setAutoAdapt(e.target.checked)}
            style={{ width: 18, height: 18 }}
          />
          <span style={{ color: "var(--text)", fontSize: 14 }}>Auto-adjust quality for smooth streaming</span>
        </label>
        <label>JPEG quality ({quality})</label>
        <input
          type="range"
          min="20"
          max="95"
          value={quality}
          onChange={(e) => setQuality(parseInt(e.target.value, 10))}
          style={{ width: "100%" }}
        />
        <div style={{ height: 12 }} />
        <button className="btn" onClick={saveStreaming}>Apply</button>
      </div>

      <div className="card">
        <h2>This phone</h2>
        <label>Phone name</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Pixel 8" />
        <div style={{ height: 12 }} />
        <button className="btn secondary" onClick={saveName}>Save name</button>
      </div>

      <div className="card">
        <h2>Security</h2>
        <div className="muted" style={{ marginBottom: 10 }}>
          Removing this phone revokes its access token on the laptop immediately. The laptop user can also
          disconnect you at any time from the dashboard.
        </div>
        <button className="btn danger" onClick={removeDevice}>Remove this device from laptop</button>
      </div>

      <div className="card">
        <h2>About</h2>
        <div className="muted">
          RemoteView streams your laptop screen over your local Wi-Fi only. Nothing is sent to the internet.
          Screenshots stay on this phone unless you share them.
        </div>
      </div>

      <ToastHost toasts={toasts} />
      <BottomNav />
    </div>
  );
}
