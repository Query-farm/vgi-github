-- Generated from generation/examples/research/*.sql. Edit those sources.
-- Attach the generated github package as engineering first (see README.md).
-- Prepared inputs: user, start/end UTC dates; compare/focus take two periods.
SET TimeZone='UTC';
SET crossfield_mode='semantic';

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

PREPARE github_pr_focus AS
WITH earlier AS (
    SELECT authored_repository_name AS repository, authored_pr_count AS prs
    FROM engineering.semantic.github(user => $1)
    WHERE authored_pr_created_day >= $2 AND authored_pr_created_day < $3
    GROUP BY authored_repository_name
), later AS (
    SELECT authored_repository_name AS repository, authored_pr_count AS prs
    FROM engineering.semantic.github(user => $1)
    WHERE authored_pr_created_day >= $4 AND authored_pr_created_day < $5
    GROUP BY authored_repository_name
), earlier_shares AS (
    SELECT *, 100.0 * prs / SUM(prs) OVER () AS share FROM earlier
), later_shares AS (
    SELECT *, 100.0 * prs / SUM(prs) OVER () AS share FROM later
)
SELECT COALESCE(earlier_shares.repository,later_shares.repository) AS repository,
       COALESCE(earlier_shares.prs,0) AS earlier_prs,
       COALESCE(later_shares.prs,0) AS later_prs,
       CASE WHEN NOT EXISTS(SELECT 1 FROM earlier) THEN NULL
            ELSE COALESCE(earlier_shares.share,0) END AS earlier_share_percent,
       CASE WHEN NOT EXISTS(SELECT 1 FROM later) THEN NULL
            ELSE COALESCE(later_shares.share,0) END AS later_share_percent,
       CASE WHEN NOT EXISTS(SELECT 1 FROM earlier) OR NOT EXISTS(SELECT 1 FROM later) THEN NULL
            ELSE COALESCE(later_shares.share,0)-COALESCE(earlier_shares.share,0)
            END AS share_change_percentage_points,
       CASE WHEN earlier_shares.repository IS NULL THEN 'new_in_comparison'
            WHEN later_shares.repository IS NULL THEN 'absent_in_later_period'
            ELSE 'present_in_both' END AS presence
FROM earlier_shares FULL OUTER JOIN later_shares USING(repository)
WHERE CASE WHEN $2 IS NULL OR $3 IS NULL OR $4 IS NULL OR $5 IS NULL
                OR CAST($3 AS DATE)<=CAST($2 AS DATE) OR CAST($5 AS DATE)<=CAST($4 AS DATE)
                OR CAST($3 AS DATE)>CAST($4 AS DATE)
           THEN error('Use ordered, non-overlapping, nonempty [start,end) UTC periods')
           ELSE true END
ORDER BY repository;

PREPARE github_activity_evidence AS
SELECT * FROM (
    SELECT 'pull_request' AS activity_kind, source_id, repository_name, created_at, url, title, body FROM (
        SELECT pull_request_node_id AS source_id, repository_name, created_at, url, title AS title, body
        FROM engineering.detail.authored_pull_requests(user => $1)
        WHERE authored_pr_created_day >= $2 AND authored_pr_created_day < $3
    ) records
    UNION ALL
    SELECT 'issue' AS activity_kind, source_id, repository_name, created_at, url, title, body FROM (
        SELECT issue_node_id AS source_id, repository_name, created_at, url, title AS title, body
        FROM engineering.detail.authored_issues(user => $1)
        WHERE authored_issue_created_day >= $2 AND authored_issue_created_day < $3
    ) records
    UNION ALL
    SELECT 'discussion' AS activity_kind, source_id, repository_name, created_at, url, title, body FROM (
        SELECT discussion_node_id AS source_id, repository_name, created_at, url, title AS title, body
        FROM engineering.detail.authored_discussions(user => $1)
        WHERE authored_discussion_created_day >= $2 AND authored_discussion_created_day < $3
    ) records
    UNION ALL
    SELECT 'issue_or_pr_comment' AS activity_kind, source_id, repository_name, created_at, url, NULL::VARCHAR AS title, body FROM (
        SELECT comment_node_id AS source_id, repository_name, created_at, url, body
        FROM engineering.detail.authored_issue_comments(user => $1)
        WHERE authored_issue_comment_created_day >= $2 AND authored_issue_comment_created_day < $3
    ) records
    UNION ALL
    SELECT 'discussion_comment' AS activity_kind, source_id, repository_name, created_at, url, title, body FROM (
        SELECT comment_node_id AS source_id, repository_name, created_at, url, subject_title AS title, body
        FROM engineering.detail.authored_discussion_comments(user => $1)
        WHERE authored_discussion_comment_created_day >= $2 AND authored_discussion_comment_created_day < $3
    ) records
    UNION ALL
    SELECT 'commit_comment' AS activity_kind, source_id, repository_name, created_at, url, NULL::VARCHAR AS title, body FROM (
        SELECT comment_node_id AS source_id, repository_name, created_at, url, body
        FROM engineering.detail.authored_commit_comments(user => $1)
        WHERE authored_commit_comment_created_day >= $2 AND authored_commit_comment_created_day < $3
    ) records
) evidence
ORDER BY created_at,activity_kind,source_id;

PREPARE github_user_cohort AS
SELECT user_login, user_count, authored_pr_count, authored_issue_count
FROM engineering.semantic.github(users => $1)
GROUP BY user_login
ORDER BY user_login;
