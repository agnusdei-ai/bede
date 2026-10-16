#!/usr/bin/env node
/**
 * G1 browser half of the voice-binding check. Run by g1_browser_check.py,
 * never on its own: that script seeds Synthetic Campus One/Two, Teacher
 * One/Two and the two same-name learners through the real admin routes,
 * serves the real API, starts the real Vite dev server, and passes the ids
 * and tokens in BEDE_G1_INPUT.
 *
 * In a real Chromium page on the app's own origin, this imports the app's
 * REAL frontend modules (services/voiceApi.ts) through Vite and drives them
 * against the real API through the app's own /api proxy. Admin revocation is
 * sent from Node, mid-stream, while the page is still reading SSE.
 *
 * Output: one JSON object on stdout. Synthetic data only.
 */
const { chromium } = require('playwright')

const input = JSON.parse(process.env.BEDE_G1_INPUT)
const { app, api, admin, one, oneNext, two, learnerOne, campusOne, teacherOne } = input

const PCM = 'AAEAAQABAAEAAQABAAEAAQABAAE=' // 24 bytes of synthetic int16 samples

async function main() {
  const browser = await chromium.launch()
  const page = await browser.newPage()
  try {
    // Any Vite-served URL puts the page on the app origin without mounting
    // the app (and its auth interceptors) around these direct module calls.
    await page.goto(`${app}/src/services/voiceApi.ts`)
    const result = {}

    // A. Authorized: start, push, partial, finish, final, done.
    // ONE reader for the whole turn, as the app's own hook does: breaking out
    // of the stream closes it, which the server treats as the client leaving.
    result.authorized = await page.evaluate(async ({ one, learnerOne, PCM }) => {
      const v = await import('/src/services/voiceApi.ts')
      const sid = await v.startVoiceStream(one, 'en', { learner_id: learnerOne })
      const items = []
      let sawPartial
      const partial = new Promise((r) => { sawPartial = r })
      const reading = (async () => {
        for await (const item of v.streamVoiceEvents(one, sid)) {
          items.push(item)
          if (item.type === 'partial') sawPartial()
        }
      })()
      const bytes = Uint8Array.from(atob(PCM), (c) => c.charCodeAt(0))
      await v.pushVoiceStreamChunk(one, sid, new Blob([bytes, new TextEncoder().encode('browser-one.')]))
      await partial
      await v.finishVoiceStream(one, sid)
      await reading
      return { types: items.map((i) => i.type), first: items[0] }
    }, { one, learnerOne, PCM })

    // B. Teacher Two cannot start a session for Learner One.
    result.crossCampusStart = await page.evaluate(async ({ two, learnerOne }) => {
      const v = await import('/src/services/voiceApi.ts')
      try {
        await v.startVoiceStream(two, 'en', { learner_id: learnerOne })
        return 'opened'
      } catch (e) {
        return String(e.message)
      }
    }, { two, learnerOne })

    // C. Teacher Two cannot subscribe to Teacher One's copied session id.
    result.copiedSessionSubscribe = await page.evaluate(async ({ one, two, learnerOne }) => {
      const v = await import('/src/services/voiceApi.ts')
      const sid = await v.startVoiceStream(one, 'en', { learner_id: learnerOne })
      const items = []
      for await (const item of v.streamVoiceEvents(two, sid)) items.push(item)
      return items
    }, { one, two, learnerOne })

    // D. Revocation while the page is reading the stream.
    await page.evaluate(async ({ one, learnerOne, PCM }) => {
      const v = await import('/src/services/voiceApi.ts')
      const sid = await v.startVoiceStream(one, 'en', { learner_id: learnerOne })
      window.__g1 = { sid, items: [], ended: false }
      const bytes = Uint8Array.from(atob(PCM), (c) => c.charCodeAt(0))
      await v.pushVoiceStreamChunk(one, sid, new Blob([bytes, new TextEncoder().encode('before-revo.')]))
      ;(async () => {
        for await (const item of v.streamVoiceEvents(one, sid)) window.__g1.items.push(item)
        window.__g1.ended = true
      })()
    }, { one, learnerOne, PCM })
    await page.waitForFunction(() => window.__g1.items.some((i) => i.type === 'partial'), null, { timeout: 15000 })
    const revoke = await fetch(`${api}/pilot/campuses/${campusOne}/educators/${teacherOne}/learners/${learnerOne}`, {
      method: 'DELETE', headers: { Authorization: `Bearer ${admin}` },
    })
    result.revokeStatus = revoke.status
    await page.waitForFunction(() => window.__g1.ended, null, { timeout: 15000 })
    result.revocation = await page.evaluate(() => window.__g1)

    // E. Reconnect after revocation, with a fresh token, is denied.
    result.reconnect = await page.evaluate(async ({ oneNext, sid }) => {
      const v = await import('/src/services/voiceApi.ts')
      const items = []
      for await (const item of v.streamVoiceEvents(oneNext, sid)) items.push(item)
      return items
    }, { oneNext, sid: result.revocation.sid })

    process.stdout.write(JSON.stringify({ ok: true, result }))
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(err && err.stack || err) }))
  } finally {
    await browser.close()
  }
}

main()
