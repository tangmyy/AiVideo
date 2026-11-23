"""Platform detection, available formats, and single-video downloads."""

import asyncio
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from bilibili_api import Credential, HEADERS, video
from bilibili_api.video import (
    AudioStreamDownloadURL,
    FLVStreamDownloadURL,
    MP4StreamDownloadURL,
    VideoDownloadURLDataDetecter,
    VideoStreamDownloadURL,
)
from dotenv import load_dotenv
from douyin_browser import detail_fields, download_format, fetch_detail

load_dotenv()
# aiohttp's Brotli decoder can fail with the Brotli build bundled in this
# environment. Bilibili accepts gzip/deflate, which avoids that decoder.
HEADERS["Accept-Encoding"] = "gzip, deflate"
ROOT = Path(__file__).resolve().parent
URL_PATTERN = re.compile(r"https?://[^\s<>\"'，。]+", re.I)
BV_PATTERN = re.compile(r"^BV[0-9A-Za-z]{10}$", re.I)


@dataclass(frozen=True)
class FormatChoice:
    key: str
    label: str


@dataclass(frozen=True)
class VideoInfo:
    platform: str
    source: str
    title: str
    cover_url: str
    choices: tuple[FormatChoice, ...]


def parse_source(text: str) -> tuple[str, str]:
    raw = text.strip()
    if BV_PATTERN.fullmatch(raw):
        return "bilibili", raw
    for match in URL_PATTERN.finditer(raw):
        url = match.group(0).rstrip(".,;!?)）】")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}:
            bv = re.search(r"/video/(BV[0-9A-Za-z]{10})(?:/|$)", parsed.path, re.I)
            if bv:
                return "bilibili", bv.group(1)
        if host == "b23.tv":
            return "bilibili", url
        if host in {"v.douyin.com", "www.douyin.com", "douyin.com", "m.douyin.com"}:
            return "douyin", url
    raise ValueError("请输入 B 站 BV 号、视频链接，或抖音视频分享链接")


def _bili_bvid(source: str) -> str:
    if BV_PATTERN.fullmatch(source):
        return source
    response = requests.get(source, timeout=15, allow_redirects=True)
    response.raise_for_status()
    bv = re.search(r"/video/(BV[0-9A-Za-z]{10})(?:/|$)", response.url, re.I)
    if not bv:
        raise ValueError("B 站短链未指向单条视频")
    return bv.group(1)


def _credential() -> Credential:
    return Credential(
        sessdata=os.getenv("SESSDATA") or None,
        bili_jct=os.getenv("BILI_JCT") or None,
        buvid3=os.getenv("BUVID3") or None,
    )


def _bili_streams(bvid: str):
    async def fetch():
        item = video.Video(bvid=bvid, credential=_credential())
        details = await item.get_info()
        streams = await item.get_download_url(page_index=0)
        detected = VideoDownloadURLDataDetecter(streams).detect_all()
        entries = []
        dash = streams.get("dash") or {}
        entries.extend(dash.get("video") or [])
        entries.extend(dash.get("audio") or [])
        entries.extend(streams.get("durl") or [])
        for item in detected:
            primary = item.url
            raw = next((entry for entry in entries if (entry.get("baseUrl") or entry.get("base_url") or entry.get("url")) == primary), None)
            backups = (raw.get("backupUrl") or raw.get("backup_url") or []) if raw else []
            item.mirrors = tuple(dict.fromkeys([primary, *backups]))
        return details, detected

    return asyncio.run(fetch())


def _bili_choices(streams) -> tuple[FormatChoice, ...]:
    choices = []
    for stream in streams:
        if isinstance(stream, VideoStreamDownloadURL):
            codec = stream.video_codecs.name if stream.video_codecs else "未知编码"
            key = f"{stream.video_quality.value}:{codec}"
            choices.append(FormatChoice(key, f"{stream.video_quality.name.lstrip('_').replace('_', ' ')} · {codec}"))
        elif isinstance(stream, (FLVStreamDownloadURL, MP4StreamDownloadURL)):
            choices.append(FormatChoice("combined", "当前可用画质 · 音视频一体"))
    return tuple(choices)


def _douyin_info(source: str) -> VideoInfo:
    aweme_id, title, cover, formats = detail_fields(fetch_detail(source))
    choices = tuple(FormatChoice(item.key, item.label) for item in formats)
    return VideoInfo("抖音", f"https://www.douyin.com/video/{aweme_id}", title, cover, choices)


def query_video(text: str) -> VideoInfo:
    platform, source = parse_source(text)
    if platform == "douyin":
        return _douyin_info(source)
    bvid = _bili_bvid(source)
    details, streams = _bili_streams(bvid)
    choices = _bili_choices(streams)
    if not choices:
        raise ValueError("没有解析到可下载的视频画质")
    return VideoInfo("B 站", bvid, details.get("title") or bvid, details.get("pic") or "", choices)


def fetch_cover(url: str) -> bytes:
    if not url:
        return b""
    response = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    if not response.headers.get("Content-Type", "").lower().startswith("image/"):
        return b""
    if len(response.content) > 8_000_000:
        return b""
    return response.content


def _safe_name(value: str) -> str:
    return (re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .") or "video")[:90]


def _unique_path(folder: Path, name: str, ext: str) -> Path:
    candidate = folder / f"{name}{ext}"
    index = 2
    while candidate.exists():
        candidate = folder / f"{name} ({index}){ext}"
        index += 1
    return candidate


def existing_video(info: VideoInfo, destination: str) -> Path | None:
    """Find a previously saved video for this work in the chosen directory."""
    folder = Path(destination).expanduser().resolve()
    work_id = info.source.rstrip("/").split("/")[-1]
    names = (_safe_name(f"{info.title}_{work_id}"), _safe_name(info.title))
    for name in names:
        path = folder / f"{name}.mp4"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _stream_download(urls: tuple[str, ...], target: Path, progress, start: int, span: int, bvid: str):
    headers = {**HEADERS, "Referer": f"https://www.bilibili.com/video/{bvid}/"}
    last_error = None
    for url in urls:
        try:
            with requests.get(url, stream=True, timeout=(15, 45), headers=headers) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0)
                count = 0
                with target.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            output.write(chunk)
                            count += len(chunk)
                            if total:
                                progress(min(start + int(span * count / total), start + span), "下载中")
            if target.stat().st_size == 0:
                raise ValueError("下载结果为空文件")
            return
        except (requests.RequestException, OSError, ValueError) as error:
            last_error = error
            target.unlink(missing_ok=True)
    raise RuntimeError(f"该画质的所有媒体地址均下载失败：{last_error}")


def _ffmpeg_path() -> str:
    configured = Path(os.getenv("FFMPEG_PATH") or "ffmpeg/bin/ffmpeg.exe")
    path = configured if configured.is_absolute() else ROOT / configured
    if path.is_file():
        return str(path)
    bundled = ROOT / "ffmpeg" / "bin" / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled)
    raise FileNotFoundError(f"未找到 FFmpeg：{path}")


def _download_bili(info: VideoInfo, choice: FormatChoice, folder: Path, progress) -> Path:
    _, streams = _bili_streams(info.source)
    selected = None
    audio = None
    for stream in streams:
        if isinstance(stream, VideoStreamDownloadURL):
            codec = stream.video_codecs.name if stream.video_codecs else "未知编码"
            if f"{stream.video_quality.value}:{codec}" == choice.key:
                selected = stream
        elif isinstance(stream, AudioStreamDownloadURL):
            if audio is None or stream.audio_quality.value > audio.audio_quality.value:
                audio = stream
        elif choice.key == "combined" and isinstance(stream, (FLVStreamDownloadURL, MP4StreamDownloadURL)):
            selected = stream
    if selected is None:
        raise ValueError("所选画质已不可用，请重新查询")
    name = _safe_name(f"{info.title}_{info.source}")
    with tempfile.TemporaryDirectory(prefix="aivideo_", dir=folder) as tmp:
        temp = Path(tmp)
        if isinstance(selected, VideoStreamDownloadURL):
            if audio is None:
                raise ValueError("未找到匹配的音频流")
            video_file, audio_file = temp / "video.m4s", temp / "audio.m4s"
            _stream_download(getattr(selected, "mirrors", (selected.url,)), video_file, progress, 0, 75, info.source)
            _stream_download(getattr(audio, "mirrors", (audio.url,)), audio_file, progress, 75, 20, info.source)
            progress(96, "合并音视频")
            output = _unique_path(folder, name, ".mp4")
            command = [_ffmpeg_path(), "-y", "-i", str(video_file), "-i", str(audio_file), "-c", "copy", str(output)]
        else:
            ext = ".flv" if isinstance(selected, FLVStreamDownloadURL) else ".mp4"
            source_file = temp / f"video{ext}"
            _stream_download(getattr(selected, "mirrors", (selected.url,)), source_file, progress, 0, 95, info.source)
            output = _unique_path(folder, name, ".mp4")
            if ext == ".mp4":
                source_file.replace(output)
                return output
            progress(96, "转换格式")
            command = [_ffmpeg_path(), "-y", "-i", str(source_file), "-c", "copy", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, errors="replace")
        if result.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg 处理失败：{result.stderr[-500:]}")
        return output


def _download_douyin(info: VideoInfo, choice: FormatChoice, folder: Path, progress) -> Path:
    aweme_id, _, _, formats = detail_fields(fetch_detail(info.source))
    if aweme_id != info.source.rstrip("/").split("/")[-1]:
        raise ValueError("作品 ID 已变化，请重新查询")
    selected = next((item for item in formats if item.key == choice.key), None)
    if selected is None:
        raise ValueError("所选画质已不可用，请重新查询")
    output = _unique_path(folder, _safe_name(f"{info.title}_{aweme_id}"), ".mp4")
    partial = output.with_name(f"{output.stem}.{uuid.uuid4().hex[:8]}.part.mp4")
    try:
        download_format(selected, partial, progress)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


def download_video(info: VideoInfo, choice: FormatChoice, destination: str, progress) -> Path:
    if choice not in info.choices:
        raise ValueError("请重新查询并选择画质")
    folder = Path(destination).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if info.platform == "B 站":
        return _download_bili(info, choice, folder, progress)
    return _download_douyin(info, choice, folder, progress)
