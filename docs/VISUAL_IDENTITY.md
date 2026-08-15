# Visual identity

Bede's app and agnusdei.ai are one object, and the palette is where that is
either true or obviously false. A family reads the marketing site, buys a
membership, and logs in; if the ink and paper change on the way through, the
product feels like a different company's software wearing the same name.

This document is the reasoning. The enforcement is
`homeschool-tutor/src/palette.test.ts`, which fails when the two part company.

## The source of truth is the site

`site/assets/site.css`'s `:root` block holds the tokens, and it is the only
place a brand colour is *decided*:

| Token | Value | What it is |
| --- | --- | --- |
| `--ink` | `#1c2438` | Iron-gall ink. Headings, and the ground of every dark band. |
| `--ink-soft` | `#3a4358` | The same ink, lifted. |
| `--fern` | `#47613f` | A fern in a nature notebook. The site's call-to-action. |
| `--fern-deep` | `#33482d` | Fern in shadow. |
| `--vellum` | `#faf6ec` | Foxed paper. The ground almost everything sits on. |
| `--vellum-deep` | `#f1e7d2` | The same paper, older. |
| `--gilt` | `#b8860b` | The gilt on a cloth book spine. |
| `--gilt-light` | `#e0b84a` | Gilt catching light, for dark grounds. |
| `--madder` | `#8c3b2e` | Madder, the old plant dye. |

They are drawn from the things this education is actually made of rather than
from a generic brand ramp, which is why photographs sit on them without
clashing.

## How the app carries them

Both `tailwind.config.js` files (app and demo) re-anchor their existing ramps
on those tokens. The ramp **names** did not change — there are ~930
`sage-*`/`navy-*`/`gold-*`/`parchment-*` classes across the two apps, and
renaming them would be a 46-file rewrite with nothing gained. Only the hex
values moved, the same approach taken when the original leaf-green was
hue-rotated to olive.

| Ramp | Anchors | Reads as |
| --- | --- | --- |
| `navy-*` | `500` = ink-soft, `600` = ink | Brand fill, headings, dark chrome |
| `sage-*` | `500` = fern, `600` = fern-deep | Secondary actions, the nature register |
| `gold-*` | `300` = gilt-light, `500` = gilt | Accents, rating stars |
| `parchment-*` | `50` = vellum, `100` = vellum-deep | The page itself |
| `madder-*` | `500` = madder | The warm accent |

Steps between the anchors are generated around them in OKLab. They are not a
brand promise and are free to be retuned; the anchors are not.

### Three things that are easy to get wrong

**The ramp must darken at every step.** The site's ink is far darker than a
stock Tailwind 500, so a generic lightness curve puts `600` *lighter* than
`500` — which silently inverts every `hover:bg-navy-600` in the app into a
hover that gets paler. That exact inversion was produced, and caught by the
test, while this palette was being built.

**`navy-500` is ink-soft, not ink.** Anchoring true ink at `500` left almost
no lightness budget beneath it, so the primary button's hover state became
imperceptible (1.10:1). With ink-soft resting and ink on hover, the button
deepens into true ink — a 1.56:1 move you can actually see, and a better
description of what the site does anyway.

**`gold-500` is for icons, not prose.** It is the site's real gilt and sits at
3.25:1 on white: a pass for the rating stars it is used on (a non-text UI
component needs 3:1) and a fail as body text. Prose uses `gold-600`/`700`.

## Contrast is measured against the real ground, never white

This app's page is vellum, and several accents sit on their own tinted panels,
so white is a ground it mostly does not use. Checking against white passed
while `text-gold-600` was 3.86:1 on the `bg-parchment-100` panel
`VisualAidCard` actually puts it on, and while `ring-sage-300` was 2.80:1 on
the vellum page — two real WCAG failures behind a green test. Every entry in
`palette.test.ts` now names its own ground, and a colour used on more than one
is checked against all of them.

One consequence worth keeping: the demo's `connect_to_faith` card focuses on
its own gilt-tinted ground, and **no gold light enough to stay above
`gold-500` can clear 3:1 there**. So the ring moved to `gold-700` rather than
the brand colour being distorted to rescue it. When an accent cannot carry a
focus indicator on its own ground, move the indicator.

## Colours written by hand, outside the ramps

A ramp change reaches every `bg-*`/`text-*` class and nothing else. Three
kinds of surface hold colour literally, and each was still carrying the
pre-launch palette after the ramps had moved:

- **`public/manifest.json`** — `theme_color`/`background_color`. The manifest
  **wins over the `<meta>` tag for an installed PWA**, so a stale value there
  reinstates on the tablet exactly the banding the meta was changed to remove.
- **`tailwind.config.js`'s own `keyframes`** — raw `rgba()`, not ramp lookups.
  `ringPulse` went on pulsing the old royal blue around a slate dot.
- **`demo/public/*.html`** — `launch.html` and both privacy notices are plain
  static pages one click from the consent modal, and had their own `--navy`
  and `--gold`. They now use the site tokens under the site's names, and
  inherit its inline-link idiom (ink, gilt underline).

`palette.test.ts` scans all of them for pre-launch literals, so the next hand-
written colour has to be a deliberate choice rather than an oversight.

## What is deliberately *not* brand-locked

`useChatTheme.ts`'s `CHAT_THEMES` and `BUBBLE_COLORS` are a child's own choice
of chat background and bubble colour — Morning Sky, Sunrise, River Stone and
the rest are meant to range beyond the brand, and forcing them into it would
remove the point of the feature. What the palette governs is the *defaults*
(`meadow`, and the `sage` bubble), which do come from the ramps above, so the
out-of-box look is Bede's own.

## Changing a brand colour

Edit `site/assets/site.css`, then move the matching anchor in **both**
`tailwind.config.js` files. `palette.test.ts` will fail until they agree, and
`.github/workflows/frontend-tests.yml`'s change filter names
`site/assets/site.css` specifically so that a site-only edit still runs it —
without that path, the one change most likely to break the agreement would
skip the test written to catch it.
