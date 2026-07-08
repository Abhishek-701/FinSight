import type { ChatWindow } from '../hooks/useChat'
import { titleFromQuestion } from '../lib/format'
import type { View } from '../lib/types'

interface Props {
  view: View
  chatWindows: ChatWindow[]
  recentSearches: string[]
  sessionId: string | null
  isBusy: boolean
  onNavigate: (view: View) => void
  onNewChat: () => void
  onSwitchChat: (id: string) => void
  onRecentClick: (q: string) => void
}

const NAV_ITEMS: { view: View; label: string }[] = [
  { view: 'chat', label: 'Chat' },
  { view: 'screener', label: 'Screener' },
  { view: 'compare', label: 'Compare' },
  { view: 'portfolio', label: 'Portfolio' },
  { view: 'insight', label: 'Insight' },
]

export default function Sidebar({
  view,
  chatWindows,
  recentSearches,
  sessionId,
  isBusy,
  onNavigate,
  onNewChat,
  onSwitchChat,
  onRecentClick,
}: Props) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="logo">F</div>
        <div>
          FinSight
          <small>AI financial assistant</small>
        </div>
      </div>
      <nav className="nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.view}
            className={view === item.view ? 'active' : ''}
            disabled={isBusy}
            onClick={() => onNavigate(item.view)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {view === 'chat' && (
        <>
          <div>
            <button className="new-chat-btn" disabled={isBusy} onClick={onNewChat}>
              + New Chat
            </button>
          </div>
          <div>
            <div className="section-title">Chat Windows</div>
            <div className="chat-list">
              {chatWindows.length === 0 && (
                <button className="chat-window" disabled>
                  <b>No chats yet</b>
                  <span>Ask a question to start</span>
                </button>
              )}
              {chatWindows.map((chat) => (
                <button
                  key={chat.id}
                  className={`chat-window ${chat.id === sessionId ? 'active' : ''}`}
                  disabled={isBusy}
                  onClick={() => onSwitchChat(chat.id)}
                >
                  <b>{chat.title}</b>
                  <span>
                    {new Date(chat.updated_at).toLocaleString([], {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="recent">
            <div className="section-title">Recent Searches</div>
            {recentSearches.map((q) => (
              <button key={q} disabled={isBusy} onClick={() => onRecentClick(q)}>
                {titleFromQuestion(q)}
              </button>
            ))}
          </div>
        </>
      )}
    </aside>
  )
}
