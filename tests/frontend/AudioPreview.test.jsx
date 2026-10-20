// Component tests for the shared audio preview player.
//
// The results table is virtualized, so a row is unmounted as soon as it
// scrolls out of view. The preview must keep playing when that happens.

import { render, screen, waitFor } from "@testing-library/react";
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
    HTMLMediaElement.prototype.play.mockImplementation(() =>
      Promise.reject(new Error("no preview"))
    );
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();
    const { container } = render(<Results showRow />);

    await user.click(container.querySelector(".recommendation-cover"));

    await waitFor(() => expect(console.error).toHaveBeenCalled());
    expect(
      screen.queryByRole("button", { name: "Close audio preview" })
    ).not.toBeInTheDocument();
    expect(container.querySelector("audio").hasAttribute("src")).toBe(false);
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

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Close audio preview" })
      ).not.toBeInTheDocument()
    );
    expect(container.querySelector("audio").hasAttribute("src")).toBe(false);
  });
});
