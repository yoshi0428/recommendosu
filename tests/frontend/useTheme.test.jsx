// Tests for hooks/useTheme.js: one theme shared by every component.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

let store;

beforeEach(() => {
  store = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => store.set(key, String(value)),
  });
  // The theme is cached per module, so each test gets a fresh copy.
  vi.resetModules();
});

it("toggling in one component updates every other component using it", async () => {
  const { default: useTheme } = await import("@/hooks/useTheme");

  function Toggle() {
    const { theme, toggleTheme } = useTheme();
    return <button onClick={toggleTheme}>toggle {theme}</button>;
  }

  function Display() {
    return <div>shown {useTheme().theme}</div>;
  }

  render(
    <>
      <Toggle />
      <Display />
    </>
  );
  expect(screen.getByText("shown dark")).toBeInTheDocument();

  await userEvent.setup().click(screen.getByText("toggle dark"));

  expect(screen.getByText("shown light")).toBeInTheDocument();
  expect(store.get("theme")).toBe("light");
  expect(document.documentElement.getAttribute("data-bs-theme")).toBe("light");
});

it("starts from the saved theme", async () => {
  store.set("theme", "light");
  const { default: useTheme } = await import("@/hooks/useTheme");

  function Display() {
    return <div>shown {useTheme().theme}</div>;
  }

  render(<Display />);
  expect(screen.getByText("shown light")).toBeInTheDocument();
});
