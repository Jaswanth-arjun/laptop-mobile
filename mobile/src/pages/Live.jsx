import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import AiChat from "../components/AiChat.jsx";
import ScreenCanvas from "../components/ScreenCanvas.jsx";
import StatusPill from "../components/StatusPill.jsx";
import { ToastHost, useToast } from "../components/Toast.jsx";
import { clientStatus, getToken } from "../services/api.js";
import { stream } from "../services/stream.js";

export default function Live() {
  const navigate = useNavigate();
  const { toasts, show } = useToast();
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const [status, setStatus] = useState(stream.getStatus());
  const [meta, setMeta] = useState({ laptop: "", resolution: null, sharing: true });
  const [captureError, setCaptureError] = useState("");
  const [fatal, setFatal] = useState("");
  const [hasFrame, setHasFrame] = useState(false);
  const [hudVisible, setHudVisible] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);

  // ------------------------------------------------------------- stream
  useEffect(() => {
    const token = getToken();
    if (!token) {
      navigate("/home", { replace: true });
      return undefined;
    }
    stream.setConfig({ autoAdapt: localStorage.getItem("rv_auto_adapt") !== "off" });
    stream.connect(token);

    const offStatus = stream.onStatus(setStatus);
    const offFrame = stream.onFrame(() => setHasFrame(true));
    const offMsg = stream.onMessage((msg) => {
      if (msg.type === "sharing_disabled") {
        setFatal("Screen sharing was stopped on the laptop. Press Reconnect once sharing is enabled again.");
        stream.disconnect();
      } else if (msg.type === "capture_error") {
        setCaptureError(msg.message || "The laptop could not capture the screen.");
      } else if (msg.type === "unauthorized") {
        setFatal("This phone is no longer authorized. Please pair again.");
        stream.disconnect();
      } else if (msg.type === "revoked") {
        setFatal("Access was revoked from the laptop dashboard.");
        stream.disconnect();
      }
    });

    clientStatus()
      .then((s) => {
        setMeta({ laptop: s.laptop_name, resolution: s.resolution, sharing: s.sharing });
        if (s.capture_error) setCaptureError(s.capture_error);
      })
      .catch((e) => {
        if (e.status === 401) {
          navigate("/home", { replace: true });
        } else {
          show(e.message, "error");
        }
      });

    return () => {
      offStatus();
      offFrame();
      offMsg();
      stream.disconnect();
    };
  }, [navigate, show]);

  const reconnect = useCallback(() => {
    setFatal("");
    setCaptureError("");
    setHasFrame(false);
    stream.reconnect();
    clientStatus()
      .then((s) => setMeta({ laptop: s.laptop_name, resolution: s.resolution, sharing: s.sharing }))
      .catch(() => {});
  }, []);

  // wake the server up if it went idle while we were away
  useEffect(() => {
    const t = setInterval(() => {
      if (status === "connected") stream.forceFullFrame();
    }, 15000);
    return () => clearInterval(t);
  }, [status]);

  // hide the top bar after a few seconds, like a video player
  useEffect(() => {
    if (!hudVisible || chatOpen) return undefined;
    const t = setTimeout(() => setHudVisible(false), 5000);
    return () => clearTimeout(t);
  }, [hudVisible, chatOpen]);

  const toggleHud = () => {
    if (chatOpen) return; // chat dock owns taps while open
    setHudVisible((v) => !v);
  };

  const disconnected = status !== "connected";

  return (
    <div className="live-root" ref={containerRef} onClick={toggleHud}>
      <ScreenCanvas active={!fatal} scale={1} offset={{ x: 0, y: 0 }} canvasRef={canvasRef} />

      {!hasFrame && !fatal && (
        <div className="center-fallback">
          {disconnected ? (
            <>
              <div className="spinner" />
              <div style={{ fontWeight: 600 }}>
                {status === "connecting" ? "Connecting to your laptop…" : "Connection lost — reconnecting…"}
              </div>
              <div className="muted">
                Check that RemoteView is running on the laptop and both devices are on the same Wi-Fi.
              </div>
              <button className="btn small" onClick={reconnect}>
                Reconnect now
              </button>
            </>
          ) : (
            <>
              <div className="spinner" />
              <div style={{ fontWeight: 600 }}>Waiting for the first frame…</div>
              <div className="muted">If this takes long, press Reconnect or lower quality in Settings.</div>
              <button className="btn small" onClick={reconnect}>Reconnect</button>
            </>
          )}
        </div>
      )}

      {fatal && (
        <div className="center-fallback">
          <div className="banner red" style={{ maxWidth: 420 }}>{fatal}</div>
          <button className="btn small" onClick={() => navigate("/home")}>
            Go to pairing
          </button>
          <button className="btn small secondary" onClick={reconnect}>
            Reconnect
          </button>
        </div>
      )}

      <div className={"live-top" + (hudVisible ? "" : " hidden")}>
        <button className="tool-btn" onClick={(e) => { e.stopPropagation(); navigate(-1); }}>
          ‹ Back
        </button>
        <span style={{ fontWeight: 700, flex: 1, textShadow: "0 1px 2px #000" }}>
          {meta.laptop || "Laptop"}
        </span>
        <span onClick={(e) => e.stopPropagation()}>
          <StatusPill status={status} />
        </span>
      </div>

      <AiChat onOpenChange={setChatOpen} />

      <ToastHost toasts={toasts} />
    </div>
  );
}
