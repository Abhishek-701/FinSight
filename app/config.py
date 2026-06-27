"""Central config. All tunables live here (G7: non-obvious values logged in DECISIONS.md)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load OPENAI_API_KEY + ANTHROPIC_API_KEY from .env before any client init

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Models ---
EMBED_MODEL = "text-embedding-3-small"   # OpenAI; Anthropic has no embeddings API
CHAT_MODEL = "claude-sonnet-4-6"         # temp-0 capable (Opus 4.8 removed `temperature`); see DECISIONS.md
TEMPERATURE = 0                          # determinism (G5)

# --- Retrieval ---
TOP_K_SINGLE = 6          # single-company question
TOP_K_SUB = 8             # per sub-query when decomposed (raised 4->8: at 4 the consolidated
                          # income-statement chunk fell outside range, so comparisons grabbed
                          # segment/MD&A figures instead — see DECISIONS "eval-driven fix")
RRF_K = 60                # reciprocal-rank-fusion constant (standard default)
MAX_CONTEXT_CHUNKS = 24   # token/cost cap per question (G12)

# --- Refusal gate ---
# Threshold on the NORMALIZED DENSE similarity (cosine) of the top retrieved chunk.
# Out-of-corpus questions (e.g. "Tesla's revenue") score low here. Provisionally calibrated from
# the Phase-3 probe scores (DECISIONS.md): Tesla 0.487 (out) vs KO-attrition 0.518 (in) vs real
# hits 0.61-0.70. 0.50 sits in the gap. Phase 6 refines with the user's eval probes.
DENSE_SIM_THRESHOLD = 0.50

# --- Reranker (Phase 5, toggleable) ---
# Cross-encoder rerank of the fused candidate pool. Fixes buried-table-row retrieval (a
# consolidated total sitting among many numeric rows that prose outranks). Toggle to compare.
USE_RERANKER = True
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_POOL = 30          # fuse this many candidates, rerank them, then take top-k

# --- Decomposition ---
FANOUT_CAP = 12           # max sub-queries; beyond this, answer primary metric + state what was dropped

# --- Agent/tool execution ---
AGENT_MAX_STEPS = 8

# --- Market data ---
MARKET_PROVIDER = "yfinance"
MARKET_CACHE_TTL_SECONDS = 60
MARKET_HISTORY_CACHE_TTL_SECONDS = 300
MARKET_HISTORY_ROWS = 8
MARKET_INTENT_RE = (
    r"\b(stock price|share price|current price|quote|trading|market cap|market capitalization|"
    r"last close|previous close|52.week|pe ratio|p/e|price)\b"
)
MARKET_DISCLAIMER = "Market data is provided by yfinance and may be delayed; not investment advice."

# --- API / production controls ---
API_KEY = os.getenv("FAIRWAY_API_KEY", "")
RATE_LIMIT_PER_MINUTE = int(os.getenv("FAIRWAY_RATE_LIMIT_PER_MINUTE", "60"))

# --- Storage ---
_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = _ROOT / "data" / "chunks.json"
CHROMA_DIR = str(_ROOT / "data" / "chroma")
COLLECTION = "filings"
SESSION_DB_PATH = _ROOT / "data" / "sessions.sqlite3"

# --- XBRL fact store ---
FACTS_PATH = _ROOT / "data" / "facts.json"

# Concept map: canonical metric name -> list of XBRL concept(s) to try, per ticker.
# Key "_default" applies to any ticker not listed explicitly.
# Verified against probe data from all six filings (see DECISIONS.md Fix D).
#
# Per-ticker overrides are required for:
#   revenue  — AAPL uses RevenueFromContractWithCustomerExcludingAssessedTax (total = Products+Services);
#              JPM uses RevenuesNetOfInterestExpense (banks report net of funding cost);
#              all others use us-gaap:Revenues.
#   net_income — CAT's consolidated income is ProfitLoss (8,882); NetIncomeLoss is absent at c-1.
#   provision_credit_loss — JPM-specific; not applicable to others (mapped to []).
#
# All concept lists are ordered: first match wins (try primary concept, fall back to alt).
XBRL_CONCEPT_MAP: dict[str, dict[str, list[str]]] = {
    "revenue": {
        "AAPL": ["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"],
        "JPM":  ["us-gaap:RevenuesNetOfInterestExpense"],
        "_default": ["us-gaap:Revenues"],
    },
    "operating_income": {
        "_default": ["us-gaap:OperatingIncomeLoss"],
    },
    "net_income": {
        "CAT": ["us-gaap:ProfitLoss"],                   # NetIncomeLoss absent at consolidated level
        "_default": ["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"],
    },
    "operating_cash_flow": {
        "_default": ["us-gaap:NetCashProvidedByUsedInOperatingActivities"],
    },
    "eps_basic": {
        "_default": ["us-gaap:EarningsPerShareBasic"],
    },
    "eps_diluted": {
        "_default": ["us-gaap:EarningsPerShareDiluted"],
    },
    "r_and_d": {
        "_default": ["us-gaap:ResearchAndDevelopmentExpense"],
    },
    "provision_credit_loss": {
        "JPM": ["us-gaap:ProvisionForLoanLeaseAndOtherLosses"],
        "_default": [],                                  # not applicable outside banking
    },
}

# Keyword patterns that map a question fragment to a canonical metric name.
# Matched case-insensitively, in order. First match wins.
# Used by xbrl_lookup() in main.py to detect numeric intent without an LLM.
XBRL_KEYWORD_MAP: list[tuple[str, str]] = [
    (r"provision.{0,30}(credit|loan)", "provision_credit_loss"),
    (r"operating\s+(income|profit|earn)", "operating_income"),
    (r"operating\s+cash\s+flow|cash.{0,20}operat", "operating_cash_flow"),
    (r"net\s+(income|earn|profit)|profit.{0,10}loss", "net_income"),
    (r"r\s*&\s*d|research.{0,20}develop", "r_and_d"),
    (r"eps|earnings?\s+per\s+share|basic\s+earn", "eps_basic"),
    (r"diluted\s+(eps|earn)", "eps_diluted"),
    (r"(total\s+)?(net\s+)?(revenue|sales|top.line)", "revenue"),
]

# --- Companies + router alias map (regex/alias routing, no LLM — for explainability + determinism) ---
COMPANIES = {
    "AAPL": "Apple", "JPM": "JPMorgan Chase", "WMT": "Walmart",
    "KO": "Coca-Cola", "NVDA": "NVIDIA", "CAT": "Caterpillar",
}
# Lowercased alias -> ticker. Matched as whole words (case-insensitive) in router.py.
ALIASES = {
    "apple": "AAPL", "aapl": "AAPL",
    "jpmorgan": "JPM", "jp morgan": "JPM", "jpmorgan chase": "JPM", "chase": "JPM", "jpm": "JPM",
    "walmart": "WMT", "wal-mart": "WMT", "wmt": "WMT",
    "coca-cola": "KO", "coca cola": "KO", "coke": "KO", "ko": "KO",
    "nvidia": "NVDA", "nvda": "NVDA",
    "caterpillar": "CAT", "cat": "CAT",
}
