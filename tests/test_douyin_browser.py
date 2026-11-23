import unittest

from douyin_browser import _video_id, detail_fields


class DouyinBrowserTests(unittest.TestCase):
    def test_detail_formats_keep_actual_resolutions_and_distinct_bitrates(self):
        item = {"aweme_id": "7705471673092427043", "desc": "Example", "video": {
            "cover": {"url_list": ["https://example.com/cover.jpg"]},
            "bit_rate": [
                {"gear_name": "normal_1080_0", "bit_rate": 300000,
                 "play_addr": {"width": 1080, "height": 1920, "url_list": ["https://example.com/high.mp4"]}},
                {"gear_name": "normal_1080_0", "bit_rate": 260000,
                 "play_addr": {"width": 1080, "height": 1920, "url_list": ["https://example.com/low.mp4"]}},
            ]}}
        aweme_id, title, cover, choices = detail_fields(item)
        self.assertEqual((aweme_id, title, cover), ("7705471673092427043", "Example", "https://example.com/cover.jpg"))
        self.assertEqual([choice.key for choice in choices], ["normal_1080_0:300000", "normal_1080_0:260000"])
        self.assertIn("1080×1920", choices[0].label)

    def test_video_id_from_full_url(self):
        self.assertEqual(_video_id("https://www.douyin.com/video/7705471673092427043?foo=1"), "7705471673092427043")
        self.assertEqual(_video_id("https://www.douyin.com/discover?modal_id=7705471673092427043"), "7705471673092427043")
        self.assertEqual(_video_id("https://www.douyin.com/user/self?from_tab_name=main&modal_id=7705471673092427043&showTab=favorite_collection"), "7705471673092427043")


if __name__ == "__main__":
    unittest.main()
