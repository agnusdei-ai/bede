# Photographs for the home page

Three background bands on `site/index.html` are built to hold a photograph.
All three ship **empty** and the page is complete without them — each band
has a solid colour underneath, so nothing is broken, missing, or 404-ing
while a slot is unset. Dropping a photo in is a one-line change.

## The rule

**Real photographs only. No AI-generated imagery.**

This page sells a curriculum built on real books, real nature study, and a
family's own judgment. Illustrating it with a synthesised meadow would
contradict the product in the one place a visitor forms their first
impression. It would also sit badly next to the promise, three sections
down, that Bede never fabricates.

## The three slots

Set these in the `:root` block near the top of `site/index.html`.

| Variable | Where it sits | What it wants |
|---|---|---|
| `--photo-hero` | Behind the logo, motto, and founder quote | Quiet and wide: a meadow, a hedgerow, morning light through a window onto a table. Nothing with a recognisable face. It sits under a 93% vellum wash, so only tone and texture survive — pick for mood, not detail. |
| `--photo-curriculum` | Behind the subject grid, and again behind "What stays yours" | Books and study: a shelf of cloth-bound spines, an open book, a pressed fern on a page, a nature notebook with handwriting. Also heavily washed. |
| `--photo-closing` | The dark band with the three steps and final call to action | The most visible of the three — it shows through a 90% ink wash as texture. Something with strong shape: a single tree, a field at dusk, a stack of books edge-on. |

To activate one, replace `none`:

```css
--photo-hero: url('/assets/photos/hero.jpg');
```

Nothing else changes. The wash, the crop, and the text contrast are already
handled by the band each slot belongs to.

## Sourcing

Prefer **public domain / CC0**, which carries no attribution obligation and
no licence-change risk on a commercial page. Good places to look:

- **Wikimedia Commons** — filter to public domain or CC0. Deep holdings of
  botanical and landscape photography.
- **The Library of Congress** — its online collections flag rights clearly;
  a great deal is free of known restrictions.
- **Smithsonian Open Access** — millions of CC0 assets, strong on natural
  history.
- **The New York Public Library Digital Collections** — public domain
  scans and photographs.
- **Openverse** — aggregates the above and more; filter by CC0.
- **Unsplash / Pexels** — permissive for commercial use and easy to search,
  but the licence is the platform's own rather than public domain. Fine to
  use; just record which it was.

Whichever you pick, **check the licence on the item itself**, not on the
site as a whole — collections mix rights, and a public-domain-heavy archive
still holds items that are not.

## What to record

Add a row here for each photo you commit, so the provenance lives beside
the file rather than in someone's memory:

| File | Source & item URL | Licence | Photographer |
|---|---|---|---|
| _(none yet)_ | | | |

## Preparing the file

- **Format:** JPEG. These are washed-out background textures; there is
  nothing for PNG or WebP transparency to do.
- **Width:** 2000px is plenty. The bands are full-bleed but heavily
  overlaid, so detail beyond that is bytes nobody sees.
- **Weight:** keep each under ~300KB. This page has no build step and no
  image pipeline — whatever you commit is what every visitor downloads.
- **Crop:** centre-weighted. Each band uses `background-position: center`
  and `background-size: cover`, so the edges are the first thing lost on a
  narrow screen.
