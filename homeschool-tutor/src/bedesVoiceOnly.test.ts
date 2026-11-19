/**
 * Every feature speaks in Bede's own voice, or not at all (owner direction
 * 2026-11-18; docs/DECISIONS.md, the beta voice decision).
 *
 * Bede's voice is `useTextToSpeech`: the server's /tutor/speak. A line it
 * cannot speak is silent. The browser's own speech engine is not Bede's
 * voice, and it is what made Number Time and Sound Time sound unlike Bede,
 * so NO shipped file in the app or the demo may use it, the hooks included,
 * and only the hook (and the demo api it calls) may request /tutor/speak.
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
  it('no shipped file speaks through the browser, not even the voice hooks', () => {
    const offenders = ROOTS.flatMap((root) => sourceFiles(root)
      .filter((path) => DIRECT_SPEECH.test(readFileSync(path, 'utf8')))
      .map((path) => relative(resolve(__dirname, '../..'), path)))
    expect(offenders).toEqual([])
  })

  it('the scan reaches both apps and recognises browser speech, so it is not vacuous', () => {
    for (const root of ROOTS) {
      const files = sourceFiles(root)
      expect(files.some((path) => ALLOWED.has(relative(root, path))), `no useTextToSpeech.ts under ${root}`).toBe(true)
      expect(files.length).toBeGreaterThan(20)
    }
    expect(DIRECT_SPEECH.test('const u = new SpeechSynthesisUtterance(text)')).toBe(true)
    expect(DIRECT_SPEECH.test('window.speechSynthesis.speak(u)')).toBe(true)
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
    for (const value of props) expect(value).toBe('roundsSpeak ? speakInBedesVoice : undefined')
  })

  it('a round asks for ear-only questions only when Bede can actually speak them', () => {
    const chat = readFileSync(resolve(__dirname, 'components/SocraticChat.tsx'), 'utf8')
    const props = [...chat.matchAll(/canSpeak=\{([^}]*)\}/g)].map((m) => m[1].trim())
    expect(props.length).toBeGreaterThanOrEqual(2)
    for (const value of props) expect(value).toBe('roundCanSpeak')
    expect(chat).toMatch(/const roundsSpeak = ttsEnabled && voiceCanSpeak === true/)
    expect(chat).toMatch(/const roundCanSpeak = !ttsEnabled \? false : voiceCanSpeak/)
  })

  it('a round only ever speaks its own fixed lines, never what the child chose', () => {
    // Everything a round hands to onSpeak: the line on screen, translated
    // feedback, or a fixed sound the server wrote into the lesson. Never the
    // `choice` the child tapped or anything they said.
    const allowed = new Set(['line', 'sound', "g.sound ?? ''", "display.word ?? ''"])
    for (const name of ['K2PhonicsPractice.tsx', 'K2MathPractice.tsx']) {
      const src = readFileSync(resolve(__dirname, 'components', name), 'utf8')
      const args = [...src.matchAll(/speakRef\.current\?\.\(([^)]*\)?)\)/g)].map((m) => m[1].trim())
      expect(args.length, name).toBeGreaterThan(2)
      for (const arg of args) {
        expect(allowed.has(arg) || /^t\('k2(Phonics|Math)\.[a-zA-Z]+'\)$/.test(arg), `${name} speaks ${arg}`).toBe(true)
      }
    }
  })
})
