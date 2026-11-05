/**
 * Splits a long upload into parts the browser sends one after another.
 *
 * There is no limit on how many pages a parent uploads. Each part is one
 * request, kept small enough for the deployment's request ceiling (nginx
 * allows 12 MB, and base64 adds a third), and the server continues the same
 * reading from part to part. The server reads six pages per model call
 * whatever a part holds; this split is only about request size.
 *
 * Mirror of homeschool-tutor/src/utils/uploadParts.ts; uploadParts.test.ts keeps the
 * two copies equal.
 */
export const PART_MAX_FILES = 6
export const PART_MAX_BYTES = 7 * 1024 * 1024

export function splitIntoParts<T extends { size: number }>(files: T[]): T[][] {
  const parts: T[][] = []
  let part: T[] = []
  let bytes = 0
  for (const file of files) {
    if (part.length && (part.length >= PART_MAX_FILES || bytes + file.size > PART_MAX_BYTES)) {
      parts.push(part)
      part = []
      bytes = 0
    }
    part.push(file)
    bytes += file.size
  }
  if (part.length) parts.push(part)
  return parts
}
