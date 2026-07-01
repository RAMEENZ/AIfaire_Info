import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  resolve: {
    // Miroir de l'alias "@/..." défini dans tsconfig.json.
    alias: { "@": path.resolve(__dirname, "src") },
  },
});
