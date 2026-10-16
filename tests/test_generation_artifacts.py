"""Limited independent checks for reviewed policies and reproducible pilot artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
from graphql import build_schema, parse, validate

from scripts import generate_semantic_catalog as generator
from vgi_github.generation.artifacts import emit_artifacts, validate_semantics
from vgi_github.generation.overlay import load_overlay, overlay_bytes
from vgi_github.generation.schema import compile_contract, compile_graphql_entity

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _pilot_baseline():
    """Compile the immutable checked-in baseline once per test process."""
    overlay = load_overlay(ROOT / "generation/pilot.json")
    overlay_data = overlay_bytes(overlay)
    specs, sdl, lock = generator.locked_inputs(ROOT, overlay)
    contract = compile_contract(specs, sdl, overlay)
    provenance = {
        "overlay_sha256": hashlib.sha256(overlay_data).hexdigest(),
        "source_lock_sha256": hashlib.sha256(
            (ROOT / "generation/sources.lock.json").read_bytes()
        ).hexdigest(),
        "rest_revision": lock["rest_revision"],
        "graphql_revision": lock["graphql_revision"],
    }
    return overlay, contract, provenance


@pytest.fixture
def pilot():
    # Tests freely mutate their own contracts; the cached baseline never escapes.
    return deepcopy(_pilot_baseline())


def test_artifacts_are_deterministic_current_and_package_contents_are_linked(pilot):
    overlay, contract, provenance = pilot
    _, sdl, lock = generator.locked_inputs(ROOT, overlay)
    audit = {
        "api_inventory": generator.locked_inventory(ROOT, lock),
        "selected_sdl": sdl,
        "coverage_policy": json.loads((ROOT / "generation/coverage-policy.json").read_text()),
    }
    output = emit_artifacts(contract, overlay, provenance, **audit)
    assert output == emit_artifacts(
        deepcopy(contract), deepcopy(overlay), deepcopy(provenance), **deepcopy(audit)
    )
    generator.write_outputs(ROOT, output, check=True)
    package = json.loads(output["models/generated-pilot/github-generated.package.json"])
    document = package["documents"][0]
    assert document["content"] == output["models/generated-pilot/github-generated.crossfield.json"]
    assert document["sha256"] == hashlib.sha256(document["content"].encode()).hexdigest()
    assert package["reports"] == []
    assert len(package["documents"]) == 1
    model = json.loads(document["content"])
    assert set(model["metrics"]) == {
        "absent_user_follow_count",
        "accepted_devcontainer_permission_count",
        "actions_cache_bytes",
        "actions_cache_count",
        "actions_cache_usage_observation_count",
        "actions_concurrency_group_count",
        "actions_concurrency_member_count",
        "active_artifact_storage_record_count",
        "activity_event_count",
        "activity_feed_observation_count",
        "added_dependency_count",
        "agent_task_artifact_count",
        "agent_task_count",
        "api_core_requests_remaining",
        "api_metadata_observation_count",
        "api_octocat_observation_count",
        "api_rate_limit_observation_count",
        "api_root_observation_count",
        "api_version_count",
        "api_zen_observation_count",
        "approvable_pending_deployment_count",
        "approved_deployment_review_count",
        "approved_review_count",
        "archived_agent_task_count",
        "artifact_deployment_record_count",
        "artifact_metadata_job_count",
        "artifact_metadata_mutated_record_count",
        "artifact_storage_record_count",
        "assigned_pull_request_count",
        "attestation_envelope_count",
        "available_codespace_count",
        "available_copilot_report_count",
        "average_repository_community_health",
        "branch_count",
        "cancelled_agent_task_count",
        "check_annotation_count",
        "check_run_count",
        "check_step_count",
        "check_step_reported_seconds",
        "check_suite_count",
        "closed_project_count",
        "closed_security_campaign_count",
        "code_of_conduct_count",
        "code_quality_dismissed_finding_count",
        "code_quality_error_finding_count",
        "code_quality_finding_count",
        "code_quality_none_finding_count",
        "code_quality_note_finding_count",
        "code_quality_open_finding_count",
        "code_quality_warning_finding_count",
        "code_scanning_alert_count",
        "code_scanning_alert_instance_count",
        "code_scanning_analysis_count",
        "code_scanning_analysis_result_count",
        "code_scanning_autofix_status_count",
        "code_scanning_dismissal_request_count",
        "code_scanning_dismissed_alert_count",
        "code_scanning_fixed_alert_count",
        "code_scanning_high_security_alert_count",
        "code_scanning_open_alert_count",
        "code_scanning_organization_settings_count",
        "code_scanning_repository_settings_count",
        "code_scanning_sarif_content_count",
        "code_scanning_sarif_content_median_bytes",
        "code_scanning_sarif_upload_count",
        "codeowners_error_count",
        "codeql_database_archives_count",
        "codeql_database_archives_median_bytes",
        "codeql_database_bytes",
        "codeql_database_count",
        "codeql_variant_analysis_count",
        "codeql_variant_artifact_bytes",
        "codeql_variant_repository_task_count",
        "codeql_variant_result_count",
        "codespace_count",
        "codespace_creation_default_observation_count",
        "codespace_devcontainer_permission_check_count",
        "codespace_export_observation_count",
        "codespace_machine_option_count",
        "commit_added_lines",
        "commit_comment_active_days",
        "commit_comment_count",
        "commit_comment_repository_count",
        "commit_comparison_count",
        "commit_count",
        "commit_deleted_lines",
        "commit_file_added_lines",
        "commit_file_change_count",
        "commit_file_deleted_lines",
        "commit_pull_request_membership_count",
        "commit_status_reported_context_count",
        "commit_status_summaries_count",
        "commit_status_summaries_error_count",
        "commit_status_summaries_failure_count",
        "commit_status_summaries_pending_count",
        "commit_status_summaries_success_count",
        "commit_statuses_count",
        "commit_statuses_error_count",
        "commit_statuses_failure_count",
        "commit_statuses_pending_count",
        "commit_statuses_success_count",
        "comparison_file_change_count",
        "completed_agent_task_count",
        "completed_artifact_metadata_job_count",
        "configured_codespace_cpu_count",
        "configured_codespace_memory_bytes",
        "configured_codespace_storage_bytes",
        "confirmed_organization_membership_check_count",
        "confirmed_repository_collaborator_count",
        "confirmed_team_membership_check_count",
        "confirmed_team_repository_permission_check_count",
        "confirmed_user_follow_count",
        "copilot_inline_resource_count",
        "copilot_report_download_link_count",
        "copilot_repository_resource_count",
        "copilot_space_collaborator_count",
        "copilot_space_count",
        "copilot_space_resource_count",
        "copilot_team_collaborator_count",
        "copilot_text_resource_count",
        "copilot_user_collaborator_count",
        "critical_dependabot_alert_count",
        "critical_security_advisory_count",
        "custom_branch_environment_count",
        "deleted_package_version_count",
        "dependabot_alert_count",
        "dependabot_approved_dismissal_request_count",
        "dependabot_denied_dismissal_request_count",
        "dependabot_dismissal_request_count",
        "dependabot_expired_dismissal_request_count",
        "dependabot_pending_dismissal_request_count",
        "dependency_change_count",
        "dependency_change_vulnerability_count",
        "dependency_sbom_count",
        "dependency_sbom_report_content_count",
        "dependency_sbom_report_content_median_bytes",
        "dependency_sbom_report_pending_count",
        "deployment_branch_pattern_count",
        "deployment_branch_policy_count",
        "deployment_count",
        "deployment_protection_rule_count",
        "deployment_rule_integration_count",
        "deployment_status_count",
        "deployment_tag_pattern_count",
        "discussion_active_days",
        "discussion_comment_active_days",
        "discussion_comment_count",
        "discussion_comment_repository_count",
        "discussion_comment_unknown_repository_count",
        "discussion_count",
        "discussion_repository_count",
        "dismissed_dependabot_alert_count",
        "distinct_followed_user_count",
        "distinct_follower_count",
        "draft_release_count",
        "draft_security_advisory_count",
        "emoji_count",
        "enqueued_async_merge_count",
        "environment_count",
        "expired_repository_invitation_count",
        "failed_agent_task_count",
        "failed_artifact_metadata_job_count",
        "failed_check_run_count",
        "failed_check_step_count",
        "failed_codespace_export_count",
        "failed_deployment_status_count",
        "failed_organization_invitation_count",
        "failed_pages_build_count",
        "failure_annotation_count",
        "featured_license_count",
        "fixed_dependabot_alert_count",
        "gist_comment_count",
        "gist_count",
        "gist_file_bytes",
        "gist_file_entry_count",
        "gist_revision_additions",
        "gist_revision_count",
        "gist_revision_deletions",
        "gist_star_observation_count",
        "git_blob_bytes",
        "git_blob_count",
        "git_reference_count",
        "git_tag_object_count",
        "git_tree_blob_entry_count",
        "git_tree_count",
        "git_tree_entry_bytes",
        "git_tree_entry_count",
        "gitignore_template_count",
        "idle_agent_task_count",
        "ignored_repository_subscription_count",
        "in_progress_agent_task_count",
        "issue_active_days",
        "issue_applied_suggestion_count",
        "issue_assignable_count",
        "issue_assignment_capability_count",
        "issue_assignment_count",
        "issue_comment_active_days",
        "issue_comment_count",
        "issue_comment_repository_count",
        "issue_count",
        "issue_dependency_count",
        "issue_event_count",
        "issue_field_count",
        "issue_field_value_count",
        "issue_related_membership_count",
        "issue_repository_count",
        "issue_subissue_membership_count",
        "issue_suggestion_count",
        "issue_timeline_entry_count",
        "issue_type_count",
        "label_count",
        "labeled_pull_request_count",
        "latest_approved_reviewer_count",
        "latest_reviewer_review_count",
        "license_count",
        "malware_security_advisory_count",
        "mean_first_review_hours",
        "median_first_review_hours",
        "median_merge_hours",
        "median_release_asset_size_bytes",
        "median_workflow_job_execution_hours",
        "merged_prs",
        "merged_pull_request_check_count",
        "milestone_closed_work_item_count",
        "milestone_count",
        "milestone_open_work_item_count",
        "monthly_pr_total",
        "monthly_repository_pr_share",
        "monthly_user_pr_rank",
        "notification_count",
        "notification_subscription_observation_count",
        "numeric_project_field_value_count",
        "observed_agent_session_count",
        "offered_codespace_cpu_count",
        "open_dependabot_alert_count",
        "open_pull_request_stack_count",
        "open_security_campaign_count",
        "organization_cache_usage_observation_count",
        "organization_count",
        "organization_invitation_count",
        "organization_invitation_team_count",
        "organization_member_count",
        "organization_membership_check_count",
        "organization_membership_record_count",
        "organization_outside_collaborator_count",
        "organization_reported_active_cache_bytes",
        "organization_reported_active_cache_count",
        "p90_first_review_hours",
        "package_count",
        "package_version_count",
        "pages_build_count",
        "pages_build_reported_duration",
        "pages_deployment_status_count",
        "pages_site_count",
        "pending_artifact_metadata_job_count",
        "pending_deployment_review_count",
        "pending_deployment_reviewer_count",
        "pending_deployment_status_count",
        "pending_deployment_wait_minutes",
        "pending_organization_invitation_count",
        "pending_organization_membership_count",
        "pending_team_membership_count",
        "pr_first_review_at",
        "pr_first_review_hours",
        "prebuilt_codespace_count",
        "prerelease_count",
        "primary_user_email_count",
        "private_package_count",
        "processing_artifact_metadata_job_count",
        "production_deployment_count",
        "project_count",
        "project_draft_item_count",
        "project_field_count",
        "project_field_label_count",
        "project_field_pull_request_count",
        "project_field_reviewer_count",
        "project_field_user_count",
        "project_field_value_count",
        "project_issue_item_count",
        "project_item_count",
        "project_pull_request_item_count",
        "protected_branch_environment_count",
        "public_gist_count",
        "public_package_count",
        "published_release_count",
        "pull_request_active_days",
        "pull_request_assignee_membership_count",
        "pull_request_count",
        "pull_request_detail_observation_count",
        "pull_request_reported_comment_count",
        "pull_request_reported_review_comment_count",
        "pull_request_reported_commit_count",
        "pull_request_reported_additions",
        "pull_request_reported_deletions",
        "pull_request_reported_changed_file_count",
        "pull_request_file_additions",
        "pull_request_file_changes",
        "pull_request_file_count",
        "pull_request_file_deletions",
        "pull_request_label_membership_count",
        "pull_request_merge_check_count",
        "pull_request_merge_result_count",
        "pull_request_repository_count",
        "pull_request_review_comment_count",
        "pull_request_stack_count",
        "push_bypass_approved_count",
        "push_bypass_cancelled_count",
        "push_bypass_completed_count",
        "push_bypass_deleted_count",
        "push_bypass_denied_count",
        "push_bypass_expired_count",
        "push_bypass_open_count",
        "push_bypass_pending_count",
        "push_bypass_request_count",
        "push_bypass_response_count",
        "queued_agent_task_count",
        "reaction_count",
        "reaction_reactor_count",
        "reaction_thumbsdown_count",
        "reaction_thumbsup_count",
        "reaction_unknown_reactor_count",
        "ready_prebuild_machine_option_count",
        "rejected_deployment_review_count",
        "release_asset_content_count",
        "release_asset_content_median_bytes",
        "release_asset_count",
        "release_asset_download_count",
        "release_asset_size_bytes",
        "release_count",
        "release_publication_day_count",
        "release_reported_mention_count",
        "release_reported_reaction_count",
        "removed_dependency_count",
        "reported_active_cache_bytes",
        "reported_active_cache_count",
        "reported_agent_session_count",
        "reported_concurrency_member_count",
        "reported_contributor_commit_count",
        "reported_package_version_count",
        "repositories_with_topic_count",
        "repository_archives_count",
        "repository_archives_median_bytes",
        "repository_assignee_count",
        "repository_branch_deletion_count",
        "repository_change_count",
        "repository_clone_bucket_event_count",
        "repository_clone_bucket_unique_max",
        "repository_clone_count",
        "repository_clone_traffic_buckets_count",
        "repository_clone_traffic_observation_count",
        "repository_clone_unique_max",
        "repository_code_frequency_additions",
        "repository_code_frequency_signed_deletions",
        "repository_code_frequency_week_count",
        "repository_collaborator_check_count",
        "repository_commit_activity_commit_count",
        "repository_commit_activity_week_count",
        "repository_commit_punch_card_bucket_count",
        "repository_commit_punch_card_commit_count",
        "repository_community_profile_count",
        "repository_content_object_count",
        "repository_content_reported_size_bytes",
        "repository_contributor_observation_count",
        "repository_contributor_statistics_commit_count",
        "repository_contributor_statistics_observation_count",
        "repository_count",
        "repository_current_stars",
        "repository_devcontainer_count",
        "repository_force_push_count",
        "repository_fork_membership_count",
        "repository_hash_observation_count",
        "repository_invitation_count",
        "repository_language_bytes",
        "repository_language_count",
        "repository_license_file_bytes",
        "repository_license_file_count",
        "repository_participation_observation_count",
        "repository_permission_observation_count",
        "repository_property_definition_count",
        "repository_property_value_count",
        "repository_push_count",
        "repository_star_count",
        "repository_star_count_observation_count",
        "repository_star_observation_count",
        "repository_star_week_count",
        "repository_subscription_observation_count",
        "repository_tag_count",
        "repository_top_paths_count",
        "repository_top_paths_event_count",
        "repository_top_paths_unique_max",
        "repository_top_referrers_count",
        "repository_top_referrers_event_count",
        "repository_top_referrers_unique_max",
        "repository_topic_membership_count",
        "repository_view_bucket_event_count",
        "repository_view_bucket_unique_max",
        "repository_view_count",
        "repository_view_traffic_buckets_count",
        "repository_view_traffic_observation_count",
        "repository_view_unique_max",
        "repository_watcher_count",
        "repository_weekly_stars_created",
        "requested_team_review_count",
        "requested_user_review_count",
        "review_latest_rank",
        "review_record_count",
        "review_record_login",
        "review_record_state",
        "review_request_population_count",
        "reviewed_environment_association_count",
        "reviewed_pr_count",
        "rule_evaluation_count",
        "rule_suite_bypass_count",
        "rule_suite_count",
        "rule_suite_fail_count",
        "rule_suite_pass_count",
        "sbom_package_entry_count",
        "sbom_relationship_entry_count",
        "search_account_hit_count",
        "search_account_hit_max_score",
        "search_code_hit_count",
        "search_code_hit_max_score",
        "search_commit_hit_count",
        "search_commit_hit_max_score",
        "search_issue_hit_count",
        "search_issue_hit_max_score",
        "search_label_hit_count",
        "search_label_hit_max_score",
        "search_repository_hit_count",
        "search_repository_hit_max_score",
        "search_topic_hit_count",
        "search_topic_hit_max_score",
        "secret_scanning_active_alert_count",
        "secret_scanning_alert_count",
        "secret_scanning_bypass_approved_count",
        "secret_scanning_bypass_request_count",
        "secret_scanning_bypassed_alert_count",
        "secret_scanning_custom_pattern_count",
        "secret_scanning_dismissal_approved_count",
        "secret_scanning_dismissal_request_count",
        "secret_scanning_location_count",
        "secret_scanning_open_alert_count",
        "secret_scanning_pattern_configuration_count",
        "secret_scanning_protected_pattern_count",
        "secret_scanning_resolved_alert_count",
        "secret_scanning_scan_snapshot_count",
        "security_advisory_count",
        "security_campaign_closed_alert_occurrences",
        "security_campaign_count",
        "security_campaign_in_progress_alert_occurrences",
        "security_campaign_open_alert_occurrences",
        "sha256_repository_count",
        "shutdown_codespace_count",
        "stack_pull_request_membership_count",
        "starred_gist_observation_count",
        "starred_repository_observation_count",
        "submitted_review_count",
        "submitted_review_state",
        "submitted_reviewer_login",
        "subscribed_notification_count",
        "succeeded_codespace_export_count",
        "successful_async_merge_count",
        "successful_check_run_count",
        "successful_deployment_status_count",
        "successful_pages_build_count",
        "successful_pages_deployment_status_count",
        "team_count",
        "team_membership_check_count",
        "team_membership_count",
        "team_membership_record_count",
        "team_repository_access_count",
        "team_repository_permission_check_count",
        "timed_out_agent_task_count",
        "transient_deployment_count",
        "truncated_gist_count",
        "unconfirmed_organization_membership_check_count",
        "unconfirmed_repository_collaborator_count",
        "unconfirmed_team_membership_check_count",
        "unconfirmed_team_repository_permission_check_count",
        "unfinished_check_run_count",
        "unmerged_pull_request_check_count",
        "unread_notification_count",
        "uploaded_release_asset_count",
        "user_context_observation_count",
        "user_count",
        "user_email_count",
        "user_follow_check_count",
        "user_follow_relationship_count",
        "user_social_account_count",
        "verified_user_email_count",
        "waiting_for_user_agent_task_count",
        "workflow_artifact_archives_count",
        "workflow_artifact_archives_median_bytes",
        "workflow_artifact_bytes",
        "workflow_artifact_count",
        "workflow_attempt_log_archives_count",
        "workflow_attempt_log_archives_median_bytes",
        "workflow_count",
        "workflow_deployment_review_count",
        "workflow_job_cancelled_count",
        "workflow_job_count",
        "workflow_job_failure_count",
        "workflow_job_logs_count",
        "workflow_job_logs_median_bytes",
        "workflow_job_step_count",
        "workflow_job_step_failure_count",
        "workflow_job_success_count",
        "workflow_pending_deployment_count",
        "workflow_run_attempt_cancelled_count",
        "workflow_run_attempt_count",
        "workflow_run_attempt_failure_count",
        "workflow_run_attempt_success_count",
        "workflow_run_cancelled_count",
        "workflow_run_concurrency_group_count",
        "workflow_run_concurrency_member_count",
        "workflow_run_count",
        "workflow_run_failure_count",
        "workflow_run_log_archives_count",
        "workflow_run_log_archives_median_bytes",
        "workflow_run_success_count",
        "workflow_step_logs_count",
        "workflow_step_logs_median_bytes",
    }
    assert model["invocations"]["sources"]["pull_request_reviews"]["function"]["schema"] == "generated"
    coverage = json.loads(output["models/generated-pilot/coverage.json"])
    assert coverage["complete_worker_replacement"] is False
    assert set(coverage["sources"]) == {
        "account_lookup",
        "actions_artifact_lookup_source",
        "actions_attempt_jobs_source",
        "actions_attempt_lookup_source",
        "actions_cache_usage_source",
        "actions_caches_source",
        "actions_concurrency_group_lookup_source",
        "actions_concurrency_groups_source",
        "actions_deployment_reviews_source",
        "actions_job_lookup_source",
        "actions_organization_cache_total_source",
        "actions_organization_cache_usage_source",
        "actions_pending_deployments_source",
        "actions_repository_artifacts_source",
        "actions_repository_runs_source",
        "actions_run_artifacts_source",
        "actions_run_concurrency_groups_source",
        "actions_run_jobs_source",
        "actions_run_lookup_source",
        "actions_workflow_list_source",
        "actions_workflow_lookup_source",
        "actions_workflow_runs_source",
        "activity_events_network_source",
        "activity_events_organization_authenticated_source",
        "activity_events_organization_source",
        "activity_events_performed_public_source",
        "activity_events_performed_source",
        "activity_events_public_source",
        "activity_events_received_public_source",
        "activity_events_received_source",
        "activity_events_repository_source",
        "activity_feeds_source",
        "activity_repository_caller_source",
        "advisory_global_lookup_source",
        "advisory_global_source",
        "advisory_organization_source",
        "advisory_repository_lookup_source",
        "advisory_repository_source",
        "api_metadata_observations_source",
        "api_octocat_observations_source",
        "api_rate_limit_observations_source",
        "api_root_observations_source",
        "api_versions_source",
        "api_zen_observations_source",
        "artifact_deployment_records_source",
        "artifact_metadata_jobs_source",
        "artifact_storage_records_source",
        "attested_repository_lookup_source",
        "authenticated_agent_tasks_lookup_source",
        "authenticated_agent_tasks_source",
        "authenticated_codespaces_source",
        "authenticated_repository_discovery_source",
        "authenticated_repository_invitations_source",
        "authored_commit_comments_source",
        "authored_discussion_comments_source",
        "authored_discussions_source",
        "authored_issue_comments_source",
        "authored_issues_source",
        "authored_pull_requests_source",
        "canonical_issue_node_lookup_source",
        "canonical_label_node_lookup_source",
        "check_annotations_source",
        "check_run_graph_source",
        "check_run_lookup",
        "check_runs_for_suite_source",
        "check_steps_source",
        "check_suite_graph_source",
        "check_suite_lookup",
        "check_suites_for_ref_source",
        "code_quality_finding_lookup_source",
        "code_quality_findings_source",
        "code_scanning_alert_discovery_source",
        "code_scanning_alert_instances_source",
        "code_scanning_alert_lookup_source",
        "code_scanning_analyses_source",
        "code_scanning_analysis_lookup_source",
        "code_scanning_autofix_source",
        "code_scanning_default_setup_source",
        "code_scanning_dismissal_lookup_source",
        "code_scanning_dismissal_requests_source",
        "code_scanning_org_alert_discovery_source",
        "code_scanning_org_dismissal_source",
        "code_scanning_organization_ai_source",
        "code_scanning_repository_ai_source",
        "code_scanning_sarif_content_source",
        "code_scanning_sarif_status_source",
        "codeql_database_archives_source",
        "codeql_database_lookup_source",
        "codeql_databases_source",
        "codeql_variant_analysis_source",
        "codeql_variant_repository_task_source",
        "codeql_variant_targets_source",
        "codes_of_conduct_get_source",
        "codes_of_conduct_list_source",
        "codespace_creation_defaults_source",
        "codespace_devcontainer_permissions_source",
        "codespace_export_details_source",
        "codespace_lookup_source",
        "codespace_machines_source",
        "collaboration_authenticated_account_source",
        "commit_comparison_source",
        "commit_files_source",
        "commit_pull_request_memberships_source",
        "comparison_commits_source",
        "copilot_organization_space_collaborators_source",
        "copilot_organization_space_lookup_source",
        "copilot_organization_space_resource_lookup_source",
        "copilot_organization_space_resources_source",
        "copilot_organization_spaces_source",
        "copilot_user_space_collaborators_source",
        "copilot_user_space_lookup_source",
        "copilot_user_space_resource_lookup_source",
        "copilot_user_space_resources_source",
        "copilot_user_spaces_source",
        "dependabot_dismissal_lookup_source",
        "dependabot_dismissal_requests_source",
        "dependabot_lookup_source",
        "dependabot_org_dismissal_requests_source",
        "dependabot_organization_source",
        "dependabot_repository_source",
        "dependency_changes_source",
        "dependency_sbom_report_content_source",
        "dependency_sbom_source",
        "deployment_branch_policies_source",
        "deployment_branch_policy_lookup",
        "deployment_lookup",
        "deployment_protection_rule_lookup",
        "deployment_protection_rules_source",
        "deployment_rule_integrations_source",
        "deployment_status_lookup",
        "deployment_statuses_source",
        "deployments_source",
        "discussion_comment_replies_source",
        "discussion_lookup",
        "discussion_thread_comments_source",
        "emoji_dictionary_source",
        "environment_deployments_source",
        "environment_lookup",
        "environments_source",
        "filtered_repository_milestones_source",
        "gist_comment_get_source",
        "gist_comment_list_source",
        "gist_commit_list_source",
        "gist_files_source",
        "gist_forks_list_source",
        "gist_get_source",
        "gist_public_list_source",
        "gist_revision_get_source",
        "gist_star_status_source",
        "gist_starred_list_source",
        "gist_user_list_source",
        "gist_visible_list_source",
        "git_blob_lookup_source",
        "git_commit_lookup_source",
        "git_matching_references_source",
        "git_recursive_tree_entries_source",
        "git_reference_lookup_source",
        "git_tag_object_source",
        "git_tree_entries_source",
        "git_tree_lookup_source",
        "gitignore_templates_get_source",
        "gitignore_templates_list_source",
        "head_commit_branches_source",
        "issue_assignment_permission_issue_source",
        "issue_assignment_permission_repository_source",
        "issue_assignments_source",
        "issue_comment_lookup_source",
        "issue_event_discovery_source",
        "issue_event_lookup_source",
        "issue_field_values_source",
        "issue_labels_source",
        "issue_lookup",
        "issue_suggestions_all_states_source",
        "issue_suggestions_source",
        "issue_thread_comments_source",
        "issue_timeline_source",
        "label_issues_source",
        "label_pull_requests_source",
        "labels_source",
        "latest_release_lookup",
        "licenses_get_source",
        "licenses_list_source",
        "milestone_lookup_source",
        "notification_caller_source",
        "notification_lookup_source",
        "notification_repository_source",
        "notification_subscription_source",
        "organization_attestation_envelopes_source",
        "organization_attested_repositories_source",
        "organization_authenticated_list_source",
        "organization_codespaces_source",
        "organization_copilot_organization_day_report_source",
        "organization_copilot_organization_latest_report_source",
        "organization_copilot_repositories_day_report_source",
        "organization_copilot_user_teams_day_report_source",
        "organization_copilot_users_day_report_source",
        "organization_copilot_users_latest_report_source",
        "organization_directory_source",
        "organization_discovered_profile_source",
        "organization_discussion_comments_source",
        "organization_failed_invitations_source",
        "organization_invitation_teams_source",
        "organization_issue_fields_source",
        "organization_issue_types_source",
        "organization_lookup",
        "organization_member_codespaces_source",
        "organization_member_identity_source",
        "organization_members_source",
        "organization_membership_authenticated_list_source",
        "organization_membership_authenticated_source",
        "organization_membership_named_source",
        "organization_membership_public_check_source",
        "organization_membership_visible_check_source",
        "organization_memberships_summary_source",
        "organization_outside_collaborators_source",
        "organization_pending_invitations_source",
        "organization_property_definition_lookup_source",
        "organization_property_definitions_source",
        "organization_property_repositories_source",
        "organization_property_repository_lookup_source",
        "organization_public_memberships_source",
        "organization_push_bypass_requests_source",
        "organization_repositories",
        "organization_rule_suite_discovery_source",
        "organization_rule_suite_lookup_source",
        "package_authenticated_conflicts_source",
        "package_authenticated_list_source",
        "package_authenticated_lookup_source",
        "package_authenticated_owner_source",
        "package_authenticated_version_source",
        "package_authenticated_versions_source",
        "package_organization_conflicts_source",
        "package_organization_list_source",
        "package_organization_lookup_source",
        "package_organization_owner_source",
        "package_organization_version_source",
        "package_organization_versions_source",
        "package_user_conflicts_source",
        "package_user_list_source",
        "package_user_lookup_source",
        "package_user_owner_source",
        "package_user_version_source",
        "package_user_versions_source",
        "pages_build_latest_source",
        "pages_build_list_source",
        "pages_build_lookup_source",
        "pages_deployment_status_lookup",
        "pages_site_source",
        "project_field_labels_source",
        "project_field_pull_requests_source",
        "project_field_reviewers_source",
        "project_field_users_source",
        "project_fields_org_list_source",
        "project_fields_org_lookup_source",
        "project_fields_user_list_source",
        "project_fields_user_lookup_source",
        "project_item_lookup_source",
        "project_item_rest_list_hydration_source",
        "project_item_rest_lookup_hydration_source",
        "project_items_list_source",
        "project_items_rest_org_list_source",
        "project_items_rest_org_lookup_source",
        "project_items_rest_org_view_source",
        "project_items_rest_user_list_source",
        "project_items_rest_user_lookup_source",
        "project_items_rest_user_view_source",
        "project_values_named_source",
        "project_values_source",
        "projects_org_list_source",
        "projects_org_lookup_source",
        "projects_user_list_source",
        "projects_user_lookup_source",
        "public_repository_discovery_source",
        "pull_request_commits_source",
        "pull_request_counts_source",
        "pull_request_detail_lookup_source",
        "pull_request_files_source",
        "pull_request_labels_source",
        "pull_request_list",
        "pull_request_lookup",
        "pull_request_merge_result_source",
        "pull_request_merge_status_source",
        "pull_request_requested_reviewers_source",
        "pull_request_review_lookup_source",
        "pull_request_stack_lookup_source",
        "pull_request_stacks_source",
        "reaction_commit_comment_nodes_subject_source",
        "reaction_commit_comments_source",
        "reaction_commit_comments_subject_source",
        "reaction_issue_comment_nodes_subject_source",
        "reaction_issue_comments_source",
        "reaction_issue_comments_subject_source",
        "reaction_issue_threads_source",
        "reaction_issue_threads_subject_source",
        "reaction_releases_source",
        "reaction_releases_subject_source",
        "reaction_review_comments_source",
        "reaction_review_comments_subject_source",
        "release_asset_content_source",
        "release_asset_lookup",
        "release_assets_source",
        "release_lookup",
        "release_tag_lookup",
        "releases_source",
        "repository_agent_tasks_lookup_source",
        "repository_agent_tasks_source",
        "repository_attestation_envelopes_source",
        "repository_branch_lookup_source",
        "repository_branches_source",
        "repository_changes_source",
        "repository_clone_traffic_buckets_source",
        "repository_clone_traffic_source",
        "repository_code_frequency_source",
        "repository_codeowners_errors_source",
        "repository_codespace_machines_source",
        "repository_codespaces_source",
        "repository_collaborator_checks_source",
        "repository_collaborator_permissions_source",
        "repository_collaborators_source",
        "repository_commit_activity_source",
        "repository_commit_comments_source",
        "repository_commit_history_source",
        "repository_commit_lookup_source",
        "repository_commit_punch_card_source",
        "repository_commit_status_contexts_source",
        "repository_commit_status_summary_source",
        "repository_commit_statuses_source",
        "repository_community_profiles_source",
        "repository_content_path_source",
        "repository_contributor_observations_source",
        "repository_contributor_statistics_source",
        "repository_devcontainers_source",
        "repository_directory_readme_source",
        "repository_discussions_source",
        "repository_eligible_assignees_source",
        "repository_fork_discovery_source",
        "repository_hash_algorithms_source",
        "repository_invitations_source",
        "repository_issue_comments_source",
        "repository_issue_events_source",
        "repository_issue_types_source",
        "repository_issues_source",
        "repository_languages_source",
        "repository_license_file_source",
        "repository_lookup",
        "repository_milestones_source",
        "repository_participation_statistics_source",
        "repository_property_values_source",
        "repository_push_bypass_lookup_source",
        "repository_push_bypass_requests_source",
        "repository_readme_source",
        "repository_rule_suite_discovery_source",
        "repository_rule_suite_lookup_source",
        "repository_star_counts_source",
        "repository_star_history_source",
        "repository_star_status_source",
        "repository_stars_authenticated_source",
        "repository_stars_by_repository_source",
        "repository_stars_user_source",
        "repository_subscription_source",
        "repository_tags_source",
        "repository_tar_archive_source",
        "repository_teams_source",
        "repository_top_paths_source",
        "repository_top_referrers_source",
        "repository_topic_memberships_source",
        "repository_view_traffic_buckets_source",
        "repository_view_traffic_source",
        "repository_watchers_authenticated_source",
        "repository_watchers_by_repository_source",
        "repository_watchers_user_source",
        "repository_zip_archive_source",
        "rest_commit_comment_lookup_source",
        "rest_commit_comments_source",
        "rest_get_parent_source",
        "rest_issue_lookup_source",
        "rest_labels_lookup_source",
        "rest_labels_milestones_source",
        "rest_labels_rest_issues_source",
        "rest_labels_rest_repositories_source",
        "rest_list_dependencies_blocked_by_source",
        "rest_list_dependencies_blocking_source",
        "rest_list_relates_to_source",
        "rest_list_sub_issues_source",
        "rest_repository_commit_comments_source",
        "rest_repository_issue_discovery_source",
        "rest_viewer_member_issues_source",
        "rest_viewer_organization_issues_source",
        "rest_viewer_visible_issues_source",
        "review_comments_lookup_source",
        "review_comments_pull_request_source",
        "review_comments_repository_source",
        "review_comments_review_source",
        "reviews_source",
        "search_account_hits_source",
        "search_code_hits_source",
        "search_commit_hits_source",
        "search_issue_hits_source",
        "search_issue_subject_source",
        "search_label_hits_source",
        "search_repository_hits_source",
        "search_topic_hits_source",
        "secret_scanning_alert_discovery_source",
        "secret_scanning_alert_lookup_source",
        "secret_scanning_bypass_lookup_source",
        "secret_scanning_bypass_requests_source",
        "secret_scanning_dismissal_lookup_source",
        "secret_scanning_dismissal_requests_source",
        "secret_scanning_history_source",
        "secret_scanning_locations_source",
        "secret_scanning_org_alert_discovery_source",
        "secret_scanning_org_bypass_source",
        "secret_scanning_org_dismissal_source",
        "secret_scanning_org_patterns_source",
        "secret_scanning_pattern_configuration_source",
        "secret_scanning_repo_patterns_source",
        "security_campaign_lookup_source",
        "security_campaigns_source",
        "team_children_named_source",
        "team_children_numeric_source",
        "team_identity_authenticated_source",
        "team_identity_lookup_source",
        "team_identity_named_context_source",
        "team_identity_numeric_source",
        "team_identity_repository_source",
        "team_identity_summary_source",
        "team_invitations_named_source",
        "team_invitations_numeric_source",
        "team_lookup",
        "team_member_identity_context_source",
        "team_members_named_identity_source",
        "team_members_numeric_identity_source",
        "team_members_source",
        "team_membership_check_source",
        "team_membership_named_object_source",
        "team_membership_numeric_object_source",
        "team_repositories_source",
        "team_repository_access_named_source",
        "team_repository_access_numeric_source",
        "team_repository_check_named_source",
        "team_repository_check_numeric_source",
        "team_repository_permission_named_source",
        "team_repository_permission_numeric_source",
        "team_repository_reverse_source",
        "teams_source",
        "user_attestation_envelopes_source",
        "user_context_source",
        "user_context_subject_source",
        "user_emails_all_source",
        "user_emails_public_source",
        "user_follow_check_authenticated_source",
        "user_follow_check_source",
        "user_follow_target_source",
        "user_followers_authenticated_source",
        "user_followers_source",
        "user_following_authenticated_source",
        "user_following_source",
        "user_identity_authenticated_source",
        "user_identity_by_id_source",
        "user_identity_directory_source",
        "user_identity_discovered_profile_source",
        "user_organizations_source",
        "user_profile_lookup",
        "user_public_organization_memberships_source",
        "user_repositories",
        "user_social_accounts_authenticated_source",
        "user_social_accounts_source",
        "workflow_artifact_archives_source",
        "workflow_attempt_log_archives_source",
        "workflow_job_logs_source",
        "workflow_run_log_archives_source",
        "workflow_step_logs_source",
    }
    assert {entity["name"] for entity in coverage["entities"]} == {
        "actions_cache_usage",
        "actions_caches",
        "actions_concurrency_groups",
        "activity_events",
        "activity_feed_observations",
        "agent_tasks",
        "api_metadata_observations",
        "api_octocat_observations",
        "api_rate_limit_observations",
        "api_root_observations",
        "api_versions",
        "api_zen_observations",
        "artifact_deployment_records",
        "artifact_metadata_jobs",
        "artifact_storage_records",
        "attestation_envelopes",
        "branches",
        "check_annotations",
        "check_runs",
        "check_steps",
        "check_suites",
        "code_quality_findings",
        "code_scanning_alert_instances",
        "code_scanning_alerts",
        "code_scanning_analyses",
        "code_scanning_autofixes",
        "code_scanning_dismissal_requests",
        "code_scanning_organization_settings",
        "code_scanning_repository_settings",
        "code_scanning_sarif_content",
        "code_scanning_sarif_uploads",
        "codeql_database_archives",
        "codeql_databases",
        "codeql_variant_analyses",
        "codeql_variant_repository_tasks",
        "codes_of_conduct",
        "codespace_creation_defaults",
        "codespace_devcontainer_permissions",
        "codespace_export_observations",
        "codespace_machine_options",
        "codespaces",
        "commit_comments",
        "commit_comparisons",
        "commit_files",
        "commit_pull_request_memberships",
        "commit_status_summaries",
        "commit_statuses",
        "commits",
        "copilot_report_metadata",
        "copilot_space_collaborators",
        "copilot_space_resources",
        "copilot_spaces",
        "dependabot_alerts",
        "dependabot_dismissal_requests",
        "dependency_changes",
        "dependency_sbom_report_content",
        "dependency_sboms",
        "deployment_branch_policies",
        "deployment_protection_rules",
        "deployment_rule_integrations",
        "deployment_statuses",
        "deployments",
        "discussion_comments",
        "discussions",
        "emojis",
        "environments",
        "gist_comments",
        "gist_files",
        "gist_revisions",
        "gist_star_observations",
        "gists",
        "git_blobs",
        "git_references",
        "git_tag_objects",
        "git_tree_entries",
        "git_trees",
        "gitignore_templates",
        "issue_assignment_capabilities",
        "issue_assignments",
        "issue_comments",
        "issue_dependencies",
        "issue_events",
        "issue_field_values",
        "issue_fields",
        "issue_related_memberships",
        "issue_subissue_memberships",
        "issue_suggestions",
        "issue_timeline_entries",
        "issue_types",
        "issues",
        "licenses",
        "milestones",
        "notification_subscriptions",
        "notifications",
        "organization_actions_cache_usage",
        "organization_invitation_teams",
        "organization_invitations",
        "organization_membership_checks",
        "organization_memberships",
        "organization_outside_collaborators",
        "organizations",
        "package_versions",
        "packages",
        "pages_builds",
        "pages_deployment_statuses",
        "pages_sites",
        "project_field_labels",
        "project_field_pull_requests",
        "project_field_reviewers",
        "project_field_users",
        "project_field_values",
        "project_fields",
        "project_items",
        "projects",
        "pull_request_files",
        "pull_request_merge_results",
        "pull_request_merge_statuses",
        "pull_request_review_comments",
        "pull_request_review_requests",
        "pull_request_reviews",
        "pull_request_stacks",
        "pull_requests",
        "push_bypass_requests",
        "reactions",
        "release_asset_content",
        "release_assets",
        "releases",
        "repositories",
        "repository_archives",
        "repository_assignees",
        "repository_changes",
        "repository_clone_traffic",
        "repository_clone_traffic_buckets",
        "repository_code_frequency",
        "repository_codeowners_errors",
        "repository_collaborator_checks",
        "repository_collaborator_permissions",
        "repository_commit_activity",
        "repository_commit_punch_card",
        "repository_community_profiles",
        "repository_contents",
        "repository_contributor_observations",
        "repository_contributor_statistics",
        "repository_devcontainers",
        "repository_fork_memberships",
        "repository_hash_observations",
        "repository_invitations",
        "repository_labels",
        "repository_languages",
        "repository_license_files",
        "repository_participation_statistics",
        "repository_property_definitions",
        "repository_property_values",
        "repository_star_counts",
        "repository_star_history",
        "repository_star_observations",
        "repository_stars",
        "repository_subscriptions",
        "repository_tags",
        "repository_top_paths",
        "repository_top_referrers",
        "repository_topics",
        "repository_view_traffic",
        "repository_view_traffic_buckets",
        "repository_watchers",
        "rule_suites",
        "search_account_hits",
        "search_code_hits",
        "search_commit_hits",
        "search_issue_hits",
        "search_label_hits",
        "search_repository_hits",
        "search_topic_hits",
        "secret_scanning_alerts",
        "secret_scanning_bypass_requests",
        "secret_scanning_custom_patterns",
        "secret_scanning_dismissal_requests",
        "secret_scanning_locations",
        "secret_scanning_pattern_configurations",
        "secret_scanning_scan_snapshots",
        "security_advisories",
        "security_campaigns",
        "team_membership_checks",
        "team_memberships",
        "team_repository_access",
        "team_repository_permission_checks",
        "teams",
        "user_context_observations",
        "user_emails",
        "user_follow_checks",
        "user_follow_relationships",
        "user_social_accounts",
        "users",
        "workflow_artifact_archives",
        "workflow_artifacts",
        "workflow_attempt_log_archives",
        "workflow_deployment_reviews",
        "workflow_job_logs",
        "workflow_jobs",
        "workflow_pending_deployments",
        "workflow_run_attempts",
        "workflow_run_concurrency_groups",
        "workflow_run_log_archives",
        "workflow_runs",
        "workflow_step_logs",
        "workflows",
    }
    assert all(source["profile"] == "producer_sync_v1" for source in model["invocations"]["sources"].values())
    assert model["invocations"]["input_contracts"] == {}
    assert model["semantic_query"]["parameters"]["owner"]["default"] is None
    assert model["semantic_query"]["parameters"]["repository"]["default"] is None
    assert model["policy"]["field_semantics"]["repositories.repository"]["sql_name"] == "repository_name"
    assert "pull_request_reviews.author_login" not in model["policy"]["dimensions"]
    assert model["policy"]["metric_semantics"]["median_merge_hours"]["additivity"] == "non_additive"
    assert {relationship["name"] for relationship in model["relationships"]} == {
        "actions_cache_usage_to_repositories",
        "actions_caches_to_repositories",
        "actions_concurrency_groups_to_repositories",
        "activity_events_to_organizations",
        "activity_events_to_repositories",
        "activity_events_to_users",
        "agent_tasks_to_repositories",
        "artifact_deployment_records_to_organizations",
        "artifact_metadata_jobs_to_organizations",
        "artifact_storage_records_to_organizations",
        "attestation_envelopes_to_repositories",
        "attestation_envelopes_to_scope_organizations",
        "attestation_envelopes_to_scope_users",
        "branches_to_head_commits",
        "branches_to_repositories",
        "check_annotations_to_repositories",
        "check_annotations_to_runs",
        "check_runs_to_deployments",
        "check_runs_to_repositories",
        "check_runs_to_suites",
        "check_steps_to_check_runs",
        "check_suites_to_creators",
        "check_suites_to_repositories",
        "check_suites_to_workflow_runs",
        "code_quality_findings_to_repositories",
        "code_scanning_alert_instances_to_alerts",
        "code_scanning_alert_instances_to_repositories",
        "code_scanning_alerts_to_repositories",
        "code_scanning_analyses_to_repositories",
        "code_scanning_analyses_to_sarif_uploads",
        "code_scanning_autofixes_to_alerts",
        "code_scanning_autofixes_to_repositories",
        "code_scanning_dismissal_requests_to_repositories",
        "code_scanning_organization_settings_to_organizations",
        "code_scanning_repository_settings_to_repositories",
        "code_scanning_sarif_content_to_code_scanning_analyses",
        "code_scanning_sarif_uploads_to_repositories",
        "codeql_database_archives_to_codeql_databases",
        "codeql_databases_to_repositories",
        "codeql_variant_analyses_to_repositories",
        "codeql_variant_repository_tasks_to_repositories",
        "codeql_variant_tasks_to_analyses",
        "codeql_variant_tasks_to_target_repositories",
        "codespace_creation_defaults_to_repositories",
        "codespace_devcontainer_permissions_to_repositories",
        "codespace_export_observations_to_codespaces",
        "codespace_export_observations_to_repositories",
        "codespace_machine_options_to_codespaces",
        "codespace_machine_options_to_repositories",
        "codespace_permissions_to_devcontainers",
        "codespaces_to_owners",
        "codespaces_to_repositories",
        "commit_comments_to_authors",
        "commit_comments_to_commits",
        "commit_comparisons_to_repositories",
        "commit_files_to_commits",
        "commit_files_to_repositories",
        "commit_pr_memberships_to_commits",
        "commit_pr_memberships_to_pull_requests",
        "commit_pull_request_memberships_to_repositories",
        "commit_status_summaries_to_repositories",
        "commit_statuses_to_repositories",
        "commit_statuses_to_summaries",
        "commits_to_repositories",
        "commits_to_trees",
        "copilot_reports_to_organizations",
        "copilot_space_collaborators_to_spaces",
        "copilot_space_resources_to_spaces",
        "copilot_spaces_to_creators",
        "dependabot_alerts_to_advisories",
        "dependabot_alerts_to_dismissers",
        "dependabot_alerts_to_repositories",
        "dependabot_dismissal_requests_to_alerts",
        "dependabot_dismissal_requests_to_organizations",
        "dependabot_dismissal_requests_to_repositories",
        "dependabot_dismissal_requests_to_requesters",
        "dependency_changes_to_repositories",
        "dependency_sbom_report_content_to_repositories",
        "dependency_sboms_to_repositories",
        "deployment_branch_policies_to_environments",
        "deployment_branch_policies_to_repositories",
        "deployment_protection_rules_to_environments",
        "deployment_protection_rules_to_repositories",
        "deployment_reviews_to_reviewers",
        "deployment_rule_integrations_to_environments",
        "deployment_rule_integrations_to_repositories",
        "deployment_statuses_to_creators",
        "deployment_statuses_to_deployments",
        "deployment_statuses_to_repositories",
        "deployments_to_creators",
        "deployments_to_repositories",
        "discussion_comments_to_authors",
        "discussions_to_authors",
        "environments_to_repositories",
        "gist_comments_to_gists",
        "gist_comments_to_users",
        "gist_files_to_gists",
        "gist_revisions_to_gists",
        "gist_revisions_to_users",
        "gist_star_observations_to_gists",
        "gist_star_observations_to_users",
        "gists_to_parent_gists",
        "gists_to_users",
        "git_blobs_to_repositories",
        "git_references_to_repositories",
        "git_tag_objects_to_repositories",
        "git_tree_entries_to_repositories",
        "git_trees_to_repositories",
        "invitation_teams_to_invitations",
        "invitation_teams_to_teams",
        "issue_assignment_capabilities_to_repositories",
        "issue_assignments_to_repositories",
        "issue_comments_to_authors",
        "issue_dependencies_to_blocked_issues",
        "issue_dependencies_to_blocking_issues",
        "issue_events_to_issues",
        "issue_events_to_repositories",
        "issue_field_values_to_repositories",
        "issue_fields_to_organizations",
        "issue_related_memberships_to_related_issues",
        "issue_related_memberships_to_source_issues",
        "issue_subissue_memberships_to_child_issues",
        "issue_subissue_memberships_to_parent_issues",
        "issue_suggestions_to_repositories",
        "issue_timeline_entries_to_repositories",
        "issue_types_to_organizations",
        "issues_to_authors",
        "labels_to_repositories",
        "membership_checks_to_members",
        "membership_checks_to_organizations",
        "memberships_to_organizations",
        "milestones_to_repositories",
        "notification_subscriptions_to_notifications",
        "notifications_to_repositories",
        "notifications_to_users",
        "organization_cache_usage_to_organizations",
        "organization_invitations_to_organizations",
        "outside_collaborators_to_organizations",
        "outside_collaborators_to_users",
        "package_versions_to_packages",
        "packages_to_repositories",
        "pages_builds_to_commits",
        "pages_builds_to_pages_sites",
        "pages_builds_to_repositories",
        "pages_builds_to_users",
        "pages_deployment_statuses_to_repositories",
        "pages_sites_to_repositories",
        "pending_deployments_to_environments",
        "project_field_labels_to_values",
        "project_field_pull_requests_to_values",
        "project_field_reviewers_to_values",
        "project_field_users_to_values",
        "project_fields_to_projects",
        "project_items_to_projects",
        "project_values_to_fields",
        "project_values_to_items",
        "property_definitions_to_organizations",
        "pull_request_files_to_pull_requests",
        "pull_request_files_to_repositories",
        "pull_request_merge_results_to_pull_requests",
        "pull_request_merge_results_to_repositories",
        "pull_request_merge_statuses_to_pull_requests",
        "pull_request_merge_statuses_to_repositories",
        "pull_request_review_comments_to_pull_requests",
        "pull_request_review_comments_to_repositories",
        "pull_request_review_requests_to_pull_requests",
        "pull_request_review_requests_to_repositories",
        "pull_request_stacks_to_repositories",
        "pull_requests_to_authors",
        "pull_requests_to_repositories",
        "push_bypass_requests_to_repositories",
        "reactions_to_commit_comments",
        "reactions_to_issue_comments",
        "reactions_to_issues",
        "reactions_to_pull_requests",
        "reactions_to_reactors",
        "reactions_to_releases",
        "reactions_to_repositories",
        "reactions_to_review_comments",
        "release_asset_content_to_release_assets",
        "release_assets_to_releases",
        "release_assets_to_repositories",
        "release_assets_to_uploaders",
        "releases_to_publishers",
        "releases_to_repositories",
        "repositories_to_organizations",
        "repository_archives_to_repositories",
        "repository_assignees_to_repositories",
        "repository_changes_to_repositories",
        "repository_changes_to_users",
        "repository_clone_traffic_buckets_to_repositories",
        "repository_clone_traffic_to_repositories",
        "repository_code_frequency_to_repositories",
        "repository_codeowners_errors_to_repositories",
        "repository_collaborator_checks_to_repositories",
        "repository_collaborator_permissions_to_repositories",
        "repository_commit_activity_to_repositories",
        "repository_commit_punch_card_to_repositories",
        "repository_community_profiles_to_repositories",
        "repository_contents_to_git_trees",
        "repository_contents_to_repositories",
        "repository_contributor_observations_to_repositories",
        "repository_contributor_statistics_to_repositories",
        "repository_contributor_statistics_to_users",
        "repository_devcontainers_to_repositories",
        "repository_forks_to_parents",
        "repository_forks_to_repositories",
        "repository_hash_observations_to_repositories",
        "repository_invitations_to_invitee",
        "repository_invitations_to_inviter",
        "repository_invitations_to_repositories",
        "repository_languages_to_repositories",
        "repository_license_files_to_licenses",
        "repository_license_files_to_repositories",
        "repository_participation_statistics_to_repositories",
        "repository_property_values_to_repositories",
        "repository_star_counts_to_repositories",
        "repository_star_history_to_repositories",
        "repository_stars_to_repositories",
        "repository_stars_to_users",
        "repository_subscriptions_to_repositories",
        "repository_subscriptions_to_users",
        "repository_tags_to_commits",
        "repository_tags_to_repositories",
        "repository_top_paths_to_repositories",
        "repository_top_referrers_to_repositories",
        "repository_topics_to_repositories",
        "repository_view_traffic_buckets_to_repositories",
        "repository_view_traffic_to_repositories",
        "repository_watchers_to_repositories",
        "repository_watchers_to_users",
        "review_comments_to_authors",
        "review_comments_to_parent_comments",
        "review_comments_to_reviews",
        "reviews_to_pull_requests",
        "rule_suites_to_repositories",
        "run_concurrency_groups_to_groups",
        "search_account_hits_to_organizations",
        "search_account_hits_to_users",
        "search_code_hits_to_repositories",
        "search_commit_hits_to_commits",
        "search_commit_hits_to_repositories",
        "search_issue_hits_to_issues",
        "search_issue_hits_to_pull_requests",
        "search_issue_hits_to_repositories",
        "search_label_hits_to_repositories",
        "search_label_hits_to_repository_labels",
        "search_repository_hits_to_repositories",
        "secret_scanning_alerts_to_repositories",
        "secret_scanning_bypass_requests_to_repositories",
        "secret_scanning_custom_patterns_to_organizations",
        "secret_scanning_custom_patterns_to_repositories",
        "secret_scanning_dismissal_requests_to_repositories",
        "secret_scanning_locations_to_alerts",
        "secret_scanning_locations_to_repositories",
        "secret_scanning_pattern_configurations_to_organizations",
        "secret_scanning_scan_snapshots_to_repositories",
        "security_advisories_to_advisory_author",
        "security_advisories_to_advisory_publisher",
        "security_advisories_to_repositories",
        "security_campaigns_to_organizations",
        "team_checks_to_members",
        "team_checks_to_teams",
        "team_memberships_to_teams",
        "team_repository_access_to_repositories",
        "team_repository_access_to_teams",
        "team_repository_checks_to_teams",
        "teams_to_organizations",
        "teams_to_parent_team",
        "tree_entries_to_trees",
        "user_context_observations_to_users",
        "user_emails_to_users",
        "user_follow_checks_to_followeds",
        "user_follow_checks_to_followers",
        "user_follow_relationships_to_followeds",
        "user_follow_relationships_to_followers",
        "user_social_accounts_to_users",
        "workflow_artifact_archives_to_workflow_artifacts",
        "workflow_artifacts_to_repositories",
        "workflow_artifacts_to_runs",
        "workflow_attempt_log_archives_to_workflow_run_attempts",
        "workflow_attempts_to_runs",
        "workflow_deployment_reviews_to_repositories",
        "workflow_deployment_reviews_to_runs",
        "workflow_job_logs_to_workflow_jobs",
        "workflow_jobs_to_attempts",
        "workflow_jobs_to_repositories",
        "workflow_jobs_to_runs",
        "workflow_pending_deployments_to_repositories",
        "workflow_pending_deployments_to_runs",
        "workflow_run_attempts_to_repositories",
        "workflow_run_concurrency_groups_to_repositories",
        "workflow_run_concurrency_groups_to_runs",
        "workflow_run_log_archives_to_workflow_runs",
        "workflow_runs_to_repositories",
        "workflow_runs_to_workflows",
        "workflow_step_logs_to_workflow_jobs",
        "workflows_to_repositories",
    }
    assert "imports" not in model
    assert {metadata["key_evidence"] for metadata in model["policy"]["dataset_semantics"].values()} == {
        "declared"
    }
    assert {metadata["key_evidence"] for metadata in model["policy"]["relationship_semantics"].values()} == {
        "declared"
    }


def test_reports_are_optional_conveniences(pilot):
    overlay, contract, provenance = pilot
    entity = contract["functions"][0]
    entity["semantics"]["detail_report"] = {"name": "inventory", "comment": "Optional repository inventory."}
    package = json.loads(
        emit_artifacts(contract, overlay, provenance)["models/generated-pilot/github-generated.package.json"]
    )
    assert [report["name"] for report in package["reports"]] == ["inventory"]


def test_semantic_parameters_publish_typed_examples_without_turning_them_into_defaults(pilot):
    overlay, contract, provenance = pilot
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    parameters = model["semantic_query"]["parameters"]
    examples = {
        "activity_view": "performed",
        "advisory_state": "published",
        "advisory_type": "reviewed",
        "agent_task_archived": False,
        "agent_task_creator_ids": [8101, 8102],
        "agent_task_direction": "desc",
        "agent_task_id": "task-001",
        "agent_task_since": "2026-09-01T00:00:00Z",
        "agent_task_sort": "updated_at",
        "agent_task_states": "completed,failed",
        "ahead_of_job_id": 1,
        "ahead_of_run_id": 1,
        "artifact_cluster": "production",
        "artifact_id": 1,
        "artifact_metadata_job_id": 57001,
        "artifact_subject_digest": (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
        "assignee_login": "alice",
        "attempt_number": 1,
        "attestation_predicate_type": "provenance",
        "attestation_subject_digest": (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
        "attested_repositories": True,
        "authenticated_user": True,
        "blob_sha": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "branch_name": "main",
        "branch_protected": True,
        "bypass_repository_name": "crossfield",
        "bypass_request_number": 1,
        "bypass_request_status": "completed",
        "bypass_requester": "main",
        "bypass_reviewer": "main",
        "bypass_time_period": "hour",
        "cache_key": "linux-",
        "cache_ref": "refs/heads/main",
        "check_run_id": 4,
        "check_run_node_id": "CR_kwDOExample",
        "check_suite_id": 5,
        "check_suite_node_id": "CS_kwDOExample",
        "code_quality_finding_number": 1,
        "code_quality_finding_state": "open",
        "code_scanning_alert_number": 1,
        "code_scanning_analysis_id": 501,
        "code_scanning_assignees": "alice",
        "code_scanning_dismissal_period": "month",
        "code_scanning_dismissal_requester": "alice",
        "code_scanning_dismissal_reviewer": "bob",
        "code_scanning_dismissal_status": "all",
        "code_scanning_pr": 12,
        "code_scanning_ref": "refs/heads/main",
        "code_scanning_sarif_id": "upload-1",
        "code_scanning_severity": "high",
        "code_scanning_state": "open",
        "code_scanning_tool_guid": "tool-1",
        "code_scanning_tool_name": "CodeQL",
        "codeowners_ref": "main",
        "codeql_database_language": "python",
        "codeql_target_repository": "scan-fixture/target",
        "codeql_variant_analysis_id": 701,
        "codespace_client_ip": "192.0.2.1",
        "codespace_export_id": "latest",
        "codespace_location": "WestUs2",
        "codespace_name": "fixture-space-a",
        "codespace_ref": "main",
        "codespace_repository_id": 31001,
        "commit_author": "alice",
        "commit_comment_id": 701,
        "commit_comment_sha": "main",
        "commit_committer": "bob",
        "commit_comparison": "main...feature",
        "commit_history_ref": "main",
        "commit_path": "src/main.py",
        "commit_ref": "main",
        "commit_since": "2026-09-01T00:00:00Z",
        "commit_status_population": "latest",
        "commit_until": "2026-10-01T00:00:00Z",
        "concurrency_group": "deploy-main",
        "conduct_key": "contributor_covenant",
        "content_path": "README.md",
        "content_ref": "main",
        "contributor_anonymous": "true",
        "copilot_report_day": "2026-09-01",
        "copilot_report_kind": "organization_day",
        "copilot_space_number": 1,
        "copilot_space_resource_id": 1,
        "custom_property_name": "risk",
        "dependabot_alert_number": 1,
        "dependabot_dismissal_org_status": "all",
        "dependabot_dismissal_period": "month",
        "dependabot_dismissal_repository_name": "crossfield",
        "dependabot_dismissal_requester": "alice",
        "dependabot_dismissal_reviewer": "bob",
        "dependabot_dismissal_status": "all",
        "dependabot_ecosystem": "npm,pip",
        "dependabot_package": "example-library",
        "dependabot_scope": "runtime",
        "dependabot_severity": "high,critical",
        "dependabot_state": "open,fixed",
        "dependency_compare": "main...topic",
        "dependency_manifest": "package-lock.json",
        "deployment_branch_policy_id": 1,
        "deployment_id": 1,
        "deployment_protection_rule_id": 1,
        "deployment_status_id": 1,
        "devcontainer_path": ".devcontainer/devcontainer.json",
        "discussion_comment_id": "DC_kwDOExample",
        "discussion_number": 1,
        "environment_name": "production",
        "follow_direction": "followers",
        "followed_user": "identity-bob",
        "follower_user": "identity-alice",
        "forks_of": "Query-farm/crossfield",
        "ghsa_id": "GHSA-xxxx-yyyy-zzzz",
        "gist_comment_id": 1,
        "gist_id": "aa5a315d61ae9438b18d",
        "gist_population": "public",
        "gist_revision": "57a7f021a713b1c5a6a199b54cc514735d2d462f",
        "gist_since": "2025-01-01T00:00:00Z",
        "git_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "git_ref": "main",
        "git_tag_sha": "cccccccccccccccccccccccccccccccccccccccc",
        "gitignore_name": "Python",
        "global_advisory_id": "GHSA-xxxx-yyyy-zzzz",
        "head_commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "issue_advanced_search": "true",
        "issue_assignee": "alice",
        "issue_blocked_by": 2,
        "issue_blocking": 1,
        "issue_children_of": 1,
        "issue_comment_id": 501,
        "issue_creator": "alice",
        "issue_event_id": 601,
        "issue_filter": "all",
        "issue_labels": "bug,triage",
        "issue_mentioned": "bob",
        "issue_milestone": "1",
        "issue_node_id": "I_fixture",
        "issue_number": 1,
        "issue_parent_of": 2,
        "issue_related_to": 1,
        "issue_search_type": "hybrid",
        "issue_since": "2026-09-01T00:00:00Z",
        "issue_state": "all",
        "issue_suggestion_action": "add_label",
        "issue_suggestion_state": "pending",
        "job_id": 1,
        "label": "bug",
        "label_collection": True,
        "label_issue_number": 1,
        "license_featured": True,
        "license_key": "mit",
        "license_ref": "main",
        "membership_user": "identity-alice",
        "merge_request_uuid": "630b9d5e-3f2a-4f7e-8b0c-2d5f9a8c1e42",
        "milestone_number": 1,
        "milestone_state": "all",
        "notification_before": "2026-01-01T00:00:00Z",
        "notification_participating": True,
        "notification_since": "2025-01-01T00:00:00Z",
        "notification_thread_id": "1",
        "octocat_speech": "Hello",
        "organization": "Query-farm",
        "organization_directory": True,
        "organization_invitation_id": 3502,
        "organization_invitation_population": "pending",
        "organization_invitation_role": "direct_member",
        "organization_invitation_source": "member",
        "organization_membership_check": "visible",
        "organization_membership_state": "active",
        "organization_public_members": True,
        "organization_since_id": 2500,
        "outside_collaborator_filter": "all",
        "owner": "Query-farm",
        "package_name": "example-image",
        "package_population": "docker_migration_conflicts",
        "package_type": "container",
        "package_version_id": 1,
        "package_version_state": "active",
        "pages_build_id": 5472601,
        "pages_build_population": "latest",
        "pages_deployment_id": "1",
        "parent_gist_id": "aa5a315d61ae9438b18d",
        "parent_team_numeric_id": 3201,
        "parent_team_slug": "platform",
        "project_field_id": 10,
        "project_field_node_id": "PVTF1-10",
        "project_item_id": 1001,
        "project_item_node_id": "ITEM1",
        "project_item_query": "is:issue",
        "project_items_rest": True,
        "project_number": 1,
        "project_owners": [{"login": "example"}, {"login": "alice"}],
        "project_view_number": 1,
        "property_repository_query": "archived:false",
        "public_repositories": True,
        "public_repository_since_id": 1,
        "pull_request_number": 1,
        "reaction_commit_comment_node_id": "CC_fixture",
        "reaction_content": "heart",
        "reaction_issue_comment_node_id": "IC_fixture",
        "readme_directory": "docs",
        "recursive_tree_sha": "dddddddddddddddddddddddddddddddddddddddd",
        "ref_prefix": "heads/",
        "reference_name": "heads/main",
        "release_asset_id": 1,
        "release_id": 1,
        "release_selection": "latest",
        "release_tag": "v1.0.0",
        "repositories": [{"repository": "Query-farm/crossfield"}, {"repository": "Query-farm/vgi"}],
        "repository": "Query-farm/crossfield",
        "repository_access_type": "all",
        "repository_activity_actor": "octocat",
        "repository_activity_after": "opaque-after",
        "repository_activity_before": "opaque-before",
        "repository_activity_direction": "desc",
        "repository_activity_period": "month",
        "repository_activity_ref": "refs/heads/main",
        "repository_activity_type": "push",
        "repository_affiliation": "owner,collaborator,organization_member",
        "repository_direction": "asc",
        "repository_fork_sort": "newest",
        "repository_pushed_before": "2026-10-01T00:00:00Z",
        "repository_pushed_since": "2026-09-01T00:00:00Z",
        "repository_sort": "full_name",
        "repository_visibility": "all",
        "review_comment_id": 1,
        "review_id": 1,
        "rule_evaluation_actor": "main",
        "rule_evaluation_mode": "all",
        "rule_evaluation_ref": "main",
        "rule_evaluation_repository": "main",
        "rule_evaluation_result": "pass",
        "rule_evaluation_time_period": "hour",
        "rule_suite_id": 1,
        "run_id": 1,
        "sbom_uuid": "example",
        "search_code_sort": "indexed",
        "search_commits_sort": "author-date",
        "search_issues_sort": "comments",
        "search_labels_sort": "created",
        "search_order": "desc",
        "search_query": "crossfield",
        "search_repositories_sort": "stars",
        "search_users_sort": "followers",
        "secret_scanning_alert_number": 1,
        "secret_scanning_assignee": "alice",
        "secret_scanning_bypass_number": 41,
        "secret_scanning_bypass_status": "all",
        "secret_scanning_bypassed": True,
        "secret_scanning_dismissal_status": "all",
        "secret_scanning_exclude_providers": "example",
        "secret_scanning_exclude_secret_types": "custom_pattern_1",
        "secret_scanning_hide_secret": True,
        "secret_scanning_included_metadata": "owner-email,secret-id",
        "secret_scanning_multi_repo": True,
        "secret_scanning_owner_email_hash": (
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
        "secret_scanning_pattern_push_protection": "enabled",
        "secret_scanning_pattern_state": "published",
        "secret_scanning_providers": "github",
        "secret_scanning_publicly_leaked": True,
        "secret_scanning_request_period": "month",
        "secret_scanning_request_requester": "alice",
        "secret_scanning_request_reviewer": "bob",
        "secret_scanning_resolution": "revoked",
        "secret_scanning_secret_type": "github_personal_access_token",
        "secret_scanning_state": "open",
        "secret_scanning_validity": "active",
        "security_campaign_number": 1,
        "security_campaign_state": "open",
        "stack_number": 1,
        "step_number": 1,
        "tar_archive_ref": "main",
        "team_member_role": "maintainer",
        "team_member_user": "membership-alice",
        "team_membership_check": True,
        "team_numeric_id": 3201,
        "team_repository_check": True,
        "team_repository_permission": True,
        "team_slug": "core",
        "traffic_granularity": "day",
        "tree_sha": "dddddddddddddddddddddddddddddddddddddddd",
        "user": "octocat",
        "user_account_id": 2601,
        "user_context_subject_id": "123",
        "user_context_subject_type": "repository",
        "user_directory": True,
        "user_email_population": "all",
        "user_since_id": 2600,
        "users": [{"login": "octocat"}, {"login": "hubot"}],
        "viewer_issues": True,
        "viewer_member_issues": True,
        "viewer_organization_issues": True,
        "workflow_id": 1,
        "zip_archive_ref": "main",
    }
    assert {name: value["example"] for name, value in parameters.items()} == examples
    for name in ("organization", "owner", "repository", "user"):
        assert parameters[name]["type"] == "VARCHAR"
        assert parameters[name]["non_empty"] is True
    for name in (
        "pull_request_number",
        "release_id",
        "release_asset_id",
        "workflow_id",
        "run_id",
        "attempt_number",
        "job_id",
        "artifact_id",
        "check_suite_id",
        "check_run_id",
        "commit_comment_id",
        "ahead_of_job_id",
        "ahead_of_run_id",
    ):
        assert parameters[name]["type"] == "BIGINT"
        assert parameters[name]["minimum"] == 1
    for name in (
        "release_tag",
        "release_selection",
        "git_ref",
        "cache_key",
        "cache_ref",
        "concurrency_group",
        "reaction_issue_comment_node_id",
        "reaction_commit_comment_node_id",
    ):
        assert parameters[name]["type"] == "VARCHAR"
        assert parameters[name]["non_empty"] is True
    assert "non_empty" not in parameters["pull_request_number"]
    assert parameters["users"]["type"] == 'STRUCT("login" VARCHAR)[]'
    assert parameters["project_owners"]["type"] == 'STRUCT("login" VARCHAR)[]'
    assert parameters["repositories"]["type"] == 'STRUCT("repository" VARCHAR)[]'
    for name in parameters:
        assert parameters[name]["nullable"] is True and parameters[name]["default"] is None
    package = json.loads(output["models/generated-pilot/github-generated.package.json"])
    assert package["revision"] == 11
    assert model["name"] == "github" and model["id"] == "queryfarm.github.generated_pilot"
    assert package["package_id"] == "9952d457-873c-5e13-965e-07fbdc1cfe2b"
    for name, source in model["invocations"]["sources"].items():
        assert source["dataset"]["id"] == f"queryfarm.github.generated_pilot/datasets/{name}"


def test_scope_constraints_are_coalesced_deterministically_and_apply_only_to_relevant_datasets(pilot):
    overlay, contract, provenance = pilot

    def constraints(value):
        return json.loads(
            emit_artifacts(value, overlay, provenance)[
                "models/generated-pilot/github-generated.crossfield.json"
            ]
        )["semantic_query"]["constraints"]

    expected = constraints(contract)
    assert len({(rule["kind"], rule.get("when"), tuple(rule["parameters"])) for rule in expected}) == len(
        expected
    )

    def applies(kind, parameters, dataset, when=None):
        return any(
            rule["kind"] == kind
            and rule["parameters"] == parameters
            and dataset in rule["datasets"]
            and rule.get("when") == when
            for rule in expected
        )

    for dataset in ("pull_requests", "pull_request_reviews", "issues", "discussion_comments"):
        assert applies("at_most_one", ["user", "users"], dataset)
    assert applies("requires", ["repository"], "pull_requests", "pull_request_number")
    assert applies("requires", ["repository"], "repository_labels", "issue_number")
    assert applies("requires", ["repository"], "discussion_comments", "discussion_number")
    assert applies("requires", ["organization"], "repositories", "team_slug")
    for dataset in ("team_memberships", "organization_invitations"):
        assert applies("requires", ["organization"], dataset, "team_slug")
        assert not any(
            rule["kind"] == "requires"
            and rule.get("when") == "organization"
            and "team_slug" in rule["parameters"]
            and dataset in rule["datasets"]
            for rule in expected
        )
    assert applies(
        "requires", ["organization"], "organization_invitations", "organization_invitation_population"
    )
    assert applies(
        "at_least_one",
        ["authenticated_user", "organization", "team_member_user", "team_numeric_id"],
        "team_memberships",
    )
    contract["functions"].reverse()
    contract["scopes"]["repositories"]["exclusive_parameters"].reverse()
    assert constraints(contract) == expected


def test_generator_preserves_exact_digest_length_and_pattern_in_native_parameters(pilot):
    overlay, contract, provenance = pilot
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    digest = model["semantic_query"]["parameters"]["artifact_subject_digest"]
    assert digest["min_length"] == digest["max_length"] == 71
    assert digest["pattern"] == "^sha256:[a-f0-9]{64}$"


@pytest.mark.parametrize(
    "name,example,error",
    [
        ("owner", None, "non-NULL scalar matching VARCHAR"),
        ("owner", 123, "non-NULL scalar matching VARCHAR"),
        ("owner", ["Query-farm"], "non-NULL scalar matching VARCHAR"),
        ("owner", {"value": "Query-farm"}, "non-NULL scalar matching VARCHAR"),
        ("owner", " ", "satisfy min_length"),
        ("pull_request_number", "1", "non-NULL scalar matching BIGINT"),
        ("pull_request_number", True, "non-NULL scalar matching BIGINT"),
        ("pull_request_number", 2**63, "non-NULL scalar matching BIGINT"),
        ("pull_request_number", 0, "satisfy minimum"),
    ],
)
def test_parameter_examples_must_satisfy_types_and_declared_bounds(pilot, name, example, error):
    overlay, _, _ = pilot
    function = next(
        route
        for entity in overlay["functions"]
        for route in entity.get("routes", [entity])
        if any(arg["name"] == name for arg in route["arguments"])
    )
    next(arg for arg in function["arguments"] if arg["name"] == name)["example"] = example
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match=error):
        compile_contract(specs, sdl, overlay)


def test_shared_semantic_parameter_examples_must_agree(pilot):
    overlay, contract, provenance = pilot
    next(arg for arg in contract["functions"][0]["arguments"] if arg["name"] == "owner")["example"] = "other"
    with pytest.raises(ValueError, match="Inconsistent shared semantic parameter owner"):
        emit_artifacts(contract, overlay, provenance)


def test_discovery_example_uses_the_qualified_invocation_name(pilot):
    overlay, contract, provenance = pilot
    readme = emit_artifacts(contract, overlay, provenance)["models/generated-pilot/README.md"]
    assert "AND invocation_name='engineering.semantic.github' ORDER BY ordinal;" in readme
    assert "invocation_name='github'" not in readme
    assert "[research.sql](research.sql)" in readme
    assert "weekly periods start on ISO Monday" in readme


def test_missing_count_populations_are_zero_but_median_stays_null(pilot):
    overlay, contract, provenance = pilot
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    metrics = model["policy"]["metric_semantics"]
    for entity in contract["functions"]:
        for recipe in entity["semantics"]["metrics"]:
            assert metrics[recipe["name"]]["missing"] == (
                "zero" if recipe["kind"] in {"count", "count_distinct"} else "null"
            )
    assert metrics["approved_review_count"]["population"].endswith("state = 'APPROVED'")
    assert metrics["median_merge_hours"]["missing"] == "null"


@pytest.mark.parametrize(
    "field", ["repository_node_id", "pull_request_created_day", "pull_request_merged_day"]
)
def test_distinct_count_recipes_preserve_scalar_grain_and_zero_empty_populations(pilot, field):
    overlay, contract, provenance = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_requests")
    entity["semantics"]["metrics"].append(
        {
            "name": "unique_values",
            "kind": "count_distinct",
            "field": field,
            "where": {"field": "merged_at", "op": "is_not_null"},
            "comment": (
                "Distinct non-NULL values in the merged PR cohort; overlapping groups cannot be summed."
            ),
        }
    )
    model = json.loads(
        emit_artifacts(contract, overlay, provenance)[
            "models/generated-pilot/github-generated.crossfield.json"
        ]
    )
    assert model["metrics"]["unique_values"]["expression"] == (f"COUNT(DISTINCT pull_requests.{field})")
    metric = model["policy"]["metric_semantics"]["unique_values"]
    assert metric["additivity"] == "non_additive"
    assert metric["missing"] == "zero"
    assert metric["population"] == "pull_requests.merged_at IS NOT NULL"
    assert "unit" not in metric


@pytest.mark.parametrize("field", [None, "unknown_field", "user"])
def test_distinct_count_rejects_missing_unknown_or_nested_fields(pilot, field):
    overlay, contract, provenance = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_request_reviews")
    entity["semantics"]["metrics"].append(
        {
            "name": "invalid_distinct",
            "kind": "count_distinct",
            **({"field": field} if field is not None else {}),
            "comment": "An invalid measure must not be emitted.",
        }
    )
    with pytest.raises(ValueError, match="Distinct count requires a declared scalar field"):
        emit_artifacts(contract, overlay, provenance)


def _category_field(contract):
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_requests")
    field = {
        "name": "test_category",
        "kind": "text_category",
        "source": "title",
        "rules": [
            {"id": "exact_doc", "match": "exact", "value": "DOCS: readme", "category": "readme"},
            {"id": "documentation", "match": "prefix", "value": "docs:", "category": "documentation"},
            {"id": "quoted", "match": "contains", "value": "user's", "category": "user's change"},
        ],
        "otherwise": "unclassified",
        "comment": "Title convention only; inspect the original title as evidence. First matching rule wins.",
    }
    entity["semantics"].setdefault("derived_fields", []).append(field)
    entity["semantics"]["detail_fields"].append("test_category")
    entity["semantics"]["dimensions"].append("test_category")
    return entity, field


def test_text_categories_preserve_order_literal_escaping_unmatched_values_and_source_evidence(pilot):
    overlay, contract, provenance = pilot
    entity, _ = _category_field(contract)
    # A nullable source still yields the explicit unmatched category, never a made-up classification.
    next(column for column in entity["columns"] if column["name"] == "title")["nullable"] = True
    outputs = emit_artifacts(contract, overlay, provenance)
    model = json.loads(outputs["models/generated-pilot/github-generated.crossfield.json"])
    source = model["invocations"]["sources"]["pull_requests"]
    field = source["dataset"]["fields"]["test_category"]
    assert field == {
        "dimension": True,
        "type": "VARCHAR",
        "expression": "CASE WHEN LOWER(pull_requests.title) = LOWER('DOCS: readme') THEN 'readme' "
        "WHEN STARTSWITH(LOWER(pull_requests.title), LOWER('docs:')) THEN 'documentation' "
        "WHEN CONTAINS(LOWER(pull_requests.title), LOWER('user''s')) THEN 'user''s change' "
        "ELSE 'unclassified' END",
    }
    assert "pull_requests.title" in model["policy"]["detail_fields"]
    assert "pull_requests.test_category" in model["policy"]["filter_dimensions"]
    assert "test_category" not in {column["name"] for column in source["result_columns"]}
    assert "| `test_category` | `VARCHAR` | no |" in outputs["models/generated-pilot/README.md"]


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("unknown_source", "VARCHAR source"),
        ("numeric_source", "VARCHAR source"),
        ("hidden_evidence", "exposed as a detail field"),
        ("raw_sql", "reviewed source"),
        ("no_fallback", "explicit otherwise"),
        ("blank_fallback", "otherwise category"),
        ("empty_rules", "between 1 and 32"),
        ("too_many_rules", "between 1 and 32"),
        ("duplicate_rule_id", "IDs must be unique"),
        ("regex", "only support exact, prefix and contains"),
        ("empty_match", "match values must be nonempty"),
        ("empty_category", "labels must be nonempty"),
    ],
)
def test_text_category_recipes_reject_unbounded_or_unreviewed_classification(pilot, mutation, error):
    overlay, contract, provenance = pilot
    entity, field = _category_field(contract)
    if mutation == "unknown_source":
        field["source"] = "invented"
    elif mutation == "numeric_source":
        field["source"] = "pull_request_number"
    elif mutation == "hidden_evidence":
        entity["semantics"]["detail_fields"].remove("title")
    elif mutation == "raw_sql":
        field["expression"] = "CURRENT_USER"
    elif mutation == "no_fallback":
        field.pop("otherwise")
    elif mutation == "blank_fallback":
        field["otherwise"] = " "
    elif mutation == "empty_rules":
        field["rules"] = []
    elif mutation == "too_many_rules":
        field["rules"] *= 11
    elif mutation == "duplicate_rule_id":
        field["rules"][1]["id"] = field["rules"][0]["id"]
    elif mutation == "regex":
        field["rules"][0]["match"] = "regex"
    elif mutation == "empty_match":
        field["rules"][0]["value"] = ""
    else:
        field["rules"][0]["category"] = ""
    with pytest.raises(ValueError, match=error):
        emit_artifacts(contract, overlay, provenance)


@pytest.mark.parametrize("granularity", ["day", "week", "month"])
def test_utc_period_recipes_emit_calendar_start_dates_and_preserve_nullability(pilot, granularity):
    overlay, contract, provenance = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_requests")
    field = next(
        field for field in entity["semantics"]["derived_fields"] if field["name"] == "pull_request_merged_day"
    )
    field["granularity"] = granularity
    outputs = emit_artifacts(contract, overlay, provenance)
    model = json.loads(outputs["models/generated-pilot/github-generated.crossfield.json"])
    emitted = model["invocations"]["sources"]["pull_requests"]["dataset"]["fields"]["pull_request_merged_day"]
    day = "CAST(pull_requests.merged_at AS DATE)"
    assert emitted["expression"] == (
        day if granularity == "day" else f"CAST(DATE_TRUNC('{granularity}', {day}) AS DATE)"
    )
    assert emitted["timezone"] == "UTC" and emitted["calendar"] == "gregorian"
    assert emitted["type"] == "DATE" and emitted["granularity"] == granularity
    assert "| `pull_request_merged_day` | `DATE` | yes |" in outputs["models/generated-pilot/README.md"]
    field["granularity"] = "year"
    with pytest.raises(ValueError, match="only support day, week and month"):
        emit_artifacts(contract, overlay, provenance)


@pytest.mark.parametrize(
    "entity_name,source_name,day_name",
    [
        ("pull_requests", "created_at", "pull_request_created_day"),
        ("pull_requests", "merged_at", "pull_request_merged_day"),
        ("pull_request_reviews", "submitted_at", "review_submitted_day"),
    ],
)
def test_date_dimensions_are_model_owned_utc_casts(pilot, entity_name, source_name, day_name):
    overlay, contract, provenance = pilot
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    source = model["invocations"]["sources"][entity_name]
    assert source["dataset"]["fields"][day_name] == {
        "dimension": True,
        "expression": f"CAST({entity_name}.{source_name} AS DATE)",
        "type": "DATE",
        "is_time": True,
        "timezone": "UTC",
        "calendar": "gregorian",
        "granularity": "day",
    }
    full_name = entity_name + "." + day_name
    for approval in ("dimensions", "filter_dimensions", "detail_fields"):
        assert full_name in model["policy"][approval]
    assert model["policy"]["field_semantics"][full_name]["sql_name"] == day_name
    # Deriving a DATE must not pretend the worker returned one or change its schema.
    assert day_name not in {column["name"] for column in source["result_columns"]}
    worker = json.loads(output["vgi_github/generated_entities.json"])
    entity = next(entity for entity in worker["functions"] if entity["name"] == entity_name)
    assert day_name not in {column["name"] for column in entity["columns"]}
    assert next(column for column in entity["columns"] if column["name"] == source_name)["type"] == (
        "TIMESTAMP WITH TIME ZONE"
    )


@pytest.mark.parametrize("nullable,required", [(False, True), (True, True), (False, False)])
def test_date_nullability_preserves_nullable_and_optional_source_contracts(pilot, nullable, required):
    overlay, contract, provenance = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_requests")
    source = next(column for column in entity["columns"] if column["name"] == "created_at")
    source["nullable"], source["required"] = nullable, required
    output = emit_artifacts(contract, overlay, provenance)
    expected = "yes" if nullable or not required else "no"
    assert (
        f"| `pull_request_created_day` | `DATE` | {expected} |" in output["models/generated-pilot/README.md"]
    )
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    field = model["invocations"]["sources"]["pull_requests"]["dataset"]["fields"]["pull_request_created_day"]
    # CAST preserves NULL; there is no fabricated epoch, current date or string fallback.
    assert field["expression"] == "CAST(pull_requests.created_at AS DATE)"


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("missing_timezone", "explicit UTC timezone"),
        ("different_timezone", "explicit UTC timezone"),
        ("sql_expression", "reviewed date recipe"),
        ("unknown_source", "timestamp-with-time-zone"),
        ("text_source", "timestamp-with-time-zone"),
        ("naive_timestamp", "timestamp-with-time-zone"),
        ("duplicate", "distinct and documented"),
        ("undocumented", "distinct and documented"),
    ],
)
def test_date_recipes_reject_unapproved_type_timezone_or_expression(pilot, mutation, error):
    overlay, contract, _ = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_requests")
    field = next(
        field
        for field in entity["semantics"]["derived_fields"]
        if field["name"] == "pull_request_created_day"
    )
    if mutation == "missing_timezone":
        field.pop("timezone")
    elif mutation == "different_timezone":
        field["timezone"] = "America/New_York"
    elif mutation == "sql_expression":
        field["expression"] = "CURRENT_DATE"
    elif mutation == "unknown_source":
        field["source"] = "invented"
    elif mutation == "text_source":
        field["source"] = "author_login"
    elif mutation == "naive_timestamp":
        next(column for column in entity["columns"] if column["name"] == "created_at")["type"] = "TIMESTAMP"
    elif mutation == "duplicate":
        field["name"] = "created_at"
    else:
        field["comment"] = " "
    with pytest.raises(ValueError, match=error):
        validate_semantics(contract, overlay)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("missing_mapping", "exactly its declared"),
        ("unknown_stage", "earlier stage"),
        ("unknown_parameter", "undeclared parameter"),
        ("incompatible_scope", "same named entity columns"),
        ("nullable_mapping", "NOT NULL"),
        ("bad_default", "NULL default"),
    ],
)
def test_connected_scope_contracts_reject_incompatible_changes(pilot, mutation, error):
    overlay, _, _ = pilot
    if mutation == "missing_mapping":
        overlay["scopes"]["repositories"]["select"]["if_present"]["arguments"] = {}
    elif mutation == "unknown_stage":
        overlay["functions"][2]["routes"][0]["traversal"]["stages"][-1]["arguments"]["pull_request_number"][
            "stage"
        ] = "future"
    elif mutation == "unknown_parameter":
        overlay["scopes"]["repositories"]["select"]["parameter"] = "unknown"
    elif mutation == "incompatible_scope":
        overlay["entities"][2]["columns"].pop()
    elif mutation == "nullable_mapping":
        overlay["scopes"]["repositories"].pop("exclusive_parameters")
    elif mutation == "bad_default":
        overlay["functions"][0]["routes"][1]["arguments"][0]["default"] = "someone"
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match=error):
        compile_contract(specs, sdl, overlay)


def test_review_role_and_repository_identity_are_explicit(pilot):
    _, contract, _ = pilot
    shared = contract["shared_dimensions"]
    assert "pull_requests.author_id" in shared["github.pr_author.account_id.v1"]
    assert "pull_request_reviews.reviewer_id" in shared["github.reviewer.account_id.v1"]
    assert set(shared["github.pr_author.account_id.v1"]).isdisjoint(shared["github.reviewer.account_id.v1"])
    reviews = next(entity for entity in contract["functions"] if entity["name"] == "pull_request_reviews")
    columns = {column["name"]: column for column in reviews["routes"][0]["columns"]}
    assert columns["repository"]["source_stage"] == "repositories"
    assert columns["author_login"]["source_stage"] == "pull_requests"
    assert columns["reviewer_login"]["source_stage"] == "reviews"


def test_disconnected_traversal_cannot_multiply_child_populations(pilot):
    overlay, _, _ = pilot
    overlay["functions"][2]["routes"][0]["traversal"]["stages"][-1]["arguments"]["pull_request_number"] = {
        "literal": 1
    }
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match="immediate parent"):
        compile_contract(specs, sdl, overlay)


def test_cyclic_relationships_reject_before_model_emission(pilot):
    overlay, contract, _ = pilot
    contract["relationships"].append(
        {
            "name": "self_loop",
            "from": "repositories",
            "to": "repositories",
            "from_columns": ["repository_id"],
            "to_columns": ["repository_id"],
        }
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_semantics(contract, overlay)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("unknown_approval", "approvals"),
        ("unknown_column", "Unknown column"),
        ("nested_dimension", "Nested values"),
        ("arbitrary_expression", "reviewed count"),
        ("incomplete_relationship", "complete entity grain"),
    ],
)
def test_invalid_policy_cannot_silently_broaden_approvals(pilot, mutation, error):
    overlay, contract, _ = pilot
    entity = contract["functions"][2]
    if mutation == "unknown_approval":
        entity["semantics"]["all_fields"] = True
    elif mutation == "unknown_column":
        entity["semantics"]["detail_fields"].append("not_a_source_field")
    elif mutation == "nested_dimension":
        entity["semantics"]["dimensions"].append("user")
    elif mutation == "arbitrary_expression":
        entity["semantics"]["metrics"][0]["expression"] = "SUM(id)"
    elif mutation == "incomplete_relationship":
        contract["relationships"][1]["to_columns"] = ["repository_id"]
    with pytest.raises(ValueError, match=error):
        validate_semantics(contract, overlay)


def test_unknown_selected_source_field_rejects_generation(pilot):
    overlay, _, _ = pilot
    overlay["entities"][0]["columns"].append({"name": "invented", "path": ["invented"]})
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match="unknown selected property"):
        compile_contract(specs, sdl, overlay)


def test_source_snapshot_tampering_fails_before_generation(pilot, tmp_path):
    overlay, _, _ = pilot
    shutil.copytree(ROOT / "generation", tmp_path / "generation")
    lock = json.loads((tmp_path / "generation/sources.lock.json").read_text())
    selected = tmp_path / lock["snapshots"][0]["path"]
    selected.write_bytes(selected.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="schema hash mismatch"):
        generator.locked_inputs(tmp_path, overlay)


def test_check_detects_stale_artifacts_without_rewriting_them(tmp_path):
    expected = {"models/pilot.json": '{"version":1}\n'}
    generator.write_outputs(tmp_path, expected, check=False)
    target = tmp_path / "models/pilot.json"
    target.write_text("stale artifact\n")
    with pytest.raises(ValueError, match="artifacts are stale"):
        generator.write_outputs(tmp_path, expected, check=True)
    assert target.read_text() == "stale artifact\n"


def test_nested_graphql_selection_keeps_only_reviewed_shape():
    sdl = """
    type Query { repository(owner:String!,name:String!): Repository }
    type Repository { labels(first:Int,after:String): LabelConnection }
    type LabelConnection { nodes:[Label],pageInfo:PageInfo! }
    type PageInfo { hasNextPage:Boolean!,endCursor:String }
    type Label { id:ID!,creator:User }
    type User { id:ID!,login:String!,organization:Organization,unused:String }
    type Organization { name:String!,backToUser:User }
    """
    entity = {
        "name": "nested_labels",
        "arguments": [{"name": "repository", "type": "VARCHAR"}],
        "grain": ["id"],
        "columns": [
            {"name": "id", "path": ["id"]},
            {
                "name": "creator",
                "path": ["creator"],
                "selection": {"login": True, "organization": {"name": True}},
            },
        ],
        "transport": {
            "kind": "graphql",
            "field_path": ["repository", "labels"],
            "field_arguments": {
                "repository": {
                    "owner": {"argument": "repository", "transform": "repository_owner"},
                    "name": {"argument": "repository", "transform": "repository_name"},
                },
                "labels": {"first": {"literal": 100}, "after": {"cursor": True}},
            },
            "result_path": ["nodes"],
            "pagination": {"kind": "cursor", "page_info_path": ["pageInfo"]},
        },
    }
    selected = generator.select_graphql(sdl, [entity])
    assert "unused" not in selected and "backToUser" not in selected
    compiled = compile_graphql_entity(selected, entity)
    creator = compiled["columns"][1]
    assert creator["type"] == 'STRUCT("login" VARCHAR, "organization" STRUCT("name" VARCHAR))'
    assert creator["nullable"] is True
    assert validate(build_schema(sdl), parse(compiled["transport"]["document"])) == []


def test_optional_relationship_is_policy_metadata_not_an_ossie_property(pilot):
    overlay, contract, provenance = pilot
    relation = next(
        relation
        for relation in contract["relationships"]
        if relation["name"] == "repositories_to_organizations"
    )
    assert relation["optional"] is True
    model = json.loads(
        emit_artifacts(contract, overlay, provenance)[
            "models/generated-pilot/github-generated.crossfield.json"
        ]
    )
    emitted = next(value for value in model["relationships"] if value["name"] == relation["name"])
    assert "optional" not in emitted
    assert model["policy"]["relationship_semantics"][relation["name"]]["optional"] is True
    relation["optional"] = "true"
    with pytest.raises(ValueError, match="optional must be a boolean"):
        validate_semantics(contract, overlay)


def test_navigation_bindings_do_not_approve_ambiguous_analytical_paths(pilot):
    overlay, contract, provenance = pilot
    model = json.loads(
        emit_artifacts(contract, overlay, provenance)[
            "models/generated-pilot/github-generated.crossfield.json"
        ]
    )
    navigation = {
        "workflow_runs_to_repositories",
        "workflow_run_attempts_to_repositories",
        "workflow_jobs_to_repositories",
        "workflow_artifacts_to_runs",
        "workflow_jobs_to_attempts",
        "release_assets_to_releases",
        "check_runs_to_suites",
        "check_annotations_to_repositories",
        "reactions_to_issues",
        "reactions_to_pull_requests",
        "reactions_to_issue_comments",
        "reactions_to_commit_comments",
        "reactions_to_review_comments",
        "reactions_to_releases",
        "reactions_to_reactors",
        "workflow_run_concurrency_groups_to_runs",
        "workflow_pending_deployments_to_runs",
        "workflow_deployment_reviews_to_runs",
        "run_concurrency_groups_to_groups",
        "pending_deployments_to_environments",
    }
    assert navigation.isdisjoint(model["policy"]["relationships"])
    assert navigation <= {relation["name"] for relation in model["relationships"]}
    retrievals = json.loads(model["policy"]["tags"]["github.relationship_retrievals"])
    assert navigation <= retrievals.keys()
    assert all("analytical" not in relation for relation in model["relationships"])
    assert "workflow_artifacts.repository" in contract["shared_dimensions"]["github.repository.full_name.v1"]
    relation = next(item for item in contract["relationships"] if item["name"] == "workflow_jobs_to_attempts")
    relation["analytical"] = "false"
    with pytest.raises(ValueError, match="analytical must be a boolean"):
        validate_semantics(contract, overlay)


def test_membership_does_not_grant_an_activity_attribution_join(pilot):
    _, contract, _ = pilot
    relationships = contract["relationships"]
    assert not any(
        relation["from"] in {"pull_requests", "pull_request_reviews"}
        and relation["to"] in {"team_memberships", "organization_memberships", "teams"}
        for relation in relationships
    )
    assert not any(
        relation["from"] == "organization_memberships" and relation["to"] == "users"
        for relation in relationships
    )


def test_graphql_common_interface_fields_preserve_types_and_validate_against_source():
    sdl = """
    type Query { user(login:String!): User }
    type User { pullRequests(first:Int,after:String): PullRequestConnection! }
    type PullRequestConnection { nodes:[PullRequest],pageInfo:PageInfo! }
    type PageInfo { hasNextPage:Boolean!,endCursor:String }
    type PullRequest { id:ID!,author:Actor }
    interface Actor { login:String!,unused:String }
    type Bot implements Actor { login:String!,unused:String }
    """
    entity = {
        "name": "user_activity",
        "arguments": [{"name": "user", "type": "VARCHAR"}],
        "grain": ["id"],
        "columns": [
            {"name": "id", "path": ["id"]},
            {"name": "author_login", "path": ["author", "login"]},
        ],
        "transport": {
            "kind": "graphql",
            "field_path": ["user", "pullRequests"],
            "field_arguments": {
                "user": {"login": {"argument": "user"}},
                "pullRequests": {"first": {"literal": 100}, "after": {"cursor": True}},
            },
            "result_path": ["nodes"],
            "pagination": {"kind": "cursor", "page_info_path": ["pageInfo"]},
        },
    }
    selected = generator.select_graphql(sdl, [entity])
    assert "unused" not in selected
    compiled = compile_graphql_entity(selected, entity)
    assert validate(build_schema(sdl), parse(compiled["transport"]["document"])) == []
    author = compiled["columns"][1]
    assert author["type"] == "VARCHAR" and author["nullable"] is True


def _native_proof(contract):
    proof = json.loads((ROOT / "tests/crossfield/generator_semantics.overlay.json").read_text())
    entity = next(item for item in contract["functions"] if item["name"] == proof["entity"])
    entity["semantics"]["crossfield"] = deepcopy(proof["crossfield"])
    for key in ("dimensions", "detail_fields"):
        entity["semantics"][key] += proof[key]
    return entity


def test_native_crossfield_definitions_preserve_expressions_and_policy_without_recipe_branches(pilot):
    overlay, contract, provenance = pilot
    entity = _native_proof(contract)
    native = entity["semantics"]["crossfield"]
    before = deepcopy(native)
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    assert model["metrics"]["proof_p90_merge_hours"] == native["metrics"]["proof_p90_merge_hours"]
    assert (
        model["invocations"]["sources"][entity["name"]]["dataset"]["fields"]["proof_title_lower"]
        == (native["fields"]["proof_title_lower"])
    )
    assert model["policy"]["metric_semantics"]["proof_p90_merge_hours"] == {
        "dataset": entity["name"],
        **native["metric_semantics"]["proof_p90_merge_hours"],
    }
    assert (
        model["policy"]["field_semantics"]["pull_requests.proof_title_lower"]
        == (native["field_semantics"]["proof_title_lower"])
    )
    assert "proof_p90_merge_hours" in output["models/generated-pilot/README.md"]
    coverage = json.loads(output["models/generated-pilot/coverage.json"])
    assert "proof_p90_merge_hours" in next(
        item["metrics"] for item in coverage["entities"] if item["name"] == entity["name"]
    )
    assert native == before
    # Native-only calculations must not alter the worker's actual API result schema.
    generated = json.loads(output["models/generated-pilot/source_schemas.json"])
    assert all(
        "proof_title_lower" not in {column["name"] for column in item["columns"]}
        for item in generated["entities"]
    )


@pytest.mark.parametrize(
    "expression",
    ["SUM(", "my_future_scalar(pull_requests.title)", "SUM(pull_requests.no_such_field)"],
)
def test_generator_leaves_native_expression_acceptance_to_crossfield(pilot, expression):
    overlay, contract, provenance = pilot
    entity = _native_proof(contract)
    entity["semantics"]["crossfield"]["metrics"]["proof_p90_merge_hours"]["expression"] = expression
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    assert model["metrics"]["proof_p90_merge_hours"]["expression"] == expression
    # Native generator_semantics.test rejects malformed/unknown definitions. Generation
    # itself neither approves SQL nor executes API requests or arbitrary code.


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("source_field_collision", "collides with a generated"),
        ("recipe_field_collision", "collides with a generated"),
        ("metric_collision", "Duplicate metric"),
        ("foreign_dataset", "declaring entity"),
        ("foreign_field", "declaring entity"),
        ("missing_policy", "metric_semantics entry"),
        ("dimension_conflict", "dimension approval"),
        ("sql_name_conflict", "generated sql_name"),
    ],
)
def test_native_definitions_cannot_replace_generated_ownership(pilot, mutation, error):
    overlay, contract, provenance = pilot
    entity = _native_proof(contract)
    native = entity["semantics"]["crossfield"]
    if mutation in {"source_field_collision", "recipe_field_collision"}:
        name = "title" if mutation == "source_field_collision" else "merge_hours"
        native["fields"][name] = native["fields"].pop("proof_title_lower")
    elif mutation == "metric_collision":
        native["metrics"]["pull_request_count"] = native["metrics"].pop("proof_p90_merge_hours")
        native["metric_semantics"]["pull_request_count"] = native["metric_semantics"].pop(
            "proof_p90_merge_hours"
        )
    elif mutation == "foreign_dataset":
        native["metric_semantics"]["proof_p90_merge_hours"]["dataset"] = "repositories"
    elif mutation == "foreign_field":
        native["field_semantics"]["foreign_field"] = {"comment": "Outside owner."}
    elif mutation == "missing_policy":
        native["metric_semantics"] = {}
    elif mutation == "dimension_conflict":
        native["fields"]["proof_title_lower"]["dimension"] = False
    elif mutation == "sql_name_conflict":
        native["field_semantics"]["repository"] = {"sql_name": "conflicting_name"}
    with pytest.raises(ValueError, match=error):
        emit_artifacts(contract, overlay, provenance)


def test_native_timestamp_metadata_is_not_replaced_by_api_defaults(pilot):
    overlay, contract, provenance = pilot
    entity = _native_proof(contract)
    definition = entity["semantics"]["crossfield"]["fields"]["proof_title_lower"]
    definition.update(
        expression="pull_requests.created_at",
        type="TIMESTAMP WITH TIME ZONE",
        timezone="America/New_York",
    )
    model = json.loads(
        emit_artifacts(contract, overlay, provenance)[
            "models/generated-pilot/github-generated.crossfield.json"
        ]
    )
    assert (
        model["invocations"]["sources"][entity["name"]]["dataset"]["fields"]["proof_title_lower"]
        == definition
    )
