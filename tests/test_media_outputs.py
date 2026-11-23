import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_outputs import OutputOptions, produce_outputs
from video_service import ROOT, _ffmpeg_path


class MediaOutputTests(unittest.TestCase):
    def test_real_ffmpeg_extracts_wav_and_keeps_video(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            video = Path(tmp) / "sample.mp4"
            subprocess.run([_ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(video)], check=True)
            outputs = produce_outputs(video, OutputOptions(video=True, wav=True), lambda *_: None)
            self.assertEqual(len(outputs), 2)
            self.assertTrue(video.is_file())
            self.assertTrue(outputs[1].read_bytes().startswith(b"RIFF"))

    def test_transcript_only_removes_video_after_success(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            video = Path(tmp) / "sample.mp4"
            subprocess.run([_ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(video)], check=True)
            def fake_transcribe(_wav, txt, _progress):
                txt.write_text("[00:00:01] 你好，世界\n", encoding="utf-8")
            with patch("media_outputs._run_transcribe", side_effect=fake_transcribe):
                outputs = produce_outputs(video, OutputOptions(video=False, transcript=True), lambda *_: None)
            self.assertFalse(video.exists())
            self.assertEqual(outputs[0].read_text(encoding="utf-8"), "[00:00:01] 你好，世界\n")

    def test_requires_one_output(self):
        with self.assertRaisesRegex(ValueError, "至少选择"):
            OutputOptions(False, False, False).validate()

    def test_local_wav_conversion_preserves_source(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            video = Path(tmp) / "sample.mp4"
            subprocess.run([_ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(video)], check=True)
            outputs = produce_outputs(video, OutputOptions(False, True, False), lambda *_: None, keep_source=True)
            self.assertTrue(video.exists())
            self.assertEqual(outputs[0].suffix, ".wav")


if __name__ == "__main__":
    unittest.main()
