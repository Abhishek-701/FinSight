"""Phase 3 — central config. All tunables live here (G7: non-obvious values logged in DECISIONS.md)."""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load OPENAI_API_KEY + ANTHROPIC_API_KEY from .env before any client init

# --- Models ---
EMBED_MODEL = "text-embedding-3-small"   # OpenAI; Anthropic has no embeddings API
CHAT_MODEL = "claude-sonnet-4-6"         # temp-0 capable (Opus 4.8 removed `temperature`); see DECISIONS.md
TEMPERATURE = 0                          # determinism (G5)

# --- Retrieval ---
TOP_K_SINGLE = 6          # single-company question
TOP_K_SUB = 4             # per sub-query when decomposed
RRF_K = 60                # reciprocal-rank-fusion constant (standard default)
MAX_CONTEXT_CHUNKS = 24   # token/cost cap per question (G12)

# --- Refusal gate ---
# Threshold on the NORMALIZED DENSE similarity (cosine) of the top retrieved chunk.
# Out-of-corpus questions (e.g. "Tesla's revenue") score low here. Provisionally calibrated from
# the Phase-3 probe scores (DECISIONS.md): Tesla 0.487 (out) vs KO-attrition 0.518 (in) vs real
# hits 0.61-0.70. 0.50 sits in the gap. Phase 6 refines with the user's eval probes.
DENSE_SIM_THRESHOLD = 0.50

# --- Decomposition ---
FANOUT_CAP = 12           # max sub-queries; beyond this, answer primary metric + state what was dropped

# --- Storage ---
_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = _ROOT / "data" / "chunks.json"
CHROMA_DIR = str(_ROOT / "data" / "chroma")
COLLECTION = "filings"

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
