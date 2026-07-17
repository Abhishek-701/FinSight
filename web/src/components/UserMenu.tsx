import type { AuthUser } from '../lib/types'

export default function UserMenu({
  user,
  loading,
  onLogin,
  onLogout,
}: {
  user: AuthUser | null
  loading: boolean
  onLogin: () => void
  onLogout: () => void
}) {
  if (loading) return null

  if (!user) {
    return (
      <button className="user-menu-login" onClick={onLogin}>
        Sign in with Google
      </button>
    )
  }

  return (
    <div className="user-menu">
      {user.picture ? (
        <img className="user-menu-avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />
      ) : (
        <span className="user-menu-avatar user-menu-avatar-fallback">
          {(user.name || user.email)[0]?.toUpperCase()}
        </span>
      )}
      <span className="user-menu-name">{user.name || user.email}</span>
      <button className="user-menu-logout" onClick={onLogout}>
        Sign out
      </button>
    </div>
  )
}
