# Data Analyst (Phase G)

Upload a CSV/XLSX, ask questions in plain language, get computed tables and charts, save and export reports.
Agents (`DATA_INTELLIGENCE_ANALYST`, and any employee granted the tools) can use the same data.

## How it works
* **Upload** (admin only): `.csv`/`.tsv`/`.txt`/`.xlsx`; max 5 MB, 50,000 rows, 100 columns; 50 datasets per company.
  Excel is read for cached values only (no formulas evaluated, no macros). Types are inferred per column (number, date, text);
  `$1,250.50`, `(40)` and thousands separators parse as numbers.
* **Engine** (`app/services/analysis_engine.py`): the only thing that produces numbers. A *spec* (op, filters, group_by, metrics,
  interval, sort, limit, chart) is validated against the dataset's real columns; anything unknown is refused with a safe message.
  Ops: `preview`, `describe`, `aggregate` (sum/mean/min/max/count/median/nunique, group by <= 2), `timeseries` (day/week/month/year),
  `value_counts`, `correlation`. No code, SQL or expressions are ever executed.
* **Natural language**: the LLM only proposes a spec; the engine computes. The narrative is checked so every number it states exists
  in the result, otherwise a deterministic template narrative is used (`narrative_source` = `llm` | `template`).
  The structured `spec` path needs no LLM at all.
* **Reports**: saving re-runs the spec on the server (client results are never stored). CSV export neutralises formula injection.
* **Agent tools** (`list_datasets`, `analyze_dataset`; read-only): tenant-scoped, restricted datasets are invisible to agents.

## Permissions
| Action | Who |
|---|---|
| Upload, delete, restrict/unrestrict | Company admin |
| List, view, analyse, save/export reports | Any member, non-restricted datasets only |
| Restricted datasets and their reports | Admin only (others get 404) |
| Delete a report | Its author or an admin |

## API
`/api/v1/datasets` (POST upload, GET list, GET/PATCH/DELETE `/{id}`, POST `/{id}/analyze`),
`/api/v1/analysis-reports` (POST, GET, GET `/{id}`, GET `/{id}/export.csv`, DELETE `/{id}`).

## Limits / honest status
* Verified with a scripted LLM only; question-to-spec quality with a real model is unverified.
* Single table per analysis (no joins), single sheet for Excel, no pivoting beyond 2 group columns.
* Datasets are stored as text in the application DB (fine for the size limits; not a data warehouse).
* Live database connectivity for analysis is Phase K.
Migration: `a4b8c93d5e21` (additive; two tables).
