import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Flask API (src/api.py) runs on http://127.0.0.1:5050 and sends CORS headers, so the UI calls it
// directly (see src/lib/api.js).  Override with VITE_API_BASE in frontend/.env if you move the API.
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: false },
});
