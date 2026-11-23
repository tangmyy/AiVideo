"""Read Douyin's own video-detail response from an isolated Chrome session."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright


PROFILE = Path(__file__).resolve().parent / ".browser-profile"
DETAIL_PATH = "/aweme/v1/web/aweme/detail/"


@dataclass(frozen=True)
class BrowserFormat:
    key: str
    label: str
    urls: tuple[str, ...]
    width: int
    height: int
    bitrate: int


def _video_id(url: str) -> str | None:
    parsed = urlparse(url)
    match = re.search(r"/video/(\d+)", parsed.path)
    if match:
        return match.group(1)
    ids = parse_qs(parsed.query).get("modal_id") or []
    return ids[0] if ids and ids[0].isdigit() else None


def _first_url(value) -> str:
    if not isinstance(value, dict):
        return ""
    urls = value.get("url_list") or []
    return next((url for url in urls if isinstance(url, str) and url.startswith("https://")), "")


def formats_from_detail(item: dict) -> tuple[BrowserFormat, ...]:
    video = item.get("video") or {}
    found = []
    seen = set()
    for index, record in enumerate(video.get("bit_rate") or []):
        address = record.get("play_addr") or {}
        urls = tuple(url for url in address.get("url_list") or [] if isinstance(url, str) and url.startswith("https://"))
        if not urls:
            continue
        gear = str(record.get("gear_name") or "unknown")
        bitrate = int(record.get("bit_rate") or 0)
        width, height = int(address.get("width") or 0), int(address.get("height") or 0)
        key = f"{gear}:{bitrate}"
        if key in seen:
            key += f":{index}"
        seen.add(key)
        size = f"{width}×{height}" if width and height else gear
        rate = f" · {round(bitrate / 1000)} kb/s" if bitrate else ""
        found.append(BrowserFormat(key, f"{size} · {gear}{rate}", urls, width, height, bitrate))
    if not found:
        address = video.get("play_addr") or {}
        urls = tuple(url for url in address.get("url_list") or [] if isinstance(url, str) and url.startswith("https://"))
        if urls:
            found.append(BrowserFormat("default", "当前可用画质", urls, int(address.get("width") or 0), int(address.get("height") or 0), 0))
    found.sort(key=lambda item: (item.width * item.height, item.bitrate), reverse=True)
    return tuple(found)


def detail_fields(item: dict) -> tuple[str, str, str, tuple[BrowserFormat, ...]]:
    aweme_id = str(item.get("aweme_id") or "")
    if not aweme_id.isdigit():
        raise ValueError("抖音作品详情缺少有效 ID")
    video = item.get("video") or {}
    cover = _first_url(video.get("cover")) or _first_url(video.get("origin_cover"))
    formats = formats_from_detail(item)
    if not formats:
        raise ValueError("没有查到可下载的视频画质")
    return aweme_id, str(item.get("desc") or f"抖音视频 {aweme_id}"), cover, formats


def fetch_detail(source: str) -> dict:
    """Open the work page and capture the matching detail response it requests."""
    expected = _video_id(source)
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(PROFILE), channel="chrome", headless=True, locale="zh-CN",
                viewport={"width": 1440, "height": 900},
                args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            )
            try:
                context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                page = context.new_page()
                details = []

                def capture(response):
                    if DETAIL_PATH not in response.url or response.status != 200:
                        return
                    try:
                        item = response.json().get("aweme_detail")
                        if isinstance(item, dict):
                            details.append(item)
                    except (ValueError, PlaywrightError):
                        pass

                page.on("response", capture)
                try:
                    page.goto(source, wait_until="domcontentloaded", timeout=30_000)
                except PlaywrightTimeout:
                    pass
                expected = expected or _video_id(page.url)
                if not expected:
                    raise ValueError("分享链接未跳转到单条抖音作品页")
                for attempt in range(18):
                    match = next((item for item in details if str(item.get("aweme_id")) == expected), None)
                    if match:
                        return match
                    if attempt == 7:
                        try:
                            page.reload(wait_until="domcontentloaded", timeout=30_000)
                        except PlaywrightTimeout:
                            pass
                    page.wait_for_timeout(1000)
                raise ValueError("浏览器未收到该作品的详情；请确认作品在浏览器中可正常播放")
            finally:
                context.close()
    except PlaywrightError as error:
        raise RuntimeError(f"无法启动或访问独立 Chrome 会话：{error}") from error


def download_format(item: BrowserFormat, destination: Path, progress) -> None:
    """Try all CDN mirrors for one selected format, without changing quality."""
    last_error = None
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.douyin.com/", "Range": "bytes=0-"}
    for url in item.urls:
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(15, 45)) as response:
                response.raise_for_status()
                if response.headers.get("Content-Type", "").lower().startswith("text/html"):
                    raise ValueError("媒体服务器返回了网页而非视频")
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                with destination.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            output.write(chunk)
                            received += len(chunk)
                            if total:
                                progress(min(int(95 * received / total), 95), "下载中")
            if destination.stat().st_size == 0:
                raise ValueError("媒体服务器返回空文件")
            return
        except (requests.RequestException, OSError, ValueError) as error:
            last_error = error
            destination.unlink(missing_ok=True)
    raise RuntimeError(f"所选画质的媒体地址均下载失败：{last_error}")
