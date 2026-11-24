// This file runs before each test file (see `test.setupFiles` in vite.config.js).

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  // Remove what the previous test rendered, so that a test cannot see the
  // components of another test.
  cleanup();
  // Undo vi.spyOn(...) and vi.stubGlobal(...) (for example, a fake fetch).
  // These are the JavaScript equivalent of the pytest monkeypatch.
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
