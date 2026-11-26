"""WordPress scheduled post audit CLI.

Reads a WordPress posts CSV export (from ``wp post list`` or a
posts export) and audits every scheduled post for the classic
missed schedule problem plus the scheduling mistakes around
it: posts whose publish time has passed without publishing,
posts missed by more than a week, posts scheduled in the far
future (usually a typo year), drafts sitting untouched for
months, two posts sharing one publish slot, posts with no
title or no author, and bad data such as duplicate ids,
malformed rows, and unreadable dates.

WordPress does not run on a real clock. Its scheduler,
WP-Cron, only fires when somebody loads a page, so on a quiet
or heavily cached site a post scheduled for 9:00 can still be
sitting unpublished at lunchtime, flagged "Missed schedule"
in red, with no notification sent. Recovery plugins publish
the post after it is already late. This tool is the audit
before that happens: it flags every post at risk from the
export alone, and never touches your site.

Each problem is a finding with a post id, a rule name, a
severity (error or warning), and a message. Errors are posts
that will not publish as planned or data that cannot be
trusted; warnings are patterns worth investigating.
--check exits 1 when any error is found, and --strict also
fails on warnings.

Dates are parsed defensively. A bad date is reported as a
finding and the row is still audited on the fields that did
parse, so one bad row never crashes the run.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 wp_post_schedule_doctor.py examples/posts.csv
    python3 wp_post_schedule_doctor.py posts.csv --json --check
    python3 wp_post_schedule_doctor.py posts.csv --as-of 2026-11-18
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone

__version__ = "1.0.0"

DEFAULT_GRACE_MINUTES = 60
DEFAULT_SOON_HOURS = 24
DEFAULT_STALE_DAYS = 30
DEFAULT_LONG_MISSED_DAYS = 7
DEFAULT_MAX_FUTURE_DAYS = 90

KNOWN_STATUSES = {"future", "publish", "draft", "pending",
                  "private", "trash", "auto-draft"}

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


class Finding:
    """One audit finding for one post, or for the post set."""

    def __init__(self, post, rule, severity, message):
        self.post = post
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"post": self.post, "rule": self.rule,
                "severity": self.severity, "message": self.message}

    def __str__(self):
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   self.post, self.message)


def parse_timestamp(text):
    """Parse a timestamp string into an aware datetime, or None.

    Accepts ISO 8601 with or without a timezone (a trailing Z is
    handled), plus a few common export formats. A naive timestamp
    is read as UTC. Returns None for an empty string or a value
    that matches no known format, so callers can report it
    instead of crashing.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def find_column(header, names):
    """Return the first of names present in header, or None."""
    for name in names:
        if name in header:
            return name
    return None


def parse_csv(path, as_of):
    """Parse a WordPress posts CSV export.

    Returns (posts, findings). Each post is a dict with the id,
    title, status, author, post type, and the parsed dates.
    Rows with the wrong number of fields are reported as
    malformed-row errors and skipped, never a crash. A UTF-8
    BOM header is handled. Extra columns are ignored.
    """
    findings = []
    posts = []
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("cannot read %s: %s" % (path, exc))
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("%s is empty, no header row found" % path)
        except csv.Error as exc:
            raise ValueError("%s is not a readable CSV file: %s"
                             % (path, exc))
        header = [name.strip() for name in header]
        id_column = find_column(header, ("id", "post_id", "ID"))
        if id_column is None:
            raise ValueError(
                "%s has no id or post_id column (header is: %s)"
                % (path, ", ".join(header)))
        scheduled_column = find_column(
            header, ("scheduled_at", "date", "post_date",
                     "scheduled", "publish_date"))
        if scheduled_column is None:
            raise ValueError(
                "%s has no scheduled_at or date column "
                "(header is: %s)" % (path, ", ".join(header)))
        title_column = find_column(header, ("title", "post_title"))
        status_column = find_column(header, ("status", "post_status"))
        author_column = find_column(header, ("author", "post_author"))
        type_column = find_column(header, ("post_type", "type"))
        published_column = find_column(
            header, ("published_at", "post_date_gmt"))
        modified_column = find_column(
            header, ("modified_at", "post_modified", "modified"))
        seen_ids = set()
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                findings.append(Finding(
                    "row %d" % line_number, "malformed-row", "error",
                    "row has %d fields but the header has %d, "
                    "so the row was skipped" % (len(row), len(header))))
                continue
            cells = dict(zip(header, (cell.strip() for cell in row)))
            post_id = cells[id_column] or "row %d" % line_number
            if post_id in seen_ids:
                findings.append(Finding(
                    post_id, "duplicate-post-id", "error",
                    "post id appears more than once in the export"))
            else:
                seen_ids.add(post_id)
            scheduled_raw = cells[scheduled_column]
            post = {"id": post_id,
                    "title": (cells[title_column]
                              if title_column else ""),
                    "status": (cells[status_column].lower()
                               if status_column else ""),
                    "author": (cells[author_column]
                               if author_column else ""),
                    "post_type": (cells[type_column]
                                  if type_column else ""),
                    "scheduled_at": None,
                    "scheduled_raw": scheduled_raw,
                    "published_at": None,
                    "modified_at": None,
                    "line": line_number}
            if scheduled_raw:
                post["scheduled_at"] = parse_timestamp(scheduled_raw)
                if post["scheduled_at"] is None:
                    findings.append(Finding(
                        post_id, "invalid-timestamp", "error",
                        "scheduled_at %r is not a readable date"
                        % scheduled_raw))
            for column, key, label in (
                    (published_column, "published_at", "published_at"),
                    (modified_column, "modified_at", "modified_at")):
                if column is None:
                    continue
                raw = cells[column]
                if not raw:
                    continue
                parsed = parse_timestamp(raw)
                if parsed is None:
                    findings.append(Finding(
                        post_id, "invalid-timestamp", "error",
                        "%s %r is not a readable date"
                        % (label, raw)))
                else:
                    post[key] = parsed
            for key, label in (
                    ("published_at", "published_at"),
                    ("modified_at", "modified_at")):
                value = post[key]
                if value is not None and value > as_of:
                    findings.append(Finding(
                        post_id, "future-timestamp", "error",
                        "%s %s is after the as-of date %s"
                        % (label, value.strftime("%Y-%m-%d %H:%M"),
                           as_of.strftime("%Y-%m-%d %H:%M"))))
            posts.append(post)
    return posts, findings


def is_missed(post, as_of, grace_minutes):
    """Return True when a future post is past its publish time."""
    scheduled = post["scheduled_at"]
    if post["status"] != "future" or scheduled is None:
        return False
    grace = timedelta(minutes=grace_minutes)
    return scheduled < as_of - grace


def audit(posts, as_of, grace_minutes=DEFAULT_GRACE_MINUTES,
          soon_hours=DEFAULT_SOON_HOURS,
          stale_days=DEFAULT_STALE_DAYS,
          long_missed_days=DEFAULT_LONG_MISSED_DAYS,
          max_future_days=DEFAULT_MAX_FUTURE_DAYS):
    """Audit a parsed post list and return a list of findings."""
    findings = []
    scheduled_times = {}
    for post in posts:
        if post["status"] == "future" \
                and post["scheduled_at"] is not None:
            key = post["scheduled_at"]
            scheduled_times[key] = scheduled_times.get(key, 0) + 1
    for post in posts:
        post_id = post["id"]
        status = post["status"]
        scheduled = post["scheduled_at"]
        published = post["published_at"]
        modified = post["modified_at"]

        if status and status not in KNOWN_STATUSES:
            findings.append(Finding(
                post_id, "invalid-status", "error",
                "status %r is not a known WordPress post status"
                % status))
        if not post["title"] and status != "trash":
            findings.append(Finding(
                post_id, "missing-title", "error",
                "post has no title, so it would publish with an "
                "empty title and a bare slug"))
        if not post["author"]:
            findings.append(Finding(
                post_id, "missing-author", "warning",
                "post has no author assigned, so nobody owns "
                "publishing it"))

        if status == "future" and not post["scheduled_raw"].strip():
            findings.append(Finding(
                post_id, "missing-scheduled-date", "error",
                "status is future but scheduled_at is empty, so "
                "the post has no publish time to check"))
        if status == "publish" and published is None:
            findings.append(Finding(
                post_id, "missing-published-date", "error",
                "status is publish but published_at is empty, so "
                "the publish cannot be dated"))
        if scheduled is not None and published is not None \
                and published < scheduled:
            findings.append(Finding(
                post_id, "published-before-scheduled", "error",
                "published_at %s is before scheduled_at %s"
                % (published.strftime("%Y-%m-%d %H:%M"),
                   scheduled.strftime("%Y-%m-%d %H:%M"))))

        if is_missed(post, as_of, grace_minutes):
            late_days = (as_of - scheduled).total_seconds() / 86400.0
            findings.append(Finding(
                post_id, "missed-schedule", "error",
                "post was scheduled for %s and is still "
                "unpublished %.1f days later, so WP-Cron never "
                "fired for it"
                % (scheduled.strftime("%Y-%m-%d %H:%M"), late_days)))
            if late_days > long_missed_days:
                findings.append(Finding(
                    post_id, "long-missed", "warning",
                    "post has been missed for %.1f days, over the "
                    "limit of %d days, so it needs a manual "
                    "publish or reschedule"
                    % (late_days, long_missed_days)))
        elif status == "future" and scheduled is not None:
            if scheduled > as_of:
                soon = as_of + timedelta(hours=soon_hours)
                if scheduled <= soon:
                    findings.append(Finding(
                        post_id, "publishing-soon", "warning",
                        "post is scheduled to publish on %s, "
                        "within the next %d hours"
                        % (scheduled.strftime("%Y-%m-%d %H:%M"),
                           soon_hours)))
                far = as_of + timedelta(days=max_future_days)
                if scheduled > far:
                    findings.append(Finding(
                        post_id, "scheduled-far-future", "warning",
                        "post is scheduled for %s, more than %d "
                        "days out, which is usually a typo year"
                        % (scheduled.strftime("%Y-%m-%d"),
                           max_future_days)))
            if scheduled_times.get(scheduled, 0) >= 2:
                findings.append(Finding(
                    post_id, "same-scheduled-time", "warning",
                    "another post shares the %s publish slot, so "
                    "both publish in one WP-Cron run"
                    % scheduled.strftime("%Y-%m-%d %H:%M")))

        if status in ("draft", "pending") and modified is not None:
            age_days = (as_of - modified).total_seconds() / 86400.0
            if age_days > stale_days:
                findings.append(Finding(
                    post_id, "stale-draft", "warning",
                    "draft was last modified %.1f days ago, over "
                    "the limit of %d days, so it is probably "
                    "abandoned" % (age_days, stale_days)))
    return findings


def summarize(posts, findings, as_of,
              grace_minutes=DEFAULT_GRACE_MINUTES,
              soon_hours=DEFAULT_SOON_HOURS):
    """Return the summary counts for a post list and findings."""
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings
                   if item.severity == "warning")
    missed = sum(1 for post in posts
                 if is_missed(post, as_of, grace_minutes))
    soon = sum(1 for post in posts
               if post["status"] == "future"
               and post["scheduled_at"] is not None
               and as_of < post["scheduled_at"]
               <= as_of + timedelta(hours=soon_hours))
    drafts = sum(1 for post in posts
                 if post["status"] in ("draft", "pending"))
    per_author = {}
    for post in posts:
        author = post["author"] or "(unassigned)"
        row = per_author.setdefault(author, {
            "author": author, "posts": 0, "missed": 0,
            "drafts": 0, "soon": 0})
        row["posts"] += 1
        if is_missed(post, as_of, grace_minutes):
            row["missed"] += 1
        if post["status"] in ("draft", "pending"):
            row["drafts"] += 1
        if post["status"] == "future" \
                and post["scheduled_at"] is not None \
                and as_of < post["scheduled_at"] \
                <= as_of + timedelta(hours=soon_hours):
            row["soon"] += 1
    authors = sorted(per_author.values(),
                     key=lambda item: item["author"])
    per_status = {}
    for post in posts:
        status = post["status"] or "(no status)"
        per_status[status] = per_status.get(status, 0) + 1
    statuses = sorted(per_status.items())
    total = len(posts)
    return {"posts": total,
            "findings": len(findings),
            "errors": errors,
            "warnings": warnings,
            "missed": missed,
            "publishing_soon": soon,
            "drafts": drafts,
            "per_author": authors,
            "per_status": [{"status": status, "posts": count}
                           for status, count in statuses]}


def render_text(posts, findings, summary):
    """Render the text report."""
    lines = [str(item) for item in findings]
    lines.append("")
    lines.append("Posts: %(posts)d, findings: %(findings)d, "
                 "errors: %(errors)d, warnings: %(warnings)d"
                 % summary)
    lines.append("Missed schedules: %(missed)d, publishing soon: "
                 "%(publishing_soon)d, drafts: %(drafts)d" % summary)
    lines.append("")
    lines.append("Per-author summary:")
    lines.append("%-12s %6s %7s %7s %5s"
                 % ("author", "posts", "missed", "drafts", "soon"))
    for row in summary["per_author"]:
        lines.append("%-12s %6d %7d %7d %5d"
                     % (row["author"], row["posts"], row["missed"],
                        row["drafts"], row["soon"]))
    lines.append("")
    lines.append("Per-status summary:")
    for row in summary["per_status"]:
        lines.append("%s: %d posts" % (row["status"], row["posts"]))
    if summary["findings"] == 0:
        lines.append("")
        lines.append("All posts clean.")
    return "\n".join(lines) + "\n"


def render_json(posts, findings, summary):
    """Render the JSON report."""
    report = dict(summary)
    report["findings"] = [item.as_dict() for item in findings]
    return json.dumps(report, indent=2) + "\n"


def build_parser():
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="wp-post-schedule-doctor",
        description="Audit a WordPress posts CSV export for "
                    "missed schedules and scheduling problems.")
    parser.add_argument("csv_file", help="posts CSV export to audit")
    parser.add_argument("--grace-minutes", type=int,
                        default=DEFAULT_GRACE_MINUTES,
                        help="a post this many minutes past its "
                        "scheduled time is still just due, not "
                        "missed (default: %d)"
                        % DEFAULT_GRACE_MINUTES)
    parser.add_argument("--soon-hours", type=int,
                        default=DEFAULT_SOON_HOURS,
                        help="a post scheduled within this many "
                        "hours is publishing soon "
                        "(default: %d)" % DEFAULT_SOON_HOURS)
    parser.add_argument("--stale-days", type=int,
                        default=DEFAULT_STALE_DAYS,
                        help="a draft untouched for this many days "
                        "is stale (default: %d)"
                        % DEFAULT_STALE_DAYS)
    parser.add_argument("--long-missed-days", type=int,
                        default=DEFAULT_LONG_MISSED_DAYS,
                        help="a post missed for more than this "
                        "many days is long missed "
                        "(default: %d)" % DEFAULT_LONG_MISSED_DAYS)
    parser.add_argument("--max-future-days", type=int,
                        default=DEFAULT_MAX_FUTURE_DAYS,
                        help="a post scheduled more than this many "
                        "days out is far future "
                        "(default: %d)" % DEFAULT_MAX_FUTURE_DAYS)
    parser.add_argument("--as-of", default=None,
                        help="date to compare timestamps against, "
                        "for example 2026-11-18 (default: now)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", default=None,
                        help="write the report to a file")
    return parser


def main(argv=None):
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    if args.grace_minutes < 0:
        print("error: --grace-minutes must be at least 0",
              file=sys.stderr)
        return 2
    if args.soon_hours < 0:
        print("error: --soon-hours must be at least 0",
              file=sys.stderr)
        return 2
    if args.stale_days < 0:
        print("error: --stale-days must be at least 0",
              file=sys.stderr)
        return 2
    if args.long_missed_days < 0:
        print("error: --long-missed-days must be at least 0",
              file=sys.stderr)
        return 2
    if args.max_future_days < 0:
        print("error: --max-future-days must be at least 0",
              file=sys.stderr)
        return 2
    if args.as_of is None:
        as_of = datetime.now(timezone.utc)
    else:
        as_of = parse_timestamp(args.as_of)
        if as_of is None:
            print("error: --as-of %r is not a readable date"
                  % args.as_of, file=sys.stderr)
            return 2
    try:
        posts, findings = parse_csv(args.csv_file, as_of)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    findings.extend(audit(posts, as_of,
                          grace_minutes=args.grace_minutes,
                          soon_hours=args.soon_hours,
                          stale_days=args.stale_days,
                          long_missed_days=args.long_missed_days,
                          max_future_days=args.max_future_days))
    summary = summarize(posts, findings, as_of,
                        grace_minutes=args.grace_minutes,
                        soon_hours=args.soon_hours)
    if args.json:
        report = render_json(posts, findings, summary)
    else:
        report = render_text(posts, findings, summary)
    if args.out is not None:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(report)
        except OSError as exc:
            print("error: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 2
    else:
        sys.stdout.write(report)
    if args.check:
        if summary["errors"] > 0:
            return 1
        if args.strict and summary["warnings"] > 0:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
