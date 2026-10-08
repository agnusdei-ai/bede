import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'))
const iosVersion: string = lock.packages['node_modules/@capacitor/ios'].version

describe('Capacitor iOS security patch', () => {
  it('locks a version patched for GHSA-rvm3-566m-v7fv', () => {
    const floor = [8, 4, 3]
    const parts = iosVersion.split('.').map(Number)
    expect(parts).toHaveLength(3)
    expect(parts.every(Number.isInteger)).toBe(true)
    const difference = parts.map((part, i) => part - floor[i]).find((diff) => diff !== 0) ?? 0
    expect(difference).toBeGreaterThanOrEqual(0)
  })

  it('uses the patched npm version in the actual native app', () => {
    const swift = readFileSync(join(root, 'ios/App/CapApp-SPM/Package.swift'), 'utf8')
    const nativeVersion = swift.match(/capacitor-swift-pm\.git", exact: "([^"]+)"/)?.[1]
    expect(nativeVersion).toBe(iosVersion)
  })
})
