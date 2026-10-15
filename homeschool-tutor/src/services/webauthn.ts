// Thin browser-native WebAuthn helpers — no external library. Converts the
// backend's base64url-encoded JSON options into the ArrayBuffers
// navigator.credentials.create()/get() expect, and serializes the resulting
// PublicKeyCredential back into the same base64url JSON shape the backend's
// py_webauthn library parses (id, rawId, type, response.{...}).

function bufferToBase64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let str = ''
  for (const b of bytes) str += String.fromCharCode(b)
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function base64urlToBuffer(b64url: string): ArrayBuffer {
  const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/')
  const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
  const str = atob(padded)
  const bytes = new Uint8Array(str.length)
  for (let i = 0; i < str.length; i++) bytes[i] = str.charCodeAt(i)
  return bytes.buffer
}

export function webauthnSupported(): boolean {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential
}

/** Enrolling a new security key. `options` is the JSON from POST /mfa/webauthn/register/options. */
export async function registerSecurityKey(options: any): Promise<object> {
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...options,
    challenge: base64urlToBuffer(options.challenge),
    user: { ...options.user, id: base64urlToBuffer(options.user.id) },
    excludeCredentials: (options.excludeCredentials ?? []).map((c: any) => ({ ...c, id: base64urlToBuffer(c.id) })),
  }
  const credential = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential
  const response = credential.response as AuthenticatorAttestationResponse
  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      attestationObject: bufferToBase64url(response.attestationObject),
    },
  }
}

/** Completing a login with an enrolled key. `options` is the JSON from POST /mfa/webauthn/authenticate/options. */
export async function authenticateSecurityKey(options: any): Promise<object> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...options,
    challenge: base64urlToBuffer(options.challenge),
    allowCredentials: (options.allowCredentials ?? []).map((c: any) => ({ ...c, id: base64urlToBuffer(c.id) })),
  }
  const credential = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential
  const response = credential.response as AuthenticatorAssertionResponse
  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      authenticatorData: bufferToBase64url(response.authenticatorData),
      signature: bufferToBase64url(response.signature),
      ...(response.userHandle ? { userHandle: bufferToBase64url(response.userHandle) } : {}),
    },
  }
}

/**
 * A non-identifying usability hint. Only the native browser can decide which
 * authenticator can complete an actual WebAuthn ceremony. Never interpret
 * this probe as enrollment, device biometric status, or permission to bypass UV.
 */
export type PasskeyReadiness = 'unsupported' | 'platform-available' | 'browser-options'
export async function detectPasskeyReadiness(): Promise<PasskeyReadiness> {
  if (!webauthnSupported()) return 'unsupported'
  try {
    const supported = await window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable?.()
    if (supported === true) return 'platform-available'
  } catch {
    // An older or restricted browser can still support roaming authenticators.
  }
  return 'browser-options'
}

export function passkeyGuidance(readiness: PasskeyReadiness): string {
  switch (readiness) {
    case 'platform-available':
      return 'This browser reports a built-in passkey option. Use Touch ID or another method offered by the browser.'
    case 'browser-options':
      return 'This device may not have built-in Touch ID. In the browser passkey prompt, choose Other Options for a compatible phone or security key if supported.'
    default:
      return 'This browser does not support Bede passkey sign-in. Use a compatible browser or another authorized device. Password-only educator access is not available.'
  }
}
