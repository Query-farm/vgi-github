PREPARE github_check_results AS
SELECT check_suite_count, check_run_count, successful_check_run_count,
       failed_check_run_count, unfinished_check_run_count,
       check_annotation_count, failure_annotation_count
FROM engineering.semantic.github(repository => $1, git_ref => $2);
