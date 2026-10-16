PREPARE github_user_cohort AS
SELECT user_login, user_count, pull_request_count, issue_count
FROM engineering.semantic.github(users => $1)
GROUP BY user_login
ORDER BY user_login;
