SELECT review_record_count, submitted_review_count, reviewed_pr_count,
       mean_first_review_hours,
       median_first_review_hours, p90_first_review_hours
FROM engineering.semantic.github(owner=>'example');
