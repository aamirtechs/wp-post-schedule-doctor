# wp-post-schedule-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/wp-post-schedule-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/wp-post-schedule-doctor/issues)

A zero-dependency Python CLI that audits a WordPress posts
CSV export for missed schedules and scheduling mistakes:
posts whose publish time has passed without publishing,
posts missed by more than a week, posts scheduled in the far
future (usually a typo year), drafts sitting untouched for
months, two posts sharing one publish slot, posts with no
title or no author, duplicate post ids, malformed rows, and
invalid or future dates. It also prints a per-author summary
table, so a site owner can see whose queue is slipping.

WordPress does not run on a real clock. Its scheduler,
WP-Cron, only fires when somebody loads a page, so on a
quiet or heavily cached site a post scheduled for 9:00 can
still be sitting unpublished at lunchtime, flagged "Missed
schedule" in red, and WordPress sends no notification.
Recovery plugins publish the post only after it is already
late, and WP Crontrol lists cron events without auditing the
scheduled posts themselves. This tool is the audit before
that happens: it flags every post at risk from the export
alone, and never touches your site.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install wp-post-schedule-doctor
```

Or run it straight from the source checkout:

```bash
python3 wp_post_schedule_doctor.py examples/posts.csv
```

## Input format

A CSV export with a header row, from `wp post list` or a
posts export. Columns used: `id` (or `post_id`), `title`,
`status`, `author`, `post_type`, `scheduled_at`,
`published_at`, and `modified_at`. Extra columns are
ignored, so a full posts export works as-is. A UTF-8 BOM
header is handled. Only `id` and `scheduled_at` are
required; the other columns are optional, and the checks
that need a missing column are skipped.

`scheduled_at` also accepts `date`, `post_date`,
`scheduled`, or `publish_date` as the column name,
`title` also accepts `post_title`, `status` also accepts
`post_status`, and `modified_at` also accepts
`post_modified` or `modified`.

Dates accept ISO 8601 with or without a timezone
(`2026-11-01 09:00`, `2026-11-01T09:30:00Z`,
`2026-11-01`), plus day/month/year and month/day/year
forms. A date with no timezone is read as UTC.

```csv
id,title,status,author,post_type,scheduled_at,published_at,modified_at
P-101,How to speed up WooCommerce,future,Ana,post,2026-11-18 14:00,,2026-11-17 10:00
P-102,Black Friday sale guide,future,Ben,post,2026-11-20 09:00,,2026-11-16 09:00
P-103,Missed launch announcement,future,Ana,post,2026-11-15 09:00,,2026-11-14 09:00
P-107,Published on time,publish,Ben,post,2026-11-10 09:00,2026-11-10 09:05,2026-11-10 09:00
P-110,Draft from spring,draft,Ana,post,,,2026-04-01 09:00
```

## What it checks

Errors, the ones that mean a post will not publish as
planned or data that cannot be trusted:

* `missed-schedule`: a future post whose scheduled time is
  more than `--grace-minutes` (default 60) in the past and
  is still unpublished, so WP-Cron never fired for it.
* `missing-scheduled-date`: a future post with an empty
  `scheduled_at`, so it has no publish time to check.
* `missing-published-date`: a published post with no
  `published_at`, so the publish cannot be dated.
* `published-before-scheduled`: `published_at` earlier
  than `scheduled_at`.
* `missing-title`: a post with no title, so it would
  publish with an empty title and a bare slug. Trash posts
  are exempt.
* `invalid-status`: a status that is not a known WordPress
  post status (future, publish, draft, pending, private,
  trash, auto-draft).
* `duplicate-post-id`: the same post id twice in the
  export.
* `malformed-row`: a row with the wrong number of fields.
  The row is skipped and reported, never a crash.
* `invalid-timestamp`: a date field that matches no known
  format. The row is still audited on the fields that did
  parse. An unreadable scheduled date does not also fire
  `missing-scheduled-date`.
* `future-timestamp`: a `published_at` or `modified_at`
  after `--as-of` (default now). A `scheduled_at` in the
  future is normal and is never flagged here.

Warnings, patterns worth investigating:

* `long-missed`: a post missed for more than
  `--long-missed-days` (default 7), so it needs a manual
  publish or reschedule.
* `publishing-soon`: a post scheduled within
  `--soon-hours` (default 24) of the as-of date.
* `scheduled-far-future`: a post scheduled more than
  `--max-future-days` (default 90) out, which is usually a
  typo year.
* `stale-draft`: a draft or pending post last modified more
  than `--stale-days` (default 30) ago, so it is probably
  abandoned.
* `same-scheduled-time`: two or more future posts sharing
  one publish slot, so both publish in one WP-Cron run.
* `missing-author`: a post with no author assigned, so
  nobody owns publishing it.

The summary reports the missed schedule count, the
publishing-soon count, the draft count, and per-author and
per-status tables.

## Usage

```bash
python3 wp_post_schedule_doctor.py examples/posts.csv --as-of 2026-11-18
```

Captured output:

```
ERROR [invalid-timestamp] P-106: scheduled_at 'not-a-date' is not a readable date
ERROR [duplicate-post-id] P-101: post id appears more than once in the export
ERROR [future-timestamp] P-118: modified_at 2026-12-01 09:00 is after the as-of date 2026-11-18 00:00
ERROR [malformed-row] row 21: row has 9 fields but the header has 8, so the row was skipped
WARNING [publishing-soon] P-101: post is scheduled to publish on 2026-11-18 14:00, within the next 24 hours
ERROR [missed-schedule] P-103: post was scheduled for 2026-11-15 09:00 and is still unpublished 2.6 days later, so WP-Cron never fired for it
ERROR [missed-schedule] P-104: post was scheduled for 2026-11-05 09:00 and is still unpublished 12.6 days later, so WP-Cron never fired for it
WARNING [long-missed] P-104: post has been missed for 12.6 days, over the limit of 7 days, so it needs a manual publish or reschedule
ERROR [missing-scheduled-date] P-105: status is future but scheduled_at is empty, so the post has no publish time to check
ERROR [missing-published-date] P-108: status is publish but published_at is empty, so the publish cannot be dated
ERROR [published-before-scheduled] P-109: published_at 2026-11-11 09:00 is before scheduled_at 2026-11-12 09:00
WARNING [stale-draft] P-110: draft was last modified 230.6 days ago, over the limit of 30 days, so it is probably abandoned
WARNING [scheduled-far-future] P-112: post is scheduled for 2027-06-01, more than 90 days out, which is usually a typo year
ERROR [missing-title] P-113: post has no title, so it would publish with an empty title and a bare slug
WARNING [missing-author] P-114: post has no author assigned, so nobody owns publishing it
WARNING [same-scheduled-time] P-115: another post shares the 2026-11-25 09:00 publish slot, so both publish in one WP-Cron run
WARNING [same-scheduled-time] P-116: another post shares the 2026-11-25 09:00 publish slot, so both publish in one WP-Cron run
ERROR [invalid-status] P-117: status 'weird' is not a known WordPress post status

Posts: 19, findings: 18, errors: 11, warnings: 7
Missed schedules: 2, publishing soon: 1, drafts: 2

Per-author summary:
author        posts  missed  drafts  soon
(unassigned)      1       0       0     0
Ana               7       1       1     1
Ben               5       0       1     0
Cara              3       1       0     0
Dan               3       0       0     0

Per-status summary:
draft: 2 posts
future: 13 posts
publish: 3 posts
weird: 1 posts
```

The sample has 20 rows; the malformed row 21 is skipped, so
19 posts are audited. The headline numbers are 2 missed
schedules (P-103 and P-104, the second missed for 12.6
days), 1 post publishing soon, and 2 drafts, one of them
stale since April. The per-author table shows Ana holds 7
posts including the soon one and one missed one, while Cara
holds the long-missed post.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 wp_post_schedule_doctor.py examples/posts.csv --as-of 2026-11-18 --check
```

On `examples/clean.csv`, three clean posts, it exits 0:

```
Posts: 3, findings: 0, errors: 0, warnings: 0
Missed schedules: 0, publishing soon: 0, drafts: 1

Per-author summary:
author        posts  missed  drafts  soon
Ana               1       0       0     0
Ben               1       0       0     0
Cara              1       0       1     0

Per-status summary:
draft: 1 posts
future: 1 posts
publish: 1 posts

All posts clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has one post publishing soon
and one stale draft, so it passes `--check` (exit 0) and
fails `--check --strict` (exit 1). With a shorter soon
window the soon post drops out:

```bash
python3 wp_post_schedule_doctor.py examples/warnings-only.csv --as-of 2026-11-18 --soon-hours 6
```

Captured output:

```
WARNING [stale-draft] P-302: draft was last modified 47.6 days ago, over the limit of 30 days, so it is probably abandoned

Posts: 2, findings: 1, errors: 0, warnings: 1
Missed schedules: 0, publishing soon: 0, drafts: 1

Per-author summary:
author        posts  missed  drafts  soon
Ana               1       0       0     0
Ben               1       0       1     0

Per-status summary:
draft: 1 posts
future: 1 posts
```

`--json` emits the summary, the per-author and per-status
tables, and the findings as JSON, and `--out` writes the
report to a file.

## Options

| Flag | Meaning |
| --- | --- |
| `--grace-minutes` | A post this many minutes past its scheduled time is still just due, not missed (default: 60) |
| `--soon-hours` | A post scheduled within this many hours is publishing soon (default: 24) |
| `--stale-days` | A draft untouched for this many days is stale (default: 30) |
| `--long-missed-days` | A post missed for more than this many days is long missed (default: 7) |
| `--max-future-days` | A post scheduled more than this many days out is far future (default: 90) |
| `--as-of` | Date to compare timestamps against, for example 2026-11-18 (default: now) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* A row with too many or too few fields is a malformed-row
  error and is skipped; the rest of the file is still
  audited.
* A bad date is an invalid-timestamp error, and the row is
  still audited on the fields that did parse, so one bad
  date never hides the other problems on the post. An
  unreadable scheduled date does not also count as a
  missing scheduled date.
* A post scheduled up to `--grace-minutes` in the past is
  still just due, not missed, because WP-Cron can legitimately
  run minutes late on a normal site.
* A `scheduled_at` in the future is normal and never fires
  the future-timestamp check; only `published_at` and
  `modified_at` after the as-of date are errors.
* A post with no title in the trash is exempt from the
  missing-title check, since trashed posts never publish.
* A blank line in the file is skipped silently. A post with
  no author is grouped under `(unassigned)` in the
  per-author table, and a post with no status under
  `(no status)`.
* `--as-of` makes runs reproducible: without it, the
  future-timestamp check compares against the current time.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

64 tests, all passing: timestamp parsing, header aliases
and BOM handling, malformed rows, duplicate ids, invalid and
future timestamps, missed schedule rules and the grace
window, long-missed and publishing-soon windows, far-future
and stale-draft rules, same-slot detection, missing title,
author, and dates, summary counts, per-author and per-status
tables, text and JSON output, and `--check` and `--strict`
exit codes. The same 64 tests pass under pytest.

## License

MIT. See [LICENSE](LICENSE).
