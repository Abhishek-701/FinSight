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
# Off by default in deploy (FINSIGHT_USE_RERANKER=0): sentence-transformers/torch is excluded
# from requirements-deploy.txt to fit the free-tier 512MB RAM ceiling.
USE_RERANKER = os.getenv("FINSIGHT_USE_RERANKER", "1") == "1"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_POOL = 30          # fuse this many candidates, rerank them, then take top-k

# --- Decomposition ---
FANOUT_CAP = 12           # max sub-queries; beyond this, answer primary metric + state what was dropped

# --- Agent/tool execution ---
# 12 (was 8): decompose-mode screener questions can stack facts_lookup/multi_company_compare +
# screen_companies + up to 6 market_quote actions + synthesize_report; see DECISIONS "V2 screener".
AGENT_MAX_STEPS = 12
SEGMENT_INTENT_RE = (
    r"\b(segment|division|data\s+center|datacenter|sam'?s?\s*club|wholesale\s+club|"
    r"financial\s+products?|me&t)\b"
)
COMPOUND_INTENT_RE = r"\b(and|also|as well as|compare .* to|versus|vs\.?)\b"
COMPUTE_INTENT_RE = (
    r"\b(price.to.sales|p/s|market cap.{0,40}revenue|market capitalization.{0,40}revenue|"
    r"margin|ratio|percentage|percent|growth|change)\b"
)

# --- V3: hybrid LLM router + valuation/explain-move/insight intents ---
ROUTER_MODEL = os.getenv("FINSIGHT_ROUTER_MODEL", "claude-haiku-4-5")
USE_LLM_ROUTER = os.getenv("FINSIGHT_USE_LLM_ROUTER", "1") == "1"
ROUTER_MAX_TOKENS = 512
ROUTER_CACHE_TTL_SECONDS = 300

# Fires the LLM router for ambiguous mixed filing/market questions. Also split below into
# per-intent regexes used by the deterministic fallback path (router disabled, or LLM/validation
# failure) so both paths recognize the same vocabulary.
VALUATION_INTENT_RE = (
    r"\b(expensive|cheap|overvalued|undervalued|fairly\s+valued|valuation|"
    r"p/e|pe\s+ratio|price.to.earnings|p/s|price.to.sales|worth\s+buying)\b"
)
EXPLAIN_MOVE_INTENT_RE = (
    r"\b(why\s+(is|did|has|was)|what('s| is)\s+(behind|driving)|explain)\b"
    r".{0,60}\b(down|up|drop(ped)?|fell|fall(en)?|declin(e|ed|ing)|rall(y|ied)|surge[ds]?|"
    r"jump(ed)?|spike[ds]?|slid(e)?|sank|mov(e|ed|ing)|sell.?off)\b"
)
INSIGHT_INTENT_RE = r"\b(insight\s+brief|company\s+brief|full\s+(picture|brief|report)|deep\s+dive|snapshot)\b"
LLM_ROUTER_TRIGGER_RE = "|".join(
    (VALUATION_INTENT_RE, EXPLAIN_MOVE_INTENT_RE, INSIGHT_INTENT_RE)
)

INSIGHT_HISTORY_PERIOD = "3mo"     # trend window for the insight brief
VALUATION_FACT_METRICS = ["revenue", "net_income", "eps_diluted"]  # facts_lookup inputs for valuation plans

# --- Screener (V2) ---
# Ordered: first match wins. Checked BEFORE the more general COMPUTE_INTENT_RE-driven
# compute_metric path so "operating margin" etc. route to the multi-company screen_companies
# tool instead of the single-company market_cap_to_revenue compute tool.
SCREEN_METRIC_PATTERNS: list[tuple[str, str]] = [
    (r"\bnet\s+(profit\s+)?margins?\b", "net_margin"),
    (r"\b(operating\s+)?margins?\b", "operating_margin"),
    (r"\b(p/s|price.to.sales|ps\s+ratios?)\b", "ps_ratio"),
    (r"\b(revenue|sales)\s+growth\b|\bgrowth\b", "revenue_growth_yoy"),
    (r"\broe\b|return\s+on\s+equity", "roe"),
]
SCREEN_ORDER_ASC_RE = r"\b(lowest|smallest|least|worst|cheapest)\b"

# --- Market data ---
MARKET_PROVIDER = "yfinance"
MARKET_CACHE_TTL_SECONDS = 60
MARKET_HISTORY_CACHE_TTL_SECONDS = 300
MARKET_HISTORY_PERIODS = ("1mo", "3mo", "6mo", "1y")
# Caps only the tail embedded in the LLM-facing evidence TEXT (see build_market_chunk) so
# long periods (6mo/1y) don't bloat synthesis context; REST callers get the full row set.
MARKET_HISTORY_ROWS = 8
MARKET_INTENT_RE = (
    r"\b(stock price|share price|current price|quote|trading|market cap|market capitalization|"
    r"last close|previous close|52.week|pe ratio|p/e|price)\b"
)
MARKET_DISCLAIMER = "Market data is provided by yfinance and may be delayed; not investment advice."

# --- API / production controls ---
API_KEY = os.getenv("FINSIGHT_API_KEY", "")
RATE_LIMIT_PER_MINUTE = int(os.getenv("FINSIGHT_RATE_LIMIT_PER_MINUTE", "60"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")

# --- Storage ---
_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = _ROOT / "data" / "chunks.json"
CHROMA_DIR = str(_ROOT / "data" / "chroma")
COLLECTION = "filings"
SESSION_DB_PATH = _ROOT / "data" / "sessions.sqlite3"
AUDIT_LOG_PATH = _ROOT / "data" / "audit.jsonl"
WEB_DIST = _ROOT / "static" / "dist"  # built React SPA (Phase 3); falls back to static/index.html

# --- Dynamic (on-demand ingested) companies (V4.0+) ---
# Not committed to git — populated at runtime by the V4.1 ingest pipeline. Empty today, so
# app.universe currently just mirrors COMPANIES/ALIASES below (see app/universe.py).
DYNAMIC_DIR = _ROOT / "data" / "dynamic"
DYNAMIC_REGISTRY_PATH = DYNAMIC_DIR / "registry.json"
DYNAMIC_CHUNKS_DIR = DYNAMIC_DIR / "chunks"
DYNAMIC_FACTS_DIR = DYNAMIC_DIR / "facts"
DYNAMIC_CIK_MAP_PATH = DYNAMIC_DIR / "cik_map.json"

# --- On-demand ingest (V4.1: ingest/pipeline.py) ---
CIK_MAP_TTL_HOURS = 24
INGEST_MAX_RAW_MB = 30  # reject filings above this size (protects the 512MB deploy RAM ceiling)

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
    "assets": {
        "_default": ["us-gaap:Assets"],
    },
    "liabilities": {
        "_default": ["us-gaap:Liabilities"],
    },
    "equity": {
        "WMT": ["us-gaap:StockholdersEquity"],
        "_default": ["us-gaap:StockholdersEquity", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    },
    "long_term_debt": {
        "_default": ["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt"],
    },
    "capex": {
        "_default": ["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"],
    },
    "dividends_paid": {
        "_default": ["us-gaap:PaymentsOfDividends", "us-gaap:PaymentsOfDividendsCommonStock"],
    },
    "share_repurchases": {
        "_default": ["us-gaap:PaymentsForRepurchaseOfCommonStock"],
    },
    "income_tax_provision": {
        "_default": ["us-gaap:IncomeTaxExpenseBenefit"],
    },
}

# Keyword patterns that map a question fragment to a canonical metric name.
# Matched case-insensitively, in order. First match wins.
# Used by xbrl_lookup() in main.py to detect numeric intent without an LLM.
XBRL_KEYWORD_MAP: list[tuple[str, str]] = [
    (r"provision.{0,30}(credit|loan)", "provision_credit_loss"),
    (r"income\s+tax\s+(provision|expense)|tax\s+provision", "income_tax_provision"),
    (r"operating\s+(income|profit|earn)", "operating_income"),
    (r"operating\s+cash\s+flow|cash.{0,20}operat", "operating_cash_flow"),
    (r"capital\s+expenditures?|capex|property,\s*plant\s+and\s+equipment", "capex"),
    (r"dividends?\s+(paid|during)|paid\s+.*dividends?", "dividends_paid"),
    (r"repurchas.{0,30}(shares?|stock|common)|share\s+repurchases?", "share_repurchases"),
    (r"long.term\s+debt|debt\s+due\s+after\s+one\s+year", "long_term_debt"),
    (r"shareholders?'?\s+equity|stockholders?'?\s+equity|total\s+equity", "equity"),
    (r"total\s+assets?|assets\s+as\s+of", "assets"),
    (r"total\s+liabilities|liabilities\s+as\s+of", "liabilities"),
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
