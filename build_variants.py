from apkmirror import Version
from utils import patch_apk


# 取得したAPKに対して、Morphe CLIを用いて4種類の異なるパッチ構成を適用し、
# それぞれ別々のAPKファイルとして出力（ビルド）する。
# 
# 【生成される4つのバリアント】
# 1. X (Material You適用)
# 2. X (通常カラー)
# 3. Twitter (青い鳥アイコン復活 + Material You適用)
# 4. Twitter (青い鳥アイコン復活 + 通常カラー)
def build_apks(latest_version: Version):
    apk = "big_file_merged.apk"
    patches = "bins/patches.mpp"
    cli = "bins/morphe-cli.jar"

    # 全バリアントに共通で適用するパッチ（有効化）のリスト
    # ※ 新しいパッチを追加したい場合はここに追記するだけで全APKに反映されます。
    common_includes = [
        "Enable app downgrading",
        "Hide FAB",
        "Disable chirp font",
        "Add ability to copy media link",
        "Hide Banner",
        "Hide promote button",
        "Hide Community Notes",
        "Delete from database",
        "Customize Navigation Bar items",
        "Remove premium upsell",
        "Control video auto scroll",
        "Force enable translate",
    ]

    # 全バリアントに共通で除外するパッチ（無効化）のリスト
    common_excludes = []

    # 1. X (Material You)
    patch_apk(
        cli, patches, apk,
        includes=common_includes,
        excludes=common_excludes,
        out=f"x-piko-material-you-v{latest_version.version}.apk",
    )

    # 2. X (通常カラー) - Dynamic colorを個別に除外
    patch_apk(
        cli, patches, apk,
        includes=common_includes,
        excludes=["Dynamic color"] + common_excludes,
        out=f"x-piko-v{latest_version.version}.apk",
    )

    # 3. Twitter (Material You) - Bring back twitterを個別に適用
    patch_apk(
        cli, patches, apk,
        includes=["Bring back twitter"] + common_includes,
        excludes=common_excludes,
        out=f"twitter-piko-material-you-v{latest_version.version}.apk",
    )

    # 4. Twitter (通常カラー) - Bring back twitter適用 ＋ Dynamic color除外
    patch_apk(
        cli, patches, apk,
        includes=["Bring back twitter"] + common_includes,
        excludes=["Dynamic color"] + common_excludes,
        out=f"twitter-piko-v{latest_version.version}.apk",
    )