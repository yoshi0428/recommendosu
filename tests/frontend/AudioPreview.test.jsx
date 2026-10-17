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
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      headers: new Headers({ "X-Preview-Time": "1000" }),
      blob: async () => new Blob(),
    }))
  );
  // jsdom has no object URLs or media playback.
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
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

  it("closes the player and releases the audio", async () => {
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
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  });
});
