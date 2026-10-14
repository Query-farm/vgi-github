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
