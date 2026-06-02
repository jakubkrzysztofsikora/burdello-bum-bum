import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API proxy target is env-configurable so the same config works for local
// `npm run dev` (default localhost:8000) and the Docker stack, where the
// backend is reachable as http://backend:8000.
const apiTarget = process.env.VITE_API_PROXY || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    proxy: {
      "/api": apiTarget,
    },
  },
});
