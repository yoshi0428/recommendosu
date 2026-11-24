// Tests for components/PageErrorBoundary.jsx: a page that fails to load or
// render must never leave a blank screen.
import { lazy, Suspense } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import PageErrorBoundary from "@/components/PageErrorBoundary";

const FLAG = "page-chunk-reload";
let store;
let reload;

beforeEach(() => {
  // The storage of jsdom does not work here. The boundary needs only get/set/remove.
  store = new Map();
  vi.stubGlobal("sessionStorage", {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  });
  reload = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, reload },
  });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPage(Page) {
  return render(
    <Suspense fallback={<div>loading</div>}>
      <PageErrorBoundary>
        <Page />
      </PageErrorBoundary>
    </Suspense>
  );
}

// A lazy page with a file that cannot be fetched (for example, after a redeploy).
const missingChunk = () =>
  lazy(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module: /assets/About-old.js")));

it("reloads once when a page's file is missing", async () => {
  const Page = missingChunk();
  renderPage(Page);

  await screen.findByText("This page didn't load");
  expect(reload).toHaveBeenCalledTimes(1);
  expect(store.get(FLAG)).toBe("1");
});

it("doesn't reload again if the file is still missing after that reload", async () => {
  store.set(FLAG, "1");
  renderPage(missingChunk());

  await screen.findByText("This page didn't load");
  expect(reload).not.toHaveBeenCalled();
  expect(screen.getByText("Back to Recommendations").closest("a").getAttribute("href")).toBe("/");
});

it("shows a way back when a page crashes while rendering", () => {
  function Broken() {
    throw new Error("boom");
  }
  renderPage(Broken);

  expect(screen.getByText("This page didn't load")).toBeTruthy();
  expect(reload).not.toHaveBeenCalled();
});

it("clears the reload flag once a page has loaded", async () => {
  store.set(FLAG, "1");
  const Page = lazy(() => Promise.resolve({ default: () => <div>about page</div> }));
  renderPage(Page);

  await screen.findByText("about page");
  expect(store.has(FLAG)).toBe(false);
});
