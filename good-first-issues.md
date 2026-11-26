# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Add a missed-by-author worst list

Title: Show the authors with the most missed schedules

Description: After the per-author summary, print a short table
of the three authors with the highest missed schedule count
(author, missed count, soon count), so a site owner can see
at a glance whose queue slips most. Ties should break by soon
count, then by author name.

Difficulty: Easy

Acceptance criteria: the table appears in text output with the
correct top three for the sample file (Ana, Cara, and
(unassigned), Ana first on the soon tiebreak, (unassigned)
third on the name tiebreak);
JSON output is unchanged; a test checks the table rows.

## 2. Add a weekly publishing calendar

Title: Show scheduled posts per week

Description: Add a --weekly flag that prints, after the
per-status summary, one line per ISO week (week starting
date, posts scheduled, posts missed, posts publishing soon),
so an editor can see whether the publishing queue is
bunched or thin. Weeks are counted from the scheduled_at
date of future posts.

Difficulty: Easy

Acceptance criteria: the weekly table appears with the correct
counts for the sample file (posts scheduled 2026-11-18 fall
in the week starting 2026-11-16, the posts scheduled
2026-11-25 fall in the week starting 2026-11-23); JSON
output is unchanged; a test checks the weekly rows.

## 3. Support a custom missed grace per post type

Title: Let pages use a different grace window than posts

Description: Some sites schedule pages differently from
posts. Add a --page-grace-minutes flag that sets the missed
grace window for rows whose post_type is page, while
--grace-minutes keeps applying to posts. When the flag is
absent, pages use the same grace as posts.

Difficulty: Easy

Acceptance criteria: a page scheduled 90 minutes ago is not
flagged missed when --page-grace-minutes 120 is passed, and
is flagged without the flag; a test covers both cases; README
documents the flag.

## 4. Report the longest missed post in the summary

Title: Print the single oldest missed post

Description: Add one line to the text summary naming the
oldest missed post (post id, title, scheduled date, days
missed), so a site owner can act on the worst case without
reading every finding. When nothing is missed, the line is
omitted.

Difficulty: Easy

Acceptance criteria: the line appears for the sample file
naming P-104, scheduled 2026-11-05, 12.6 days missed; it is
absent for the clean file; JSON output is unchanged; a test
checks both cases.
