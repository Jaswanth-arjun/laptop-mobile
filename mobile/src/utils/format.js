export function formatDateTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) +
    " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function fileSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(2) + " MB";
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function screenshotFilename(item) {
  const d = new Date(item.ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return (
    "remoteview-" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) +
    "-" + pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds()) + ".jpg"
  );
}

export async function shareBlob(blob, filename, title) {
  const nav = navigator;
  if (nav.canShare && nav.canShare({ files: [new File([blob], filename, { type: blob.type })] })) {
    try {
      const file = new File([blob], filename, { type: blob.type });
      await nav.share({ files: [file], title: title || "RemoteView screenshot" });
      return true;
    } catch (e) {
      if (e && e.name === "AbortError") return true;
    }
  }
  // fallback: download
  downloadBlob(blob, filename);
  return false;
}
