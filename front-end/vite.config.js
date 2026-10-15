import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api/admin/detector-settings": {
        target: "http://127.0.0.1:8000",
        rewrite: path => path.replace(/^\/api/, ""),
      },
      "/api/video-source": {
        target: "http://127.0.0.1:8000",
        rewrite: () => "/video_source",
      },
      "/api/video-feed": {
        target: "http://127.0.0.1:8000",
        rewrite: path => path.replace(/^\/api\/video-feed/, "/video_feed"),
      },
      "/api/events": {
        target: "http://127.0.0.1:8000",
        rewrite: path => path.replace(/^\/api/, ""),
      },
    },
  },
});
