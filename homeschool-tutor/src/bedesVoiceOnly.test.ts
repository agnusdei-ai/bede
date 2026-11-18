/**
 * Every feature speaks in Bede's own voice and in no other (owner decisions
 * 2026-11-18, docs/DECISIONS.md entry 46).
 *
 * Bede's voice is the server's /tutor/speak, reached through `useTextToSpeech`
 * (in the demo, through the `api.ts` helper that hook calls). So:
 *
 * - no shipped file in the app or the demo may speak through the browser's own
 *   speechSynthesis, the hook included: with no voice configured, or a failed
 *   line, Bede is silent rather than speaking in a voice that is not his;
 * - nothing but the hook (and the demo's api.ts) may request /tutor/speak;
 * - in the chat, every practice screen that speaks (Map Practice, Sound Time,
 *   Number Time, and any added later) is handed the one Bede-voice callback.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOTS = [resolve(__dirname), resolve(__dirname, '../../demo/src')]
const VOICE_HOOK = new Set(['useTextToSpeech.ts', join('hooks', 'useTextToSpeech.ts')])
const DIRECT_SPEECH = /new\s+SpeechSynthesisUtterance|speechSynthesis\.speak\s*\(/
// The voice request itself: the app's hook, and the demo's api.ts that its hook calls.
const SPEAK_ROUTE = /['"`][^'"`]*\/tutor\/speak['"`]/
const SPEAK_ROUTE_ALLOWED = new Set([...VOICE_HOOK, 'api.ts'])

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : sourceFiles(path)
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : []
  })
}

describe("Bede's voice is the only voice", () => {
  it('no shipped file, the voice hook included, speaks through the browser voice', () => {
    const offenders = ROOTS.flatMap((root) => sourceFiles(root)
      .filter((path) => DIRECT_SPEECH.test(readFileSync(path, 'utf8')))
      .map((path) => relative(resolve(__dirname, '../..'), path)))
    expect(offenders).toEqual([])
  })

  it('the scans are not vacuous: they see both voice hooks and recognize what they forbid', () => {
    for (const root of ROOTS) {
      const hook = sourceFiles(root).find((path) => VOICE_HOOK.has(relative(root, path)))
      expect(hook, `no useTextToSpeech.ts under ${root}`).toBeTruthy()
      expect(SPEAK_ROUTE.test(readFileSync(hook!, 'utf8')) || root.endsWith('demo/src')).toBe(true)
    }
    expect(DIRECT_SPEECH.test('window.speechSynthesis.speak(u)')).toBe(true)
    expect(DIRECT_SPEECH.test('new SpeechSynthesisUtterance(text)')).toBe(true)
    expect(SPEAK_ROUTE.test("fetch('/api/tutor/speak')")).toBe(true)
  })

  it('only the voice hook (and the demo api it calls) requests /tutor/speak', () => {
    const offenders = ROOTS.flatMap((root) => sourceFiles(root)
      .filter((path) => !SPEAK_ROUTE_ALLOWED.has(relative(root, path)))
      .filter((path) => SPEAK_ROUTE.test(readFileSync(path, 'utf8')))
      .map((path) => relative(resolve(__dirname, '../..'), path)))
    expect(offenders).toEqual([])
  })

  it("every speaking screen in the chat is handed Bede's voice and nothing else", () => {
    const chat = readFileSync(resolve(__dirname, 'components/SocraticChat.tsx'), 'utf8')
    const props = [...chat.matchAll(/onSpeak=\{([^}]*)\}/g)].map((m) => m[1].trim())
    expect(props.length).toBeGreaterThanOrEqual(3)
    for (const value of props) expect(value).toBe('ttsEnabled ? speakInBedesVoice : undefined')
  })
})
