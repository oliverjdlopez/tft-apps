import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

const apiTarget = process.env.TFT_API_PROXY_TARGET || "http://127.0.0.1:8300";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": apiTarget,
      "/__chattft_desktop__": apiTarget,
      "/media": apiTarget,
      "/static": apiTarget,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.js",
    globals: true,
  },
});
