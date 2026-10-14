-- Replace the fixture login 'researcher' and dates for a real account.
SELECT authored_pr_created_month, authored_pr_count,
       authored_pr_active_days, authored_pr_repository_count,
       authored_median_merge_hours
FROM engineering.semantic.github(user => 'researcher')
WHERE authored_pr_created_day >= DATE '2026-08-01'
  AND authored_pr_created_day < DATE '2026-10-01'
GROUP BY authored_pr_created_month
ORDER BY authored_pr_created_month;
