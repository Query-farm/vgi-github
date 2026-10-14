PREPARE github_user_cohort AS
SELECT user_login, user_count, authored_pr_count, authored_issue_count
FROM engineering.semantic.github(users => $1)
GROUP BY user_login
ORDER BY user_login;
