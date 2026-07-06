import { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import Composer from './components/Composer'
import WatchlistPanel from './components/WatchlistPanel'
import ScreenerView from './components/ScreenerView'
import CompareView from './components/CompareView'
import PortfolioView from './components/PortfolioView'
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

  useEffect(() => {
    getCompanies()
      .then((res) => setCompanies(res.companies))
      .catch(() => setOnline(false))
  }, [])

  function handleNewChat() {
    setView('chat')
    newChat()
  }

  function handleCompare(tickers: string[]) {
    setCompareTickers(tickers)
    setView('compare')
  }

  const titles: Record<View, string> = {
    chat: 'Filings RAG + XBRL facts + market data',
    screener: 'Rank the six companies by financial and valuation metrics',
    compare: 'Side-by-side comparison',
    portfolio: 'Track your holdings and allocation',
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
          {view === 'chat' && <ChatView turns={turns} />}
          {view === 'screener' && <ScreenerView onCompare={handleCompare} />}
          {view === 'compare' && <CompareView tickers={compareTickers} />}
          {view === 'portfolio' && <PortfolioView companies={companies} />}
        </section>
        {view === 'chat' && <Composer isBusy={isBusy} onAsk={ask} onClear={newChat} />}
      </main>
      <WatchlistPanel companies={companies} />
    </div>
  )
}

export default App
