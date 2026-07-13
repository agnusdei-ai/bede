import { Component, type ErrorInfo, type ReactNode } from 'react'
import { BookOpen, RotateCcw } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

/**
 * Catches render-time exceptions anywhere below it so a single bad render
 * shows a recoverable screen instead of a blank page — a public demo visitor
 * has no console open to explain a silent white screen.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  handleReload = () => {
    this.setState({ hasError: false })
    window.location.href = '/'
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-sage-50 to-faith-100 flex items-center justify-center px-4">
        <div className="text-center max-w-sm">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-sage-100 rounded-2xl mb-4">
            <BookOpen size={32} className="text-sage-600" />
          </div>
          <p className="text-sage-600 font-display text-lg font-semibold">Bede</p>
          <p className="text-sm text-gray-500 mt-2 mb-6">
            Something went wrong. Let's get back on track.
          </p>
          <button
            onClick={this.handleReload}
            className="inline-flex items-center gap-2 px-5 py-3 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors"
          >
            <RotateCcw size={16} /> Start Over
          </button>
        </div>
      </div>
    )
  }
}
