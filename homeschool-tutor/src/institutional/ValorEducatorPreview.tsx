import { useState } from 'react'
import { BookOpen, ClipboardList, Feather, Library, ShieldCheck } from 'lucide-react'
import './ValorEducatorPreview.css'

type View = 'study' | 'lessons' | 'evidence'
const lessons = [
  { subject: 'Literature', title: 'The art of a good question', text: 'Distinguish motive from action in an approved Odyssey passage.' },
  { subject: 'History', title: 'Citizenship and the ancient polis', text: 'Compare civic duties in two Greek city-states.' },
  { subject: 'Composition', title: 'Reasoning from evidence', text: 'Support a written claim with a specific passage.' },
]
const observations = [
  { skill: 'Explain a passage in your own words', help: 'Independent', source: 'Narration · October 12' },
  { skill: 'Compare two historical perspectives', help: 'After a nudge', source: 'Seminar · October 11' },
  { skill: 'Support a claim with textual evidence', help: 'Worked through together', source: 'Composition · October 10' },
]

/** Fictional design-preview data. Not authenticated, persistent, or connected to learners. */
export default function ValorEducatorPreview() {
  const [view, setView] = useState<View>('study')
  const [draft, setDraft] = useState<number | null>(null)
  return <div className="valor-shell">
    <a className="valor-skip" href="#valor-main">Skip to content</a>
    <aside className="valor-rail">
      <div className="valor-seal">✧</div>
      <div className="valor-brand">BEDE <span>EDUCATOR</span></div>
      <p className="valor-caption">THE ACADEMY</p>
      <div className="valor-campus">Founding campus <small>Illustrative workspace</small></div>
      <nav aria-label="Educator sections">
        <button aria-current={view === 'study' ? 'page' : undefined} onClick={() => setView('study')}><Library size={17}/> The study</button>
        <button aria-current={view === 'lessons' ? 'page' : undefined} onClick={() => setView('lessons')}><BookOpen size={17}/> Lesson companion</button>
        <button aria-current={view === 'evidence' ? 'page' : undefined} onClick={() => setView('evidence')}><ClipboardList size={17}/> Learning evidence</button>
      </nav>
      <p className="valor-disclaimer"><ShieldCheck size={16}/> Design review only. No student records or live AI are connected.</p>
    </aside>
    <main id="valor-main" className="valor-main">
      <header className="valor-header"><span>AGNUS DEI TECHNOLOGIES / BEDE FOR SCHOOLS</span><strong>DESIGN PREVIEW</strong></header>
      <div className="valor-inner">
        <div className="valor-eyebrow">✳ &nbsp; THE EDUCATOR'S DESK · AUTUMN TERM</div>
        <h1>{view === 'study' ? <>The art of <em>attentive teaching.</em></> : view === 'lessons' ? <>Lessons formed by <em>good questions.</em></> : <>An honest account of <em>learning.</em></>}</h1>
        <p className="valor-lede">{view === 'study' ? 'A quiet place to prepare, observe, and guide. The educator remains the author of each lesson.' : view === 'lessons' ? 'Begin with the book. Invite the student to think. Approve what is taught.' : 'See the work completed and the help it took, not a ranking of children.'}</p>
        <div className="valor-divider"><span>AD DISCENDUM · AD FLORENDUM</span></div>
        {view === 'study' && <div className="valor-grid">
          <section className="valor-card valor-feature"><span className="valor-overline">TODAY'S STUDY</span><Feather className="valor-feather" size={22}/><h2>What is worthy of our attention?</h2><p>Review the next lesson with its approved source. Bede can suggest questions, but instructional decisions remain with the teacher.</p><blockquote>“Education is an atmosphere, a discipline, a life.”</blockquote><button className="valor-action" onClick={() => setView('lessons')}>Open lesson companion →</button></section>
          <section className="valor-card"><span className="valor-overline">EVIDENCE, NOT RANKINGS</span><h2>Learning observed</h2><p>Three sample observations, each tied to work and the assistance provided.</p><button className="valor-secondary" onClick={() => setView('evidence')}>Read evidence ledger →</button></section>
        </div>}
        {view === 'lessons' && <section className="valor-card"><span className="valor-overline">FROM THE APPROVED CURRICULUM</span><h2>Lesson companion</h2><p className="valor-muted">Illustrative lesson cards. Draft creation below is a local UI example and does not call an AI service.</p>
          <div className="valor-list">{lessons.map((lesson,i) => <article className="valor-item" key={lesson.title}><span className="valor-overline">{lesson.subject}</span><h3>{lesson.title}</h3><p>{lesson.text}</p><button className="valor-secondary" onClick={() => setDraft(draft === i ? null : i)} aria-expanded={draft === i}> {draft === i ? 'Close example' : 'View sample question'} →</button>{draft === i && <div className="valor-draft"><strong>Example for teacher review</strong><p>What in the assigned reading led you to that conclusion? Point to a sentence that supports your answer.</p><small>Illustration only · Not assigned or sent to learners</small></div>}</article>)}</div>
        </section>}
        {view === 'evidence' && <section className="valor-card"><span className="valor-overline">THE WORK LEDGER</span><h2>What was demonstrated</h2><p>Individual, dated observations preserve context. No student totals, rankings, or moral scores.</p><div className="valor-list">{observations.map(o => <article className="valor-item" key={o.skill}><span className="valor-overline">{o.source}</span><h3>{o.skill}</h3><p>Assistance: <strong>{o.help}</strong></p></article>)}</div></section>}
        <footer className="valor-footer">BEDE · A CLASSICAL LEARNING COMPANION <span>PROTOTYPE / FICTIONAL DATA</span></footer>
      </div>
    </main>
  </div>
}
