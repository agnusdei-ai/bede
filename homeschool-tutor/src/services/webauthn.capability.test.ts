import { afterEach, describe, expect, it, vi } from 'vitest'
import { detectPasskeyReadiness, passkeyGuidance } from './webauthn'

afterEach(() => { vi.unstubAllGlobals() })

describe('passkey UX on old and new workstations', () => {
  it('uses a built-in platform authenticator when the browser reports one', async () => {
    vi.stubGlobal('PublicKeyCredential', {
      isUserVerifyingPlatformAuthenticatorAvailable: vi.fn().mockResolvedValue(true),
    })
    expect(await detectPasskeyReadiness()).toBe('platform-available')
    expect(passkeyGuidance('platform-available')).toContain('Touch ID')
  })

  it('offers a supported phone or security key on an older Mac without platform authenticator', async () => {
    vi.stubGlobal('PublicKeyCredential', {
      isUserVerifyingPlatformAuthenticatorAvailable: vi.fn().mockResolvedValue(false),
    })
    expect(await detectPasskeyReadiness()).toBe('browser-options')
    expect(passkeyGuidance('browser-options')).toContain('Other Options')
  })

  it('does not claim there is native Touch ID when the browser does not expose a platform probe', async () => {
    vi.stubGlobal('PublicKeyCredential', {})
    expect(await detectPasskeyReadiness()).toBe('browser-options')
  })

  it('does not permit a password-only educator login when WebAuthn is absent', async () => {
    vi.stubGlobal('PublicKeyCredential', undefined)
    expect(await detectPasskeyReadiness()).toBe('unsupported')
    expect(passkeyGuidance('unsupported')).toContain('Password-only educator access is not available')
  })

  it('does not mistake a rejected platform probe for proof that all passkeys fail', async () => {
    vi.stubGlobal('PublicKeyCredential', {
      isUserVerifyingPlatformAuthenticatorAvailable: vi.fn().mockRejectedValue(new Error('not available')),
    })
    expect(await detectPasskeyReadiness()).toBe('browser-options')
  })
})
