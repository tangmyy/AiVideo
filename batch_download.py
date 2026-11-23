"""Sequential download of Bilibili and Douyin links."""

from dataclasses import dataclass

from media_outputs import OutputOptions, produce_outputs
from video_service import (BV_PATTERN, URL_PATTERN, VideoInfo, download_video,
                           existing_video, fetch_cover, parse_source, query_video)


def batch_sources(text: str) -> tuple[str, ...]:
    sources = []
    seen = set()
    for line in text.splitlines():
        candidates = [match.group(0) for match in URL_PATTERN.finditer(line)]
        if not candidates and BV_PATTERN.fullmatch(line.strip()):
            candidates = [line.strip()]
        for candidate in candidates:
            try:
                platform, source = parse_source(candidate)
            except ValueError:
                continue
            key = (platform, source)
            if key not in seen:
                seen.add(key)
                sources.append(source)
    if not sources:
        raise ValueError("请每行粘贴一条 B 站或抖音链接，也可单独填写 BV 号")
    return tuple(sources)


def highest_quality(info: VideoInfo):
    if not info.choices:
        raise ValueError("没有可用画质")
    if info.platform == "B 站":
        return max(info.choices, key=lambda choice: (
            int(choice.key.partition(":")[0]) if choice.key.partition(":")[0].isdigit() else -1,
            choice.key.endswith(":AVC"),
        ))
    return info.choices[0]


@dataclass(frozen=True)
class BatchResult:
    completed: int
    failed: int
    cancelled: bool


def run_batch(sources, destination: str, options: OutputOptions, progress, item_done, cancelled,
              item_started=None, video_ready=None) -> BatchResult:
    options.validate()
    completed = failed = 0
    total = len(sources)
    for index, source in enumerate(sources, 1):
        if cancelled():
            return BatchResult(completed, failed, True)
        video_path = None
        try:
            if item_started:
                item_started(index, total, source)
            progress(-1, f"第 {index}/{total} 条：查询视频")
            info = query_video(source)
            choice = highest_quality(info)
            if video_ready:
                try:
                    cover = fetch_cover(info.cover_url)
                except Exception:
                    cover = b""
                video_ready(info, cover, choice, index, total)
            video_path = existing_video(info, destination)
            reused = video_path is not None
            if reused:
                progress(96, f"第 {index}/{total} 条：复用已有视频")
            else:
                video_path = download_video(
                    info, choice, destination,
                    lambda value, stage: progress(value, f"第 {index}/{total} 条：{stage}"),
                )
            produce_outputs(
                video_path, options,
                lambda value, stage: progress(value, f"第 {index}/{total} 条：{stage}"),
                keep_source=reused,
            )
            completed += 1
            item_done(True, f"{index}/{total}  完成 · {info.title}")
        except Exception as error:
            failed += 1
            note = f"；视频已保留：{video_path}" if video_path is not None and video_path.exists() else ""
            item_done(False, f"{index}/{total}  失败 · {source} · {error}{note}")
    return BatchResult(completed, failed, False)
