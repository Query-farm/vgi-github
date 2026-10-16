PREPARE github_repository_activity AS
SELECT pull_request_count, issue_count, discussion_count,
       issue_comment_count, discussion_comment_count, commit_comment_count
FROM engineering.semantic.github(repository => $1, user => $2);
