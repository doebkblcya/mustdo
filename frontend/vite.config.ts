import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function normalizeOrigin(value: string | undefined): string {
  return (value || "http://127.0.0.1:8000").replace(/\/$/, "");
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget = normalizeOrigin(env.API_PROXY_TARGET || env.VITE_API_BASE_URL);

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  };
});
