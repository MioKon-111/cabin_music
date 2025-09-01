import pygame
import threading
import time
from collections import deque


class AudioManager:
    def __init__(self):
        pygame.mixer.init()
        self.background_volume = 1.0
        self.voice_volume = 1.0
        self.current_voice_channel = None  # 用来存放 Channel
        self.current_voice_sound = None    # 用来存放 Sound 对象
        self.fading_out = False
        self.lock = threading.Lock()

    def set_global_volume(self, volume):
        self.background_volume = volume
        self.voice_volume = volume

        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.set_volume(self.background_volume)

            if self.current_voice_channel and self.current_voice_channel.get_busy():
                self.current_voice_channel.set_volume(self.voice_volume)
        except Exception as e:
            print(f"更新音量失败: {e}")

    def play_background(self, file, loop=True):
        try:
            pygame.mixer.music.load(file)
            pygame.mixer.music.play(-1 if loop else 0)
            pygame.mixer.music.set_volume(self.background_volume)
            return True
        except Exception as e:
            print(f"播放背景音乐失败: {e}")
            return False

    def play_voice(self, file):
        with self.lock:
            if self.current_voice_channel and self.current_voice_channel.get_busy():
                self._fade_out_current_voice()

            try:
                self.current_voice_sound = pygame.mixer.Sound(file)
                self.current_voice_channel = self.current_voice_sound.play()
                if self.current_voice_channel:
                    self.current_voice_channel.set_volume(self.voice_volume)
                    return True
                else:
                    print("播放语音失败: 无法获得 Channel")
                    return False
            except Exception as e:
                print(f"播放语音失败: {e}")
                return False

    def _fade_out_current_voice(self, duration=1.0, steps=30):
        if not self.current_voice_channel or not self.current_voice_channel.get_busy():
            return
        if self.fading_out:
            return

        self.fading_out = True

        def fade_thread():
            step_volume = self.voice_volume / steps
            delay = duration / steps
            for i in range(steps):
                new_volume = max(0, self.voice_volume - step_volume * (i + 1))
                try:
                    self.current_voice_channel.set_volume(new_volume)
                except:
                    pass
                time.sleep(delay)
            try:
                self.current_voice_channel.stop()
            except:
                pass
            self.fading_out = False

        threading.Thread(target=fade_thread, daemon=True).start()
