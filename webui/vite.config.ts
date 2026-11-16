import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Base URL 为空字符串（同源）。开发期通过 Vite dev server 的 /api 代理转发到后端；
// 后端（laa_core/bridge/http_server.py）就绪后只需调整下方 target 端口。
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8123",
        changeOrigin: true,
      },
    },
  },
});