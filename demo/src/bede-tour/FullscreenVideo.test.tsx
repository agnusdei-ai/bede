import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { enterVideoFullscreen, FullscreenVideoControls, useFullscreenVideo } from "./FullscreenVideo";

afterEach(cleanup);

function Player() {
  const fullscreen = useFullscreenVideo();
  return <>
    <video ref={fullscreen.videoRef} onPlay={fullscreen.onPlay} controls data-testid="video" />
    <FullscreenVideoControls title="the overview" onClick={fullscreen.playFullscreen} message={fullscreen.message} />
  </>;
}

describe("full-screen tour playback", () => {
  it("requests standard desktop fullscreen", async () => {
    const video = document.createElement("video");
    video.requestFullscreen = vi.fn().mockResolvedValue(undefined);
    expect(await enterVideoFullscreen(video)).toBe(true);
    expect(video.requestFullscreen).toHaveBeenCalledOnce();
  });

  it("uses Safari's native mobile player", async () => {
    const video = Object.assign(document.createElement("video"), { webkitEnterFullscreen: vi.fn() });
    expect(await enterVideoFullscreen(video)).toBe(true);
    expect(video.webkitEnterFullscreen).toHaveBeenCalledOnce();
  });

  it("supports older WebKit fullscreen", async () => {
    const video = Object.assign(document.createElement("video"), { webkitRequestFullscreen: vi.fn() });
    expect(await enterVideoFullscreen(video)).toBe(true);
    expect(video.webkitRequestFullscreen).toHaveBeenCalledOnce();
  });

  it("handles unsupported or denied fullscreen without an unhandled rejection", async () => {
    const video = document.createElement("video");
    expect(await enterVideoFullscreen(video)).toBe(false);
    video.requestFullscreen = vi.fn().mockRejectedValue(new Error("Denied"));
    expect(await enterVideoFullscreen(video)).toBe(false);
  });

  it("requests fullscreen directly from the button and starts playback", async () => {
    render(<Player />);
    const video = screen.getByTestId("video") as HTMLVideoElement;
    video.requestFullscreen = vi.fn().mockResolvedValue(undefined);
    video.play = vi.fn().mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Play the overview full screen" }));
    expect(video.requestFullscreen).toHaveBeenCalledOnce();
    expect(video.play).toHaveBeenCalledOnce();
    fireEvent.play(video);
    expect(video.requestFullscreen).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("requests fullscreen on native Play without trapping a viewer who later exits", async () => {
    render(<Player />);
    const video = screen.getByTestId("video") as HTMLVideoElement;
    video.requestFullscreen = vi.fn().mockResolvedValue(undefined);
    fireEvent.play(video);
    fireEvent.pause(video);
    fireEvent.play(video);
    expect(video.requestFullscreen).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("keeps native playback available and explains a blocked fullscreen request", async () => {
    render(<Player />);
    fireEvent.play(screen.getByTestId("video"));
    expect(await screen.findByRole("status")).toHaveProperty("textContent",
      "Full screen is unavailable in this browser. You can keep watching in the player.");
  });

  it("reports a rejected playback request", async () => {
    render(<Player />);
    const video = screen.getByTestId("video") as HTMLVideoElement;
    video.requestFullscreen = vi.fn().mockResolvedValue(undefined);
    video.play = vi.fn().mockRejectedValue(new Error("Playback denied"));
    fireEvent.click(screen.getByRole("button", { name: "Play the overview full screen" }));
    expect(await screen.findByRole("status")).toHaveProperty("textContent",
      "Playback could not start. Use the player’s Play control or the captioned download.");
  });
});
