import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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

    def test_query_progress_is_busy_then_hidden(self):
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
            self.assertTrue(window.progress.isHidden())
            window.url_input.setText("BV1vp37zDEVZ")
            window.query()
            self.assertFalse(window.progress.isHidden())
            self.assertEqual((window.progress.minimum(), window.progress.maximum()), (0, 0))
            window.query_done(VideoInfo("B 站", "BV1vp37zDEVZ", "Example", "", (FormatChoice("64:AVC", "720P"),)), b"")
            self.assertTrue(window.progress.isHidden())
            window.close()


if __name__ == "__main__":
    unittest.main()
