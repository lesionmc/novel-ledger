import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// A′ 预构建：先构建到本目录 dist，再由 build 脚本拷贝到 ../ui（随仓库分发，用户无需 Node）
// 注：outDir 直接指 ../ 会在 Windows 盘符/中文路径下触发 rollup 的绝对路径校验报错，故走 dist+拷贝
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true },
});
