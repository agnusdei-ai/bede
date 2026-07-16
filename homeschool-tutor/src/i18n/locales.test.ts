import { describe, expect, it } from 'vitest'
import en from './locales/en.json'
import es from './locales/es.json'

// Regression guard for silent localization gaps: a key added to en.json and
// forgotten in es.json wouldn't error at runtime — i18next just falls back
// to the key string itself, which a translated deployment would ship
// without anyone noticing until a parent reported garbled UI text.

function flattenKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'object' && value !== null
      ? flattenKeys(value as Record<string, unknown>, path)
      : [path]
  })
}

function interpolationVars(value: string): string[] {
  return [...value.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort()
}

describe('locale resource parity (en vs es)', () => {
  it('has exactly the same keys in both locales', () => {
    const enKeys = flattenKeys(en).sort()
    const esKeys = flattenKeys(es).sort()
    expect(esKeys).toEqual(enKeys)
  })

  it('has no empty translated values', () => {
    const esKeys = flattenKeys(es)
    for (const key of esKeys) {
      const value = key.split('.').reduce<any>((o, k) => o[k], es)
      expect(value.trim().length, `es.json key "${key}" is empty`).toBeGreaterThan(0)
    }
  })

  it('uses the same {{interpolation}} variables in both locales, per key', () => {
    const enKeys = flattenKeys(en)
    for (const key of enKeys) {
      const enValue = key.split('.').reduce<any>((o, k) => o[k], en)
      const esValue = key.split('.').reduce<any>((o, k) => o[k], es)
      expect(interpolationVars(esValue), `key "${key}"`).toEqual(interpolationVars(enValue))
    }
  })
})
