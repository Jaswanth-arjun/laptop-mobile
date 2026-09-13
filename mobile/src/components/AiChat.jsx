// AI agent chat for the live screen.
//  [+] captures the current laptop screen into the chat (tap again for more)
//  [rocket/send] sends all captured screens + your question to the AI
//  (via the laptop backend -> OpenRouter; the API key stays on the laptop)

import { useEffect, useRef, useState } from "react";
import { aiChat } from "../services/api.js";
import { chatStore } from "../services/chatStore.js";
import { stream } from "../services/stream.js";
import { compressScreenshot } from "../utils/image.js";

function formatMessageText(text) {
  if (!text) return null;
  const lines = text.split("\n");
  return lines.map((line, idx) => {
    const parts = line.split(/(\*\*.*?\*\*)/g);
    const renderedParts = parts.map((part, pIdx) => {
      if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
        return <strong key={pIdx}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });
    return (
      <span key={idx}>
        {renderedParts}
        {idx < lines.length - 1 && <br />}
      </span>
    );
  });
}

export default function AiChat({ onOpenChange }) {
  const [messages, setMessages] = useState(chatStore.get());
  const [pending, setPending] = useState([]); // {id, dataUrl, thumbUrl}
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [open, setOpen] = useState(false);
  const [viewer, setViewer] = useState(null);
  const listRef = useRef(null);
  const idRef = useRef(0);

  useEffect(() => chatStore.subscribe(setMessages), []);
  useEffect(() => {
    if (onOpenChange) onOpenChange(open);
  }, [open, onOpenChange]);
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, busy, open]);

  const capture = async () => {
    setCapturing(true);
    try {
      const frameBlob = stream.getLatestFrameBlob();
      if (!frameBlob) {
        throw new Error("No live screen frame available yet on mobile. Wait a moment for stream.");
      }
      const { dataUrl, thumbUrl } = await compressScreenshot(frameBlob);
      const item = { id: "c_" + Date.now() + "_" + ++idRef.current, dataUrl, thumbUrl };
      setPending((p) => [...p, item]);
      setOpen(true);
    } catch (e) {
      chatStore.add({ id: "e_" + Date.now(), role: "assistant", text: "Capture failed: " + e.message, error: true });
      setOpen(true);
    } finally {
      setCapturing(false);
    }
  };

  const removePending = (id) => setPending((p) => p.filter((x) => x.id !== id));

  const send = async () => {
    const prompt = input.trim();
    if (busy || (!prompt && pending.length === 0)) return;
    const images = pending.map((p) => p.dataUrl);
    const history = messages
      .filter((m) => !m.error && (m.text || "").trim())
      .slice(-12)
      .map((m) => ({ role: m.role, content: m.text }));

    chatStore.add({
      id: "u_" + Date.now(),
      role: "user",
      text: prompt,
      images: pending.map((p) => ({ thumbUrl: p.thumbUrl, dataUrl: p.dataUrl })),
    });
    setInput("");
    setPending([]);
    setOpen(true);
    setBusy(true);
    chatStore.add({ id: "a_" + Date.now(), role: "assistant", text: "", pending: true });
    try {
      const text = await aiChat(prompt, images, history);
      chatStore.updateLast({ text: text || "(empty answer)", pending: false });
    } catch (e) {
      chatStore.updateLast({ text: e.message, pending: false, error: true });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="chatdock" onClick={(e) => e.stopPropagation()}>
      {open && (
        <div className="chat-panel">
          <div className="chat-panel-head">
            <b>AI Assistant</b>
            <span className="muted">{messages.length} messages</span>
            <button className="tool-btn" onClick={() => chatStore.clear()}>Clear</button>
            <button className="tool-btn" onClick={() => setOpen(false)}>▾</button>
          </div>
          <div className="chat-list" ref={listRef}>
            {messages.length === 0 && (
              <div className="muted chat-hint">
                Tap <b>+</b> to capture the laptop screen into the chat (tap again for more screens), type your
                question, then press <b>➤</b> for an AI answer.
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={"msg " + m.role + (m.error ? " error" : "")}>
                {m.images && m.images.length > 0 && (
                  <div className="msg-images">
                    {m.images.map((im, i) => (
                      <img key={i} src={im.thumbUrl} alt="Screen capture" onClick={() => setViewer(im.dataUrl)} />
                    ))}
                  </div>
                )}
                {m.pending && <div className="typing"><span /><span /><span /></div>}
                {m.text && <div className="bubble">{formatMessageText(m.text)}</div>}
              </div>
            ))}
            {busy && !messages.some((m) => m.pending) && <div className="typing"><span /><span /><span /></div>}
          </div>
        </div>
      )}

      {viewer && (
        <div className="modal-back" onClick={() => setViewer(null)}>
          <img className="shot-full" src={viewer} alt="Capture full view" />
        </div>
      )}

      {pending.length > 0 && (
        <div className="chat-captures">
          {pending.map((p) => (
            <div className="chip" key={p.id}>
              <img src={p.thumbUrl} alt="Queued capture" />
              <button onClick={() => removePending(p.id)}>×</button>
            </div>
          ))}
          <span className="muted chip-note">{pending.length} screen{pending.length > 1 ? "s" : ""} ready</span>
        </div>
      )}

      <div className="chat-bar">
        <button
          className="chat-plus"
          onClick={capture}
          disabled={capturing || busy}
          title="Capture laptop screen"
        >
          {capturing ? "…" : "+"}
        </button>
        <input
          type="text"
          placeholder="Ask AI about this screen…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
          onFocus={() => setOpen(true)}
        />
        <button className="chat-send" onClick={send} disabled={busy || (!input.trim() && pending.length === 0)}>
          {busy ? "…" : "➤"}
        </button>
      </div>
    </div>
  );
}
