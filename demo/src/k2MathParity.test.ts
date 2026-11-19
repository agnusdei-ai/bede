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
    expect(mathBlock).toContain('onSpeak={roundsSpeak ? speakInBedesVoice : undefined}')
    expect(mathBlock).not.toContain('speakOnDevice')
    expect(chat).toMatch(/const speakInBedesVoice = useCallback\(\(text: string\) => \{ stopSpeech\(\); speak\(text\) \}/)

    const demoApp = source(demo, 'App.tsx')
    expect(demoApp).toMatch(/const speakNumberTime = useCallback\(\(text: string\) => \{ stopSpeech\(\); speak\(text\) \}/)
    expect(demoApp).not.toContain('SpeechSynthesisUtterance')
    expect(source(demo, 'useTextToSpeech.ts')).not.toMatch(/new SpeechSynthesisUtterance|speechSynthesis\.speak/)
    const demoBlock = demoApp.slice(demoApp.indexOf('<K2MathPractice'), demoApp.indexOf('/>', demoApp.indexOf('<K2MathPractice')))
    expect(demoBlock).toContain('onSpeak={ttsEnabled ? speakNumberTime : undefined}')
  })

  it('keeps Sound Time and Map Practice aligned with the household app', () => {
    const appPhonics = source(app, 'components/K2PhonicsPractice.tsx')
      .replace("../services/k2PhonicsTypes", "./k2PhonicsTypes")
      .replace("./routine/RoutineShell", "./RoutineShell")
    const appMap = source(app, 'components/MapPractice.tsx')
      .replace("../services/mapPracticeTypes", "./mapPracticeTypes")
      .replace("./routine/RoutineShell", "./RoutineShell")
    const appScene = source(app, 'components/MapScene.tsx')
      .replace("../services/mapPracticeTypes", "./mapPracticeTypes")

    expect(source(demo, 'K2PhonicsPractice.tsx')).toBe(appPhonics)
    expect(source(demo, 'MapPractice.tsx')).toBe(appMap)
    expect(source(demo, 'MapScene.tsx')).toBe(appScene)
    expect(source(demo, 'k2PhonicsTypes.ts')).toBe(source(app, 'services/k2PhonicsTypes.ts'))
    expect(source(demo, 'mapPracticeTypes.ts')).toBe(source(app, 'services/mapPracticeTypes.ts'))

    for (const lang of ['en', 'es']) {
      const appCopy = JSON.parse(source(app, `i18n/locales/${lang}.json`))
      const demoCopy = JSON.parse(source(demo, `i18n/locales/${lang}.json`))
      expect(demoCopy.k2Phonics).toEqual(appCopy.k2Phonics)
      expect(demoCopy.mapPractice).toEqual(appCopy.mapPractice)
    }
  })

  it("speaks every K-2 round in Bede's own voice only, in both apps", () => {
    // Owner direction 2026-11-19: the demo and all features use Bede's voice
    // only. No browser speech, no on-device voice.
    const block = (text: string, tag: string) =>
      text.slice(text.indexOf(tag), text.indexOf('/>', text.indexOf(tag)))
    const chat = source(app, 'components/SocraticChat.tsx')
    const demoApp = source(demo, 'App.tsx')
    for (const tag of ['<K2PhonicsPractice', '<MapPractice']) {
      expect(block(chat, tag)).toContain('onSpeak={roundsSpeak ? speakInBedesVoice : undefined}')
      expect(block(demoApp, tag)).toContain('onSpeak={ttsEnabled ? speakNumberTime : undefined}')
    }
    for (const file of ['K2PhonicsPractice.tsx', 'MapPractice.tsx', 'MapScene.tsx']) {
      const text = source(demo, file)
      expect(text).not.toContain('SpeechSynthesis')
      expect(text).not.toContain('speakOnDevice')
    }
  })

  it('keeps runtime code independent of household source imports', () => {
    const runtime = [
      source(demo, 'App.tsx'),
      source(demo, 'api.ts'),
      source(demo, 'K2MathPractice.tsx'),
      source(demo, 'MathPieces.tsx'),
      source(demo, 'RoutineShell.tsx'),
      source(demo, 'K2PhonicsPractice.tsx'),
      source(demo, 'MapPractice.tsx'),
      source(demo, 'MapScene.tsx'),
    ].join('\n')
    expect(runtime).not.toMatch(/from\s+['"][^'"]*homeschool-tutor\/src/)
  })
})
