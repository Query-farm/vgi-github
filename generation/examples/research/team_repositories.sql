PREPARE github_team_repositories AS
SELECT repository_name, repository_count
FROM engineering.semantic.github(organization => $1, team_slug => $2)
GROUP BY repository_name
ORDER BY repository_name;
