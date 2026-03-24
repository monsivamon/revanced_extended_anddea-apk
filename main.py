import os
import re
import time
import json
import urllib.request
import subprocess
import argparse
import apkmirror

from apkmirror import Version, Variant
from utils import panic, patch_apk, merge_apk 
from download_bins import download_apkeditor, download_morphe_cli

def get_latest_releases(repo: str, require_mpp: bool = False) -> dict:
    print(f"  -> Fetching release history for {repo}...")
    cmd = ["gh", "api", f"repos/{repo}/releases?per_page=30"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        releases = json.loads(result.stdout)
    except Exception as e:
        print(f"  -> [WARNING] Failed to fetch releases for {repo}: {e}")
        return {"stable": None, "pre": None}
        
    stable = None
    pre = None
    for r in releases:
        tag = r.get("tag_name")
        is_pre = r.get("prerelease", False)
        
        if require_mpp:
            has_mpp = any(a.get("name", "").endswith(".mpp") for a in r.get("assets", []))
            if not has_mpp: continue
        
        if is_pre:
            if not pre: pre = tag
        else:
            if not stable: stable = tag
        if stable and pre: break
        
    return {"stable": stable, "pre": pre}

# 🚀 衝突回避！「作成」と「追記アップロード」を自動判別するハイブリッド・リリース機能
def publish_github_release(tag_name: str, files: list, message: str, title: str, is_prerelease: bool):
    print(f"  -> Attempting to publish/upload to {tag_name}...")
    
    # すでにリリース枠が存在するかチェック
    check_cmd = ["gh", "release", "view", tag_name]
    res = subprocess.run(check_cmd, capture_output=True)
    
    if res.returncode == 0:
        # すでに相方(別サーバー)が枠を作っていたら、そこにファイルを「追記」する
        print("  -> Release already exists! Uploading assets to the existing release...")
        subprocess.run(["gh", "release", "upload", tag_name] + files + ["--clobber"], check=True)
    else:
        # まだ誰も作っていなければ、枠を作成してファイルを上げる
        print("  -> Creating new release...")
        cmd_create = ["gh", "release", "create", tag_name] + files + ["-t", title, "-n", message]
        if is_prerelease: cmd_create.append("--prerelease")
        try:
            subprocess.run(cmd_create, check=True)
        except subprocess.CalledProcessError:
            # 作成中に一瞬の差で相方が作った場合のフェイルセーフ
            print("  -> Create failed (likely race condition). Falling back to upload...")
            subprocess.run(["gh", "release", "upload", tag_name] + files + ["--clobber"], check=True)

def get_target_versions_and_patches(tag: str) -> dict:
    url = f"https://raw.githubusercontent.com/anddea/revanced-patches/refs/tags/{tag}/patches.json"
    print(f"  -> Fetching patches.json from {url}...")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        panic(f"Failed to load patches.json: {e}")
        
    youtube_version = None
    ytmusic_version = None
    youtube_patches = []
    ytmusic_patches = []

    patches_list = data.get("patches", []) if isinstance(data, dict) else data
    mandatory_patches = ["Change package name", "GmsCore support", "MicroG support"]

    for patch in patches_list:
        patch_name = patch.get("name")
        compat = patch.get("compatiblePackages")
        is_excluded = patch.get("excluded", False)
        is_use = patch.get("use", True)
        
        if (is_excluded or not is_use) and patch_name not in mandatory_patches: continue

        if isinstance(compat, dict):
            if "com.google.android.youtube" in compat:
                youtube_patches.append(patch_name)
                versions = compat["com.google.android.youtube"]
                if isinstance(versions, list) and len(versions) > 0: youtube_version = versions[-1]
            if "com.google.android.apps.youtube.music" in compat:
                ytmusic_patches.append(patch_name)
                versions = compat["com.google.android.apps.youtube.music"]
                if isinstance(versions, list) and len(versions) > 0: ytmusic_version = versions[-1]
        elif isinstance(compat, list):
            for pkg in compat:
                if isinstance(pkg, dict):
                    pkg_name = pkg.get("name")
                    versions = pkg.get("versions")
                    if pkg_name == "com.google.android.youtube":
                        youtube_patches.append(patch_name)
                        if isinstance(versions, list) and len(versions) > 0: youtube_version = versions[-1]
                    elif pkg_name == "com.google.android.apps.youtube.music":
                        ytmusic_patches.append(patch_name)
                        if isinstance(versions, list) and len(versions) > 0: ytmusic_version = versions[-1]

    return {
        "youtube": {"version": youtube_version, "patches": youtube_patches},
        "ytmusic": {"version": ytmusic_version, "patches": ytmusic_patches}
    }

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
        except Exception:
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

def build_target_apk(target_name: str, target_data: dict, input_apk: str):
    patches = "bins/patches.mpp"
    cli = "bins/morphe-cli.jar"
    version = target_data["version"]
    all_patches = target_data["patches"]
    
    output_apk = f"{target_name}-rvx-v{version}.apk"
    print(f"  -> Building {output_apk} (Force applying {len(all_patches)} patches!)...")
    patch_apk(cli, patches, input_apk, includes=all_patches, excludes=[], out=output_apk)
    
    if not os.path.exists(output_apk): panic(f"  -> [ERROR] Failed to build {output_apk}")
    print(f"  -> [SUCCESS] {output_apk} successfully built!")
    return output_apk

def clean_workspace():
    for f in ["youtube_base.apk", "youtube_base.apkm", "youtube_base_merged.apk", "ytmusic_base.apk", "ytmusic_base.apkm", "ytmusic_base_merged.apk", "bins/patches.mpp"]:
        if os.path.exists(f): os.remove(f)
    for f in os.listdir("."):
        if f.endswith(".apk") and "rvx-v" in f: os.remove(f)

# 🚀 引数 target_app で指定されたアプリのみを処理する
def process(tag: str, is_pre: bool, target_app: str):
    print(f"\n=======================================================")
    print(f"🚀 INITIATING BUILD PIPELINE FOR: {tag} ({target_app.upper()})")
    print(f"=======================================================")
    
    clean_workspace()

    print("\n[STEP 3] Downloading patches & CLI...")
    subprocess.run(["gh", "release", "download", tag, "-R", "anddea/revanced-patches", "-p", "*.mpp", "-O", "bins/patches.mpp"], check=True)
    download_apkeditor()
    download_morphe_cli()

    target_data = get_target_versions_and_patches(tag)
    yt_url = "https://www.apkmirror.com/apk/google-inc/youtube/"
    ytm_url = "https://www.apkmirror.com/apk/google-inc/youtube-music/"

    outputs = []

    # 🎯 指定が youtube または all の場合のみ実行
    if target_app in ["youtube", "all"]:
        print("\n[YOUTUBE] Fetching target and downloading base APK...")
        yt_v, yt_variant = get_target_apk_variant(yt_url, target_data["youtube"]["version"], "youtube")
        if yt_variant:
            ext = ".apkm" if yt_variant.is_bundle else ".apk"
            try:
                apkmirror.download_apk(yt_variant, path=f"youtube_base{ext}")
                if yt_variant.is_bundle:
                    merge_apk("youtube_base.apkm")
                    yt_input = "youtube_base_merged.apk"
                else:
                    yt_input = "youtube_base.apk"
                outputs.append(build_target_apk("youtube", target_data["youtube"], yt_input))
            except Exception as e:
                print(f"  -> [WARNING] 🚨 YouTube build failed: {e}")

    # 🎯 指定が ytmusic または all の場合のみ実行
    if target_app in ["ytmusic", "all"]:
        print("\n[YT MUSIC] Fetching target and downloading base APK...")
        ytm_v, ytm_variant = get_target_apk_variant(ytm_url, target_data["ytmusic"]["version"], "youtube-music")
        if ytm_variant:
            ext = ".apkm" if ytm_variant.is_bundle else ".apk"
            try:
                apkmirror.download_apk(ytm_variant, path=f"ytmusic_base{ext}")
                if ytm_variant.is_bundle:
                    merge_apk("ytmusic_base.apkm")
                    ytm_input = "ytmusic_base_merged.apk"
                else:
                    ytm_input = "ytmusic_base.apk"
                outputs.append(build_target_apk("ytmusic", target_data["ytmusic"], ytm_input))
            except Exception as e:
                print(f"  -> [WARNING] 🚨 YT Music build failed: {e}")

    if not outputs:
        panic("  -> [FATAL] No APKs were built. Aborting release.")

    print(f"\n[STEP 8] Publishing release to GitHub...")
    message = f"Changelogs:\n[Anddea Patches {tag}](https://github.com/anddea/revanced-patches/releases/tag/{tag})\n*(Apps are uploaded individually via matrix build)*"
    publish_github_release(tag, outputs, message, f"RVX {tag}", is_pre)
    print("  -> [DONE] Release successfully published!")


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

def main():
    # 🚀 引数パーサーを追加
    parser = argparse.ArgumentParser(description="RVX Auto Builder")
    parser.add_argument("--app", choices=["youtube", "ytmusic", "all"], default="all", help="Which app to build")
    args = parser.parse_args()

    repo_url = "monsivamon/revanced_extended_anddea-apk" 
    upstream_repo = "anddea/revanced-patches"

    print(f"\n[STEP 1] Fetching release history... (Mode: {args.app.upper()})")
    upstream = get_latest_releases(upstream_repo, require_mpp=True)
    my_repo = get_latest_releases(repo_url, require_mpp=False)
    
    print("[STEP 2] Verifying build history for updates...")
    build_targets = []
    
    if upstream["stable"] and version_greater(upstream["stable"], my_repo["stable"]):
        build_targets.append({"tag": upstream["stable"], "is_pre": False})
        
    if upstream["pre"] and version_greater(upstream["pre"], my_repo["pre"]):
        build_targets.append({"tag": upstream["pre"], "is_pre": True})

    if not build_targets:
        print("  -> [EXIT] No new updates found. Skipping build.")
        return

    for target in build_targets:
        process(target["tag"], target["is_pre"], args.app)

if __name__ == "__main__":
    main()