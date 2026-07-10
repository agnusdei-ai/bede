/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of a publicly-reachable homeschool-api deployment with
   *  DEMO_PIN set — required for this demo to function at all. Set at
   *  build time, e.g. VITE_DEMO_API_BASE=https://api.example.com */
  readonly VITE_DEMO_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
