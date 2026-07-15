import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Relative base path so this build works whether it's served from a domain
// root or a GitHub Pages project subpath (e.g. /bede/).
export default defineConfig({
  plugins: [react()],
  base: './',
  test: {
    environment: 'jsdom',
  },
})
