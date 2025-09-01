import sys
import queue
import threading
import os
import traceback
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QPixmap, QColor, QPainter, QBrush
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QTextEdit, QHBoxLayout, QGraphicsBlurEffect, QSizePolicy,
    QSlider, QFrame, QComboBox  # 添加 QComboBox 组件用于文件夹选择
)

# ---- 事件处理信号类 ----
class EventHandler(QObject):
    status_update = pyqtSignal(str)
    enable_descent = pyqtSignal(object)  # 允许携带 True/False
    announcement = pyqtSignal(str)
    error = pyqtSignal(str)
    log_event = pyqtSignal(str)


# ---- 后端线程包装：把后端的 PyQt 信号转发到前端队列 ----
class FlightAnnouncerThread(threading.Thread):
    def __init__(self, event_queue):
        super().__init__()
        self.event_queue = event_queue
        self.daemon = True
        import flight_announcer
        self.announcer = flight_announcer.FlightAnnouncer()

        # 把后端的 event_signal 连接到队列（关键修复点）
        self.announcer.event_signal.connect(self._on_backend_event)

    def _on_backend_event(self, event_type, data):
        # 统一放入前端队列，供 UI 线程拉取
        self.event_queue.put((event_type, data))

    def run(self):
        try:
            self.announcer.start_detection()
        except Exception as e:
            self.event_queue.put(("error", f"线程异常: {e}"))
            traceback.print_exc()
        finally:
            try:
                import pyuipc
                pyuipc.close()
            except Exception:
                pass


# ---- UI按钮，带动画 ----
class GlassButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setFont(QFont("Segoe UI", 12, weight=QFont.Bold))
        self.setStyleSheet(self._normal_style())
        self.setCursor(Qt.PointingHandCursor)

        self.anim_scale = QPropertyAnimation(self, b"geometry")
        self.anim_scale.setDuration(200)
        self.anim_scale.setEasingCurve(QEasingCurve.OutBack)

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style())
        rect = self.geometry()
        self.anim_scale.stop()
        self.anim_scale.setStartValue(rect)
        self.anim_scale.setEndValue(rect.adjusted(-5, -3, 5, 3))
        self.anim_scale.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._normal_style())
        rect = self.geometry()
        self.anim_scale.stop()
        self.anim_scale.setStartValue(rect)
        self.anim_scale.setEndValue(rect.adjusted(5, 3, -5, -3))
        self.anim_scale.start()
        super().leaveEvent(event)

    def _normal_style(self):
        return """
            QPushButton {
                background-color: rgba(50, 150, 255, 180);
                border-radius: 10px;
                color: white;
                border: 2px solid rgba(255, 255, 255, 0.5);
                padding: 8px 20px;
            }
        """

    def _hover_style(self):
        return """
            QPushButton {
                background-color: rgba(50, 150, 255, 255);
                border-radius: 12px;
                color: white;
                border: 2px solid rgba(255, 255, 255, 0.9);
                padding: 8px 20px;
            }
        """


# ---- 主窗口 ----
class GlassWindow(QWidget):
    def __init__(self):
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        self.base_path = base_path

        super().__init__()
        self.setWindowTitle("客舱语音系统")
        self.resize(520, 440)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self.event_queue = queue.Queue()
        self.event_handler = EventHandler()

        self._init_ui()
        self._connect_signals()

        # 启动后端线程
        self.announcer_thread = FlightAnnouncerThread(self.event_queue)
        self.announcer_thread.start()

        # 定时器处理事件队列
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_event_queue)
        self.timer.start(100)

        # 拖动支持
        self._offset = None

    def _init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        self.setLayout(main_layout)

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("""
            background: rgba(40, 50, 60, 220);
            border-radius: 20px;
        """)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(1.5)
        self.content_widget.setGraphicsEffect(blur)

        content_layout = QVBoxLayout()
        content_layout.setSpacing(15)
        content_layout.setContentsMargins(30, 30, 30, 30)
        self.content_widget.setLayout(content_layout)
        main_layout.addWidget(self.content_widget)

        # Logo
        self.logo_label = QLabel()
        self.logo_label.setFixedHeight(80)
        self.logo_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.logo_label.setAlignment(Qt.AlignCenter)
        try:
            possible_exts = ['png', 'jpg', 'jpeg']
            logo_path = None
            sounds_path = os.path.join(self.base_path, 'sounds')
            for ext in possible_exts:
                candidate = os.path.join(sounds_path, f'logo.{ext}')
                if os.path.exists(candidate):
                    logo_path = candidate
                    break
            if not logo_path:
                logo_path = os.path.join(self.base_path, 'assets', 'airline_logo.png')
            pix = QPixmap(logo_path)
            if not pix.isNull():
                self.logo_label.setPixmap(pix.scaledToHeight(80, Qt.SmoothTransformation))
        except Exception as e:
            print(f"无法加载logo: {str(e)}")
        content_layout.addWidget(self.logo_label)

        # 标题与状态
        self.title = QLabel("客舱语音系统")
        self.title.setStyleSheet("color: #a9d1ff; font-size: 24px; font-weight: 700;")
        self.title.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(self.title)

        self.status_label = QLabel("系统准备就绪")
        self.status_label.setStyleSheet("color: #7ec8ff; font-size: 14px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(self.status_label)

        # 按钮区（两行：核心流程 + 自定义）
        core_btns = QHBoxLayout()
        self.start_btn = GlassButton("开始登机")
        self.cruise_btn = GlassButton("巡航")          # 新增：巡航
        self.descent_btn = GlassButton("准备下高")

        # 初始禁用巡航与下高（待后端允许）
        self.cruise_btn.setEnabled(False)
        self.descent_btn.setEnabled(False)

        core_btns.addWidget(self.start_btn)
        core_btns.addWidget(self.cruise_btn)
        core_btns.addWidget(self.descent_btn)
        content_layout.addLayout(core_btns)

        # 语音文件夹选择
        self.folder_selector = QComboBox()
        self.folder_selector.currentTextChanged.connect(self.on_folder_selected)
        content_layout.addWidget(self.folder_selector)

        # 加载文件夹
        self.load_folders()

        # 音量控制
        volume_frame = QFrame()
        volume_frame.setStyleSheet("background: transparent;")
        volume_layout = QHBoxLayout(volume_frame)
        volume_layout.setContentsMargins(10, 5, 10, 5)

        volume_label = QLabel("音量:")
        volume_label.setStyleSheet("color: #c2e0ff; font-size: 14px;")
        volume_layout.addWidget(volume_label)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setStyleSheet("""
            QSlider { background: transparent; }
            QSlider::groove:horizontal {
                background: rgba(100, 100, 150, 100);
                height: 8px; border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4a9bff;
                width: 16px; height: 16px; margin: -4px 0; border-radius: 8px;
            }
            QSlider::sub-page:horizontal { background: #4a9bff; border-radius: 4px; }
        """)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        volume_layout.addWidget(self.volume_slider, 1)

        self.volume_value = QLabel("80%")
        self.volume_value.setStyleSheet("color: #c2e0ff; font-size: 14px; min-width: 40px;")
        volume_layout.addWidget(self.volume_value)

        content_layout.addWidget(volume_frame)

        # 日志
        self.event_log = QTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setStyleSheet("""
            background: rgba(0, 0, 0, 50);
            color: #a6c8ff;
            border-radius: 10px;
            font-family: Consolas, monospace;
            font-size: 13px;
        """)
        content_layout.addWidget(self.event_log)

    def _connect_signals(self):
        # 核心流程
        self.start_btn.clicked.connect(self.on_start_boarding)
        self.cruise_btn.clicked.connect(self.on_trigger_cruise)          # 新增：巡航绑定
        self.descent_btn.clicked.connect(self.on_prepare_descent)

        # 后端事件
        self.event_handler.status_update.connect(self.update_status)
        self.event_handler.enable_descent.connect(self.on_enable_descent)
        self.event_handler.announcement.connect(self.handle_announcement)
        self.event_handler.error.connect(self.show_error)
        self.event_handler.log_event.connect(self.append_event)

    def load_folders(self):
        """动态加载 sounds 目录下的文件夹并显示在下拉框中"""
        sounds_path = os.path.join(self.base_path, "sounds")
        try:
            for folder in os.listdir(sounds_path):
                folder_path = os.path.join(sounds_path, folder)
                if os.path.isdir(folder_path):
                    self.folder_selector.addItem(folder)  # 将文件夹名称添加到下拉框
        except Exception as e:
            print(f"加载文件夹失败: {str(e)}")
            self.append_event(f"加载文件夹失败: {str(e)}")

    def on_folder_selected(self, folder_name):
        """当用户选择新的语音文件夹时"""
        try:
            if hasattr(self, 'announcer_thread') and self.announcer_thread is not None:
                self.announcer_thread.announcer.switch_sound_folder(folder_name)
        except Exception as e:
            print(f"切换语音文件夹失败: {str(e)}")
            self.append_event(f"切换语音文件夹失败: {str(e)}")

    # 音量
    def on_volume_changed(self, value):
        self.volume_value.setText(f"{value}%")
        volume = value / 100.0
        try:
            self.announcer_thread.announcer.set_volume(volume)
        except Exception as e:
            self.append_event(f"设置音量失败: {str(e)}")

    # 事件队列轮询（由后端 event_signal 转过来）
    def process_event_queue(self):
        try:
            while not self.event_queue.empty():
                evt_type, data = self.event_queue.get_nowait()
                if evt_type == "status":
                    self.event_handler.status_update.emit(data)
                elif evt_type == "enable_descent":
                    # 后端 climb->takeoff 后会发 True
                    self.event_handler.enable_descent.emit(data)
                elif evt_type == "announcement":
                    self.event_handler.announcement.emit(data)
                elif evt_type == "error":
                    self.event_handler.error.emit(data)
                elif evt_type == "log":
                    self.event_handler.log_event.emit(data)
        except queue.Empty:
            pass

    # ---- 信号槽 ----
    def update_status(self, text):
        self.status_label.setText(text)

    def on_enable_descent(self, _flag=True):
        # 同时开放“巡航”和“准备下高”
        self.cruise_btn.setEnabled(True)
        self.descent_btn.setEnabled(True)
        self.append_event("后端允许：已解锁“巡航/下高”按钮")

    def handle_announcement(self, event_name):
        self.append_event(f"广播事件触发: {event_name}")

    def show_error(self, message):
        self.append_event(f"错误: {message}")

    def append_event(self, text):
        now = datetime.now().strftime("%H:%M:%S")
        self.event_log.append(f"[{now}] {text}")

    # ---- 按钮事件 ----
    def on_start_boarding(self):
        self.status_label.setText("登机流程启动")
        self.start_btn.setEnabled(False)
        self.append_event("开始登机")
        try:
            self.announcer_thread.announcer.start_boarding()
        except Exception as e:
            self.append_event(f"启动登机失败: {str(e)}")

    def on_trigger_cruise(self):
        self.append_event("手动触发：巡航")
        try:
            self.announcer_thread.announcer.trigger_cruise()
        except Exception as e:
            self.append_event(f"触发巡航失败: {str(e)}")

    def on_prepare_descent(self):
        self.status_label.setText("准备下高")
        self.append_event("准备下高")
        try:
            self.announcer_thread.announcer.prepare_descent()
        except Exception as e:
            self.append_event(f"准备下高失败: {str(e)}")

    # 自定义按钮示例（可按需改成你自己的后端方法/音频）
    def on_custom_a(self):
        # 示例：直接让后端播“安全须知”
        try:
            am = self.announcer_thread.announcer.audio_manager
            path = self.announcer_thread.announcer.sound_files.get("safety_briefing")
            ok = am.play_voice(path) if path else False
            if ok:
                self.append_event("自定义A：播放安全须知")
            else:
                self.append_event("自定义A：播放失败（找不到或无法播放）")
        except Exception as e:
            self.append_event(f"自定义A失败: {str(e)}")

    def on_custom_b(self):
        # 示例：直接让后端播“到达”
        try:
            am = self.announcer_thread.announcer.audio_manager
            path = self.announcer_thread.announcer.sound_files.get("arrival")
            ok = am.play_voice(path) if path else False
            if ok:
                self.append_event("自定义B：播放到达提示")
            else:
                self.append_event("自定义B：播放失败（找不到或无法播放）")
        except Exception as e:
            self.append_event(f"自定义B失败: {str(e)}")

    # ---- 拖动窗口 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._offset = event.pos()

    def mouseMoveEvent(self, event):
        if self._offset is not None and event.buttons() == Qt.LeftButton:
            self.move(self.pos() + event.pos() - self._offset)

    def mouseReleaseEvent(self, event):
        self._offset = None

    # ---- 自定义绘制圆角半透明背景 ----
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        brush = QBrush(QColor(30, 40, 50, 190))
        painter.setBrush(brush)
        painter.setPen(Qt.NoPen)
        rect = self.rect()
        painter.drawRoundedRect(rect, 20, 20)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = GlassWindow()
    win.show()
    sys.exit(app.exec())
