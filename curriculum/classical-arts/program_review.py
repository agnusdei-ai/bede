"""Render the public program facts and original support; never open teacher data."""
from html import escape as e

from services import classical_program_service as programs


def render_program_alignment(data):
    html = [
        '<details class="program-alignment"><summary>Program alignment / Correspondencia con programas</summary>'
    ]
    for locale in ("en", "es"):
        es = locale == "es"
        html.append(f'<section data-language="{locale}">')
        for program in ("valor", "memoria_press", "other"):
            row = programs.view(data, program, locale)
            html.extend([
                "<h2>"+e(row["label"])+"</h2>",
                "<p>"+e(row["description"])+"</p><p>"+e(row["schedule_note"])+"</p>",
                "<p>"+e(row["coverage_note"])+"</p>",
            ])
            matches = data["programs"][program]["matches"]
            if matches:
                html.append("<p>"+e(data["program_edition_note"][locale])+"</p><ul>")
                for unit_id, match in matches.items():
                    kind = ("guía" if es else "guide") if match["reference_kind"] == "study_guide" else ("texto" if es else "text")
                    reference = (" · ISBN "+kind+": "+match["reference_isbn"]) if match["reference_isbn"] else ""
                    html.append(
                        "<li><a href=\""+e(match["reference_url"], quote=True)+"\">"+e(match["work"])+"</a>"
                        +" · "+("grado " if es else "Grade ")+e(match["placement"])+e(reference)
                        +" · <code>"+e(unit_id)+"</code></li>"
                    )
                html.append("</ul>")
            if program == "valor":
                routes = [
                    ("Preparación de lectura: grados anteriores a IHP" if es else "Reading preparation below IHP",
                     data["program_steps"]["valor"]["lower"]),
                    ("Preparación para IHP: grados 9–12" if es else "IHP preparation: Grades 9–12",
                     data["program_steps"]["valor"]["upper"]),
                ]
            elif program == "memoria_press":
                routes = [("Preparación original de Bede" if es else "Original Bede preparation",
                           data["program_steps"]["memoria_press"])]
            else:
                routes = []
            for title, steps in routes:
                html.append("<h3>"+e(title)+"</h3><ol>")
                html.extend("<li>"+e(step[locale])+"</li>" for step in steps)
                html.append("</ol>")
            html.append("<ul>")
            html.extend(
                '<li><a href="'+e(ref["url"], quote=True)+'">'+e(ref["title"])+"</a> · "+e(ref["locator"])+"</li>"
                for ref in row["references"]
            )
            html.append("</ul>")
        html.append("</section>")
    html.append("</details>")
    return "\n".join(html)
