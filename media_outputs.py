"""Create WAV and speech transcript artifacts from a downloaded video."""

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from video_service import ROOT, _ffmpeg_path, _unique_path


@dataclass(frozen=True)
class OutputOptions:
    video: bool = True
    wav: bool = False
    transcript: bool = False

    def validate(self):
        if not (self.video or self.wav or self.transcript):
            raise ValueError("请至少选择一种输出格式")


def _extract_wav(source: Path, destination: Path, speech_only: bool):
    command = [_ffmpeg_path(), "-y", "-i", str(source), "-vn"]
    if speech_only:
        command += ["-ac", "1", "-ar", "16000"]
    command += ["-c:a", "pcm_s16le", "-f", "wav", str(destination)]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"提取 WAV 失败：{result.stderr[-500:]}")


def _timestamp(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 3600:02}:{whole // 60 % 60:02}:{whole % 60:02}"


def _speech_samples(wav_path: Path) -> np.ndarray:
    command = [_ffmpeg_path(), "-v", "error", "-i", str(wav_path), "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"读取人声音频失败：{result.stderr.decode('utf-8', errors='replace')[-500:]}")
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def _transcribe(wav_path: Path, txt_path: Path, progress):
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    try:
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model
    except ImportError as error:
        raise RuntimeError("未安装语音识别依赖，请先运行 uv sync") from error
    cache_dir = str(ROOT / ".model-cache")
    try:
        model_path = download_model("small", cache_dir=cache_dir, local_files_only=True)
    except Exception:
        progress(98, "正在下载语音模型（首次使用；需要访问 Hugging Face）")
        try:
            model_path = download_model("small", cache_dir=cache_dir)
        except Exception as error:
            raise RuntimeError(f"语音模型下载失败，请检查 Hugging Face 网络连接后重试：{error}") from error
    progress(98, "正在加载语音模型")
    model = WhisperModel(model_path, device="cpu", compute_type="int8", local_files_only=True)
    progress(98, "正在识别人声；CPU 转写可能需要几分钟")
    segments, _ = model.transcribe(_speech_samples(wav_path), language="zh", task="transcribe", vad_filter=True)
    partial = txt_path.with_name(txt_path.name + ".part")
    try:
        with partial.open("w", encoding="utf-8", newline="\n") as output:
            for segment in segments:
                line = segment.text.strip()
                if line:
                    output.write(f"[{_timestamp(segment.start)}] {line}\n")
        partial.replace(txt_path)
    finally:
        partial.unlink(missing_ok=True)


def _run_transcribe(wav_path: Path, txt_path: Path, progress):
    """Keep native model failures outside the GUI process."""
    progress(98, "正在独立进程中识别人声")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()), "--transcribe", str(wav_path), str(txt_path)],
        capture_output=True, text=True, errors="replace", cwd=ROOT,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise RuntimeError(f"语音识别进程失败（退出码 {result.returncode}）：{detail}")
    if not txt_path.is_file():
        raise RuntimeError("语音识别进程未生成 TXT 文件")


def produce_outputs(video_path: Path, options: OutputOptions, progress, keep_source: bool = False) -> tuple[Path, ...]:
    """Produce selected files; keep the video if a later stage fails."""
    options.validate()
    video_path = Path(video_path)
    outputs = [video_path] if options.video else []
    if not (options.wav or options.transcript):
        return tuple(outputs)

    with tempfile.TemporaryDirectory(prefix="aivideo_audio_", dir=video_path.parent) as tmp:
        if options.wav:
            wav_path = _unique_path(video_path.parent, video_path.stem, ".wav")
            wav_partial = Path(tmp) / "audio.wav"
        else:
            wav_path = Path(tmp) / "speech.wav"
            wav_partial = wav_path
        progress(97, "提取音频")
        _extract_wav(video_path, wav_partial, speech_only=not options.wav)
        if options.wav:
            wav_partial.replace(wav_path)
            outputs.append(wav_path)
        if options.transcript:
            progress(98, "识别人声（首次使用需下载模型）")
            txt_path = _unique_path(video_path.parent, video_path.stem, ".txt")
            _run_transcribe(wav_path, txt_path, progress)
            outputs.append(txt_path)
    if not options.video and not keep_source:
        video_path.unlink()
    progress(99, "整理输出文件")
    return tuple(outputs)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--transcribe":
        raise SystemExit("用法：media_outputs.py --transcribe <WAV> <TXT>")
    _transcribe(Path(sys.argv[2]), Path(sys.argv[3]), lambda _value, stage: print(stage, flush=True))
