import pyuipc
import time
import threading
import sys
import os
import pygame
import random
from collections import deque
from PyQt5.QtCore import QObject, pyqtSignal
from audio_manager import AudioManager  # 新增的音频管理器


class FlightAnnouncer(QObject):
    event_signal = pyqtSignal(str, object)  # (event_type, data)

    def __init__(self):
        super().__init__()
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        self.base_path = base_path
        print(f"[FlightAnnouncer] Base path: {self.base_path}")

        self._stop_flag = threading.Event()

        # 偏移量定义
        self.offsets = [
            (0x0D0C, 'H'),  # 灯光位图
            (0x02B8, 'H'),  # 真空速 (TAS)
            (0x05C0, 'l'),  # 高度（真实压力高度）
            (0x341D, 'b'),  # 安全带灯状态
        ]

        self.states = {
            "boarding_music_playing": False,
            "beacon_light": False,
            "taxi_light": False,
            "landing_light": False,
            "on_ground": True,
            "takeoff_detected": False,
            "climb_detected": False,
            "cruise_detected": False,
            "descent_detected": False,
            "landing_detected": False,
            "arrival_detected": False,
            "deboarding_detected": False,
            "last_altitude": 0,
            "last_tas": 0,
            "descent_button_pressed": False,
        }

        # 状态机
        self.phase = "boarding"   # boarding -> briefing -> taxi -> takeoff -> climb -> cruise -> descent -> approach -> landing_roll -> shutdown -> deboarding
        self.manual_cruise_request = False

        self.audio_queue = deque(maxlen=5)
        self.currently_playing = False

        self.audio_manager = AudioManager()

        # 音频包（可切换的文件夹）
        self.sound_files = {}
        self.current_folder = "CES"  # 默认加载 CES
        self.load_sound_folder(self.current_folder)

        # 语音间隔控制（防止“连珠炮”）
        self.min_gap_sec = 5.0           # 两段播报之间的基础静默秒数
        self.gap_jitter_sec = 2.0        # 随机抖动（-jitter ~ +jitter）
        self.next_allowed_play_ts = 0.0  # 下一次允许播放的时间戳

        # 登机音乐淡出时长
        self.boarding_fade_ms = 1800

        # 初始化 pygame mixer（防止多次 init 出错）
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception:
            # 不让异常影响主流程
            pass

    # =============== 外部控制 API（前端会调用的） ===============

    def set_volume(self, volume: float):
        """
        设置全局音量（0.0 ~ 1.0），同步到 AudioManager 和 登机音乐（pygame.mixer.music）。
        """
        try:
            # 同步给 AudioManager（若其实现了全局音量）
            if hasattr(self.audio_manager, "set_global_volume"):
                self.audio_manager.set_global_volume(volume)
            # 同步给登机音乐
            try:
                pygame.mixer.music.set_volume(max(0.0, min(1.0, float(volume))))
            except Exception:
                pass
            self.event_signal.emit("log", f"音量设置为: {volume * 100:.0f}%")
        except Exception as e:
            self.event_signal.emit("error", f"设置音量失败: {e}")

    def trigger_cruise(self):
        """
        手动请求进入巡航（在 climb 阶段会优先响应）。
        """
        self.manual_cruise_request = True
        self.event_signal.emit("log", "收到手动巡航指令")

    def start_boarding(self):
        """
        播放登机音乐（只播一遍，不循环）。
        """
        path = self._resolve_sound("boarding_music")
        if not path:
            self.event_signal.emit("error", "未找到登机音乐文件（ogg/wav/mp3）")
            return

        try:
            # 只播一遍
            pygame.mixer.music.load(path)
            # 如果 AudioManager 有全局音量，就用它；否则 1.0
            gv = 1.0
            if hasattr(self.audio_manager, "get_global_volume"):
                try:
                    gv = float(self.audio_manager.get_global_volume())
                except Exception:
                    gv = 1.0
            pygame.mixer.music.set_volume(gv)
            pygame.mixer.music.play(loops=0)
            self.states["boarding_music_playing"] = True
            self.event_signal.emit("status", "登机中...")
        except Exception as e:
            self.event_signal.emit("error", f"无法播放登机音乐: {e}")

    def prepare_descent(self):
        """
        前端“准备下高”按钮调用：只置位，由状态机完成阶段切换。
        """
        self.states["descent_button_pressed"] = True
        # 播放“descent”语音
        path = self._resolve_sound("descent")
        if path and self._play_voice_with_gap(path):
            self.event_signal.emit("status", "准备下高中...")
        else:
            self.event_signal.emit("error", "无法播放下高广播")

    def switch_sound_folder(self, folder_name):
        """切换到指定的语音文件夹"""
        self.load_sound_folder(folder_name)

    # =============== 内部工具 ===============

    def load_sound_folder(self, folder_name):
        """
        加载指定的语音文件夹：
        - 支持 mp3/ogg/wav
        - 以“文件名（不含扩展名）”作为键，例如 boarding_music / safety_briefing 等
        """
        folder_path = os.path.join(self.base_path, "sounds", folder_name)

        if not os.path.exists(folder_path):
            self.event_signal.emit("error", f"文件夹 {folder_name} 不存在!")
            return

        self.sound_files.clear()
        try:
            for filename in os.listdir(folder_path):
                if filename.lower().endswith((".mp3", ".ogg", ".wav")):
                    sound_name = os.path.splitext(filename)[0]
                    self.sound_files[sound_name] = os.path.join(folder_path, filename)

            self.current_folder = folder_name
            self.event_signal.emit("status", f"已加载 {folder_name} 语音包")
        except Exception as e:
            self.event_signal.emit("error", f"加载语音文件夹失败: {e}")

    def _resolve_sound(self, basename):
        """
        在当前 sound_files 表中查找 basename 对应的文件路径。
        """
        return self.sound_files.get(basename)

    def _fadeout_boarding_music_if_playing(self):
        """
        若登机音乐仍在播，进入下一阶段/有高优先级语音时，平滑淡出。
        """
        if self.states.get("boarding_music_playing"):
            try:
                pygame.mixer.music.fadeout(self.boarding_fade_ms)
            except Exception:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
            finally:
                self.states["boarding_music_playing"] = False

    def _play_voice_with_gap(self, path: str) -> bool:
        """
        执行“带间隔”的语音播报：
        - 确保与上一条语音间隔 >= min_gap_sec +/- jitter
        - 播放前会淡出登机音乐（若还在放）
        """
        # 先让登机音乐淡出（紧急优先级）
        self._fadeout_boarding_music_if_playing()

        now = time.time()
        if now < self.next_allowed_play_ts:
            remain = max(0.0, self.next_allowed_play_ts - now)
            # 为了不阻塞太久，最多等 2 秒；如果间隔更长，分片等待
            waited = 0.0
            while waited < min(remain, 2.0) and not self._stop_flag.is_set():
                time.sleep(0.05)
                waited += 0.05

        ok = self.audio_manager.play_voice(path)
        if ok:
            # 计算下一次允许播放的时间（带随机抖动）
            jitter = random.uniform(-self.gap_jitter_sec, self.gap_jitter_sec)
            self.next_allowed_play_ts = time.time() + max(0.0, self.min_gap_sec + jitter)
        return ok

    # =============== 主循环 ===============

    def detect_state(self):
        print("客舱语音系统已启动，等待飞行数据...")
        self.event_signal.emit("status", "等待飞行数据...")

        try:
            pyuipc.open(0)
            self.fsuipc_connected = True
            print("已成功连接到FSUIPC")
            self.event_signal.emit("status", "已连接FSUIPC")
        except Exception as e:
            print(f"连接FSUIPC失败: {e}")
            self.event_signal.emit("error", f"无法连接到FSUIPC: {e}")
            return

        def _play_once_by_key(key: str) -> bool:
            """
            根据 key 找到音频并使用“带间隔”的方式播放一次。
            播放前会自动淡出登机音乐。
            """
            path = self._resolve_sound(key)
            if not path:
                self.event_signal.emit("error", f"未找到音频: {key}")
                return False
            ok = self._play_voice_with_gap(path)
            if not ok:
                self.event_signal.emit("error", f"无法播放音频: {key}")
            return ok

        while not self._stop_flag.is_set():
            try:
                light_bits, tas_raw, alt_raw, seatbelt_raw = pyuipc.read(self.offsets)

                # 灯光 & 空速
                nav_light     = bool(light_bits & 0x0001)
                beacon_light  = bool(light_bits & 0x0002)                    # 防撞
                landing_light = bool(light_bits & 0x0004 or light_bits & 0x0008)  # 着陆或机鼻
                taxi_light    = bool(light_bits & 0x0008)                    # 机鼻
                tas_knots     = tas_raw / 128.0

                # 高度（仅显示）
                altitude_ft   = alt_raw / 256.0
                seatbelt_sign = bool(seatbelt_raw)

                status_text = f"阶段:{self.phase} | 高度: {altitude_ft:.0f} ft | 空速: {tas_knots:.0f} kt"
                self.event_signal.emit("status", status_text)

                # ================= 有限状态机 =================

                # boarding -> briefing（防撞灯 ON 触发安全须知）
                if self.phase == "boarding":
                    if beacon_light:
                        if _play_once_by_key("safety_briefing"):
                            self.phase = "briefing"

                # briefing -> taxi（防撞 ON + 滑行灯 ON + 速度 3~30kt）
                elif self.phase == "briefing":
                    if beacon_light and taxi_light and 3 < tas_knots < 30:
                        if _play_once_by_key("taxi_check"):
                            self.phase = "taxi"

                # taxi -> takeoff（在上一条基础上再加着陆灯 ON）
                elif self.phase == "taxi":
                    if beacon_light and taxi_light and landing_light:
                        if _play_once_by_key("takeoff"):
                            self.phase = "takeoff"

                # takeoff -> climb（起飞后：着陆灯 OFF 且速度>30）
                elif self.phase == "takeoff":
                    if not landing_light and tas_knots > 30:
                        if _play_once_by_key("climb"):
                            self.phase = "climb"
                            # 允许“巡航/下高”按钮
                            self.event_signal.emit("enable_descent", True)

                # climb -> cruise（优先手动按钮；其次 seatbelt OFF）
                elif self.phase == "climb":
                    if self.manual_cruise_request or (not seatbelt_sign):
                        if _play_once_by_key("cruise"):
                            self.phase = "cruise"
                            self.manual_cruise_request = False

                # cruise -> descent（只接受“下高”按钮）
                elif self.phase == "cruise":
                    if self.states.get("descent_button_pressed"):
                        # prepare_descent 已经播放了“descent”，这里只切阶段
                        self.phase = "descent"
                        self.states["descent_button_pressed"] = False

                # descent -> approach（着陆灯 + 滑行灯都 ON 认为进近）
                elif self.phase == "descent":
                    if landing_light and taxi_light:
                        if _play_once_by_key("landing"):
                            self.phase = "approach"

                # approach -> landing_roll（速度<80 认为接地滑跑）
                elif self.phase == "approach":
                    if tas_knots < 80:
                        self.phase = "landing_roll"

                # landing_roll -> shutdown（到达阶段：着陆灯 OFF 且防撞灯仍 ON）
                elif self.phase == "landing_roll":
                    if (not landing_light) and beacon_light:
                        if _play_once_by_key("arrival"):
                            self.phase = "shutdown"

                # shutdown -> deboarding（完全停稳且防撞灯 OFF）
                elif self.phase == "shutdown":
                    if tas_knots < 3 and not beacon_light:
                        if _play_once_by_key("deboarding"):
                            self.phase = "deboarding"
                            if self.states["boarding_music_playing"]:
                                try:
                                    pygame.mixer.music.stop()
                                except Exception:
                                    pass
                                self.states["boarding_music_playing"] = False

                # 记录上一拍数据（保留）
                self.states["last_tas"] = tas_knots
                self.states["last_altitude"] = altitude_ft

                time.sleep(0.5)

            except pyuipc.FSUIPCException as e:
                print(f"读取数据错误: {e}")
                self.event_signal.emit("error", f"读取数据错误: {e}")
                self.fsuipc_connected = False
                try:
                    pyuipc.close()
                except:
                    pass
                try:
                    pyuipc.open(0)
                    self.fsuipc_connected = True
                    print("重新连接成功")
                    self.event_signal.emit("status", "重新连接成功")
                except Exception as e2:
                    print(f"重新连接失败: {e2}")
                    self.event_signal.emit("error", f"重新连接失败: {e2}")
                    time.sleep(2)

            except Exception as e:
                print(f"检测状态错误: {e}")
                self.event_signal.emit("error", f"检测状态错误: {e}")
                time.sleep(1)

        try:
            pyuipc.close()
        except:
            pass
        self.fsuipc_connected = False
        self.event_signal.emit("status", "已断开FSUIPC连接")

    # =============== 线程控制 ===============

    def start_detection(self):
        if hasattr(self, "_thread") and self._thread.is_alive():
            print("检测线程已在运行")
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self.detect_state, daemon=True)
        self._thread.start()

    def stop_detection(self):
        self._stop_flag.set()
        if hasattr(self, "_thread"):
            self._thread.join(timeout=2)
