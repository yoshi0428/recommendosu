// Tests for pages/Changelog.jsx, with the API call replaced by a fake.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getChangelog } from "@/api/client";
import Changelog from "@/pages/Changelog";

vi.mock("@/api/client", () => ({ getChangelog: vi.fn() }));

beforeEach(() => {
  // jsdom's localStorage isn't usable here; useTheme only needs get/set.
  const store = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => store.set(key, String(value)),
  });
});

function renderPage() {
  render(
    <MemoryRouter>
      <Changelog />
    </MemoryRouter>
  );
}

describe("Changelog", () => {
  it("shows each entry with its date and changes", async () => {
    getChangelog.mockResolvedValue([
      { date: "2026-11-01", title: "Fixes", changes: ["Cancelling no longer shows an error."] },
      { date: "2026-10-19", title: "Discord bot", changes: ["Added /rec.", "Added /classify."] },
    ]);
    renderPage();

    expect(await screen.findByRole("heading", { name: "Fixes" })).toBeInTheDocument();
    // The date is the same in every time zone.
    expect(screen.getByText("November 1, 2026")).toHaveAttribute("datetime", "2026-11-01");
    expect(screen.getByText("Added /classify.")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("turns URLs into links, leaving punctuation around them as text", async () => {
    getChangelog.mockResolvedValue([
      {
        date: "2026-11-01",
        title: "Links",
        changes: ["fixed this map (https://osu.ppy.sh/beatmapsets/2321908). see https://example.com/a?b=1."],
      },
    ]);
    renderPage();

    const links = await screen.findAllByRole("link", { name: /^https/ });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "https://osu.ppy.sh/beatmapsets/2321908",
      "https://example.com/a?b=1",
    ]);
    expect(screen.getByRole("listitem")).toHaveTextContent(
      "fixed this map (https://osu.ppy.sh/beatmapsets/2321908). see https://example.com/a?b=1."
    );
  });

  it("says so when there are no entries", async () => {
    getChangelog.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText("No changes posted yet.")).toBeInTheDocument();
  });

  it("shows a loading error", async () => {
    getChangelog.mockRejectedValue(new Error("Failed to load the changelog (status 500)."));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("status 500");
  });
});
