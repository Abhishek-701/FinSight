import { useCallback, useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import Composer from './components/Composer'
import WatchlistPanel from './components/WatchlistPanel'
import ScreenerView from './components/ScreenerView'
import CompareView from './components/CompareView'
import PortfolioView from './components/PortfolioView'
import InsightView from './components/InsightView'
import { useChat } from './hooks/useChat'
import { getCompanies } from './lib/api'
import type { View } from './lib/types'
import './App.css'

function App() {
  const { sessionId, turns, isBusy, chatWindows, recentSearches, ask, newChat, switchChat } = useChat()
  const [companies, setCompanies] = useState<Record<string, string>>({})
  const [online, setOnline] = useState(true)
  const [view, setView] = useState<View>('chat')
  const [compareTickers, setCompareTickers] = useState<string[]>([])
  const [insightTicker, setInsightTicker] = useState<string | null>(null)

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

  const titles: Record<View, string> = {
    chat: 'Filings RAG + XBRL facts + market data',
    screener: 'Rank the six companies by financial and valuation metrics',
    compare: 'Side-by-side comparison',
    portfolio: 'Track your holdings and allocation',
    insight: 'Quote, valuation, ranks, and filing narrative for one company',
  }

  return (
    <div className="app">
      <Sidebar
        view={view}
        chatWindows={chatWindows}
        recentSearches={recentSearches}
        sessionId={sessionId}
        isBusy={isBusy}
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
          <div className="status">
            <span className="dot" style={{ background: online ? undefined : '#c0392b' }} />
            {online ? 'Online' : 'Offline'}
          </div>
        </header>
        <section className="workspace">
          {view === 'chat' && <ChatView turns={turns} onAsk={ask} />}
          {view === 'screener' && <ScreenerView onCompare={handleCompare} onInsight={handleInsight} />}
          {view === 'compare' && <CompareView tickers={compareTickers} />}
          {view === 'portfolio' && <PortfolioView companies={companies} />}
          {view === 'insight' && <InsightView companies={companies} initialTicker={insightTicker} />}
        </section>
        {view === 'chat' && <Composer isBusy={isBusy} onAsk={ask} onClear={newChat} />}
      </main>
      <WatchlistPanel companies={companies} onInsight={handleInsight} />
    </div>
  )
}

export default App
