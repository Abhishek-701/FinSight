import { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import Composer from './components/Composer'
import WatchlistPanel from './components/WatchlistPanel'
import { useChat } from './hooks/useChat'
import { getCompanies } from './lib/api'
import './App.css'

function App() {
  const { sessionId, turns, isBusy, chatWindows, recentSearches, ask, newChat, switchChat } = useChat()
  const [companies, setCompanies] = useState<Record<string, string>>({})
  const [online, setOnline] = useState(true)

  useEffect(() => {
    getCompanies()
      .then((res) => setCompanies(res.companies))
      .catch(() => setOnline(false))
  }, [])

  return (
    <div className="app">
      <Sidebar
        chatWindows={chatWindows}
        recentSearches={recentSearches}
        sessionId={sessionId}
        isBusy={isBusy}
        onNewChat={newChat}
        onSwitchChat={switchChat}
        onRecentClick={ask}
      />
      <main className="main">
        <header className="topbar">
          <div className="title">
            <h1>FinSight</h1>
            <p>Filings RAG + XBRL facts + market data</p>
          </div>
          <div className="status">
            <span className="dot" style={{ background: online ? undefined : '#c0392b' }} />
            {online ? 'Online' : 'Offline'}
          </div>
        </header>
        <section className="workspace">
          <ChatView turns={turns} />
        </section>
        <Composer isBusy={isBusy} onAsk={ask} onClear={newChat} />
      </main>
      <WatchlistPanel companies={companies} />
    </div>
  )
}

export default App
