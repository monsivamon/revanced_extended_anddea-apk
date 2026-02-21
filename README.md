# YouTube & YT Music APK (Anddea RVX Patches) - Auto Builder

[![Build Status](https://github.com/monsivamon/revanced_extended_anddea-apk/actions/workflows/build.yaml/badge.svg)](https://github.com/monsivamon/revanced_extended_anddea-apk/actions)
[![Latest Release](https://img.shields.io/github/v/release/monsivamon/revanced_extended_anddea-apk)](https://github.com/monsivamon/revanced_extended_anddea-apk/releases/latest)

Automated build system for applying [Anddea's RVX](https://github.com/anddea/revanced-patches) patches to YouTube and YouTube Music.
The core mechanism of this builder is based on [monsivamon/twitter-apk](https://github.com/monsivamon/twitter-apk).

## ⚠️ Disclaimer
**App stability is NOT guaranteed.** This build system is configured to automatically force-apply **ALL available patches** for the target applications. Because it blindly applies every patch without selective configuration, unexpected bugs or crashes may occur. Use at your own risk.

## ✨ Key Features & Improvements

### 1. Always Latest Patches
The system automatically detects updates to **Anddea's patches**, fetches the exactly supported base APK versions, and rebuilds the apps.

### 2. Powered by Morphe CLI
The build pipeline relies entirely on **Morphe CLI** for fast and modern patch application.

### 3. Daily Automation
Checks for patch updates every day automatically.

## 📥 Download

Get the latest pre-built APKs from the **[Releases Page](https://github.com/monsivamon/revanced_extended_anddea-apk/releases)**.

## Credits

* [anddea/revanced-patches](https://github.com/anddea/revanced-patches) - The patch source.
* [MorpheApp/morphe-cli](https://github.com/MorpheApp/morphe-cli) - Morphe CLI.