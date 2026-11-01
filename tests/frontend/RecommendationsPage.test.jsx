// Tests for pages/RecommendationsPage.jsx: running and cancelling a request.
//
// vi.mock replaces a whole module for this file, so the page talks to fake
// API functions instead of fetch, and the results table (which needs real
// layout to render rows) is replaced by a stub.

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRecommendations } from "@/api/client";
import RecommendationsPage from "@/pages/RecommendationsPage";

vi.mock("@/api/client", () => ({
  getRecommendations: vi.fn(),
  getRecommendationPage: vi.fn(async () => ({ recommendations: [] })),
  cancelRecommendation: vi.fn(async () => ({})),
}));

vi.mock("@/components/recommendations/RecommendationBody", () => ({
  default: ({ recommendations, totalCount }) => (
    <div>
      {totalCount} results{recommendations[0] ? `: ${recommendations[0].title}` : ""}
    </div>
  ),
}));

beforeEach(() => {
  // jsdom's localStorage isn't usable here; useTheme only needs get/set.
  const store = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => store.set(key, String(value)),
  });
});

function renderPage(logout = async () => {}) {
  render(
    <MemoryRouter>
      <RecommendationsPage user={{ player_id: 42 }} logout={logout} />
    </MemoryRouter>
  );
  return userEvent.setup();
}

describe("RecommendationsPage", () => {
  it("sends the player's ID and shows the first page", async () => {
    getRecommendations.mockResolvedValue({
      recommendation_id: "abc",
      total_count: 1,
      recommendations: [{ title: "Song" }],
    });
    const user = renderPage();

    await user.click(screen.getByText("Apply & Run"));

    expect(getRecommendations.mock.calls[0][0]).toMatchObject({ player_id: 42 });
    expect(await screen.findByText("1 results: Song")).toBeInTheDocument();
  });

  it("doesn't show an error when the backend confirms a cancellation", async () => {
    // The backend answers a cancelled POST /recommend with 204, which
    // getRecommendations returns as null.
    getRecommendations.mockResolvedValue(null);
    const user = renderPage();

    await user.click(screen.getByText("Apply & Run"));
    await act(async () => {});

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("0 results")).toBeInTheDocument();
  });

  it("shows a logout failure", async () => {
    const user = renderPage(async () => {
      throw new Error("Failed to log out.");
    });

    await user.click(screen.getByText("Logout"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to log out.");
  });
});
