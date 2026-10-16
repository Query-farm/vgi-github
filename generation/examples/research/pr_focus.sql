PREPARE github_pr_focus AS
WITH earlier AS (
    SELECT pull_request_repository_name AS repository, pull_request_count AS prs
    FROM engineering.semantic.github(user => $1)
    WHERE pull_request_created_day >= $2 AND pull_request_created_day < $3
    GROUP BY pull_request_repository_name
), later AS (
    SELECT pull_request_repository_name AS repository, pull_request_count AS prs
    FROM engineering.semantic.github(user => $1)
    WHERE pull_request_created_day >= $4 AND pull_request_created_day < $5
    GROUP BY pull_request_repository_name
), earlier_shares AS (
    SELECT *, 100.0 * prs / SUM(prs) OVER () AS share FROM earlier
), later_shares AS (
    SELECT *, 100.0 * prs / SUM(prs) OVER () AS share FROM later
)
SELECT COALESCE(earlier_shares.repository,later_shares.repository) AS repository,
       COALESCE(earlier_shares.prs,0) AS earlier_prs,
       COALESCE(later_shares.prs,0) AS later_prs,
       CASE WHEN NOT EXISTS(SELECT 1 FROM earlier) THEN NULL
            ELSE COALESCE(earlier_shares.share,0) END AS earlier_share_percent,
       CASE WHEN NOT EXISTS(SELECT 1 FROM later) THEN NULL
            ELSE COALESCE(later_shares.share,0) END AS later_share_percent,
       CASE WHEN NOT EXISTS(SELECT 1 FROM earlier) OR NOT EXISTS(SELECT 1 FROM later) THEN NULL
            ELSE COALESCE(later_shares.share,0)-COALESCE(earlier_shares.share,0)
            END AS share_change_percentage_points,
       CASE WHEN earlier_shares.repository IS NULL THEN 'new_in_comparison'
            WHEN later_shares.repository IS NULL THEN 'absent_in_later_period'
            ELSE 'present_in_both' END AS presence
FROM earlier_shares FULL OUTER JOIN later_shares USING(repository)
WHERE CASE WHEN $2 IS NULL OR $3 IS NULL OR $4 IS NULL OR $5 IS NULL
                OR CAST($3 AS DATE)<=CAST($2 AS DATE) OR CAST($5 AS DATE)<=CAST($4 AS DATE)
                OR CAST($3 AS DATE)>CAST($4 AS DATE)
           THEN error('Use ordered, non-overlapping, nonempty [start,end) UTC periods')
           ELSE true END
ORDER BY repository;
