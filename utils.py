import os
import shutil
import requests
import subprocess
import sys
import glob

_scraper = None

# Check if the response is a Cloudflare challenge page (HTTP 200 with HTML)
def _is_challenge_page(res) -> bool:
    if res is None or getattr(res, "status_code", None) != 200:
        return False
    try:
        text = (res.text or "")[:5000]
    except Exception:
        return False
    markers = (
        "Just a moment", "cf-chl-", "__cf_chl_", "Checking your browser",
        "Attention Required", "challenge-platform", "cf_chl_opt",
    )
    return any(m in text for m in markers)

# Hybrid scraper to bypass Cloudflare/Bot detection
class _HybridSession:
    def __init__(self) -> None:
        import cloudscraper
        try:
            self._primary = cloudscraper.create_scraper(enable_stealth=True)
        except TypeError:
            self._primary = cloudscraper.create_scraper()
        self._primary.headers.update({"User-Agent": "APKUpdater-v3.0.3"})
        self._fallback = None
        self.headers = self._primary.headers
        print("[scraper] primary: cloudscraper (stealth + APKUpdater UA)", flush=True)

    def _get_fallback(self):
        if self._fallback is None:
            from curl_cffi import requests as curl_requests
            self._fallback = curl_requests.Session(impersonate="chrome124")
            print("[scraper] fallback: curl_cffi (Chrome 124 full impersonation)", flush=True)
        return self._fallback

    def get(self, *args, **kwargs):
        r = self._primary.get(*args, **kwargs)
        if r.status_code == 403 or _is_challenge_page(r):
            reason = "403" if r.status_code == 403 else "challenge page"
            try: r.close()
            except Exception: pass
            print(f"[scraper] primary returned {reason}, retrying with curl_cffi...", flush=True)
            r = self._get_fallback().get(*args, **kwargs)
        return r

# Get browser impersonating scraper to bypass Cloudflare/Bot detection
def get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = _HybridSession()
    return _scraper

# Print fatal error message and exit the script
def panic(message: str):
    print(message, file=sys.stderr)
    exit(1)

# Download file from specified URL (using hybrid scraper)
def download(link: str, out: str, headers=None, use_scraper=True):
    if os.path.exists(out):
        print(f"{out} already exists skipping download")
        return

    print(f"  -> Downloading {link}...")

    if headers is None:
        headers = {}
    if "Referer" not in headers:
        headers["Referer"] = "https://www.apkmirror.com/"

    session = get_scraper() if use_scraper else requests
    r = session.get(link, stream=True, headers=headers)
    
    if r.status_code != 200:
        raise RuntimeError(f"HTTP Error {r.status_code} for URL: {link}")

    # Prevent saving HTML challenge pages as APK/APKM
    chunks = r.iter_content(chunk_size=8192)
    try:
        first_chunk = next(chunks)
    except StopIteration:
        first_chunk = b""
        
    if first_chunk:
        lower_chunk = first_chunk.lower()
        if b"<html" in lower_chunk or b"<!doctype" in lower_chunk:
             raise RuntimeError(f"Downloaded file is HTML (challenge page), not an APK/APKM")

    with open(out, "wb") as f:
        if first_chunk:
            f.write(first_chunk)
        for chunk in chunks:
            if chunk:
                f.write(chunk)

# Execute external shell command, output log on failure and exit abnormally
def run_command(command: list[str]):
    cmd = subprocess.run(command, capture_output=True, shell=True)
    try:
        cmd.check_returncode()
    except subprocess.CalledProcessError:
        print(cmd.stdout)
        print(cmd.stderr)
        exit(1)

# Merge split APKs (APKM/APKS etc.) into a single APK using APKEditor
def merge_apk(path: str):
    subprocess.run(
        ["java", "-jar", "./bins/apkeditor.jar", "m", "-extractNativeLibs", "true", "-i", path]
    ).check_returncode()

# Apply patches and sign using Morphe CLI, outputting the generated artifact directly to target path
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

    if out is not None:
        command += ["-o", out]

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
        if not os.path.exists(out):
            panic(f"Expected CLI output not found at: {out}")
        print(f"  -> [DEBUG] Detected generated APK: {out}")

# Create GitHub release using GitHub CLI (including deletion and recreation of existing releases)
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