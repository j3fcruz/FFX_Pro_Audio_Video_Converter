# ffx_pro.py
import sys
import os
import re
import subprocess
import datetime
import shutil
import threading
import queue
import time
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QComboBox, QProgressBar, QMessageBox, QTextEdit,
    QListWidget, QLineEdit, QHBoxLayout, QAction, QToolBar, QStatusBar,
    QCheckBox, QFrame, QSplitter, QSizePolicy
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QSettings, QSize, QFile, QTextStream
# Local imports

from modules.converter_thread import ConverterThread
from modules.utils import which_ffmpeg, AUDIO_EXTS, VIDEO_EXTS
from modules.watcher import FolderWatchHandler, WATCHDOG_AVAILABLE
import resources_rc

SPLEETER_AVAILABLE = True
try:
    from spleeter.separator import Separator
except Exception:
    SPLEETER_AVAILABLE = False

class ConverterApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('FFX Pro – Smart Audio & Video Converter by PatronHub')
        self.setGeometry(200, 200, 1000, 700)

        self.input_files = []
        self.output_folder = None
        self.converter_thread = None
        self.watch_observer = None
        self.watch_queue = queue.Queue()

        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        packaged_ffmpeg = os.path.join(base_dir, 'ffmpeg')
        self.ffmpeg_path = which_ffmpeg(packaged_path=base_dir) or ''

        # QSettings for persistence
        self.settings = QSettings('PatronHub', 'FFXPro')

        self.current_theme = self.settings.value('theme', 'dark')
        self.init_ui()
        self.apply_theme(self.current_theme)
        self.load_settings()

    def init_ui(self):
        central = QWidget()
        layout = QVBoxLayout()

        top_row = QHBoxLayout()

        # Select Files
        file_frame = QFrame()
        file_layout = QVBoxLayout()
        self.file_list = QListWidget()
        self.file_list.setAcceptDrops(True)
        self.file_list.dragEnterEvent = self.dragEnterEvent
        self.file_list.dropEvent = self.dropEvent
        file_layout.addWidget(QLabel('Input Files:'))
        file_layout.addWidget(self.file_list)

        btns = QHBoxLayout()
        select_button = QPushButton('Select Files')
        select_button.clicked.connect(self.select_files)
        btns.addWidget(select_button)

        clear_button = QPushButton('Clear List')
        clear_button.clicked.connect(self.clear_files)
        btns.addWidget(clear_button)

        file_layout.addLayout(btns)
        file_frame.setLayout(file_layout)
        file_frame.setMinimumWidth(480)

        # Right column: settings
        settings_frame = QFrame()
        settings_layout = QVBoxLayout()

        self.format_combo = QComboBox()
        self.format_combo.addItems(['mp4', 'mp3', 'avi', 'wav', 'mkv', 'flac', 'm4a'])
        settings_layout.addWidget(QLabel('Output Format:'))
        settings_layout.addWidget(self.format_combo)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(['High', 'Medium', 'Low'])
        settings_layout.addWidget(QLabel('Quality:'))
        settings_layout.addWidget(self.quality_combo)

        # Enhancement presets
        self.enhance_combo = QComboBox()
        self.enhance_combo.addItems(['None', 'Normalize', 'Bass Boost', 'Treble Boost', 'Vocal Clarity', 'Rock EQ', 'EDM EQ', 'Chill EQ', 'Classical EQ', 'Auto (Genre)'])
        settings_layout.addWidget(QLabel('Enhancement Preset:'))
        settings_layout.addWidget(self.enhance_combo)

        self.custom_name_input = QLineEdit()
        self.custom_name_input.setPlaceholderText('Optional: Custom output name (base)')
        settings_layout.addWidget(self.custom_name_input)

        out_btn = QPushButton('Select Output Folder')
        out_btn.clicked.connect(self.select_output_folder)
        settings_layout.addWidget(out_btn)

        self.output_label = QLabel('No output folder selected')
        settings_layout.addWidget(self.output_label)

        ffmpeg_btn = QPushButton('Set ffmpeg Path (auto-detected if available)')
        ffmpeg_btn.clicked.connect(self.select_ffmpeg)
        settings_layout.addWidget(ffmpeg_btn)

        self.ffmpeg_label = QLabel(f'ffmpeg: {self.ffmpeg_path or "Not found"}')
        settings_layout.addWidget(self.ffmpeg_label)

        # Additional options
        self.keep_meta_chk = QCheckBox('Keep metadata (map_metadata)')
        self.keep_meta_chk.setChecked(True)
        settings_layout.addWidget(self.keep_meta_chk)

        self.sep_stems_chk = QCheckBox('Separate stems (Spleeter, optional)')
        self.sep_stems_chk.setChecked(False)
        self.sep_stems_chk.setEnabled(SPLEETER_AVAILABLE)
        if not SPLEETER_AVAILABLE:
            self.sep_stems_chk.setToolTip('Spleeter not installed. Install spleeter and tensorflow to enable.')
        settings_layout.addWidget(self.sep_stems_chk)

        # Watch folder
        watch_btn = QPushButton('Set & Watch Folder')
        watch_btn.clicked.connect(self.select_watch_folder)
        settings_layout.addWidget(watch_btn)

        self.watch_label = QLabel('Watch: None')
        settings_layout.addWidget(self.watch_label)

        # Save logs
        save_logs_btn = QPushButton('Save Logs...')
        save_logs_btn.clicked.connect(self.save_logs)
        settings_layout.addWidget(save_logs_btn)

        settings_frame.setLayout(settings_layout)

        top_row.addWidget(file_frame)
        top_row.addWidget(settings_frame)

        layout.addLayout(top_row)

        # Progress + logs
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(QLabel('Live Logs:'))
        layout.addWidget(self.log_box)

        # Convert controls
        controls = QHBoxLayout()
        convert_button = QPushButton('Start Conversion')
        convert_button.clicked.connect(self.start_conversion)
        controls.addWidget(convert_button)

        stop_button = QPushButton('Stop')
        stop_button.clicked.connect(self.stop_conversion)
        controls.addWidget(stop_button)

        controls.addStretch()
        layout.addLayout(controls)

        central.setLayout(layout)
        self.setCentralWidget(central)

        # Menu / toolbar
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')
        view_menu = menubar.addMenu('View')   # ✅ Define view_menu here
        help_menu = menubar.addMenu('Help')

        add_file_action = QAction('Add File', self)
        add_file_action.triggered.connect(self.select_files)
        file_menu.addAction(add_file_action)

        export_logs_action = QAction('Export Logs', self)
        export_logs_action.triggered.connect(self.save_logs)
        file_menu.addAction(export_logs_action)

        exit_action = QAction('Exit', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 🌗 Theme Switcher
        toggle_theme_action = QAction('Switch Light/Dark Theme', self)
        toggle_theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme_action)

        about_action = QAction('About FFX Pro', self)
        about_action.triggered.connect(lambda: QMessageBox.information(
            self, 'About',
            'FFX Pro – Smart Audio & Video Converter by PatronHub\nVersion: 1.0\n\nNow with Light & Dark themes!'
        ))
        help_menu.addAction(about_action)


        toolbar = QToolBar('Main Toolbar')
        self.addToolBar(toolbar)
        toolbar.addAction(add_file_action)
        toolbar.addAction(export_logs_action)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        # Timer to update clock and poll watch queue
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.timeout.connect(self._poll_watch_queue)
        self.timer.start(1000)

    def apply_theme_old(self, theme_name: str):
        try:
            if theme_name == 'dark':
                qss_path = ':/assets/themes/dark_theme.qss'
            else:
                qss_path = ':/assets/themes/light_theme.qss'

            file = QFile(qss_path)
            if not file.exists():
                raise FileNotFoundError(f"Theme file not found: {qss_path}")

            if file.open(QFile.ReadOnly | QFile.Text):
                stream = QTextStream(file)
                qss = stream.readAll()
                self.setStyleSheet(qss)
                file.close()
                self.settings.setValue('theme', theme_name)
                print(f"Applied {theme_name} theme successfully.")
            else:
                raise IOError("Could not open theme file")

        except Exception as e:
            print(f"Failed to apply {theme_name} theme: {e}")

    def apply_theme(self, theme_name: str):
        try:
            app = QApplication.instance()

            # 1. Set palette for dialogs and built-in widgets
            palette = QPalette()
            if theme_name == 'dark_theme':
                palette.setColor(QPalette.Window, QColor(36, 36, 36))
                palette.setColor(QPalette.WindowText, Qt.white)
                palette.setColor(QPalette.Base, QColor(25, 25, 25))
                palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
                palette.setColor(QPalette.ToolTipBase, Qt.white)
                palette.setColor(QPalette.ToolTipText, Qt.black)
                palette.setColor(QPalette.Text, Qt.white)
                palette.setColor(QPalette.Button, QColor(45, 45, 45))
                palette.setColor(QPalette.ButtonText, Qt.white)
                palette.setColor(QPalette.BrightText, Qt.red)
                palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
                palette.setColor(QPalette.HighlightedText, Qt.white)
            else:
                palette = app.style().standardPalette()

            app.setPalette(palette)

            # 2. Apply the .qss stylesheet from resources
            qss_path = f':/assets/themes/{theme_name}.qss'
            file = QFile(qss_path)
            if not file.exists():
                raise FileNotFoundError(f"Theme file not found: {qss_path}")

            if file.open(QFile.ReadOnly | QFile.Text):
                stream = QTextStream(file)
                qss = stream.readAll()
                self.setStyleSheet(qss)
                file.close()
                self.settings.setValue('theme', theme_name)
                print(f"Applied {theme_name} theme successfully.")
            else:
                raise IOError("Could not open theme file")

        except Exception as e:
            print(f"Failed to apply {theme_name} theme: {e}")

    def toggle_theme(self):
        current = self.settings.value('theme', 'dark_theme')
        new_theme = 'light_theme' if current == 'dark_theme' else 'dark_theme'
        self.apply_theme(new_theme)

    def update_time(self):
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.status.showMessage(f'Ready | {now}')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.add_input_file(file_path)

    def add_input_file(self, path):
        if path not in self.input_files:
            self.input_files.append(path)
            self.file_list.addItem(path)

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Select Input Files')
        if files:
            for f in files:
                self.add_input_file(f)

    def clear_files(self):
        self.input_files = []
        self.file_list.clear()
        self.log_box.clear()

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Output Folder')
        if folder:
            self.output_folder = folder
            self.output_label.setText(f'Output Folder: {folder}')
            self.settings.setValue('output_folder', folder)

    def select_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Locate ffmpeg executable')
        if path:
            self.ffmpeg_path = path
            self.ffmpeg_label.setText(f'ffmpeg: {self.ffmpeg_path}')
            self.settings.setValue('ffmpeg_path', self.ffmpeg_path)

    def select_watch_folder(self):
        if not WATCHDOG_AVAILABLE:
            QMessageBox.warning(self, 'Watchdog missing', 'watchdog library is not installed. Run `pip install watchdog` to enable folder watching.')
            return
        folder = QFileDialog.getExistingDirectory(self, 'Select Folder to Watch')
        if folder:
            self.watch_label.setText(f'Watch: {folder}')
            self.settings.setValue('watch_folder', folder)
            # Start observer
            if self.watch_observer:
                self.watch_observer.stop()
                self.watch_observer.join()
            handler = FolderWatchHandler(self.watch_queue)
            observer = Observer()
            observer.schedule(handler, folder, recursive=False)
            observer.start()
            self.watch_observer = observer

    def _poll_watch_queue(self):
        try:
            while True:
                path = self.watch_queue.get_nowait()
                if os.path.isfile(path):
                    self.add_input_file(path)
                    self.log_box.append(f'Auto-added: {path}')
        except Exception:
            pass

    def save_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Logs', 'ffx_pro_logs.txt', 'Text Files (*.txt)')
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(self.log_box.toPlainText())
                QMessageBox.information(self, 'Saved', f'Logs saved to {path}')
            except Exception as e:
                QMessageBox.warning(self, 'Error', f'Could not save logs: {e}')

    def start_conversion(self):
        if not self.input_files:
            QMessageBox.warning(self, 'Error', 'No input files selected.')
            return
        if not self.output_folder:
            QMessageBox.warning(self, 'Error', 'No output folder selected.')
            return
        if not self.ffmpeg_path:
            QMessageBox.warning(self, 'Error', 'ffmpeg not set. Please set ffmpeg path or add ffmpeg to PATH.')
            return

        output_format = self.format_combo.currentText()
        quality = self.quality_combo.currentText()
        custom_name = self.custom_name_input.text().strip()
        enhancement_mode = self.enhance_combo.currentText()
        keep_meta = self.keep_meta_chk.isChecked()
        separate_stems = self.sep_stems_chk.isChecked()

        # Save settings
        self.settings.setValue('last_format', output_format)
        self.settings.setValue('last_quality', quality)
        self.settings.setValue('last_enhance', enhancement_mode)
        self.settings.setValue('ffmpeg_path', self.ffmpeg_path)
        self.settings.setValue('output_folder', self.output_folder)

        self.progress_bar.setValue(0)
        self.log_box.append('Starting conversion...')

        self.converter_thread = ConverterThread(
            self.ffmpeg_path, self.input_files, self.output_folder, output_format, custom_name, quality, enhancement_mode, keep_meta, separate_stems
        )
        self.converter_thread.progress.connect(self.update_progress)
        self.converter_thread.finished.connect(self.conversion_finished)
        self.converter_thread.log_signal.connect(self.update_logs)
        self.converter_thread.start()

    def stop_conversion(self):
        if self.converter_thread and self.converter_thread.isRunning():
            self.converter_thread.stop()
            self.log_box.append('Stop requested...')

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_logs(self, log_line):
        self.log_box.append(log_line)

    def conversion_finished(self, success, message):
        QMessageBox.information(self, 'Status', message)
        self.progress_bar.setValue(100 if success else 0)

    def closeEvent(self, event):
        # stop observer
        try:
            if self.watch_observer:
                self.watch_observer.stop()
                self.watch_observer.join(timeout=1)
        except Exception:
            pass
        # save settings
        self.save_settings()
        super().closeEvent(event)

    def save_settings(self):
        self.settings.setValue('ffmpeg_path', self.ffmpeg_path)
        self.settings.setValue('output_folder', self.output_folder or '')
        self.settings.setValue('last_format', self.format_combo.currentText())
        self.settings.setValue('last_quality', self.quality_combo.currentText())
        self.settings.setValue('last_enhance', self.enhance_combo.currentText())

    def load_settings(self):
        ff = self.settings.value('ffmpeg_path', '')
        out = self.settings.value('output_folder', '')
        fmt = self.settings.value('last_format', '')
        q = self.settings.value('last_quality', '')
        enh = self.settings.value('last_enhance', '')
        watch = self.settings.value('watch_folder', '')

        if ff:
            self.ffmpeg_path = ff
            self.ffmpeg_label.setText(f'ffmpeg: {self.ffmpeg_path}')
        if out:
            self.output_folder = out
            self.output_label.setText(f'Output Folder: {out}')
        if fmt and fmt in [self.format_combo.itemText(i) for i in range(self.format_combo.count())]:
            self.format_combo.setCurrentText(fmt)
        if q and q in [self.quality_combo.itemText(i) for i in range(self.quality_combo.count())]:
            self.quality_combo.setCurrentText(q)
        if enh:
            self.enhance_combo.setCurrentText(enh)
        if watch and WATCHDOG_AVAILABLE:
            # try to auto-start watching
            try:
                handler = FolderWatchHandler(self.watch_queue)
                observer = Observer()
                observer.schedule(handler, watch, recursive=False)
                observer.start()
                self.watch_observer = observer
                self.watch_label.setText(f'Watch: {watch}')
            except Exception:
                pass