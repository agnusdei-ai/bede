# Blind demo model experiment (temporary)

**Question:** can you tell, in an ordinary demo session, whether Bede is
running on today's production stack or on a US-developed open-weight model?

This is a perception test, not the measured evaluation `docs/DECISIONS.md`
entry 20 requires before any open model is adopted. A pass here means "hard
to tell apart in normal use". It says nothing about tool-call validity rates,
constitution adherence under adversarial input, Spanish quality, or
throughput on donated hardware. Entry 20 stays open whatever the result.

The code exists only for this experiment and is removed afterwards (see
"Removing it" below).

## What moves and what does not

| | Baseline arm | Open arm |
|---|---|---|
| Tutor turn, including every tool call | OpenAI `gpt-4.1-mini`, then Mistral/Claude on failover | `EXPERIMENT_TUTOR_MODEL` through OpenRouter, then the baseline on failover |
| Pre-turn safety classifier | Production stack | **Production stack** |
| Voice (text-to-speech, transcription) | OpenAI | OpenAI |
| Real families, any non-demo role | Never assigned an arm | Never assigned an arm |

Tool calls cannot be split off to a second, faster model. Bede makes them
inline in the tutor's own streamed reply and feeds results back to the same
model, so the tutor model is the tool-calling model. The session summary and
learner-profile synthesis are parent-only, so a demo session never reaches
them. One model slot moves, which means one model per run. To compare Gemma 4
31B against gpt-oss-20b, run the experiment twice with a different
`EXPERIMENT_TUTOR_MODEL`.

The classifier never moves because it fails open. A model that answered it
badly would silently stop self-harm screening for a child on the public demo,
and a visitor cannot perceive the classifier anyway.

Assignment is a keyed hash of the demo code (`services/model_experiment.py`):
stable for a whole session, about 50/50 across sessions, and unpredictable
without the salt.

## Before switching it on

All five are required, and the first two are what the public Privacy Notice
now promises:

1. **In OpenRouter's privacy settings, turn off providers that may train on
   prompts and require zero data retention.** The notice says the
   conversation goes to a host "configured not to retain it or train on it".
   That is true only once these settings are on.
2. **Allow only US-developed models** if the provenance criterion is the
   point of the run: Gemma (Google) and gpt-oss (OpenAI).
3. **Create a dedicated API key with a low credit limit** (a few dollars is
   plenty for 30 sessions), so a scripted visitor cannot run up a bill.
4. Check on the model's OpenRouter page that its listed providers support
   **tool calling**. A provider that drops tools would make the open arm
   show no cards, which is an easy tell and says nothing about the model.
5. Confirm the model id on OpenRouter's model page. The default here is
   `google/gemma-4-31b-it`. The OpenRouter id for Gemma 4 26B-A4B was not
   confirmed when this was written.

## Switching it on

In the Render dashboard, on `bede-demo-api`:

- `EXPERIMENT_LLM_API_KEY`: the OpenRouter key.
- `DEMO_MODEL_EXPERIMENT_SALT`: any long random string, e.g. the output of
  `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Keep it to
  yourself; anyone holding it can compute which arm a code is on.
- `EXPERIMENT_LLM_BASE_URL` and `EXPERIMENT_TUTOR_MODEL` come from
  `render.yaml`. Change the model here for the second run.

The experiment is off until both secrets are set. It refuses a base URL that
isn't `https`.

## Running it blind

1. Start a fresh demo session for each trial (log out and back in, so you get
   a new code and a fresh coin flip).
2. Use the demo the way a family would: a few turns, a subject with a picture
   or a narration, ideally one Spanish session.
3. **Before the session ends, write your guess in the feedback form**,
   either the in-session feedback button or the end-of-session survey's text
   box: `Guess: open` or `Guess: baseline`, plus one line on why.
4. The feedback email in your inbox carries the answer on its last line:
   `[model experiment arm: open]`. Only demo feedback carries it, and only
   while the experiment is on.

A failover from the open model to production is invisible to you during the
session, so an open-arm session that failed over will read as baseline. The
operator gets the usual failover alert email when that happens. Discard those
sessions from the tally.

## Scoring

Guessing by chance gets about half right. To claim "I can tell" at the usual
5% threshold you need at least:

| Sessions | Correct guesses needed |
|---|---|
| 10 | 9 |
| 20 | 15 |
| 30 | 20 |

Fewer correct than that means the two arms were not reliably distinguishable
in your use, not that they are equivalent. Note the reasons you gave too: a
tell that appears in every correct guess (tone, card use, Spanish, latency)
is the specific thing entry 20's evaluation should then measure.

## Switching it off

Delete `DEMO_MODEL_EXPERIMENT_SALT` in the Render dashboard. Every session
returns to the production stack at once.

## Removing it

The experiment is removed as one change, and every item goes in that change:

- `homeschool-api/services/model_experiment.py` and
  `homeschool-api/tests/test_demo_model_experiment.py`
- the experiment settings block in `homeschool-api/core/config.py`
- the hook in `services/adapters/router.py` (`_adapter`, `_live_order`)
- `model_experiment.bind(...)` in `routers/tutor.py` and `routers/sandbox.py`
- `model_experiment.suspended()` in `services/moderation.py`
- the arm line in `routers/feedback.py`
- the four experiment keys in `render.yaml`, and the two secrets in Render
- the OpenRouter lines in `demo/public/privacy.html`,
  `demo/public/privacy.es.html`, `site/privacy/index.html`,
  `docs/INFORMATION_SECURITY_POLICY.md` §5, `docs/VENDOR_DATA_FLOW.md`, and
  `docs/RETENTION_POLICY.md`'s 2026-10-22 note (amended to say it ended)
- the OpenRouter key, revoked in OpenRouter's dashboard
- this file, and its entry in `CLAUDE.md`

Afterwards, `grep -rn "model_experiment\|OpenRouter\|EXPERIMENT_" .` should
find nothing except the retention policy's dated history.
