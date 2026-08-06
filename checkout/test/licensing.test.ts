import { describe, expect, it } from 'vitest';
import { issueLicense } from '../src/licensing';
import { TEST_PRIVATE_KEY_PEM, verifyTestLicense } from './fixtures';

describe('issueLicense', () => {
  it('produces a license whose signature verifies against the matching public key', async () => {
    const { licenseKey } = await issueLicense(TEST_PRIVATE_KEY_PEM, {
      licensee: 'The Smith Family',
      tier: 'core',
      seats: 10,
    });
    expect(await verifyTestLicense(licenseKey)).toBe(true);
  });

  it('a tampered payload fails verification', async () => {
    const { licenseKey } = await issueLicense(TEST_PRIVATE_KEY_PEM, {
      licensee: 'The Smith Family',
      tier: 'core',
      seats: 10,
    });
    const [payloadPart, sigPart] = licenseKey.split('.');
    const tamperedPayload = payloadPart.slice(0, -2) + (payloadPart.slice(-2) === 'AA' ? 'BB' : 'AA');
    expect(await verifyTestLicense(`${tamperedPayload}.${sigPart}`)).toBe(false);
  });

  it('perpetual license (no expiresInDays) has expires: null', async () => {
    const { payload } = await issueLicense(TEST_PRIVATE_KEY_PEM, {
      licensee: 'X',
      tier: 'core',
      seats: 10,
    });
    expect(payload.expires).toBeNull();
  });

  it('trial license sets expires to today + expiresInDays', async () => {
    const { payload } = await issueLicense(TEST_PRIVATE_KEY_PEM, {
      licensee: 'X',
      tier: 'trial',
      seats: 10,
      expiresInDays: 21,
    });
    expect(payload.expires).not.toBeNull();
    const expiresDate = new Date(payload.expires as string);
    const expectedDate = new Date();
    expectedDate.setUTCDate(expectedDate.getUTCDate() + 21);
    // Allow a day of slack for test-run timing across a UTC midnight boundary.
    const diffDays = Math.abs((expiresDate.getTime() - expectedDate.getTime()) / 86_400_000);
    expect(diffDays).toBeLessThan(1.5);
  });

  it('payload fields match the shape core/licensing.py expects', async () => {
    const { payload } = await issueLicense(TEST_PRIVATE_KEY_PEM, {
      licensee: 'The Smith Family',
      tier: 'coop',
      seats: 40,
    });
    expect(payload.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(payload.licensee).toBe('The Smith Family');
    expect(payload.tier).toBe('coop');
    expect(payload.seats).toBe(40);
    expect(payload.issued).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('each call mints a unique license id', async () => {
    const a = await issueLicense(TEST_PRIVATE_KEY_PEM, { licensee: 'X', tier: 'core', seats: 10 });
    const b = await issueLicense(TEST_PRIVATE_KEY_PEM, { licensee: 'X', tier: 'core', seats: 10 });
    expect(a.payload.id).not.toBe(b.payload.id);
  });
});
