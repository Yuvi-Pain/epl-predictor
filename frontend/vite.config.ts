import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser calls /health on the Vite dev server, which forwards it to the
// backend. Same origin for the browser, so no CORS setup is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/health": process.env.BACKEND_URL ?? "http://localhost:8000",
    },
  },
});
