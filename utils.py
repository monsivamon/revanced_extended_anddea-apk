import os
import shutil
import requests
import subprocess
import sys
import glob

_scraper = None

# Cloudflare等のBot判定を回避するためのブラウザ偽装スクレイパーを取得する
def get_scraper():
    global _scraper
    if _scraper is None:
        import cloudscraper
        _scraper = cloudscraper.create_scraper()
        _scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        })
    return _scraper

# 致命的なエラーメッセージを表示し、スクリプトを強制終了する
def panic(message: str):
    print(message, file=sys.stderr)
    exit(1)

# 指定されたURLからファイルをダウンロードする（curl_cffiでブラウザを偽装）
def download(link: str, out: str, headers=None, use_scraper=True):
    if os.path.exists(out):
        print(f"{out} already exists skipping download")
        return

    print("  -> [DEBUG] Downloading with curl_cffi...")

    if headers is None:
        headers = {}
    if "Referer" not in headers:
        headers["Referer"] = "https://www.apkmirror.com/"

    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(link, stream=True, headers=headers, impersonate="chrome")
        r.raise_for_status()
    except Exception as e:
        status = getattr(r, 'status_code', 'Unknown') if 'r' in locals() else 'Unknown'
        print(f"\n  -> [FATAL ERROR] Download blocked (Status: {status})")
        print(f"  -> Target: {link}")
        panic(f"Error details: {e}")

    with open(out, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

# 外部シェルコマンドを実行し、失敗時はログを出力して異常終了する
def run_command(command: list[str]):
    cmd = subprocess.run(command, capture_output=True, shell=True)
    try:
        cmd.check_returncode()
    except subprocess.CalledProcessError:
        print(cmd.stdout)
        print(cmd.stderr)
        exit(1)

# APKEditorを使用して、分割されたAPK（APKM/APKS等）を単一のAPKにマージする
def merge_apk(path: str):
    subprocess.run(
        ["java", "-jar", "./bins/apkeditor.jar", "m", "-extractNativeLibs", "true", "-i", path]
    ).check_returncode()

# Morphe CLIでパッチを適用・署名し、生成された成果物を指定パスへ移動する
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
        "java", "-jar", cli, "patch",
        "-p", patches,
        "--continue-on-error",
        "--keystore", "ks.keystore",
        "--keystore-entry-password", "123456789",
        "--keystore-password", "123456789",
        "--signer", "jhc",
        "--keystore-entry-alias", "jhc",
    ]

    for i in includes:
        command += ["-e", i]
    for e in excludes:
        command += ["-d", e]

    command.append(apk)

    print(f"Executing: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)

    if result.stdout:
        print(result.stdout)

    if result.returncode != 0:
        print("--- CLI Error Output ---", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        print("------------------------", file=sys.stderr)
        result.check_returncode()

    if out is not None:
        base_name = os.path.splitext(apk)[0]
        
        # 大文字小文字の区別を無視して、生成された成果物を再帰的に検索する
        all_apks = glob.glob("**/*.apk", recursive=True)
        found_files = [
            f for f in all_apks 
            if base_name in os.path.basename(f) and "morphe" in os.path.basename(f).lower()
        ]

        if not found_files:
            panic(f"Expected CLI output not found for: {base_name}")

        cli_output = found_files[0]
        print(f"  -> [DEBUG] Detected generated APK: {cli_output}")

        if os.path.exists(out):
            os.unlink(out)

        shutil.move(cli_output, out)

# GitHub CLIを使用してGitHubリポジトリにリリースを作成（既存リリースの削除と再作成を含む）
def publish_release(tag: str, files: list[str], message: str, title=""):
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
        print(f"Release '{tag}' already exists — deleting...")
        subprocess.run(["gh", "release", "delete", tag, "-y"],
                       env=os.environ.copy()).check_returncode()

        print(f"Deleting tag '{tag}' via API...")
        api_cmd = [
            "gh", "api", "--method", "DELETE",
            f"/repos/{os.environ['GITHUB_REPOSITORY']}/git/refs/tags/{tag}"
        ]
        subprocess.run(api_cmd, env=os.environ.copy()).check_returncode()
        print("Old release removed. Creating new one...")

    command = ["gh", "release", "create", "--latest", tag, "--notes", message, "--title", title]
    command.extend(files)
    subprocess.run(command, env=os.environ.copy()).check_returncode()