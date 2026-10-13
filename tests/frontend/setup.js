// Runs before every test file (see `test.setupFiles` in vite.config.js).

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  // Remove whatever the previous test rendered, so tests can't see each
  // other's components.
  cleanup();
  // Undo vi.spyOn(...) and vi.stubGlobal(...) (e.g. a faked fetch), the
  // JavaScript equivalent of pytest's monkeypatch.
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
