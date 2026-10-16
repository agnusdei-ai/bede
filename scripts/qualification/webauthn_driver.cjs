#!/usr/bin/env node
/**
 * Chromium + CDP virtual WebAuthn authenticator, driven over JSON lines.
 *
 * The qualification harness (Python) talks to this process on stdin/stdout,
 * one JSON object per line each way. Every passkey ceremony therefore runs
 * a REAL navigator.credentials.create()/get() in a real browser page whose
 * origin is the application's own WEBAUTHN_ORIGIN, against an authenticator
 * Chromium emulates (CDP WebAuthn.addVirtualAuthenticator: CTAP2, internal
 * transport, resident keys, user verification satisfied). Nothing about the
 * server's verification is bypassed: it receives an ordinary attestation or
 * assertion and checks challenge, origin, RP ID, signature and counter.
 *
 * One browser CONTEXT per principal, each with its own authenticator, so
 * Synthetic Teacher One's credential can never be offered for Teacher Two.
 *
 * Ops:  {op:"context", ctx}                         -> {ok, userAgent}
 *       {op:"create",  ctx, publicKey}              -> {ok, credential}
 *       {op:"get",     ctx, publicKey}              -> {ok, credential}
 *       {op:"fetch",   ctx, method, path, headers, body} -> {ok, status, text}
 *       {op:"close"}
 *
 * Usage: node webauthn_driver.cjs <origin>
 * Resolves `playwright` from the repo's node_modules or NODE_PATH.
 */
'use strict';
const readline = require('node:readline');
const { chromium } = require('playwright');

const ORIGIN = process.argv[2];
if (!ORIGIN) {
  process.stderr.write('usage: webauthn_driver.cjs <origin>\n');
  process.exit(2);
}

let browser;
const contexts = new Map();

async function ensureBrowser() {
  if (!browser) browser = await chromium.launch({ headless: true });
  return browser;
}

async function openContext(name) {
  if (contexts.has(name)) return contexts.get(name);
  const b = await ensureBrowser();
  const context = await b.newContext();
  const page = await context.newPage();
  // Any same-origin document gives the page the RP's origin.
  await page.goto(`${ORIGIN}/health`);
  const cdp = await context.newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2', transport: 'internal', hasResidentKey: true,
      hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true,
    },
  });
  const userAgent = await page.evaluate(() => navigator.userAgent);
  const entry = { context, page, cdp, authenticatorId, userAgent };
  contexts.set(name, entry);
  return entry;
}

// Runs in the page: base64url <-> ArrayBuffer conversion around the real API.
const IN_PAGE = `
  window.__b64 = {
    dec(s) { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '=';
             return Uint8Array.from(atob(s), c => c.charCodeAt(0)).buffer; },
    enc(buf) { const b = new Uint8Array(buf); let s = ''; for (const x of b) s += String.fromCharCode(x);
               return btoa(s).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, ''); },
  };`;

async function ceremony(entry, kind, publicKey) {
  await entry.page.evaluate(IN_PAGE);
  return entry.page.evaluate(async ({ kind, pk }) => {
    const B = window.__b64;
    const opts = JSON.parse(JSON.stringify(pk));
    opts.challenge = B.dec(opts.challenge);
    if (kind === 'create') {
      opts.user.id = B.dec(opts.user.id);
      (opts.excludeCredentials || []).forEach(c => { c.id = B.dec(c.id); });
      const cred = await navigator.credentials.create({ publicKey: opts });
      return {
        id: cred.id, rawId: B.enc(cred.rawId), type: cred.type,
        authenticatorAttachment: cred.authenticatorAttachment || undefined,
        clientExtensionResults: cred.getClientExtensionResults(),
        response: {
          clientDataJSON: B.enc(cred.response.clientDataJSON),
          attestationObject: B.enc(cred.response.attestationObject),
          transports: cred.response.getTransports ? cred.response.getTransports() : [],
        },
      };
    }
    (opts.allowCredentials || []).forEach(c => { c.id = B.dec(c.id); });
    const cred = await navigator.credentials.get({ publicKey: opts });
    return {
      id: cred.id, rawId: B.enc(cred.rawId), type: cred.type,
      authenticatorAttachment: cred.authenticatorAttachment || undefined,
      clientExtensionResults: cred.getClientExtensionResults(),
      response: {
        clientDataJSON: B.enc(cred.response.clientDataJSON),
        authenticatorData: B.enc(cred.response.authenticatorData),
        signature: B.enc(cred.response.signature),
        userHandle: cred.response.userHandle ? B.enc(cred.response.userHandle) : null,
      },
    };
  }, { kind, pk: publicKey });
}

async function pageFetch(entry, msg) {
  return entry.page.evaluate(async ({ method, path, headers, body }) => {
    const res = await fetch(path, {
      method, headers: headers || {}, body: body == null ? undefined : body,
      credentials: 'same-origin',
    });
    return { status: res.status, text: await res.text() };
  }, msg);
}

async function handle(msg) {
  switch (msg.op) {
    case 'context': {
      const e = await openContext(msg.ctx);
      return { userAgent: e.userAgent };
    }
    case 'create':
    case 'get': {
      const e = await openContext(msg.ctx);
      return { credential: await ceremony(e, msg.op, msg.publicKey) };
    }
    case 'fetch': {
      const e = await openContext(msg.ctx);
      return pageFetch(e, msg);
    }
    case 'close':
      if (browser) await browser.close();
      return { closed: true };
    default:
      throw new Error(`unknown op ${msg.op}`);
  }
}

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', async (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: 'bad json' }) + '\n');
    return;
  }
  try {
    const out = await handle(msg);
    process.stdout.write(JSON.stringify({ ok: true, id: msg.id, ...out }) + '\n');
    if (msg.op === 'close') process.exit(0);
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, id: msg.id, error: String(e && e.message || e) }) + '\n');
  }
});
