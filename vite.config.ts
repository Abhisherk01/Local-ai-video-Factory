import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Browser dev mode talks to the backend through this proxy so the WebView
// never needs to know the port. Inside Tauri, the shell provides the real
// port + session token via the get_backend_info command (ADR-008).
const backendPort = process.env.LAF_PORT ?? "8756";

export default defineConfig({
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/laf-api": {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/laf-api/, ""),
        headers: { "X-LAF-Token": process.env.LAF_TOKEN ?? "dev-token" },
      },
    },
  },
  build: {
    target: "es2022",
  },
  plugins: [react(), tailwindcss()],
});
