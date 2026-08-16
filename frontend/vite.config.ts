import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 3300,
    strictPort: true,
    watch: {
      usePolling: true,
      interval: 250,
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8310",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8310",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4300,
  },
});
