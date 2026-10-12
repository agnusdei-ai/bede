/**
 * Three promises nobody has decided to make, and the wiring that keeps them
 * from being made by accident.
 *
 * An unresolved policy is dangerous in a specific way: the *friendly* thing
 * to write is the promise. A customer cancelling wants to hear that they keep
 * their trial, that they will be refunded, that they drop to Community rather
 * than to nothing — so a sentence saying so reads as good service and gets
 * written, by a person or by a model, long before anyone rules on whether it
 * is true. By the time it is noticed it is in a customer's inbox.
 *
 * So each promise is represented here as something that must be AFFIRMATIVELY
 * RECORDED before it can be made, with the default being that it cannot. The
 * same shape as `conversion.ts` refusing an unconfigured price and
 * `cancellation.ts` refusing an unrecorded trial-access policy: the path
 * exists, fully built, for the moment the decision lands, and until then it
 * is unreachable rather than absent.
 *
 * **The scanner is the half that actually catches things.** A predicate only
 * helps code that asks it; the promise, when it appears, appears in COPY. So
 * `unresolvedPromisesIn()` reads rendered text and names which promise it
 * found, and the suites run it over every surface a customer can receive.
 *
 * None of this rules on the policies. It makes the absence of a ruling
 * visible instead of silently filled in.
 */

/** The three, named by what they would promise. */
export type UnresolvedPromise =
  /** That paid or trial access drops to Community rather than to nothing. */
  | "community_downgrade"
  /** That money comes back, now or automatically, on cancelling. */
  | "immediate_refund"
  /** That trial lessons continue after a cancellation. */
  | "retained_trial_access";

export const UNRESOLVED_PROMISES: readonly UnresolvedPromise[] = [
  "community_downgrade",
  "immediate_refund",
  "retained_trial_access",
];

/**
 * Which promises a deployment has been authorised to make.
 *
 * Deliberately a record of booleans rather than optional fields: adding a
 * fourth promise forces every construction site to state a position on it,
 * which is how this stays a decision rather than drifting into a default.
 */
export type PromiseAuthorisation = Record<UnresolvedPromise, boolean>;

/**
 * The authorisation as it stands: none of them.
 *
 * This is the value the product actually runs on, and it is a statement of
 * fact rather than caution — see docs/PAYMENTS_AND_CANCELLATION.md §8. When a
 * policy is recorded, flipping its entry here is the one edit, in a place
 * that explains what the flip means.
 */
export const NOTHING_PROMISED: PromiseAuthorisation = {
  community_downgrade: false,
  immediate_refund: false,
  retained_trial_access: false,
};

export function mayPromise(
  promise: UnresolvedPromise,
  authorisation: PromiseAuthorisation = NOTHING_PROMISED,
): boolean {
  return authorisation[promise] === true;
}

/**
 * Phrasings that would constitute each promise.
 *
 * Deliberately blunt, on this repository's standing rule: where a pattern
 * catches honest copy, the COPY moves rather than the pattern being narrowed,
 * because a guard with a small vocabulary passes while the thing it forbids
 * walks in under another name. Each pattern was written against the sentence
 * someone would actually write, not against a paraphrase of the rule.
 */
const PROMISE_PATTERNS: Record<UnresolvedPromise, readonly RegExp[]> = {
  community_downgrade: [
    // "you'll move to Community", "switch to the free Community tier",
    // "revert to Community access", "keep Community access".
    /\b(move|moved|moves|switch|switched|revert|reverts|downgrade|downgraded|drop|dropped|return|returns|keep|keeps|retain|retains|continue)\b[^.?!]{0,60}\bcommunity\b/i,
    /\bcommunity\b[^.?!]{0,40}\b(instead|automatically|afterwards|after that|thereafter)\b/i,
    /\bfree (community|tier|plan)\b/i,
  ],
  immediate_refund: [
    // "you'll be refunded", "we'll refund you", "money back", "refunded
    // automatically". NOT "does not automatically refund", which is the
    // honest sentence — see `isRefundDisclaimer`.
    /\b(refund|refunds|refunded|refunding)\b/i,
    /\bmoney back\b/i,
    /\breimburs/i,
  ],
  retained_trial_access: [
    // "you can continue using your trial until", "trial access continues",
    // "keep your trial".
    /\btrial\b[^.?!]{0,60}\b(continues|continue|still available|remains|stays)\b/i,
    /\b(keep|keeps|retain|retains|continue using)\b[^.?!]{0,30}\btrial\b/i,
  ],
};

/**
 * The one legitimate use of refund words, and the reason this is a function
 * rather than a hole in the pattern.
 *
 * "Cancelling renewal does not automatically refund your current payment" is
 * a sentence the product NEEDS: it is the disclaimer that stops a customer
 * assuming the opposite. The blunt refund pattern catches it, correctly, and
 * the resolution is to recognise the negation rather than to weaken the
 * pattern — a narrower pattern would also stop catching "we will refund you".
 */
function isRefundDisclaimer(sentence: string): boolean {
  return /\b(not|never|no)\b[^.?!]{0,40}\brefund/i.test(sentence) ||
    /\brefund[^.?!]{0,40}\b(policy|eligibility|terms)\b/i.test(sentence);
}

/** Split on sentence boundaries and strip markup, so a pattern is judged
 * against one claim at a time rather than a whole page. */
function sentencesOf(text: string): string[] {
  return text
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .split(/(?<=[.?!])\s+/)
    .filter((s) => s.trim().length > 0);
}

/**
 * Which unresolved promises this text would make. Empty is the only passing
 * answer while `NOTHING_PROMISED` stands.
 */
export function unresolvedPromisesIn(
  text: string,
  authorisation: PromiseAuthorisation = NOTHING_PROMISED,
): readonly UnresolvedPromise[] {
  const found = new Set<UnresolvedPromise>();
  for (const sentence of sentencesOf(text)) {
    for (const promise of UNRESOLVED_PROMISES) {
      if (mayPromise(promise, authorisation)) continue;
      if (promise === "immediate_refund" && isRefundDisclaimer(sentence)) continue;
      if (PROMISE_PATTERNS[promise].some((pattern) => pattern.test(sentence))) {
        found.add(promise);
      }
    }
  }
  return [...found];
}
