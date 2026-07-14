import { describe, expect, it } from 'vitest';
import {
  recordLicense, findByInvoiceNumber, mostRecentByEmail, hasRecentTrial, recentLicenses,
  recordPendingCheckout, findPendingCheckoutByInvoiceNumber, findPendingCheckoutByToken,
} from '../src/ledger';
import type { LicensePayload } from '../src/licensing';
import { FakeD1Database } from './fixtures';

function payload(overrides: Partial<LicensePayload> = {}): LicensePayload {
  return {
    id: 'lic-1', licensee: 'The Smith Family', tier: 'core', seats: 10,
    issued: '2026-07-14', expires: null, ...overrides,
  };
}

describe('ledger — licenses', () => {
  it('records and finds a license by Helcim invoice number', async () => {
    const db = new FakeD1Database();
    await recordLicense(db as any, 'a@b.com', 'license-key-1', payload(), 'helcim', {
      invoiceNumber: 'inv_123', transactionId: 'txn_123',
    });
    const found = await findByInvoiceNumber(db as any, 'inv_123');
    expect(found?.licensee_email).toBe('a@b.com');
    expect(found?.license_key).toBe('license-key-1');
  });

  it('returns null for an unknown invoice number', async () => {
    const db = new FakeD1Database();
    const found = await findByInvoiceNumber(db as any, 'inv_does_not_exist');
    expect(found).toBeNull();
  });

  it('rejects a second license write for the same invoice number (webhook idempotency)', async () => {
    const db = new FakeD1Database();
    await recordLicense(db as any, 'a@b.com', 'key-1', payload({ id: 'lic-1' }), 'helcim', {
      invoiceNumber: 'inv_123',
    });
    await expect(
      recordLicense(db as any, 'a@b.com', 'key-2', payload({ id: 'lic-2' }), 'helcim', {
        invoiceNumber: 'inv_123',
      }),
    ).rejects.toThrow(/UNIQUE constraint/);
  });

  it('mostRecentByEmail returns the newest of several licenses', async () => {
    const db = new FakeD1Database();
    db.rows.push(
      { id: 'a', licensee_email: 'x@y.com', created_at: '2026-01-01T00:00:00Z', license_key: 'old' } as any,
      { id: 'b', licensee_email: 'x@y.com', created_at: '2026-06-01T00:00:00Z', license_key: 'new' } as any,
    );
    const found = await mostRecentByEmail(db as any, 'x@y.com');
    expect(found?.license_key).toBe('new');
  });

  it('hasRecentTrial is true within the window and false outside it', async () => {
    const db = new FakeD1Database();
    const recent = new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString();
    const old = new Date(Date.now() - 200 * 24 * 60 * 60 * 1000).toISOString();
    db.rows.push({ licensee_email: 'recent@x.com', source: 'trial', created_at: recent } as any);
    db.rows.push({ licensee_email: 'old@x.com', source: 'trial', created_at: old } as any);

    expect(await hasRecentTrial(db as any, 'recent@x.com', 90)).toBe(true);
    expect(await hasRecentTrial(db as any, 'old@x.com', 90)).toBe(false);
    expect(await hasRecentTrial(db as any, 'never-seen@x.com', 90)).toBe(false);
  });

  it('hasRecentTrial ignores non-trial licenses for the same email', async () => {
    const db = new FakeD1Database();
    const recent = new Date().toISOString();
    db.rows.push({ licensee_email: 'paid@x.com', source: 'helcim', created_at: recent } as any);
    expect(await hasRecentTrial(db as any, 'paid@x.com', 90)).toBe(false);
  });

  it('recentLicenses respects the limit and newest-first order', async () => {
    const db = new FakeD1Database();
    for (let i = 0; i < 5; i++) {
      db.rows.push({ id: `id-${i}`, created_at: `2026-01-0${i + 1}T00:00:00Z` } as any);
    }
    const rows = await recentLicenses(db as any, 3);
    expect(rows).toHaveLength(3);
    expect(rows[0].id).toBe('id-4');
  });
});

describe('ledger — pending checkouts', () => {
  it('records and finds a pending checkout by invoice number', async () => {
    const db = new FakeD1Database();
    await recordPendingCheckout(db as any, {
      checkoutToken: 'tok_1', invoiceNumber: 'inv_1', email: 'a@b.com',
      licenseeName: 'The Smiths', tier: 'core', seats: 10,
    });
    const found = await findPendingCheckoutByInvoiceNumber(db as any, 'inv_1');
    expect(found?.licensee_email).toBe('a@b.com');
    expect(found?.tier).toBe('core');
  });

  it('finds a pending checkout by checkout token', async () => {
    const db = new FakeD1Database();
    await recordPendingCheckout(db as any, {
      checkoutToken: 'tok_1', invoiceNumber: 'inv_1', email: 'a@b.com',
      licenseeName: 'The Smiths', tier: 'coop', seats: 40,
    });
    const found = await findPendingCheckoutByToken(db as any, 'tok_1');
    expect(found?.invoice_number).toBe('inv_1');
    expect(found?.seats).toBe(40);
  });

  it('returns null for an unknown invoice number or token', async () => {
    const db = new FakeD1Database();
    expect(await findPendingCheckoutByInvoiceNumber(db as any, 'nope')).toBeNull();
    expect(await findPendingCheckoutByToken(db as any, 'nope')).toBeNull();
  });
});
