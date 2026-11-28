"""Factual course references and original Bede support, not publisher guides.

Only the listed matches have first-party evidence. Reading-list placement is
not an assigned school week, an edition match, or endorsement. No proprietary
questions, commentary, tests or teacher answers are reproduced.
"""
VALOR_LIST = "https://www.valoreducation.org/s/Valor_26-27_Reading-List-ISBN-080426.pdf"
VALOR_IHP = "https://www.valoreducation.org/integrated-humanities-program"
MP_MIDSUMMER = "https://www.memoriapress.com/curriculum/literature-and-poetry/a-midsummer-nights-dream-student-guide-second-edition/"
MP_CAESAR = "https://www.memoriapress.com/curriculum/literature-and-poetry/ninth/julius-caesar-set/"


def localized(en, es):
    return {"en": en, "es": es}


def match(work, grade, isbn, url, placement=None, reference_kind="reading_text"):
    return {
        "work": work, "min_grade": grade, "placement": placement or str(grade),
        "reference_isbn": isbn, "reference_url": url, "reference_kind": reference_kind,
    }


PROGRAMS = {
    "bede": {
        "label": localized("Bede classical sequence", "Secuencia clásica de Bede"),
        "description": localized(
            "Original Bede units and verified source passages.",
            "Unidades originales de Bede y pasajes con fuentes verificadas."),
        "coverage_note": localized(
            "Choose a school or press to see the verified course matches.",
            "Elige una escuela o editorial para ver las correspondencias verificadas."),
        "references": [], "matches": {},
    },
    "valor": {
        "label": localized("Valor Education", "Valor Education"),
        "description": localized(
            "Reading placements from Valor's published 2026–27 list. Older learners may revisit an earlier listed work.",
            "Ubicación de lecturas según la lista publicada de Valor de 2026–27. Se puede retomar una obra de un grado anterior."),
        "coverage_note": localized(
            "Six listed works have bounded support here. The Comedy of Errors (7), Richard II (11), Hamlet, King Lear and Othello (12) are not covered by this supplement.",
            "Aquí hay apoyo acotado para seis obras de la lista. Este complemento no cubre La comedia de las equivocaciones (7), Ricardo II (11), Hamlet, El rey Lear ni Otelo (12)."),
        "references": [
            {"title": "Valor 2026–27 reading list with ISBNs", "url": VALOR_LIST,
             "locator": "Grade headings 5, 6, 8, 10 and 11; Shakespeare rows"},
            {"title": "Valor Integrated Humanities Program", "url": VALOR_IHP,
             "locator": "Grades 9–12; primary-text seminars, panel presentations and symposium"},
        ],
        "matches": {
            "midsummer-scene": match("A Midsummer Night's Dream", 5, "9780743477543", VALOR_LIST),
            "caesar-plutarch": match("Julius Caesar", 6, "9780743482745", VALOR_LIST),
            "merchant-mercy": match("The Merchant of Venice", 8, "9780743477567", VALOR_LIST),
            "macbeth-deliberation": match("Macbeth", 10, "9780743477109", VALOR_LIST),
            "tempest-release": match("The Tempest", 10, "9780743482837", VALOR_LIST),
            "henryv-community": match("Henry V", 11, "9781982109417", VALOR_LIST),
        },
    },
    "memoria_press": {
        "label": localized("Memoria Press", "Memoria Press"),
        "description": localized(
            "Verified product placements, with original Bede preparation for vocabulary, comprehension, discussion and expression.",
            "Ubicaciones verificadas en los productos, con preparación original de Bede para vocabulario, comprensión, diálogo y expresión."),
        "coverage_note": localized(
            "Verified here: the Midsummer Student Guide, second edition (9+), and Julius Caesar set (8+). Other press courses are not mapped here.",
            "Verificados aquí: la guía del estudiante de Sueño de una noche de verano, segunda edición (9+), y el conjunto de Julio César (8+). No se han vinculado aquí otros cursos de la editorial."),
        "references": [
            {"title": "Midsummer Student Guide, second edition", "url": MP_MIDSUMMER,
             "locator": "Grades 9+; ISBN identifies the study guide, not Shakespeare's text; grammar, logic and rhetoric stages"},
            {"title": "Julius Caesar set", "url": MP_CAESAR,
             "locator": "Grades 8+ product heading; student guide, second edition; reading notes, vocabulary, comprehension and Socratic discussion"},
        ],
        "matches": {
            "midsummer-scene": match("A Midsummer Night's Dream", 9, "9781547702299", MP_MIDSUMMER, "9+", "study_guide"),
            "caesar-plutarch": match("Julius Caesar", 8, "", MP_CAESAR, "8+"),
        },
    },
    "other": {
        "label": localized("Another curriculum / adult selection", "Otro currículo / selección adulta"),
        "description": localized(
            "Use Bede's cited passage alongside the actual assigned reading. No publisher placement is assumed.",
            "Usa el pasaje citado por Bede junto a la lectura realmente asignada. No se presupone una ubicación editorial."),
        "coverage_note": localized(
            "The adult checks the assigned work, passage and edition before selecting this support.",
            "La persona adulta comprueba la obra, el pasaje y la edición asignados antes de elegir este apoyo."),
        "references": [], "matches": {},
    },
}

SCHEDULE_NOTE = localized(
    "Weeks 1–3 are Bede support steps, not the school's or publisher's calendar. Keep the actual assigned reading and schedule.",
    "Las semanas 1–3 son pasos de apoyo de Bede, no el calendario escolar o editorial. Conserva la lectura y el calendario realmente asignados.")

EDITION_NOTE = localized(
    "Bede supplies its cited historical edition, not the listed modern text or study-guide edition. Check the act, scene and passage in the assigned book; page numbers and editorial notes are not interchangeable.",
    "Bede aporta la edición histórica citada, no la edición moderna del texto o de la guía. Comprueba acto, escena y pasaje en el libro asignado; páginas y notas editoriales no son intercambiables.")

PROGRAM_STEPS = {
    "valor": {
        "lower": [
            localized("Choose a short part of the supplied passage. Retell what happens and point to a word that supports your account. Ask one question at a time.",
                      "Elige una parte breve del pasaje. Cuenta qué sucede y señala una palabra que apoye tu relato. Haz una pregunta a la vez."),
            localized("Offer a possible reading, then ask what detail might support a different reading. Listen and return to the actual words; do not supply the learner's answer.",
                      "Propón una lectura posible y pregunta qué detalle apoyaría otra. Escucha y vuelve a las palabras del texto; no des la respuesta de quien aprende."),
            localized("Prepare a short spoken or typed explanation with a located detail and one question for class. This is Bede reading preparation, not a high-school IHP panel or school assessment.",
                      "Prepara una explicación breve, oral o escrita, con un detalle localizado y una pregunta para clase. Es preparación de lectura de Bede, no un panel de IHP de secundaria superior ni una evaluación escolar."),
        ],
        "upper": [
            localized("Prepare for seminar by locating a short passage and forming a question that admits more than one defensible reading.",
                      "Prepárate para el seminario localizando un pasaje breve y formulando una pregunta que admita más de una lectura defendible."),
            localized("State a tentative interpretation, listen to a counterreading and ask which supplied words discriminate between them. Do not invent a classmate's views.",
                      "Expón una interpretación provisional, escucha otra y pregunta qué palabras aportadas ayudan a distinguirlas. No inventes opiniones de compañeros."),
            localized("Rehearse a brief panel contribution: a question, a text-grounded position and a remaining difficulty. Connect history or art only when the relevant source is supplied. Do not mark a school panel or symposium complete.",
                      "Ensaya una intervención breve para un panel: pregunta, postura apoyada en el texto y dificultad pendiente. Relaciona historia o arte solo con la fuente pertinente disponible. No marques como completado un panel o simposio escolar."),
        ],
    },
    "memoria_press": [
        localized("Grammar-stage preparation: identify the speaker, clarify one word in context and narrate the supplied passage. Use the learner's own words, not the study guide's answers.",
                  "Preparación de la etapa gramatical: identifica la voz, aclara una palabra en contexto y narra el pasaje. Usa palabras propias, no las respuestas de la guía."),
        localized("Logic-stage preparation: ask how a claim is supported and what a counterreading would need. Guide discussion with the supplied passage; do not reproduce or solve a proprietary guide question.",
                  "Preparación de la etapa lógica: pregunta cómo se apoya una afirmación y qué necesitaría otra lectura. Guía el diálogo con el pasaje; no reproduzcas ni resuelvas una pregunta de la guía editorial."),
        localized("Rhetoric-stage preparation: help the learner plan an evidence-based spoken or written interpretation and consider an objection. The learner composes it; do not write a thesis or finished essay for them.",
                  "Preparación de la etapa retórica: ayuda a planear una interpretación oral o escrita apoyada en el texto y a considerar una objeción. Quien aprende la redacta; no escribas su tesis ni su ensayo."),
    ],
}
