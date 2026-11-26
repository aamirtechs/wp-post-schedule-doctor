"""Tests for wp-post-schedule-doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wp_post_schedule_doctor as wpsd

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples")

AS_OF = datetime(2026, 11, 18, tzinfo=timezone.utc)

HEADER = ("id,title,status,author,post_type,scheduled_at,"
          "published_at,modified_at\n")


def write_csv(content):
    """Write content to a temp CSV file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8")
    handle.write(content)
    handle.close()
    return handle.name


def row(post_id="P-1", title="Title", status="future", author="Ana",
        post_type="post", scheduled="2026-11-20 09:00",
        published="", modified="2026-11-17 09:00"):
    """Build one CSV row with the standard columns."""
    return ",".join([post_id, title, status, author, post_type,
                     scheduled, published, modified]) + "\n"


def parse(content, as_of=AS_OF):
    """Parse CSV content and return (posts, findings)."""
    return wpsd.parse_csv(write_csv(content), as_of)


def audit(content, as_of=AS_OF, **kwargs):
    """Parse CSV content and audit it, returning all findings."""
    posts, findings = parse(content, as_of)
    findings.extend(wpsd.audit(posts, as_of, **kwargs))
    return posts, findings


def rules(findings):
    """Return the sorted rule names of a findings list."""
    return sorted(item.rule for item in findings)


def by_rule(findings, rule):
    """Return the findings with one rule name."""
    return [item for item in findings if item.rule == rule]


class TestParseTimestamp(unittest.TestCase):
    def test_iso_with_space(self):
        parsed = wpsd.parse_timestamp("2026-11-01 09:30")
        self.assertEqual(parsed,
                         datetime(2026, 11, 1, 9, 30,
                                  tzinfo=timezone.utc))

    def test_iso_with_t(self):
        parsed = wpsd.parse_timestamp("2026-11-01T09:30:00")
        self.assertEqual(parsed.hour, 9)
        self.assertEqual(parsed.minute, 30)

    def test_iso_with_z(self):
        parsed = wpsd.parse_timestamp("2026-11-01T09:30:00Z")
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_date_only(self):
        parsed = wpsd.parse_timestamp("2026-11-01")
        self.assertEqual(parsed,
                         datetime(2026, 11, 1, tzinfo=timezone.utc))

    def test_slash_format(self):
        parsed = wpsd.parse_timestamp("01/11/2026 09:30")
        self.assertEqual(parsed.day, 1)
        self.assertEqual(parsed.month, 11)

    def test_whitespace_is_stripped(self):
        self.assertIsNotNone(wpsd.parse_timestamp(" 2026-11-01 "))

    def test_empty_returns_none(self):
        self.assertIsNone(wpsd.parse_timestamp(""))
        self.assertIsNone(wpsd.parse_timestamp("   "))
        self.assertIsNone(wpsd.parse_timestamp(None))

    def test_garbage_returns_none(self):
        self.assertIsNone(wpsd.parse_timestamp("not-a-date"))
        self.assertIsNone(wpsd.parse_timestamp("2026-13-40"))

    def test_naive_is_utc(self):
        parsed = wpsd.parse_timestamp("2026-11-01 09:00")
        self.assertEqual(parsed.tzinfo, timezone.utc)


class TestParseCsv(unittest.TestCase):
    def test_header_aliases(self):
        content = ("post_id,post_title,post_status,post_author,"
                   "post_type,date,post_date_gmt,post_modified\n"
                   "P-1,Title,future,Ana,post,2026-11-20 09:00,,"
                   "2026-11-17 09:00\n")
        posts, findings = parse(content)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["id"], "P-1")
        self.assertEqual(posts[0]["title"], "Title")
        self.assertEqual(findings, [])

    def test_bom_header(self):
        content = "\ufeff" + HEADER + row()
        posts, findings = parse(content)
        self.assertEqual(len(posts), 1)
        self.assertEqual(findings, [])

    def test_missing_id_column(self):
        content = ("title,status,scheduled_at\n"
                   "Title,future,2026-11-20 09:00\n")
        with self.assertRaises(ValueError):
            parse(content)

    def test_missing_date_column(self):
        content = "id,title,status\nP-1,Title,future\n"
        with self.assertRaises(ValueError):
            parse(content)

    def test_empty_file(self):
        with self.assertRaises(ValueError):
            parse("")

    def test_malformed_row_skipped(self):
        content = HEADER + row() + "P-2,Title,future,Ana,post\n"
        posts, findings = parse(content)
        self.assertEqual(len(posts), 1)
        self.assertEqual(rules(findings), ["malformed-row"])

    def test_duplicate_id(self):
        content = HEADER + row("P-1") + row("P-1")
        posts, findings = parse(content)
        self.assertEqual(len(posts), 2)
        self.assertEqual(rules(findings), ["duplicate-post-id"])

    def test_invalid_timestamp(self):
        content = HEADER + row(scheduled="not-a-date")
        posts, findings = parse(content)
        self.assertEqual(rules(findings), ["invalid-timestamp"])
        self.assertIsNone(posts[0]["scheduled_at"])

    def test_future_timestamp(self):
        content = HEADER + row(modified="2026-12-01 09:00")
        posts, findings = parse(content)
        self.assertEqual(rules(findings), ["future-timestamp"])

    def test_scheduled_in_future_is_not_future_timestamp(self):
        content = HEADER + row(scheduled="2026-12-01 09:00")
        posts, findings = parse(content)
        self.assertEqual(findings, [])

    def test_extra_columns_ignored(self):
        content = HEADER.rstrip("\n") + ",category\n" + \
            row().rstrip("\n") + ",News\n"
        posts, findings = parse(content)
        self.assertEqual(len(posts), 1)

    def test_blank_lines_skipped(self):
        content = HEADER + "\n" + row() + "\n"
        posts, findings = parse(content)
        self.assertEqual(len(posts), 1)
        self.assertEqual(findings, [])

    def test_missing_file(self):
        with self.assertRaises(ValueError):
            wpsd.parse_csv("/tmp/no-such-file-wpsd.csv", AS_OF)


class TestMissedSchedule(unittest.TestCase):
    def test_missed_is_error(self):
        content = HEADER + row(scheduled="2026-11-15 09:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["missed-schedule"])
        self.assertEqual(findings[0].severity, "error")

    def test_grace_minutes_keeps_just_due_post_clean(self):
        content = HEADER + row(scheduled="2026-11-17 23:30")
        posts, findings = audit(content, grace_minutes=60)
        self.assertEqual(findings, [])

    def test_past_grace_is_missed(self):
        content = HEADER + row(scheduled="2026-11-17 22:00")
        posts, findings = audit(content, grace_minutes=60)
        self.assertEqual(rules(findings), ["missed-schedule"])

    def test_long_missed_adds_warning(self):
        content = HEADER + row(scheduled="2026-11-05 09:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings),
                         ["long-missed", "missed-schedule"])

    def test_short_missed_has_no_long_warning(self):
        content = HEADER + row(scheduled="2026-11-15 09:00")
        posts, findings = audit(content)
        self.assertNotIn("long-missed", rules(findings))

    def test_published_post_never_missed(self):
        content = HEADER + row(status="publish",
                               scheduled="2026-11-10 09:00",
                               published="2026-11-10 09:05")
        posts, findings = audit(content)
        self.assertEqual(findings, [])

    def test_is_missed_helper(self):
        posts, _ = parse(HEADER + row(scheduled="2026-11-15 09:00"))
        self.assertTrue(wpsd.is_missed(posts[0], AS_OF, 60))
        posts, _ = parse(HEADER + row(scheduled="2026-11-20 09:00"))
        self.assertFalse(wpsd.is_missed(posts[0], AS_OF, 60))


class TestSoonAndFarFuture(unittest.TestCase):
    def test_publishing_soon(self):
        content = HEADER + row(scheduled="2026-11-18 14:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["publishing-soon"])

    def test_not_soon_beyond_window(self):
        content = HEADER + row(scheduled="2026-11-20 09:00")
        posts, findings = audit(content)
        self.assertEqual(findings, [])

    def test_soon_hours_flag_widens_window(self):
        content = HEADER + row(scheduled="2026-11-20 09:00")
        posts, findings = audit(content, soon_hours=72)
        self.assertEqual(rules(findings), ["publishing-soon"])

    def test_far_future(self):
        content = HEADER + row(scheduled="2027-06-01 09:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["scheduled-far-future"])

    def test_not_far_future_within_window(self):
        content = HEADER + row(scheduled="2026-12-01 09:00")
        posts, findings = audit(content)
        self.assertEqual(findings, [])


class TestDrafts(unittest.TestCase):
    def test_stale_draft(self):
        content = HEADER + row(status="draft", scheduled="",
                               modified="2026-04-01 09:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["stale-draft"])

    def test_fresh_draft_is_clean(self):
        content = HEADER + row(status="draft", scheduled="",
                               modified="2026-11-16 09:00")
        posts, findings = audit(content)
        self.assertEqual(findings, [])

    def test_pending_counts_as_draft(self):
        content = HEADER + row(status="pending", scheduled="",
                               modified="2026-04-01 09:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["stale-draft"])

    def test_future_post_ignores_modified_age(self):
        content = HEADER + row(modified="2026-04-01 09:00")
        posts, findings = audit(content)
        self.assertEqual(findings, [])


class TestDataRules(unittest.TestCase):
    def test_missing_scheduled_date(self):
        content = HEADER + row(scheduled="")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["missing-scheduled-date"])

    def test_invalid_date_does_not_double_fire_missing(self):
        content = HEADER + row(scheduled="not-a-date")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["invalid-timestamp"])

    def test_missing_published_date(self):
        content = HEADER + row(status="publish",
                               scheduled="2026-11-08 09:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["missing-published-date"])

    def test_published_before_scheduled(self):
        content = HEADER + row(status="publish",
                               scheduled="2026-11-12 09:00",
                               published="2026-11-11 09:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings),
                         ["published-before-scheduled"])

    def test_invalid_status(self):
        content = HEADER + row(status="weird")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["invalid-status"])

    def test_missing_title(self):
        content = HEADER + row(title="")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["missing-title"])

    def test_trash_without_title_is_clean(self):
        content = HEADER + row(title="", status="trash",
                               scheduled="")
        posts, findings = audit(content)
        self.assertEqual(findings, [])

    def test_missing_author(self):
        content = HEADER + row(author="")
        posts, findings = audit(content)
        self.assertEqual(rules(findings), ["missing-author"])

    def test_same_scheduled_time(self):
        content = HEADER + row("P-1", scheduled="2026-11-25 09:00") \
            + row("P-2", scheduled="2026-11-25 09:00")
        posts, findings = audit(content)
        self.assertEqual(rules(findings),
                         ["same-scheduled-time", "same-scheduled-time"])

    def test_different_times_no_same_time_warning(self):
        content = HEADER + row("P-1", scheduled="2026-11-25 09:00") \
            + row("P-2", scheduled="2026-11-26 09:00")
        posts, findings = audit(content)
        self.assertEqual(findings, [])


class TestSummary(unittest.TestCase):
    def test_sample_counts(self):
        path = os.path.join(EXAMPLES, "posts.csv")
        posts, findings = wpsd.parse_csv(path, AS_OF)
        findings.extend(wpsd.audit(posts, AS_OF))
        summary = wpsd.summarize(posts, findings, AS_OF)
        self.assertEqual(summary["posts"], 19)
        self.assertEqual(summary["findings"], 18)
        self.assertEqual(summary["errors"], 11)
        self.assertEqual(summary["warnings"], 7)
        self.assertEqual(summary["missed"], 2)
        self.assertEqual(summary["publishing_soon"], 1)
        self.assertEqual(summary["drafts"], 2)

    def test_per_author_table(self):
        path = os.path.join(EXAMPLES, "posts.csv")
        posts, findings = wpsd.parse_csv(path, AS_OF)
        findings.extend(wpsd.audit(posts, AS_OF))
        summary = wpsd.summarize(posts, findings, AS_OF)
        by_author = {item["author"]: item
                     for item in summary["per_author"]}
        self.assertEqual(by_author["Ana"]["posts"], 7)
        self.assertEqual(by_author["Ana"]["missed"], 1)
        self.assertEqual(by_author["Ana"]["drafts"], 1)
        self.assertEqual(by_author["Ana"]["soon"], 1)
        self.assertEqual(by_author["(unassigned)"]["posts"], 1)

    def test_per_status_table(self):
        path = os.path.join(EXAMPLES, "posts.csv")
        posts, findings = wpsd.parse_csv(path, AS_OF)
        findings.extend(wpsd.audit(posts, AS_OF))
        summary = wpsd.summarize(posts, findings, AS_OF)
        by_status = {item["status"]: item["posts"]
                     for item in summary["per_status"]}
        self.assertEqual(by_status["future"], 13)
        self.assertEqual(by_status["publish"], 3)
        self.assertEqual(by_status["draft"], 2)
        self.assertEqual(by_status["weird"], 1)

    def test_clean_summary(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        posts, findings = wpsd.parse_csv(path, AS_OF)
        findings.extend(wpsd.audit(posts, AS_OF))
        summary = wpsd.summarize(posts, findings, AS_OF)
        self.assertEqual(summary["findings"], 0)
        self.assertEqual(summary["posts"], 3)


class TestRender(unittest.TestCase):
    def test_text_contains_summary_lines(self):
        path = os.path.join(EXAMPLES, "posts.csv")
        posts, findings = wpsd.parse_csv(path, AS_OF)
        findings.extend(wpsd.audit(posts, AS_OF))
        summary = wpsd.summarize(posts, findings, AS_OF)
        text = wpsd.render_text(posts, findings, summary)
        self.assertIn("Posts: 19, findings: 18, errors: 11, "
                      "warnings: 7", text)
        self.assertIn("Missed schedules: 2, publishing soon: 1, "
                      "drafts: 2", text)
        self.assertIn("Per-author summary:", text)

    def test_json_is_valid(self):
        path = os.path.join(EXAMPLES, "posts.csv")
        posts, findings = wpsd.parse_csv(path, AS_OF)
        findings.extend(wpsd.audit(posts, AS_OF))
        summary = wpsd.summarize(posts, findings, AS_OF)
        report = json.loads(wpsd.render_json(posts, findings, summary))
        self.assertEqual(report["posts"], 19)
        self.assertEqual(len(report["findings"]), 18)
        self.assertEqual(report["findings"][0]["severity"], "error")

    def test_clean_text_says_clean(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        posts, findings = wpsd.parse_csv(path, AS_OF)
        findings.extend(wpsd.audit(posts, AS_OF))
        summary = wpsd.summarize(posts, findings, AS_OF)
        self.assertIn("All posts clean.",
                      wpsd.render_text(posts, findings, summary))


class TestMain(unittest.TestCase):
    def run_main(self, argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = wpsd.main(argv)
        return code, buffer.getvalue()

    def test_sample_check_exits_1(self):
        path = os.path.join(EXAMPLES, "posts.csv")
        code, _ = self.run_main([path, "--as-of", "2026-11-18",
                                 "--check"])
        self.assertEqual(code, 1)

    def test_clean_check_exits_0(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, _ = self.run_main([path, "--as-of", "2026-11-18",
                                 "--check"])
        self.assertEqual(code, 0)

    def test_warnings_only_passes_check_fails_strict(self):
        path = os.path.join(EXAMPLES, "warnings-only.csv")
        code, _ = self.run_main([path, "--as-of", "2026-11-18",
                                 "--check"])
        self.assertEqual(code, 0)
        code, _ = self.run_main([path, "--as-of", "2026-11-18",
                                 "--check", "--strict"])
        self.assertEqual(code, 1)

    def test_soon_hours_changes_output(self):
        path = os.path.join(EXAMPLES, "warnings-only.csv")
        code, output = self.run_main(
            [path, "--as-of", "2026-11-18", "--soon-hours", "6"])
        self.assertEqual(code, 0)
        self.assertIn("findings: 1", output)

    def test_json_flag(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, output = self.run_main(
            [path, "--as-of", "2026-11-18", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["posts"], 3)

    def test_out_writes_file(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8")
        handle.close()
        code, _ = self.run_main(
            [path, "--as-of", "2026-11-18", "--out", handle.name])
        self.assertEqual(code, 0)
        with open(handle.name, encoding="utf-8") as read_handle:
            self.assertIn("All posts clean.", read_handle.read())

    def test_bad_as_of_exits_2(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, _ = self.run_main([path, "--as-of", "not-a-date"])
        self.assertEqual(code, 2)

    def test_missing_file_exits_2(self):
        code, _ = self.run_main(["/tmp/no-such-file-wpsd.csv"])
        self.assertEqual(code, 2)

    def test_negative_option_exits_2(self):
        path = os.path.join(EXAMPLES, "clean.csv")
        code, _ = self.run_main([path, "--grace-minutes", "-1"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
