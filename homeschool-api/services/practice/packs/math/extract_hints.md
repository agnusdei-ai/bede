# Reading a mathematics worksheet

- Copy each problem exactly as printed into `prompt`, using + − × ÷ and `/` for
  a fraction (`3/4`). Write a mixed number as `2 3/4`. Keep `=` at the end if
  the page has one.
- Copy the child's final answer into `student_response` exactly, including a
  negative sign, a decimal point, or a fraction left unsimplified. If working
  is shown, record only the final answer.
- A word problem: copy its question into `prompt` in plain words. Do not turn
  it into an equation yourself.
- A tick means correct, a cross incorrect. Copy any number the teacher wrote
  beside the answer into `teacher_correction`.
- If a digit, sign, or decimal point is hard to read, give your best reading,
  lower `confidence`, and say which character is unclear in `ask_parent`.
- A picture problem (a shaded fraction, a clock, an array of dots, base-ten
  blocks, a rectangle or right triangle with its sides marked, a number line,
  a bar graph, points on a grid, things laid along a ruler, coins and bills,
  a thermometer): record the picture in `diagram` with its
  exact numbers, and copy the question into `prompt` ("What fraction is
  shaded?"). Bede draws it again and checks the answer against it, so count
  carefully. A picture that is none of these goes in `stimulus` only.
