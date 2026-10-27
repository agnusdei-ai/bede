# Bede recorded lesson

The existing `/bede/tour/` page now includes **Watch Bede in action**, alongside
the preserved short overview. The entry link and `#lesson-title` deep link
reach the new player. The **Try Bede for 20 minutes** link opens `/bede/`;
twenty minutes is an invitation, not a new enforced session limit.

## What was recorded

- The real public Bede backend with the production demo interface.
- A fictional Grade 3 role-play exploring Aesop's *The Lion and the Mouse*.
- Typed requests and answers, including retelling, reasoning, evidence, and
  an everyday application. No real child's identity or records were used.
- Edited highlights: network waiting time is shortened, actual frames may
  be held for readability, and the temporary demo access code is redacted.
- A separate adult-facing guide voice, recorded as one complete take and
  mastered as one track. It is not a replacement for Bede's tutor voice or
  a real learner testimonial.

The final on-screen responses are Bede's actual generated replies, not the
proposed dialogue from the planning script. The readable transcript includes
guide narration and the actual on-screen exchanges. The clip demonstrates
the example's teaching practices; it does not report measured learning gains.

## Delivery

The compact MP4, WebM fallback, captioned MP4, poster, English captions, and transcript JSON
are included under `demo/tour-public/bede-tour/`. The existing combined-site
build copies them into `publish/bede/tour/bede-tour/`. Native playback is
user-initiated; the demo link remains available without an automatic redirect.
Unavailable media and transcript states provide explicit alternatives.

Keep raw session footage, narration masters, access credentials, and temporary
renders out of Git. Preserve the existing overview media during revisions.
For a future Spanish edition, follow the approved general-Spanish scope,
without country-specific positioning.
