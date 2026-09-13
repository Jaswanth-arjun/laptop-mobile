import { Navigate, Outlet, useLocation } from "react-router-dom";
import { getToken } from "./services/api.js";

// Layout shell: pages render full-screen; bottom nav lives inside each page
// so Live can hide it in fullscreen mode.
export default function App() {
  return <Outlet />;
}
