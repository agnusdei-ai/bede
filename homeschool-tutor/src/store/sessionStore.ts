import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { SessionConfig, Subject, ChatMessage, VisualAidData } from '../types'
import { SUBJECTS } from '../types'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool?: string
  visualAid?: VisualAidData
  timestamp: Date
}

export type TimeOfDay = 'morning' | 'afternoon' | 'evening'

// Bede has no built-in sense of wall-clock time — this is the only source
// of it, read once from the device's own clock at login. 9am-11:59am =
// morning (Morning Time + its opening prayer), 12pm-4:59pm = afternoon,
// 5pm-11:59pm = evening (its own prayer intro, framed as the day closing
// rather than opening) — see ai_service.py's _time_of_day_note.
export function deriveTimeOfDay(date: Date): TimeOfDay {
  const hour = date.getHours()
  if (hour < 12) return 'morning'
  if (hour < 17) return 'afternoon'
  return 'evening'
}

interface SessionState {
  // Auth
  token: string | null
  role: 'parent' | 'child' | null
  // Chosen at the login screen itself (Login.tsx's English/Español toggle),
  // per-login rather than per-student — see docs/LOCALIZATION.md. Persisted
  // so a page refresh mid-session doesn't silently fall back to English;
  // reset to null on logout so the next login starts from the toggle's own
  // default again, not whatever the last person picked.
  locale: string | null
  setAuth: (token: string, role: 'parent' | 'child', locale?: string) => void
  logout: () => void

  // Pod — all students configured for today's session (parent's device)
  podStudents: SessionConfig[]
  setPodStudents: (configs: SessionConfig[]) => void

  // Session configuration for the currently active student
  sessionConfig: SessionConfig | null
  setSessionConfig: (config: SessionConfig) => void

  // Active tutoring state
  currentSubjectIndex: number
  currentSubject: Subject
  // Index into displayMessages where the current subject's messages begin.
  // getApiMessages(displayMessages, subjectStart) gives the current-subject context
  // sent to the API; cleared implicitly on each subject transition.
  subjectStart: number
  displayMessages: DisplayMessage[]
  isStreaming: boolean
  sessionStartedAt: Date | null
  subjectStartedAt: Date | null
  subjectsCompleted: Subject[]
  // Derived once from the device clock when the session starts (see
  // deriveTimeOfDay) and sent to the API on every chat turn so Bede's
  // greeting and opening/closing prayer match the child's actual local
  // time of day, not just subject order.
  timeOfDay: TimeOfDay | null

  // Actions
  startSession: () => void
  startAssistantStream: () => void
  addUserMessage: (content: string) => void
  appendAssistantChunk: (content: string) => void
  addToolMessage: (tool: string, content: string) => void
  addVisualAidMessage: (visualAid: VisualAidData) => void
  finalizeAssistantMessage: () => void
  nextSubject: () => void
  endSession: () => void
  setStreaming: (v: boolean) => void
}

let msgIdCounter = 0
const nextId = () => `msg-${++msgIdCounter}`

/**
 * Derive API-format ChatMessage[] from a displayMessages slice. Excludes
 * system messages, the streaming placeholder, and any turn left with no
 * text at all once the mapping below runs.
 *
 * Tool-card and visual-aid messages are NOT dropped (real bug this fixes):
 * doing so used to erase Bede's own memory of anything it did outside
 * typed prose — a turn where it only called show_visual_aid, with no other
 * text, looked to Bede like it had said nothing at all last turn. In Art &
 * Music this meant a child saying "I see the picture" right after Bede
 * showed one read, from Bede's side, as an unprompted remark following its
 * own silence — the natural conclusion being "my last attempt didn't
 * work," so it would show the very same image again. Tool-card content is
 * already real natural-language text Bede said to the child, so it's
 * folded back in as ordinary assistant text here; visual aids have no
 * natural text of their own, so they get a short synthesized description
 * instead of the blank string they used to leave behind.
 *
 * @param msgs  - full displayMessages array
 * @param from  - start index (defaults to 0 = full session)
 */
export function getApiMessages(msgs: DisplayMessage[], from = 0): ChatMessage[] {
  return msgs
    .slice(from)
    .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.id !== 'streaming-response')
    .map((m): ChatMessage | null => {
      if (m.visualAid) {
        return {
          role: m.role as 'user' | 'assistant',
          content: `[Showed a picture: "${m.visualAid.title}" by ${m.visualAid.creator} (${m.visualAid.year})]`,
        }
      }
      if (!m.content.trim()) return null
      return { role: m.role as 'user' | 'assistant', content: m.content }
    })
    .filter((m): m is ChatMessage => m !== null)
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
  token: null,
  role: null,
  locale: null,
  setAuth: (token, role, locale) => set({ token, role, locale: locale ?? null }),
  logout: () =>
    set({
      token: null,
      role: null,
      locale: null,
      sessionConfig: null,
      podStudents: [],
      displayMessages: [],
      subjectStart: 0,
      sessionStartedAt: null,
      subjectStartedAt: null,
      currentSubjectIndex: 0,
      subjectsCompleted: [],
      timeOfDay: null,
    }),

  podStudents: [],
  setPodStudents: (configs) => set({ podStudents: configs }),

  sessionConfig: null,
  setSessionConfig: (config) => set({ sessionConfig: config }),

  currentSubjectIndex: 0,
  currentSubject: 'morning_time',
  subjectStart: 0,
  displayMessages: [],
  isStreaming: false,
  sessionStartedAt: null,
  subjectStartedAt: null,
  subjectsCompleted: [],
  timeOfDay: null,

  startSession: () => {
    const config = get().sessionConfig
    if (!config) return
    const firstSubject = config.subjects[0] ?? 'morning_time'
    const welcomeMsg: DisplayMessage = {
      id: nextId(),
      role: 'system',
      content: `Welcome, ${config.student_name}! Today we begin with ${
        SUBJECTS.find((s) => s.id === firstSubject)?.label ?? firstSubject
      }. Bede is ready to learn with you. 🌿`,
      timestamp: new Date(),
    }
    const now = new Date()
    set({
      sessionStartedAt: now,
      subjectStartedAt: now,
      timeOfDay: deriveTimeOfDay(now),
      currentSubjectIndex: 0,
      currentSubject: firstSubject,
      displayMessages: [welcomeMsg],
      subjectStart: 1, // API history starts after the welcome system message
      subjectsCompleted: [],
    })
  },

  startAssistantStream: () =>
    set((s) => ({
      isStreaming: true,
      displayMessages: [
        ...s.displayMessages,
        { id: 'streaming-response', role: 'assistant' as const, content: '', timestamp: new Date() },
      ],
    })),

  addUserMessage: (content) => {
    set((s) => ({
      displayMessages: [
        ...s.displayMessages,
        { id: nextId(), role: 'user', content, timestamp: new Date() },
        // Reserve streaming slot immediately so the UI shows the thinking indicator
        { id: 'streaming-response', role: 'assistant', content: '', timestamp: new Date() },
      ],
      isStreaming: true,
    }))
  },

  appendAssistantChunk: (content) => {
    set((s) => ({
      displayMessages: s.displayMessages.map((m) =>
        m.id === 'streaming-response'
          ? { ...m, content: m.content + content }
          : m,
      ),
    }))
  },

  addToolMessage: (tool, content) => {
    set((s) => ({
      displayMessages: [
        ...s.displayMessages.filter((m) => m.id !== 'streaming-response'),
        // Preserve any text already streamed before the tool call
        ...s.displayMessages
          .filter((m) => m.id === 'streaming-response' && m.content)
          .map((m) => ({ ...m, id: nextId() })),
        { id: nextId(), role: 'assistant' as const, content, tool, timestamp: new Date() },
        // Reopen streaming slot for any text that follows the tool call
        { id: 'streaming-response', role: 'assistant' as const, content: '', timestamp: new Date() },
      ],
    }))
  },

  addVisualAidMessage: (visualAid) => {
    set((s) => ({
      displayMessages: [
        ...s.displayMessages.filter((m) => m.id !== 'streaming-response'),
        ...s.displayMessages
          .filter((m) => m.id === 'streaming-response' && m.content)
          .map((m) => ({ ...m, id: nextId() })),
        { id: nextId(), role: 'assistant' as const, content: '', visualAid, timestamp: new Date() },
        { id: 'streaming-response', role: 'assistant' as const, content: '', timestamp: new Date() },
      ],
    }))
  },

  finalizeAssistantMessage: () => {
    set((s) => {
      const streamingMsg = s.displayMessages.find((m) => m.id === 'streaming-response')
      const fullContent = streamingMsg?.content ?? ''
      const withoutSlot = s.displayMessages.filter((m) => m.id !== 'streaming-response')
      const display = fullContent
        ? [
            ...withoutSlot,
            {
              id: nextId(),
              role: 'assistant' as const,
              content: fullContent,
              timestamp: new Date(),
            },
          ]
        : withoutSlot

      return { displayMessages: display, isStreaming: false }
    })
  },

  nextSubject: () => {
    const { currentSubjectIndex, sessionConfig, currentSubject, subjectsCompleted } = get()
    if (!sessionConfig) return
    // Every subject already marked complete — nothing left to transition
    // to. A second call here (e.g. Bede calling suggest_next_subject again
    // after the day is already wrapped up) must be a no-op, not another
    // "All subjects complete!" system message stacking up.
    if (subjectsCompleted.length >= sessionConfig.subjects.length) return
    const nextIndex = currentSubjectIndex + 1
    const nextSubj = sessionConfig.subjects[nextIndex]
    set((s) => {
      const transitionMsg: DisplayMessage = {
        id: nextId(),
        role: 'system',
        content: nextSubj
          ? `✅ Moving to ${SUBJECTS.find((sub) => sub.id === nextSubj)?.label ?? nextSubj}`
          : '🎉 All subjects complete! Great work today.',
        timestamp: new Date(),
      }
      return {
        currentSubjectIndex: nextIndex,
        currentSubject: nextSubj ?? currentSubject,
        subjectsCompleted: [...s.subjectsCompleted, currentSubject],
        subjectStartedAt: nextSubj ? new Date() : s.subjectStartedAt,
        // Real bug this fixes (scripts/bugcatcher.mts's S4 scenario): once
        // there's no next subject, there's no new context to start fresh —
        // this must NOT jump past the transition message, or any further
        // chat (a child who keeps talking after finishing the day) gets
        // sliced down to a completely empty history on the very next turn.
        subjectStart: nextSubj ? s.displayMessages.length + 1 : s.subjectStart,
        displayMessages: [...s.displayMessages, transitionMsg],
      }
    })
  },

  endSession: () => {
    const { currentSubject } = get()
    set((s) => ({
      subjectsCompleted: s.subjectsCompleted.includes(currentSubject)
        ? s.subjectsCompleted
        : [...s.subjectsCompleted, currentSubject],
    }))
  },

      setStreaming: (v) => set({ isStreaming: v }),
    }),
    {
      name: 'agnus-dei-session',
      storage: createJSONStorage(() => sessionStorage),
      // Only persist auth + config — never chat history or streaming state
      partialize: (s) => ({
        token: s.token,
        role: s.role,
        locale: s.locale,
        sessionConfig: s.sessionConfig,
        podStudents: s.podStudents,
      }),
    }
  )
)
