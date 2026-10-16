#!/usr/bin/env python3
"""Owner-run, 10-20 minute real-device check: one teacher, one Touch ID passkey.

What this is: the small interactive companion to the automated qualification
matrix. The matrix proves the server's behaviour with a Chromium *virtual*
authenticator. It cannot prove that a real Mac, a real Safari and a real
Touch ID prompt work against the same routes. This script lets a person do
that part and records, mechanically, what the server answered.

What you provide: the Touch ID taps, the button presses in one browser page,
and a yes/no (plus an optional short note) for each item. Everything else is
automatic: it starts the real stack on synthetic data, invites one synthetic
teacher, grants and revokes the roster through the real admin routes, records
every response status, and decides pass or fail from those records.

What it is NOT: not the G3 Mac package check, not Engineering Complete, not a
Pilot GO, and not a test of a real teacher, learner or mailbox. It uses the
same loopback AI stub and loopback mail sink as the automated harness. It
never writes a token, ticket, passkey or response body to disk: the result
file holds only route templates, status codes, short body hashes and counts.

    export QUAL_DB_ADMIN_URL=postgresql://postgres@127.0.0.1:5432/postgres
    python scripts/qualification/mac_check.py [--browser safari|chrome|none]

Exit status: 0 every item passed, 1 at least one item failed or you marked it
wrong, 2 the check could not complete.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import ssl
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Environment first: qualconfig and the preflight read it at import time.
PROXY_PORT = 8765          # the browser-facing origin (also WEBAUTHN_ORIGIN)
BACKEND_PORT = 8768        # uvicorn, plain http on loopback, behind the proxy
ORIGIN = f"https://localhost:{PROXY_PORT}"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = Path(os.environ.get("QUAL_OUT_DIR", str(REPO / "mac-check-out"))).resolve()
os.environ.setdefault("QUAL_OUT_DIR", str(OUT))
if not os.environ.get("QUAL_CANDIDATE_SHA"):
    # The preflight pins the run to the checked-out commit; a hand run uses HEAD.
    os.environ["QUAL_CANDIDATE_SHA"] = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
os.environ["QUAL_TLS"] = "false"
os.environ["QUAL_API_PORT"] = str(BACKEND_PORT)
os.environ["QUAL_API_ORIGIN"] = ORIGIN

sys.path.insert(0, str(HERE))
import qualconfig as cfg  # noqa: E402
from harness import Api, Driver, HarnessError, Stack, make_tls  # noqa: E402

TEACHER = cfg.TEACHER_USERNAMES["teacher_one"]
TEACHER_EMAIL = f"{TEACHER}@{cfg.INSTITUTION_EMAIL_DOMAIN}"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RECORDED_PREFIXES = ("/auth/educator-passkey/", "/pilot/me/")


# ── What the proxy remembers ──────────────────────────────────────────────

class Recorder:
    """Status codes, route templates, body hashes and counts. Never a body."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[dict] = []
        self.observations: dict[str, dict] = {}
        self.marks: list[str] = []

    def mark(self, label: str) -> None:
        with self.lock:
            self.marks.append(label)
            self.calls.append({"mark": label, "t": round(time.time(), 1)})

    def call(self, method: str, path: str, status: int, body: bytes) -> None:
        if not path.startswith(RECORDED_PREFIXES):
            return
        entry = {"t": round(time.time(), 1), "method": method,
                 "route": UUID.sub("{id}", path.split("?")[0]), "status": status,
                 "body_sha8": hashlib.sha256(body).hexdigest()[:8],
                 "phase": self.marks[-1] if self.marks else "start"}
        if path.rstrip("/") == "/pilot/me/learners" and status == 200:
            try:
                rows = json.loads(body)
                entry["count"] = len(rows)
                entry["names"] = sorted({r.get("display_name", "") for r in rows})
            except (ValueError, AttributeError):
                pass
        with self.lock:
            self.calls.append(entry)

    def where(self, phase: str | None = None, **match) -> list[dict]:
        with self.lock:
            rows = [c for c in self.calls if "route" in c]
        return [c for c in rows if (phase is None or c["phase"] == phase)
                and all(c.get(k) == v for k, v in match.items())]


REC = Recorder()
FIXTURE: dict = {}


# ── The one page the browser needs (same origin as the API, so WebAuthn works) ──

PAGE = r"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>Bede real-device check</title>
<style>body{font:16px/1.45 system-ui;max-width:42rem;margin:2rem auto;padding:0 1rem}
button{font:inherit;padding:.5rem .9rem;margin:.2rem .2rem .2rem 0}
pre{background:#f3f3f3;padding:.6rem;white-space:pre-wrap}.ok{color:#0a6b2d}.bad{color:#a11}
.note{color:#555}input[type=text]{width:60%}</style>
<h1>Bede real-device check</h1>
<p class=note>Synthetic data only. Do not type any real name, address or student information into this page.</p>
<ol>
<li><b>Enroll</b> a passkey for the synthetic teacher (Touch ID will prompt).
 <br><button id=enroll>Enroll passkey</button>
 <button id=again>Try this invitation again</button></li>
<li><b>Sign in</b> with that passkey. <br><button id=login>Sign in with Touch ID</button></li>
<li><b>Read</b> what this teacher can see.
 <br><button id=list>Check my learners</button>
 <button id=one>Open granted learner</button>
 <button id=other>Open the other campus's learner</button>
 <button id=bogus>Open an unknown id</button></li>
<li><b>After revocation</b> (the terminal will tell you when).
 <br><button id=list2>Check again</button>
 <button id=relogin>Sign in again, then check</button></li>
</ol>
<pre id=log>Ready.</pre>
<h3>Your observations</h3>
<p class=note>For each, does the page match what the terminal told you to expect? A short note is optional.</p>
<div id=obs></div><button id=send>Send my observations</button> <span id=sent></span>
<script>
const $=id=>document.getElementById(id), log=m=>{$('log').textContent+='\n'+m};
const h=new URLSearchParams(location.hash.slice(1));
const ticket={ticket_id:h.get('ticket')||'',ticket_token:h.get('token')||''};
if(h.get('ticket')) history.replaceState(null,'',location.pathname);  // the link is single-use; do not leave it in history
let token='', fixture={};
fetch('/__fixture').then(r=>r.json()).then(f=>fixture=f);
const U='synthetic-teacher-one';
const dec=s=>{s=s.replace(/-/g,'+').replace(/_/g,'/');while(s.length%4)s+='=';return Uint8Array.from(atob(s),c=>c.charCodeAt(0)).buffer};
const enc=b=>{let s='';for(const x of new Uint8Array(b))s+=String.fromCharCode(x);return btoa(s).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'')};
async function api(method,path,body,auth){
  const r=await fetch(path,{method,headers:Object.assign({'Content-Type':'application/json'},auth&&token?{Authorization:'Bearer '+token}:{}),
    body:body?JSON.stringify(body):undefined});
  let t=await r.text(); return {status:r.status,text:t};
}
function show(label,r){log(label+' -> HTTP '+r.status)}
async function create(pk){
  const o=JSON.parse(JSON.stringify(pk)); o.challenge=dec(o.challenge); o.user.id=dec(o.user.id);
  (o.excludeCredentials||[]).forEach(c=>c.id=dec(c.id));
  const c=await navigator.credentials.create({publicKey:o});
  return {id:c.id,rawId:enc(c.rawId),type:c.type,authenticatorAttachment:c.authenticatorAttachment||undefined,
    clientExtensionResults:c.getClientExtensionResults(),
    response:{clientDataJSON:enc(c.response.clientDataJSON),attestationObject:enc(c.response.attestationObject),
      transports:c.response.getTransports?c.response.getTransports():[]}};
}
async function get(pk){
  const o=JSON.parse(JSON.stringify(pk)); o.challenge=dec(o.challenge);
  (o.allowCredentials||[]).forEach(c=>c.id=dec(c.id));
  const c=await navigator.credentials.get({publicKey:o});
  return {id:c.id,rawId:enc(c.rawId),type:c.type,authenticatorAttachment:c.authenticatorAttachment||undefined,
    clientExtensionResults:c.getClientExtensionResults(),
    response:{clientDataJSON:enc(c.response.clientDataJSON),authenticatorData:enc(c.response.authenticatorData),
      signature:enc(c.response.signature),userHandle:c.response.userHandle?enc(c.response.userHandle):null}};
}
let usedTicket=null;
$('enroll').onclick=async()=>{try{
  usedTicket=Object.assign({},ticket);
  const o=await api('POST','/auth/educator-passkey/register/options',ticket); show('register options',o);
  if(o.status!==200)return; const j=JSON.parse(o.text);
  const cred=await create(j.options);
  const v=await api('POST','/auth/educator-passkey/register/verify',Object.assign({},ticket,{ceremony_id:j.ceremony_id,credential:cred}));
  show('register verify',v);
}catch(e){log('enrollment stopped: '+e.name)}};
$('again').onclick=async()=>{const o=await api('POST','/auth/educator-passkey/register/options',usedTicket||ticket);show('same invitation again',o)};
async function signin(){
  const o=await api('POST','/auth/educator-passkey/login/options',{username:U}); show('login options',o);
  if(o.status!==200)return false; const j=JSON.parse(o.text);
  let a; try{a=await get(j.options)}catch(e){log('sign-in stopped: '+e.name);return false}
  const v=await api('POST','/auth/educator-passkey/login/verify',{username:U,ceremony_id:j.ceremony_id,credential:a});
  show('login verify',v); if(v.status===200){token=JSON.parse(v.text).access_token;return true} return false;
}
$('login').onclick=signin;
const list=async()=>{const r=await api('GET','/pilot/me/learners',null,true);
  let n='?'; try{n=JSON.parse(r.text).length}catch(e){} show('my learners (count '+n+')',r)};
$('list').onclick=list; $('list2').onclick=list;
$('relogin').onclick=async()=>{await signin(); await list()};
$('one').onclick=async()=>show('granted learner',await api('GET','/pilot/me/learners/'+fixture.learner_one,null,true));
$('other').onclick=async()=>show("other campus's learner",await api('GET','/pilot/me/learners/'+fixture.learner_two,null,true));
$('bogus').onclick=async()=>show('unknown id',await api('GET','/pilot/me/learners/'+fixture.unknown,null,true));
const ITEMS=[['enroll','Touch ID enrollment and sign-in worked'],['reuse','Reusing the invitation was refused'],
 ['empty','Before the grant I saw no learners'],['granted','After the grant I saw exactly one learner'],
 ['isolation','The other campus and the unknown id looked identical (not found)'],
 ['revoked','After revocation I could not read, even after signing in again']];
$('obs').innerHTML=ITEMS.map(([k,t])=>`<div><label>${t}: <select id=o_${k}><option value="">(skip)</option><option>yes</option><option>no</option></select></label> <input type=text id=n_${k} maxlength=200 placeholder="optional note"></div>`).join('');
$('send').onclick=async()=>{const o={};for(const [k] of ITEMS)o[k]={answer:$('o_'+k).value,note:$('n_'+k).value};
  await fetch('/__observe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});$('sent').textContent='sent';};
</script>"""


# ── TLS front proxy: serves the page, forwards the API, records outcomes ───

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    backend: "httpx.Client"  # set below

    def log_message(self, *a) -> None:  # silence; the Recorder is the log
        pass

    def _send(self, status: int, body: bytes, ctype: str = "application/json", extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self) -> None:
        self._proxy("GET")

    def do_POST(self) -> None:
        self._proxy("POST")

    def do_DELETE(self) -> None:
        self._proxy("DELETE")

    def _proxy(self, method: str) -> None:
        path = self.path
        body = self._body()
        if method == "GET" and path.split("?")[0] in ("/educator-enroll", "/mac-check", "/"):
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if path == "/__fixture":
            return self._send(200, json.dumps(FIXTURE).encode())
        if path == "/__observe" and method == "POST":
            try:
                data = json.loads(body)
                for k, v in data.items():
                    REC.observations[str(k)[:20]] = {
                        "answer": str(v.get("answer", ""))[:5],
                        "note": str(v.get("note", ""))[:200]}
            except (ValueError, AttributeError):
                return self._send(400, b"{}")
            return self._send(200, b"{}")
        skip = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in skip}
        try:
            r = self.backend.request(method, path, content=body or None, headers=headers)
        except Exception:  # noqa: BLE001
            return self._send(502, b'{"detail":"backend unreachable"}')
        REC.call(method, path, r.status_code, r.content)
        extra = {k: v for k, v in r.headers.items()
                 if k.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}}
        self._send(r.status_code, r.content, r.headers.get("content-type", "application/json"), extra)


def start_proxy(tls: dict):
    import httpx
    Handler.backend = httpx.Client(base_url=f"http://127.0.0.1:{BACKEND_PORT}", timeout=30)
    srv = ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tls["cert"], tls["key"])
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ── The application's environment: synthetic, loopback-only, production off ──

def build_env(db_url: str, sink_key: str) -> dict:
    return {
        **os.environ,
        "PRODUCTION": "false", "DISABLE_API_DOCS": "true", "EDUCATOR_PILOT_ENABLED": "true",
        "ELEVATION_ENFORCED": "true", "MCP_EXTERNAL_ENABLED": "false", "LOCUTO_IPC_ENABLED": "false",
        "EDUCATOR_INSTITUTION_EMAIL_DOMAIN": cfg.INSTITUTION_EMAIL_DOMAIN,
        "WEBAUTHN_RP_ID": "localhost", "WEBAUTHN_ORIGIN": ORIGIN, "CORS_ORIGINS": ORIGIN,
        "RESEND_API_BASE_URL": f"http://{cfg.MAIL_SINK_HOST}:{cfg.MAIL_SINK_PORT}",
        "RESEND_API_KEY": sink_key, "RESEND_FROM_ADDRESS": f"bede@{cfg.INSTITUTION_EMAIL_DOMAIN}",
        "LOCAL_LLM_BASE_URL": f"http://{cfg.STUB_HOST}:{cfg.STUB_PORT}/v1",
        "LOCAL_LLM_MODEL": "synthetic-stub", "BEDE_FORCE_ADAPTER": "local",
        "RATE_LIMIT_AUTH_PER_MINUTE": "120", "RATE_LIMIT_API_PER_MINUTE": "1200",
        "CHILD_PIN": "739184", "DATABASE_URL": db_url,
        "SECRET_KEY": secrets.token_hex(32), "MASTER_SECRET": secrets.token_hex(32),
        "PARENT_PASSWORD": "synthetic-" + secrets.token_hex(16),
    }


def open_browser(url: str, which: str) -> None:
    if which == "none":
        return
    if which == "chrome" and sys.platform == "darwin":
        subprocess.run(["open", "-a", "Google Chrome", url], check=False)
    elif which == "safari" and sys.platform == "darwin":
        subprocess.run(["open", "-a", "Safari", url], check=False)
    else:
        webbrowser.open(url)


def wait_for(pred, seconds: float, what: str) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.5)
    raise HarnessError(f"timed out waiting for {what}")


def ask(msg: str) -> None:
    input(f"\n>>> {msg}\n    Press Enter here when done. ")


# ── Decide pass/fail from what the server actually answered ───────────────

def evaluate() -> dict:
    items: dict[str, dict] = {}

    def verdict(key: str, ok: bool, why: str) -> None:
        obs = REC.observations.get(key, {})
        items[key] = {"server_says": "PASS" if ok else "FAIL", "why": why,
                      "you_said": obs.get("answer") or "(skipped)", "note": obs.get("note", "")}

    reg = REC.where(route="/auth/educator-passkey/register/verify")
    login = REC.where(route="/auth/educator-passkey/login/verify")
    verdict("enroll", any(c["status"] in (200, 201) for c in reg) and any(c["status"] == 200 for c in login),
            f"register/verify {[c['status'] for c in reg]}, login/verify {[c['status'] for c in login]}")
    opts = REC.where(route="/auth/educator-passkey/register/options")
    reuse = opts[1:] if len(opts) > 1 else []
    verdict("reuse", bool(reuse) and all(400 <= c["status"] < 500 for c in reuse),
            f"later register/options {[c['status'] for c in reuse]} (expected 4xx)")
    lists = REC.where(route="/pilot/me/learners")
    pre = [c for c in lists if c["phase"] == "before_grant"]
    verdict("empty", bool(pre) and all(c.get("count") == 0 for c in pre),
            f"counts before grant {[c.get('count') for c in pre]}")
    post = [c for c in lists if c["phase"] == "after_grant"]
    verdict("granted", bool(post) and all(c.get("count") == 1 for c in post)
            and all(c.get("names") == ["Synthetic Learner"] for c in post),
            f"counts after grant {[c.get('count') for c in post]} (two same-named learners exist)")
    one = REC.where(route="/pilot/me/learners/{id}", phase="after_grant")
    by_status = {}
    for c in one:
        by_status.setdefault(c["status"], set()).add(c["body_sha8"])
    other_ok = [c for c in one if c["status"] == 404]
    verdict("isolation", any(c["status"] == 200 for c in one) and len(other_ok) >= 2
            and len({c["body_sha8"] for c in other_ok}) == 1,
            f"statuses {sorted(by_status)}; not-found responses identical: "
            f"{len({c['body_sha8'] for c in other_ok}) == 1 if other_ok else 'none seen'}")
    after = [c for c in REC.where(phase="after_revoke")
             if c["route"] in ("/pilot/me/learners", "/pilot/me/learners/{id}")]
    refused = [c for c in after if c["status"] != 200 or c.get("count") == 0]
    verdict("revoked", bool(after) and len(refused) == len(after),
            f"post-revoke reads {[(c['route'].rsplit('/', 1)[-1], c['status'], c.get('count')) for c in after]}")
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", choices=("safari", "chrome", "none"), default="safari")
    args = ap.parse_args()
    admin = os.environ.get("QUAL_DB_ADMIN_URL", "")
    if not admin:
        print("QUAL_DB_ADMIN_URL is required (a local Postgres superuser URL; see docs/SYNTHETIC_QUALIFICATION.md)")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    cfg.MAIL_SINK_DIR.mkdir(parents=True, exist_ok=True)

    import db_setup
    app_pw = "synthetic-" + secrets.token_hex(12)
    dbname = "bede_mac_check"
    db_url = asyncio.run(db_setup.setup(admin, dbname, cfg.APP_DB_ROLE, app_pw, recreate=True))
    env = build_env(db_url, "synthetic-" + secrets.token_hex(12))
    os.environ.update(env)           # preflight and the app import read the process environment
    import preflight
    pre = preflight.run("pre-start", env)
    (OUT / "preflight-pre-start.json").write_text(json.dumps({"ok": pre.ok, "checks": pre.checks}, indent=2))
    if not pre.ok:
        print("Preflight failed closed; see", OUT / "preflight-pre-start.json")
        return 2

    tls = make_tls(cfg.RUN_TMP / "tls")
    stack = Stack(env=env, out=OUT)
    driver = api = None
    status = 2
    try:
        stack.start_stub()
        stack.start_sink()
        stack.start_server()
        driver = Driver(ORIGIN, OUT, tls["spki"])   # Chromium only plays the synthetic ADMIN
        proxy = start_proxy(tls)
        api = Api(stack.base, driver.user_agent("admin"), True)
        from seed import Seeder
        seeder = Seeder(api, driver, env)
        seeder.bootstrap_admin()
        seeder.seed_campuses_and_learners()
        fx = seeder.fx
        FIXTURE.update(learner_one=fx.learner["learner_one"], learner_two=fx.learner["learner_two"],
                       unknown="00000000-0000-4000-8000-000000000000")

        REC.mark("invite")
        r = api.call("POST", "/auth/educator-passkey/invite", fx.admin_token,
                     {"username": TEACHER, "institutional_email": TEACHER_EMAIL})
        if r.status_code != 202:
            raise HarnessError(f"invite -> {r.status_code}")
        from seed import _ticket_from_sink
        ticket = _ticket_from_sink(TEACHER_EMAIL)
        if ticket is None:
            raise HarnessError("no enrollment email reached the loopback mail sink")
        accounts = api.call("GET", "/educators/accounts", fx.admin_token).json()
        teacher_id = next(a["id"] for a in accounts if a["username"] == TEACHER)

        url = f"{ORIGIN}/educator-enroll#ticket={ticket[0]}&token={ticket[1]}"
        print("\n=== Bede real-device check (synthetic data only) ===")
        print("Your browser will show a certificate warning once: this run's own self-signed certificate.")
        print("Accept it for localhost. Then, in the page:\n"
              "  1. Press 'Enroll passkey' (Touch ID), then 'Try this invitation again' (should be refused).\n"
              "  2. Press 'Sign in with Touch ID'.")
        print("\nOpening:", url.split("#")[0], "(the one-time link is in the browser, not saved anywhere)")
        REC.mark("enroll")
        open_browser(url, args.browser)
        if args.browser == "none":
            print("Open this link yourself:", url)

        wait_for(lambda: any(c["status"] == 200 for c in REC.where(route="/auth/educator-passkey/login/verify")),
                 900, "your enrollment and sign-in")
        print("Recorded: enrollment and sign-in reached the server.")

        REC.mark("before_grant")
        ask("In the page press 'Check my learners'. You should see none (count 0).")
        seeder.elevate()
        c1, l1 = fx.campus["campus_one"], fx.learner["learner_one"]
        for label, path in (("membership", f"/pilot/campuses/{c1}/educators/{teacher_id}"),
                            ("grant", f"/pilot/campuses/{c1}/educators/{teacher_id}/learners/{l1}")):
            if api.call("POST", path, fx.admin_token).status_code != 204:
                raise HarnessError(f"admin {label} failed")
        REC.mark("after_grant")
        ask("Granted ONE learner. In the page press 'Check my learners' (expect 1), then "
            "'Open granted learner' (opens), 'Open the other campus's learner' and 'Open an unknown id' "
            "(both should say not found).")
        seeder.elevate()
        rv = api.call("DELETE", f"/pilot/campuses/{c1}/educators/{teacher_id}/learners/{l1}", fx.admin_token)
        if rv.status_code != 204:
            raise HarnessError(f"admin revoke -> {rv.status_code}")
        REC.mark("after_revoke")
        ask("Grant REVOKED. In the page press 'Check again', 'Open granted learner', then "
            "'Sign in again, then check'. All should be refused or empty. Then fill in the "
            "observations at the bottom and press 'Send my observations'.")

        items = evaluate()
        result = {"candidate_sha": os.environ.get("QUAL_CANDIDATE_SHA", ""),
                  "browser_requested": args.browser, "platform": sys.platform,
                  "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  "items": items,
                  "note": "Evidence only. Not the G3 Mac package check; no Engineering Complete, no GO."}
        (OUT / "mac-check-result.json").write_text(json.dumps(result, indent=2) + "\n")
        (OUT / "mac-check-calls.json").write_text(json.dumps(REC.calls, indent=2) + "\n")
        print("\n=== Result ===")
        bad = 0
        for k, v in items.items():
            flag = v["server_says"]
            if flag != "PASS" or v["you_said"] == "no":
                bad += 1
            print(f"{k:10} server: {flag:4}  you: {v['you_said']:8}  {v['why']}")
        print(f"\nWrote {OUT/'mac-check-result.json'} (statuses and counts only; no tokens or bodies).")
        status = 1 if bad else 0
        proxy.shutdown()
    except (HarnessError, KeyboardInterrupt) as exc:
        print(f"\ncheck could not complete: {exc}", file=sys.stderr)
    finally:
        if api:
            api.close()
        if driver:
            driver.close()
        stack.stop_all()
        try:
            import asyncpg

            async def drop() -> None:
                c = await asyncpg.connect(admin.replace("postgresql+asyncpg://", "postgresql://"))
                try:
                    await c.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
                finally:
                    await c.close()
            asyncio.run(drop())
            print("Scratch database dropped.")
        except Exception as exc:  # noqa: BLE001
            print(f"Could not drop scratch database {dbname}: {exc}", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main())
