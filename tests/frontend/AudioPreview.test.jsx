// Component tests for the shared audio preview player.
//
// The results table is virtualized, so a row unmounts as soon as it scrolls
// out of view. The preview must continue to play when that happens.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AudioPreviewProvider } from "@/components/recommendations/AudioPreview";
import RecommendationRow from "@/components/recommendations/RecommendationRow";

const RECOMMENDATION = {
  beatmap_id: 1,
  beatmapset_id: 2,
  artist: "Artist",
  title: "Title",
  version: "Insane",
  creator: "Mapper",
};

function Results({ showRow }) {
  return (
    <AudioPreviewProvider>
      <table>
        <tbody>
          {showRow && (
            <RecommendationRow
              recommendation={RECOMMENDATION}
              virtualRow={{ index: 0 }}
              rowVirtualizer={{ measureElement: () => {} }}
            />
          )}
        </tbody>
      </table>
    </AudioPreviewProvider>
  );
}

beforeEach(() => {
  // jsdom has no media playback.
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function () {
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function () {
    this.dispatchEvent(new Event("pause"));
  });
});

// Make each later play() fail, as for a set that has no preview on osu!.
function failPlayback() {
  HTMLMediaElement.prototype.play.mockImplementation(() =>
    Promise.reject(new Error("no preview"))
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
}

// The bar is hidden and the audio element has no source.
async function expectPlayerClosed(container) {
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Close audio preview" })
    ).not.toBeInTheDocument()
  );
  expect(container.querySelector("audio").hasAttribute("src")).toBe(false);
}

describe("AudioPreviewProvider", () => {
  it("plays osu!'s preview for the row's beatmapset", async () => {
    const user = userEvent.setup();
    const { container } = render(<Results showRow />);

    await user.click(container.querySelector(".recommendation-cover"));

    expect(
      await screen.findByRole("button", { name: "Pause preview" })
    ).toBeInTheDocument();
    expect(container.querySelector("audio").getAttribute("src")).toBe(
      "https://b.ppy.sh/preview/2.mp3"
    );
  });

  it("doesn't open the player when the preview fails to load", async () => {
    failPlayback();
    const user = userEvent.setup();
    const { container } = render(<Results showRow />);

    await user.click(container.querySelector(".recommendation-cover"));

    // The bar was never open, so wait for the failure first.
    await waitFor(() => expect(console.error).toHaveBeenCalled());
    await expectPlayerClosed(container);
  });

  it("keeps playing after the row that started it unmounts", async () => {
    const user = userEvent.setup();
    const { container, rerender } = render(<Results showRow />);

    await user.click(container.querySelector(".recommendation-cover"));

    expect(
      await screen.findByRole("button", { name: "Pause preview" })
    ).toBeInTheDocument();

    // Scroll the row out of view.
    rerender(<Results showRow={false} />);

    expect(
      screen.getByRole("button", { name: "Pause preview" })
    ).toBeInTheDocument();
    expect(HTMLMediaElement.prototype.pause).not.toHaveBeenCalled();
  });

  it("closes the player and unloads the audio", async () => {
    const user = userEvent.setup();
    const { container } = render(<Results showRow />);

    await user.click(container.querySelector(".recommendation-cover"));
    await user.click(
      await screen.findByRole("button", { name: "Close audio preview" })
    );

    await expectPlayerClosed(container);
  });
});

describe("previous, next and repeat", () => {
  // Two variants of mapset 2 (the same preview audio), then mapset 3, then a
  // row that did not load yet, then mapset 4.
  const PLAYLIST = [
    { ...RECOMMENDATION, variant_id: 10 },
    { ...RECOMMENDATION, variant_id: 11 },
    { ...RECOMMENDATION, beatmap_id: 3, beatmapset_id: 3, variant_id: 12 },
    undefined,
    { ...RECOMMENDATION, beatmap_id: 4, beatmapset_id: 4, variant_id: 13 },
  ];

  function Player() {
    return (
      <AudioPreviewProvider playlist={PLAYLIST}>
        <table>
          <tbody>
            <RecommendationRow
              recommendation={PLAYLIST[0]}
              virtualRow={{ index: 0 }}
              rowVirtualizer={{ measureElement: () => {} }}
            />
          </tbody>
        </table>
      </AudioPreviewProvider>
    );
  }

  it("skips variants with the same preview and rows not fetched yet", async () => {
    const user = userEvent.setup();
    const { container } = render(<Player />);
    const src = () => container.querySelector("audio").getAttribute("src");

    await user.click(container.querySelector(".recommendation-cover"));
    await screen.findByRole("button", { name: "Pause preview" });
    expect(screen.getByRole("button", { name: "Previous preview" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next preview" }));
    await waitFor(() => expect(src()).toBe("https://b.ppy.sh/preview/3.mp3"));

    await user.click(screen.getByRole("button", { name: "Next preview" }));
    await waitFor(() => expect(src()).toBe("https://b.ppy.sh/preview/4.mp3"));
    expect(screen.getByRole("button", { name: "Next preview" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Previous preview" }));
    await waitFor(() => expect(src()).toBe("https://b.ppy.sh/preview/3.mp3"));
  });

  it("closes the player when the next preview fails to load", async () => {
    const user = userEvent.setup();
    const { container } = render(<Player />);

    await user.click(container.querySelector(".recommendation-cover"));
    await screen.findByRole("button", { name: "Pause preview" });

    // The failed preview replaced the source of the audio element, so the
    // first preview is gone. The bar must not stay open for an empty player.
    failPlayback();
    await user.click(screen.getByRole("button", { name: "Next preview" }));

    await expectPlayerClosed(container);
  });

  it("repeat loops the preview", async () => {
    const user = userEvent.setup();
    const { container } = render(<Player />);

    await user.click(container.querySelector(".recommendation-cover"));
    const repeat = await screen.findByRole("button", { name: "Repeat preview" });
    expect(container.querySelector("audio").loop).toBe(false);

    await user.click(repeat);
    expect(container.querySelector("audio").loop).toBe(true);
    expect(repeat).toHaveAttribute("aria-pressed", "true");
  });
});

describe("feedback", () => {
  function Row({ onFeedback }) {
    return (
      <AudioPreviewProvider onFeedback={onFeedback}>
        <table>
          <tbody>
            <RecommendationRow
              recommendation={RECOMMENDATION}
              onFeedback={onFeedback}
              virtualRow={{ index: 0 }}
              rowVirtualizer={{ measureElement: () => {} }}
            />
          </tbody>
        </table>
      </AudioPreviewProvider>
    );
  }

  it("reports a preview when it starts, not when it pauses or resumes", async () => {
    const onFeedback = vi.fn();
    const user = userEvent.setup();
    const { container } = render(<Row onFeedback={onFeedback} />);
    const cover = container.querySelector(".recommendation-cover");

    await user.click(cover);
    await screen.findByRole("button", { name: "Pause preview" });
    await user.click(cover);
    await user.click(cover);

    expect(onFeedback.mock.calls).toEqual([["preview", RECOMMENDATION]]);
  });

  it("doesn't report a preview that fails to load", async () => {
    failPlayback();
    const onFeedback = vi.fn();
    const user = userEvent.setup();
    const { container } = render(<Row onFeedback={onFeedback} />);

    await user.click(container.querySelector(".recommendation-cover"));
    await waitFor(() => expect(console.error).toHaveBeenCalled());

    expect(onFeedback).not.toHaveBeenCalled();
  });

  it("reports link clicks, middle clicks and row clicks", () => {
    const onFeedback = vi.fn();
    const { container } = render(<Row onFeedback={onFeedback} />);
    const link = container.querySelector("a");

    fireEvent.click(link);
    fireEvent(link, new MouseEvent("auxclick", { bubbles: true, button: 1 }));
    fireEvent(link, new MouseEvent("auxclick", { bubbles: true, button: 2 }));
    fireEvent.click(container.querySelector("tr"));

    expect(onFeedback.mock.calls.map(([type]) => type)).toEqual(["open", "open", "details"]);
  });
});
