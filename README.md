# YouTube & YT Music APK (Anddea RVX Patches) - Auto Builder

[![Build Status](https://github.com/monsivamon/revanced_extended_anddea-apk/actions/workflows/build.yaml/badge.svg)](https://github.com/monsivamon/revanced_extended_anddea-apk/actions)
[![Latest Release](https://img.shields.io/github/v/release/monsivamon/revanced_extended_anddea-apk)](https://github.com/monsivamon/revanced_extended_anddea-apk/releases/latest)

Automated build system for applying [Anddea's RVX](https://github.com/anddea/revanced-patches) patches to YouTube and YouTube Music.

---

## ⚠️ Disclaimer

**App stability is NOT guaranteed.** This build system is configured to automatically force-apply **ALL compatible patches** for the target applications. Because it aggressively applies every supported patch without cherry-picking, unexpected bugs, conflicts, or crashes may occur. Use at your own risk.

**Note on Missing APKs:** Due to APKMirror's strict download restrictions (Cloudflare protection), an app's base APK might occasionally fail to download even after attempting older compatible versions. If a release only contains either YouTube or YouTube Music, don't worry—this is completely normal. The system automatically publishes whichever app successfully builds.

---

## ⚠️ Requirements

To use the patched apps and log in with your Google account, you **MUST** install MicroG (GmsCore).

We highly recommend using **[MicroG-RE](https://github.com/MorpheApp/MicroG-RE)** provided by the Morphe team.

---

## ✨ Key Features & Improvements

### 1. Force-Apply All Compatible Patches

Unlike the upstream default recommendations, this builder extracts the full list of compatible patches from the Morphe CLI metadata and **forcefully applies every single one** that is compatible with the downloaded APK version. This ensures you get the maximum feature set available, though it may come at the cost of stability.

### 2. Auto-Fallback Download System

To combat aggressive anti-bot measures on APKMirror (Cloudflare challenges), the builder extracts a list of all supported APK versions directly from the Morphe CLI metadata. If downloading the latest compatible version is blocked, it **automatically falls back to older compatible versions** until a successful download is achieved. This ensures the build continues even when APKMirror is being difficult.

### 3. Dynamic Patch Extraction via Morphe CLI

Instead of relying on fragile upstream JSON files or hardcoded constants, the system dynamically parses patch metadata—including version compatibility and patch names—directly from the **Morphe CLI** text output. This makes the build process robust against upstream repository structure changes and eliminates the need for manual metadata maintenance.

### 4. Dual-Track Release System (Stable & Pre-release)

The builder independently monitors the upstream repository for both **Stable** and **Pre-release** channels. When an update is detected on either track, it automatically triggers a build and appropriately tags the resulting GitHub Release. You always have access to both the latest stable version and the bleeding-edge pre-release builds.

### 5. Daily Automation

The entire build pipeline runs automatically every day via GitHub Actions scheduled workflow. You don't need to wait for manual updates—the system continuously checks for new patches and APK versions, ensuring you always have the latest builds available.

---

## 📥 Download

Get the latest pre-built APKs from the **[Releases Page](https://github.com/monsivamon/revanced_extended_anddea-apk/releases)**.

---

## 🙏 Credits

- **[anddea/revanced-patches](https://github.com/anddea/revanced-patches)** – The patch source providing all ReVanced Extended modifications.
- **[MorpheApp/morphe-cli](https://github.com/MorpheApp/morphe-cli)** – The Morphe CLI patcher that powers the entire build system.