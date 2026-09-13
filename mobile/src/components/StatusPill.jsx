export default function StatusPill({ status }) {
  const map = {
    connected: { text: "Connected", cls: "pill on" },
    connecting: { text: "Connecting…", cls: "pill wait" },
    disconnected: { text: "Disconnected", cls: "pill off" },
  };
  const s = map[status] || map.disconnected;
  return <span className={s.cls}>{s.text}</span>;
}
