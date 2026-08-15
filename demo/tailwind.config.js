/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      // Mirrors homeschool-tutor's tailwind.config.js — see that file's own
      // comment. Stock Tailwind breakpoints are all width-based; the writing
      // pad's toolbar needs to shrink when HEIGHT is scarce (a phone rotated
      // to landscape), which is an orthogonal axis stock Tailwind has none
      // for. 500px separates "phone in landscape" from "tablet in landscape"
      // (already roomy) — see HandwritingCanvas.tsx's `short:` classes.
      screens: {
        short: { raw: '(max-height: 500px)' },
      },
      // Tailwind's default type scale, each size up 15% — applies globally to
      // every text-* utility class without touching the spacing scale.
      fontSize: {
        xs: ['0.8625rem', { lineHeight: '1.15rem' }],
        sm: ['1.00625rem', { lineHeight: '1.4375rem' }],
        base: ['1.15rem', { lineHeight: '1.725rem' }],
        lg: ['1.29375rem', { lineHeight: '2.0125rem' }],
        xl: ['1.4375rem', { lineHeight: '2.0125rem' }],
        '2xl': ['1.725rem', { lineHeight: '2.3rem' }],
        '3xl': ['2.15625rem', { lineHeight: '2.5875rem' }],
        '4xl': ['2.5875rem', { lineHeight: '2.875rem' }],
        '5xl': ['3.45rem', { lineHeight: '1' }],
        '6xl': ['4.3125rem', { lineHeight: '1' }],
        '7xl': ['5.175rem', { lineHeight: '1' }],
        '8xl': ['6.9rem', { lineHeight: '1' }],
        '9xl': ['9.2rem', { lineHeight: '1' }],
      },
      colors: {
        // ── Drawn from agnusdei.ai's own palette ──────────────────────────
        // Every 500/600 below IS a token from site/assets/site.css, copied
        // verbatim, so the app a family logs into is the same object as the
        // site they bought it from. The ramp NAMES are unchanged (there are
        // ~930 sage-*/navy-*/gold-*/parchment-* classes across both apps);
        // only the hex values moved — the same approach taken when the
        // original leaf-green was hue-rotated to olive.
        //
        // The intermediate steps are generated around those anchors in OKLab
        // rather than snapped to a generic Tailwind curve: the site's ink is
        // far darker than a stock 500, and a generic curve puts 600 LIGHTER
        // than 500, silently inverting every `hover:bg-*-600` in the app.
        // tests/palette.test.ts pins the anchors, the monotonic ordering,
        // and the WCAG floors so neither can drift back.

        // fern / fern-deep — the nature-notebook green.
        sage: {
          50:  '#f5f9f4',
          100: '#cfd9cd',
          200: '#acb9a8',
          300: '#83937f',
          400: '#6a7c65',
          500: '#47613f', // --fern
          600: '#33482d', // --fern-deep
          700: '#25381f',
          800: '#172911',
          900: '#091b05',
        },
        // ink-soft / ink — iron-gall ink. 500 is the resting brand fill and
        // heading colour; hover deepens into true ink at 600, which is also
        // the colour of the site's dark bands.
        navy: {
          50:  '#f6f7fb',
          100: '#ccd0da',
          200: '#a5abb8',
          300: '#7f8697',
          400: '#5c6476',
          500: '#3a4358', // --ink-soft
          600: '#1c2438', // --ink
          700: '#12192c',
          800: '#090f21',
          900: '#030616',
        },
        // gilt-light / gilt — the gilt on a cloth book spine.
        gold: {
          50:  '#fff6e5',
          100: '#f6e1bc',
          200: '#eacc97',
          300: '#e0b84a', // --gilt-light
          400: '#b38832',
          500: '#b8860b', // --gilt
          600: '#8e5f00',
          700: '#7d4f00',
          800: '#603600',
          900: '#451d00',
        },
        // vellum / vellum-deep — foxed paper. parchment-50 is the page the
        // whole app is printed on, and matches the site's own ground exactly.
        parchment: {
          50:  '#faf6ec', // --vellum
          100: '#f1e7d2', // --vellum-deep
          200: '#d7ceb9',
          300: '#beb5a1',
          400: '#a69d8a',
          500: '#8e8573',
        },
        // madder — the old plant dye, and the site's fifth token. Replaces a
        // violet ramp named `faith` that appeared nowhere on agnusdei.ai and
        // gave every loading screen a cool cast against Bede's warm portrait.
        madder: {
          50:  '#fff4f1',
          100: '#f2cbc3',
          200: '#dca59a',
          300: '#c28174',
          400: '#a85e50',
          500: '#8c3b2e', // --madder
          600: '#7b2d21',
          700: '#691e13',
          800: '#580e05',
          900: '#480000',
        },
      },
      fontFamily: {
        serif: ['Georgia', 'Cambria', '"Times New Roman"', 'serif'],
        display: ['"Palatino Linotype"', 'Palatino', 'serif'],
      },
      animation: {
        'fade-in': 'fadeIn 0.4s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-soft': 'pulseSoft 2s ease-in-out infinite',
        'celebrate': 'celebrate 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)',
        'bede-talk': 'bedeTalk 0.5s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: { from: { transform: 'translateY(8px)', opacity: '0' }, to: { transform: 'translateY(0)', opacity: '1' } },
        pulseSoft: { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.6' } },
        celebrate: {
          '0%': { transform: 'scale(0.9) translateY(6px)', opacity: '0' },
          '60%': { transform: 'scale(1.03) translateY(0)', opacity: '1' },
          '100%': { transform: 'scale(1) translateY(0)' },
        },
        // A gentle head-bob, not a literal mouth-flap (no per-frame mouth art
        // exists for bede-icon.png) — reads as "he's the one talking" at the
        // small size this renders at, without needing new art assets.
        bedeTalk: {
          '0%, 100%': { transform: 'scale(1) rotate(0deg)' },
          '50%': { transform: 'scale(1.08) rotate(-3deg)' },
        },
      },
    },
  },
  plugins: [],
}
