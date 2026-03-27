import sys
import os
import re
import time
import json
import urllib.request
import subprocess
import argparse
import apkmirror
from functools import cmp_to_key

# 外部ライブラリによる sys.exit() 等のプロセス強制終了を例外に変換して捕捉可能にする
class ProcessExitException(BaseException): pass
def prevent_exit(code=0):
    raise ProcessExitException(f"Process exit prevented! (exit code {code})")
    
sys.exit = prevent_exit
os._exit = prevent_exit

from apkmirror import Version, Variant
from utils import patch_apk, merge_apk 
from download_bins import download_apkeditor, download_morphe_cli

# 外部ライブラリの panic を上書きし、安全に例外として処理する
def panic(msg):
    print(f"  -> [FATAL] {msg}")
    raise ProcessExitException(msg)

# プレリリースを含むバージョン文字列を数値的に比較し、v1 が v2 より新しければ True を返す
def version_greater(v1: str | None, v2: str | None) -> bool:
    if not v1: return False
    if not v2: return True
    def normalize(v: str):
        v = v.lstrip('v')
        parts = v.split('-', 1)
        main_part = parts[0]
        prerelease_part = parts[1] if len(parts) > 1 else ""
        main_nums = [int(n) for n in re.findall(r'\d+', main_part)[:3]]
        while len(main_nums) < 3: main_nums.append(0)
        pre_parts = [int(p) if p.isdigit() else p for p in re.split(r'(\d+)', prerelease_part) if p]
        return main_nums, pre_parts

    nums1, pre1 = normalize(v1)
    nums2, pre2 = normalize(v2)

    for i in range(3):
        if nums1[i] != nums2[i]: return nums1[i] > nums2[i]

    if not pre1 and pre2: return True
    if pre1 and not pre2: return False
    for p1, p2 in zip(pre1, pre2):
        if p1 != p2:
            return p1 > p2 if type(p1) == type(p2) else str(p1) > str(p2)
    return len(pre1) > len(pre2)

# リポジトリのリリース一覧を取得し、バージョン文字列でソートして最新のStableとPre-releaseを返す
def get_latest_releases(repo: str, require_mpp: bool = False) -> dict:
    print(f"  -> Fetching release history for {repo}...")
    cmd = ["gh", "api", f"repos/{repo}/releases?per_page=30"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        releases = json.loads(result.stdout)
    except Exception as e:
        print(f"  -> [WARNING] Failed to fetch releases for {repo}: {e}")
        return {"stable": None, "pre": None}
        
    valid_stable = []
    valid_pre = []

    for r in releases:
        tag = r.get("tag_name")
        is_pre = r.get("prerelease", False)
        
        if require_mpp:
            has_mpp = any(a.get("name", "").endswith(".mpp") for a in r.get("assets", []))
            if not has_mpp: continue
        
        if is_pre:
            valid_pre.append(tag)
        else:
            valid_stable.append(tag)

    def cmp_versions(v1, v2):
        if v1 == v2: return 0
        return 1 if version_greater(v1, v2) else -1

    if valid_stable:
        valid_stable.sort(key=cmp_to_key(cmp_versions), reverse=True)
    if valid_pre:
        valid_pre.sort(key=cmp_to_key(cmp_versions), reverse=True)

    return {
        "stable": valid_stable[0] if valid_stable else None,
        "pre": valid_pre[0] if valid_pre else None
    }

# GitHubリリースを作成または既存のリリースにアセットを追記する（並列実行時の競合回避）
def publish_github_release(tag_name: str, files: list, message: str, title: str, is_prerelease: bool):
    print(f"  -> Attempting to publish/upload to {tag_name}...")
    check_cmd = ["gh", "release", "view", tag_name]
    res = subprocess.run(check_cmd, capture_output=True)
    
    if res.returncode == 0:
        print("  -> Release already exists! Uploading assets to the existing release...")
        subprocess.run(["gh", "release", "upload", tag_name] + files + ["--clobber"], check=True)
    else:
        print("  -> Creating new release...")
        cmd_create = ["gh", "release", "create", tag_name] + files + ["-t", title, "-n", message]
        if is_prerelease: cmd_create.append("--prerelease")
        try:
            subprocess.run(cmd_create, check=True)
        except subprocess.CalledProcessError:
            print("  -> Create failed (likely race condition). Falling back to upload...")
            subprocess.run(["gh", "release", "upload", tag_name] + files + ["--clobber"], check=True)

# Anddeaリポジトリからpatches.json を取得してパースする
def fetch_patches_json(tag: str) -> list:
    url = f"https://raw.githubusercontent.com/anddea/revanced-patches/refs/heads/main/patches-list.json"
    print(f"  -> Fetching patches.json from {url}...")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get("patches", []) if isinstance(data, dict) else data
    except Exception as e:
        panic(f"Failed to load patches.json: {e}")

# 対象アプリがサポートするAPKバージョンのリストを抽出し、直近5件を古い順にソートして返す
def get_supported_versions(patches_list: list, package_name: str) -> list:
    versions_set = set()
    for patch in patches_list:
        compat = patch.get("compatiblePackages")
        if isinstance(compat, dict) and package_name in compat:
            if compat[package_name]: versions_set.update(compat[package_name])
        elif isinstance(compat, list):
            for pkg in compat:
                if isinstance(pkg, dict) and pkg.get("name") == package_name:
                    if pkg.get("versions"): versions_set.update(pkg.get("versions"))

    def parse_ver(v):
        return [int(x) for x in re.findall(r'\d+', v)]
    
    sorted_versions = sorted(list(versions_set), key=parse_ver)
    return sorted_versions[-5:]

# 指定されたAPKバージョンと互換性のあるすべてのパッチをフラグを無視して抽出する
def get_patches_for_version(patches_list: list, package_name: str, target_version: str) -> list:
    patches = []
    for patch in patches_list:
        patch_name = patch.get("name")
        compat = patch.get("compatiblePackages")

        supports_version = False
        if not compat: 
            supports_version = True
        elif isinstance(compat, dict) and package_name in compat:
            versions = compat[package_name]
            if not versions or target_version in versions: supports_version = True
        elif isinstance(compat, list):
            for pkg in compat:
                if isinstance(pkg, dict) and pkg.get("name") == package_name:
                    versions = pkg.get("versions", [])
                    if not versions or target_version in versions: supports_version = True
                    break

        if supports_version:
            patches.append(patch_name)

    return patches

# APKMirrorをスクレイピングし、指定バージョンのダウンロード可能なVariantを取得する
def get_target_apk_variant(base_url: str, target_version: str, app_id: str) -> tuple[Version | None, Variant | None]:
    if not target_version: return None, None
    slug_version = target_version.replace('.', '-')
    urls_to_try = [f"{base_url}{app_id}-{slug_version}-release/", f"{base_url}{app_id}-{slug_version}/"]
    
    variants = []
    target_v = None
    for url in urls_to_try:
        target_v = Version(version=target_version, link=url)
        try:
            variants = apkmirror.get_variants(target_v)
            if variants: break
        except BaseException:
            time.sleep(1)
            continue

    if not variants: return None, None

    for variant in variants:
        if variant.is_bundle:
            arch = variant.architecture.lower()
            if "universal" in arch or "arm64" in arch or "nodpi" in arch: return target_v, variant
    for variant in variants:
        if not variant.is_bundle:
            arch = variant.architecture.lower()
            if "nodpi" in arch or "universal" in arch or "arm64" in arch: return target_v, variant
    return None, None

# Morphe CLI を使用してベースAPKにパッチを適用し、最終的なAPKをビルドする
def build_target_apk(target_name: str, version: str, patches_to_apply: list, input_apk: str):
    patches = "bins/patches.mpp"
    cli = "bins/morphe-cli.jar"
    
    output_apk = f"{target_name}-rvx-v{version}.apk"
    print(f"  -> Building {output_apk} (Force applying ALL {len(patches_to_apply)} compatible patches)...")
    patch_apk(cli, patches, input_apk, includes=patches_to_apply, excludes=[], out=output_apk)
    
    if not os.path.exists(output_apk): panic(f"Failed to build {output_apk}")
    print(f"  -> [SUCCESS] {output_apk} successfully built!")
    return output_apk

# ビルド環境の不要な一時ファイルや過去のAPKを削除してクリーンアップする
def clean_workspace():
    for f in ["youtube_base.apk", "youtube_base.apkm", "youtube_base_merged.apk", "ytmusic_base.apk", "ytmusic_base.apkm", "ytmusic_base_merged.apk", "bins/patches.mpp"]:
        if os.path.exists(f): os.remove(f)
    for f in os.listdir("."):
        if f.endswith(".apk") and "rvx-v" in f: os.remove(f)

# サポートバージョンを最新から順に試行し、ブロックされた場合は古いバージョンへフォールバックしてダウンロードする
def download_with_fallback(app_id: str, base_url: str, supported_versions: list):
    for version in reversed(supported_versions): 
        print(f"\n  -> [FALLBACK ROUTINE] Trying to fetch v{version} for {app_id}...")
        v, variant = get_target_apk_variant(base_url, version, app_id)
        if not variant:
            print(f"  -> [SKIP] No valid variants found for v{version}. Trying older version...")
            continue

        ext = ".apkm" if variant.is_bundle else ".apk"
        filename = f"{app_id.replace('-', '')}_base"
        filepath = f"{filename}{ext}"

        if os.path.exists(filepath): os.remove(filepath)

        try:
            apkmirror.download_apk(variant, path=filepath)
            if os.path.exists(filepath):
                print(f"  -> [SUCCESS] Successfully downloaded base APK for v{version}!")
                if variant.is_bundle:
                    merge_apk(filepath)
                    return f"{filename}_merged.apk", version
                else:
                    return filepath, version
        except BaseException as e:
            print(f"  -> [BLOCKED] Download failed for v{version}. Intercepted fatal exit: {e}")
            if os.path.exists(filepath): os.remove(filepath)
            print("  -> Retrying with an older supported version...")
            time.sleep(3) 
            continue

    return None, None

# パッチの取得からAPKのダウンロード、パッチ適用、GitHubリリース作成までの一連のパイプライン処理
def process(tag: str, is_pre: bool, target_app: str):
    print(f"\n=======================================================")
    print(f"INITIATING BUILD PIPELINE FOR: {tag} ({target_app.upper()})")
    print(f"=======================================================")
    
    clean_workspace()

    print("\n[STEP 3] Downloading patches & CLI...")
    subprocess.run(["gh", "release", "download", tag, "-R", "anddea/revanced-patches", "-p", "*.mpp", "-O", "bins/patches.mpp"], check=True)
    download_apkeditor()
    download_morphe_cli()

    patches_list = fetch_patches_json(tag)
    yt_url = "https://www.apkmirror.com/apk/google-inc/youtube/"
    ytm_url = "https://www.apkmirror.com/apk/google-inc/youtube-music/"

    outputs = []
    included_apps_text = []

    if target_app in ["youtube", "all"]:
        print("\n[YOUTUBE] Fetching target versions...")
        yt_versions = get_supported_versions(patches_list, "com.google.android.youtube")
        
        yt_input, final_yt_ver = download_with_fallback("youtube", yt_url, yt_versions)
        if yt_input and final_yt_ver:
            try:
                yt_patches = get_patches_for_version(patches_list, "com.google.android.youtube", final_yt_ver)
                out = build_target_apk("youtube", final_yt_ver, yt_patches, yt_input)
                outputs.append(out)
                included_apps_text.append(f"- YouTube v{final_yt_ver}")
            except BaseException as e:
                print(f"  -> [WARNING] YouTube build failed: {e}")
        else:
            print("  -> [FATAL] All fallback attempts failed for YouTube.")

    if target_app in ["ytmusic", "all"]:
        print("\n[YT MUSIC] Fetching target versions...")
        ytm_versions = get_supported_versions(patches_list, "com.google.android.apps.youtube.music")
        
        ytm_input, final_ytm_ver = download_with_fallback("youtube-music", ytm_url, ytm_versions)
        if ytm_input and final_ytm_ver:
            try:
                ytm_patches = get_patches_for_version(patches_list, "com.google.android.apps.youtube.music", final_ytm_ver)
                out = build_target_apk("ytmusic", final_ytm_ver, ytm_patches, ytm_input)
                outputs.append(out)
                included_apps_text.append(f"- YouTube Music v{final_ytm_ver}")
            except BaseException as e:
                print(f"  -> [WARNING] YT Music build failed: {e}")
        else:
            print("  -> [FATAL] All fallback attempts failed for YT Music.")

    if not outputs:
        panic("No APKs were built. Aborting release.")

    print(f"\n[STEP 8] Publishing release to GitHub...")
    apps_str = "\n".join(included_apps_text)
    message = f"Changelogs:\n[Anddea Patches {tag}](https://github.com/anddea/revanced-patches/releases/tag/{tag})"
    
    publish_github_release(tag, outputs, message, f"RVX {tag}", is_pre)
    print("  -> [DONE] Release successfully published!")

# 引数を解釈して上流と自リポジトリのバージョンを比較し、更新があればビルドを開始する
def main():
    parser = argparse.ArgumentParser(description="RVX Auto Builder")
    parser.add_argument("--app", choices=["youtube", "ytmusic", "all"], default="all", help="Which app to build")
    args = parser.parse_args()

    repo_url = "monsivamon/revanced_extended_anddea-apk" 
    upstream_repo = "anddea/revanced-patches"

    print(f"\n[STEP 1] Fetching release history... (Mode: {args.app.upper()})")
    upstream = get_latest_releases(upstream_repo, require_mpp=True)
    my_repo = get_latest_releases(repo_url, require_mpp=False)
    
    print(f"\n[VERSION INFO]")
    print(f"  -> Upstream ({upstream_repo}):")
    print(f"     - Stable: {upstream['stable'] or 'None'}")
    print(f"     - Pre-release: {upstream['pre'] or 'None'}")
    print(f"  -> My Repo ({repo_url}):")
    print(f"     - Stable: {my_repo['stable'] or 'None'}")
    print(f"     - Pre-release: {my_repo['pre'] or 'None'}")
    
    print("\n[STEP 2] Verifying build history for updates...")
    build_targets = []
    
    if upstream["stable"] and version_greater(upstream["stable"], my_repo["stable"]):
        print(f"  -> [NEW UPDATE] Stable: {my_repo['stable']} -> {upstream['stable']}")
        build_targets.append({"tag": upstream["stable"], "is_pre": False})
        
    if upstream["pre"] and version_greater(upstream["pre"], my_repo["pre"]):
        print(f"  -> [NEW UPDATE] Pre-release: {my_repo['pre']} -> {upstream['pre']}")
        build_targets.append({"tag": upstream["pre"], "is_pre": True})

    if not build_targets:
        print("  -> [EXIT] No new updates found. Skipping build.")
        return

    for target in build_targets:
        process(target["tag"], target["is_pre"], args.app)

if __name__ == "__main__":
    main()
