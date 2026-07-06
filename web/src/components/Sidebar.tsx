import type { ChatWindow } from '../hooks/useChat'
import { titleFromQuestion } from '../lib/format'

interface Props {
  chatWindows: ChatWindow[]
  recentSearches: string[]
  sessionId: string | null
  isBusy: boolean
  onNewChat: () => void
  onSwitchChat: (id: string) => void
  onRecentClick: (q: string) => void
}

export default function Sidebar({
  chatWindows,
  recentSearches,
  sessionId,
  isBusy,
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
        <button className="active" disabled={isBusy} onClick={onNewChat}>
          New Chat
        </button>
      </nav>
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
    </aside>
  )
}
