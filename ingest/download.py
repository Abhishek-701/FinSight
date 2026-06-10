"""Phase 1 — download the latest 10-K primary document for six companies from SEC EDGAR.

Flow per company:
  ticker -> CIK (company_tickers.json) -> submissions JSON -> newest form == "10-K"
  -> fetch primary document HTML -> data/raw/{TICKER}.html

EDGAR etiquette (G11): real User-Agent, rate-limited, cached (no refetch if file exists).
No synthetic fallback (G3): if a fetch fails we raise and report, never fabricate.
"""

import json
import time
import urllib.request
from pathlib import Path

# SEC requires a genuine identifying User-Agent (fair-access policy).
USER_AGENT = "Abhishek <walvekarabhishek701@gmail.com>"
REQUEST_SLEEP_S = 0.2  # <= 10 req/s; we stay well under.

TICKERS = ["AAPL", "JPM", "WMT", "KO", "NVDA", "CAT"]

RAW_DIR = Path("data/raw")
MANIFEST_PATH = Path("data/manifest.json")
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"


def _get(url: str) -> bytes:
    """One rate-limited GET with the required headers. Raises on HTTP error."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    time.sleep(REQUEST_SLEEP_S)
    return data


def load_cik_map() -> dict[str, str]:
    """ticker (upper) -> 10-digit zero-padded CIK string."""
    raw = json.loads(_get(TICKER_MAP_URL))
    out = {}
    for entry in raw.values():
        out[entry["ticker"].upper()] = str(entry["cik_str"]).zfill(10)
    return out


def latest_10k(cik: str) -> dict:
    """Return metadata for the most recent form exactly '10-K' (rejects 10-K/A amendments)."""
    subs = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    recent = subs["filings"]["recent"]
    forms = recent["form"]
    # recent.* are parallel arrays ordered newest-first.
    for i, form in enumerate(forms):
        if form == "10-K":  # exact match: "10-K/A" amendments are excluded.
            accession = recent["accessionNumber"][i]
            return {
                "form": form,
                "accession": accession,
                "accession_nodash": accession.replace("-", ""),
                "filing_date": recent["filingDate"][i],
                "primary_doc": recent["primaryDocument"][i],
            }
    raise RuntimeError(f"No 10-K found in recent filings for CIK {cik}")


def doc_url(cik: str, meta: dict) -> str:
    cik_int = int(cik)  # archive path uses the un-padded CIK.
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
        f"{meta['accession_nodash']}/{meta['primary_doc']}"
    )


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cik_map = load_cik_map()
    manifest = []

    for ticker in TICKERS:
        if ticker not in cik_map:
            raise RuntimeError(f"Ticker {ticker} not found in EDGAR company_tickers.json")
        cik = cik_map[ticker]
        meta = latest_10k(cik)
        url = doc_url(cik, meta)
        out_path = RAW_DIR / f"{ticker}.html"

        if out_path.exists():
            print(f"[cache] {ticker}: {out_path} already present, skipping download")
        else:
            print(f"[fetch] {ticker}: {url}")
            html = _get(url)
            out_path.write_bytes(html)

        size = out_path.stat().st_size
        print(
            f"   {ticker}  CIK={cik}  acc={meta['accession']}  "
            f"filed={meta['filing_date']}  {size:,} bytes"
        )
        manifest.append({
            "ticker": ticker,
            "cik": cik,
            "form": meta["form"],
            "accession": meta["accession"],
            "filing_date": meta["filing_date"],
            "primary_doc": meta["primary_doc"],
            "source_url": url,
            "raw_path": str(out_path),
            "bytes": size,
        })

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
