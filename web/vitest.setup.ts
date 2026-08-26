import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// No `globals: true` in vitest.config.ts (test files import `describe`/`it`/`expect` explicitly),
// so testing-library's auto-cleanup — which detects a global test framework — never registers
// itself. Do it here instead, once, for every test file.
afterEach(() => {
  cleanup();
});
