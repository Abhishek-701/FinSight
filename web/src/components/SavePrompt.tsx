export default function SavePrompt({
  show,
  onLogin,
  onDismiss,
}: {
  show: boolean
  onLogin: () => void
  onDismiss: () => void
}) {
  if (!show) return null

  return (
    <div className="save-prompt-banner">
      You're browsing as a guest. Sign in to keep your portfolio, watchlist, and chats across devices.
      <span className="save-prompt-banner-actions">
        <button className="save-prompt-signin" onClick={onLogin}>
          Sign in
        </button>
        <button className="save-prompt-dismiss" onClick={onDismiss}>
          Dismiss
        </button>
      </span>
    </div>
  )
}
