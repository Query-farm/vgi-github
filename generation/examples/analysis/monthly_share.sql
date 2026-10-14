SELECT activity_user_id, activity_user, authored_pr_created_month, activity_repository_id, authored_repository_name,
       authored_pr_count, monthly_authored_pr_total,
       monthly_repository_pr_share
FROM engineering.semantic.github(user=>'researcher')
GROUP BY activity_user_id, activity_user, authored_pr_created_month,
         activity_repository_id, authored_repository_name;
