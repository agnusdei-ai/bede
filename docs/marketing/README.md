# Marketing sheets

Two one-page Letter sheets carrying the Fall Launch membership pricing, for
sending to families and co-op leaders. The pricing they state is
[`docs/DECISIONS.md`](../DECISIONS.md) entry 10 — change it there first, then
here, or the two drift and the register stops being the source of truth.

| File | What it says |
| --- | --- |
| `membership-pricing.pdf` | The $199/month or $2,149/year Family Membership, the co-op and network tiers, and the per-child table |
| `one-environment.pdf` | What a membership carries, and the four values |

**The `.html` file is the source; the `.pdf` is generated.** Edit the HTML,
regenerate, and commit both. Do not edit a PDF directly — the next
regeneration discards it.

Deliberately **not** published to the website. `scripts/build_pages_site.sh`
copies `site/` and `demo/dist/` into `publish/` and nothing from `docs/`, so
these are sales collateral to attach to an email, not pages a visitor can
reach. Publishing one would bring `site/privacy/index.html`'s storage and
network inventory into scope, which is a separate decision.

No webfonts, no external images, no network requests — the same
`font-src 'self'` constraint that shaped `demo/public/launch.html`, and the
reason these render identically wherever they are opened.

## Regenerating

```bash
cd /path/to/bede
python3 - <<'EOF'
from playwright.sync_api import sync_playwright
import pathlib

for name in ["membership-pricing", "one-environment"]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 816, "height": 1056})
        pg.goto(pathlib.Path(f"docs/marketing/{name}.html").resolve().as_uri())
        # The sheet is one page by construction. 1056px is exactly 11in at
        # 96 DPI, so anything else means content has overflowed onto a
        # second page and the layout needs tightening rather than the check
        # relaxing. Both dimensions are checked: scrollHeight of the fixed
        # page, AND the natural content height with the fixed height
        # released — the first alone was satisfied vacuously while
        # flex-shrink silently crushed ~69px of overflow out of the layout
        # (the gold rule rendered at 0px), which is why the sheets now also
        # set `.page > * { flex-shrink: 0 }`.
        h = pg.evaluate("document.querySelector('.page').scrollHeight")
        assert h == 1056, f"{name} is {h}px tall, expected 1056 (one Letter page)"
        natural = pg.evaluate(
            "(() => { const el = document.querySelector('.page');"
            " el.style.height = 'auto'; const n = el.scrollHeight;"
            " el.style.height = ''; return n; })()"
        )
        assert natural <= 1056, (
            f"{name}'s natural content height is {natural}px — it only "
            "appears to fit because something is being crushed"
        )
        pg.pdf(
            path=f"docs/marketing/{name}.pdf",
            format="Letter",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        b.close()
EOF
```
