import path from "node:path";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const TESTS_DIR = path.resolve(import.meta.dirname, "../tests/frontend");

export default defineConfig({
  // Always treat frontend/ as the project root, even when Vitest is started
  // from the repo root (e.g. by the editor's Vitest extension). Otherwise
  // packages would be looked up in <repo>/node_modules, which doesn't exist.
  root: import.meta.dirname,
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: [
      "frontend",
      "localhost",
      "recommendosu.com",
      "liking-size-booth.ngrok-free.dev",
    ],
    // Vite only serves files inside frontend/ by default; the tests live
    // in ../tests/frontend.
    fs: {
      allow: [import.meta.dirname, TESTS_DIR],
    },
  },
  // Vitest reads this section. The frontend tests live next to the Python
  // tests in <repo>/tests/frontend, so paths below point there.
  test: {
    dir: TESTS_DIR,
    include: ["**/*.test.{js,jsx}"],
    // jsdom is a fake browser (document, window, DOM events) running inside
    // Node, so React components can render without opening a real browser.
    environment: "jsdom",
    // Runs before every test file; adds matchers like toBeChecked().
    setupFiles: [path.join(TESTS_DIR, "setup.js")],
  },
  resolve: {
    alias: {
      // Lets tests import app code as "@/components/ModOptions".
      "@": path.resolve(import.meta.dirname, "src"),
    },
    // Packages are normally found by walking up from the importing file to
    // a node_modules folder. tests/frontend has no node_modules above it, so
    // resolve these from frontend/node_modules instead. (dedupe also keeps a
    // single copy of React, which hooks require.)
    dedupe: [
      "react",
      "react-dom",
      "@testing-library/react",
      "@testing-library/dom",
      "@testing-library/user-event",
      "@testing-library/jest-dom",
    ],
  },
});
