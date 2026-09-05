import type { TFunction } from 'i18next'

import { SUBJECT_MAP } from '../types'
import type { Subject } from '../types'

/**
 * The subject's name in the language of the session showing it.
 *
 * `SUBJECT_MAP[id].label` is English and was rendered directly everywhere —
 * so a Spanish session's own sidebar read "Morning Time" while Bede was
 * (correctly) speaking Spanish around it. The backend has the same fix at
 * `models/schemas.py`'s `subject_label`, and
 * `tests/test_mixed_language_output.py` asserts the two agree, since a
 * subject named one way on screen and another way in the prompt is the same
 * defect wearing different clothes.
 *
 * Falls back to the English label rather than to the raw key: a missing
 * translation should read as an untranslated name, never as `subjects.latin`.
 */
export function subjectLabel(t: TFunction, id: Subject): string {
  return t(`subjects.${id}`, SUBJECT_MAP[id]?.label ?? id)
}
