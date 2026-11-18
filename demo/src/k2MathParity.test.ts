import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const app = resolve(__dirname, '../../homeschool-tutor/src')
const demo = __dirname

function source(root: string, path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('demo Number Time mirrors', () => {
  it('keeps the shared UI, wire types, and classes aligned with the household app', () => {
    const appMath = source(app, 'components/K2MathPractice.tsx')
      .replace("../services/k2MathTypes", "./k2MathTypes")
      .replace("./routine/RoutineShell", "./RoutineShell")
    const demoMath = source(demo, 'K2MathPractice.tsx')
    const appPieces = source(app, 'components/MathPieces.tsx')
      .replace("../services/k2MathTypes", "./k2MathTypes")
    const demoPieces = source(demo, 'MathPieces.tsx')

    expect(demoMath).toBe(appMath)
    expect(demoPieces).toBe(appPieces)
    expect(source(demo, 'RoutineShell.tsx')).toBe(source(app, 'components/routine/RoutineShell.tsx'))
    expect(source(demo, 'practiceStyles.ts')).toBe(source(app, 'components/practiceStyles.ts'))
    expect(source(demo, 'k2MathTypes.ts')).toBe(source(app, 'services/k2MathTypes.ts'))
  })

  it("speaks Number Time in Bede's own voice in both apps, with no other voice as a default", () => {
    // Owner direction 2026-11-18. Both apps hand the round Bede's chat voice
    // (useTextToSpeech's speak), never an on-device or browser default voice.
    const chat = source(app, 'components/SocraticChat.tsx')
    const mathBlock = chat.slice(chat.indexOf('<K2MathPractice'), chat.indexOf('/>', chat.indexOf('<K2MathPractice')))
    expect(mathBlock).toContain('onSpeak={ttsEnabled ? speakInBedesVoice : undefined}')
    expect(mathBlock).not.toContain('speakOnDevice')
    expect(chat).toMatch(/const speakInBedesVoice = useCallback\(\(text: string\) => \{ stopSpeech\(\); speak\(text\) \}/)

    const demoApp = source(demo, 'App.tsx')
    expect(demoApp).toMatch(/const speakNumberTime = useCallback\(\(text: string\) => \{ stopSpeech\(\); speak\(text\) \}/)
    expect(demoApp).not.toContain('SpeechSynthesisUtterance')
    const demoBlock = demoApp.slice(demoApp.indexOf('<K2MathPractice'), demoApp.indexOf('/>', demoApp.indexOf('<K2MathPractice')))
    expect(demoBlock).toContain('onSpeak={ttsEnabled ? speakNumberTime : undefined}')
  })

  it('keeps runtime code independent of household source imports', () => {
    const runtime = [
      source(demo, 'App.tsx'),
      source(demo, 'api.ts'),
      source(demo, 'K2MathPractice.tsx'),
      source(demo, 'MathPieces.tsx'),
      source(demo, 'RoutineShell.tsx'),
    ].join('\n')
    expect(runtime).not.toMatch(/from\s+['"][^'"]*homeschool-tutor\/src/)
  })
})
