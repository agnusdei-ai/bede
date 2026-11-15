import { Component, type ErrorInfo, type ReactNode } from 'react'
import { RotateCcw } from 'lucide-react'
import { AgnusDeiMark, BedeWordmark } from './BedeMark'
import i18n from '../i18n'
import { logDebug } from '../hooks/debugBus'
import { isChunkLoadError, reloadOnceForNewRelease } from '../utils/staleBuild'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  /** True while the page reloads to fetch a new release (see staleBuild.ts). */
  updating: boolean
}

/**
 * Catches render-time exceptions anywhere below it so a single bad render
 * (e.g. malformed API data) shows a recoverable screen instead of a blank
 * tablet — this is a child-facing session, not a page a parent can debug.
 *
 * Two kinds of failure land here, and they are handled differently. A page
 * whose file could not be loaded (the tab is still running the previous
 * release, see utils/staleBuild.ts) reloads once and recovers by itself. Any
 * other error is a real bug: it is recorded in the debug log, which is how a
 * family reports one, and the recovery screen is shown.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, updating: false }

  static getDerivedStateFromError(error: unknown): State {
    return { hasError: true, updating: isChunkLoadError(error) }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
    const stale = isChunkLoadError(error)
    logDebug(`ERROR SCREEN ${stale ? 'page file failed to load' : 'render error'} ${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`)
    if (stale) {
      if (reloadOnceForNewRelease()) {
        logDebug('ERROR SCREEN reloading once for a new release')
      } else {
        // Already reloaded moments ago and the file is still missing: show
        // the recovery screen rather than reload forever.
        this.setState({ updating: false })
      }
    }
  }

  handleReload = () => {
    this.setState({ hasError: false, updating: false })
    window.location.href = '/'
  }

  render() {
    if (!this.state.hasError) return this.props.children

    if (this.state.updating) {
      return (
        <div role="status" className="min-h-screen bg-gradient-to-br from-parchment-100 via-sage-50 to-madder-100 flex items-center justify-center px-4">
          <p className="text-sm text-gray-500">{i18n.t('errorBoundary.updating')}</p>
        </div>
      )
    }

    return (
      <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-sage-50 to-madder-100 flex items-center justify-center px-4">
        <div className="text-center max-w-sm">
          <AgnusDeiMark className="w-16 h-16 mx-auto mb-4" />
          <p className="text-sage-600 font-display text-lg font-semibold">
            <BedeWordmark />
          </p>
          <p className="text-sm text-gray-500 mt-2 mb-6">
            {i18n.t('errorBoundary.message')}
          </p>
          <button
            onClick={this.handleReload}
            className="inline-flex items-center gap-2 px-5 py-3 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors"
          >
            <RotateCcw size={16} /> {i18n.t('errorBoundary.returnToLogin')}
          </button>
        </div>
      </div>
    )
  }
}
