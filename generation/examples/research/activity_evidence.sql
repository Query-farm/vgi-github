PREPARE github_activity_evidence AS
SELECT * FROM (
    SELECT 'pull_request' AS activity_kind, source_id, repository_name, created_at, url, title, body FROM (
        SELECT pull_request_node_id AS source_id, repository AS repository_name, created_at, html_url AS url, title AS title, body
        FROM engineering.detail.pull_requests(user => $1)
        WHERE pull_request_created_day >= $2 AND pull_request_created_day < $3
    ) records
    UNION ALL
    SELECT 'issue' AS activity_kind, source_id, repository_name, created_at, url, title, body FROM (
        SELECT issue_node_id AS source_id, repository_name, created_at, url, title AS title, body
        FROM engineering.detail.issues(user => $1)
        WHERE issue_created_day >= $2 AND issue_created_day < $3
    ) records
    UNION ALL
    SELECT 'discussion' AS activity_kind, source_id, repository_name, created_at, url, title, body FROM (
        SELECT discussion_node_id AS source_id, repository_name, created_at, url, title AS title, body
        FROM engineering.detail.discussions(user => $1)
        WHERE discussion_created_day >= $2 AND discussion_created_day < $3
    ) records
    UNION ALL
    SELECT 'issue_or_pr_comment' AS activity_kind, source_id, repository_name, created_at, url, NULL::VARCHAR AS title, body FROM (
        SELECT comment_node_id AS source_id, repository_name, created_at, url, body
        FROM engineering.detail.issue_comments(user => $1)
        WHERE issue_comment_created_day >= $2 AND issue_comment_created_day < $3
    ) records
    UNION ALL
    SELECT 'discussion_comment' AS activity_kind, source_id, repository_name, created_at, url, title, body FROM (
        SELECT comment_node_id AS source_id, repository_name, created_at, url, subject_title AS title, body
        FROM engineering.detail.discussion_comments(user => $1)
        WHERE discussion_comment_created_day >= $2 AND discussion_comment_created_day < $3
    ) records
    UNION ALL
    SELECT 'commit_comment' AS activity_kind, source_id, repository_name, created_at, url, NULL::VARCHAR AS title, body FROM (
        SELECT comment_node_id AS source_id, repository_name, created_at, url, body
        FROM engineering.detail.commit_comments(user => $1)
        WHERE commit_comment_created_day >= $2 AND commit_comment_created_day < $3
    ) records
) evidence
ORDER BY created_at,activity_kind,source_id;
