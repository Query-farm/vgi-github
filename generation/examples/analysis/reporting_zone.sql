SELECT authored_pr_created_day, authored_pr_created_eastern_day, authored_pr_count
FROM engineering.semantic.github(user=>'researcher')
GROUP BY authored_pr_created_day, authored_pr_created_eastern_day;
