/**
 * RelayJoin — page where mobile users enter a relay URL + room code
 * to connect to a laptop across any network.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ToastHost, useToast } from "../components/Toast.jsx";
import { setRelayUrl, setRoomCode, getRelayUrl, getRoomCode } from "../services/relay.js";

const DEFAULT_RELAY = "wss://remoteview-relay.onrender.com";

export default function RelayJoin() {
  const navigate = useNavigate();
  const { toasts, show } = useToast();
  const [url, setUrl] = useState(getRelayUrl() || DEFAULT_RELAY);
  const [code, setCode] = useState(getRoomCode() || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const doConnect = () => {
    const cleanCode = code.trim();
    const cleanUrl = url.trim();

    if (!cleanUrl) {
      setError("Enter the relay server URL");
      return;
    }
    if (!/^\d{4,8}$/.test(cleanCode)) {
      setError("Enter the 6-digit room code shown on the laptop");
      return;
    }

    setError("");
    setBusy(true);

    // Save and navigate to relay live page
    setRelayUrl(cleanUrl);
    setRoomCode(cleanCode);
    navigate("/relay-live", { replace: true });
  };

  return (
    <div className="page" style={{ paddingTop: 40 }}>
      <div className="logo" style={{ marginBottom: 26 }}>
        <div className="logo-badge">RV</div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 20 }}>RemoteView</div>
          <div className="muted">Connect from anywhere — no Wi-Fi needed</div>
        </div>
      </div>

      <div className="card">
        <h2>Connect via Cloud Relay</h2>
        <div className="muted" style={{ marginBottom: 8 }}>
          1. Run <b>python main.py --relay</b> on the laptop.<br />
          2. Enter the 6-digit room code shown on the laptop below.
        </div>

        {error && <div className="banner red" style={{ marginTop: 12 }}>{error}</div>}

        <label>Relay Server URL</label>
        <input
          type="text"
          placeholder={DEFAULT_RELAY}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />

        <label>Room Code</label>
        <input
          type="text"
          inputMode="numeric"
          placeholder="e.g. 481902"
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 8))}
        />

        <div style={{ height: 16 }} />
        <button className="btn" disabled={busy} onClick={doConnect}>
          {busy ? "Connecting…" : "Connect to Laptop"}
        </button>
      </div>

      <div className="card">
        <h2>Same Wi-Fi? Use local mode instead</h2>
        <div className="muted" style={{ marginBottom: 8 }}>
          If your phone and laptop are on the same network, local mode is faster.
        </div>
        <button className="btn secondary" onClick={() => navigate("/home")}>
          Switch to Local Mode
        </button>
      </div>

      <ToastHost toasts={toasts} />
    </div>
  );
}
