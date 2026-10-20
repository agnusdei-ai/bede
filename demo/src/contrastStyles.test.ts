import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '../..')
const siteCss = readFileSync(join(root, 'site/assets/streamlined.css'), 'utf8')
const demoCss = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'index.css'), 'utf8')

function luminance(hex: string) {
  const channels = hex.match(/[a-f\d]{2}/gi)!.map((channel) => parseInt(channel, 16) / 255)
  const linear = channels.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  )
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
}

function contrast(foreground: string, background: string) {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
  return (values[0] + 0.05) / (values[1] + 0.05)
}

describe('marketing and demo contrast treatments', () => {
  it('keeps the site ink, muted, gilt, and hero text pairs above AA', () => {
    expect(contrast('#1b2b3b', '#fbf8f1')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#394957', '#fbf8f1')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#705429', '#fbf8f1')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#fbf8f1', '#1b2b3b')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#e3c982', '#1b2b3b')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#1b2b3b', '#c4a45f')).toBeGreaterThanOrEqual(4.5)
    expect(siteCss).toContain('color: #d6d8d7;')
    expect(siteCss).toContain('opacity: 1;')
  })

  it('uses readable note and input colors in the demo', () => {
    expect(contrast('#202b38', '#faf6ec')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#59656b', '#faf6ec')).toBeGreaterThanOrEqual(4.5)
    expect(contrast('#788577', '#ffffff')).toBeGreaterThanOrEqual(3)
    expect(demoCss).toContain('.text-gray-400,')
    expect(demoCss).toContain('color: #59656b;')
    expect(demoCss).toContain('color-scheme: light;')
  })

  it('retains visible keyboard focus and practical touch target sizing', () => {
    expect(siteCss).toContain('outline: 3px solid #8c6326;')
    expect(siteCss).toContain('min-height: 44px;')
    expect(demoCss).toContain(':focus-visible {')
    expect(demoCss).toContain('outline: 3px solid #8c6326 !important;')
    expect(demoCss).toContain('button {\n  min-height: 44px;')
  })
})
