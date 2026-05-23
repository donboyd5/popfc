# popfc — project rules and conventions

Durable rules for anyone (human or AI) working in this repo. These are not preferences — they are the operating contract. The full project plan, status, and phase details live in `docs/planning.md`; this file is the short list of things that always apply.

------------------------------------------------------------------------

## Git workflow

1. **Never work directly on `main`.** All commits — code AND docs — land on dedicated branches and only reach `main` via a branch merge.
2. **Code changes** go on a feature branch (`feat/...`, `fix/...`, etc.) in the primary working tree at `/home/donboyd5/Documents/python_projects/popfc/`.
3. **Docs changes** (anything under `docs/`, plus root-level docs like `README.md` and this file) go on the long-lived `docs/main` branch via the worktree at `/home/donboyd5/Documents/python_projects/popfc/.worktree-docs/`. The worktree is always pinned to `docs/main`.
4. **Merging to `main`** is solo-repo lightweight: fast-forward-merge the relevant branch into `main` locally and push when a phase or feature is genuinely finished. **Do not merge to `main` without the user's explicit go-ahead.** PRs are optional and only used when the user wants CI checks, the GitHub diff UI, or a formal review pause.
5. **Push periodically.** Both feature branches and `docs/main` should be pushed to GitHub regularly so nothing important lives only on the local machine.
6. **Never use destructive git commands** (`push --force`, `reset --hard`, `branch -D`, `clean -f`, `--no-verify`) without explicit user instruction. Investigate before deleting unfamiliar branches or files — they may be in-progress work.
7. **Defer deferred work to GitHub issues** via `gh issue create` rather than scattering TODOs in code.

## Repo layout

- **Primary tree** (current branch usually `feat/...`): `/home/donboyd5/Documents/python_projects/popfc/`
- **Docs worktree** (always on `docs/main`): `/home/donboyd5/Documents/python_projects/popfc/.worktree-docs/`
- Both worktrees share the same `.git`; edits in one do not appear in the other until merged through `main`.

------------------------------------------------------------------------

## Data engineering conventions

1. **Statewide by default.** Loaders never hardcode Washington County FIPS (`36115`) or pre-filter to it. Subset at analysis time only. A future sibling project should be able to `pip install -e ../popfc` and query any NY county or town.
2. **Long / tidy format.** All loaders emit canonical long-format DataFrames with the schemas defined in `src/popfc/data/_common.py` (`POP_LONG_COLUMNS`, `COMPONENTS_LONG_COLUMNS`). Standard identifier columns: `state_fips`, `county_fips`, `geoid`, `mcd_fips` (when applicable), plus provenance: `source`, `vintage`, `notes`.
3. **String-first ingestion.** Read raw CSVs with `dtype=str` (use `read_csv_strings` from `_common.py`), then explicitly coerce numeric columns with `coerce_numeric()`. Coercion failures must warn (count of values lost), not silently mask. Rationale: pandas auto-inference silently converts mixed-type columns to `object`, loses leading zeros on FIPS codes, and turns sentinel strings into NaN.
4. **Provenance on every row.** `source`, `vintage`, and `notes` columns travel with the data into interim parquet files. Always answerable: "where did this number come from?"
5. **Loaders are pure.** Every loader accepts a `path` (and usually a `vintage`) parameter with a default. Swapping in a newer vintage of an upstream file is a one-line change at the call site, never a code edit deep in a function body.
6. **Interim data is statewide and stored in parquet** under `data_interim/`. Storage is cheap; recomputing isn't.
7. **Preserve detail.** Town-level components of change and age/sex detail stay in the interim layer even when current work only needs county totals.

## Code conventions

1. **Library code in `src/popfc/`, not notebooks.** Notebooks orchestrate and visualize; reusable logic lives in tested modules. Promote anything that's been used twice.
2. **Vectorized / array-based over per-unit loops** when working with DataFrames or numeric data.
3. **Every notebook ends with assertions / sanity checks.** Populations sum, no negatives, year coverage complete, identities hold.
4. **Do not feel constrained by the R implementation.** The legacy R/Quarto project (formerly at `popfc_R/`, deleted in Phase 5) is preserved at `docs/r_reference/` for context only — apply Python best practices even when they depart from the R code.
5. **Default to no comments.** Write a comment only when *why* is non-obvious (a hidden constraint, a workaround for a specific bug, behavior that would surprise a reader). Don't narrate what well-named code already says.

## Documentation maintenance

1. **Keep `docs/planning.md` current** as work progresses — both the "Current Status" section and the phase details.
2. **Keep the "Prompt for a new Claude Code session" block in `docs/planning.md` up to date** so the user can paste it into a fresh session and resume seamlessly.
3. **Update or remove memory entries that turn out to be wrong or outdated.**

------------------------------------------------------------------------

## Pointers

- How to actually run the forecast end-to-end: `docs/workflow.md`
- Full plan, status, and phase breakdown: `docs/planning.md`
- R-project reference materials (preserved): `docs/r_reference/`
- Claude auto-memory (Claude's working notes, machine-local): `~/.claude/projects/-home-donboyd5-Documents-python-projects-popfc/memory/MEMORY.md`
- Repo on GitHub: https://github.com/donboyd5/popfc
