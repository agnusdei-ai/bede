/**
 * Renders a narrow subset of inline Markdown emphasis (**bold**, *italic*)
 * as real elements instead of literal asterisks. Bede's own text
 * occasionally uses this for emphasis — useTextToSpeech.ts already strips
 * the same syntax before speaking it aloud, but every chat bubble in this
 * app was showing it completely unparsed ("**place value** means...").
 *
 * Deliberately narrow: only these two inline forms, no links/headers/lists
 * — a Socratic tutor's chat turn has no legitimate need for anything
 * heavier, and pulling in a full Markdown library for two regexes would be
 * a lot of surface for very little. Builds a plain array of strings and
 * elements (never dangerouslySetInnerHTML), so this stays exactly as safe
 * against injected HTML as the raw-text rendering it replaces — React
 * escapes every text child automatically either way.
 */
const EMPHASIS_PATTERN = /\*\*(.+?)\*\*|\*(.+?)\*/g

export function renderEmphasis(text: string): React.ReactNode {
  if (!text.includes('*')) return text

  const nodes: React.ReactNode[] = []
  let lastIndex = 0
  let key = 0
  EMPHASIS_PATTERN.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = EMPHASIS_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index))
    if (match[1] !== undefined) {
      nodes.push(<strong key={key++}>{match[1]}</strong>)
    } else {
      nodes.push(<em key={key++}>{match[2]}</em>)
    }
    lastIndex = EMPHASIS_PATTERN.lastIndex
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex))
  return nodes
}
