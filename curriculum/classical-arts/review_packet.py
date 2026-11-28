"""Self-contained student-only review packet. Never opens the private bundle."""
import base64
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "homeschool-api"))
from services.classical_arts_service import catalog, lesson, load_release, RELEASE_FILE

OUTPUT = ROOT / "generated-artifacts/classical-arts-review/packet.html"


def e(value):
    return escape(str(value), quote=True)


def source_block(source, locale):
    language = "Original en inglés" if locale == "es" and source["language"] == "en" else source["language"]
    return (
        "<details class=source><summary>"+e(source["title"])+" · "+e(language)+"</summary>\n"
        "<p>"+e(source["locator"])+"</p>\n<pre>"+e(source["text"])+"</pre>\n"
        '<p><a href="'+e(source["url"])+'">Source / fuente</a> · '+e(source["rights"])+"</p>\n</details>\n"
    )


def packet():
    data = load_release()
    digest = sha256(RELEASE_FILE.read_bytes()).hexdigest()
    titles = {unit["id"]: unit["title"] for unit in catalog("12")["units"]}
    contents = []
    for unit in data["units"]:
        html = ['<details class="unit" id="'+e(unit["id"])+'"><summary>'+e(titles[unit["id"]])
                +' <small>Grade '+str(unit["min_grade"])+'+ · 3 weeks</small></summary>\n'
                '<button class=copy type=button>Copy this unit / Copiar esta unidad</button>\n']
        for locale in ("en", "es"):
            translated = next(x for x in catalog("12", locale)["units"] if x["id"] == unit["id"])
            html += ['<section data-language="'+locale+'"><h2>'+e(translated["title"])+"</h2>\n",
                     "<p>"+e(translated["summary"])+"</p>\n",
                     "<p class=warning>"+e(translated["content_note"])+"</p>\n"]
            for week in range(1, 4):
                row = lesson(unit["id"], "12", week, locale)
                html += ["<article><h3>"+("Semana " if locale == "es" else "Week ")+str(week)+"</h3>\n",
                         "<p><strong>"+e(row["objective"])+"</strong></p>\n<ol>\n"]
                for step in row["steps"]:
                    html += ["<li><strong>"+e(step["label"])+":</strong> "+e(step["instruction"])+"</li>\n"]
                html += ["</ol><details><summary>"+("Otras rutas de apoyo" if locale == "es" else "Other support routes")+"</summary><ul>\n"]
                for support, label in (("independent", "Independiente" if locale == "es" else "Independent"), ("extension", "Ampliación" if locale == "es" else "Extension")):
                    alternative = lesson(unit["id"], "12", week, locale, support)
                    html += ["<li><strong>"+e(label)+":</strong> "+e(alternative["steps"][-1]["instruction"])+"</li>\n"]
                html += ["</ul></details>\n<h4>"+("Evaluación y transferencia" if locale == "es" else "Checks and transfer")+"</h4>\n<ul>\n"]
                html += ["<li>"+e(check["kind"])+": "+e(check["prompt"])+"</li>\n" for check in row["assessments"]]
                html += ["</ul>\n", source_block(row["source"], locale)]
                html += [source_block(source, locale) for source in row["companion_sources"]]
                html += ["</article>\n"]
            html += ["</section>\n"]
        if unit["id"] == "michelangelo-looking":
            html += ['<details class=gallery><summary>Adult preview · decorative artistic nudity / Revisión adulta · desnudos artísticos decorativos</summary><div class=images>']
            for image in unit["lessons"][0]["visual_previews"]:
                raw = (RELEASE_FILE.parent / "classical-arts-art" / (image["id"]+".jpg")).read_bytes()
                assert sha256(raw).hexdigest() == image["asset_sha256"]
                html += ['<figure><img alt="'+e(image["title"])+'" src="data:image/jpeg;base64,'
                         +base64.b64encode(raw).decode()+'"><figcaption>'+e(image["title"])+' · <a href="'
                         +e(image["source_url"])+'">Source / fuente</a></figcaption></figure>']
            html += ["</div></details>"]
        html += ["</details>\n"]
        contents += html
    crosswalk = (Path(__file__).parent / "CROSSWALK.md").read_text()
    verification = (Path(__file__).parent / "VERIFICATION.md").read_text()
    document = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Bede — classical literature & arts review</title>
<style>
:root{font-family:system-ui,sans-serif;color:#19372f;background:#f6f5ef;line-height:1.65}body{margin:0}
main{max-width:940px;margin:auto;padding:36px 22px 80px}h1,h2,h3{line-height:1.2}h1{font-size:clamp(2rem,6vw,3.1rem);margin:12px 0}
.eyebrow{letter-spacing:.12em;font-size:.8rem;text-transform:uppercase}.status{border-left:4px solid #587f66;padding:12px 18px;background:white}
nav{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0}button{font:inherit;border:1px solid #587f66;background:white;color:#19372f;padding:9px 14px;border-radius:5px;cursor:pointer}
button:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid #a3691e;outline-offset:3px}
.unit{background:white;border:1px solid #d6dfd6;border-radius:8px;margin:14px 0;padding:17px}summary{font-weight:650;cursor:pointer}small{display:block;font-weight:400}
.unit>section{padding:8px 0}.unit article{border-top:1px solid #d6dfd6;margin-top:25px;padding-top:12px}
.warning{border-left:3px solid #a3691e;padding-left:12px}.source{margin:15px 0;padding:12px;background:#f4f6f2}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}a{color:#244e76}.copy{margin-top:15px;font-size:.85rem}
li{margin:.65em 0}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px}figure{margin:15px 0}img{max-width:100%;max-height:460px;object-fit:contain}
html[lang=en] [data-language=es],html[lang=es] [data-language=en]{display:none}code{overflow-wrap:anywhere;font-size:.85em}
@media print{body{background:white;color:black}main{padding:0;max-width:none}nav,button,#status{display:none!important}.unit{border:0;padding:0;break-before:page}.gallery{display:none}.source{background:white}h3{break-after:avoid}pre,li{orphans:3;widows:3}a{color:black}}
</style></head><body><main>
<p class=eyebrow>Bede · Agnus Dei</p><h1>Classical literature & arts</h1>
<p>Student-only review packet · Paquete de revisión sin claves docentes</p>
<div class=status><strong>12 bounded units · 36 weekly records · English & Spanish</strong>
<p>This is an inspectable supplement, not a full grade-year curriculum. Tutoring activation remains off by default. Nothing here establishes production deployment, human acceptance, Pilot GO or learning efficacy.</p>
<p>Son unidades complementarias, no años curriculares completos. La activación de tutoría permanece deshabilitada por defecto. Las fuentes literarias inglesas están identificadas; las instrucciones son originales de Bede en español general.</p></div>
<nav><button type=button id=en>English</button><button type=button id=es>Español</button><button type=button id=print>Print / Imprimir</button></nav>
<p id=status role=status aria-live=polite>Open a unit to inspect all three weeks. Source passages can be expanded. Copy uses the selected language; print expands the selected-language packet.</p>
<p><strong>Source projection SHA-256</strong><br><code>""" + digest + """</code></p>
<p>Everyman requires the adult's agreed edition. Source-specific music study requires an actual lawful score or recording; none is supplied. Without the relevant source, record original-method practice only. Private adult models and keys are excluded.</p>
""" + "".join(contents) + """
<details class=unit><summary>Scope, provenance and release boundaries</summary><pre>""" + e(crosswalk) + """</pre></details>
<details class=unit><summary>Verification evidence and limits</summary><pre>""" + e(verification) + """</pre></details>
</main><script>
const status=document.getElementById('status');
for(const lang of ['en','es'])document.getElementById(lang).onclick=()=>{document.documentElement.lang=lang};
document.getElementById('print').onclick=()=>window.print();
let opened=[];
window.addEventListener('beforeprint',()=>{opened=[...document.querySelectorAll('details')].map(d=>[d,d.open]);opened.forEach(([d])=>d.open=true)});
window.addEventListener('afterprint',()=>{opened.forEach(([d,was])=>d.open=was)});
document.querySelectorAll('.copy').forEach(button=>button.onclick=async()=>{
 const unit=button.closest('.unit'),lang=document.documentElement.lang;
 const text=unit.querySelector('summary').textContent+'\\n\\n'+[...unit.querySelectorAll('[data-language]')].filter(p=>p.dataset.language===lang).map(p=>p.textContent).join('\\n\\n');
 try{await navigator.clipboard.writeText(text);status.textContent=lang==='es'?'Unidad copiada.':'Unit copied.'}
 catch{status.textContent=lang==='es'?'No se pudo copiar automáticamente. Selecciona el texto o imprime.':'Automatic copy is unavailable. Select the text or print.'}
});
</script></body></html>"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(document)
    print(json.dumps({"file": str(OUTPUT), "student_projection_sha256": digest, "units": 12, "weeks": 36}))


if __name__ == "__main__":
    packet()
