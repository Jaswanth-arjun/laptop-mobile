import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getDeviceName, pair, setDeviceName as persistName, getToken } from "../services/api.js";
import { ToastHost, useToast } from "../components/Toast.jsx";

export default function Home({ autoPair = false }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { toasts, show } = useToast();
  const [code, setCode] = useState(params.get("code") || "");
  const [name, setName] = useState(getDeviceName());
  const [busy, setBusy] = useState(false);
  const [pairError, setPairError] = useState("");
  const [scanning, setScanning] = useState(!!params.get("code"));

  // already paired -> go straight to live view
  useEffect(() => {
    if (getToken()) navigate("/live", { replace: true });
  }, [navigate]);

  const doPair = async (pairCode) => {
    const clean = (pairCode || "").trim();
    if (!/^\d{4,8}$/.test(clean)) {
      setPairError("Enter the 6-digit pairing code shown on your laptop dashboard.");
      return;
    }
    setBusy(true);
    setPairError("");
    try {
      const deviceName = name.trim() || "My phone";
      persistName(deviceName);
      await pair(clean, deviceName);
      show("Paired successfully", "success");
      navigate("/live", { replace: true });
    } catch (e) {
      setPairError(e.message);
      setScanning(false);
    } finally {
      setBusy(false);
    }
  };

  // QR flow: URL contains ?code=NNNNNN -> pair automatically once
  useEffect(() => {
    if (autoPair && code && !busy && !getToken()) {
      doPair(code);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPair, code]);

  // if a code arrived via URL but component mounted without autoPair, still try
  useEffect(() => {
    if (params.get("code") && !autoPair) setScanning(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="page" style={{ paddingTop: 40 }}>
      <div className="logo" style={{ marginBottom: 26 }}>
        <div className="logo-badge">RV</div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 20 }}>RemoteView</div>
          <div className="muted">View your laptop from your phone</div>
        </div>
      </div>

      {scanning && (
        <div className="banner yellow">
          Pairing code detected from QR scan. Make sure RemoteView is running on your laptop, then confirm below.
        </div>
      )}

      <div className="card">
        <h2>Connect to your laptop</h2>
        <div className="muted" style={{ marginBottom: 4 }}>
          1. Open the RemoteView dashboard on your laptop.<br />
          2. Scan the QR code with your phone camera, or type the pairing code below.
        </div>

        {pairError && <div className="banner red" style={{ marginTop: 12 }}>{pairError}</div>}

        <label>Pairing code</label>
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="e.g. 481902"
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 8))}
        />

        <label>This phone's name</label>
        <input type="text" placeholder="e.g. Pixel 8" value={name} onChange={(e) => setName(e.target.value)} />

        <div style={{ height: 16 }} />
        <button className="btn" disabled={busy} onClick={() => doPair(code)}>
          {busy ? "Pairing…" : "Connect to laptop"}
        </button>
      </div>

      <div className="card">
        <h2>No pairing code?</h2>
        <div className="muted">
          On your laptop, run <b>python main.py</b> inside the <b>laptop</b> folder. A dashboard opens in your
          browser showing a QR code and a 6-digit pairing code. Codes expire after 5 minutes for your security.
        </div>
      </div>

      <div className="card">
        <h2>Different network?</h2>
        <div className="muted" style={{ marginBottom: 8 }}>
          Not on the same Wi-Fi? Use <b>Cloud Relay</b> to connect from anywhere.
        </div>
        <button className="btn secondary" onClick={() => navigate("/relay")}>
          Connect via Cloud Relay
        </button>
      </div>

      <ToastHost toasts={toasts} />
    </div>
  );
}
