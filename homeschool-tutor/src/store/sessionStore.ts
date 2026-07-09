import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { SessionConfig, Subject, ChatMessage } from '../types'
import { SUBJECTS } from '../types'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool?: string
  timestamp: Date
}

interface SessionState {
  // Auth
  token: string | null
  role: 'parent' | 'child' | null
  setAuth: (token: string, role: 'parent' | 'child') => void
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

  // Actions
  startSession: () => void
  startAssistantStream: () => void
  addUserMessage: (content: string) => void
  appendAssistantChunk: (content: string) => void
  addToolMessage: (tool: string, content: string) => void
  finalizeAssistantMessage: () => void
  nextSubject: () => void
  endSession: () => void
  setStreaming: (v: boolean) => void
}

let msgIdCounter = 0
const nextId = () => `msg-${++msgIdCounter}`

/**
 * Derive API-format ChatMessage[] from a displayMessages slice.
 * Excludes system messages, tool messages, and the streaming placeholder.
 *
 * @param msgs  - full displayMessages array
 * @param from  - start index (defaults to 0 = full session)
 */
export function getApiMessages(msgs: DisplayMessage[], from = 0): ChatMessage[] {
  return msgs
    .slice(from)
    .filter(
      (m) =>
        (m.role === 'user' || m.role === 'assistant') &&
        !m.tool &&
        m.id !== 'streaming-response',
    )
    .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
  token: null,
  role: null,
  setAuth: (token, role) => set({ token, role }),
  logout: () =>
    set({
      token: null,
      role: null,
      sessionConfig: null,
      podStudents: [],
      displayMessages: [],
      subjectStart: 0,
      sessionStartedAt: null,
      subjectStartedAt: null,
      currentSubjectIndex: 0,
      subjectsCompleted: [],
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
    const { currentSubjectIndex, sessionConfig, currentSubject } = get()
    if (!sessionConfig) return
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
        subjectStartedAt: new Date(),
        // New subject context starts AFTER the transition system message
        subjectStart: s.displayMessages.length + 1,
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
        sessionConfig: s.sessionConfig,
        podStudents: s.podStudents,
      }),
    }
  )
)
