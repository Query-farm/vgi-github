PREPARE github_ci_outcomes AS
SELECT workflow_run_count, workflow_run_success_count, workflow_run_failure_count,
       workflow_job_count, workflow_job_failure_count,
       workflow_artifact_count, workflow_artifact_bytes
FROM engineering.semantic.github(repository => $1);
