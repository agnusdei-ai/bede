import type { CapacitorConfig } from '@capacitor/cli'

// RC1 iPhone/iPad binary: HTML, CSS, JS and locales are bundled into the
// signed application. DO NOT add server.url: it silently replaces the
// installed UI with the server's latest version.
//
// The existing /api and WebAuthn flows need a separately validated native
// HTTPS integration before this is a functional release candidate.
const config: CapacitorConfig = {
  appId: 'ai.agnusdei.bede',
  appName: 'Bede',
  webDir: 'dist',
  server: {
    hostname: 'localhost',
    iosScheme: 'capacitor',
  },
  ios: {
    contentInset: 'automatic',
  },
}

export default config
