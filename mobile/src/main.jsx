import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App.jsx";
import Home from "./pages/Home.jsx";
import Live from "./pages/Live.jsx";
import RelayJoin from "./pages/RelayJoin.jsx";
import RelayLive from "./pages/RelayLive.jsx";
import Screenshots from "./pages/Screenshots.jsx";
import Settings from "./pages/Settings.jsx";
import { getToken } from "./services/api.js";
import { isRelayMode } from "./services/relay.js";
import "./styles.css";

function RequireAuth({ children }) {
  if (!getToken()) return <Navigate to="/home" replace />;
  return children;
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<Navigate to={isRelayMode() ? "/relay-live" : getToken() ? "/live" : "/home"} replace />} />
          <Route path="home" element={<Home />} />
          <Route path="pair" element={<Home autoPair />} />
          <Route path="relay" element={<RelayJoin />} />
          <Route path="relay-live" element={<RelayLive />} />
          <Route
            path="live"
            element={
              <RequireAuth>
                <Live />
              </RequireAuth>
            }
          />
          <Route
            path="screenshots"
            element={
              <RequireAuth>
                <Screenshots />
              </RequireAuth>
            }
          />
          <Route
            path="settings"
            element={
              <RequireAuth>
                <Settings />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  });
}
