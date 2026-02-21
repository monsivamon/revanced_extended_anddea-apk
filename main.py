import os
import re
import time
import apkmirror
import github

from apkmirror import Version, Variant
from build_variants import build_apks
from download_bins import download_apkeditor, download_morphe_cli, download_release_asset
from utils import panic, merge_apk, publish_release


# APKMirrorのバージョン一覧から「Universal Bundleが確実に存在する最新のリリース」を探して返す。
# ※アクセス制限（Bot検知）を防ぐため、1秒のウェイトを挟みながら最大10件まで探索する安全設計。
def get_latest_valid_release(versions: list[Version]) -> tuple[Version | None, Variant | None]:
    check_count = 0
    for i in versions:
        # release版だけを対象にする（alphaやbetaはこの時点でスルーされるためカウントも消費しない）
        if i.version.find("release") >= 0:
            check_count += 1
            print(f"  -> Checking ({check_count}/10): {i.version}")
            
            try:
                variants = apkmirror.get_variants(i)
            except Exception as e:
                print(f"  -> Failed to fetch variants: {e}")
                continue

            for variant in variants:
                if variant.is_bundle and variant.architecture == "universal":
                    print(f"  -> [SUCCESS] Universal bundle found: {i.version}")
                    return i, variant
            
            print(f"  -> No universal bundle found. Trying next version...")
            
            # API制限対策: 最大10件まで探して見つからなければ諦める
            if check_count >= 10:
                print("  -> [WARNING] Checked top 10 releases but found no bundles. Giving up to prevent rate limits.")
                break
            
            # Bot判定回避のため、次のページを見に行く前に1秒待つ
            time.sleep(1)
                
    return None, None


# ビルドのメインパイプライン。
# 既に検証済みの download_link (Variant) を受け取り、ダウンロードからリリースまでを行う。
def process(latest_version: Version, pikoRelease, download_link: Variant):
    print("\n[STEP 4] Downloading APK and tools...")
    
    # 1. APKのダウンロード
    print(f"  -> Downloading {latest_version.version} bundle from APKMirror...")
    apkmirror.download_apk(download_link)
    if not os.path.exists("big_file.apkm"):
        panic("  -> [ERROR] Failed to download APK.")

    # 2. 結合ツールのダウンロードとAPKのマージ
    print("  -> Downloading APKEditor...")
    download_apkeditor()
    if not os.path.exists("big_file_merged.apk"):
        print("  -> Merging APK (big_file.apkm -> big_file_merged.apk)...")
        merge_apk("big_file.apkm")
    else:
        print("  -> Merged APK already exists. Skipping merge.")

    print("\n[STEP 5] Preparing Morphe CLI...")
    # 3. パッチツール (Morphe CLI) のダウンロード
    download_morphe_cli()
    
    message: str = f"""
Changelogs:
[piko-{pikoRelease["tag_name"]}]({pikoRelease["html_url"]})
"""

    print(f"\n[STEP 6] Building patched APKs (Target: {latest_version.version})...")
    # 4. バリアントごとのパッチ適用
    build_apks(latest_version)

    print("\n[STEP 7] Publishing release to GitHub...")
    # 5. GitHubへ完成したAPKをリリース
    publish_release(
        latest_version.version,
        [
            f"x-piko-v{latest_version.version}.apk",
            f"x-piko-material-you-v{latest_version.version}.apk",
            f"twitter-piko-v{latest_version.version}.apk",
            f"twitter-piko-material-you-v{latest_version.version}.apk",
        ],
        message,
        latest_version.version
    )
    print("  -> [DONE] Release successfully published!")


# 過去のGitHubリリースの本文から、適用されたPikoパッチのバージョンを抽出する。
def extract_piko_version(body: str) -> str | None:
    m = re.search(r"piko-(v[\w\.\-]+)", body, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


# バージョンの新旧を比較する（v1 > v2 なら True）。
def version_greater(v1: str, v2: str) -> bool:
    print(f"\n[DEBUG] Comparing: '{v1}' > '{v2}' ?")

    def normalize(v: str):
        v = v.lstrip('v')
        parts = v.split('-', 1)
        main_part = parts[0]
        prerelease_part = parts[1] if len(parts) > 1 else None

        main_nums = re.findall(r'\d+', main_part)
        main_nums = [int(n) for n in main_nums[:3]]
        while len(main_nums) < 3:
            main_nums.append(0)

        return main_nums, prerelease_part

    nums1, pre1 = normalize(v1)
    nums2, pre2 = normalize(v2)

    for i in range(3):
        if nums1[i] != nums2[i]:
            result = nums1[i] > nums2[i]
            print(f"  -> Numeric check pos {i+1}: {nums1[i]} vs {nums2[i]} -> {result}")
            return result

    if pre1 is None and pre2 is not None:
        return True
    if pre1 is not None and pre2 is None:
        return False

    return v1 > v2


# 自動実行モード。
# Twitter APKとPikoパッチの更新状況を確認し、新しいものがあればビルド処理を走らせる。
def main():
    url: str = "https://www.apkmirror.com/apk/x-corp/twitter/"
    repo_url: str = "monsivamon/twitter-apk"

    print("\n[STEP 1] Scanning APKMirror for the latest valid release (Bundle)...")
    # 1. 最新バージョンの取得とチェック
    versions = apkmirror.get_versions(url)
    latest_version, bundle_variant = get_latest_valid_release(versions)
    
    if latest_version is None or bundle_variant is None:
        print("  -> [EXIT] No release with a universal bundle found. Skipping for now.")
        return

    print("\n[STEP 2] Fetching the latest Piko patches from GitHub...")
    # 2. Pikoパッチの最新版を取得
    pikoRelease = download_release_asset(
        "crimera/piko",
        r".*\.mpp$",
        "bins",
        "patches.mpp",
        include_prereleases=True
    )
    final_piko = pikoRelease["tag_name"]
    print(f"  -> Latest Piko patch: {final_piko}")

    print("\n[STEP 3] Verifying build history for updates...")
    last_build_version: github.GithubRelease | None = github.get_last_build_version(repo_url)
        
    final_apk = latest_version.version

    # 3. 初回ビルド時の処理
    if last_build_version is None:
        print("  -> No previous release found. Treating as initial build.")
        process(latest_version, pikoRelease, bundle_variant)
        return

    # 4. 更新判定ロジック
    last_ver_apk = last_build_version.tag_name
    last_ver_piko = extract_piko_version(last_build_version.body or "")
    
    print(f"  -> Target APK: {final_apk}")
    print(f"  -> Target Piko: {final_piko}")
    print(f"  -> Previous Build APK: {last_ver_apk}")
    print(f"  -> Previous Build Piko: {last_ver_piko}")
    
    apk_is_new = version_greater(final_apk, last_ver_apk)

    if last_ver_piko is None:
        print("  -> Previous Piko version is unknown. Treating as new.")
        piko_is_new = True
    else:
        piko_is_new = version_greater(final_piko, last_ver_piko)

    if not apk_is_new and not piko_is_new:
        print("\n  -> [EXIT] No updates for APK or Piko. Skipping build.")
        return
        
    print("\n  -> [RESULT] Update detected! Initiating build sequence.")
    if apk_is_new:
        print(f"     APK Update:  {last_ver_apk} -> {final_apk}")
    if piko_is_new:
        print(f"     Piko Update: {last_ver_piko} -> {final_piko}")
        
    # 5. 更新があればビルド開始
    process(latest_version, pikoRelease, bundle_variant)


if __name__ == "__main__":
    main()