/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.AIGEN_BACKEND ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
