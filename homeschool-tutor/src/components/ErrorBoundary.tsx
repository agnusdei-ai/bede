import { Component, type ErrorInfo, type ReactNode } from 'react'
import { RotateCcw } from 'lucide-react'
import { AgnusDeiMark, BedeWordmark } from './BedeMark'
import i18n from '../i18n'
import { logDebug } from '../hooks/debugBus'
import { isChunkLoadError, releaseChanged, reloadOnceForNewRelease } from '../utils/staleBuild'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  /**
   * For a page file that failed to load (see utils/staleBuild.ts):
   * 'checking' while it asks the server whether a new release is out,
   * 'updating' once it is reloading to fetch one. Null for every other
   * outcome, which shows the recovery screen.
   */
  recovery: 'checking' | 'updating' | null
}

/**
 * Catches render-time exceptions anywhere below it so a single bad render
 * (e.g. malformed API data) shows a recoverable screen instead of a blank
 * tablet — this is a child-facing session, not a page a parent can debug.
 *
 * Two kinds of failure land here, and they are handled differently. A page
 * whose file could not be loaded may mean the tab is still running the
 * previous release (see utils/staleBuild.ts): the server is asked, and only
 * if it now serves a different release does the page reload, once, and
 * recover by itself. Any other error, and a failed page file with no new
 * release behind it, is recorded in the debug log, which is how a family
 * reports one, and the recovery screen is shown.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, recovery: null }

  static getDerivedStateFromError(error: unknown): State {
    return { hasError: true, recovery: isChunkLoadError(error) ? 'checking' : null }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
    const stale = isChunkLoadError(error)
    logDebug(`ERROR SCREEN ${stale ? 'page file failed to load' : 'render error'} ${error?.name ?? 'Error'}: ${error?.message ?? String(error)}`)
    if (stale) void this.recoverFromFailedPageFile()
  }

  private async recoverFromFailedPageFile() {
    if (await releaseChanged()) {
      if (reloadOnceForNewRelease()) {
        logDebug('ERROR SCREEN new release on the server; reloading once')
        this.setState({ recovery: 'updating' })
        return
      }
      // Already reloaded moments ago and the file is still missing: show
      // the recovery screen rather than reload forever.
      logDebug('ERROR SCREEN new release, but already reloaded within the guard window')
    } else {
      logDebug('ERROR SCREEN page file failed to load; release unchanged, not reloading')
    }
    this.setState({ recovery: null })
  }

  handleReload = () => {
    this.setState({ hasError: false, recovery: null })
    window.location.href = '/'
  }

  render() {
    if (!this.state.hasError) return this.props.children

    if (this.state.recovery) {
      return (
        <div role="status" className="min-h-screen bg-gradient-to-br from-parchment-100 via-sage-50 to-madder-100 flex items-center justify-center px-4">
          <p className="text-sm text-gray-500">{i18n.t(`errorBoundary.${this.state.recovery}`)}</p>
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
