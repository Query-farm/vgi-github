PREPARE github_activity_compare AS
WITH earlier AS (
    SELECT 'pull_request' AS activity_kind, counts.* FROM (
        SELECT authored_pr_count AS records,
           authored_pr_active_days AS active_days, authored_pr_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_pr_created_day >= $2 AND authored_pr_created_day < $3
    ) counts
    UNION ALL
    SELECT 'issue' AS activity_kind, counts.* FROM (
        SELECT authored_issue_count AS records,
           authored_issue_active_days AS active_days, authored_issue_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_issue_created_day >= $2 AND authored_issue_created_day < $3
    ) counts
    UNION ALL
    SELECT 'discussion' AS activity_kind, counts.* FROM (
        SELECT authored_discussion_count AS records,
           authored_discussion_active_days AS active_days, authored_discussion_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_discussion_created_day >= $2 AND authored_discussion_created_day < $3
    ) counts
    UNION ALL
    SELECT 'issue_or_pr_comment' AS activity_kind, counts.* FROM (
        SELECT authored_issue_comment_count AS records,
           authored_issue_comment_active_days AS active_days, authored_issue_comment_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_issue_comment_created_day >= $2 AND authored_issue_comment_created_day < $3
    ) counts
    UNION ALL
    SELECT 'discussion_comment' AS activity_kind, counts.* FROM (
        SELECT authored_discussion_comment_count AS records,
           authored_discussion_comment_active_days AS active_days, authored_discussion_comment_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_discussion_comment_created_day >= $2 AND authored_discussion_comment_created_day < $3
    ) counts
    UNION ALL
    SELECT 'commit_comment' AS activity_kind, counts.* FROM (
        SELECT authored_commit_comment_count AS records,
           authored_commit_comment_active_days AS active_days, authored_commit_comment_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_commit_comment_created_day >= $2 AND authored_commit_comment_created_day < $3
    ) counts
), later AS (
    SELECT 'pull_request' AS activity_kind, counts.* FROM (
        SELECT authored_pr_count AS records,
           authored_pr_active_days AS active_days, authored_pr_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_pr_created_day >= $4 AND authored_pr_created_day < $5
    ) counts
    UNION ALL
    SELECT 'issue' AS activity_kind, counts.* FROM (
        SELECT authored_issue_count AS records,
           authored_issue_active_days AS active_days, authored_issue_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_issue_created_day >= $4 AND authored_issue_created_day < $5
    ) counts
    UNION ALL
    SELECT 'discussion' AS activity_kind, counts.* FROM (
        SELECT authored_discussion_count AS records,
           authored_discussion_active_days AS active_days, authored_discussion_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_discussion_created_day >= $4 AND authored_discussion_created_day < $5
    ) counts
    UNION ALL
    SELECT 'issue_or_pr_comment' AS activity_kind, counts.* FROM (
        SELECT authored_issue_comment_count AS records,
           authored_issue_comment_active_days AS active_days, authored_issue_comment_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_issue_comment_created_day >= $4 AND authored_issue_comment_created_day < $5
    ) counts
    UNION ALL
    SELECT 'discussion_comment' AS activity_kind, counts.* FROM (
        SELECT authored_discussion_comment_count AS records,
           authored_discussion_comment_active_days AS active_days, authored_discussion_comment_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_discussion_comment_created_day >= $4 AND authored_discussion_comment_created_day < $5
    ) counts
    UNION ALL
    SELECT 'commit_comment' AS activity_kind, counts.* FROM (
        SELECT authored_commit_comment_count AS records,
           authored_commit_comment_active_days AS active_days, authored_commit_comment_repository_count AS known_repositories
        FROM engineering.semantic.github(user => $1)
        WHERE authored_commit_comment_created_day >= $4 AND authored_commit_comment_created_day < $5
    ) counts
), bounds AS (
    SELECT DATE_DIFF('day', CAST($2 AS DATE), CAST($3 AS DATE)) AS earlier_days,
           DATE_DIFF('day', CAST($4 AS DATE), CAST($5 AS DATE)) AS later_days
)
SELECT earlier.activity_kind,
       earlier.records AS earlier_records, later.records AS later_records,
       later.records - earlier.records AS record_change,
       earlier.active_days AS earlier_active_days, later.active_days AS later_active_days,
       earlier.known_repositories AS earlier_repositories, later.known_repositories AS later_repositories,
       earlier.records * 1.0 / earlier_days AS earlier_records_per_day,
       later.records * 1.0 / later_days AS later_records_per_day,
       100.0 * ((later.records * 1.0 / later_days) /
                NULLIF(earlier.records * 1.0 / earlier_days, 0) - 1) AS rate_change_percent,
       CASE WHEN earlier.records=0 AND later.records=0 THEN 'no_observed_activity'
            WHEN earlier.records=0 THEN 'activity_without_baseline'
            ELSE 'comparable' END AS comparison_status
FROM earlier JOIN later USING (activity_kind) CROSS JOIN bounds
WHERE CASE WHEN earlier_days IS NULL OR later_days IS NULL
                OR earlier_days<=0 OR later_days<=0
                OR CAST($3 AS DATE)>CAST($4 AS DATE)
           THEN error('Use ordered, non-overlapping, nonempty [start,end) UTC periods')
           ELSE true END
ORDER BY earlier.activity_kind;
