import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.{ts,tsx}"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "json-summary"],
      include: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
      // layout.tsx is the Next.js root layout (html/body + font imports): it cannot
      // render inside jsdom's own document. types.ts holds types only.
      exclude: ["app/layout.tsx", "lib/types.ts"],
      thresholds: { lines: 96, statements: 96, functions: 96, branches: 96 },
    },
  },
});
