SELECT pull_request_created_day, pull_request_created_eastern_day, pull_request_count
FROM engineering.semantic.github(user=>'researcher')
GROUP BY pull_request_created_day, pull_request_created_eastern_day;
