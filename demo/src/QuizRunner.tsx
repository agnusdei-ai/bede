import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
import Diagram, { type DiagramSpec } from './Diagram'
import { checkAnswer, nextQuestion, stepLevel, type QuizDifficulty, type QuizResult, type RunnableQuestion } from './quizRunner'

export type RunnerQuestion = RunnableQuestion & { diagram?: DiagramSpec | null }

export interface QuizSummary {
  total: number
  right: number
  wrong: number
  open: number
}

/**
 * Takes a drafted quiz one question at a time. The answer and its short
 * explanation appear only after the student answers; the next question steps
 * up a level after a right answer and down after a miss (utils/quizRunner.ts).
 * Mirror of homeschool-tutor/src/components/QuizRunner.tsx (parity asserted).
 */
export default function QuizRunner({ title, questions, onFinish }: {
  title: string
  questions: RunnerQuestion[]
  onFinish: (summary: QuizSummary) => void
}) {
  const { t } = useTranslation()
  const [answered, setAnswered] = useState<Set<number>>(() => new Set())
  const [level, setLevel] = useState<QuizDifficulty>('on')
  const [current, setCurrent] = useState<number | null>(() => nextQuestion(questions, new Set(), 'on'))
  const [response, setResponse] = useState('')
  const [result, setResult] = useState<QuizResult | null>(null)
  const [results, setResults] = useState<QuizResult[]>([])

  const summary = useMemo<QuizSummary>(() => ({
    total: results.length,
    right: results.filter((r) => r === 'right').length,
    wrong: results.filter((r) => r === 'wrong').length,
    open: results.filter((r) => r === 'open').length,
  }), [results])

  const question = current === null ? null : questions[current]

  const submit = (given: string) => {
    if (!question || result !== null || !given.trim()) return
    const outcome = checkAnswer(question, given)
    setResult(outcome)
    setResults((previous) => [...previous, outcome])
  }

  const next = () => {
    if (current === null || result === null) return
    const done = new Set(answered).add(current)
    const nextLevel = stepLevel(level, result)
    setAnswered(done)
    setLevel(nextLevel)
    setCurrent(nextQuestion(questions, done, nextLevel))
    setResponse('')
    setResult(null)
  }

  const button = 'min-h-[44px] rounded-lg px-4 py-2 text-sm font-medium'

  if (!question) {
    return (
      <section aria-label={title} className="space-y-3 rounded-xl border border-sage-200 bg-sage-50 p-3 text-sm">
        <h3 className="font-semibold text-sage-900">{title}</h3>
        <p role="status">{t('quizRunner.finished', { right: summary.right, total: summary.total })}</p>
        {summary.open > 0 && <p className="text-xs text-gray-600">{t('quizRunner.openNote', { count: summary.open })}</p>}
        <button type="button" onClick={() => onFinish(summary)} className={`${button} bg-sage-700 text-white`}>
          {t('quizRunner.done')}
        </button>
      </section>
    )
  }

  const choices = question.options.length > 0
  return (
    <section aria-label={title} className="space-y-2 rounded-xl border border-sage-200 bg-sage-50 p-3 text-sm">
      <h3 className="font-semibold text-sage-900">{title}</h3>
      <p className="text-xs text-gray-600">{t('quizRunner.progress', { n: answered.size + 1, total: questions.length })}</p>
      <p className="whitespace-pre-line text-gray-800">{question.prompt}</p>
      <Diagram d={question.diagram} />
      {choices ? (
        <div className="flex flex-col gap-2">
          {question.options.map((option, index) => (
            <button key={option} type="button" disabled={result !== null}
              onClick={() => { setResponse(option); submit(option) }}
              aria-pressed={response === option}
              className={`${button} border text-left ${response === option ? 'border-sage-600 bg-white' : 'border-gray-200 bg-white'} disabled:opacity-70`}>
              {String.fromCharCode(65 + index)}) {option}
            </button>
          ))}
        </div>
      ) : (
        <form onSubmit={(event) => { event.preventDefault(); submit(response) }} className="flex gap-2">
          <input value={response} onChange={(event) => setResponse(event.target.value)} disabled={result !== null}
            aria-label={t('quizRunner.answerLabel')} maxLength={400}
            className="min-w-0 flex-1 rounded-lg border border-sage-300 bg-white px-3 py-2" />
          <button type="submit" disabled={!response.trim() || result !== null} className={`${button} bg-sage-700 text-white disabled:opacity-50`}>
            <Check size={15} className="mr-1 inline" />{t('quizRunner.check')}
          </button>
        </form>
      )}
      {result !== null && (
        <div role="status" className="space-y-1 rounded-lg bg-white p-2">
          <p className={result === 'right' ? 'font-medium text-sage-800' : 'font-medium text-gray-800'}>
            {result === 'right' ? t('quizRunner.right')
              : result === 'wrong' ? t('quizRunner.wrong', { answer: question.answer })
                : t('quizRunner.open', { answer: question.answer })}
          </p>
          {question.explanation && <p className="text-gray-700">{t('quizRunner.why', { text: question.explanation })}</p>}
          <button type="button" onClick={next} className={`${button} bg-navy-700 text-white`}>
            {answered.size + 1 < questions.length ? t('quizRunner.next') : t('quizRunner.seeResults')}
          </button>
        </div>
      )}
    </section>
  )
}
