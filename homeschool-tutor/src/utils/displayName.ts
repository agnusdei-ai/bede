/** How a learner is addressed on screen. A display value, never a key: records,
 *  routes and caches stay keyed by `student_name`, so an adult can set or change
 *  a preferred name (a corrected spelling or a nickname) without moving any data.
 *  Mirrors SessionConfig.display_name in homeschool-api/models/schemas.py. */
export function displayNameOf(
  config: { student_name?: string | null; preferred_name?: string | null } | null | undefined,
): string {
  return config?.preferred_name?.trim() || config?.student_name || ''
}
