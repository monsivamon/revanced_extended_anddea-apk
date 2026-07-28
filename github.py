import requests
from dataclasses import dataclass


# Data class representing each asset (download file) in a GitHub release
@dataclass
class Asset:
    browser_download_url: str
    name: str


# Data class representing overall GitHub release details (tag name, URL, asset list, body)
@dataclass
class GithubRelease:
    tag_name: str
    html_url: str
    assets: list[Asset]
    body: str | None = ""


# Fetches the latest release information for the specified GitHub repository (e.g., "monsivamon/twitter-apk").
# Returns None if no release exists yet (e.g. 404).
def get_last_build_version(repo_url: str) -> GithubRelease | None:
    url = f"https://api.github.com/repos/{repo_url}/releases/latest"
    
    # Simple request without custom HTTP headers
    response = requests.get(url)

    if response.status_code == 200:
        release = response.json()

        assets = [
            Asset(
                browser_download_url=asset["browser_download_url"], 
                name=asset["name"]
            )
            for asset in release.get("assets", [])
        ]

        return GithubRelease(
            tag_name=release.get("tag_name", ""),
            html_url=release.get("html_url", ""),
            assets=assets,
            body=release.get("body", "")
        )
    
    # Return None for non-200 responses (e.g., 404)
    return None