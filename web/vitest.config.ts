import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    exclude: ["tests/e2e/**", "node_modules/**"],
    coverage: { provider: "v8", include: ["src/lib/**/*.ts"], reporter: ["text", "html"], thresholds: { lines: 80, functions: 80, statements: 80, branches: 80 } }
  }
});
