/**
 * Splits a long upload into parts the browser sends one after another.
 *
 * There is no limit on how many pages a parent uploads, only on size: up to
 * 1 GB in all and 25 MB a file. Each part is one request, kept within the
 * request ceiling (nginx allows 42 MB on /api/practice/, base64 adds a third,
 * and the API takes 30 MB a request), and the server continues the same
 * reading from part to part. The server reads six pages per model call
 * whatever a part holds; this split is only about request size.
 *
 * Mirror of homeschool-tutor/src/utils/uploadParts.ts; uploadParts.test.ts keeps the
 * two copies equal.
 */
export const PART_MAX_FILES = 6
export const PART_MAX_BYTES = 24 * 1024 * 1024
export const FILE_MAX_BYTES = 25 * 1024 * 1024
export const UPLOAD_MAX_BYTES = 1024 * 1024 * 1024
/** How much copied-out source a quiz draft reads (models/practice.py). */
export const SOURCE_TEXT_MAX_CHARS = 60_000

/** Why an upload cannot be sent, or null when it can. */
export function uploadProblem(files: { size: number }[]): 'total' | 'file' | null {
  if (files.some((f) => f.size > FILE_MAX_BYTES)) return 'file'
  if (files.reduce((sum, f) => sum + f.size, 0) > UPLOAD_MAX_BYTES) return 'total'
  return null
}

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
