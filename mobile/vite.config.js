import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  css: {
    postcss: {},
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8756", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8756", ws: true },
    },
  },
  build: {
    outDir: "dist",
    assetsInlineLimit: 0,
  },
});
