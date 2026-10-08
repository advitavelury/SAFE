import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { validateDeploymentEnv } from "./src/api/deploymentConfig.js";

export default defineConfig(({ command, mode }) => {
  if (command === "build") {
    validateDeploymentEnv({ ...loadEnv(mode, process.cwd(), "VITE_"), ...process.env });
  }
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        "/api/camera": "http://127.0.0.1:5001",
        "/api/incidents": "http://127.0.0.1:5001",
      },
    },
  };
});
