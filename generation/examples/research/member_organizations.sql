PREPARE github_member_organizations AS
SELECT organization_login, organization_count
FROM engineering.semantic.github(user => $1)
GROUP BY organization_login
ORDER BY organization_login;
