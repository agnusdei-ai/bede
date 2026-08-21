"""Build the PDF from the package files themselves, so the document cannot
drift from the export it documents."""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Preformatted,
    Spacer, KeepTogether, Table, TableStyle,
)
from reportlab.platypus import Image as RLImage
from reportlab.platypus.flowables import HRFlowable

PKG = Path(__file__).resolve().parent.parent
OUT = PKG / "dist" / "Agent-Governance-Prompts.pdf"

NAVY = colors.HexColor("#1F3A5F")
GREY = colors.HexColor("#5A5A5A")
RULE = colors.HexColor("#C9C4B8")
CODEBG = colors.HexColor("#EFEEE8")
MADDER = colors.HexColor("#8A3A3A")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=10,
                      leading=14.5, spaceAfter=7, textColor=colors.HexColor("#1A1A1A"))
h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=17, leading=21,
                    textColor=NAVY, spaceBefore=0, spaceAfter=3)
sub = ParagraphStyle("sub", parent=body, fontName="Helvetica-Oblique", fontSize=9.5,
                     textColor=GREY, spaceBefore=2, spaceAfter=12)
h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                    textColor=NAVY, spaceBefore=14, spaceAfter=5)
h3 = ParagraphStyle("h3", parent=body, fontName="Helvetica-Bold", fontSize=10.8, leading=14,
                    textColor=NAVY, spaceBefore=11, spaceAfter=4)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=16, bulletIndent=4, spaceAfter=4)
code = ParagraphStyle("code", parent=body, fontName="Courier", fontSize=7.6, leading=9.9,
                      textColor=colors.HexColor("#20242B"), backColor=CODEBG,
                      borderColor=CODEBG, borderWidth=0.25,
                      borderPadding=(5, 6, 5, 6), leftIndent=2, rightIndent=2,
                      spaceBefore=5, spaceAfter=9)
title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=26, leading=32,
                       alignment=TA_CENTER, textColor=NAVY, spaceAfter=10)
subtitle = ParagraphStyle("subtitle", parent=body, fontSize=12.5, leading=17,
                          alignment=TA_CENTER, textColor=colors.HexColor("#4A4A4A"))
tiny = ParagraphStyle("tiny", parent=body, fontSize=8.6, alignment=TA_CENTER, textColor=colors.HexColor("#7A7A7A"))

# reportlab's built-in Type 1 fonts (Courier, Helvetica) encode cp1252 only.
# A character outside it is not dropped — it is drawn as a WRONG glyph, so a
# box-drawing rule in a source comment silently rendered as a row of "I"s.
# Anything outside the encodable set is mapped to a plain-ASCII stand-in here
# rather than left to surprise the next person who pastes in a nice arrow.
_GLYPH_FALLBACK = {
    "\u2500": "-", "\u2501": "-", "\u2502": "|", "\u2503": "|",
    "\u2192": "->", "\u2190": "<-", "\u21d2": "=>",
    "\u2713": "v", "\u2717": "x", "\u2022": "*", "\u200b": "",
}


def renderable(t: str) -> str:
    out = []
    for ch in t:
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            out.append(_GLYPH_FALLBACK.get(ch, "?"))
        else:
            out.append(ch)
    return "".join(out)


def esc(t: str) -> str:
    t = renderable(t)
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_LINK_RE = re.compile(r'<link href="[^"]+"><font color="#2A5DA0">[^<]*</font></link>')

LINK = colors.HexColor("#2A5DA0")


def inline(t: str) -> str:
    """**bold**, *italic*, `code` and [text](url) -> reportlab markup.

    Links were rendering as their raw markdown source, which reads as a
    typo in a finished document and hides the URL behind punctuation.
    """
    t = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: f'<link href="{m.group(2)}"><font color="#2A5DA0">{m.group(1)}</font></link>',
        t,
    )
    # Stash finished link markup so the escaper below leaves it alone.
    stash: list[str] = []

    def _park(m: re.Match) -> str:
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    t = _LINK_RE.sub(_park, t)

    out, last = [], 0
    for m in re.finditer(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)", t):
        out.append(esc(t[last:m.start()]))
        tok = m.group(0)
        if tok.startswith("**"):
            # Bold can contain code spans; formatting the inner text rather
            # than escaping it is what stops literal backticks reaching the page.
            out.append(f"<b>{inline(tok[2:-2])}</b>")
        elif tok.startswith("*"):
            out.append(f"<i>{esc(tok[1:-1])}</i>")
        else:
            out.append(f'<font face="Courier" size="9">{esc(tok[1:-1])}</font>')
        last = m.end()
    out.append(esc(t[last:]))
    rendered = "".join(out)
    for i, link in enumerate(stash):
        rendered = rendered.replace(f"\x00{i}\x00", link)
    return rendered

def wrap_code(text: str, width: int) -> str:
    """Hard-wrap long lines so nothing runs off the page.

    Preformatted does NOT wrap — an over-long line is simply drawn past the
    page edge and silently lost. Continuation lines get a visible hanging
    indent so a wrapped line cannot be mistaken for a real newline, which
    matters most for the prompt blocks: someone retyping them from this
    document must be able to tell the two apart.
    """
    out = []
    for line in renderable(text).replace("\t", "    ").split("\n"):
        if len(line) <= width:
            out.append(line)
            continue
        lead = len(line) - len(line.lstrip(" "))
        cont = " " * min(lead + 4, width - 20)
        out.extend(textwrap.wrap(
            line, width=width, initial_indent="", subsequent_indent=cont,
            break_long_words=True, break_on_hyphens=False,
            replace_whitespace=False, drop_whitespace=False) or [line])
    return "\n".join(out)


def code_block(text: str, size: float | None = None):
    """Render a literal block.

    Deliberately a Paragraph rather than Preformatted: Preformatted silently
    ignores backColor (verified — it draws no fill at all), and the shaded
    panel is what separates literal prompt text from prose in this document.
    Line breaks are explicit <br/>, and indentation is held with non-breaking
    spaces since the wrapping is already done by wrap_code above.
    """
    st = code if size is None else ParagraphStyle("c2", parent=code, fontSize=size, leading=size * 1.3)
    # Courier advance width is 0.6 em; frame is 6.5in minus the style's own padding.
    usable = (LETTER[0] - 2 * inch) - 14
    width = int(usable / (st.fontSize * 0.6))
    lines = []
    for line in wrap_code(text, width).split("\n"):
        e = esc(line) or "&nbsp;"
        # preserve leading indentation and any run of 2+ spaces
        e = re.sub(r"^ +", lambda m: "&nbsp;" * len(m.group(0)), e)
        e = re.sub(r"  +", lambda m: "&nbsp;" * len(m.group(0)), e)
        lines.append(e)
    return Paragraph("<br/>".join(lines), st)

CELL = ParagraphStyle("cell", parent=body, fontSize=8.6, leading=11.2, spaceAfter=0)
CELL_H = ParagraphStyle("cellh", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)


def md_table(rows: list[str]):
    """Render a markdown table as a real table. Raw pipe characters in a
    finished document read as a rendering failure, which is exactly what
    they were."""
    parsed = []
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells if c != ""):
            continue  # the |---|---| separator row
        parsed.append(cells)
    if not parsed:
        return Spacer(1, 0)
    ncols = max(len(r) for r in parsed)
    parsed = [r + [""] * (ncols - len(r)) for r in parsed]
    data = [[Paragraph(inline(c), CELL_H if ri == 0 else CELL) for c in row]
            for ri, row in enumerate(parsed)]
    avail = LETTER[0] - 2 * inch
    # weight columns by their longest cell so a narrow "#" column stays narrow
    weights = [max(len(r[c]) for r in parsed) or 1 for c in range(ncols)]
    widths = [avail * w / sum(weights) for w in weights]

    # A dotted config key broken across lines reads as two keys and can be
    # copied wrong, so column 0 gets the width its longest code span needs.
    # This has to happen AFTER the proportional split, not before: an earlier
    # cut applied the minimum first and the rescale below silently undid it.
    CODE_PT = 9  # the size inline() renders a code span at
    longest = max(
        (len(m) for row in parsed for m in re.findall(r"`([^`]+)`", row[0])), default=0
    )
    needed = longest * CODE_PT * 0.6 + 16
    if ncols > 1 and needed > widths[0] and needed < avail * 0.55:
        deficit = needed - widths[0]
        widths[0] = needed
        rest = sum(widths[1:])
        widths[1:] = [w - deficit * (w / rest) for w in widths[1:]]

    widths[-1] += avail - sum(widths)  # absorb rounding
    t = Table(data, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAF9F6")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return KeepTogether([Spacer(1, 4), t, Spacer(1, 10)])


def render_markdown(md: str) -> list:
    # HTML comments are markup, not content — an SPDX header rendered as body
    # text is the file's licence leaking onto the page.
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    # Layout tags are markup too. A README that positions an image with <img>
    # renders that tag as a line of body text here, which is worse than simply
    # not showing the picture — the PDF has its own contributors page for it.
    # Deliberately a short, named list: an XML-ish tag in a prompt block (for
    # example <untrusted source="...">) is CONTENT and must survive.
    md = re.sub(r"</?(?:img|br|div|span|p|hr)\b[^>]*>", "", md, flags=re.S)
    flow, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            flow.append(code_block("\n".join(buf)))
            continue
        if line.startswith("|"):
            buf = []
            while i < len(lines) and lines[i].startswith("|"):
                buf.append(lines[i]); i += 1
            flow.append(md_table(buf))
            continue
        if re.match(r"^#{1,4} ", line):
            lvl = len(re.match(r"^#+", line).group(0))
            style = h2 if lvl <= 2 else h3
            flow.append(Paragraph(inline(re.sub(r"^#+\s*", "", line)), style))
            i += 1
            continue
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", line.strip()):
            flow.append(HRFlowable(width="100%", thickness=0.5, color=RULE,
                                   spaceBefore=8, spaceAfter=10))
            i += 1
            continue
        if re.match(r"^[-*] ", line):
            # Gather continuation lines: a wrapped bullet is one bullet, not a
            # bullet followed by an orphan paragraph.
            buf = [re.sub(r"^[-*]\s*", "", line)]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(
                r"^([-*] |\d+\. |#{1,4} |\||```|-{3,}$)", lines[i]
            ):
                buf.append(lines[i].strip())
                i += 1
            flow.append(Paragraph(inline(" ".join(buf)), bullet, bulletText="•"))
            continue
        if re.match(r"^\d+\. ", line):
            num = re.match(r"^(\d+)\.", line).group(1)
            buf = [re.sub(r"^\d+\.\s*", "", line)]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(
                r"^([-*] |\d+\. |#{1,4} |\||```|-{3,}$)", lines[i]
            ):
                buf.append(lines[i].strip())
                i += 1
            flow.append(Paragraph(inline(" ".join(buf)), bullet, bulletText=f"{num}."))
            continue
        if not line.strip():
            i += 1
            continue
        buf = [line]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^([-*] |\d+\. |#{1,4} |\||```)", lines[i]):
            buf.append(lines[i]); i += 1
        flow.append(Paragraph(inline(" ".join(buf)), body))
    return flow

def section(num_title: str, subtitle_text: str, flow: list, first=False) -> list:
    out = [] if first else [PageBreak()]
    out.append(Paragraph(esc(num_title), h1))
    out.append(Paragraph(f'<font face="Courier" size="8.5">{esc(subtitle_text)}</font>', sub))
    out.extend(flow)
    return out

read = lambda p: (PKG / p).read_text(encoding="utf-8").rstrip()

story: list = []

# Title page
story += [
    Spacer(1, 2.4 * inch),
    Paragraph("Agent Governance Prompts", title),
    Paragraph("A portable governance layer for LLM agents that take real actions", subtitle),
    Spacer(1, 0.45 * inch),
    Paragraph("Complete package contents — constitution, prompt blocks,<br/>reference implementation, and tests",
              ParagraphStyle("t2", parent=subtitle, fontSize=10.5, textColor=GREY, fontName="Helvetica-Oblique")),
    Spacer(1, 1.5 * inch),
    Paragraph("Generated from agent-governance.tar.gz", tiny),
    Spacer(1, 0.08 * inch),
    Paragraph("Licensed under the Apache License, Version 2.0 — see section 11", tiny),
    PageBreak(),
]

TOC = [
    ("1", "README.md", "Overview, quick start, and the reasoning behind each layer"),
    ("2", "constitution.template.json", "The immutable layer"),
    ("3", "placeholders.json", "Every placeholder, documented"),
    ("4", "prompts/02-ethical-boundaries.md", "What the agent is not, and what stops it"),
    ("5", "prompts/03-action-safety.md", "Limits on actions the agent originates"),
    ("6", "prompts/04-operating-rules.md", "Honesty and turn-shape rules"),
    ("7", "prompts/05-tool-guidance.md", "How tools may be spent"),
    ("8", "prompts/optional/", "Opt-in blocks — rendered only when named"),
    ("9", "profiles/", "Filled-in placeholder sets — a starting point, never a configuration"),
    ("10", "reference/", "governance.py · governance.ts · parity_check.ts · limits.py · test_governance.py"),
    ("11", "LICENSE · NOTICE", "Apache License 2.0, and what it does not cover"),
]
story.append(Paragraph("Contents", h1))
story.append(Spacer(1, 0.18 * inch))
for n, name, desc in TOC:
    story.append(KeepTogether([
        Paragraph(f'<b><font color="#1F3A5F">{n}.</font></b>&nbsp;&nbsp;'
                  f'<font face="Courier" size="9.5">{esc(name)}</font>', body),
        Paragraph(f'<i><font color="#5A5A5A" size="9">{esc(desc)}</font></i>',
                  ParagraphStyle("d", parent=body, leftIndent=20, spaceAfter=9)),
    ]))

story += section("1.  README", "README.md", render_markdown(read("README.md")))
story += section("2.  Constitution template",
                 "constitution.template.json — copy to constitution.json, fill every placeholder, then hash it",
                 [code_block(read("constitution.template.json"))])
story += section("3.  Placeholders",
                 "placeholders.json — the builder refuses to render with any of these unresolved",
                 [code_block(read("placeholders.json"))])
story += section("4.  Ethical boundaries", "prompts/02-ethical-boundaries.md",
                 [code_block(read("prompts/02-ethical-boundaries.md"))])
story += section("5.  Action safety", "prompts/03-action-safety.md",
                 [code_block(read("prompts/03-action-safety.md"))])
story += section("6.  Operating rules", "prompts/04-operating-rules.md",
                 [code_block(read("prompts/04-operating-rules.md"))])
story += section("7.  Tool guidance", "prompts/05-tool-guidance.md",
                 [code_block(read("prompts/05-tool-guidance.md"))])

story += section("8.  Optional blocks",
                 "prompts/optional/ — off unless named in extra_blocks, so an agent is not "
                 "governed by rules its own surface never meets",
                 [code_block(read("prompts/optional/10-untrusted-content.md"))])

story.append(PageBreak())
story.append(Paragraph("Installer", h1))
story.append(Paragraph('<font face="Courier" size="8.5">tools/harden-openclaw.sh</font>', sub))
story.extend(render_markdown(
    "One command for someone who would rather not read the runbook first. It "
    "writes a hardened configuration with a fresh access token, installs the "
    "governance prompt where OpenClaw reads it, checks its own work, and stops "
    "with an error if the result is not actually hardened. It backs up anything "
    "it replaces and is safe to run twice.\n\n```bash\nbash tools/harden-openclaw.sh\n```"))
story.append(code_block(read("tools/harden-openclaw.sh"), size=6.6))

story += section("9.  Profiles",
                 "profiles/ — every placeholder filled for one real agent",
                 [code_block(read("profiles/openclaw.values.json"))])
story.append(PageBreak())
story.append(Paragraph("Deployment runbook", h2))
story.append(Paragraph('<font face="Courier" size="8.5">profiles/openclaw.runbook.md</font>', sub))
story.extend(render_markdown(read("profiles/openclaw.runbook.md")))
story.append(PageBreak())
story.append(Paragraph("Hardened configuration", h2))
story.append(Paragraph('<font face="Courier" size="8.5">profiles/openclaw.hardened.json5 — copy to ~/.openclaw/openclaw.json</font>', sub))
story.append(code_block(read("profiles/openclaw.hardened.json5")))

story += section("10.  Reference implementation",
                 "reference/ — a ~100-line builder in two runtimes, the constants, and the guards",
                 [Paragraph(inline(
                     "The prompts are plain text and the constitution is plain JSON, so this layer is "
                     "deliberately small and easy to port. Three properties are worth preserving in any port: "
                     "verify the digest at boot and refuse to start on a mismatch; refuse to render an "
                     "unresolved placeholder; keep the constitution block first and read-only."), body)])
for fname, label in [
    ("reference/governance.py", "Python builder"),
    ("reference/governance.ts", "TypeScript builder"),
    ("reference/parity_check.ts", "Renders through the TS builder so a test can diff it against Python's"),
    ("reference/limits.py", "The constants a prompt cannot argue with"),
    ("reference/test_governance.py", "Guards — each verified by breaking what it guards"),
]:
    story.append(PageBreak())
    story.append(Paragraph(f'<font face="Courier">{esc(fname)}</font>', h2))
    story.append(Paragraph(f"<i>{esc(label)}</i>", sub))
    story.append(code_block(read(fname)))

# ---- Contributors ----
_photo = PKG / "assets" / "contributor.jpg"
if _photo.exists():
    story.append(PageBreak())
    story.append(Paragraph("Contributors", h1))
    story.append(Paragraph(
        '<font face="Courier" size="8.5">assets/contributor.jpg</font>', sub))
    _img = RLImage(str(_photo), width=1.35 * inch, height=1.35 * inch)
    _img.hAlign = "LEFT"
    _bio = [
        Paragraph("<b>JK Gonzalez</b> — security practitioner", body),
        Paragraph(
            "Commissioned this package, reviewed every layer of it, and is putting it in "
            "front of a real OpenClaw deployment. The direction that shaped it came from "
            "practice rather than theory: check the running registry instead of the "
            "documentation, ship the config instead of describing it, and say plainly "
            "which failures a prompt cannot touch.", body),
    ]
    # Leave a few points of slack: reportlab's own cell padding pushed an
    # exact-width table past the frame by 6pt, which the overflow check caught.
    _avail = (LETTER[0] - 2 * inch) - 10
    _t = Table([[_img, _bio]], colWidths=[1.55 * inch, _avail - 1.55 * inch],
               hAlign="LEFT")
    _t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(_t)

story += section("11.  Licensing", "NOTICE — attribution and scope",
                 [code_block(read("NOTICE"))])
story.append(Paragraph("Apache License 2.0 — full text", h2))
story.append(Paragraph(
    "Reproduced verbatim from apache.org. Use this package in commercial or closed products, "
    "modify it, and redistribute it; keep the notice and state your changes. It grants no "
    "trademark rights and carries no warranty.", body))
story.append(code_block(read("LICENSE"), size=6.4))


def decorate(canvas, doc):
    canvas.saveState()
    if canvas.getPageNumber() > 1:
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(1 * inch, 0.72 * inch, LETTER[0] - 1 * inch, 0.72 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#8A8A8A"))
        canvas.drawCentredString(LETTER[0] / 2, 0.52 * inch, str(canvas.getPageNumber()))
        canvas.drawString(1 * inch, 0.52 * inch, "Agent Governance Prompts")
    canvas.restoreState()


# dist/ is gitignored, so a fresh clone does not have it.
OUT.parent.mkdir(parents=True, exist_ok=True)

doc = BaseDocTemplate(str(OUT), pagesize=LETTER,
                      leftMargin=1 * inch, rightMargin=1 * inch,
                      topMargin=0.85 * inch, bottomMargin=0.95 * inch,
                      title="Agent Governance Prompts",
                      author="Agent Governance export",
                      subject="Portable governance layer for LLM agents that take real actions")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=decorate)])
doc.build(story)
print("wrote", OUT.name)
