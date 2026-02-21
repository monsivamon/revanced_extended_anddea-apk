import os
import requests
import subprocess
import sys

# Cloudscraperのインスタンスを保持する変数（必要な時だけ読み込む設計）
_scraper = None

# CloudflareなどのBotアクセス制限を突破してダウンロードするためのスクレイパーを取得する
def get_scraper():
    global _scraper
    if _scraper is None:
        import cloudscraper
        _scraper = cloudscraper.create_scraper()
        _scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        })
    return _scraper


# エラーメッセージを標準エラー出力に吐き出して、プログラムを強制終了させる
def panic(message: str):
    print(message, file=sys.stderr)
    exit(1)


# 指定したURLからファイルをダウンロードしてローカルに保存する
def download(link: str, out: str, headers=None, use_scraper=False):
    if os.path.exists(out):
        print(f"{out} already exists skipping download")
        return

    if use_scraper:
        r = get_scraper().get(link, stream=True, headers=headers)
    else:
        r = requests.get(link, stream=True, headers=headers)
    
    r.raise_for_status()
    with open(out, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)


# コマンドライン実行のラッパー（エラーが発生した場合はログを出して強制終了）
def run_command(command: list[str]):
    cmd = subprocess.run(command, capture_output=True, shell=True)

    try:
        cmd.check_returncode()
    except subprocess.CalledProcessError:
        print(cmd.stdout)
        print(cmd.stderr)
        exit(1)


# APKEditorを使用して、分割APK（.apkm）を1つのAPK（.apk）に結合する
def merge_apk(path: str):
    subprocess.run(
        ["java", "-jar", "./bins/apkeditor.jar", "m", "-i", path]
    ).check_returncode()


# Morphe CLIを使用して、指定したAPKにパッチ（.mpp）を適用する
def patch_apk(
    cli: str,
    patches: str,
    apk: str,
    includes: list[str] | None = None,
    excludes: list[str] | None = None,
    out: str | None = None,
):
    includes = includes or []
    excludes = excludes or []

    command = [
        "java",
        "-jar",
        cli,
        "patch",
    ]

    command += ["-p", patches]

    for i in includes:
        command += ["-e", i]

    for e in excludes:
        command += ["-d", e]

    # ダミーの署名（キーストア）情報を付与
    command += [
        "--keystore", "ks.keystore",
        "--keystore-entry-password", "123456789",
        "--keystore-password", "123456789",
        "--keystore-entry-alias", "jhc",
    ]

    if out is not None:
        command += ["--out", out]

    command.append(apk)

    print(f"Executing: {' '.join(command)}")

    result = subprocess.run(command, capture_output=True, text=True)
    
    # 成功時もMorpheのパッチ進行ログを表示
    if result.stdout:
        print(result.stdout)
    
    # エラー時は詳細なログを出力して停止
    if result.returncode != 0:
        print("--- CLI Error Output ---", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr) 
        print("------------------------", file=sys.stderr)
        result.check_returncode() 


# GitHubに完成したAPKをリリース（アップロード）する
# 既に同じバージョンのリリースが存在する場合は、一旦削除してから再作成する
def publish_release(tag: str, files: list[str], message: str, title = ""):
    key = os.environ.get("GITHUB_TOKEN")
    if key is None:
        raise Exception("GITHUB_TOKEN is not set")

    if len(files) == 0:
        raise Exception("Files should have at least one item")

    def release_exists(t: str) -> bool:
        result = subprocess.run(
            ["gh", "release", "view", t],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return result.returncode == 0

    if release_exists(tag):
        print(f"Release '{tag}' already exists — deleting old release...")

        # リリース本体の削除
        subprocess.run(
            ["gh", "release", "delete", tag, "-y"],
            env=os.environ.copy()
        ).check_returncode()

        # タグの削除 (GitHub API 経由)
        print(f"Deleting tag '{tag}' via GitHub API...")
        api_cmd = [
            "gh", "api",
            "--method", "DELETE",
            f"/repos/{os.environ['GITHUB_REPOSITORY']}/git/refs/tags/{tag}"
        ]

        subprocess.run(api_cmd, env=os.environ.copy()).check_returncode()

        print("Old release & tag removed. Recreating fresh release...")

    # 新規リリースの作成とファイルのアップロード
    command = ["gh", "release", "create", "--latest", tag, "--notes", message, "--title", title]
    command.extend(files)

    subprocess.run(command, env=os.environ.copy()).check_returncode()