/**
 * Every feature speaks in Bede's own voice (owner direction 2026-11-18).
 *
 * Bede's voice is `useTextToSpeech`: the server's /tutor/speak, and the
 * browser's own speech only when no speech provider is configured at all.
 * A feature that builds its own SpeechSynthesisUtterance speaks in some other
 * voice, which is what made Number Time and Sound Time sound unlike Bede. So
 * outside the hook itself, in both the app and the demo, no shipped file may
 * call the browser's speech engine directly, or call /tutor/speak itself.
 *
 * And in the chat, every practice screen that speaks (Map Practice, Sound
 * Time, Number Time, and any added later) is handed the one Bede-voice
 * callback, so a new screen cannot be wired to a different one by accident.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOTS = [resolve(__dirname), resolve(__dirname, '../../demo/src')]
const ALLOWED = new Set(['useTextToSpeech.ts', join('hooks', 'useTextToSpeech.ts')])
const DIRECT_SPEECH = /new\s+SpeechSynthesisUtterance|speechSynthesis\.speak\s*\(/
// The voice request itself: the app's hook, and the demo's api.ts that its hook calls.
const SPEAK_ROUTE = /['"`][^'"`]*\/tutor\/speak['"`]/
const SPEAK_ROUTE_ALLOWED = new Set([...ALLOWED, 'api.ts'])

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : sourceFiles(path)
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : []
  })
}

describe("Bede's voice is the only voice", () => {
  it('no shipped file outside useTextToSpeech speaks through the browser directly', () => {
    const offenders = ROOTS.flatMap((root) => sourceFiles(root)
      .filter((path) => !ALLOWED.has(relative(root, path)))
      .filter((path) => DIRECT_SPEECH.test(readFileSync(path, 'utf8')))
      .map((path) => relative(resolve(__dirname, '../..'), path)))
    expect(offenders).toEqual([])
  })

  it('still finds the one place that is allowed, so the scan is not vacuous', () => {
    for (const root of ROOTS) {
      const hook = sourceFiles(root).find((path) => ALLOWED.has(relative(root, path)))
      expect(hook, `no useTextToSpeech.ts under ${root}`).toBeTruthy()
      expect(DIRECT_SPEECH.test(readFileSync(hook!, 'utf8'))).toBe(true)
    }
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
