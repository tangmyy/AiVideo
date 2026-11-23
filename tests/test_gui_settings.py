import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from aivideo_gui import MainWindow
from video_service import ROOT


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
            first.close()
            second = MainWindow()
            self.assertEqual(second.size(), first.size())
            self.assertEqual(second.destination.text(), directory)
            second.close()


if __name__ == "__main__":
    unittest.main()
