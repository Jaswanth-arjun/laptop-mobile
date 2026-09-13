// Screenshot history stored locally on the phone in IndexedDB.

const DB_NAME = "remoteview";
const STORE = "screenshots";

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: "id" });
        store.createIndex("ts", "ts");
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("IndexedDB unavailable"));
  });
}

function tx(db, mode) {
  return db.transaction(STORE, mode).objectStore(STORE);
}

export async function saveScreenshot({ blob, timestamp, laptop, width, height }) {
  const db = await openDb();
  const item = {
    id: "s_" + Date.now() + "_" + Math.floor(Math.random() * 1e6),
    ts: timestamp || Date.now() / 1000,
    laptop: laptop || "Laptop",
    blob,
    width: width || 0,
    height: height || 0,
  };
  return new Promise((resolve, reject) => {
    const r = tx(db, "readwrite").add(item);
    r.onsuccess = () => resolve(item);
    r.onerror = () => reject(r.error);
  });
}

export async function listScreenshots() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const r = tx(db, "readonly").getAll();
    r.onsuccess = () => resolve((r.result || []).sort((a, b) => b.ts - a.ts));
    r.onerror = () => reject(r.error);
  });
}

export async function deleteScreenshot(id) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const r = tx(db, "readwrite").delete(id);
    r.onsuccess = () => resolve(true);
    r.onerror = () => reject(r.error);
  });
}

export async function clearScreenshots() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const r = tx(db, "readwrite").clear();
    r.onsuccess = () => resolve(true);
    r.onerror = () => reject(r.error);
  });
}
