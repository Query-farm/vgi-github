"""Independent review-history oracle; all worker calls still use native VGI.

First-review PR observations are 2, 7, 1 hours, despite unequal review counts.
Latest PR/reviewer pairs number five, two approved. The timestamp tie on PR beta#1
is resolved by larger review ID. A pending review has no submitted timestamp.
The existing research activity/time-offset oracle is retained unchanged.
"""

from __future__ import annotations

import research_fixture as research


def review(identity, state, reviewer, submitted):
    row = research.baseline.review(identity, state, reviewer)
    if submitted is None:
        # The pinned REST contract permits omission, but not explicit JSON null.
        row.pop("submitted_at")
    else:
        row["submitted_at"] = submitted
    return row


research.baseline.REVIEWS = {
    ("alpha", 1): [
        review(11, "APPROVED", "bob", "2026-09-01T02:00:00Z"),
        review(12, "COMMENTED", "alice", "2026-09-01T05:00:00Z"),
        review(14, "CHANGES_REQUESTED", "bob", "2026-09-01T03:00:00Z"),
    ],
    ("alpha", 2): [
        review(13, "APPROVED", "bob", "2026-09-02T07:00:00Z"),
        review(15, "PENDING", "carol", None),
    ],
    ("beta", 1): [
        review(21, "COMMENTED", "carol", "2026-09-03T01:00:00Z"),
        review(22, "APPROVED", "carol", "2026-09-03T01:00:00Z"),
        review(23, "COMMENTED", "bob", "2026-09-03T04:00:00Z"),
    ],
}

if __name__ == "__main__":
    research.main()
