# Eval results

Generated 2026-06-10 - model `claude-sonnet-4-6` - dense-similarity threshold 0.5

Grades are BLANK by design (G4 — fill these in by hand):
- **correct** = the figure/claim is right
- **grounded** = it cited the passage that actually contains the answer
- **refusal-correct** = it refused iff it should have

| # | cat | question | route | refused | reason | top_sim | citations | gaps | correct | grounded | refusal-correct |
|---|-----|----------|-------|---------|--------|---------|-----------|------|---------|----------|-----------------|
| 1 | lookup | What were Coca-Cola's net operating revenues for fiscal year 2024? | single | no |  | 0.756 | KO-0117, KO-0280 |  |  |  |  |
| 2 | lookup | What were Walmart's total assets at the end of its most recent fiscal year? | single | no |  | 0.678 | WMT-0063, WMT-0185 |  |  |  |  |
| 3 | comparison | Which of these companies reported the highest total revenue in its most recent fiscal year, and what were the figures? | decompose | no |  | 0.716 | CAT-0114, JPM-0220, KO-0280, NVDA-0062, WMT-0182 | Apple |  |  |  |
| 4 | units | What was Apple's diluted weighted-average share count for fiscal 2025? | single | no |  | 0.694 | AAPL-0059, AAPL-0074 |  |  |  |  |
| 5 | fiscal_year | Compare Walmart's and Coca-Cola's most recent annual total revenue. What period does each figure cover? | decompose | no |  | 0.656 | KO-0117, WMT-0099 |  |  |  |  |
| 6 | footnote | What does NVIDIA's most recent 10-K disclose about customer concentration, and what portion of revenue did its largest customer(s) represent? | single | no |  | 0.694 | NVDA-0141, NVDA-0177, NVDA-0178 |  |  |  |  |
| 7 | precision | What was Caterpillar's total sales and revenues, and separately its profit (net income), for 2024? | single | no |  | 0.716 | CAT-0114 |  |  |  |  |
| 8 | refusal_oos | What was Microsoft's total revenue in its latest fiscal year? | oos | yes | threshold | 0.454 |  |  |  |  |  |
| 9 | refusal_undisclosed | What is JPMorgan Chase's customer Net Promoter Score (NPS)? | single | no |  | 0.548 |  | JPMorgan Chase |  |  |  |


## Answers (for grading)

### 1. What were Coca-Cola's net operating revenues for fiscal year 2024?
- **category:** lookup  |  **route:** single  |  **refused:** False ()  |  **top_sim:** 0.756
- **your note:** Income-statement top line. Coca-Cola labels it 'Net operating revenues', not 'Revenue', so this also tests terminology. Record the exact figure + units (millions) from Item 8.
- **sub-queries:**
  - KO: sim=0.756  q="What were Coca-Cola's net operating revenues for fiscal year 2024?"
- **citations:** KO-0117, KO-0280  |  **gaps:** (none)

**Answer:**

Coca-Cola's net operating revenues for fiscal year 2024 (year ended December 31, 2024) were **$47,061 million** [KO-0117][KO-0280].

---

### 2. What were Walmart's total assets at the end of its most recent fiscal year?
- **category:** lookup  |  **route:** single  |  **refused:** False ()  |  **top_sim:** 0.678
- **your note:** Balance-sheet lookup â€” confirms the system reads statements beyond the income statement. Record the figure + units.
- **sub-queries:**
  - WMT: sim=0.678  q="What were Walmart's total assets at the end of its most recent fiscal year?"
- **citations:** WMT-0063, WMT-0185  |  **gaps:** (none)

**Answer:**

Walmart's total consolidated assets at the end of its most recent fiscal year (January 31, 2026) were **$284,668 million** [WMT-0185][WMT-0063].

---

### 3. Which of these companies reported the highest total revenue in its most recent fiscal year, and what were the figures?
- **category:** comparison  |  **route:** decompose  |  **refused:** False ()  |  **top_sim:** 0.716
- **your note:** Fans out across all six. A correct answer must also state each company's fiscal-year-end, since the periods are not the same. Fill in the six top-line figures from each Item 8 to grade. Watch terminology: Apple 'net sales', Coca-Cola 'net operating revenues', Caterpillar 'total sales and revenues', JPMorgan 'total net revenue'.
- **sub-queries:**
  - AAPL: sim=0.646  q="What was Apple's total revenue in its most recent fiscal year as reported in its 10-K?"
  - JPM: sim=0.716  q="What was JPMorgan Chase's total revenue (net revenue) in its most recent fiscal year as reported in its 10-K?"
  - WMT: sim=0.687  q="What was Walmart's total revenue in its most recent fiscal year as reported in its 10-K?"
  - KO: sim=0.696  q="What was Coca-Cola's total revenue (net revenues) in its most recent fiscal year as reported in its 10-K?"
  - NVDA: sim=0.699  q="What was NVIDIA's total revenue in its most recent fiscal year as reported in its 10-K?"
  - CAT: sim=0.693  q="What was Caterpillar's total revenue (total sales and revenues) in its most recent fiscal year as reported in its 10-K?"
- **citations:** CAT-0114, JPM-0220, KO-0280, NVDA-0062, WMT-0182  |  **gaps:** Apple

**Answer:**

Based on the provided filings, here are the most recent fiscal year total revenues for each company:

1. **Walmart** (FY ended January 31, 2026): Total revenues of **$485,599 million** [WMT-0182]
2. **NVIDIA** (FY ended January 25, 2026): Total revenue of **$215,938 million** [NVDA-0062]
3. **Caterpillar** (FY ended December 31, 2025): Total sales and revenues of **$67,589 million** [CAT-0114]
4. **Coca-Cola** (FY ended December 31, 2025): Net operating revenues of **$47,941 million** [KO-0280]
5. **Apple** (FY ended September 27, 2025): Not found in the provided filings for Apple as a single consolidated revenue total.
6. **JPMorgan Chase** (FY ended December 31, 2025): Total net revenue of **$185,581 million** [JPM-0220]

**Walmart reported the highest total revenue** among the companies with available figures, at **$485,599 million** for its fiscal year ended January 31, 2026 [WMT-0182].

---

### 4. What was Apple's diluted weighted-average share count for fiscal 2025?
- **category:** units  |  **route:** single  |  **refused:** False ()  |  **top_sim:** 0.694
- **your note:** Trap: on Apple's income statement, dollars are in millions but share counts are in THOUSANDS. A system that stamps one 'in millions' label on the whole table is off by 1000x. Verify the scale on the face of the statement and record the correct number + unit.
- **sub-queries:**
  - AAPL: sim=0.694  q="What was Apple's diluted weighted-average share count for fiscal 2025?"
- **citations:** AAPL-0059, AAPL-0074  |  **gaps:** (none)

**Answer:**

Apple's diluted weighted-average share count for fiscal 2025 was **15,004,697 thousand shares** [AAPL-0074][AAPL-0059].

---

### 5. Compare Walmart's and Coca-Cola's most recent annual total revenue. What period does each figure cover?
- **category:** fiscal_year  |  **route:** decompose  |  **refused:** False ()  |  **top_sim:** 0.656
- **your note:** Walmart's FY ends ~Jan 31, 2025; Coca-Cola's ends Dec 31, 2024. Correct answer must flag that the two figures cover DIFFERENT periods and not present them as the same year. Record both figures.
- **sub-queries:**
  - WMT: sim=0.656  q="What was Walmart's most recent annual total revenue, and what fiscal period does this figure cover?"
  - KO: sim=0.654  q="What was Coca-Cola's most recent annual total revenue, and what fiscal period does this figure cover?"
- **citations:** KO-0117, WMT-0099  |  **gaps:** (none)

**Answer:**

## Revenue Comparison: Walmart vs. Coca-Cola (Most Recent Annual Figures)

**Walmart**
- **Total Revenues: $713,163 million** for the fiscal year ended **January 31, 2026** [WMT-0099]

**Coca-Cola**
- **Net Operating Revenues: $47,941 million** for the fiscal year ended **December 31, 2025** [KO-0117]

---

### Summary

| Company | Most Recent Revenue | Fiscal Year End |
|---|---|---|
| Walmart | $713,163 million | January 31, 2026 |
| Coca-Cola | $47,941 million | December 31, 2025 |

Walmart's total revenues are approximately **14.9× larger** than Coca-Cola's net operating revenues. Note that the two figures are not perfectly comparable in timing (Walmart's fiscal year ends in late January, Coca-Cola's in December) and also differ in business model — Walmart reports retail sales plus membership/other income, while Coca-Cola reports net operating revenues from beverage concentrate and finished product operations.

---

### 6. What does NVIDIA's most recent 10-K disclose about customer concentration, and what portion of revenue did its largest customer(s) represent?
- **category:** footnote  |  **route:** single  |  **refused:** False ()  |  **top_sim:** 0.694
- **your note:** Note/MD&A-driven (concentration of revenue, significant customers). The percentage is meaningless without the surrounding disclosure. VERIFY the exact wording/figure exists in NVIDIA's filing; if phrased differently (e.g. 'one customer accounted for ~X%'), match it. Tests whether the system surfaces the qualifier, not just a bare number.
- **sub-queries:**
  - NVDA: sim=0.694  q="What does NVIDIA's most recent 10-K disclose about customer concentration, and what portion of revenue did its largest customer(s) represent?"
- **citations:** NVDA-0141, NVDA-0177, NVDA-0178  |  **gaps:** (none)

**Answer:**

## NVIDIA Customer Concentration Disclosure (Fiscal Year 2026, ended January 25, 2026)

### Revenue Concentration

NVIDIA's most recent 10-K discloses significant customer concentration risk, noting that "revenue is concentrated among a limited number of direct and indirect customers and this trend may continue" [NVDA-0178].

**Direct Customer Revenue Concentration for Fiscal Year 2026:**
- **Largest direct customer:** represented **22% of total revenue**
- **Second largest direct customer:** represented **14% of total revenue**
- Both were primarily attributable to the **Compute & Networking segment** [NVDA-0178]

For context, in fiscal year 2025, one direct customer represented 12% and two others each represented 11% of total revenue; in fiscal year 2024, one direct customer represented 13% of total revenue [NVDA-0178].

### Accounts Receivable Concentration

As of January 25, 2026, **three direct customers** accounted for **25%, 18%, and 13%** of NVIDIA's accounts receivable balance, respectively [NVDA-0141].

### Geographic Revenue Concentration

Revenue from customers headquartered **outside the United States** accounted for only **31%** of total revenue in fiscal year 2026 (down from 41% in FY2025 and 48% in FY2024), reflecting increasing U.S.-based Compute & Networking demand [NVDA-0178]. Total revenue for fiscal year 2026 was **$215,938 million**, with **$149,617 million** from U.S.-headquartered customers [NVDA-0177].

---

### 7. What was Caterpillar's total sales and revenues, and separately its profit (net income), for 2024?
- **category:** precision  |  **route:** single  |  **refused:** False ()  |  **top_sim:** 0.716
- **your note:** Tests whether the system confuses the top line ('total sales and revenues') with the bottom line ('profit'/'net income'). Both are on the income statement; record both exact figures. A precisely-cited but wrong-concept answer is the failure to watch for.
- **sub-queries:**
  - CAT: sim=0.716  q="What was Caterpillar's total sales and revenues, and separately its profit (net income), for 2024?"
- **citations:** CAT-0114  |  **gaps:** (none)

**Answer:**

Based on the provided filings (fiscal year ending December 31, 2024):

- **Total Sales and Revenues (2024):** $64,809 million [CAT-0114]

- **Profit (Net Income) attributable to Caterpillar (2024):** The filings report "Profit of consolidated and affiliated companies" of **$10,788 million** in 2024 [CAT-0114]. (Note: This represents profit of consolidated and affiliated companies; a separate minority interest breakdown is not provided in the excerpts above.)

---

### 8. What was Microsoft's total revenue in its latest fiscal year?
- **category:** refusal_oos  |  **route:** oos  |  **refused:** True (threshold)  |  **top_sim:** 0.454
- **your note:** Microsoft is NOT in the corpus. Expected: refuse via the threshold gate (no relevant chunks retrieved). Grade refusal-correct, not a number.
- **sub-queries:**
  - None: sim=0.454  q="What was Microsoft's total revenue in its latest fiscal year?"
- **citations:** (none)  |  **gaps:** (none)

**Answer:**

I couldn't find this in the six filings I cover (Apple, JPMorgan Chase, Walmart, Coca-Cola, NVIDIA, Caterpillar), so I can't answer it.

---

### 9. What is JPMorgan Chase's customer Net Promoter Score (NPS)?
- **category:** refusal_undisclosed  |  **route:** single  |  **refused:** False ()  |  **top_sim:** 0.548
- **your note:** JPMorgan IS covered, but a 10-K does not report NPS. Retrieval WILL return JPMorgan chunks that lack the answer, so the threshold won't fire â€” this must be caught by the synthesis/gaps gate stating 'not found', not a guess. Grade refusal-correct. This is the hardest refusal case.
- **sub-queries:**
  - JPM: sim=0.548  q="What is JPMorgan Chase's customer Net Promoter Score (NPS)?"
- **citations:** (none)  |  **gaps:** JPMorgan Chase

**Answer:**

Not found in the provided filings for JPMorgan Chase.
