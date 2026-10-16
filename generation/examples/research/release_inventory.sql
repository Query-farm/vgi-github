PREPARE github_release_inventory AS
SELECT release_count, published_release_count, draft_release_count, prerelease_count,
       release_asset_count, release_asset_size_bytes, release_asset_download_count
FROM engineering.semantic.github(repository => $1);
