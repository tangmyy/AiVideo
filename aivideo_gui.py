"""Desktop entry point for Bilibili and Douyin downloads."""

import sys
import os
from threading import Event
from pathlib import Path

from PyQt5.QtCore import Qt, QSize, QSettings, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                             QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QProgressBar, QPlainTextEdit,
                             QPushButton, QScrollArea, QStyledItemDelegate, QVBoxLayout, QWidget)

from batch_download import batch_sources, run_batch
from video_service import ROOT, download_video, existing_video, fetch_cover, query_video
from media_outputs import OutputOptions, produce_outputs


SETTINGS_PATH = ROOT / ".user-settings.ini"


class QualityItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), 40))


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


class BatchWorker(QThread):
    progress_changed = pyqtSignal(int, str)
    item_started = pyqtSignal(int, int, str)
    video_ready = pyqtSignal(object, bytes, object, int, int)
    item_finished = pyqtSignal(bool, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, sources, destination, options):
        super().__init__()
        self.sources, self.destination, self.options = sources, destination, options
        self._cancel = Event()

    def request_cancel(self):
        self._cancel.set()

    def run(self):
        try:
            result = run_batch(
                self.sources, self.destination, self.options,
                self.progress_changed.emit, self.item_finished.emit, self._cancel.is_set,
                self.item_started.emit, self.video_ready.emit,
            )
            self.completed.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.info = None
        self.busy = False
        self.worker = None
        self.setWindowTitle("AiVideo · 视频下载工作台")
        self.logo_pixmap = QPixmap()
        for candidate in (os.getenv("ICON_PATH"), "icon_image/icons.png"):
            if not candidate:
                continue
            icon_path = Path(candidate)
            if not icon_path.is_absolute():
                icon_path = ROOT / icon_path
            if self.logo_pixmap.load(str(icon_path)):
                break
        if not self.logo_pixmap.isNull():
            self.setWindowIcon(QIcon(self.logo_pixmap))
        self.resize(880, 660)
        self.setMinimumSize(650, 540)
        self.build_ui()
        self.setStyleSheet(Path(__file__).with_name("aivideo.qss").read_text(encoding="utf-8"))
        self.settings = QSettings(str(SETTINGS_PATH), QSettings.IniFormat)
        saved_path = self.settings.value("download/path", "", type=str)
        if saved_path:
            self.destination.setText(saved_path)
        for key, checkbox, default in (
            ("output/video", self.save_video, True),
            ("output/wav", self.save_wav, False),
            ("output/transcript", self.save_txt, False),
        ):
            checkbox.setChecked(self.settings.value(key, default, type=bool))
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
            if not any(self.frameGeometry().intersects(screen.availableGeometry()) for screen in QApplication.screens()):
                screen = QApplication.primaryScreen().availableGeometry()
                self.move(screen.center() - self.rect().center())

    @staticmethod
    def section(text):
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def card(self, parent, label):
        frame = QFrame()
        frame.setObjectName("group")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
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
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(26)
        brand_row = QHBoxLayout()
        if not self.logo_pixmap.isNull():
            logo = QLabel()
            logo.setPixmap(self.logo_pixmap.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            logo.setFixedSize(32, 32)
            brand_row.addWidget(logo)
        brand = QLabel("AiVideo")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        outer.addLayout(brand_row)
        title = QLabel("视频下载")
        title.setObjectName("heading")
        outer.addWidget(title)
        subtitle = QLabel("粘贴链接，查看封面和画质，再选择需要的文件。")
        subtitle.setObjectName("subtitle")
        outer.addWidget(subtitle)

        input_layout = self.card(outer, "视频链接")
        mode_row = QHBoxLayout()
        self.single_mode = QPushButton("单个下载")
        self.batch_mode = QPushButton("批量下载")
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for button in (self.single_mode, self.batch_mode):
            button.setObjectName("modeButton")
            button.setCheckable(True)
            button.setMinimumHeight(40)
            self.mode_group.addButton(button)
            mode_row.addWidget(button)
        self.single_mode.setChecked(True)
        self.single_mode.clicked.connect(self.switch_mode)
        self.batch_mode.clicked.connect(self.switch_mode)
        mode_row.addStretch()
        input_layout.addLayout(mode_row)
        self.url_input = QLineEdit()
        self.url_input.setMinimumHeight(44)
        self.url_input.setPlaceholderText("BV 号、视频链接，或包含抖音短链的分享文案")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.textChanged.connect(self.invalidate)
        self.url_input.returnPressed.connect(self.query)
        self.query_button = QPushButton("查询视频")
        self.query_button.setMinimumHeight(44)
        self.query_button.setObjectName("primary")
        self.query_button.clicked.connect(self.query)
        single_input_row = QHBoxLayout()
        single_input_row.setSpacing(10)
        single_input_row.addWidget(self.url_input, 1)
        single_input_row.addWidget(self.query_button)
        input_layout.addLayout(single_input_row)
        self.batch_input = QPlainTextEdit()
        self.batch_input.setPlaceholderText("每行粘贴一条 B 站或抖音链接，也可粘贴分享文案")
        self.batch_input.setMinimumHeight(112)
        self.batch_input.textChanged.connect(self.invalidate_batch)
        self.batch_input.hide()
        input_layout.addWidget(self.batch_input)

        result_layout = self.card(outer, "查询结果")
        self.result_heading = result_layout.itemAt(0).widget()
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
        self.quality_heading = self.section("可用画质")
        details.addWidget(self.quality_heading)
        self.quality = QComboBox()
        self.quality.setMinimumHeight(44)
        self.quality.setItemDelegate(QualityItemDelegate(self.quality))
        self.quality.addItem("查询后选择画质")
        self.quality.setEnabled(False)
        details.addWidget(self.quality)
        result_row.addWidget(details_widget, 0, 1)
        result_row.setColumnStretch(1, 1)
        self.result_row = result_row
        self.narrow_layout = False
        self.single_result = QWidget()
        self.single_result.setLayout(result_row)
        result_layout.addWidget(self.single_result)
        self.batch_log = QPlainTextEdit()
        self.batch_log.setReadOnly(True)
        self.batch_log.setPlaceholderText("失败的项目会显示在这里")
        self.batch_log.setFixedHeight(94)
        self.batch_log.hide()
        result_layout.addWidget(self.batch_log)

        save_layout = self.card(outer, "保存与下载")
        output_row = QHBoxLayout()
        output_row.addWidget(self.section("输出文件"))
        self.save_video = QCheckBox("视频")
        self.save_video.setChecked(True)
        self.save_wav = QCheckBox("WAV 音频")
        self.save_txt = QCheckBox("人声 TXT")
        for checkbox in (self.save_video, self.save_wav, self.save_txt):
            checkbox.setMinimumHeight(44)
            output_row.addWidget(checkbox)
        output_row.addStretch()
        save_layout.addLayout(output_row)
        save_layout.addSpacing(8)
        save_layout.addWidget(self.section("保存目录"))
        save_row = QHBoxLayout()
        self.destination = QLineEdit(str(Path.home() / "Downloads"))
        self.destination.setMinimumHeight(44)
        self.destination.setPlaceholderText("保存目录")
        save_row.addWidget(self.destination, 1)
        browse = QPushButton("选择目录")
        browse.setMinimumHeight(44)
        browse.clicked.connect(self.choose_directory)
        save_row.addWidget(browse)
        self.download_button = QPushButton("开始下载")
        self.download_button.setMinimumHeight(44)
        self.download_button.setObjectName("primary")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self.download)
        self.cancel_batch_button = QPushButton("完成当前条后停止")
        self.cancel_batch_button.setMinimumHeight(44)
        self.cancel_batch_button.setEnabled(False)
        self.cancel_batch_button.hide()
        self.cancel_batch_button.clicked.connect(self.cancel_batch)
        save_layout.addLayout(save_row)
        action_row = QHBoxLayout()
        action_row.addStretch()
        action_row.addWidget(self.cancel_batch_button)
        action_row.addWidget(self.download_button)
        save_layout.addLayout(action_row)

        bottom = QHBoxLayout()
        self.status = QLabel("等待链接")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(190)
        self.progress.hide()
        bottom.addWidget(self.progress)
        outer.addLayout(bottom)
        outer.addStretch()

    def invalidate(self):
        self.info = None
        self.quality.clear()
        self.quality.addItem("查询后选择画质")
        self.quality.setEnabled(False)
        if self.single_mode.isChecked():
            self.download_button.setEnabled(False)
        self.platform.setText("等待查询")
        self.video_title.setText("选择一条视频，查看它的画质")
        self.cover.setPixmap(QPixmap())
        self.cover.setText("封面将在这里显示")
        self.progress.setValue(0)
        self.progress.hide()
        if not self.busy:
            self.status.setText("等待链接")

    def invalidate_batch(self):
        self.batch_log.clear()
        self.batch_log.hide()
        if self.batch_mode.isChecked() and not self.busy:
            self.clear_preview()
            self.status.setText("等待批量下载")
            self.set_busy(False)

    def clear_preview(self):
        self.info = None
        self.platform.setText("等待查询")
        self.video_title.setText("当前视频的封面与画质将在这里显示")
        self.quality.clear()
        self.quality.addItem("等待查询")
        self.quality.setEnabled(False)
        self.cover.setPixmap(QPixmap())
        self.cover.setText("封面将在这里显示")

    def switch_mode(self):
        batch = self.batch_mode.isChecked()
        self.url_input.setVisible(not batch)
        self.batch_input.setVisible(batch)
        self.batch_log.setVisible(batch and bool(self.batch_log.toPlainText()))
        self.cancel_batch_button.setVisible(batch)
        self.query_button.setVisible(not batch)
        self.download_button.setText("开始批量下载" if batch else "开始下载")
        self.result_heading.setText("当前视频" if batch else "查询结果")
        self.quality_heading.setText("自动选择画质" if batch else "可用画质")
        self.video_title.setVisible(not batch)
        self.progress.hide()
        self.clear_preview()
        self.status.setText("粘贴多条链接后开始批量下载" if batch else "等待链接")
        self.set_busy(False)

    def set_busy(self, busy, downloading=False):
        self.busy = busy
        self.single_mode.setEnabled(not busy)
        self.batch_mode.setEnabled(not busy)
        self.query_button.setEnabled(not busy)
        self.url_input.setEnabled(not busy)
        self.batch_input.setEnabled(not busy)
        for checkbox in (self.save_video, self.save_wav, self.save_txt):
            checkbox.setEnabled(not downloading)
        self.quality.setEnabled(not busy and self.info is not None and self.single_mode.isChecked())
        can_download = bool(self.batch_input.toPlainText().strip()) if self.batch_mode.isChecked() else self.info is not None
        self.download_button.setEnabled(not busy and can_download)
        self.cancel_batch_button.setEnabled(busy and isinstance(self.worker, BatchWorker))

    def query(self):
        if self.batch_mode.isChecked():
            self.start_batch()
            return
        text = self.url_input.text().strip()
        if self.busy:
            return
        if not text:
            self.status.setText("请先粘贴视频链接")
            return
        self.invalidate()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText("正在查询视频、封面和可用画质…")
        self.set_busy(True)
        self.worker = QueryWorker(text)
        self.worker.result.connect(self.query_done)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_finished)
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
        self.progress.hide()
        self.status.setText(f"查询完成 · 找到 {len(info.choices)} 个可用画质")

    def batch_item_started(self, index, total, source):
        self.clear_preview()
        self.platform.setText(f"第 {index}/{total} 条")
        self.cover.setText("正在查询封面…")

    def batch_video_ready(self, info, cover, choice, index, total):
        self.info = info
        self.platform.setText(f"{info.platform} · 第 {index}/{total} 条")
        self.cover.setToolTip(info.title)
        self.quality.clear()
        self.quality.addItem(choice.label, choice)
        pixmap = QPixmap()
        if cover and pixmap.loadFromData(cover):
            self.cover.setPixmap(pixmap.scaled(self.cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cover.setText("封面暂不可用")

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.destination.text())
        if path:
            self.destination.setText(path)

    def download(self):
        if self.batch_mode.isChecked():
            self.start_batch()
            return
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
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("准备下载…")
        self.set_busy(True, downloading=True)
        self.worker = DownloadWorker(self.info, choice, destination, options)
        self.worker.progress_changed.connect(self.progress_changed)
        self.worker.completed.connect(self.download_done)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def start_batch(self):
        if self.busy:
            return
        try:
            sources = batch_sources(self.batch_input.toPlainText())
            options = OutputOptions(self.save_video.isChecked(), self.save_wav.isChecked(), self.save_txt.isChecked())
            options.validate()
        except ValueError as error:
            self.status.setText(str(error))
            return
        destination = self.destination.text().strip()
        if not destination:
            self.status.setText("请选择保存目录")
            return
        self.clear_preview()
        self.batch_log.clear()
        self.batch_log.hide()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText(f"准备处理 {len(sources)} 条视频…")
        self.worker = BatchWorker(sources, destination, options)
        self.worker.progress_changed.connect(self.progress_changed)
        self.worker.item_started.connect(self.batch_item_started)
        self.worker.video_ready.connect(self.batch_video_ready)
        self.worker.item_finished.connect(self.batch_item_done)
        self.worker.completed.connect(self.batch_done)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_finished)
        self.set_busy(True, downloading=True)
        self.worker.start()

    def cancel_batch(self):
        if isinstance(self.worker, BatchWorker):
            self.worker.request_cancel()
            self.cancel_batch_button.setEnabled(False)
            self.status.setText("当前条处理完成后停止…")

    def batch_item_done(self, success, message):
        if not success:
            self.batch_log.show()
            self.batch_log.appendPlainText(message)

    def batch_done(self, result):
        self.progress.hide()
        self.set_busy(False)
        state = "已停止" if result.cancelled else "已完成"
        self.status.setText(f"批量下载{state}：成功 {result.completed} 条，失败 {result.failed} 条")

    def progress_changed(self, value, stage):
        if value < 0 or value == 98:
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
        self.progress.hide()
        self.set_busy(False)
        self.status.setText(f"操作失败：{message}")
        self.status.setToolTip(message)

    def worker_finished(self):
        worker = self.sender()
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("当前任务尚未结束，请稍候再关闭窗口")
            event.ignore()
        else:
            self.settings.setValue("window/geometry", self.saveGeometry())
            self.settings.setValue("download/path", self.destination.text().strip())
            self.settings.setValue("output/video", self.save_video.isChecked())
            self.settings.setValue("output/wav", self.save_wav.isChecked())
            self.settings.setValue("output/transcript", self.save_txt.isChecked())
            self.settings.sync()
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
    app.setFont(QFont("Microsoft YaHei", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
