import os
import re
import time
import json
import urllib.request
import subprocess
import apkmirror

from apkmirror import Version, Variant
from utils import panic, patch_apk, merge_apk 
from download_bins import download_apkeditor, download_morphe_cli

# GitHub CLI を使ってリポジトリの「最新Stable」と「最新Pre-release」を両方取得する
def get_latest_releases(repo: str) -> dict:
    print(f"  -> Fetching release history for {repo}...")
    cmd = ["gh", "release", "list", "-R", repo, "--limit", "30", "--json", "tagName,isPrerelease"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        releases = json.loads(result.stdout)
    except Exception as e:
        print(f"  -> [WARNING] Failed to fetch releases for {repo}. Might be empty.")
        return {"stable": None, "pre": None}
        
    stable = None
    pre = None
    for r in releases:
        tag = r["tagName"]
        if r["isPrerelease"]:
            if not pre: pre = tag
        else:
            if not stable: stable = tag
        if stable and pre: break
        
    return {"stable": stable, "pre": pre}

# GitHub CLI を使ってリリースを作成（Pre-releaseフラグを自動制御）
def publish_github_release(tag_name: str, files: list, message: str, title: str, is_prerelease: bool):
    release_type = "Pre-release" if is_prerelease else "Stable release"
    print(f"  -> Publishing {release_type}: {tag_name}...")
    
    cmd = ["gh", "release", "create", tag_name] + files + ["-t", title, "-n", message]
    if is_prerelease:
        cmd.append("--prerelease")
        
    subprocess.run(cmd, check=True)

# JSON解析: 指定したタグのパッチ情報からターゲットバージョンとパッチリストを取得
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

    # JSONがリストか辞書かを吸収する
    patches_list = data.get("patches", []) if isinstance(data, dict) else data

    # 必須パッチ（無効化されていても強制的に適用する）
    mandatory_patches = ["Change package name", "GmsCore support", "MicroG support"]

    for patch in patches_list:
        patch_name = patch.get("name")
        compat = patch.get("compatiblePackages")
        
        # 除外フラグ(excluded)や使用フラグ(use)がある場合の安全対策
        is_excluded = patch.get("excluded", False)
        is_use = patch.get("use", True)
        
        # 安定性のため、デフォルトで除外されているパッチはスキップ（必須パッチは例外）
        if (is_excluded or not is_use) and patch_name not in mandatory_patches:
            continue

        if isinstance(compat, dict):
            if "com.google.android.youtube" in compat:
                youtube_patches.append(patch_name)
                versions = compat["com.google.android.youtube"]
                if isinstance(versions, list) and len(versions) > 0:
                    youtube_version = versions[-1]
            
            if "com.google.android.apps.youtube.music" in compat:
                ytmusic_patches.append(patch_name)
                versions = compat["com.google.android.apps.youtube.music"]
                if isinstance(versions, list) and len(versions) > 0:
                    ytmusic_version = versions[-1]

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


# APK取得: リスト画面を無視し、URLを予測して直接狙い撃つ
def get_target_apk_variant(base_url: str, target_version: str, app_id: str) -> tuple[Version | None, Variant | None]:
    if not target_version: return None, None
        
    print(f"  -> [SNIPER MODE] Predicting direct URL for {app_id} v{target_version}...")
    slug_version = target_version.replace('.', '-')
    
    urls_to_try = [
        f"{base_url}{app_id}-{slug_version}-release/",
        f"{base_url}{app_id}-{slug_version}/"
    ]
    
    variants = []
    target_v = None
    
    for url in urls_to_try:
        print(f"  -> Trying direct link: {url}")
        target_v = Version(version=target_version, link=url)
        try:
            variants = apkmirror.get_variants(target_v)
            if variants:
                print("  -> [SUCCESS] Direct link hit! Found variants.")
                break
        except Exception as e:
            time.sleep(1)
            continue

    if not variants:
        print(f"  -> [WARNING] Could not snipe the URL for {target_version}.")
        return None, None

    # Morphe版と同様、Bundle(apkm)も許容してマージする方針に変更（取得成功率大幅UP）
    for variant in variants:
        if variant.is_bundle:
            arch = variant.architecture.lower()
            if "universal" in arch or "arm64" in arch or "nodpi" in arch:
                return target_v, variant
                
    for variant in variants:
        if not variant.is_bundle:
            arch = variant.architecture.lower()
            if "nodpi" in arch or "universal" in arch or "arm64" in arch:
                return target_v, variant
                
    return None, None


# ビルド実行
def build_target_apk(target_name: str, target_data: dict, input_apk: str):
    patches = "bins/patches.mpp"
    cli = "bins/morphe-cli.jar"
    version = target_data["version"]
    all_patches = target_data["patches"]
    
    output_apk = f"{target_name}-rvx-v{version}.apk"
    print(f"  -> Building {output_apk} (Force applying {len(all_patches)} patches!)...")

    patch_apk(cli, patches, input_apk, includes=all_patches, excludes=[], out=output_apk)
    
    if not os.path.exists(output_apk):
        panic(f"  -> [ERROR] Failed to build {output_apk}")
        
    print(f"  -> [SUCCESS] {output_apk} successfully built!")
    return output_apk


# 古い作業ファイルを削除（連続ビルド時の干渉を防ぐ）
def clean_workspace():
    files = ["youtube_base.apk", "youtube_base.apkm", "youtube_base_merged.apk",
             "ytmusic_base.apk", "ytmusic_base.apkm", "ytmusic_base_merged.apk", "bins/patches.mpp"]
    for f in files:
        if os.path.exists(f): os.remove(f)
    for f in os.listdir("."):
        if f.endswith(".apk") and "rvx-v" in f:
            os.remove(f)


# 処理統合: 1つのタグに対するビルドパイプライン
def process(tag: str, is_pre: bool):
    print(f"\n=======================================================")
    print(f"INITIATING BUILD PIPELINE FOR: {tag} ({'Pre-release' if is_pre else 'Stable'})")
    print(f"=======================================================")
    
    clean_workspace()

    print("\n[STEP 3] Downloading patches.mpp for the target version...")
    subprocess.run(["gh", "release", "download", tag, "-R", "anddea/revanced-patches", "-p", "*.mpp", "-O", "bins/patches.mpp"], check=True)

    print("\n[STEP 4] Fetching target APK versions & patches from JSON...")
    target_data = get_target_versions_and_patches(tag)
    yt_target_ver = target_data["youtube"]["version"]
    ytm_target_ver = target_data["ytmusic"]["version"]

    yt_url = "https://www.apkmirror.com/apk/google-inc/youtube/"
    ytm_url = "https://www.apkmirror.com/apk/google-inc/youtube-music/"

    yt_v, yt_variant = get_target_apk_variant(yt_url, yt_target_ver, "youtube")
    ytm_v, ytm_variant = get_target_apk_variant(ytm_url, ytm_target_ver, "youtube-music")

    if not yt_variant and not ytm_variant:
        print("  -> [EXIT] Could not find any valid APK variants on APKMirror.")
        return

    print("\n[STEP 5] Downloading tools and base APKs...")
    download_apkeditor()

    yt_input = None
    if yt_variant:
        ext = ".apkm" if yt_variant.is_bundle else ".apk"
        apkmirror.download_apk(yt_variant, path=f"youtube_base{ext}")
        if os.path.exists(f"youtube_base{ext}"):
            if yt_variant.is_bundle:
                merge_apk("youtube_base.apkm")
                yt_input = "youtube_base_merged.apk"
            else:
                yt_input = "youtube_base.apk"

    ytm_input = None
    if ytm_variant:
        ext = ".apkm" if ytm_variant.is_bundle else ".apk"
        apkmirror.download_apk(ytm_variant, path=f"ytmusic_base{ext}")
        if os.path.exists(f"ytmusic_base{ext}"):
            if ytm_variant.is_bundle:
                merge_apk("ytmusic_base.apkm")
                ytm_input = "ytmusic_base_merged.apk"
            else:
                ytm_input = "ytmusic_base.apk"

    print("\n[STEP 6] Preparing CLI...")
    download_morphe_cli()

    print(f"\n[STEP 7] Building patched APKs...")
    outputs = []
    if yt_input and os.path.exists(yt_input):
        outputs.append(build_target_apk("youtube", target_data["youtube"], yt_input))
    if ytm_input and os.path.exists(ytm_input):
        outputs.append(build_target_apk("ytmusic", target_data["ytmusic"], ytm_input))

    if not outputs:
        panic("  -> [ERROR] No APKs were built.")

    print(f"\n[STEP 8] Publishing release to GitHub...")
    message = f"Changelogs:\n[Anddea Patches {tag}](https://github.com/anddea/revanced-patches/releases/tag/{tag})\n\n### Included Apps:\n- YouTube v{yt_target_ver}\n- YouTube Music v{ytm_target_ver}"
    publish_github_release(tag, outputs, message, f"RVX {tag}", is_pre)
    print("  -> [DONE] Release successfully published!")


# バージョンの新旧比較ロジック
def version_greater(v1: str | None, v2: str | None) -> bool:
    if not v1: return False
    if not v2: return True
    
    print(f"  -> [DEBUG] Comparing: '{v1}' > '{v2}' ?")
    def normalize(v: str):
        v = v.lstrip('v')
        parts = v.split('-', 1)
        main_part = parts[0]
        prerelease_part = parts[1] if len(parts) > 1 else ""

        main_nums = re.findall(r'\d+', main_part)
        main_nums = [int(n) for n in main_nums[:3]]
        while len(main_nums) < 3: main_nums.append(0)

        pre_parts = []
        if prerelease_part:
            for part in re.split(r'(\d+)', prerelease_part):
                if part == '': continue
                if part.isdigit(): pre_parts.append(int(part))
                else: pre_parts.append(part)

        return main_nums, pre_parts

    nums1, pre1 = normalize(v1)
    nums2, pre2 = normalize(v2)

    for i in range(3):
        if nums1[i] != nums2[i]:
            result = nums1[i] > nums2[i]
            print(f"  -> Numeric check: {nums1[i]} vs {nums2[i]} -> {result}")
            return result

    if not pre1 and pre2: return True
    if pre1 and not pre2: return False

    for p1, p2 in zip(pre1, pre2):
        if p1 != p2:
            if type(p1) == type(p2): result = p1 > p2
            else: result = str(p1) > str(p2)
            print(f"  -> Prerelease check: {p1} vs {p2} -> {result}")
            return result
    return len(pre1) > len(pre2)


# メイン処理
def main():
    repo_url = "monsivamon/revanced_extended_anddea-apk" 
    upstream_repo = "anddea/revanced-patches"

    print("\n[STEP 1] Fetching release history for upstream and my repo...")
    upstream = get_latest_releases(upstream_repo)
    my_repo = get_latest_releases(repo_url)
    
    print("\n--- VERSION STATUS ---")
    print(f"Upstream Stable: {upstream['stable']}")
    print(f"Upstream Pre   : {upstream['pre']}")
    print(f"My Repo  Stable: {my_repo['stable']}")
    print(f"My Repo  Pre   : {my_repo['pre']}")
    print("----------------------\n")

    print("[STEP 2] Verifying build history for updates...")
    build_targets = []
    
    if upstream["stable"] and version_greater(upstream["stable"], my_repo["stable"]):
        build_targets.append({"tag": upstream["stable"], "is_pre": False})
        
    if upstream["pre"] and version_greater(upstream["pre"], my_repo["pre"]):
        build_targets.append({"tag": upstream["pre"], "is_pre": True})

    if not build_targets:
        print("  -> [EXIT] No new updates found. Skipping build.")
        return

    print(f"  -> [RESULT] Found {len(build_targets)} pending update(s)!")
    
    for target in build_targets:
        process(target["tag"], target["is_pre"])


if __name__ == "__main__":
    main()