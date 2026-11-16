import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      // 开发期把 /api 转发到后端 8000
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
    watch: {
      // 编辑器的原子写入会生成 .xxx.tmpdir / *.tmp，watcher 撞上会 EBUSY 崩溃
      ignored: ["**/.*.tmpdir/**", "**/*.tmpdir/**", "**/*.tmp", "**/.*.swp"],
    },
  },
});
