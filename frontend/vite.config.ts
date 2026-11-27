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
      // 编辑器的原子写入会生成临时文件，watcher 撞上会 EBUSY 直接崩掉 dev server。
      // 注意 glob **大小写敏感**：Windows 上常见的是大写 `.TMP` 与 `~RFxxxx.TMP`，
      // 只写 "**/*.tmp" 拦不住（本项目已因此崩过一次）。
      ignored: [
        "**/.*.tmpdir/**", "**/*.tmpdir/**",
        "**/*.tmp", "**/*.TMP", "**/*.Tmp",
        "**/~$*", "**/*~RF*",
        "**/.*.swp",
      ],
    },
  },
});
