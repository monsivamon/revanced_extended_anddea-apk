import requests
from dataclasses import dataclass


# GitHubリリースの各アセット（ダウンロードファイル）の情報を保持するデータクラス
@dataclass
class Asset:
    browser_download_url: str
    name: str


# GitHubリリースの全体情報（タグ名、URL、アセット一覧、本文）を保持するデータクラス
@dataclass
class GithubRelease:
    tag_name: str
    html_url: str
    assets: list[Asset]
    body: str | None = ""


# 指定したGitHubリポジトリ（例: "monsivamon/twitter-apk"）の最新リリース情報を取得する。
# まだ一度もリリースされていない場合（404）などは None を返す。
def get_last_build_version(repo_url: str) -> GithubRelease | None:
    url = f"https://api.github.com/repos/{repo_url}/releases/latest"
    
    # HTTPヘッダーなしでシンプルにリクエスト
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
    
    # 200以外（404など）の場合は何も返さない（None）
    return None