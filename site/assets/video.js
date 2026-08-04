// To add the intro video: paste the ID from its YouTube URL below, then
// push — no build step, no rebuild pipeline, this file is served as-is.
// Leave YOUTUBE_VIDEO_ID blank to keep showing the placeholder.
// The ID is the same part of the URL either way:
//   youtube.com/watch?v=dQw4w9WgXcQ          -> "dQw4w9WgXcQ"
//   youtube.com/shorts/dQw4w9WgXcQ            -> "dQw4w9WgXcQ"
// Set YOUTUBE_VIDEO_VERTICAL to true for a YouTube Shorts style
// (portrait) video, false for a normal landscape video.
//
// Lives in its own file (not an inline <script> in index.html) so the
// site's Content-Security-Policy (see site/_headers) can set
// script-src 'self' with no 'unsafe-inline' exception — a real script
// tag Cloudflare can serve with the right MIME type, rather than inline
// JS a strict CSP would otherwise have to carve out an exception for.
const YOUTUBE_VIDEO_ID = 'M7OV1-RrK2M';
const YOUTUBE_VIDEO_VERTICAL = true;

const videoWrap = document.getElementById('video-wrap');
if (YOUTUBE_VIDEO_VERTICAL) videoWrap.classList.add('vertical');

function playerIframe(autoplay) {
  const params = autoplay ? '?autoplay=1' : '';
  return `<iframe src="https://www.youtube-nocookie.com/embed/${YOUTUBE_VIDEO_ID}${params}"
       title="Agnus Dei Technologies: Meet Bede"
       allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
       allowfullscreen></iframe>`;
}

if (!YOUTUBE_VIDEO_ID) {
  // No video configured yet — a plain, non-interactive placeholder.
  videoWrap.innerHTML =
    `<div class="video-placeholder"><span>&#9654;</span><p>Video coming soon</p></div>`;
} else {
  // Click-to-play: YouTube is not contacted until the visitor presses
  // play, so no third-party request happens on page load. A <button>
  // rather than a styled <div>, so it is keyboard-operable for free.
  videoWrap.innerHTML =
    `<button type="button" class="video-placeholder">
       <span>&#9654;</span>
       <p>Watch: Meet Bede</p>
       <small>Plays from YouTube. Nothing is requested from them until you press play.</small>
     </button>`;
  videoWrap.querySelector('button').addEventListener('click', () => {
    videoWrap.innerHTML = playerIframe(true);
  });
}
