import { useCallback, useEffect, useRef, useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import Composer from './components/Composer'
import WatchlistPanel from './components/WatchlistPanel'
import ScreenerView from './components/ScreenerView'
import CompareView from './components/CompareView'
import PortfolioView from './components/PortfolioView'
import InsightView from './components/InsightView'
import AdminView from './components/AdminView'
import FeaturesView from './components/FeaturesView'
import UserMenu from './components/UserMenu'
import SavePrompt from './components/SavePrompt'
import { DEFAULT_PROMPTS, useChat } from './hooks/useChat'
import { useAuth } from './hooks/useAuth'
import { usePreferences } from './hooks/usePreferences'
import { getClientId } from './lib/clientId'
import { getCompanies, getPortfolio, getWatchlist } from './lib/api'
import type { View } from './lib/types'
import './App.css'

const SAVE_PROMPT_KEY = 'finsight_save_prompt_dismissed'

function App() {
  const { user, isAdmin, oauthConfigured, loading: authLoading, login, logout } = useAuth()
  const { prefs, ready: prefsReady, update: updatePrefs } = usePreferences(user, authLoading)
  const recentSearches = prefs.recent_searches?.length
    ? prefs.recent_searches
    : DEFAULT_PROMPTS.slice(0, 3)
  const { sessionId, turns, isBusy, chatWindows, ask, newChat, switchChat } = useChat({
    signedIn: !authLoading && !!user,
    recentSearches,
    onRecentSearches: (next) => updatePrefs({ recent_searches: next }),
  })
  const [companies, setCompanies] = useState<Record<string, string>>({})
  const [online, setOnline] = useState(true)
  const [view, setView] = useState<View>('chat')
  const [compareTickers, setCompareTickers] = useState<string[]>([])
  const [insightTicker, setInsightTicker] = useState<string | null>(null)
  const [authError, setAuthError] = useState(
    () => new URLSearchParams(window.location.search).get('auth_error') === '1'
  )
  const [hydrated, setHydrated] = useState(false)
  const didRestore = useRef(false)
  const [saveDismissed, setSaveDismissed] = useState(
    () => localStorage.getItem(SAVE_PROMPT_KEY) === '1'
  )
  const [hasAccountData, setHasAccountData] = useState(false)

  useEffect(() => {
    if (authError) {
      const url = new URL(window.location.href)
      url.searchParams.delete('auth_error')
      window.history.replaceState({}, '', url)
    }
  }, [authError])

  useEffect(() => {
    if (!prefsReady || didRestore.current) return
    didRestore.current = true
    // Stay on chat. Restoring last_view (screener, portfolio, …) after /api/auth/me
    // returns yanks the first-impression replay off screen a beat after mount.
    if (prefs.last_view === 'admin' && isAdmin) setView('admin')
    if (prefs.last_insight_ticker) setInsightTicker(prefs.last_insight_ticker)
    if (prefs.compare_tickers?.length) setCompareTickers(prefs.compare_tickers)
    setHydrated(true)
  }, [prefsReady, isAdmin, prefs])

  useEffect(() => {
    if (!hydrated) return
    const last_view = view === 'admin' && !isAdmin ? 'chat' : view
    updatePrefs({
      last_view,
      last_insight_ticker: insightTicker,
      compare_tickers: compareTickers,
    })
  }, [hydrated, view, insightTicker, compareTickers, isAdmin, updatePrefs])

  useEffect(() => {
    if (user || authLoading) return
    let cancelled = false
    const id = getClientId()
    Promise.all([getWatchlist(id), getPortfolio(id)])
      .then(([w, p]) => {
        if (!cancelled) setHasAccountData(w.items.length > 0 || p.items.length > 0)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [user, authLoading, view])

  const refreshCompanies = useCallback(() => {
    getCompanies()
      .then((res) => {
        setCompanies(res.companies)
        setOnline(true)
      })
      .catch(() => setOnline(false))
  }, [])

  useEffect(() => {
    refreshCompanies()
  }, [refreshCompanies])

  function handleCompanyAdded() {
    refreshCompanies()
  }

  function handleNewChat() {
    setView('chat')
    newChat()
  }

  function handleCompare(tickers: string[]) {
    setCompareTickers(tickers)
    setView('compare')
  }

  function handleInsight(ticker: string) {
    setInsightTicker(ticker)
    setView('insight')
  }

  function handleExplainPortfolio() {
    setView('chat')
    ask('Explain my portfolio today')
  }

  function handleDismissSave() {
    localStorage.setItem(SAVE_PROMPT_KEY, '1')
    setSaveDismissed(true)
  }

  const showSavePrompt =
    !user &&
    !authLoading &&
    oauthConfigured &&
    !saveDismissed &&
    (turns.length > 0 || chatWindows.length > 0 || hasAccountData)

  const titles: Record<View, string> = {
    chat: 'Filings RAG + XBRL facts + market data',
    screener: 'Rank the six companies by financial and valuation metrics',
    compare: 'Side-by-side comparison',
    portfolio: 'Track your holdings and allocation',
    insight: 'Quote, valuation, ranks, and filing narrative for one company',
    features: 'What each part of FinSight does',
    admin: 'Requests, latency, token spend, and refusal rate',
  }

  return (
    <div className="app">
      <Sidebar
        view={view}
        chatWindows={chatWindows}
        recentSearches={recentSearches}
        sessionId={sessionId}
        isBusy={isBusy}
        isAdmin={isAdmin}
        onNavigate={setView}
        onNewChat={handleNewChat}
        onSwitchChat={switchChat}
        onRecentClick={ask}
        onCompanyAdded={handleCompanyAdded}
      />
      <main className="main">
        <header className="topbar">
          <div className="title">
            <h1>FinSight</h1>
            <p>{titles[view]}</p>
          </div>
          <div className="topbar-right">
            <div className="status">
              <span className="dot" style={{ background: online ? undefined : '#c0392b' }} />
              {online ? 'Online' : 'Offline'}
            </div>
            <UserMenu
              user={user}
              loading={authLoading}
              oauthConfigured={oauthConfigured}
              onLogin={login}
              onLogout={logout}
            />
          </div>
        </header>
        {authError && (
          <div className="auth-error-banner">
            Google sign-in didn't complete — check that this site's URL is registered as an
            authorized redirect URI, or try again.
            <button onClick={() => setAuthError(false)}>Dismiss</button>
          </div>
        )}
        <SavePrompt show={showSavePrompt} onLogin={login} onDismiss={handleDismissSave} />
        <section className="workspace">
          {view === 'chat' && <ChatView turns={turns} onAsk={ask} onOpenFeatures={() => setView('features')} />}
          {view === 'screener' && <ScreenerView onCompare={handleCompare} onInsight={handleInsight} />}
          {view === 'compare' && <CompareView tickers={compareTickers} />}
          {view === 'portfolio' && <PortfolioView onExplain={handleExplainPortfolio} />}
          {view === 'insight' && <InsightView companies={companies} initialTicker={insightTicker} />}
          {view === 'features' && (
            <FeaturesView
              isBusy={isBusy}
              oauthConfigured={oauthConfigured}
              onOpen={setView}
              onTry={(q) => {
                setView('chat')
                ask(q)
              }}
              onLogin={login}
            />
          )}
          {view === 'admin' && isAdmin && <AdminView />}
        </section>
        {view === 'chat' && (
          <Composer isBusy={isBusy} onAsk={ask} onClear={newChat} onOpenFeatures={() => setView('features')} />
        )}
      </main>
      <WatchlistPanel companies={companies} onInsight={handleInsight} />
    </div>
  )
}

export default App
