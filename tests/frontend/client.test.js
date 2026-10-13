// Tests for src/api/client.js: the functions that talk to the backend.
//
// No server runs during these tests. `fetch` is replaced with a fake
// (vi.fn) that returns whatever response a test sets up. This lets each test:
//   1. check what the client *sent* (URL, method, headers, body), and
//   2. check how it *handles* each kind of reply, including ones that are
//      hard to trigger for real, like nginx's HTML 504 timeout page.
//
// `Response` is the browser's real response class (Node has it too), so
// .json(), .ok and .headers behave exactly like in the browser.

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelRecommendation,
  getCurrentUser,
  getRecommendationPage,
  getRecommendations,
  logout,
} from "@/api/client";

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let fetchMock;

beforeEach(() => {
  // beforeEach runs before every test in this file, so each test starts
  // with a fresh fake that has no recorded calls. src/test/setup.js removes
  // it again after each test.
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

// The URL and options of the n-th fetch call.
function fetchCall(n = 0) {
  const [url, options] = fetchMock.mock.calls[n];
  return { url, options };
}

describe("getRecommendations", () => {
  it("POSTs the settings with the recommendation ID header", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ recommendation_id: "abc", recommendations: [] }));
    const signal = new AbortController().signal;

    const data = await getRecommendations({ goal: "balanced" }, { recommendationId: "abc", signal });

    expect(data.recommendation_id).toBe("abc");

    const { url, options } = fetchCall();
    expect(url).toBe("/api/v1/recommend");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include"); // Sends the session cookie.
    expect(options.headers["X-Recommendation-Id"]).toBe("abc");
    expect(JSON.parse(options.body)).toEqual({ goal: "balanced" });
    expect(options.signal).toBe(signal); // So the request can be aborted.
  });

  it("shows the backend's error message", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "osu! player 1 was not found." }, 404));

    // For async code, use `await expect(promise).rejects...`.
    await expect(getRecommendations({})).rejects.toThrow("osu! player 1 was not found.");
  });

  it("formats FastAPI validation errors (422) readably", async () => {
    // This is the shape FastAPI/pydantic returns for invalid settings.
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          detail: [
            { loc: ["body", "min_year"], msg: "Input should be greater than or equal to 2007" },
            { loc: ["body", "goal"], msg: "Field required" },
          ],
        },
        422,
      ),
    );

    await expect(getRecommendations({})).rejects.toThrow(
      "body.min_year: Input should be greater than or equal to 2007\nbody.goal: Field required",
    );
  });

  it("explains an nginx timeout instead of failing to parse HTML", async () => {
    fetchMock.mockResolvedValue(
      new Response("<html>504 Gateway Time-out</html>", {
        status: 504,
        headers: { "Content-Type": "text/html" },
      }),
    );

    await expect(getRecommendations({})).rejects.toThrow("took too long");
  });

  it("rejects other non-JSON responses with the status", async () => {
    fetchMock.mockResolvedValue(
      new Response("<html>Bad Gateway</html>", { status: 502, headers: { "Content-Type": "text/html" } }),
    );

    await expect(getRecommendations({})).rejects.toThrow("status 502. Server returned text/html");
  });

  it("passes an abort through as an AbortError", async () => {
    // RecommendationsPage treats AbortError as "the user cancelled", not as
    // an error to show, so the error type matters.
    fetchMock.mockRejectedValue(new DOMException("aborted", "AbortError"));

    await expect(getRecommendations({})).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("getRecommendationPage", () => {
  it("requests the right slice", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ total_count: 5000, recommendations: [] }));

    await getRecommendationPage("abc", 2000, 1000);

    expect(fetchCall().url).toBe("/api/v1/recommend/abc/page?offset=2000&limit=1000");
  });

  it("surfaces an expired result", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Recommendation result expired or not found. Run the recommender again." }, 404),
    );

    await expect(getRecommendationPage("abc", 0, 1000)).rejects.toThrow("expired");
  });

  it("falls back to the status for non-JSON errors", async () => {
    fetchMock.mockResolvedValue(new Response("oops", { status: 500 }));

    await expect(getRecommendationPage("abc", 0, 1000)).rejects.toThrow("status 500");
  });
});

describe("cancelRecommendation", () => {
  it("POSTs to the cancel endpoint", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ recommendation_id: "abc", cancelled: true }));

    expect(await cancelRecommendation("abc")).toEqual({ recommendation_id: "abc", cancelled: true });
    expect(fetchCall().url).toBe("/api/v1/recommend/abc/cancel");
    expect(fetchCall().options.method).toBe("POST");
  });

  it("throws with the backend's message", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Not authenticated." }, 401));

    await expect(cancelRecommendation("abc")).rejects.toThrow("Not authenticated.");
  });
});

describe("auth helpers", () => {
  it("getCurrentUser returns the player when logged in", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ player_id: 100 }));
    expect(await getCurrentUser()).toEqual({ player_id: 100 });
  });

  it("getCurrentUser returns null when logged out", async () => {
    // A 401 here is normal (it's how the app knows to show the login screen),
    // so it must not throw.
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Not authenticated." }, 401));
    expect(await getCurrentUser()).toBeNull();
  });

  it("logout throws if the server refuses", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 500 }));
    await expect(logout()).rejects.toThrow("Failed to log out.");
  });
});
