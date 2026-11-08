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

function parseRoster(text: string): SessionConfig[] {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (!lines.length || lines.length > 90) throw new Error('Enter between 1 and 90 learners')
  const names = new Set<string>()
  return lines.map((line, index) => {
    const parts = line.split(',').map((part) => part.trim())
    if (parts.length < 2 || parts.length > 3) {
      throw new Error(`Line ${index + 1}: use Name,Grade (optional third field: M/F)`)
    }
    const [student_name, grade, sex] = parts
    if (!student_name || student_name.length > 50 || !/^(K|[1-8])$/.test(grade)) {
      throw new Error(`Line ${index + 1}: enter a learner name and grade K–8`)
    }
    if (sex && !['M', 'F'].includes(sex.toUpperCase())) {
      throw new Error(`Line ${index + 1}: optional sex must be M or F`)
    }
    if (names.has(student_name.toLowerCase())) throw new Error('Duplicate learner in roster')
    names.add(student_name.toLowerCase())
    const numeric = grade === 'K' ? 0 : Number(grade)
    return {
      student_name,
      grade,
      grade_stage: numeric <= 2 ? 'K-2' : numeric <= 5 ? '3-5' : '6-8',
      subjects: ['mathematics', 'living_books', 'language_arts'],
      ...(sex ? { sex: sex.toLowerCase() === 'm' ? 'male' as const : 'female' as const } : {}),
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
  const [rosterText, setRosterText] = useState('')
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
      const parsed = parseRoster(rosterText)
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
          <label className="block text-sm">Learners (one per line: Name,Grade,optional M/F)
            <textarea value={rosterText} onChange={e => setRosterText(e.target.value)}
              rows={7} className="mt-1 block border rounded-lg p-2 w-full font-mono text-sm"
              placeholder={'Learner A,4\nLearner B,3\nLearner C,K'} />
          </label>
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

export { parseRoster }
