import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.TFT_API_PROXY_TARGET || "http://127.0.0.1:8000",
      "/__chattft_desktop__": process.env.TFT_API_PROXY_TARGET || "http://127.0.0.1:8000",
    },
  },
});
