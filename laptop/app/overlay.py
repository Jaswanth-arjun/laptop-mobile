"""Visible on-screen indicator while screen sharing is active.

Runs a tiny always-on-top tkinter window in its own thread. The laptop user
always sees who is connected and can disconnect instantly.
"""
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont


class ShareOverlay:
    def __init__(self, on_disconnect=None):
        self._queue: queue.Queue = queue.Queue()
        self._on_disconnect = on_disconnect
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # called from any thread
    def update(self, text: str) -> None:
        self._queue.put(text)

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="rv-overlay", daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._queue.put(None)

    # ------------------------------------------------------------ internals
    def _run(self) -> None:
        try:
            import tkinter as tk
        except ImportError:
            return
        root = tk.Tk()
        root.title("RemoteView")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        try:
            root.attributes("-toolwindow", True)
        except Exception:
            pass

        bold = tkfont.Font(weight="bold")
        status = tk.Label(root, text="Screen sharing active", fg="white", bg="#c62828",
                          font=bold, padx=14, pady=6)
        status.pack(fill="both")
        info = tk.Label(root, text="No device connected", fg="#222", bg="#ffe9a8",
                        padx=14, pady=4)
        info.pack(fill="both")
        btn = tk.Button(root, text="Disconnect mobile", command=self._on_disconnect,
                        bg="#37474f", fg="white", relief="flat", cursor="hand2")
        btn.pack(fill="both", padx=10, pady=8)

        def poll():
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                item = "__keep__"
            if item is None:
                root.destroy()
                return
            if item != "__keep__":
                info.config(text=item)
            connected = item != "No device connected" and item != "__keep__"
            if connected:
                status.config(text="SCREEN SHARING ACTIVE", bg="#c62828")
            root.after(400, poll)

        root.after(200, poll)
        root.mainloop()

    def _on_disconnect(self):
        if self._on_disconnect:
            try:
                self._on_disconnect()
            except Exception:
                pass
