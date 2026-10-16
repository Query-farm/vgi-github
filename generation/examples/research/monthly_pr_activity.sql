-- Replace the fixture login 'researcher' and dates for a real account.
SELECT pull_request_created_month, pull_request_count,
       pull_request_active_days, pull_request_repository_count,
       median_merge_hours
FROM engineering.semantic.github(user => 'researcher')
WHERE pull_request_created_day >= DATE '2026-08-01'
  AND pull_request_created_day < DATE '2026-10-01'
GROUP BY pull_request_created_month
ORDER BY pull_request_created_month;
