import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API is proxied, so the browser sees a single origin. That keeps the
// SameSite=Strict, HttpOnly refresh cookie working and means no CORS configuration is needed.
// (In Docker, nginx does the same job.)
const backend = process.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/health": backend,
    },
  },
});
