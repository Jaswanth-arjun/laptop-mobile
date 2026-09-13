// Subscribes to the WebSocket stream and paints JPEG frames onto a canvas.
// Canvas backing store matches frame size; CSS transform handles zoom/pan.

import { useEffect, useRef } from "react";
import { stream } from "../services/stream.js";

export default function ScreenCanvas({ active, scale = 1, offset = { x: 0, y: 0 }, canvasRef, onResolution, streamSource }) {
  const localRef = useRef(null);
  const ref = canvasRef || localRef;
  const resCb = useRef(onResolution);
  resCb.current = onResolution;

  // Use provided streamSource or default to local stream
  const source = streamSource || stream;

  useEffect(() => {
    if (!active) return undefined;
    const draw = async (blob) => {
      const canvas = ref.current;
      if (!canvas) return;
      let bitmap = null;
      try {
        if (window.createImageBitmap) {
          bitmap = await createImageBitmap(blob);
        } else {
          const url = URL.createObjectURL(blob);
          bitmap = await new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => resolve(img);
            img.onerror = reject;
            img.src = url;
          }).then((img) => {
            URL.revokeObjectURL(url);
            return img;
          });
        }
      } catch {
        return;
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        if (resCb.current) resCb.current(bitmap.width, bitmap.height);
      }
      ctx.drawImage(bitmap, 0, 0);
      if (bitmap.close) bitmap.close();
    };
    return source.onFrame(draw);
  }, [active, ref, source]);

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
        background: "#000",
        touchAction: "none",
      }}
    >
      <canvas
        ref={ref}
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          maxWidth: "100%",
          maxHeight: "100%",
          width: "auto",
          height: "auto",
          transform: `translate(-50%, -50%) scale(${scale}) translate(${offset.x / (scale || 1)}px, ${offset.y / (scale || 1)}px)`,
          transformOrigin: "center",
          imageRendering: scale > 1.6 ? "pixelated" : "auto",
        }}
      />
    </div>
  );
}
