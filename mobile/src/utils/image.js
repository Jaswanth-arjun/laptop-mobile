// Image helpers for the AI chat captures.

export async function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(new Error("Could not read image"));
    r.readAsDataURL(blob);
  });
}

// Downscale + re-encode a screenshot blob so chat requests stay small
// (~100 KB per capture) while remaining readable for the AI.
export async function compressScreenshot(blob, maxWidth = 1280, quality = 0.55) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(blob);
  } catch {
    return { dataUrl: await blobToDataUrl(blob), thumbUrl: URL.createObjectURL(blob) };
  }
  const scale = Math.min(1, maxWidth / bitmap.width);
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  canvas.getContext("2d").drawImage(bitmap, 0, 0, w, h);
  const dataUrl = canvas.toDataURL("image/jpeg", quality);
  // small thumbnail for chips/bubbles
  const tScale = Math.min(1, 320 / bitmap.width);
  const tw = Math.max(1, Math.round(bitmap.width * tScale));
  const th = Math.max(1, Math.round(bitmap.height * tScale));
  const tCanvas = document.createElement("canvas");
  tCanvas.width = tw;
  tCanvas.height = th;
  tCanvas.getContext("2d").drawImage(bitmap, 0, 0, tw, th);
  const thumbUrl = tCanvas.toDataURL("image/jpeg", 0.6);
  if (bitmap.close) bitmap.close();
  return { dataUrl, thumbUrl };
}
