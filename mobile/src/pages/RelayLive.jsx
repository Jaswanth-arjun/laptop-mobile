/**
 * RelayLive — live screen view connected through the cloud relay.
 * Similar to Live.jsx but uses the relay WebSocket instead of direct connection.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import AiChat from "../components/AiChat.jsx";
import ScreenCanvas from "../components/ScreenCanvas.jsx";
import StatusPill from "../components/StatusPill.jsx";
import { ToastHost, useToast } from "../components/Toast.jsx";
import { relay, getRelayUrl, getRoomCode, getLaptopName, relayTakeScreenshot, relayAiChat } from "../services/relay.js";

export default function RelayLive() {
  const navigate = useNavigate();
  const { toasts, show } = useToast();
  const canvasRef = useRef(null);
  const [status, setStatus] = useState(relay.getStatus());
  const [meta, setMeta] = useState({ laptop: "", sharing: true });
  const [fatal, setFatal] = useState("");
  const [hasFrame, setHasFrame] = useState(false);
  const [hudVisible, setHudVisible] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);

  // ─── Connect to relay ───
  useEffect(() => {
    const relayUrl = getRelayUrl();
    const code = getRoomCode();
    if (!relayUrl || !code) {
      navigate("/relay", { replace: true });
      return undefined;
    }

    relay.connect(relayUrl, code, "Mobile");

    const offStatus = relay.onStatus(setStatus);
    const offFrame = relay.onFrame(() => setHasFrame(true));
    const offMsg = relay.onMessage((msg) => {
      if (msg.type === "joined") {
        setMeta({ laptop: msg.laptop_name || "Laptop", sharing: msg.sharing });
      } else if (msg.type === "sharing_disabled") {
        setFatal("Screen sharing was stopped on the laptop.");
        relay.disconnect();
      } else if (msg.type === "room_closed") {
        setFatal("The laptop disconnected. The room is closed.");
        relay.disconnect();
      } else if (msg.type === "error") {
        setFatal(msg.message || "Connection error");
        relay.disconnect();
      }
    });

    return () => {
      offStatus();
      offFrame();
      offMsg();
      relay.disconnect();
    };
  }, [navigate]);

  const reconnect = useCallback(() => {
    setFatal("");
    setHasFrame(false);
    relay.reconnect();
  }, []);

  // keep-alive ping
  useEffect(() => {
    const t = setInterval(() => {
      if (status === "connected") relay.forceFullFrame();
    }, 15000);
    return () => clearInterval(t);
  }, [status]);

  // auto-hide HUD
  useEffect(() => {
    if (!hudVisible || chatOpen) return undefined;
    const t = setTimeout(() => setHudVisible(false), 5000);
    return () => clearTimeout(t);
  }, [hudVisible, chatOpen]);

  const toggleHud = () => {
    if (chatOpen) return;
    setHudVisible((v) => !v);
  };

  const disconnected = status !== "connected";

  return (
    <div className="live-root" ref={useRef(null)} onClick={toggleHud}>
      <ScreenCanvas active={!fatal} scale={1} offset={{ x: 0, y: 0 }} canvasRef={canvasRef} streamSource={relay} />

      {!hasFrame && !fatal && (
        <div className="center-fallback">
          {disconnected ? (
            <>
              <div className="spinner" />
              <div style={{ fontWeight: 600 }}>
                {status === "connecting" ? "Connecting via relay…" : "Connection lost — reconnecting…"}
              </div>
              <div className="muted">
                Make sure the laptop is running <b>python main.py --relay</b>
              </div>
              <button className="btn small" onClick={reconnect}>
                Reconnect
              </button>
            </>
          ) : (
            <>
              <div className="spinner" />
              <div style={{ fontWeight: 600 }}>Waiting for the first frame…</div>
              <div className="muted">Connected to relay. Waiting for laptop to stream.</div>
              <button className="btn small" onClick={reconnect}>Reconnect</button>
            </>
          )}
        </div>
      )}

      {fatal && (
        <div className="center-fallback">
          <div className="banner red" style={{ maxWidth: 420 }}>{fatal}</div>
          <button className="btn small" onClick={() => navigate("/relay")}>
            Enter new code
          </button>
          <button className="btn small secondary" onClick={reconnect}>
            Reconnect
          </button>
        </div>
      )}

      <div className={"live-top" + (hudVisible ? "" : " hidden")}>
        <button className="tool-btn" onClick={(e) => { e.stopPropagation(); navigate("/relay"); }}>
          ‹ Back
        </button>
        <span style={{ fontWeight: 700, flex: 1, textShadow: "0 1px 2px #000" }}>
          {meta.laptop || "Laptop"} <span className="muted" style={{ fontSize: 11 }}>(relay)</span>
        </span>
        <span onClick={(e) => e.stopPropagation()}>
          <StatusPill status={status} />
        </span>
      </div>

      <AiChat onOpenChange={setChatOpen} relayMode={true} />

      <ToastHost toasts={toasts} />
    </div>
  );
}
