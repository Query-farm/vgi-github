SELECT activity_user_id, activity_user, authored_pr_created_month, authored_pr_count, monthly_user_pr_rank
FROM engineering.semantic.github(users=>[{'login':'alice'},{'login':'bob'},{'login':'researcher'},{'login':'carol'}])
GROUP BY activity_user_id, activity_user, authored_pr_created_month;
