import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { UserPlus, Users, ShieldCheck, ArrowLeft, Copy } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import {
  assignInstructorRoster, disableInstructor, fetchEducatorPilotMode, fetchInstructors,
  invitePasskeyInstructor, recoverPasskeyInstructor,
} from '../services/api'
import type { InstructorAccount, LocutoCapacity } from '../services/api'

export const ROSTER_GRADES = ['K', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'] as const
export type RosterGrade = typeof ROSTER_GRADES[number]
export interface RosterRow { id: number; name: string; grade: RosterGrade | ''; sex: '' | 'M' | 'F' }

const gradeStageFor = (grade: RosterGrade): SessionConfig['grade_stage'] => {
  const numeric = grade === 'K' ? 0 : Number(grade)
  return numeric <= 2 ? 'K-2' : numeric <= 5 ? '3-5' : '6-8'
}

/** Rows chosen on screen to the learner plans the API takes. Grade and sex are
 * selectors, so only a learner's name is ever typed. */
export function buildRoster(rows: RosterRow[]): SessionConfig[] {
  const filled = rows.filter((row) => row.name.trim() || row.grade)
  if (!filled.length || filled.length > 90) throw new Error('Enter between 1 and 90 learners')
  const names = new Set<string>()
  return filled.map((row, index) => {
    const student_name = row.name.trim()
    if (!student_name || student_name.length > 50 || !ROSTER_GRADES.includes(row.grade as RosterGrade)) {
      throw new Error(`Learner ${index + 1}: enter a name and choose a grade`)
    }
    if (names.has(student_name.toLowerCase())) throw new Error('Duplicate learner in roster')
    names.add(student_name.toLowerCase())
    const grade = row.grade as RosterGrade
    return {
      student_name,
      grade,
      grade_stage: gradeStageFor(grade),
      subjects: ['mathematics', 'living_books', 'language_arts'],
      ...(row.sex ? { sex: row.sex === 'M' ? 'male' as const : 'female' as const } : {}),
    }
  })
}

interface Handover { url: string; minutes: number; username: string; kind: 'invite' | 'recovery' }

export default function ClassroomSetup() {
  const navigate = useNavigate()
  const token = useSessionStore((s) => s.token)
  const [educators, setEducators] = useState<InstructorAccount[]>([])
  const [pilotMode, setPilotMode] = useState(false)
  const [username, setUsername] = useState('')
  const [institutionalEmail, setInstitutionalEmail] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [rosterRows, setRosterRows] = useState<RosterRow[]>([{ id: 1, name: '', grade: '', sex: '' }])
  const [capacity, setCapacity] = useState<LocutoCapacity | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  // A one-time enrollment link, shown only when this computer has no
  // outbound mail. Component state only: never localStorage/sessionStorage,
  // and cleared on the next invite, on Done, or when the page is left.
  const [handover, setHandover] = useState<Handover | null>(null)
  const [recoveryEmail, setRecoveryEmail] = useState('')
  const [copied, setCopied] = useState(false)

  const refresh = async () => {
    if (!token) return
    const rows = await fetchInstructors(token)
    setEducators(rows)
    setSelectedId((current) => current || rows[0]?.id || '')
  }

  useEffect(() => {
    if (!token) return
    let active = true
    fetchEducatorPilotMode().then(value => {
      if (active) setPilotMode(value.enabled)
    }).catch(() => { if (active) setPilotMode(false) })
    fetchInstructors(token).then((list) => {
      if (active) {
        setEducators(list)
        setSelectedId((current) => current || list[0]?.id || '')
      }
    }).catch(() => { if (active) setMessage('Could not load instructor accounts') })
    return () => { active = false }
  }, [token])

  const enroll = async () => {
    if (!token || busy) return
    setBusy(true)
    setMessage('')
    setHandover(null)
    setCopied(false)
    try {
      const result = await invitePasskeyInstructor(token, username, institutionalEmail)
      setUsername('')
      setInstitutionalEmail('')
      if (result.delivery === 'shown_to_admin' && result.enrollment_url) {
        setHandover({
          url: result.enrollment_url,
          minutes: result.expires_in_minutes ?? 10,
          username: result.username,
          kind: 'invite',
        })
      } else {
        setMessage(`Passkey invitation sent to the school mailbox for ${result.username}.`)
      }
      const rows = await fetchInstructors(token)
      setEducators(rows)
      setSelectedId(rows.find(e => e.username === result.username)?.id ?? rows[0]?.id ?? '')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not deliver passkey invitation')
    } finally {
      setBusy(false)
    }
  }

  const importRoster = async () => {
    if (!token || !selectedId || busy) return
    setBusy(true)
    setMessage('')
    try {
      const parsed = buildRoster(rosterRows)
      const result = await assignInstructorRoster(token, selectedId, parsed)
      setCapacity(result.messaging)
      setMessage(`${result.learner_count} authorized. ${result.new_learner_count} new learner plans created.`)
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not import roster')
    } finally {
      setBusy(false)
    }
  }

  const recover = async () => {
    if (!token || !selectedId || busy) return
    const teacher = educators.find(e => e.id === selectedId)
    setBusy(true)
    setMessage('')
    setHandover(null)
    setCopied(false)
    try {
      const result = await recoverPasskeyInstructor(token, selectedId, recoveryEmail)
      setRecoveryEmail('')
      if (result.delivery === 'shown_to_admin' && result.enrollment_url) {
        setHandover({
          url: result.enrollment_url,
          minutes: result.expires_in_minutes ?? 10,
          username: teacher?.username ?? '',
          kind: 'recovery',
        })
      } else {
        setMessage('Passkey recovery link sent to the school mailbox.')
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not issue a recovery link')
    } finally {
      setBusy(false)
    }
  }

  const handoverBox = handover && (
    <div role="alert" className="bg-amber-50 border border-amber-300 rounded-xl p-3 text-sm space-y-2">
      <p>
        Email isn't set up on this computer. Give this link to the teacher in person.
        It works once and expires in {handover.minutes} minutes.
      </p>
      <p className="text-xs text-gray-600">
        {handover.kind === 'recovery' ? 'Recovery link' : 'Enrollment link'} for {handover.username}
      </p>
      <input readOnly aria-label="Enrollment link" value={handover.url}
        onFocus={e => e.currentTarget.select()}
        className="block w-full border rounded-lg p-2 font-mono text-xs bg-white" />
      <div className="flex gap-3 items-center">
        <button type="button" className="border border-navy-300 text-navy-800 px-3 py-1.5 rounded-lg"
          onClick={() => {
            void navigator.clipboard?.writeText(handover.url)
              .then(() => setCopied(true), () => setCopied(false))
          }}>
          <Copy size={14} className="inline mr-1"/> {copied ? 'Copied' : 'Copy link'}
        </button>
        <button type="button" className="text-navy-700 underline"
          onClick={() => { setHandover(null); setCopied(false) }}>Done</button>
      </div>
    </div>
  )

  const revoke = async () => {
    if (!token || !selectedId || busy ||
        !window.confirm('Disable this instructor’s credentials and revoke their session?')) return
    setBusy(true)
    try {
      await disableInstructor(token, selectedId)
        setMessage('Instructor disabled; existing tokens are revoked')
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not disable instructor')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="min-h-screen bg-parchment-50 px-4 py-8">
      <div className="max-w-3xl mx-auto space-y-6">
        <button type="button" className="text-sm text-navy-700 flex items-center gap-2"
          onClick={() => navigate('/pod')}><ArrowLeft size={16}/> Return to Pod</button>
        <header>
          <h1 className="text-2xl font-display font-bold text-gray-900">Classical Educator enrollment</h1>
          <p className="mt-2 text-sm text-gray-600">A parent/operator authorizes the class. Instructors can teach and review only assigned learners, never manage Bede's credentials, AI provider, or server.</p>
        </header>
        {!pilotMode && (
          <p role="alert" className="bg-amber-50 border border-amber-300 rounded-xl p-3 text-sm">
            Classroom accounts are disabled on this family installation. The operator must explicitly set
            EDUCATOR_PILOT_ENABLED=true and restart the Bede API before enrolling unrelated learners.
            In pilot mode, supervised educator sessions replace the shared child-PIN login.
          </p>
        )}

        <section className="bg-white border rounded-2xl p-5 space-y-3">
          <h2 className="font-semibold flex items-center gap-2"><ShieldCheck size={18}/> Add an instructor</h2>
          <p className="text-xs text-gray-600">Requires a strongly authenticated Bede administrator using a registered passkey. A one-use enrollment invitation is delivered only to the approved school mailbox, or, if email isn't set up on this computer, shown once here for you to give the teacher in person. No password or TOTP secret is shared.</p>
          <label className="block text-sm">Instructor username
            <input autoComplete="off" value={username} onChange={e => setUsername(e.target.value)}
              className="mt-1 block border rounded-lg p-2 w-full" placeholder="instructor.name" />
          </label>
          <label className="block text-sm">Verified school-affiliated email
            <input type="email" autoComplete="off" value={institutionalEmail}
              onChange={e => setInstitutionalEmail(e.target.value)}
              className="mt-1 block border rounded-lg p-2 w-full"
              placeholder="teacher@school.example" />
          </label>
          <button type="button" disabled={!pilotMode || busy || username.trim().length < 3 || !institutionalEmail.includes('@')}
            onClick={() => void enroll()} className="bg-navy-600 text-white px-4 py-2 rounded-lg disabled:opacity-50">
            <UserPlus size={15} className="inline mr-1"/> Send passkey invitation
          </button>
          {handover?.kind === 'invite' && handoverBox}
        </section>

        <section className="bg-white border rounded-2xl p-5 space-y-3">
          <h2 className="font-semibold flex items-center gap-2"><Users size={18}/> Authorize a class roster</h2>
          <label className="block text-sm">Instructor account
            <select value={selectedId} onChange={e => setSelectedId(e.target.value)}
              className="block mt-1 border rounded-lg p-2 w-full">
              {educators.map(e => <option key={e.id} value={e.id}>
                {e.username} — {e.learner_count} learners {e.enabled ? '' : '(disabled)'}
              </option>)}
            </select>
          </label>
          <fieldset className="text-sm space-y-2">
            <legend className="font-medium">Learners</legend>
            {rosterRows.map((row, i) => (
              <div key={row.id} className="flex gap-2 items-center flex-wrap">
                <input aria-label={`Learner ${i + 1} name`} value={row.name} maxLength={50} placeholder="First name"
                  onChange={e => setRosterRows(rows => rows.map(r => r.id === row.id ? { ...r, name: e.target.value } : r))}
                  className="border rounded-lg p-2 flex-1 min-w-[10rem]" />
                <select aria-label={`Learner ${i + 1} grade`} value={row.grade}
                  onChange={e => setRosterRows(rows => rows.map(r => r.id === row.id ? { ...r, grade: e.target.value as RosterGrade | '' } : r))}
                  className="border rounded-lg p-2 min-h-[44px]">
                  <option value="">Grade</option>
                  {ROSTER_GRADES.map(g => <option key={g} value={g}>{g === 'K' ? 'Kindergarten' : `Grade ${g}`}</option>)}
                </select>
                <select aria-label={`Learner ${i + 1} sex (optional)`} value={row.sex}
                  onChange={e => setRosterRows(rows => rows.map(r => r.id === row.id ? { ...r, sex: e.target.value as RosterRow['sex'] } : r))}
                  className="border rounded-lg p-2 min-h-[44px]">
                  <option value="">Sex (optional)</option>
                  <option value="M">Male</option>
                  <option value="F">Female</option>
                </select>
                <button type="button" aria-label={`Remove learner ${i + 1}`} disabled={rosterRows.length === 1}
                  onClick={() => setRosterRows(rows => rows.filter(r => r.id !== row.id))}
                  className="border rounded-lg px-3 py-2 min-h-[44px] disabled:opacity-40">Remove</button>
              </div>
            ))}
            <button type="button" disabled={rosterRows.length >= 90}
              onClick={() => setRosterRows(rows => [...rows, { id: Math.max(...rows.map(r => r.id)) + 1, name: '', grade: '', sex: '' }])}
              className="border rounded-lg px-3 py-2 min-h-[44px] disabled:opacity-40">Add a learner</button>
          </fieldset>
          <p className="text-xs text-gray-600">This replaces the instructor’s assignment list. Existing parent-approved learner plans are not overwritten. New learners start with classical books, math, and language arts; the parent can refine their plans in Setup. Import only learners whose authorized adult has approved participation.</p>
          <div className="flex gap-3 items-center flex-wrap">
            <button type="button" disabled={!pilotMode || busy || !selectedId} onClick={() => void importRoster()}
              className="bg-navy-600 text-white px-4 py-2 rounded-lg disabled:opacity-50">Save authorized roster</button>
            <button type="button" disabled={busy || !selectedId} onClick={() => void revoke()}
              className="border border-red-300 text-red-700 px-4 py-2 rounded-lg disabled:opacity-50">Disable instructor</button>
          </div>
          <div className="border-t pt-3 space-y-2">
            <h3 className="text-sm font-semibold">Replace a lost passkey</h3>
            <p className="text-xs text-gray-600">Confirm the teacher's identity and school affiliation yourself first. Using the new link turns off the teacher's old passkeys and signs out their sessions.</p>
            <label className="block text-sm">The teacher's school email (the one they were invited with)
              <input type="email" autoComplete="off" value={recoveryEmail}
                onChange={e => setRecoveryEmail(e.target.value)}
                className="mt-1 block border rounded-lg p-2 w-full" placeholder="teacher@school.example" />
            </label>
            <button type="button" disabled={!pilotMode || busy || !selectedId || !recoveryEmail.includes('@')}
              onClick={() => void recover()}
              className="border border-navy-300 text-navy-800 px-4 py-2 rounded-lg disabled:opacity-50">
              Issue recovery link
            </button>
            {handover?.kind === 'recovery' && handoverBox}
          </div>
          {capacity && <p className="text-xs text-gray-600">
            Locuto capacity planning: {capacity.groups.length} potential Pods, each at most {capacity.maximum_members} people, including instructor. Messaging integration is NOT connected or enabled; no roster details are transmitted.
          </p>}
        </section>
        {message && <p role="status" className="text-sm text-navy-800">{message}</p>}
      </div>
    </main>
  )
}

