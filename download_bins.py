import requests
import re
from utils import download


# GitHubのリポジトリから、正規表現に一致するアセット（ファイル）を検索してダウンロードする共通関数。
# 最新版（または指定バージョン、プレリリース等）の条件に合うリリースを特定して取得する。
def download_release_asset(repo: str, regex: str, out_dir: str, filename=None, include_prereleases: bool = False, version=None):
    url = f"https://api.github.com/repos/{repo}/releases"

    # ヘッダーなしでシンプルにリクエスト
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch GitHub releases for {repo}")

    # プレリリースを含めるかどうかのフィルタリング
    releases = [r for r in response.json() if include_prereleases or not r.get("prerelease")]

    if not releases:
        raise Exception(f"No releases found for {repo}")

    # バージョン指定がある場合はさらに絞り込む
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

    # 該当するファイルが見つからなかった場合の安全対策
    if link is None:
        raise Exception(f"No asset matching regex '{regex}' found in release.")

    # utils.pyのdownload関数を呼び出して保存
    download(link, f"{out_dir.lstrip('/')}/{filename}")

    return latest_release


# APKEditorをダウンロードする。
# 複数APKのマージ（.apkm → .apk）に使用する。
def download_apkeditor():
    print("Downloading APKEditor...")
    download_release_asset("REAndroid/APKEditor", "APKEditor", "bins", "apkeditor.jar")


# Morphe CLIをダウンロードする。
# APKへのパッチ適用（.mppファイルの実行）に使用する。
def download_morphe_cli():
    print("Downloading Morphe CLI...")
    download_release_asset(
        "MorpheApp/morphe-cli",
        r".*morphe-cli.*-all\.jar$",
        "bins",
        "morphe-cli.jar",
        include_prereleases=True
    )