import { Component, type ErrorInfo, type ReactNode } from 'react'
import { RotateCcw } from 'lucide-react'
import { AgnusDeiMark, BedeWordmark } from './BedeMark'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

/**
 * Catches render-time exceptions anywhere below it so a single bad render
 * (e.g. malformed API data) shows a recoverable screen instead of a blank
 * tablet — this is a child-facing session, not a page a parent can debug.
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
          <AgnusDeiMark className="w-16 h-16 mx-auto mb-4" />
          <p className="text-sage-600 font-display text-lg font-semibold">
            <BedeWordmark />
          </p>
          <p className="text-sm text-gray-500 mt-2 mb-6">
            Something went wrong. Let's get back on track.
          </p>
          <button
            onClick={this.handleReload}
            className="inline-flex items-center gap-2 px-5 py-3 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors"
          >
            <RotateCcw size={16} /> Return to Login
          </button>
        </div>
      </div>
    )
  }
}
