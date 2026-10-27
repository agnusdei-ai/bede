import { useEffect, useState } from "react";
import { FullscreenVideoControls, useFullscreenVideo } from "./FullscreenVideo";

type TranscriptSegment = {
  start: number;
  end: number;
  speaker: string;
  text: string;
};

type LessonTranscript = {
  duration: number;
  description: string;
  segments: TranscriptSegment[];
};

type LessonVideoProps = {
  publicDemoHref: string;
};

function asset(name: string) {
  return `${import.meta.env.BASE_URL.replace(/\/$/, "")}/bede-tour/${name}`;
}

function formatTime(seconds: number) {
  const wholeSeconds = Math.floor(seconds);
  return `${Math.floor(wholeSeconds / 60)}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

function isTranscript(value: unknown): value is LessonTranscript {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<LessonTranscript>;
  return typeof candidate.duration === "number"
    && typeof candidate.description === "string"
    && Array.isArray(candidate.segments)
    && candidate.segments.every((segment) =>
      typeof segment.start === "number"
      && typeof segment.end === "number"
      && typeof segment.speaker === "string"
      && typeof segment.text === "string"
    );
}

export function LessonVideo({ publicDemoHref }: LessonVideoProps) {
  const fullscreen = useFullscreenVideo();
  const [transcript, setTranscript] = useState<LessonTranscript | null>(null);
  const [transcriptUnavailable, setTranscriptUnavailable] = useState(false);
  const [videoUnavailable, setVideoUnavailable] = useState(false);
  const [duration, setDuration] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    fetch(asset("lesson-transcript.json"))
      .then((response) => {
        if (!response.ok) throw new Error("Transcript unavailable");
        return response.json() as Promise<unknown>;
      })
      .then((data) => {
        if (!isTranscript(data)) throw new Error("Transcript format unavailable");
        if (active) {
          setTranscript(data);
          setTranscriptUnavailable(false);
        }
      })
      .catch(() => {
        if (active) {
          setTranscript(null);
          setTranscriptUnavailable(true);
        }
      });
    return () => { active = false; };
  }, []);

  return (
    <section className="tour-video-card lesson-video-card" aria-labelledby="lesson-title" data-testid="section-recorded-lesson">
      <div className="tour-video-heading">
        <div>
          <p className="tour-eyebrow">Recorded practice · fictional Grade 3 learner</p>
          <h2 id="lesson-title" tabIndex={-1}>Watch Bede in action</h2>
          <p>
            Reading, writing, and mathematics
            {duration !== null && Number.isFinite(duration) ? ` · ${formatTime(duration)} · English captions` : " · English captions"}
          </p>
        </div>
      </div>
      <p className="lesson-description">Follow three simple steps: retell a story, revise a sentence, and explain a solution.</p>
      <video
        ref={fullscreen.videoRef}
        onPlay={fullscreen.onPlay}
        controls
        preload="metadata"
        poster={asset("lesson-poster.jpg")}
        aria-label="Recorded Bede practice with a fictional Grade 3 learner exploring reading, writing, and mathematics"
        data-testid="video-recorded-lesson"
        onError={() => setVideoUnavailable(true)}
        onLoadedMetadata={(event) => {
          const actualDuration = event.currentTarget.duration;
          setDuration(Number.isFinite(actualDuration) ? actualDuration : null);
          setVideoUnavailable(false);
        }}
      >
        <source src={asset("generated/lesson.mp4")} type="video/mp4" />
        <source src={asset("generated/lesson.webm")} type="video/webm" />
        <track kind="captions" src={asset("lesson.vtt")} srcLang="en" label="English" default />
        Your browser does not support embedded video. Use the captioned download or transcript below.
      </video>
      <FullscreenVideoControls title="Bede in action" onClick={fullscreen.playFullscreen} message={fullscreen.message} />
      {videoUnavailable && (
        <p className="tour-note" role="status" data-testid="status-lesson-video-unavailable">
          Video playback is unavailable. <a href={asset("generated/lesson-captioned.mp4")} download>Download the captioned lesson</a>.
        </p>
      )}
      <details className="tour-disclosure">
        <summary>Read the lesson transcript</summary>
        {transcript
          ? <div className="tour-transcript lesson-transcript" data-testid="text-lesson-transcript">
            {transcript.segments.map((segment, index) => (
              <p key={`${segment.start}-${index}`}>
                <time>{formatTime(segment.start)}</time>
                <strong>{segment.speaker}</strong>
                <span>{segment.text}</span>
              </p>
            ))}
          </div>
          : <p className="lesson-transcript-status" role="status" data-testid="status-lesson-transcript">
            {transcriptUnavailable ? "The transcript is unavailable right now. Please use the video’s English captions." : "Loading the lesson transcript…"}
          </p>}
      </details>
      <div className="lesson-demo-action">
        <p>Continue with Bede at your own pace.</p>
        <a className="tour-button" href={publicDemoHref} data-testid="link-try-bede">Try Bede for 20 minutes <span aria-hidden="true">→</span></a>
      </div>
    </section>
  );
}
