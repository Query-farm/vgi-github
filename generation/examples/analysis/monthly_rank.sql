SELECT author_id, author_login, pull_request_created_month, pull_request_count, monthly_user_pr_rank
FROM engineering.semantic.github(users=>[{'login':'alice'},{'login':'bob'},{'login':'researcher'},{'login':'carol'}])
GROUP BY author_id, author_login, pull_request_created_month;
