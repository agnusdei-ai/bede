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

| Variable | Where it sits | Status |
|---|---|---|
| `--photo-hero` | Behind the logo, motto, and founder quote | **`live-oak.jpg`** — sits under an 88% vellum wash, so it reads as a warm branch watermark rather than a photograph. |
| `--photo-curriculum` | Behind the subject grid, and again behind "What stays yours" | **`meadow-grasses.jpg`** — under a 90% wash, a quiet green ground behind the cards. |
| `--photo-closing` | The dark band with the three steps and final call to action | **Empty, deliberately.** Solid ink keeps the final call to action and the notes row crisp. If you do fill it, it wants strong shape — a single tree, a field at dusk, a stack of books edge-on — since it shows through an 82% ink wash and is the most visible of the three. |

To fill a slot, point the variable at the file:

```css
--photo-closing: url('/assets/photos/whatever.jpg');
```

Nothing else changes. The wash, the crop, and the text contrast are already
handled by the band each slot belongs to. Files are named for **what they
are**, not which slot they occupy, so reassigning a photo is a one-line
change and never a rename.

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

| File | Source | Licence | Photographer |
|---|---|---|---|
| `live-oak.jpg` | Supplied by the founder (original camera file, IMG_4847) | Owned by Agnus Dei Technologies | Kristian Gonzalez |
| `meadow-grasses.jpg` | Supplied by the founder (original camera file, IMG_4841) | Owned by Agnus Dei Technologies | Kristian Gonzalez |

Both were shot at a public venue. Each was rotated to its true orientation
from EXIF, then cropped **specifically** to remove things that should not
appear on a marketing page:

- `live-oak.jpg` keeps only the upper-left canopy. The original frame
  contained several identifiable people and a restaurant deck; all of it
  sits below the crop line.
- `meadow-grasses.jpg` keeps the lower band of ivy and ornamental grasses.
  The original frame included a third-party business sign, which sits well
  above the crop line.

If either is ever re-cropped from the original, **re-check both of those**
before committing the result.

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
