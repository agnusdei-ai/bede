import { useRef, useState } from "react";
import { Maximize } from "lucide-react";

type FullscreenVideo = HTMLVideoElement & {
  webkitEnterFullscreen?: () => void;
  webkitDisplayingFullscreen?: boolean;
  webkitRequestFullscreen?: () => void | Promise<void>;
};

export async function enterVideoFullscreen(video: FullscreenVideo): Promise<boolean> {
  if (video.ownerDocument.fullscreenElement === video || video.webkitDisplayingFullscreen) return true;
  try {
    // iPhone/iPad Safari use the native media player rather than document fullscreen.
    if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
    else if (video.requestFullscreen) await video.requestFullscreen();
    else if (video.webkitRequestFullscreen) await video.webkitRequestFullscreen();
    else return false;
    return true;
  } catch {
    return false;
  }
}

export function useFullscreenVideo() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const requestedOnPlay = useRef(false);
  const [fullscreenUnavailable, setFullscreenUnavailable] = useState(false);
  const [playbackUnavailable, setPlaybackUnavailable] = useState(false);

  const requestFullscreen = () => {
    if (videoRef.current) {
      void enterVideoFullscreen(videoRef.current).then((success) => setFullscreenUnavailable(!success));
    }
  };

  const onPlay = () => {
    setPlaybackUnavailable(false);
    // Request once on first play; do not force viewers back after they exit.
    if (!requestedOnPlay.current) {
      requestedOnPlay.current = true;
      requestFullscreen();
    }
  };

  const playFullscreen = () => {
    const video = videoRef.current;
    if (!video) return;
    requestedOnPlay.current = true;
    setPlaybackUnavailable(false);
    // Request synchronously from the click so browser user-gesture checks pass.
    requestFullscreen();
    void video.play().catch(() => setPlaybackUnavailable(true));
  };

  return {
    videoRef,
    onPlay,
    playFullscreen,
    message: playbackUnavailable
      ? "Playback could not start. Use the player’s Play control or the captioned download."
      : fullscreenUnavailable
        ? "Full screen is unavailable in this browser. You can keep watching in the player."
        : null,
  };
}

export function FullscreenVideoControls({
  title, onClick, message,
}: {
  title: string;
  onClick: () => void;
  message: string | null;
}) {
  return (
    <div className="tour-video-actions">
      <button type="button" className="tour-button secondary" onClick={onClick}
        aria-label={`Play ${title} full screen`}>
        <Maximize size={16} aria-hidden="true" /> Play full screen
      </button>
      {message && <p className="tour-note" role="status">{message}</p>}
    </div>
  );
}
