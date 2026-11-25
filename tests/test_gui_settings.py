import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication
from aivideo_gui import MainWindow
from video_service import ROOT, FormatChoice, VideoInfo


class GuiSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_query_keeps_output_choices_available(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("aivideo_gui.SETTINGS_PATH", Path(directory) / "settings.ini"):
            window = MainWindow()
            window.set_busy(True)
            self.assertTrue(all(box.isEnabled() for box in (window.save_video, window.save_wav, window.save_txt)))
            window.set_busy(True, downloading=True)
            self.assertFalse(any(box.isEnabled() for box in (window.save_video, window.save_wav, window.save_txt)))
            window.set_busy(False)
            window.close()

    def test_project_logo_is_loaded(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("aivideo_gui.SETTINGS_PATH", Path(directory) / "settings.ini"):
            window = MainWindow()
            self.assertFalse(window.logo_pixmap.isNull())
            self.assertFalse(window.windowIcon().isNull())
            window.close()

    def test_controls_have_comfortable_hit_targets_and_one_font(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("aivideo_gui.SETTINGS_PATH", Path(directory) / "settings.ini"):
            window = MainWindow()
            window.show()
            self.app.processEvents()
            for control in (window.url_input, window.query_button, window.quality,
                            window.save_video, window.save_wav, window.save_txt,
                            window.destination, window.download_button):
                self.assertGreaterEqual(control.height(), 44)
                self.assertEqual(control.font().family(), "Microsoft YaHei")
            window.close()

    def test_restores_geometry_and_download_path(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("aivideo_gui.SETTINGS_PATH", Path(directory) / "settings.ini"):
            first = MainWindow()
            first.resize(900, 700)
            first.move(80, 90)
            first.destination.setText(directory)
            first.save_video.setChecked(False)
            first.save_wav.setChecked(True)
            first.save_txt.setChecked(True)
            first.close()
            second = MainWindow()
            self.assertEqual(second.size(), first.size())
            self.assertEqual(second.destination.text(), directory)
            self.assertFalse(second.save_video.isChecked())
            self.assertTrue(second.save_wav.isChecked())
            self.assertTrue(second.save_txt.isChecked())
            second.close()

    def test_query_progress_remains_visible(self):
        class Signal:
            def connect(self, _slot):
                pass

        class Worker:
            result = failed = finished = Signal()

            def __init__(self, _text):
                pass

            def start(self):
                pass

            def isRunning(self):
                return False

        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("aivideo_gui.SETTINGS_PATH", Path(directory) / "settings.ini"), patch("aivideo_gui.QueryWorker", Worker):
            window = MainWindow()
            window.show()
            self.assertFalse(window.progress.isHidden())
            self.assertEqual(window.progress.value(), 0)
            window.url_input.setText("BV1vp37zDEVZ")
            window.query()
            self.assertFalse(window.progress.isHidden())
            self.assertEqual((window.progress.minimum(), window.progress.maximum()), (0, 0))
            window.query_done(VideoInfo("B 站", "BV1vp37zDEVZ", "Example", "", (FormatChoice("64:AVC", "720P"),)), b"")
            self.assertFalse(window.progress.isHidden())
            self.assertEqual(window.progress.value(), 100)
            window.close()

    def test_batch_mode_switches_input_and_shows_current_video(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("aivideo_gui.SETTINGS_PATH", Path(directory) / "settings.ini"):
            window = MainWindow()
            window.show()
            window.batch_mode.click()
            self.assertFalse(window.batch_input.isHidden())
            self.assertTrue(window.url_input.isHidden())
            self.assertTrue(window.query_button.isHidden())
            self.assertFalse(window.download_button.isHidden())
            self.assertEqual(window.download_button.text(), "开始批量下载")
            self.assertEqual(window.result_heading.text(), "当前视频")
            info = VideoInfo("抖音", "https://www.douyin.com/video/123", "Example", "", (FormatChoice("high", "最高画质"),))
            window.batch_item_started(1, 2, info.source)
            window.batch_video_ready(info, b"", info.choices[0], 1, 2)
            self.assertTrue(window.video_title.isHidden())
            self.assertEqual(window.cover.toolTip(), "Example")
            self.assertEqual(window.quality.currentData(), info.choices[0])
            self.assertFalse(window.single_result.isHidden())
            window.batch_input.setPlainText("https://v.douyin.com/another/")
            self.assertTrue(window.batch_log.isHidden())
            window.batch_item_done(True, "完成 · Example")
            self.assertTrue(window.batch_log.isHidden())
            window.batch_item_done(False, "失败 · Example")
            self.assertFalse(window.batch_log.isHidden())
            with patch.object(window, "start_batch") as start:
                window.download()
                start.assert_called_once()
            window.single_mode.click()
            self.assertFalse(window.url_input.isHidden())
            self.assertTrue(window.batch_input.isHidden())
            self.assertFalse(window.video_title.isHidden())
            window.close()

    def test_download_action_is_below_path_field(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("aivideo_gui.SETTINGS_PATH", Path(directory) / "settings.ini"):
            window = MainWindow()
            window.show()
            self.app.processEvents()
            self.assertGreater(window.download_button.mapTo(window, window.download_button.rect().topLeft()).y(), window.destination.mapTo(window, window.destination.rect().topLeft()).y())
            self.assertEqual(window.progress.mapTo(window, window.progress.rect().topLeft()).y(), window.download_button.mapTo(window, window.download_button.rect().topLeft()).y() + (window.download_button.height() - window.progress.height()) // 2)
            window.close()

    def test_single_query_button_sits_beside_link_input(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("aivideo_gui.SETTINGS_PATH", Path(directory) / "settings.ini"):
            window = MainWindow()
            window.resize(650, 540)
            window.show()
            self.app.processEvents()
            self.assertGreater(window.query_button.x(), window.url_input.x() + window.url_input.width())
            self.assertLessEqual(abs(window.query_button.geometry().center().y() - window.url_input.geometry().center().y()), 2)
            window.close()


if __name__ == "__main__":
    unittest.main()
