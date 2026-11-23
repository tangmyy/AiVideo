"""Desktop entry point for Bilibili and Douyin downloads."""

import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMainWindow, QProgressBar,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

from video_service import download_video, existing_video, fetch_cover, query_video
from media_outputs import OutputOptions, produce_outputs


class QueryWorker(QThread):
    result = pyqtSignal(object, bytes)
    failed = pyqtSignal(str)

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            info = query_video(self.text)
            try:
                cover = fetch_cover(info.cover_url)
            except Exception:
                cover = b""
            self.result.emit(info, cover)
        except Exception as error:
            self.failed.emit(str(error))


class DownloadWorker(QThread):
    progress_changed = pyqtSignal(int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, info, choice, destination, options):
        super().__init__()
        self.info, self.choice, self.destination, self.options = info, choice, destination, options

    def run(self):
        video_path = None
        try:
            video_path = existing_video(self.info, self.destination)
            reused = video_path is not None
            if reused:
                self.progress_changed.emit(96, "复用已下载的视频")
            else:
                video_path = download_video(self.info, self.choice, self.destination, self.progress_changed.emit)
            outputs = produce_outputs(video_path, self.options, self.progress_changed.emit, keep_source=reused)
            self.completed.emit(tuple(str(path) for path in outputs))
        except Exception as error:
            note = f"；已保留视频：{video_path}" if video_path is not None and video_path.exists() else ""
            self.failed.emit(f"{error}{note}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.info = None
        self.busy = False
        self.worker = None
        self.setWindowTitle("AiVideo · 视频下载工作台")
        self.resize(880, 660)
        self.setMinimumSize(650, 540)
        self.build_ui()
        self.setStyleSheet(Path(__file__).with_name("aivideo.qss").read_text(encoding="utf-8"))

    @staticmethod
    def section(text):
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def card(self, parent, label):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(23, 18, 23, 22)
        layout.setSpacing(12)
        layout.addWidget(self.section(label))
        parent.addWidget(frame)
        return layout

    def build_ui(self):
        scroll = QScrollArea()
        scroll.setObjectName("scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.setCentralWidget(scroll)
        root = QWidget()
        root.setObjectName("root")
        scroll.setWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(36, 28, 36, 28)
        outer.setSpacing(17)
        brand = QLabel("A I V I D E O    /    DESKTOP")
        brand.setObjectName("brand")
        outer.addWidget(brand)
        title = QLabel("把喜欢的视频，留在本地。")
        title.setObjectName("heading")
        outer.addWidget(title)
        subtitle = QLabel("粘贴 B 站或抖音链接，查询封面与画质后再下载。")
        subtitle.setObjectName("subtitle")
        outer.addWidget(subtitle)

        input_layout = self.card(outer, "01   视频链接")
        input_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("BV 号、视频链接，或包含抖音短链的分享文案")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.textChanged.connect(self.invalidate)
        self.url_input.returnPressed.connect(self.query)
        input_row.addWidget(self.url_input, 1)
        self.query_button = QPushButton("查询视频")
        self.query_button.setObjectName("primary")
        self.query_button.clicked.connect(self.query)
        input_row.addWidget(self.query_button)
        input_layout.addLayout(input_row)

        result_layout = self.card(outer, "02   查询结果")
        result_row = QGridLayout()
        result_row.setHorizontalSpacing(22)
        result_row.setVerticalSpacing(16)
        self.cover = QLabel("封面将在这里显示")
        self.cover.setObjectName("cover")
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setFixedSize(300, 180)
        result_row.addWidget(self.cover, 0, 0)
        details_widget = QWidget()
        self.details_widget = details_widget
        details = QVBoxLayout(details_widget)
        details.setContentsMargins(0, 0, 0, 0)
        self.platform = QLabel("等待查询")
        self.platform.setObjectName("platform")
        details.addWidget(self.platform)
        self.video_title = QLabel("选择一条视频，查看它的画质")
        self.video_title.setObjectName("videoTitle")
        self.video_title.setWordWrap(True)
        details.addWidget(self.video_title)
        details.addStretch()
        details.addWidget(self.section("可用画质"))
        self.quality = QComboBox()
        self.quality.addItem("查询后选择画质")
        self.quality.setEnabled(False)
        details.addWidget(self.quality)
        result_row.addWidget(details_widget, 0, 1)
        result_row.setColumnStretch(1, 1)
        self.result_row = result_row
        self.narrow_layout = False
        result_layout.addLayout(result_row)

        save_layout = self.card(outer, "03   保存与下载")
        output_row = QHBoxLayout()
        output_row.addWidget(self.section("输出文件"))
        self.save_video = QCheckBox("视频")
        self.save_video.setChecked(True)
        self.save_wav = QCheckBox("WAV 音频")
        self.save_txt = QCheckBox("人声 TXT")
        for checkbox in (self.save_video, self.save_wav, self.save_txt):
            output_row.addWidget(checkbox)
        output_row.addStretch()
        save_layout.addLayout(output_row)
        save_row = QHBoxLayout()
        self.destination = QLineEdit(str(Path.home() / "Downloads"))
        self.destination.setPlaceholderText("保存目录")
        save_row.addWidget(self.destination, 1)
        browse = QPushButton("选择目录")
        browse.clicked.connect(self.choose_directory)
        save_row.addWidget(browse)
        self.download_button = QPushButton("开始下载")
        self.download_button.setObjectName("primary")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self.download)
        save_row.addWidget(self.download_button)
        save_layout.addLayout(save_row)

        bottom = QHBoxLayout()
        self.status = QLabel("等待链接")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(190)
        bottom.addWidget(self.progress)
        outer.addLayout(bottom)
        outer.addStretch()

    def invalidate(self):
        self.info = None
        self.quality.clear()
        self.quality.addItem("查询后选择画质")
        self.quality.setEnabled(False)
        self.download_button.setEnabled(False)
        self.platform.setText("等待查询")
        self.video_title.setText("选择一条视频，查看它的画质")
        self.cover.setPixmap(QPixmap())
        self.cover.setText("封面将在这里显示")
        self.progress.setValue(0)
        if not self.busy:
            self.status.setText("等待链接")

    def set_busy(self, busy):
        self.busy = busy
        self.query_button.setEnabled(not busy)
        self.url_input.setEnabled(not busy)
        for checkbox in (self.save_video, self.save_wav, self.save_txt):
            checkbox.setEnabled(not busy)
        self.quality.setEnabled(not busy and self.info is not None)
        self.download_button.setEnabled(not busy and self.info is not None)

    def query(self):
        text = self.url_input.text().strip()
        if self.busy:
            return
        if not text:
            self.status.setText("请先粘贴视频链接")
            return
        self.invalidate()
        self.status.setText("正在查询视频、封面和可用画质…")
        self.set_busy(True)
        self.worker = QueryWorker(text)
        self.worker.result.connect(self.query_done)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def query_done(self, info, cover):
        self.info = info
        self.platform.setText(info.platform)
        self.video_title.setText(info.title)
        self.video_title.setToolTip(info.title)
        self.quality.clear()
        for choice in info.choices:
            self.quality.addItem(choice.label, choice)
        pixmap = QPixmap()
        if cover and pixmap.loadFromData(cover):
            self.cover.setPixmap(pixmap.scaled(self.cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cover.setText("封面暂不可用")
        self.set_busy(False)
        self.status.setText(f"查询完成 · 找到 {len(info.choices)} 个可用画质")

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.destination.text())
        if path:
            self.destination.setText(path)

    def download(self):
        if self.busy or self.info is None:
            return
        choice = self.quality.currentData()
        destination = self.destination.text().strip()
        if not choice or not destination:
            self.status.setText("请选择画质和保存目录")
            return
        options = OutputOptions(self.save_video.isChecked(), self.save_wav.isChecked(), self.save_txt.isChecked())
        try:
            options.validate()
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.progress.setValue(0)
        self.status.setText("准备下载…")
        self.set_busy(True)
        self.worker = DownloadWorker(self.info, choice, destination, options)
        self.worker.progress_changed.connect(self.progress_changed)
        self.worker.completed.connect(self.download_done)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def progress_changed(self, value, stage):
        if value == 98:
            self.progress.setRange(0, 0)
            self.status.setText(stage)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(value)
            self.status.setText(f"{stage} · {value}%")

    def download_done(self, paths):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.set_busy(False)
        names = "、".join(Path(path).name for path in paths)
        self.status.setText(f"处理完成：{names}")
        self.status.setToolTip("\n".join(paths))

    def failed(self, message):
        self.progress.setRange(0, 100)
        self.set_busy(False)
        self.status.setText(f"操作失败：{message}")
        self.status.setToolTip(message)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("当前任务尚未结束，请稍候再关闭窗口")
            event.ignore()
        else:
            event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "result_row"):
            return
        narrow = self.width() < 800
        if narrow == self.narrow_layout:
            return
        self.narrow_layout = narrow
        self.result_row.removeWidget(self.details_widget)
        if narrow:
            self.result_row.addWidget(self.details_widget, 1, 0)
            self.result_row.setColumnStretch(1, 0)
        else:
            self.result_row.addWidget(self.details_widget, 0, 1)
            self.result_row.setColumnStretch(1, 1)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
