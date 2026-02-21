# YouTube & YT Music APK (Anddea RVX Patches) - Auto Builder

[![Build Status](https://github.com/monsivamon/revanced_extended_anddea-apk/actions/workflows/build.yaml/badge.svg)](https://github.com/monsivamon/revanced_extended_anddea-apk/actions)
[![Latest Release](https://img.shields.io/github/v/release/monsivamon/revanced_extended_anddea-apk)](https://github.com/monsivamon/revanced_extended_anddea-apk/releases/latest)

Automated build system for applying [Anddea's RVX](https://github.com/anddea/revanced-patches) patches to YouTube and YouTube Music.
The core mechanism of this builder is based on [monsivamon/twitter-apk](https://github.com/monsivamon/twitter-apk).

## ⚠️ Disclaimer
**App stability is NOT guaranteed.** This build system is configured to automatically parse the upstream JSON and apply the **recommended patches**, but unexpected bugs or crashes may still occur. Use at your own risk.

**Note on Missing APKs:** Due to APKMirror's download restrictions, one of the apps might occasionally fail to download during the build process. If a release only contains either YouTube or YouTube Music, don't worry—this is completely normal! The system is designed to automatically publish whichever app successfully builds.

## ⚠️ Requirements
To use the patched YouTube and YouTube Music apps and log in with your Google account, you **MUST** install MicroG (GmsCore). 
We highly recommend using **[MicroG-RE](https://github.com/MorpheApp/MicroG-RE)** provided by the Morphe team.

## ✨ Key Features & Improvements

### 1. Independent Matrix Builds
To bypass download restrictions, YouTube and YouTube Music are built simultaneously on completely separate servers. They intelligently merge into a single GitHub Release upon completion. Even if one app's build process fails, the surviving app will still be successfully published.

### 2. Dual-Track Release System (Stable & Pre-release)
The builder independently monitors the upstream repository for both **Stable** and **Pre-release** updates, automatically triggering builds and appropriately tagging them so you always have access to the latest channels.

### 3. Powered by Morphe CLI & Daily Automation
The pipeline relies entirely on the modern **Morphe CLI** for fast and reliable patching, running automatically every day via GitHub Actions.

## 📥 Download

Get the latest pre-built APKs from the **[Releases Page](https://github.com/monsivamon/revanced_extended_anddea-apk/releases)**.

## Credits

* [anddea/revanced-patches](https://github.com/anddea/revanced-patches) - The patch source.
* [MorpheApp/morphe-cli](https://github.com/MorpheApp/morphe-cli) - Morphe CLI patcher.