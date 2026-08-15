import type { View } from '../lib/types'

type Feature = {
  title: string
  blurb: string
  open?: Exclude<View, 'admin' | 'features'>
  tryQuestion?: string
  signIn?: boolean
}

const FEATURES: Feature[] = [
  {
    title: 'Chat',
    blurb: 'Ask about filings, XBRL facts, and delayed quotes. The tool plan shows before anything runs, then the answer streams in.',
    open: 'chat',
  },
  {
    title: 'Citations & sources',
    blurb: 'Every filing figure points at a chunk or XBRL fact. Click a cite to inspect the source. If the corpus cannot support the number, FinSight refuses.',
    tryQuestion: "What was Apple's revenue last quarter?",
  },
  {
    title: 'Add a company',
    blurb: 'A name that is not loaded yet can be fetched from EDGAR, parsed, and indexed in about a minute. Market-only questions skip that step.',
    tryQuestion: "What was Tesla's revenue last year?",
  },
  {
    title: 'Screener',
    blurb: 'Rank the universe by revenue, margins, growth, or valuation. Select names to compare or open an Insight brief.',
    open: 'screener',
  },
  {
    title: 'Compare',
    blurb: 'Overlay delayed price history for a few companies on one chart.',
    open: 'compare',
  },
  {
    title: 'Insight',
    blurb: 'One-page brief: quote, valuation versus peers, ranks, and a filing narrative for a single company.',
    open: 'insight',
  },
  {
    title: 'Watchlist',
    blurb: 'The right-hand panel keeps delayed quotes for names you star. Open Insight from any row.',
  },
  {
    title: 'Portfolio',
    blurb: 'Holdings, live value, P&L, concentration, and what-if trades. Nothing is executed.',
    open: 'portfolio',
  },
  {
    title: 'Sign in',
    blurb: 'Google is optional. Without it, portfolio, watchlist, and chat key off this browser. Sign in to claim that data onto an account.',
    signIn: true,
  },
]

interface Props {
  isBusy: boolean
  oauthConfigured: boolean
  onOpen: (view: View) => void
  onTry: (question: string) => void
  onLogin: () => void
}

export default function FeaturesView({ isBusy, oauthConfigured, onOpen, onTry, onLogin }: Props) {
  return (
    <div className="features-view">
      <div className="view-header">
        <h2>What FinSight can do</h2>
      </div>
      <p className="features-lede">
        Answers come from SEC filings, delayed market data, and your portfolio. Filing figures are
        cited. If the evidence is not there, the answer is a refusal, not a guess.
      </p>
      <div className="features-grid">
        {FEATURES.map((feature) => {
          const { open, tryQuestion } = feature
          const showSignIn = Boolean(feature.signIn && oauthConfigured)
          const hasActions = Boolean(open || tryQuestion || showSignIn)
          return (
            <article className="feature-card" key={feature.title}>
              <h3>{feature.title}</h3>
              <p>{feature.blurb}</p>
              {hasActions && (
                <div className="feature-card-actions">
                  {open && (
                    <button className="chip" disabled={isBusy} onClick={() => onOpen(open)}>
                      Open
                    </button>
                  )}
                  {tryQuestion && (
                    <button className="chip" disabled={isBusy} onClick={() => onTry(tryQuestion)}>
                      Try this
                    </button>
                  )}
                  {showSignIn && (
                    <button className="chip" onClick={onLogin}>
                      Sign in
                    </button>
                  )}
                </div>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}
