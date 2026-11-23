import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from requests import HTTPError

from bilibili_api.video import AudioQuality, AudioStreamDownloadURL, VideoCodecs, VideoQuality, VideoStreamDownloadURL

from video_service import (_bili_choices, _download_bili, _douyin_info, _stream_download, existing_video,
                           parse_source, FormatChoice, VideoInfo)


class VideoServiceTests(unittest.TestCase):
    def test_recognizes_video_links_and_share_text(self):
        self.assertEqual(parse_source("BV1vp37zDEVZ"), ("bilibili", "BV1vp37zDEVZ"))
        self.assertEqual(parse_source("https://www.bilibili.com/video/BV1vp37zDEVZ/?spm=1"), ("bilibili", "BV1vp37zDEVZ"))
        self.assertEqual(parse_source("复制 8.1 https://v.douyin.com/abc123/ 分享"), ("douyin", "https://v.douyin.com/abc123/"))
        with self.assertRaises(ValueError):
            parse_source("https://example.com/video/BV1vp37zDEVZ")

    def test_bilibili_lists_only_returned_video_streams(self):
        streams = [
            VideoStreamDownloadURL("video-url", VideoQuality._720P, VideoCodecs.AVC),
            AudioStreamDownloadURL("audio-url", AudioQuality._132K),
        ]
        self.assertEqual([x.key for x in _bili_choices(streams)], ["64:AVC"])

    def test_douyin_uses_browser_detail_for_quality(self):
        data = {"aweme_id": "7705471673092427043", "desc": "Example", "video": {
            "cover": {"url_list": ["https://example.com/cover.jpg"]},
            "bit_rate": [{"gear_name": "normal_720_0", "bit_rate": 300000,
                          "play_addr": {"url_list": ["https://example.com/video.mp4"], "width": 720, "height": 1280}}],
        }}
        with patch("video_service.fetch_detail", return_value=data):
            info = _douyin_info("https://v.douyin.com/abc/")
        self.assertEqual(info.choices[0].key, "normal_720_0:300000")
        self.assertEqual(info.source, "https://www.douyin.com/video/7705471673092427043")
        self.assertTrue(info.cover_url)

    def test_bilibili_does_not_silently_substitute_quality(self):
        info = VideoInfo("B 站", "BV1vp37zDEVZ", "Example", "", (FormatChoice("80:AVC", "1080P"),))
        streams = [VideoStreamDownloadURL("video-url", VideoQuality._720P, VideoCodecs.AVC)]
        with patch("video_service._bili_streams", return_value=({}, streams)):
            with self.assertRaisesRegex(ValueError, "重新查询"):
                _download_bili(info, info.choices[0], __import__("pathlib").Path("."), lambda *_: None)

    def test_bilibili_403_tries_same_quality_backup(self):
        class Response:
            headers = {"Content-Length": "4"}

            def __init__(self, forbidden):
                self.forbidden = forbidden

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def raise_for_status(self):
                if self.forbidden:
                    raise HTTPError("403 Forbidden")

            def iter_content(self, chunk_size):
                yield b"data"

        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs["headers"]["Referer"], kwargs["headers"]["Range"]))
            return Response(url == "primary")

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory, patch("video_service.requests.get", side_effect=get):
            target = Path(directory) / "video.m4s"
            _stream_download(("primary", "backup"), target, lambda *_: None, 0, 75, "BV1vp37zDEVZ")
            self.assertEqual(target.read_bytes(), b"data")
        self.assertEqual([call[0] for call in calls], ["primary", "backup"])
        self.assertTrue(all(call[1].endswith("/video/BV1vp37zDEVZ/") for call in calls))
        self.assertTrue(all(call[2] == "bytes=0-" for call in calls))

    def test_reuses_existing_video_in_destination(self):
        info = VideoInfo("B 站", "BV1vp37zDEVZ", "Example", "", ())
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            video = Path(directory) / "Example_BV1vp37zDEVZ.mp4"
            video.write_bytes(b"video")
            self.assertEqual(existing_video(info, directory), video)



if __name__ == "__main__":
    unittest.main()
