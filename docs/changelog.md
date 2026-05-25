# Project changelog

Chronological record of what the project has actually done — methodology
changes, data refreshes, fixes, and major refactors. **This is the
canonical "current state" reference.** `docs/planning.md` retains the
historical phase narrative; this file is what you read to see what's
been built recently and what's currently in motion.

Each entry: date, branch, one-line summary, plus a short bullet list of
the substantive changes. Entries are newest first.

---

## 2026-05-25 — `feat/outlier-audit` (in progress)

Batch 2 of the post-V2025-refresh review: explicit outlier-detection
sections in every notebook that produces forecast inputs, plus a
cohort-level data-quality summary in Notebook 10.

- **Notebook 01 §4b** — statewide source-disagreement audit. Flags
  county-years where `(max - min) / max > 0.5%` across available
  sources. Top offender: Hamilton County (7-15% spread across multiple
  years). Cohort: Washington is the cleanest (17% of years flagged);
  Saratoga and Warren show ~38% (decennial-seam intercensal vs
  postcensal drift, which the reconciliation rule already handles).
- **Notebook 02 §2.6** — explicit identity-check thresholds:
  `|residual|/pop > 5‰`, plus births/deaths YoY changes > 20%.
  Surfaces the known PEP decennial-seam artifact (partial-year
  births at 2010/2020 → 4× "jump" at 2011/2021). Notebook 05 already
  works around this by using rate-based annualization.
- **Notebook 03 §2b** — across all 62 NY counties, gap between the
  4/1/2020 census enumeration and 7/1/2020 estimate. Cohort all
  within ±0.5%; small counties (Hamilton) and NYC boroughs are the
  outliers.
- **Notebook 05 §6b** — extreme ASFR scaling factor `k` and implied
  TFR. Real outliers surfaced: Tompkins County (Cornell U) at
  TFR ~0.75; Rockland County (Orthodox communities) at TFR ~3.3.
- **Notebook 07 §4b** — implausible per-cohort migration rates
  `|m_rate| > 20%/yr`. 1.3% of cells flagged; concentrated in small
  rural counties and college towns. Cohort counties: 0-2 flagged
  cells each (Washington 1).
- **Notebook 10 §5b** — cross-notebook outlier summary. Per-cohort-
  county table consolidating flag counts from all five audits, plus
  reading guide. Conclusion: cohort-county forecast inputs are clean;
  the constraining limitations are *methodological* (single net
  migration rate, scenario knobs, national ASFR pattern) rather
  than data-quality.

Status: in progress on the branch. Pushed once complete.

---

## 2026-05-25 — `feat/quickfixes-batch1` (merged to main `b384ab1`)

Batch 1 of the post-V2025-refresh review: quick wins, plus the
methodology book as the centerpiece.

- **`docs/methodology.md`** — new comprehensive reference: acronyms
  (ACS, ASFR, CCM, CCR, CWR, MCD, NCHS, NVSR, NYSDOH, NYSDOL, PEP, SYA,
  USALEEP, plus more); demographic notation (l(x), L(x), q(x), S(x),
  ω, P(x,t), CCR); plain-language method explanations (cohort-component
  projection, survival from life tables, Preston open-band formula,
  scaled fertility, residual migration, Hamilton-Perry, pro-rata
  constraint); data-source quick reference; methods-we-use vs
  methods-we-don't table.
- **NYSDOL vintage now reflects data publication, not retrieval.**
  Filenames carry both: `..._d20260401_r20260525.csv` = data
  published 2026-04-01, retrieved 2026-05-25. Parquet `vintage` column
  reads `nysdol_2026-04-01`. Loader's `_derive_vintage` parses the
  publication date; legacy single-date filenames fall back to
  `nysdol_retrieved_<date>`.
- **Forecast plots gain history + speculation emphasis.** Notebooks 08
  and 10: all forecast time-series plots now show reconciled history
  back to 2015 (~10 years of context). Years beyond 2035 are visually
  deemphasized via a faint grey band + "more speculative beyond 2035"
  annotation. Parquet retains full 2024-2050 horizon; only display
  changes.
- **"Headline" jargon removed** from plot titles and section headers
  ("Headline — Washington" → "Main projected trajectory — Washington").
- **ASFR documentation clarified** in notebook 05: explicit
  "national pattern, local level" walk-through with the small-N
  rationale (Washington has ~545 births / 30 reproductive ages = 18
  per age, too noisy to fit locally).
- **`Makefile`** — convenience targets: `make help | refresh-data |
  build-nb | run-all | test | export-final | all`. Uses
  `.venv/bin/python` directly.
- **`docs/workflow.md`** — clarified the decennial-year rule (every
  retained value is July-1; April-1 census enumerations stay in
  `population_all_sources` for QA only). Documented the ACS pull
  mechanism (hand-rolled wrapper, no third-party package, JSON cache
  layout). Documented the NYSDOL filename convention.
- **`docs/changelog.md`** — this file. New convention for "what we did
  recently"; `docs/planning.md` retains the historical phase narrative.

Status: in progress on the branch. Pushed once complete.

---

## 2026-05-24 — `feat/data-refresh-v2025` (merged to main `3111c0f`)

End-to-end pipeline refresh on the latest available upstream data.

- **Census PEP V2025** (`co-est2025-alldata.csv`, released 2026-03-26)
  replaces V2024 — extends totals + components of change through 2025.
- **Census SYA V2024** (`cc-est2024-syasex-36.csv`, released
  2025-06-26) replaces V2023 — extends age × sex through 2024.
  YEAR-code 6 added to the SYA loader (`_SYA_YEAR_MAP_V2024`).
- **Census V2025 subcounty** (`sub-est2025.csv`) dropped into
  `data_raw/` but unused by the pipeline currently (kept as a future
  hook for town-base anchoring).
- **NYSDOL** refreshed from data.ny.gov (now through 2025). Loader
  gains space-to-underscore column normalization for the direct-download
  header style.
- **`data_interim/county_agesex_1990_2023.parquet`** →
  **`county_agesex_1990_2024.parquet`** (one more year).
- **Forecast base year**: 2023 → 2024. Cohort-component run now
  2024-2050 (was 2023-2050).
- **Migration averaged over 4 year-pairs** (2020-21..2023-24) instead
  of 3.
- **Washington baseline 2050: 47,567** (was 45,342 from the 2023
  base) — less pessimistic, mostly because the 2023-24 year softened
  the residual-method migration average and partly because the base
  year shifted one year forward.
- **`download.py`** extended with `DownloadSpec`s for Census PEP +
  SYA + sub-est + NYSDOL so refreshes are one command.
- **130 tests passing** after refresh. SYA test fixtures updated to
  V2024 expectations.

Open follow-up (deferred to a separate branch): `feat/data-archival`
will add `data_raw/MANIFEST.toml` with SHA-256 hashes + URLs and
commit small foundational raw files inline for long-term
reproducibility against URL rot.

---

## Earlier work

For the original Phase 1-5 build (data reconciliation → external data
loaders → cohort-component engine → town forecasts → reporting),
see `docs/planning.md` (sections "Phase 1" through "Phase 5"). Those
sections document the original development; the changes since merge
to main are tracked in this file.
