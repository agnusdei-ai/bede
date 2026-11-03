# Reading a spelling test

- Copy each word exactly as the child wrote it into `student_response`,
  letter for letter, even when it is wrong. Never correct it.
- If the test gives a sentence or a number for each word, put that in
  `prompt` (e.g. "Word 4" or "We went ___ the park.").
- Copy the correct spelling the teacher wrote into `teacher_correction`. If
  the page has a printed word list, use the listed word as the correction for
  a word marked wrong.
- A tick means correct, a cross incorrect.
- If a letter is hard to read (a, o, u; n, h; e, c), give your best reading,
  lower `confidence`, and say which letter is unclear in `ask_parent`.
