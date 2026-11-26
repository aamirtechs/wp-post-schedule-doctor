# Changelog

## 1.0.0 - 2026-11-18

Initial release.

* Missed schedule audit over a WordPress posts CSV export:
  posts whose publish time has passed without publishing,
  posts missed for more than a configurable number of days,
  posts scheduled in the far future, posts publishing soon,
  stale drafts, and two posts sharing one publish slot.
* A 60 minute grace window, so a post minutes past its time
  is still just due and not flagged as missed.
* Data quality checks: duplicate post ids, malformed rows,
  invalid or future timestamps, missing titles, authors,
  scheduled and published dates, unknown statuses, and
  published dates earlier than scheduled dates.
* Per-author and per-status summary tables.
* Defensive timestamp parsing (ISO 8601 with or without a
  timezone, plus common day/month/year forms); a bad row is
  reported as a finding and never crashes the run. UTF-8 BOM
  headers and extra columns handled.
* Findings carry a post id, a rule name, a severity (error
  or warning), and a message; errors and warnings are counted
  in the summary.
* Text and --json output, --out file output,
  --grace-minutes, --soon-hours, --stale-days,
  --long-missed-days, --max-future-days, and --as-of
  thresholds, and a --check CI gate that exits 1 on errors
  (and on warnings with --strict).
* Zero dependencies, Python 3.10 or newer.
