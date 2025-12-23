import os
import tkinter as tk
from tkinter import ttk
import threading
import time
import pymem
import pymem.process
import json
from enum import Enum
import platform
import win32api
import win32con

class SoundAction(Enum):
    PLAY_PAUSE = "play_pause"
    NEXT_TRACK = "next_track"
    PREV_TRACK = "prev_track"

class MediaController:
    def __init__(self):
        self.last_action = "None"

    def send_media_key(self, action):
        try:
            self.last_action = action.value
            
            VK_MEDIA_PLAY_PAUSE = 0xB3
            VK_MEDIA_NEXT_TRACK = 0xB0
            VK_MEDIA_PREV_TRACK = 0xB1

            key_map = {
                SoundAction.PLAY_PAUSE: VK_MEDIA_PLAY_PAUSE,
                SoundAction.NEXT_TRACK: VK_MEDIA_NEXT_TRACK,
                SoundAction.PREV_TRACK: VK_MEDIA_PREV_TRACK,
            }

            if action in key_map:
                key = key_map[action]
                win32api.keybd_event(key, 0, 0, 0)
                time.sleep(0.05)
                win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
                print(f"Media key pressed: {action.value}")
                return True
                
            return False
            
        except Exception as e:
            print(f"Error: {e}")
            return False

    def get_last_action(self):
        return self.last_action

class ConfigManager:
    def __init__(self):
        self.config_file = "echo_media_settings.json"
        self.config = self.load_config()

    def get_config_path(self):
        return os.path.join(os.getcwd(), self.config_file)

    def load_config(self):
        default_config = {
            "click_patterns": {
                "prev_track": 3,
                "next_track": 4,
            },
            "hold_actions": {
                "play_pause": 3.0,
            },
            "auto_reconnect": True,
            "click_timeout": 0.8,
            "debounce_delay": 0.15,
            "detection_threshold": 0.1,
            "hold_threshold": 3.0,
        }

        config_path = self.get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                for key in default_config:
                    if key not in loaded_config:
                        loaded_config[key] = default_config[key]
                return loaded_config
            except Exception as e:
                print(f"Error: {e}")
                return default_config
        return default_config

    def save_config(self):
        try:
            config_path = self.get_config_path()
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error: {e}")
            return False

class EchoVRButtonDetector:
    BUTTON_ADDRESSES = [
        0x20C7CA8,
        0x20C7CA0, 0x20C7CB0, 0x20C7C98, 0x20C7CB8,
        0x207CA8, 0x20C7D00, 0x20C8000
    ]

    def __init__(self, media_controller, gui_update_callback=None):
        self.pm = None
        self.echo_connected = False
        self.button_address = None
        self.base_address = None

        self.last_state = 0
        self.press_start_time = 0
        self.release_time = 0
        self.last_press_time = 0
        self.last_release_time = 0
        
        self.click_count = 0
        self.click_timer = None
        self.hold_timer = None
        self.hold_detected = False
        self.detection_active = False

        self.media_controller = media_controller
        self.gui_update_callback = gui_update_callback
        self.config = ConfigManager()

        self.click_patterns = self.config.config.get("click_patterns", {})
        self.hold_thresholds = self.config.config.get("hold_actions", {})
        self.click_timeout = self.config.config.get("click_timeout", 0.8)
        self.debounce_delay = self.config.config.get("debounce_delay", 0.15)
        self.detection_threshold = self.config.config.get("detection_threshold", 0.1)
        self.hold_threshold = self.config.config.get("hold_threshold", 3.0)

    def connect_to_echo(self):
        try:
            self.pm = pymem.Pymem("echovr.exe")
            echo_module = pymem.process.module_from_name(
                self.pm.process_handle, "echovr.exe"
            )
            self.base_address = echo_module.lpBaseOfDll

            self.button_address = self.scan_for_button_address()

            if self.button_address:
                test_value = self.pm.read_uchar(self.button_address)
                self.echo_connected = test_value in [0, 1]
                if self.echo_connected:
                    print(f"Connected to EchoVR. Button address: {hex(self.button_address)}")
                    return self.echo_connected

            return False

        except pymem.exception.ProcessNotFound:
            print("EchoVR process not found.")
            self.echo_connected = False
            return False
        except Exception as e:
            print(f"Failed: {e}")
            self.echo_connected = False
            return False

    def scan_for_button_address(self):
        if not self.pm or not self.base_address:
            return None

        for offset in self.BUTTON_ADDRESSES:
            try:
                addr = self.base_address + offset
                value = self.pm.read_uchar(addr)
                if value in [0, 1]:
                    return addr
            except:
                continue

        try:
            for offset in range(-0x100, 0x100, 4):
                try:
                    addr = self.base_address + 0x20C7CA8 + offset
                    value = self.pm.read_uchar(addr)
                    if value in [0, 1]:
                        print(f"Found button at offset {hex(offset)}")
                        return addr
                except:
                    continue
        except:
            pass

        return None

    def read_button_state(self):
        if not self.echo_connected or self.button_address is None:
            return -1
        try:
            button_state = self.pm.read_uchar(self.button_address)
            return button_state
        except:
            self.echo_connected = False
            return -1

    def process_clicks(self):
        if self.click_count > 0 and not self.hold_detected:
            print(f"Processing {self.click_count} clicks")
            
            pattern_map = {
                int(self.click_patterns.get("prev_track", 3)): SoundAction.PREV_TRACK,
                int(self.click_patterns.get("next_track", 4)): SoundAction.NEXT_TRACK,
            }

            if self.click_count in pattern_map:
                action = pattern_map[self.click_count]
                success = self.media_controller.send_media_key(action)
                if success and self.gui_update_callback:
                    action_text = action.value.replace("_", " ").title()
                    self.gui_update_callback(f"{action_text} ({self.click_count} clicks)")

        self.reset_detection()

    def reset_detection(self):
        self.click_count = 0
        if self.click_timer:
            self.click_timer.cancel()
            self.click_timer = None
        if self.hold_timer:
            self.hold_timer.cancel()
            self.hold_timer = None
        self.hold_detected = False
        self.detection_active = False

    def check_button_actions(self):
        current_state = self.read_button_state()
        if current_state < 0:
            return

        current_time = time.time()

        if current_state == 1 and self.last_state == 0:
            press_time = current_time
            
            if (press_time - self.last_release_time) < self.debounce_delay:
                self.last_state = current_state
                return
                
            self.press_start_time = press_time
            self.last_press_time = press_time
            self.hold_detected = False
            
            if not self.detection_active:
                self.detection_active = True
            
            if self.hold_timer:
                self.hold_timer.cancel()
            self.hold_timer = threading.Timer(self.hold_threshold, self.process_hold)
            self.hold_timer.daemon = True
            self.hold_timer.start()

        elif current_state == 1 and self.last_state == 1:
            hold_duration = current_time - self.press_start_time
            
            if hold_duration >= 1.0 and self.gui_update_callback and not self.hold_detected:
                if hold_duration < self.hold_threshold:
                    progress = int((hold_duration / self.hold_threshold) * 100)
                    self.gui_update_callback(f"Hold: {progress}%...")
                elif hold_duration >= self.hold_threshold and not self.hold_detected:
                    self.process_hold()

        elif current_state == 0 and self.last_state == 1:
            release_time = current_time
            press_duration = release_time - self.press_start_time
            self.last_release_time = release_time
            
            if self.hold_timer:
                self.hold_timer.cancel()
                self.hold_timer = None
            
            if self.hold_detected:
                self.reset_detection()
                self.last_state = current_state
                return
            
            if press_duration < self.detection_threshold:
                self.last_state = current_state
                return
                
            if press_duration < 1.0:
                self.click_count += 1
                print(f"Click #{self.click_count} detected")
                
                if self.click_timer:
                    self.click_timer.cancel()
                
                self.click_timer = threading.Timer(self.click_timeout, self.process_clicks)
                self.click_timer.daemon = True
                self.click_timer.start()
            else:
                print(f"Long press ({press_duration:.1f}s) - ignoring")
                self.reset_detection()

        self.last_state = current_state

    def process_hold(self):
        if not self.hold_detected:
            self.hold_detected = True
            print(f"Hold detected - Play/Pause")
            
            success = self.media_controller.send_media_key(SoundAction.PLAY_PAUSE)
            if success and self.gui_update_callback:
                self.gui_update_callback(f"Play/Pause ({self.hold_threshold}s hold)")
            
            if self.click_timer:
                self.click_timer.cancel()
                self.click_timer = None
            self.click_count = 0

class EchoMediaControllerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("EchoVR Media Controller")
        self.root.geometry("450x450")
        self.root.configure(bg='#1a1a1a')
        
        self.root.resizable(False, False)
        self.root.attributes('-toolwindow', False)

        self.config = ConfigManager()
        self.media_controller = MediaController()
        self.echo_detector = EchoVRButtonDetector(self.media_controller, self.update_action_display)

        self.setup_styles()
        self.create_widgets()

        self.center_window()

        self.connect_to_echovr()
        self.start_echo_monitoring()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.update_ui()

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')

        bg_color = '#1a1a1a'
        fg_color = '#ffffff'
        accent_color = '#4a90e2'

        self.style.configure('Title.TLabel', 
                           background=bg_color, 
                           foreground=accent_color,
                           font=('Arial', 14, 'bold'))

        self.style.configure('Info.TLabel',
                           background=bg_color,
                           foreground=fg_color,
                           font=('Arial', 10))

        self.style.configure('Status.TLabel',
                           background=bg_color,
                           foreground='#888888',
                           font=('Arial', 8))

    def create_widgets(self):
        main_frame = tk.Frame(self.root, bg='#1a1a1a')
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        title_label = ttk.Label(main_frame,
                              text="🎮 EchoVR Media Controller",
                              style='Title.TLabel')
        title_label.pack(pady=(0, 10))

        status_frame = tk.Frame(main_frame, bg='#252525', relief='flat')
        status_frame.pack(fill='x', pady=5)

        self.echo_status = ttk.Label(status_frame,
                                   text="EchoVR: Disconnected",
                                   style='Info.TLabel',
                                   background='#252525')
        self.echo_status.pack(side='left', padx=10, pady=5)

        self.action_display = tk.Label(status_frame,
                                     text="Status: Ready",
                                     bg='#2d2d2d',
                                     fg='#48bb78',
                                     font=('Arial', 10, 'bold'),
                                     relief='flat',
                                     padx=10,
                                     pady=5)
        self.action_display.pack(side='right', padx=10, pady=5)

        controls_frame = tk.Frame(main_frame, bg='#252525', relief='flat')
        controls_frame.pack(fill='x', pady=10)

        controls_label = ttk.Label(controls_frame,
                                 text="🎮 Mute Button Controls",
                                 style='Info.TLabel',
                                 background='#252525')
        controls_label.pack(pady=(10, 5))

        controls_text = """• Hold 3 Seconds = Play/Pause
• 3 Clicks = Previous Track
• 4 Clicks = Next Track"""

        controls_desc = ttk.Label(controls_frame,
                                text=controls_text,
                                style='Status.TLabel',
                                background='#252525',
                                justify='left')
        controls_desc.pack(pady=(0, 10), padx=20)

        stats_frame = tk.Frame(main_frame, bg='#252525', relief='flat')
        stats_frame.pack(fill='x', pady=10)

        stats_label = ttk.Label(stats_frame,
                              text="⚙️ Settings",
                              style='Info.TLabel',
                              background='#252525')
        stats_label.pack(pady=(10, 5))

        settings_text = f"""Hold Time: {self.config.config['hold_threshold']}s
Click Timeout: {self.config.config['click_timeout']}s"""

        settings_desc = ttk.Label(stats_frame,
                                text=settings_text,
                                style='Status.TLabel',
                                background='#252525',
                                justify='left')
        settings_desc.pack(pady=(0, 10), padx=20)

        test_frame = tk.Frame(main_frame, bg='#1a1a1a')
        test_frame.pack(pady=10)

        test_label = ttk.Label(test_frame,
                             text="Test Controls:",
                             style='Status.TLabel',
                             background='#1a1a1a')
        test_label.pack(pady=(0, 5))

        test_buttons_frame = tk.Frame(test_frame, bg='#1a1a1a')
        test_buttons_frame.pack()

        test_buttons = [
            ("⏯ Play/Pause", SoundAction.PLAY_PAUSE),
            ("⏮ Prev Track", SoundAction.PREV_TRACK),
            ("⏭ Next Track", SoundAction.NEXT_TRACK),
        ]

        for text, action in test_buttons:
            btn = tk.Button(test_buttons_frame, text=text,
                          bg='#4a90e2', fg='white',
                          font=('Arial', 9),
                          borderwidth=0,
                          cursor='hand2',
                          command=lambda a=action: self.test_media_key(a))
            btn.pack(side='left', padx=5, pady=5)
            btn.bind('<Enter>', lambda e, b=btn: b.config(bg='#357abd'))
            btn.bind('<Leave>', lambda e, b=btn: b.config(bg='#4a90e2'))

        platform_text = f"Windows"
        self.platform_label = ttk.Label(main_frame,
                                      text=platform_text,
                                      style='Status.TLabel')
        self.platform_label.pack(pady=10)

        exit_btn = tk.Button(main_frame,
                           text="Exit",
                           bg='#dc3545',
                           fg='white',
                           font=('Arial', 9),
                           borderwidth=0,
                           cursor='hand2',
                           command=self.close_app)
        exit_btn.pack(pady=5)
        exit_btn.bind('<Enter>', lambda e: exit_btn.config(bg='#c82333'))
        exit_btn.bind('<Leave>', lambda e: exit_btn.config(bg='#dc3545'))

    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'+{x}+{y}')

    def connect_to_echovr(self):
        self.echo_connected = self.echo_detector.connect_to_echo()
        status = "Connected" if self.echo_connected else "Disconnected"
        color = "#48bb78" if self.echo_connected else "#f56565"
        self.echo_status.config(text=f"EchoVR: {status}", foreground=color)

        if not self.echo_connected and self.config.config.get("auto_reconnect", True):
            self.root.after(5000, self.connect_to_echovr)

    def monitor_echo_buttons(self):
        while True:
            try:
                if self.echo_detector.echo_connected:
                    self.echo_detector.check_button_actions()
                elif self.config.config.get("auto_reconnect", True):
                    time.sleep(5)
                    if not self.echo_detector.echo_connected:
                        self.connect_to_echovr()
                time.sleep(0.01)
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(1)

    def start_echo_monitoring(self):
        self.detection_thread = threading.Thread(target=self.monitor_echo_buttons, daemon=True)
        self.detection_thread.start()

    def update_action_display(self, action_text):
        self.action_display.config(text=f"Status: {action_text}")

    def update_ui(self):
        if hasattr(self.echo_detector, 'echo_connected'):
            status = "Connected" if self.echo_detector.echo_connected else "Disconnected"
            color = "#48bb78" if self.echo_detector.echo_connected else "#f56565"
            self.echo_status.config(text=f"EchoVR: {status}", foreground=color)

        self.root.after(1000, self.update_ui)

    def test_media_key(self, action):
        success = self.media_controller.send_media_key(action)
        if success:
            action_text = action.value.replace("_", " ").title()
            self.update_action_display(f"Test: {action_text}")
            self.root.after(2000, lambda: self.update_action_display("Ready"))

    def on_closing(self):
        self.close_app()

    def close_app(self):
        print("Shutting down...")
        self.root.quit()
        self.root.destroy()

    def run(self):
        self.root.mainloop()

def main():
    print("=" * 60)
    print("EchoVR Media Controller")
    print("=" * 60)
    print("Controls:")
    print("  • Hold 3 Seconds = Play/Pause")
    print("  • 3 Clicks = Previous Track")
    print("  • 4 Clicks = Next Track")
    print("=" * 60)

    app = EchoMediaControllerGUI()
    app.run()

if __name__ == "__main__":
    main()
