import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, /api calls are forwarded to the FastAPI backend, so the browser sees one
// origin (no CORS setup needed locally). In production set VITE_API_URL instead.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 127.0.0.1, not "localhost": Node 17+ resolves localhost to IPv6 ::1 first, but uvicorn
      // listens on IPv4 only -> "ECONNREFUSED ::1:8000".
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
