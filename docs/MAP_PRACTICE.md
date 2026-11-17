# Map practice (K-2)

Short map-reading practice for the youngest learners, offered by Bede during
History, Nature Study or Living Books. It is "home geography" in its early
form: where things are, what a map is, and how to read a simple one. Scale,
latitude and longitude, and real road or atlas maps are not part of it.

## What each grade practises

The three grades are kept distinct. A child gets the level for the grade
saved in Parent Setup, never one chosen in the request.

| Grade | What it practises | What the map looks like |
| --- | --- | --- |
| K | Position words (above, below, left of, right of, next to). A map is a picture seen from above. Following a path on a picture map. | A small picture map, no grid lines, no compass. |
| 1 | Symbols and a key. The four directions: north, south, east, west. Placing a thing on a map. | A 4 by 4 map with a key and a compass. |
| 2 | The compass rose and two-step routes. Simple grids ("the well is in square B2"). Land and water. | A 5 by 5 map with lettered columns and numbered rows. |

Grade 2's continents and oceans, and maps of places in history, stay in
ordinary lessons, where Bede uses the sourced picture catalogue. They are
not practice maps.

## The routine: Watch, Together, Your turn

1. **Watch.** The scene tilts from a side view to a view from above, and
   one answer is shown.
2. **Together.** Two questions with hints on screen (a highlighted row or
   square, a compass with all four letters). A miss shows the answer
   straight away. Nothing is recorded.
3. **Your turn.** Three questions on new maps with no hints. The child taps
   a square or picks an answer. Two tries, then the answer is shown and the
   child moves on.

The frame for the three steps (`components/routine/RoutineShell.tsx`) holds
no lesson logic, so other K-2 practice can reuse it.

## How it starts

Bede offers it with the `invite_map_practice` tool, at most once a session,
when a lesson reaches a place or a route. The card and its wording are
written by the server, not the model. The server refuses the tool outside
K-2, outside those three subjects, a second time in one session, and in the
public demo. The child can close it at any time and reopen it from the card.

## Three rules

1. **No real places.** Bede never asks for a child's street, address or
   neighbourhood. A practice map has no place names, and the answer routes
   accept only a tapped square, one of the offered choices, or spoken words
   matched against those same choices. Nothing typed or said is kept.
2. **Maps are drawn by code.** `services/map_practice.py` builds every map
   from ten fixed symbols (house, tree, pond, gate, well, barn, bridge,
   rock, flower, bench) plus water, a path and a compass, and works out
   every answer. No model draws a map or decides whether an answer is right.
3. **No map score.** A "Your turn" question answered correctly adds one row
   to the work ledger (subject area `map_skills`), once. A question that
   ended with the answer shown adds nothing. There is no mastery estimate
   for maps and nothing is added to the mathematics skills.

## What is stored

Only the work-ledger row above, in the existing encrypted
`skill_activity_log` table. No new table. A lesson is rebuilt from its id
each time an answer is checked; the id names the level, skill, a random
number and the day, and is signed for one learner, so it works for that
learner today and tomorrow and for nobody else. Misses within a lesson are
held in memory for up to six hours and never written down.

## Routes

- `GET /map-practice/{student}/lesson` returns a new lesson.
- `POST /map-practice/{student}/lessons/{lesson_id}/answers` checks one answer.

Both need a signed-in parent or child with access to that learner and a
consent record for the learner. The demo cannot reach them.

## Not built

- Answering by voice inside the practice screen. The server accepts a
  spoken answer; the screen does not yet record one.
- The public demo. Changes there need the owner's sign-off.
- Other subjects in the Watch, Together, Your turn routine. Phonics is built
  (step 1 of [K2_PRACTICE.md](K2_PRACTICE.md)); the rest are specified there,
  not built.

Tests: `homeschool-api/tests/test_map_practice.py` and
`homeschool-tutor/src/components/MapPractice.test.tsx`.
