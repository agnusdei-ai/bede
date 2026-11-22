"""Self-contained reading packets, with the adult key in a separate file."""
from html import escape
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "generated-artifacts/upper-school-review"


def inline(text):
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)

    def link(match):
        label, url = match.groups()
        if url == "wallace-4-1-review-extract.md":
            return f'<a href="#wallace-reference">{label}</a>'
        if url.startswith("https://"):
            return f'<a href="{url}" rel="noopener noreferrer">{label}</a>'
        return f"{label} ({url})"
    return re.sub(r"\[([^]]+)\]\(([^)]+)\)", link, text)


def markdown(text):
    result, paragraph = [], []

    def flush():
        if paragraph:
            result.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()
    for line in text.splitlines():
        heading = re.match(r"^(#{1,3}) (.+)$", line)
        if heading:
            flush()
            level, title = len(heading[1]), inline(heading[2])
            result.append(f"<h{level}>{title}</h{level}>")
        elif not line.strip():
            flush()
        elif re.match(r"^(?:- |\d+\. )", line):
            flush()
            result.append('<p class="item">' + inline(line) + "</p>")
        else:
            paragraph.append(line.strip())
    flush()
    return "\n".join(result)


def export():
    OUT.mkdir(parents=True, exist_ok=True)
    reference = markdown((HERE / "wallace-4-1-review-extract.md").read_text())
    for audience in ("student", "teacher"):
        source = HERE / f"grade-9-week-10-math-{audience}.md"
        body = markdown(source.read_text())
        html = f"""<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Bede Grade 9 Week 10 mathematics — {audience}</title>
<style>
body{{max-width:49rem;margin:2rem auto;padding:0 1.25rem;color:#192a35;
font:18px/1.6 Georgia,serif;background:#fff}}
h1,h2,h3{{line-height:1.2;break-after:avoid}}
h1{{font-size:2rem}}h2{{font-size:1.45rem;margin-top:2rem}}
h3{{font-size:1.15rem}}code{{font:0.9em/1.5 monospace;overflow-wrap:anywhere}}
a{{color:#254d72;overflow-wrap:anywhere}}.item{{padding-left:1rem}}
.status{{font:0.8rem/1.5 sans-serif;letter-spacing:.04em;
border-bottom:1px solid #bcc4ca;padding-bottom:1rem}}
section{{margin-top:3rem;border-top:2px solid #bcc4ca;padding-top:1rem}}
@media print{{body{{font-size:11pt;margin:0;max-width:none}}section{{break-before:page}}}}
</style>
<div class="status">BEDE · LOCAL CONTENT REVIEW · {audience.upper()} PACKET · NOT LIVE-ACTIVATED</div>
<main>{body}<section id="wallace-reference">{reference}</section></main></html>
"""
        output = OUT / f"grade-9-week-10-math-{audience}.html"
        output.write_text(html, encoding="utf-8")
        print(output.relative_to(HERE.parents[1]))


if __name__ == "__main__":
    export()
