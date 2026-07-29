import requests
import re
from utils import download


# Helper function to search for and download an asset matching a regular expression from a GitHub repository releases.
# Identifies and retrieves a release matching criteria (latest version, specified version, prereleases, etc.).
def download_release_asset(repo: str, regex: str, out_dir: str, filename=None, include_prereleases: bool = False, version=None):
    url = f"https://api.github.com/repos/{repo}/releases"

    # Simple request without custom HTTP headers
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch GitHub releases for {repo}")

    # Filter whether to include prereleases
    releases = [r for r in response.json() if include_prereleases or not r.get("prerelease")]

    if not releases:
        raise Exception(f"No releases found for {repo}")

    # Filter further if a specific version is requested
    if version is not None:
        releases = [r for r in releases if r.get("tag_name") == version]

    if len(releases) == 0:
        raise Exception(f"No release found for version {version}")

    latest_release = releases[0]
    assets = latest_release.get("assets", [])

    link = None
    for i in assets:
        if re.search(regex, i["name"]):
            link = i["browser_download_url"]
            if filename is None:
                filename = i["name"]
            break

    # Safety check if matching file was not found
    if link is None:
        raise Exception(f"No asset matching regex '{regex}' found in release.")

    # Save file by calling download function from utils.py
    download(link, f"{out_dir.lstrip('/')}/{filename}")

    return latest_release


# Downloads APKEditor.
# Used for merging multiple APKs (.apkm -> .apk).
def download_apkeditor():
    print("Downloading APKEditor...")
    download_release_asset("REAndroid/APKEditor", "APKEditor", "bins", "apkeditor.jar")


# Downloads Morphe CLI.
# Used for patching APKs (executing .mpp files).
def download_morphe_cli():
    print("Downloading Morphe CLI...")
    download_release_asset(
        "MorpheApp/morphe-desktop",
        r".*morphe-desktop.*-all\.jar$",
        "bins",
        "morphe-cli.jar",
        include_prereleases=True
    )
