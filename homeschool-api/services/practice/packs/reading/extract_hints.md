# Reading a reading-comprehension quiz

- Do not copy the passage itself. Copy only the questions.
- Copy each question into `prompt` exactly as printed. For multiple choice,
  include the options in `prompt` (e.g. "What does weary mean? A) happy
  B) tired C) angry D) late").
- Copy the child's answer exactly into `student_response`. For multiple
  choice record the letter they chose. For a long written answer, copy the
  first 200 characters.
- Copy any answer the teacher wrote into `teacher_correction`. If an answer
  key is printed on the page, use it for a question marked wrong.
- A tick means correct, a cross incorrect, a half tick or "½" partial. A
  score such as "2/4" on a written answer is partial.
- If a word or letter is hard to read, give your best reading, lower
  `confidence`, and say what is unclear in `ask_parent`.
