import os
import re
import time
import json
import urllib.request
import apkmirror
import github

from apkmirror import Version, Variant
from utils import panic, publish_release, patch_apk
from download_bins import download_morphe_cli, download_release_asset



# [STEP 1] JSON解析: Anddeaのパッチ情報からターゲットバージョンと全パッチリストを取得

def get_target_data() -> dict:
    url = "https://raw.githubusercontent.com/anddea/revanced-patches/main/patches.json"
    print("  -> Fetching patches.json from Anddea's repository...")
    
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        
    youtube_version = None
    ytmusic_version = None
    youtube_patches = []
    ytmusic_patches = []

    for patch in data:
        patch_name = patch.get("name")
        compat = patch.get("compatiblePackages")
        
        if isinstance(compat, dict):
            # YouTube の情報を抽出
            if "com.google.android.youtube" in compat:
                youtube_patches.append(patch_name)
                versions = compat["com.google.android.youtube"]
                if isinstance(versions, list) and len(versions) > 0:
                    youtube_version = versions[-1]
            
            # YouTube Music の情報を抽出
            if "com.google.android.apps.youtube.music" in compat:
                ytmusic_patches.append(patch_name)
                versions = compat["com.google.android.apps.youtube.music"]
                if isinstance(versions, list) and len(versions) > 0:
                    ytmusic_version = versions[-1]

    return {
        "youtube": {"version": youtube_version, "patches": youtube_patches},
        "ytmusic": {"version": ytmusic_version, "patches": ytmusic_patches}
    }



# [STEP 2] APK取得: APKMirrorから「指定バージョン」の「通常APK」を探す

def get_target_apk_variant(base_url: str, target_version: str) -> tuple[Version | None, Variant | None]:
    print(f"  -> Scanning APKMirror for target version: {target_version}")
    versions = apkmirror.get_versions(base_url)
    
    # ターゲットバージョンに合致するリリースを探す（"19.05.36" など）
    target_v = None
    for v in versions:
        if target_version in v.version:
            target_v = v
            break
            
    if not target_v:
        print(f"  -> [WARNING] Version {target_version} not found on APKMirror.")
        return None, None

    # Bot判定回避のため1秒待機
    time.sleep(1)
    
    try:
        variants = apkmirror.get_variants(target_v)
    except Exception as e:
        print(f"  -> Failed to fetch variants: {e}")
        return None, None

    # Bundleを避け、nodpi, universal, または arm64 の通常APKを探す
    for variant in variants:
        if not variant.is_bundle:
            arch = variant.architecture.lower()
            if "nodpi" in arch or "universal" in arch or "arm64" in arch:
                print(f"  -> [SUCCESS] Valid normal APK found: {arch}")
                return target_v, variant
                
    print(f"  -> [WARNING] No valid normal APK (non-bundle) found for {target_version}.")
    return None, None



# [STEP 3] ビルド実行: 脳死全適用（強制フルパッチ）モード

def build_target_apk(target_name: str, target_data: dict, input_apk: str):
    patches = "bins/patches.mpp"
    cli = "bins/morphe-cli.jar"
    
    version = target_data["version"]
    all_patches = target_data["patches"]
    
    output_apk = f"{target_name}-rvx-v{version}.apk"
    print(f"  -> Building {output_apk} (Force applying {len(all_patches)} patches)...")

    # もし将来的に「このパッチを入れるとエラーで落ちる」という競合パッチがあれば、
    # この exclude_list にパッチ名を文字列で追加してください。（例: ["Custom icon"]）
    exclude_list = []

    # リストにある全パッチを includes に突っ込んで強制適用
    patch_apk(
        cli, patches, input_apk,
        includes=all_patches,
        excludes=exclude_list,
        out=output_apk,
    )
    
    if not os.path.exists(output_apk):
        panic(f"  -> [ERROR] Failed to build {output_apk}")
        
    print(f"  -> [SUCCESS] {output_apk} successfully built!")
    return output_apk



# [STEP 4] 処理統合: ダウンロード〜ビルド〜リリースのパイプライン

def process(patch_version: str, rvxRelease, target_data: dict, yt_variant: Variant, ytm_variant: Variant):
    print("\n[STEP 4] Downloading base APKs (Directly to .apk, no merge needed)...")
    
    if yt_variant:
        print("  -> Downloading YouTube base APK...")
        apkmirror.download_apk(yt_variant, path="youtube_base.apk")
    if ytm_variant:
        print("  -> Downloading YouTube Music base APK...")
        apkmirror.download_apk(ytm_variant, path="ytmusic_base.apk")

    print("\n[STEP 5] Preparing Morphe CLI...")
    download_morphe_cli()
    
    print(f"\n[STEP 6] Building patched APKs...")
    outputs = []
    
    if os.path.exists("youtube_base.apk"):
        out = build_target_apk("youtube", target_data["youtube"], "youtube_base.apk")
        outputs.append(out)
        
    if os.path.exists("ytmusic_base.apk"):
        out = build_target_apk("ytmusic", target_data["ytmusic"], "ytmusic_base.apk")
        outputs.append(out)

    if not outputs:
        panic("  -> [ERROR] No APKs were built.")

    print(f"\n[STEP 7] Publishing release to GitHub (Tag: {patch_version})...")
    # リリースノート（Changelogへのリンク）
    message: str = f"Changelogs:\n[Anddea RVX {patch_version}]({rvxRelease['html_url']})"
    
    publish_release(
        patch_version,          # タグ名は「Anddeaのパッチバージョン」にする
        outputs,                # 生成された youtube-rvx-xxx.apk と ytmusic-rvx-xxx.apk
        message,
        f"RVX {patch_version}"  # リリース名
    )
    print("  -> [DONE] Release successfully published!")


# バージョンの新旧比較ロジック（そのまま流用・v4.0.0-dev.5形式にも完全対応）
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

# メインシーケンス

def main():

    repo_url: str = "monsivamon/revanced_extended_anddea-apk" 
    yt_url: str = "https://www.apkmirror.com/apk/google-inc/youtube/"
    ytm_url: str = "https://www.apkmirror.com/apk/google-inc/youtube-music/"

    print("\n[STEP 1] Fetching the latest RVX (Anddea) patches from GitHub...")
    # 1. 最新のAnddeaパッチ(.mpp)を取得
    rvxRelease = download_release_asset(
        "anddea/revanced-patches",
        r".*\.mpp$",
        "bins",
        "patches.mpp",
        include_prereleases=True
    )
    final_patch_ver = rvxRelease["tag_name"]
    print(f"  -> Latest RVX patch: {final_patch_ver}")

    print("\n[STEP 2] Verifying build history for updates...")
    # 2. 過去のビルド（自分のリポジトリの最新タグ）と比較する
    last_build_version = github.get_last_build_version(repo_url)
    last_ver_patch = last_build_version.tag_name if last_build_version else None

    print(f"  -> Target Patch: {final_patch_ver}")
    print(f"  -> Previous Build Patch: {last_ver_patch}")

    is_new_patch = False
    if last_ver_patch is None:
        print("  -> No previous release found. Treating as initial build.")
        is_new_patch = True
    else:
        is_new_patch = version_greater(final_patch_ver, last_ver_patch)

    # アプリのバージョンアップは無視し、パッチの更新がなければ終了する
    if not is_new_patch:
        print("\n  -> [EXIT] No updates for RVX patches. Skipping build.")
        return

    print("\n  -> [RESULT] Patch update detected! Initiating build sequence.")

    print("\n[STEP 3] Fetching target APK versions from patches.json...")
    # 3. JSONからバージョンとパッチリストを取得
    target_data = get_target_data()
    yt_target_ver = target_data["youtube"]["version"]
    ytm_target_ver = target_data["ytmusic"]["version"]
    print(f"  -> Target YouTube version: {yt_target_ver}")
    print(f"  -> Target YT Music version: {ytm_target_ver}")

    # 4. APKMirrorから指定バージョンの通常APKをピンポイントで探す
    yt_v, yt_variant = get_target_apk_variant(yt_url, yt_target_ver)
    ytm_v, ytm_variant = get_target_apk_variant(ytm_url, ytm_target_ver)

    if not yt_variant and not ytm_variant:
        print("  -> [EXIT] Could not find any valid APK variants on APKMirror.")
        return

    # 5. すべての準備が整ったらビルドパイプラインへ！
    process(final_patch_ver, rvxRelease, target_data, yt_variant, ytm_variant)


if __name__ == "__main__":
    main()