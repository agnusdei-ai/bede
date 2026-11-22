// Run by hand (jsdom has no layout): start the demo with
//   VITE_DEMO_API_BASE=http://127.0.0.1:9 npx vite --port 5199 --host 127.0.0.1   (in demo/)
// then: node scripts/demo_header_layout_check.cjs
// Fails if any header button leaves the viewport or sits under the fixed
// text-size button at phone and tablet widths. Mocks every API call.
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright')
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url')
;(async () => {
  const browser = await chromium.launch()
  const tok = `${b64({ alg: 'none' })}.${b64({ exp: Math.floor(Date.now() / 1000) + 3600 })}.x`
  const cfg = { student_name: 'Sample', grade: '1', subjects: ['mathematics', 'language_arts'], session_cap_minutes: 120 }
  let bad = 0
  for (const [w, h] of [[375, 667], [390, 844], [768, 1024], [820, 1180], [1024, 768]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: true })
    const p = await ctx.newPage()
    await p.addInitScript(([t]) => sessionStorage.setItem('bede-demo-auth', JSON.stringify({ token: t, code: '123456' })), [tok])
    await p.route(/\/(auth|tutor|diagnostic|feedback|k2-practice|practice)\//, (r) =>
      r.request().url().includes('demo-config') ? r.fulfill({ json: cfg }) : r.fulfill({ status: 404, json: {} }))
    await p.goto('http://127.0.0.1:5199/')
    await p.waitForTimeout(2000)
    const res = await p.evaluate(() => {
      const t = document.querySelector('[aria-label^="Reading settings"]')?.getBoundingClientRect()
      return [...document.querySelectorAll('header button')].filter((e) => e.getBoundingClientRect().width > 0).map((e) => {
        const r = e.getBoundingClientRect()
        const over = t && r.right > t.left && r.left < t.right && r.bottom > t.top && r.top < t.bottom
        return { n: (e.getAttribute('aria-label') || e.title || '').slice(0, 30), out: r.left < 0 || r.right > innerWidth, over: !!over }
      })
    })
    for (const x of res) if (x.out || x.over) { bad++; console.log('FAIL', w, x) }
    console.log(w, 'header buttons', res.length)
    await ctx.close()
  }
  await browser.close()
  process.exit(bad ? 1 : 0)
})()
