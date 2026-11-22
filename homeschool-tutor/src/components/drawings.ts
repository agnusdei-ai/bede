/**
 * Bede's hand-drawn pictures, one for every picture name the API accepts
 * (models/practice.py's ICONS): a sepia ink line over a watercolour wash, in
 * the classical natural-history style the owner approved. Drawn for Bede;
 * nothing here is fetched, traced from or credited to another source.
 * Diagram.tsx's DrawingArt draws them, on screen and in print.
 *
 * Mirrored byte for byte in demo/src/drawings.ts; demo/src/Diagram.test.tsx
 * keeps the two the same.
 *
 * Every path is in a 64 x 64 box. `ink` is the outline and must carry the
 * shape on its own: at 34px only `wash`, `bold`, `ink`, `thin` and `dots` are
 * drawn. No drawing holds a letter, a number or a word.
 */

export interface Drawing {
  wash: [path: string, colour: string][]
  ink: string
  bold?: string
  thin?: string
  fine?: string
  dots?: [cx: number, cy: number, r: number][]
  hatch?: string
  cross?: string
}

export const DRAWING_PALETTE: Record<string, string> = { 'rust': '#b8642e', 'madder': '#8c3b2e', 'rose': '#c98a7a', 'gilt': '#d4a63c', 'ochre': '#c99530', 'straw': '#e3cd8a', 'leaf': '#4d6a43', 'sage': '#8fa37a', 'water': '#5f7f99', 'sky': '#a9bfcf', 'pale': '#dde4e8', 'cream': '#efe4cc', 'white': '#fbf8f0', 'wood': '#6b4a2e', 'oak': '#8a5a34', 'tan': '#c9a47a', 'skin': '#e0b894', 'skin2': '#a8754e', 'stone': '#7d7a72', 'slate': '#5b6270', 'dark': '#4a3a2a', 'night': '#2f3a52', 'black': '#3a3530' }

export const DRAWINGS: Record<string, Drawing> = {
  cat: {"wash":[["M22 58 C18 46 20 34 28 30 C34 28 40 30 42 36 C46 44 46 52 42 58Z","stone"],["M26 18 C26 12 30 10 34 10 C38 10 42 12 42 18 C42 24 38 27 34 27 C30 27 26 24 26 18Z","stone"]],"ink":"M27 14 L27 5 L32 11 M41 14 L41 5 L36 11 M26 18 C26 12 30 10 34 10 C38 10 42 12 42 18 C42 24 38 27 34 27 C30 27 26 24 26 18 M30 17 c1 -0.7 2 -0.7 2.4 0 M36 17 c1 -0.7 2 -0.7 2.4 0 M33 21 L34 22 L35 21 M34 22 L34 23.5 M30 27 C24 30 20 40 22 58 L42 58 C46 50 46 42 42 34 C40 30 38 28 38 27 M42 56 C52 58 56 50 52 44","thin":"M28 58 L28 50 M36 58 L36 50","fine":"M29 22 L22 21 M29 23 L22 24 M39 22 L46 21 M39 23 L46 24 M24 36 c3 0 4 1 5 0 M23 42 c3 0 4 1 5 0 M23 48 c3 0 4 1 5 0","cross":"M38 30 C44 36 46 48 42 58 L39 58 C42 48 41 38 36 31Z"},
  bee: {"wash":[["M26 22 C18 10 8 12 10 20 C12 26 22 26 28 24Z M38 22 C46 10 56 12 54 20 C52 26 42 26 36 24Z","pale"],["M23 38 a9 14 0 1 0 18 0 a9 14 0 1 0 -18 0Z","ochre"],["M26 20 a6 6 0 1 0 12 0 a6 6 0 1 0 -12 0Z","dark"]],"ink":"M26 22 C18 10 8 12 10 20 C12 26 22 26 28 24 M38 22 C46 10 56 12 54 20 C52 26 42 26 36 24 M26 20 a6 6 0 1 0 12 0 a6 6 0 1 0 -12 0 M23 38 a9 14 0 1 0 18 0 a9 14 0 1 0 -18 0","bold":"M23.5 33 C28 35 36 35 40.5 33 M23 40 C28 42 36 42 41 40 M25 46 C29 48 35 48 39 46","thin":"M30 14 C28 8 25 6 22 6 M34 14 C36 8 39 6 42 6 M24 28 L16 32 L14 38 M24 34 L15 40 L14 46 M40 28 L48 32 L50 38 M40 34 L49 40 L50 46","fine":"M14 18 C18 18 22 20 26 22 M50 18 C46 18 42 20 38 22"},
  fox: {"wash":[["M22 56 C20 44 24 34 32 30 L40 28 C44 34 44 46 42 56Z","rust"],["M36 28 C35 20 39 15 45 15 L56 19 C55 23 50 26 44 27Z","rust"],["M22 54 C12 56 6 50 8 42 C10 36 16 36 20 40","rust"],["M8 46 C7 50 10 53 13 52","cream"],["M33 38 C34 45 37 51 39 56 L34 56 C32 50 31 44 33 38Z M46 24 L56 19 C55 23 50 25 46 24Z","cream"]],"ink":"M39 16 L38 7 L44 13 M45 14 L47 6 L50 15 M36 28 C35 20 39 15 45 15 L56 19 C55 23 50 26 44 27 M44 18.5 c1 -0.8 2 -0.8 2.6 0 M36 28 C28 31 22 42 22 56 M40 28 C44 34 44 46 42 56 M27 56 L26 60 L29 60 M37 56 L37 60 L40 60 M22 54 C12 56 6 50 8 42 C10 36 16 36 20 40","fine":"M39.5 10 L42 13 M46.5 9 L48 13 M24 40 c3 -1 4 0 6 -1 M24 44 c3 -1 4 0 6 -1 M24 48 c3 -1 4 0 6 -1 M10 44 c2 -1 4 -1 5 0 M11 48 c2 -1 4 -1 5 0","dots":[[56,19,0.9]],"hatch":"M38 32 C42 38 42 46 40 54 L42 54 C44 46 44 36 40 29Z"},
  tree: {"wash":[["M29 40 L35 40 L37 58 L27 58Z","wood"],["M32 6 C42 5 50 12 50 20 C57 24 56 36 48 38 C46 44 38 45 34 42 C30 46 20 45 18 40 C9 38 8 26 14 22 C13 12 22 6 32 6Z","leaf"]],"ink":"M32 6 C42 5 50 12 50 20 C57 24 56 36 48 38 C46 44 38 45 34 42 C30 46 20 45 18 40 C9 38 8 26 14 22 C13 12 22 6 32 6Z M29 42 L27 58 M35 42 L37 58 M22 58 C26 57 38 57 42 58 M32 42 L31 48 M32 44 L26 38 M33 44 L40 37","fine":"M18 18 c3 -2 5 -2 7 0 M30 12 c3 -2 5 -2 7 0 M38 22 c3 -2 5 -2 7 0 M22 30 c3 -2 5 -2 7 0 M36 33 c3 -2 5 -2 7 0","hatch":"M34 42 L36 58 L33 58 L32 44Z","cross":"M14 30 C16 38 24 42 34 41 C42 43 48 38 52 30 C50 36 44 40 34 39 C24 40 18 36 14 30Z"},
  sun: {"wash":[["M32 20 a12 12 0 1 0 0.01 0Z","gilt"]],"ink":"M32 20 a12 12 0 1 0 0.01 0","thin":"M32 4 L32 16 M32 48 L32 60 M4 32 L16 32 M48 32 L60 32 M12 12 L20 20 M44 44 L52 52 M52 12 L44 20 M12 52 L20 44","fine":"M22 6 L25 17 M42 6 L39 17 M6 22 L17 25 M6 42 L17 39 M58 22 L47 25 M58 42 L47 39 M22 58 L25 47 M42 58 L39 47","hatch":"M32 20 A12 12 0 0 1 32 44 A8 12 0 0 0 32 20Z"},
  ship: {"wash":[["M4 52 C14 49 22 55 32 52 C42 49 50 55 60 52 L60 62 L4 62Z","water"],["M10 42 L56 42 L50 52 L16 52Z","oak"],["M22 12 L22 40 L12 40Z M34 8 L34 40 L24 40Z M46 14 L46 40 L38 40Z","cream"]],"ink":"M8 42 L56 42 L50 52 L16 52 Z M22 10 L22 42 M34 6 L34 42 M46 12 L46 42 M22 12 C18 22 14 30 12 40 L22 40 M34 8 C30 20 26 30 24 40 L34 40 M46 14 C43 24 40 32 38 40 L46 40","thin":"M34 6 L39 4 L34 2 M4 54 C14 51 22 57 32 54 C42 51 50 57 60 54","fine":"M8 42 L4 36 M34 6 L22 10 M34 6 L46 12 M8 58 c4 -1 6 0 9 -1 M40 59 c4 -1 6 0 9 -1","cross":"M16 46 L52 46 L50 52 L18 52Z"},
  boat: {"wash":[["M4 46 C14 43 22 49 32 46 C42 43 50 49 60 46 L60 58 L4 58Z","water"],["M8 36 L56 34 C54 42 46 46 32 46 C18 46 10 42 8 36Z","oak"]],"ink":"M8 36 L56 34 C54 42 46 46 32 46 C18 46 10 42 8 36Z M44 50 l5 4 l-1 2 l-5 -4Z","bold":"M18 30 L46 52","thin":"M24 36 L22 30 L28 30 L26 36 M4 48 C14 45 22 51 32 48 C42 45 50 51 60 48","fine":"M10 38 C24 39 40 38 54 36 M10 54 c4 -1 6 0 9 -1 M38 55 c4 -1 6 0 9 -1","cross":"M10 40 C20 44 44 44 54 37 C50 43 44 46 32 46 C20 46 12 43 10 40Z"},
  kite: {"wash":[["M38 5 L52 22 L38 40 L24 22Z","madder"],["M38 5 L38 40 L24 22Z","gilt"]],"ink":"M38 5 L52 22 L38 40 L24 22Z M38 5 L38 40 M24 22 L52 22","thin":"M38 40 C33 46 34 50 27 52 C20 54 22 58 13 60 M30 51 l3 -2 l1 3 M21 55 l3 -2 l1 3 M14 59 l3 -2 l1 3","hatch":"M38 22 L52 22 L38 40Z"},
}
