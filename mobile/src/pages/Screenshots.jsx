import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import BottomNav from "../components/BottomNav.jsx";
import { ToastHost, useToast } from "../components/Toast.jsx";
import { deleteScreenshot, listScreenshots } from "../services/db.js";
import { aiChat } from "../services/api.js";
import { compressScreenshot } from "../utils/image.js";
import { downloadBlob, formatDateTime, screenshotFilename, shareBlob } from "../utils/format.js";
export default function Screenshots() {
  const navigate = useNavigate();
  const { toasts, show } = useToast();
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(null);
  const [aiText, setAiText] = useState("");
  const [aiBusy, setAiBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setItems(await listScreenshots());
    } catch {
      show("Could not read screenshot history from this device", "error");
    }
  }, [show]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const [urls, setUrls] = useState({});

  useEffect(() => {
    const next = {};
    items.forEach((it) => {
      next[it.id] = URL.createObjectURL(it.blob);
    });
    setUrls(next);
    return () => Object.values(next).forEach((u) => URL.revokeObjectURL(u));
  }, [items]);

  const openShot = (item) => {
    setOpen(item);
    setAiText("");
  };

  const doSave = async (item) => {
    downloadBlob(item.blob, screenshotFilename(item));
    show("Saved to your downloads", "success");
  };

  const doShare = async (item) => {
    const fellBack = await shareBlob(item.blob, screenshotFilename(item), "RemoteView screenshot");
    if (!fellBack) show("Sharing not supported here — saved to downloads instead");
  };

  const doDelete = async (item) => {
    await deleteScreenshot(item.id);
    setOpen(null);
    await refresh();
    show("Screenshot deleted");
  };

  const doAi = async () => {
    if (!open) return;
    setAiBusy(true);
    setAiText("");
    try {
      const { dataUrl } = await compressScreenshot(open.blob);
      const text = await aiChat("Briefly describe what is visible in this screenshot.", [dataUrl], []);
      setAiText(text || "(empty response)");
    } catch (e) {
      setAiText("AI unavailable: " + e.message);
    } finally {
      setAiBusy(false);
    }
  };

  return (
    <div className="page">
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Screenshots</h1>
      <p className="muted" style={{ marginBottom: 16 }}>
        Stored locally on this phone. Tap a screenshot to open it.
      </p>

      {items.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 28 }}>
          <div style={{ fontSize: 34, marginBottom: 8 }}>📷</div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>No screenshots yet</div>
          <div className="muted">
            Open the live view and press <b>Take Laptop Screenshot</b>. Captures will appear here.
          </div>
          <div style={{ height: 14 }} />
          <button className="btn small" onClick={() => navigate("/live")}>Open live view</button>
        </div>
      ) : (
        <div className="shot-grid">
          {items.map((it) => (
            <div className="shot" key={it.id}>
              <img src={urls[it.id]} alt="Laptop screenshot" loading="lazy" onClick={() => openShot(it)} />
              <div className="meta" onClick={() => openShot(it)}>
                <b>{it.laptop}</b>
                {formatDateTime(it.ts)}
              </div>
              <div className="actions">
                <button onClick={() => doSave(it)}>Save</button>
                <button onClick={() => doShare(it)}>Share</button>
                <button className="danger" onClick={() => doDelete(it)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {open && (
        <div className="modal-back">
          <img className="shot-full" src={urls[open.id]} alt="Screenshot full view" />
          {aiText && <div className="ai-box">{aiText}</div>}
          <div className="modal-bar">
            <button className="btn secondary" onClick={doAi} disabled={aiBusy}>
              {aiBusy ? "…" : "AI"}
            </button>
            <button className="btn secondary" onClick={() => doSave(open)}>Save</button>
            <button className="btn secondary" onClick={() => doShare(open)}>Share</button>
            <button className="btn danger" onClick={() => doDelete(open)}>Delete</button>
            <button className="btn" onClick={() => setOpen(null)}>Close</button>
          </div>
        </div>
      )}

      <ToastHost toasts={toasts} />
      <BottomNav />
    </div>
  );
}
