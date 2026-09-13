import { useEffect, useRef, useState } from "react";

// Zoom & pan state for the screen canvas. Supports pinch gestures,
// double-tap zoom and +/- buttons. Returns handlers to attach to the canvas.
export function useZoom(maxScale = 5) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const gesture = useRef(null);
  const wrapRef = useRef(null);

  const clampOffset = (s, o) => {
    const el = wrapRef.current;
    if (!el) return o;
    const maxX = Math.max(0, (el.clientWidth * (s - 1)) / 2);
    const maxY = Math.max(0, (el.clientHeight * (s - 1)) / 2);
    return {
      x: Math.min(maxX, Math.max(-maxX, o.x)),
      y: Math.min(maxY, Math.max(-maxY, o.y)),
    };
  };

  const applyScale = (s, o) => {
    const cs = Math.min(maxScale, Math.max(1, s));
    setScale(cs);
    setOffset(cs === 1 ? { x: 0, y: 0 } : clampOffset(cs, o));
  };

  const zoomIn = () => applyScale(scale + 0.5, offset);
  const zoomOut = () => applyScale(scale - 0.5, offset);
  const fit = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };
  const toggleZoom = () => (scale > 1 ? fit() : applyScale(2, offset));

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;

    const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);

    const onStart = (e) => {
      if (e.touches.length === 2) {
        gesture.current = { mode: "pinch", startDist: dist(e.touches), startScale: scale };
        e.preventDefault();
      } else if (e.touches.length === 1 && scale > 1) {
        gesture.current = { mode: "pan", lastX: e.touches[0].clientX, lastY: e.touches[0].clientY };
      }
    };
    const onMove = (e) => {
      const g = gesture.current;
      if (!g) return;
      if (g.mode === "pinch" && e.touches.length === 2) {
        const ratio = dist(e.touches) / g.startDist;
        applyScale(g.startScale * ratio, offset);
        e.preventDefault();
      } else if (g.mode === "pan" && e.touches.length === 1) {
        const dx = e.touches[0].clientX - g.lastX;
        const dy = e.touches[0].clientY - g.lastY;
        g.lastX = e.touches[0].clientX;
        g.lastY = e.touches[0].clientY;
        applyScale(scale, { x: offset.x + dx, y: offset.y + dy });
        e.preventDefault();
      }
    };
    const onEnd = () => {
      gesture.current = null;
    };

    el.addEventListener("touchstart", onStart, { passive: false });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd);
    el.addEventListener("touchcancel", onEnd);
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", onEnd);
    };
  }, [scale, offset]);

  return { scale, offset, zoomIn, zoomOut, fit, toggleZoom, wrapRef, setTransform: applyScale };
}
