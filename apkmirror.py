from dataclasses import dataclass
from typing import cast
from urllib.parse import urlparse
from bs4 import BeautifulSoup, Tag
from utils import download, get_scraper, resolve_apk_via_translate


@dataclass
class Version:
    version: str
    link: str


@dataclass
class Variant:
    is_bundle: bool  # Whether the APK is in bundle format
    link: str        # Link to the variant page
    architecture: str  # Architecture (e.g., arm64-v8a)


# Exception raised when failing to find an HTML element
class FailedToFindElement(Exception):
    def __init__(self, message=None) -> None:
        self.message = f"Failed to find element{' ' + message if message is not None else ''}"
        super().__init__(self.message)


# Exception raised when an HTTP request fails
class FailedToFetch(Exception):
    def __init__(self, url=None) -> None:
        self.message = f"Failed to fetch{' ' + url if url is not None else ''}"
        super().__init__(self.message)


# Fetches the list of app versions from the specified APKMirror URL
def get_versions(url: str) -> list[Version]:
    response = get_scraper().get(url)
    if response.status_code != 200:
        raise FailedToFetch(f"{url}: {response.status_code}")

    bs4 = BeautifulSoup(response.text, "html.parser")
    versions = bs4.find("div", attrs={"class": "listWidget"})

    out: list[Version] = []
    if versions is not None:
        for version_row in cast(Tag, versions).findChildren("div", recursive=False)[1:]:
            if version_row is None:
                continue

            version_span = version_row.find("span", {"class": "infoSlide-value"})
            if version_span is None:
                continue

            version = version_span.string.strip()
            link = f"https://www.apkmirror.com/{version_row.find('a')['href']}"
            out.append(Version(version=version, link=link))

    return out


# Downloads the APK file from the variant link
def download_apk(variant: Variant, path: str = "big_file.apkm"):
    url = variant.link

    response = get_scraper().get(url)
    if response.status_code != 200:
        raise FailedToFetch(url)

    response_body = BeautifulSoup(response.content, "html.parser")

    download_button = response_body.find("a", {"class": "downloadButton"})
    if download_button is None:
        raise FailedToFindElement("Download button")

    download_page_link = f"https://www.apkmirror.com/{cast(Tag, download_button).attrs['href']}"

    # Navigate to the next download page
    download_page = get_scraper().get(download_page_link)

    if download_page.status_code != 200:
        raise FailedToFetch(download_page_link)

    download_page_body = BeautifulSoup(download_page.content, "html.parser")

    # Prefer rel="nofollow" links pointing to download.php
    nofollow_links = download_page_body.find_all("a", {"rel": "nofollow"})
    direct_link = next(
        (link for link in nofollow_links if "download.php" in (link.get("href") or "")),
        nofollow_links[0] if nofollow_links else None,
    )
    if direct_link is None:
        raise FailedToFindElement("download link")

    direct_link_href = cast(Tag, direct_link).attrs["href"]
    if direct_link_href.startswith("http://") or direct_link_href.startswith("https://"):
        direct_link_url = direct_link_href
    else:
        direct_link_url = f"https://www.apkmirror.com/{direct_link_href.lstrip('/')}"
    print(f"Direct link: {direct_link_url}")

    # download.php redirects (302) to signed CDN (r2.cloudflarestorage.com).
    # Handle the redirect manually and fetch the APK binary directly from CDN.
    response = get_scraper().get(
        direct_link_url,
        headers={"Referer": download_page_link},
        allow_redirects=False,
        stream=True,
    )
    location = response.headers.get("Location") or response.headers.get("location")

    if response.status_code in (301, 302, 303, 307, 308) and location:
        try:
            response.close()
        except Exception:
            pass
        if _is_apkmirror_url(location):
            download(location, path, headers={"Referer": direct_link_url}, use_scraper=True)
        else:
            print("  -> APK is served from CDN, downloading directly")
            download(location, path, headers={"Referer": direct_link_url}, use_scraper=False)
    elif response.status_code == 200 and "text/html" not in (
        response.headers.get("Content-Type") or ""
    ).lower():
        print("  -> Saving APK from direct response")
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        try:
            response.close()
        except Exception:
            pass
    else:
        # If blocked (403 / challenge HTML), resolve the 302 CDN URL via translate relay
        print(f"  -> HTTP {response.status_code}; resolving CDN URL via relay...")
        try:
            response.close()
        except Exception:
            pass
        location = resolve_apk_via_translate(direct_link_url)
        if not location:
            print("  -> relay could not resolve; trying headless browser...")
            try:
                from browser import get_browser
                location = get_browser().resolve_redirect(direct_link_url)
            except Exception as e:
                print(f"  -> browser fallback failed: {type(e).__name__}: {e}")
                location = None
        if not location:
            raise RuntimeError(f"HTTP Error {response.status_code} for URL: {direct_link_url}")
        print("  -> APK is served from CDN, downloading directly")
        download(location, path, headers={"Referer": direct_link_url}, use_scraper=False)

    # Verify ZIP/APK magic bytes to ensure no HTML challenge page was saved
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic != b"PK\x03\x04":
        raise RuntimeError(f"Downloaded file is not a valid ZIP/APK (magic={magic!r}). URL may be blocked by Cloudflare.")


def _is_apkmirror_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "apkmirror.com" or host.endswith(".apkmirror.com")


# Fetches available variants (architectures, bundle format) for the specified version
def get_variants(version: Version) -> list[Variant]:
    url = version.link
    variants_page = get_scraper().get(url)

    if variants_page is None or variants_page.status_code != 200:
        raise FailedToFetch(url)

    variants_page_body = BeautifulSoup(variants_page.content, "html.parser")

    variants_table = variants_page_body.find("div", {"class": "table"})
    if variants_table is None:
        raise FailedToFindElement("variants table")

    variants_table_rows = cast(Tag, variants_table).findChildren("div", recursive=False)[1:]

    variants: list[Variant] = []
    for variant_row in variants_table_rows:
        cells = variant_row.findChildren("div", {"class": "table-cell"}, recursive=False)
        if len(cells) == 0:
            continue

        is_bundle_tag = variant_row.find("span", {"class": "apkm-badge"})
        is_bundle = is_bundle_tag is not None and is_bundle_tag.string.strip() == "BUNDLE"

        architecture: str = cells[1].string if len(cells) > 1 and cells[1].string else ""

        link_element = variant_row.find("a", {"class": "accent_color"})
        if link_element is None:
            continue

        link: str = f"https://www.apkmirror.com{link_element.attrs['href']}"
        variants.append(
            Variant(is_bundle=is_bundle, link=link, architecture=architecture)
        )

    return variants
