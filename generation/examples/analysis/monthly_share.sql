SELECT author_id, author_login, pull_request_created_month, activity_repository_id, pull_request_repository_name,
       pull_request_count, monthly_pr_total,
       monthly_repository_pr_share
FROM engineering.semantic.github(user=>'researcher')
GROUP BY author_id, author_login, pull_request_created_month,
         activity_repository_id, pull_request_repository_name;
