import { useCallback, useRef, useState } from "react";

let toastId = 0;

export function useToast() {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});

  const show = useCallback((message, kind = "info", ms = 3200) => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, message, kind }]);
    timers.current[id] = setTimeout(() => {
      setToasts((t) => t.filter((x) => x.id !== id));
      delete timers.current[id];
    }, ms);
  }, []);

  return { toasts, show };
}

export function ToastHost({ toasts }) {
  return (
    <div className="toast-host">
      {toasts.map((t) => (
        <div key={t.id} className={"toast " + t.kind}>
          {t.message}
        </div>
      ))}
    </div>
  );
}
