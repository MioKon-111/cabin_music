import pyuipc
import time
import pygame
import threading
import tkinter as tk
from collections import deque
from tkinter import messagebox
import os


class CabinAnnouncementSystem:
    def __init__(self):
        # 初始化pygame音频系统
        pygame.mixer.init()

        # 偏移量定义 - 完全按照您提供的格式
        self.offsets = [
            (0x0D0C, 'H'),  # 灯光位图 (2字节无符号)
            (0x02B8, 'H'),  # 真空速 (TAS) (2字节无符号)
            (0x3324, 'L'),  # 高度（真实压力高度）(4字节无符号)
            # 其他偏移量将在需要时添加
        ]

        # 状态跟踪
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

        # 语音队列
        self.audio_queue = deque(maxlen=5)
        self.currently_playing = False
        self.background_music = None
        self.background_volume = 1.0

        # 语音文件路径 - 使用MP3格式
        self.sound_files = {
            "boarding_music": "sounds/boarding_music.mp3",
            "safety_briefing": "sounds/safety_briefing.mp3",
            "taxi_check": "sounds/taxi_check.mp3",
            "takeoff": "sounds/takeoff.mp3",
            "climb": "sounds/climb.mp3",
            "cruise": "sounds/cruise.mp3",
            "descent": "sounds/descent.mp3",
            "landing": "sounds/landing.mp3",
            "arrival": "sounds/arrival.mp3",
            "deboarding": "sounds/deboarding.mp3",
        }

        # 验证所有音频文件是否存在
        self._verify_audio_files()

        # 创建GUI
        self.root = tk.Tk()
        self.root.title("客舱语音系统")
        self.root.geometry("400x300")

        # 开始按钮
        self.start_button = tk.Button(
            self.root, text="开始登机",
            command=self.start_boarding,
            font=("Arial", 14), height=2, width=15
        )
        self.start_button.pack(pady=10)

        # 下高按钮
        self.descent_button = tk.Button(
            self.root, text="准备下高",
            command=self.prepare_descent,
            font=("Arial", 14), height=2, width=15,
            state=tk.DISABLED
        )
        self.descent_button.pack(pady=10)

        # 状态标签
        self.status_label = tk.Label(
            self.root, text="系统准备就绪",
            font=("Arial", 12), fg="blue"
        )
        self.status_label.pack(pady=10)

        # 退出按钮
        self.exit_button = tk.Button(
            self.root, text="退出系统",
            command=self.exit_system,
            font=("Arial", 12), height=1, width=10
        )
        self.exit_button.pack(pady=10)

        # 连接FSUIPC
        try:
            pyuipc.open(0)
            print("已成功连接到FSUIPC")
            self.status_label.config(text="已连接FSUIPC", fg="green")
        except Exception as e:
            print(f"连接FSUIPC失败: {e}")
            self.status_label.config(text="FSUIPC连接失败", fg="red")
            messagebox.showerror("连接错误", "无法连接到FSUIPC，请确保MSFS和FSUIPC7正在运行")

    def _verify_audio_files(self):
        """验证所有音频文件是否存在"""
        missing_files = []
        for key, file_path in self.sound_files.items():
            if not os.path.exists(file_path):
                missing_files.append(file_path)

        if missing_files:
            messagebox.showwarning(
                "缺少音频文件",
                f"以下音频文件不存在:\n\n" + "\n".join(missing_files)
            )

    def start_boarding(self):
        """开始登机流程"""
        self.start_button.config(state=tk.DISABLED)
        self.status_label.config(text="登机中...", fg="purple")

        # 播放登机音乐
        self._play_background_music(self.sound_files["boarding_music"])

        # 开始状态检测
        threading.Thread(target=self.detect_state, daemon=True).start()

    def prepare_descent(self):
        """准备下高"""
        self.states["descent_button_pressed"] = True
        self.descent_button.config(state=tk.DISABLED)
        self.status_label.config(text="准备下高...", fg="orange")
        self._trigger_announcement("descent")

    def exit_system(self):
        """退出系统"""
        self.root.destroy()
        pygame.mixer.quit()
        pyuipc.close()

    def _play_background_music(self, file):
        """播放背景音乐"""
        try:
            # 停止任何正在播放的背景音乐
            if self.background_music:
                pygame.mixer.music.stop()

            # 加载并播放背景音乐
            pygame.mixer.music.load(file)
            pygame.mixer.music.play(-1)  # 循环播放
            pygame.mixer.music.set_volume(self.background_volume)
            self.background_music = file
            self.states["boarding_music_playing"] = True
            print(f"开始播放背景音乐: {file}")
        except Exception as e:
            print(f"播放背景音乐失败: {e}")
            messagebox.showerror("音频错误", f"无法播放背景音乐: {e}")

    def _adjust_background_volume(self, volume):
        """调整背景音乐音量"""
        if self.states["boarding_music_playing"]:
            pygame.mixer.music.set_volume(volume)
            self.background_volume = volume

    def _play_sound_thread(self, file):
        """在单独的线程中播放音频"""
        try:
            # 降低背景音乐音量
            self._adjust_background_volume(0.2)

            # 播放语音
            sound = pygame.mixer.Sound(file)
            channel = sound.play()

            # 等待播放完成
            while channel and channel.get_busy():
                time.sleep(0.1)
        except Exception as e:
            print(f"播放音频失败: {e}")
            messagebox.showerror("音频错误", f"无法播放语音: {e}")
        finally:
            # 恢复背景音乐音量
            self._adjust_background_volume(1.0)
            self.currently_playing = False

            # 检查队列中是否有待播放的音频
            if self.audio_queue:
                next_file = self.audio_queue.popleft()
                self._play_sound(next_file)

    def _play_sound(self, file):
        """播放音频文件，加入队列或直接播放"""
        if self.currently_playing:
            # 如果正在播放，加入队列
            self.audio_queue.append(file)
            print(f"语音加入队列: {file}")
        else:
            # 直接播放
            self.currently_playing = True
            threading.Thread(target=self._play_sound_thread, args=(file,), daemon=True).start()
            print(f"开始播放语音: {file}")

    def _trigger_announcement(self, event):
        """触发客舱广播"""
        if event in self.sound_files:
            print(f"触发广播: {event}")
            self._play_sound(self.sound_files[event])

    def detect_state(self):
        """检测飞机状态并触发相应广播"""
        try:
            print("客舱语音系统已启动，等待飞行数据...")

            while True:
                try:
                    # 读取所有数据
                    data = pyuipc.read(self.offsets)
                    light_bits, tas_raw, alt_raw = data

                    # 计算实际值
                    tas_knots = tas_raw / 128.0
                    altitude_ft = alt_raw / 256.0

                    # 判断灯光状态
                    beacon_light = bool(light_bits & 0x0002)  # 防撞灯
                    taxi_light = bool(light_bits & 0x0008)  # 滑行灯
                    landing_light = bool(light_bits & 0x0004 or light_bits & 0x0008)  # 着陆灯

                    # 简化版地面检测（高度<50英尺）
                    on_ground = altitude_ft < 50

                    # 更新状态显示
                    status_text = f"高度: {altitude_ft:.0f} ft | 空速: {tas_knots:.0f} kt"
                    self.status_label.config(text=status_text)

                    # 1. 防撞灯打开后播放安全须知
                    if beacon_light and not self.states["beacon_light"]:
                        self._trigger_announcement("safety_briefing")
                        self.states["beacon_light"] = True

                    # 2. 滑行灯打开并开始滑出
                    if taxi_light and tas_knots > 5 and not self.states["taxi_light"]:
                        self._trigger_announcement("taxi_check")
                        self.states["taxi_light"] = True

                    # 3. 着陆灯打开并在地面上时播放起飞语音
                    if landing_light and on_ground and not self.states["takeoff_detected"]:
                        self._trigger_announcement("takeoff")
                        self.states["takeoff_detected"] = True

                    # 4. 起飞后着陆灯关闭播放正在关键爬升阶段
                    if (not landing_light and self.states["takeoff_detected"] and
                            not self.states["climb_detected"] and altitude_ft > 1000):
                        self._trigger_announcement("climb")
                        self.states["climb_detected"] = True
                        # 启用下高按钮
                        self.descent_button.config(state=tk.NORMAL)

                    # 5. 巡航阶段（高度无明显变化）
                    if (self.states["climb_detected"] and
                            not self.states["cruise_detected"] and
                            abs(altitude_ft - self.states["last_altitude"]) < 50 and
                            abs(tas_knots - self.states["last_tas"]) < 10):
                        self._trigger_announcement("cruise")
                        self.states["cruise_detected"] = True

                    # 6. 下高按钮按下后播放准备下高语音
                    # (在prepare_descent方法中处理)

                    # 7. 当着陆灯、滑行灯再次打开且飞机在下降
                    if (landing_light and taxi_light and
                            altitude_ft < self.states["last_altitude"] and
                            not self.states["landing_detected"]):
                        self._trigger_announcement("landing")
                        self.states["landing_detected"] = True

                    # 8. 在地面上关闭着陆灯时播放已经到达
                    if (on_ground and not landing_light and
                            self.states["landing_detected"] and
                            not self.states["arrival_detected"]):
                        self._trigger_announcement("arrival")
                        self.states["arrival_detected"] = True

                    # 9. 空速归0且防撞灯关闭时播放有序下机
                    if (tas_knots < 5 and not beacon_light and
                            self.states["arrival_detected"] and
                            not self.states["deboarding_detected"]):
                        self._trigger_announcement("deboarding")
                        self.states["deboarding_detected"] = True
                        # 停止背景音乐
                        pygame.mixer.music.stop()
                        self.states["boarding_music_playing"] = False

                    # 保存当前状态用于下次比较
                    self.states["last_altitude"] = altitude_ft
                    self.states["last_tas"] = tas_knots

                    time.sleep(0.5)  # 更新频率

                except pyuipc.FSUIPCException as e:
                    print(f"读取数据错误: {e}")
                    time.sleep(2)  # 等待后重试
                except Exception as e:
                    print(f"检测状态错误: {e}")
                    time.sleep(1)

        except Exception as e:
            print(f"状态检测线程错误: {e}")

    def run(self):
        """运行主循环"""
        self.root.mainloop()


if __name__ == "__main__":
    system = CabinAnnouncementSystem()
    system.run()