import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, RotateCcw, SkipForward } from "lucide-react";
import { overviewSegments } from "./overview-script";
import { LessonVideo } from "./LessonVideo";
import { FullscreenVideoControls, useFullscreenVideo } from "./FullscreenVideo";
import "./tour.css";

type TourPath = "parent" | "educator";
type ParentResponse = "choice" | "evidence" | "answer";
type TeacherDecision = "approved" | "edited" | "rejected";

const parentSteps = [
  "Choose a starting point",
  "A question worth considering",
  "Listen to the learner",
  "Your review",
  "Return to the work",
];
const educatorSteps = [
  "Review synthetic evidence",
  "Consider the next instruction",
  "Confirm your review",
  "Review the record",
];
const feedback: Record<ParentResponse, { title: string; text: string }> = {
  choice: {
    title: "A useful beginning",
    text: "A reasoned choice gives the learner something to explain. Invite a line from the story that supports it; the text remains the source of the discussion.",
  },
  evidence: {
    title: "Look back at the words",
    text: "A detail from the fable can help clarify a reason. This scripted response models returning to the text rather than treating an answer as a score.",
  },
  answer: {
    title: "Keep the learner thinking",
    text: "A direct answer can close the question too soon. You might ask what in the story led the learner there, then let them put the reasoning into their own words.",
  },
};

function asset(name: string) {
  return `${import.meta.env.BASE_URL.replace(/\/$/, "")}/bede-tour/${name}`;
}

function formatTime(seconds: number) {
  const wholeSeconds = Math.floor(seconds);
  const minutes = Math.floor(wholeSeconds / 60);
  return `${minutes}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

function OverviewVideo() {
  const [unavailable, setUnavailable] = useState(false);
  const fullscreen = useFullscreenVideo();
  const transcript = useMemo(() => {
    let start = 0;
    return overviewSegments.map((segment) => {
      const item = { ...segment, start, end: start + segment.duration };
      start = item.end;
      return item;
    });
  }, []);
  return (
    <section className="tour-video-card" aria-labelledby="overview-title" data-testid="section-overview-video">
      <div className="tour-video-heading">
        <div>
          <h2 id="overview-title">Explore the two paths</h2>
          <p>{formatTime(overviewSegments.reduce((total, segment) => total + segment.duration, 0))} · English captions</p>
        </div>
        <img src={asset("bede-portrait.webp")} alt="Illustrated portrait of Bede" />
      </div>
      <video
        ref={fullscreen.videoRef}
        onPlay={fullscreen.onPlay}
        controls
        preload="metadata"
        onError={() => setUnavailable(true)}
        onLoadedMetadata={() => setUnavailable(false)}
        poster={asset("overview-poster.jpg")}
        aria-label="Short Bede guided-tour overview"
        data-testid="video-short-overview"
      >
        <source src={asset("generated/overview.mp4")} type="video/mp4" />
        <source src={asset("generated/overview.webm")} type="video/webm" onError={() => setUnavailable(true)} />
        <track
          kind="captions"
          src={asset("overview.vtt")}
          srcLang="en"
          label="English"
          default
        />
        Your browser does not support embedded video. Read the overview transcript below.
      </video>
      <FullscreenVideoControls title="the short overview" onClick={fullscreen.playFullscreen} message={fullscreen.message} />
      {unavailable && <p className="tour-note" role="status">Video playback is unavailable. <a href={asset("generated/overview-captioned.mp4")} download>Download the captioned overview</a> or read the complete transcript below.</p>}
      <details className="tour-disclosure">
        <summary>Read the overview transcript</summary>
        <div className="tour-transcript" data-testid="text-overview-transcript">
          {transcript.map((segment, index) => (
            <p key={`${segment.start}-${index}`}>
              <time>{formatTime(segment.start)}</time> {segment.text}
            </p>
          ))}
        </div>
      </details>
    </section>
  );
}

function Entry({ onStart }: { onStart: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const hash = window.location.hash;
    if (hash === "#overview-title" || hash === "#lesson-title") {
      const target = hash === "#lesson-title"
        ? document.querySelector<HTMLElement>("[data-testid=section-recorded-lesson] video")
        : document.querySelector<HTMLVideoElement>("[data-testid=video-short-overview]");
      target?.scrollIntoView({ block: "center" });
      target?.focus();
    } else headingRef.current?.focus();
  }, []);
  return (
    <>
      <header className="tour-topbar">
        <a className="tour-brand" href="#tour-home" aria-label="Bede guided tour home">
          <img src={asset("bede-icon.webp")} alt="" />
          <span>BEDE</span>
        </a>
        <span className="tour-topbar-note">Human-led classical learning</span>
      </header>
      <main className="tour-shell tour-entry-shell">
        <div className="tour-entry">
          <section className="tour-entry-copy" id="tour-home">
            <p className="tour-eyebrow">A classical learning companion</p>
            <h1 tabIndex={-1} ref={headingRef}>Begin with a book. Keep the adult at the center.</h1>
            <p className="tour-lead">
              See how Bede can support thoughtful reading and planning—without taking the place of a parent or teacher.
            </p>
            <div className="tour-actions" aria-label="Choose how to explore">
              <button className="tour-button" onClick={onStart} data-testid="button-take-guided-tour">
                Take a guided tour <ArrowRight size={17} aria-hidden="true" />
              </button>
              <a className="tour-button secondary" href="#overview-title" data-testid="link-watch-short-overview">
                Watch the short overview
              </a>
              <a className="tour-button secondary" href="#lesson-title" data-testid="link-watch-recorded-lesson">
                Watch Bede in action
              </a>
            </div>
            <div className="tour-values">
              <span><i className="tour-dot" /> You choose</span>
              <span><i className="tour-dot" /> Bede supports</span>
              <span><i className="tour-dot" /> You review</span>
            </div>
          </section>
          <div className="tour-entry-video">
            <OverviewVideo />
            <LessonVideo publicDemoHref="/bede/" />
          </div>
        </div>
        <TourFooter />
      </main>
    </>
  );
}

function TourFooter() {
  return (
    <footer className="tour-footer">
      <div className="tour-links" aria-label="Other Bede resources">
        <a href="https://agnusdei.ai/bede/" target="_blank" rel="noreferrer" data-testid="link-public-demo">Public Bede demo</a>
        <a href="https://www.youtube.com/watch?v=M7OV1-RrK2M" target="_blank" rel="noreferrer" data-testid="link-meet-bede">Meet Bede on YouTube</a>
        <a href="mailto:info@agnusdei.ai?subject=Bede%20onboarding%20request" data-testid="link-onboarding">Onboarding request</a>
      </div>
      <p>Demo and onboarding are separate from this walkthrough.</p>
    </footer>
  );
}

function PathPicker({ onChoose, onBack }: { onChoose: (path: TourPath) => void; onBack: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headingRef.current?.focus(); }, []);
  return (
    <>
      <header className="tour-topbar">
        <a className="tour-brand" href="#choose-path" aria-label="Bede guided tour"><img src={asset("bede-icon.webp")} alt="" /><span>BEDE</span></a>
        <span className="tour-topbar-note">Choose one of two guided paths</span>
      </header>
      <main className="tour-shell tour-path-select tour-transition" id="choose-path">
        <p className="tour-eyebrow">Two adult-led paths</p>
        <h1 tabIndex={-1} ref={headingRef} data-testid="heading-choose-tour-path">Who is this walkthrough for?</h1>
        <p className="tour-lead">Both paths use fictional examples. Choose the setting that best matches your questions.</p>
        <div className="tour-path-grid">
          <button className="tour-path-choice" onClick={() => onChoose("parent")} data-testid="button-choose-homeschool-parent">
            <strong>Homeschooling parent</strong>
            <span>For moms and dads alike: choose a book and goal, consider a question, and review sample learner work together.</span>
            <small>5 steps · family learning</small>
          </button>
          <button className="tour-path-choice" onClick={() => onChoose("educator")} data-testid="button-choose-classical-educator">
            <strong>Classical educator</strong>
            <span>Teacher-only, synthetic-only planning: separate illustrative evidence from observation, then make the instructional decision.</span>
            <small>3 steps · school pilot simulation</small>
          </button>
        </div>
        <div className="tour-step-actions"><button className="tour-button subtle" onClick={onBack} data-testid="button-back-to-tour-entry"><ArrowLeft size={16} /> Back</button></div>
        <TourFooter />
      </main>
    </>
  );
}

function TourHeader({
  path, step, steps, onSwitch,
}: { path: TourPath; step: number; steps: string[]; onSwitch: () => void }) {
  return (
    <>
      <header className="tour-topbar">
        <a className="tour-brand" href="#tour-step" aria-label="Bede guided tour"><img src={asset("bede-icon.webp")} alt="" /><span>BEDE</span></a>
        <span className="tour-topbar-note">{path === "parent" ? "Homeschooling parent" : "Classical educator"} · simulated</span>
      </header>
      <div className="tour-step-nav" aria-label="Tour progress">
        {steps.map((label, index) => (
          <button type="button" key={label} aria-current={step === index ? "step" : undefined} disabled data-testid={`status-tour-step-${index + 1}`}>
            {index + 1}. {label}
          </button>
        ))}
      </div>
      <div className="tour-progress" role="progressbar" aria-label="Tour progress" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={step + 1}>
        <span style={{ width: `${((step + 1) / steps.length) * 100}%` }} />
      </div>
      <button className="tour-switch-link" type="button" onClick={onSwitch} data-testid="button-switch-tour-path">Switch path</button>
    </>
  );
}

function ParentStep({
  step, learner, setLearner, book, setBook, goal, setGoal, response, setResponse,
  parentNote, setParentNote, workFormat, setWorkFormat, practical, setPractical,
}: {
  step: number; learner: string; setLearner: (v: string) => void; book: string; setBook: (v: string) => void;
  goal: string; setGoal: (v: string) => void; response: ParentResponse | null; setResponse: (v: ParentResponse) => void;
  parentNote: string; setParentNote: (v: string) => void; workFormat: string; setWorkFormat: (v: string) => void;
  practical: string; setPractical: (v: string) => void;
}) {
  const selectedFeedback = response ? feedback[response] : null;
  if (step === 0) return (
    <>
      <p className="tour-eyebrow">Step 1 · the adult sets the direction</p>
      <h1 tabIndex={-1} data-tour-heading>Choose a fictional learner, book, and goal.</h1>
      <p className="tour-lead">Use only the prepared examples. Do not enter a real child’s name or personal information.</p>
      <div className="tour-field-grid">
        <label className="tour-field">Fictional learner
          <select value={learner} onChange={(e) => setLearner(e.target.value)} data-testid="select-fictional-learner">
            <option value="Mara · Grade 4">Mara · Grade 4</option>
            <option value="Elias · Grade 5">Elias · Grade 5</option>
            <option value="Clara · Grade 3">Clara · Grade 3</option>
          </select><small>Invented example; no learner record is created.</small>
        </label>
        <label className="tour-field">Book
          <select value={book} onChange={(e) => setBook(e.target.value)} data-testid="select-sample-book">
            <option value="Aesop’s Fables · “The Lion and the Mouse”">Aesop’s Fables · “The Lion and the Mouse” (fixed example)</option>
            <option value="Charlotte’s Web">Charlotte’s Web (planning choice; exercise remains the Aesop fable)</option>
            <option value="The Wind in the Willows">The Wind in the Willows (planning choice; exercise remains the Aesop fable)</option>
          </select>
        </label>
        <label className="tour-field full">A practical learning goal
          <select value={goal} onChange={(e) => setGoal(e.target.value)} data-testid="select-learning-goal">
            <option>Explain a character’s choice using a detail from the text</option>
            <option>Retell the passage clearly in the learner’s own words</option>
            <option>Write a brief response with one supporting quotation</option>
          </select>
        </label>
      </div>
      <p className="tour-note"><strong>Fixed sample exercise:</strong> The later scripted question and learner work always use “The Lion and the Mouse.” Choosing another book here is a planning choice only; the example does not switch texts.</p>
      <p className="tour-note"><strong>You choose.</strong> Parent direction begins with a real text, an attainable purpose, and your knowledge of the learner.</p>
    </>
  );
  if (step === 1) return (
    <>
      <p className="tour-eyebrow">Step 2 · guided reasoning</p>
      <h1 tabIndex={-1} data-tour-heading>What does the Lion learn from the Mouse?</h1>
      <p className="tour-lead">A representative Socratic question, followed by a choice of scripted learner response. Nothing is generated live.</p>
      <blockquote className="tour-quote">“Why might the Lion’s decision to spare the Mouse matter later in the story?”</blockquote>
      <span className="tour-scripted-label">Select a fictional response</span>
      <div className="tour-choice-list" role="radiogroup" aria-label="Choose a sample learner response">
        <label className="tour-choice"><input type="radio" name="parent-response" checked={response === "choice"} onChange={() => setResponse("choice")} data-testid="radio-response-reasoning" /><span><strong>“The Mouse could help him later.”</strong> A prediction tied to the story’s events.</span></label>
        <label className="tour-choice"><input type="radio" name="parent-response" checked={response === "evidence"} onChange={() => setResponse("evidence")} data-testid="radio-response-text-detail" /><span><strong>“He let it go, even though it was small.”</strong> A detail worth connecting to the outcome.</span></label>
        <label className="tour-choice"><input type="radio" name="parent-response" checked={response === "answer"} onChange={() => setResponse("answer")} data-testid="radio-response-short-answer" /><span><strong>“Because he was kind.”</strong> A starting thought that invites a reason from the text.</span></label>
      </div>
      {selectedFeedback && <div className="tour-feedback" role="status" aria-live="polite" data-testid="status-scripted-feedback"><strong>{selectedFeedback.title}</strong>{selectedFeedback.text}<br /><small>Illustrative scripted feedback only · no inference or assessment</small></div>}
    </>
  );
  if (step === 2) return (
    <>
      <p className="tour-eyebrow">Step 3 · sample learner work</p>
      <h1 tabIndex={-1} data-tour-heading>Listen before you evaluate.</h1>
      <p className="tour-lead">A fictional narration might sound like this. Use the switch to compare a short written response.</p>
      <div className="tour-quote" aria-live="polite" data-testid="text-sample-learner-work">
        {workFormat === "writing"
          ? "The Lion let the Mouse go. Later, the Mouse helped free him from the net. The story shows that even a small friend can help."
          : "The Lion thought the Mouse was too small to help. But then the Lion got caught, and the Mouse chewed the net. The little animal helped the big one."}
      </div>
      <div className="tour-action-group">
        <button type="button" className={`tour-button ${workFormat !== "writing" ? "" : "secondary"}`} onClick={() => setWorkFormat("narration")} aria-pressed={workFormat !== "writing"} data-testid="button-show-sample-narration">Sample narration</button>
        <button type="button" className={`tour-button ${workFormat === "writing" ? "" : "secondary"}`} onClick={() => setWorkFormat("writing")} aria-pressed={workFormat === "writing"} data-testid="button-show-sample-writing">Sample writing</button>
      </div>
      <p className="tour-note"><strong>Sample only.</strong> This is invented learner work. It is not a real child’s response, a learning outcome, or a model to copy.</p>
    </>
  );
  if (step === 3) return (
    <>
      <p className="tour-eyebrow">Step 4 · parent review</p>
      <h1 tabIndex={-1} data-tour-heading>You know what needs another question.</h1>
      <p className="tour-lead">Review the fictional learner’s work in light of your chosen goal. Add a note if you like; it stays on this screen and is not saved.</p>
      <div className="tour-review-card">
        <strong>{learner} · selected planning book: {book}</strong>
        <dl><dt>Your goal</dt><dd>{goal}</dd><dt>Fixed sample work · “The Lion and the Mouse”</dt><dd>{workFormat === "writing" ? "A brief written response connecting the Lion’s release of the Mouse to the later rescue." : "An oral retelling that notices the reversal between the large Lion and small Mouse."}</dd></dl>
      </div>
      <p className="tour-note"><strong>For clarity:</strong> the selected planning book does not change this scripted Aesop exercise.</p>
      <label className="tour-field full" style={{ marginTop: "1rem" }}>Your review note <small>Optional, fictional, and not stored beyond this tour state.</small>
        <textarea value={parentNote} onChange={(e) => setParentNote(e.target.value)} maxLength={320} placeholder="For example: Ask which detail shows the Mouse can help." data-testid="textarea-parent-review" />
      </label>
      <p className="tour-note"><strong>Your judgment leads.</strong> Bede may support a conversation; you decide whether the response meets your purpose.</p>
    </>
  );
  return (
    <>
      <p className="tour-eyebrow">Step 5 · screen to real work</p>
      <h1 tabIndex={-1} data-tour-heading>Close the screen. Carry the question forward.</h1>
      <p className="tour-lead">Choose one practical next move for the fictional learner. This is a prompt for your judgment, not an assigned lesson.</p>
      <div className="tour-choice-list" role="radiogroup" aria-label="Choose a practical application">
        <label className="tour-choice"><input type="radio" name="application" checked={practical === "book"} onChange={() => setPractical("book")} data-testid="radio-practical-book" /><span><strong>Return to the book</strong> Find the line that gives the Mouse a chance to help.</span></label>
        <label className="tour-choice"><input type="radio" name="application" checked={practical === "handwriting"} onChange={() => setPractical("handwriting")} data-testid="radio-practical-handwriting" /><span><strong>Write by hand</strong> Put the character’s decision and its consequence into two sentences.</span></label>
        <label className="tour-choice"><input type="radio" name="application" checked={practical === "conversation"} onChange={() => setPractical("conversation")} data-testid="radio-practical-application" /><span><strong>Make a practical connection</strong> Talk about a time a small act of help made a difference.</span></label>
      </div>
      <p className="tour-feedback" role="status" data-testid="status-practical-application"><strong>Your chosen direction:</strong> {practical === "book" ? "return to the text and find the evidence together." : practical === "handwriting" ? "put the thought into the learner’s own handwriting." : "connect the story’s idea to a practical conversation."}</p>
      <div className="tour-review-card"><strong>A simple rhythm</strong><p>Choose the text and goal → Bede supports a question → you review → learning returns to reading, writing, and life.</p></div>
    </>
  );
}

function EducatorStep({
  step, observation, setObservation, proposed, setProposed, decision, setDecision,
  reviewConfirmed, setReviewConfirmed,
}: {
  step: number; observation: string; setObservation: (v: string) => void; proposed: string;
  setProposed: (v: string) => void; decision: TeacherDecision | null; setDecision: (v: TeacherDecision | null) => void;
  reviewConfirmed: boolean; setReviewConfirmed: (v: boolean) => void;
}) {
  if (step === 0) return (
    <>
      <p className="tour-eyebrow">Step 1 · teacher-only review</p>
      <h1 tabIndex={-1} data-tour-heading>Keep evidence and observation distinct.</h1>
      <p className="tour-lead">A fictional campus, learner, and sample record. No official assessment item or real student information appears here.</p>
      <div className="tour-review-card" data-testid="card-synthetic-evidence">
        <span className="tour-scripted-label">Synthetic illustrative evidence</span>
        <strong>Fictional learner · Grade 5</strong>
        <dl><dt>Illustrative measure</dt><dd>Oral reading sample · 74 words correct per minute</dd><dt>Record status</dt><dd>Sample value only; not a benchmark, diagnosis, or official result.</dd></dl>
      </div>
      <div className="tour-review-card" style={{ marginTop: ".8rem" }} data-testid="card-teacher-observation">
        <span className="tour-scripted-label">Teacher observation · separately recorded</span>
        <p>During a familiar passage, the fictional learner paused at longer words and retold the central events after a prompt.</p>
        <label className="tour-field">Your teacher observation <small>Optional example. Do not enter real student data.</small>
          <textarea value={observation} onChange={(e) => { setObservation(e.target.value); setReviewConfirmed(false); }} maxLength={320} placeholder="What did you notice in this synthetic example?" data-testid="textarea-teacher-observation" />
        </label>
      </div>
      <p className="tour-note"><strong>School pilot scope:</strong> teacher-only and synthetic-only. No direct student instruction or delivery.</p>
    </>
  );
  if (step === 1) return (
    <>
      <p className="tour-eyebrow">Step 2 · teacher judgment</p>
      <h1 tabIndex={-1} data-tour-heading>Decide what happens next.</h1>
      <p className="tour-lead">Review this proposed next instruction. Edit the sample wording, approve it, or reject it. Your decision is illustrative and does not send a lesson.</p>
      <label className="tour-field full">Proposed next instruction
        <textarea value={proposed} onChange={(e) => { setProposed(e.target.value); setReviewConfirmed(false); setDecision(null); }} maxLength={800} data-testid="textarea-proposed-instruction" />
      </label>
      <div className="tour-decision-row" aria-label="Teacher decision">
        <button className="tour-button" type="button" disabled={!proposed.trim()} aria-pressed={decision === "approved"} onClick={() => { setDecision("approved"); setReviewConfirmed(false); }} data-testid="button-approve-instruction">Approve as written</button>
        <button className="tour-button secondary" type="button" disabled={!proposed.trim()} aria-pressed={decision === "edited"} onClick={() => { setDecision("edited"); setReviewConfirmed(false); }} data-testid="button-save-edited-instruction">Save edited wording</button>
        <button className="tour-button subtle" type="button" aria-pressed={decision === "rejected"} onClick={() => { setDecision("rejected"); setReviewConfirmed(false); }} data-testid="button-reject-instruction">Reject proposal</button>
      </div>
      <p className="tour-feedback" role="status" aria-live="polite" data-testid="status-teacher-decision">
        {decision === "approved" && "Approved as written. Teacher judgment remains responsible for any next action."}
        {decision === "edited" && "Edited wording recorded for this local walkthrough only."}
        {decision === "rejected" && "Proposal rejected. No instructional step is assigned."}
        {!decision && "No decision yet. Choose approve, edit, or reject before reviewing the record."}
      </p>
      <p className="tour-note"><strong>No direct instruction or delivery.</strong> This school-pilot illustration is for teacher review only; it does not message or teach a student.</p>
    </>
  );
  if (step === 2) return (
    <>
      <p className="tour-eyebrow">Step 3 · deliberate review</p>
      <h1 tabIndex={-1} data-tour-heading>Check the evidence, observation, and decision.</h1>
      <p className="tour-lead">Before viewing the local review record, take a moment to confirm that this synthetic example reflects the choice you intended.</p>
      <div className="tour-review-card">
        <dl>
          <dt>Illustrative evidence</dt><dd>Fictional oral reading sample · 74 words correct per minute</dd>
          <dt>Separate teacher observation</dt><dd>{observation.trim() || "No additional note entered."}</dd>
          <dt>Your decision</dt><dd>{decision === "approved" ? "Approve as written" : decision === "edited" ? "Save edited wording" : decision === "rejected" ? "Reject proposal" : "No decision yet"}</dd>
          <dt>Current wording</dt><dd>{decision === "rejected" ? "No instructional step retained." : proposed.trim() || "No proposed wording entered."}</dd>
        </dl>
      </div>
      <label className="tour-choice" style={{ marginTop: "1rem" }}>
        <input type="checkbox" checked={reviewConfirmed} onChange={(e) => setReviewConfirmed(e.target.checked)} data-testid="checkbox-confirm-teacher-review" />
        <span><strong>I have reviewed this fictional example.</strong> This confirms only my local walkthrough review; it does not approve delivery to a student.</span>
      </label>
      <p className="tour-note"><strong>Human judgment stays visible.</strong> Review is separate from the evidence and from any instruction delivered in a real classroom.</p>
    </>
  );
  return (
    <>
      <p className="tour-eyebrow">Step 4 · review record</p>
      <h1 tabIndex={-1} data-tour-heading>Keep a clear record of the decision.</h1>
      <p className="tour-lead">The record reflects only what the teacher reviewed and chose in this synthetic example.</p>
      <div className="tour-review-card" data-testid="card-teacher-review-record">
        <span className="tour-scripted-label">Local sample record · not saved</span>
        <dl>
          <dt>Evidence</dt><dd>Fictional oral reading sample · 74 words correct per minute</dd>
          <dt>Teacher observation</dt><dd>{observation.trim() || "No additional note entered."}</dd>
          <dt>Teacher decision</dt><dd>{decision === "approved" ? "Approved as written" : decision === "edited" ? "Saved edited wording" : decision === "rejected" ? "Rejected proposal" : "No decision recorded"}</dd>
          <dt>Reviewed instruction</dt><dd>{decision === "rejected" ? "No instruction retained; proposal rejected." : proposed.trim() || "No proposed instruction text."}</dd>
        </dl>
      </div>
      <p className="tour-note"><strong>Teacher remains accountable.</strong> No result is delivered to a learner, and nothing is persisted after leaving the local preview.</p>
    </>
  );
}

function Completion({
  path, skipped, onRestart, onSwitch,
}: { path: TourPath; skipped: boolean; onRestart: () => void; onSwitch: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => { headingRef.current?.focus(); }, []);
  const decisionLabel = path === "educator" ? "Your teacher decision is recorded only if you selected approve, edit, or reject." : "Your review is yours to make; this tour does not grade the sample work.";
  return (
    <main className="tour-shell tour-complete tour-transition">
      <p className="tour-eyebrow">{skipped ? "Walkthrough ended early" : "Walkthrough complete"}</p>
      <h1 tabIndex={-1} ref={headingRef} data-testid="heading-tour-complete">
        {skipped ? "This example is incomplete." : "The adult leads. The learning continues."}
      </h1>
      {skipped
        ? <p className="tour-lead">You chose to finish before all steps were reviewed. No missing response, review, or teacher decision has been filled in for you.</p>
        : <p className="tour-lead">{path === "parent" ? "You chose the book, question, and practical next move. Bede’s role is support; your judgment remains central." : "You reviewed synthetic evidence, separated teacher observation, and made the instructional decision. Nothing was sent to a learner."}</p>}
      <p className="tour-note"><strong>{path === "educator" ? "Teacher-only, synthetic-only." : "Fictional family example."}</strong> {decisionLabel} No live inference, account, or persistence.</p>
      <div className="tour-actions tour-complete-actions">
        <button className="tour-button" onClick={onRestart} data-testid="button-restart-tour"><RotateCcw size={16} /> Restart this path</button>
        <button className="tour-button secondary" onClick={onSwitch} data-testid="button-switch-path-complete">Switch path</button>
      </div>
      <TourFooter />
    </main>
  );
}

export function Tour() {
  const [screen, setScreen] = useState<"entry" | "choose" | "tour" | "complete">("entry");
  const [path, setPath] = useState<TourPath>("parent");
  const [step, setStep] = useState(0);
  const [skipped, setSkipped] = useState(false);
  const [learner, setLearner] = useState("Mara · Grade 4");
  const [book, setBook] = useState("Aesop’s Fables · “The Lion and the Mouse”");
  const [goal, setGoal] = useState("Explain a character’s choice using a detail from the text");
  const [response, setResponse] = useState<ParentResponse | null>(null);
  const [parentNote, setParentNote] = useState("");
  const [workFormat, setWorkFormat] = useState("narration");
  const [practical, setPractical] = useState("book");
  const [observation, setObservation] = useState("");
  const [proposed, setProposed] = useState("Practice oral reading and narration with an approved classroom text. Observe fluency and comprehension during teacher-led instruction.");
  const [decision, setDecision] = useState<TeacherDecision | null>(null);
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const steps = path === "parent" ? parentSteps : educatorSteps;

  useEffect(() => {
    const previousTitle = document.title;
    const description = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    const previousDescription = description?.content;
    const newDescription = description ?? document.createElement("meta");
    document.title = "Bede Guided Tour | Human-led classical learning";
    newDescription.name = "description";
    newDescription.content = "Explore a local, simulated Bede tour for homeschooling parents and classical educators. Adults lead; fictional examples only.";
    if (!description) document.head.appendChild(newDescription);
    return () => {
      document.title = previousTitle;
      if (previousDescription !== undefined) newDescription.content = previousDescription;
      else newDescription.remove();
    };
  }, []);

  const resetPath = (nextPath: TourPath) => {
    setPath(nextPath);
    setStep(0);
    setSkipped(false);
    setLearner("Mara · Grade 4");
    setBook("Aesop’s Fables · “The Lion and the Mouse”");
    setGoal("Explain a character’s choice using a detail from the text");
    setResponse(null);
    setParentNote("");
    setWorkFormat("narration");
    setPractical("book");
    setObservation("");
    setProposed("Practice oral reading and narration with an approved classroom text. Observe fluency and comprehension during teacher-led instruction.");
    setDecision(null);
    setReviewConfirmed(false);
    setScreen("tour");
  };
  const advance = () => {
    if (step >= steps.length - 1) setScreen("complete");
    else setStep((current) => Math.min(current + 1, steps.length - 1));
  };
  const back = () => setStep((current) => Math.max(current - 1, 0));
  const finishSkipped = () => { setSkipped(true); setScreen("complete"); };

  useEffect(() => {
    if (screen === "tour") {
      const timer = window.setTimeout(() => {
        const heading = document.querySelector<HTMLElement>("[data-tour-heading]");
        heading?.focus();
      }, 0);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [screen, step, path]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (screen !== "tour" || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, button, a, [contenteditable=true]")) return;
      if (event.key === "ArrowRight"
        && !(path === "parent" && step === 1 && !response)
        && !(path === "educator" && step === 1 && !decision)
        && !(path === "educator" && step === 2 && !reviewConfirmed)) {
        event.preventDefault();
        advance();
      } else if (event.key === "ArrowLeft" && step > 0) {
        event.preventDefault();
        back();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [screen, path, step, decision, response, reviewConfirmed, steps.length]);

  if (screen === "entry") return <div className="bede-tour"><Entry onStart={() => setScreen("choose")} /></div>;
  if (screen === "choose") return <div className="bede-tour"><PathPicker onChoose={resetPath} onBack={() => setScreen("entry")} /></div>;
  if (screen === "complete") return (
    <div className="bede-tour">
      <header className="tour-topbar"><a className="tour-brand" href="#tour-end"><img src={asset("bede-icon.webp")} alt="" /><span>BEDE</span></a><span className="tour-topbar-note">Local walkthrough · simulated</span></header>
      <Completion path={path} skipped={skipped} onRestart={() => resetPath(path)} onSwitch={() => setScreen("choose")} />
    </div>
  );

  const isParentResponseRequired = path === "parent" && step === 1 && !response;
  const isEducatorDecisionRequired = path === "educator" && step === 1 && !decision;
  const isEducatorConfirmationRequired = path === "educator" && step === 2 && !reviewConfirmed;
  return (
    <div className="bede-tour">
      <TourHeader path={path} step={step} steps={steps} onSwitch={() => setScreen("choose")} />
      <main className="tour-shell tour-workspace tour-transition" id="tour-step">
        <section className="tour-main-panel" aria-label={`${path === "parent" ? "Homeschooling parent" : "Classical educator"} tour step`}>
          <div className="tour-step-head">
            <div>
              {path === "parent"
                ? <ParentStep step={step} learner={learner} setLearner={setLearner} book={book} setBook={setBook} goal={goal} setGoal={setGoal} response={response} setResponse={setResponse} parentNote={parentNote} setParentNote={setParentNote} workFormat={workFormat} setWorkFormat={setWorkFormat} practical={practical} setPractical={setPractical} />
                : <EducatorStep step={step} observation={observation} setObservation={setObservation} proposed={proposed} setProposed={setProposed} decision={decision} setDecision={setDecision} reviewConfirmed={reviewConfirmed} setReviewConfirmed={setReviewConfirmed} />}
            </div>
            <span className="tour-step-number">Step {step + 1} of {steps.length}</span>
          </div>
          <div className="tour-step-actions">
            <button className="tour-button subtle" onClick={back} disabled={step === 0} data-testid="button-tour-back"><ArrowLeft size={16} /> Back</button>
            <div className="tour-action-group">
              <button className="tour-button subtle" onClick={finishSkipped} data-testid="button-tour-skip"><SkipForward size={16} /> Skip tour</button>
              <button className="tour-button" onClick={advance} disabled={isParentResponseRequired || isEducatorDecisionRequired || isEducatorConfirmationRequired} data-testid="button-tour-next">
                {step === steps.length - 1 ? "Finish tour" : "Continue"} <ArrowRight size={16} />
              </button>
            </div>
          </div>
        </section>
        <aside className="tour-side-panel">
          <img className="tour-side-mark" src={asset("bede-icon.webp")} alt="" />
          <p className="tour-eyebrow">{path === "parent" ? "Family learning" : "School pilot scope"}</p>
          <h2 className="tour-side-heading">{path === "parent" ? "You choose. Bede supports. You review." : "The teacher decides."}</h2>
          <p>{path === "parent" ? "Read closely, discuss thoughtfully, and return to the book or written work." : "Teacher-only, synthetic-only. No direct student tutoring or delivery."}</p>
          {path === "educator" && <p><strong>Decision:</strong> {decision ? decision[0].toUpperCase() + decision.slice(1) : "Not recorded"}</p>}
          <div className="tour-side-rule" />
          <p><span className="tour-kbd">←</span> Back <span className="tour-kbd">→</span> Continue</p>
          <button className="tour-button subtle" onClick={() => resetPath(path)} data-testid="button-tour-restart-inline"><RotateCcw size={15} /> Restart path</button>
          <p className="tour-note">Illustrative only. Nothing is saved or sent.</p>
        </aside>
      </main>
      <TourFooter />
    </div>
  );
}

export default Tour;
