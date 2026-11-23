import unittest
from pathlib import Path
from unittest.mock import patch

from batch_download import batch_sources, highest_quality, run_batch
from media_outputs import OutputOptions
from video_service import FormatChoice, VideoInfo


class BatchDownloadTests(unittest.TestCase):
    def test_extracts_links_and_bv_numbers_without_duplicate(self):
        text = "标题\nBV1vp37zDEVZ\n分享 https://v.douyin.com/abc123/ 复制链接\nBV1vp37zDEVZ"
        self.assertEqual(batch_sources(text), ("BV1vp37zDEVZ", "https://v.douyin.com/abc123/"))

    def test_selects_highest_bili_quality_and_prefers_avc_tie(self):
        info = VideoInfo("B 站", "BV1vp37zDEVZ", "Example", "", (
            FormatChoice("64:AV1", "720P"), FormatChoice("80:HEV", "1080P"),
            FormatChoice("80:AVC", "1080P"),
        ))
        self.assertEqual(highest_quality(info).key, "80:AVC")

    def test_one_failure_does_not_stop_next_video(self):
        info = VideoInfo("抖音", "https://www.douyin.com/video/123", "Example", "", (FormatChoice("high", "最高画质"),))
        events = []
        outputs = []
        ready = []
        with patch("batch_download.query_video", side_effect=[ValueError("第一条不可用"), info]), \
             patch("batch_download.fetch_cover", return_value=b"cover"), \
             patch("batch_download.existing_video", return_value=None), \
             patch("batch_download.download_video", return_value=Path("example.mp4")) as download, \
             patch("batch_download.produce_outputs", return_value=(Path("example.mp4"),)) as produce:
            result = run_batch(("first", "second"), ".", OutputOptions(),
                               lambda value, stage: events.append((value, stage)),
                               lambda ok, message: outputs.append((ok, message)), lambda: False,
                               video_ready=lambda *args: ready.append(args))
        self.assertEqual((result.completed, result.failed, result.cancelled), (1, 1, False))
        self.assertEqual([ok for ok, _ in outputs], [False, True])
        self.assertEqual(download.call_count, 1)
        self.assertEqual(produce.call_count, 1)
        self.assertEqual((ready[0][1], ready[0][2].key, ready[0][3:]), (b"cover", "high", (2, 2)))

    def test_cancel_stops_before_next_item(self):
        result = run_batch(("first",), ".", OutputOptions(), lambda *_: None,
                           lambda *_: None, lambda: True)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.completed, 0)

    def test_shows_each_cover_before_its_download(self):
        first = VideoInfo("抖音", "https://www.douyin.com/video/123", "First", "cover", (FormatChoice("high", "最高"),))
        second = VideoInfo("抖音", "https://www.douyin.com/video/456", "Second", "cover", (FormatChoice("high", "最高"),))
        events = []

        def download(info, *_args):
            events.append(("download", info.title))
            return Path("video.mp4")

        with patch("batch_download.query_video", side_effect=[first, second]), \
             patch("batch_download.fetch_cover", return_value=b"image"), \
             patch("batch_download.existing_video", return_value=None), \
             patch("batch_download.download_video", side_effect=download), \
             patch("batch_download.produce_outputs", return_value=()):
            result = run_batch(("first", "second"), ".", OutputOptions(),
                               lambda *_: None, lambda *_: None, lambda: False,
                               video_ready=lambda info, cover, choice, index, total: events.append(("cover", info.title)))
        self.assertEqual(events, [("cover", "First"), ("download", "First"),
                                  ("cover", "Second"), ("download", "Second")])
        self.assertEqual(result.completed, 2)


if __name__ == "__main__":
    unittest.main()
