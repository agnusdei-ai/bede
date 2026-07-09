import type { CapacitorConfig } from '@capacitor/cli'

// Native iOS wrapper for demo purposes. The WebView loads the already-deployed
// LAN instance directly (same Caddy TLS + Docker stack as the browser demo) —
// this app is a thin shell, not a separate build of the frontend, so the CSP,
// auth-gating, and encryption model are unchanged.
//
// IMPORTANT: WKWebView (what Capacitor uses) does NOT implement the Web Speech
// API the way Safari's own browser process does — voice input on native iOS
// falls back to the server-side Whisper transcription path exclusively
// (see useHybridVoiceInput.ts). Test the mic button specifically after
// building — do not assume Safari-tab behavior carries over.
const config: CapacitorConfig = {
  appId: 'ai.agnusdei.bede',
  appName: 'Bede',
  webDir: 'dist',
  server: {
    // Replace with the LAN IP of the Docker host running docker-compose.
    // Must match the trusted Caddy root CA installed on this device.
    url: 'https://REPLACE_WITH_LAN_IP',
    cleartext: false,
  },
  ios: {
    contentInset: 'automatic',
  },
}

export default config
