import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: fileURLToPath(new URL("./tour/", import.meta.url)),
  base: "./",
  publicDir: fileURLToPath(new URL("./tour-public/", import.meta.url)),
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("./dist-tour/", import.meta.url)),
    emptyOutDir: true,
  },
});
