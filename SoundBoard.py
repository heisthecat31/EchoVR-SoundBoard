import os
import pygame
import tkinter as tk
from tkinter import filedialog, ttk, Listbox, Scrollbar
import threading
import time
import pymem
import pymem.process
import json
from dataclasses import dataclass
from enum import Enum

class SoundAction(Enum):
    PLAY_CURRENT = "play_current"
    NEXT_SONG = "next_song"
    PREV_SONG = "prev_song"
    TOGGLE_PAUSE = "toggle_pause"
    RESTART_SONG = "restart_song"

@dataclass
class SoundItem:
    path: str
    name: str = ""
    
    def __post_init__(self):
        if not self.name:
            self.name = os.path.splitext(os.path.basename(self.path))[0]

class ConfigManager:
    
    def __init__(self):
        self.config_file = "settings.json"
        self.config = self.load_config()
    
    def get_config_path(self):
        return os.path.join(os.getcwd(), self.config_file)
    
    def load_config(self):
        default_config = {
            "last_folder": "",
            "volume": 70,
            "loop": False,
            "current_index": 0
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
                print(f"Error loading config: {e}")
                return default_config
        return default_config
    
    def save_config(self):
        try:
            config_path = self.get_config_path()
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def set_last_folder(self, folder_path):
        self.config["last_folder"] = folder_path
        self.save_config()
    
    def get_last_folder(self):
        return self.config.get("last_folder", "")
    
    def set_volume(self, volume):
        self.config["volume"] = volume
        self.save_config()
    
    def get_volume(self):
        return self.config.get("volume", 70)
    
    def set_loop(self, loop_enabled):
        self.config["loop"] = loop_enabled
        self.save_config()
    
    def get_loop(self):
        return self.config.get("loop", False)
    
    def set_current_index(self, index):
        self.config["current_index"] = index
        self.save_config()
    
    def get_current_index(self):
        return self.config.get("current_index", 0)

class EchoVRButtonDetector:
    
    BUTTON_ADDRESSES = [
        0x20C7CA8,
        0x20C7CA0, 0x20C7CB0, 0x20C7C98, 0x20C7CB8,
        0x207CA8, 0x20C7D00, 0x20C8000
    ]
    
    def __init__(self):
        self.pm = None
        self.echo_connected = False
        self.button_address = None
        self.base_address = None
        
        self.last_state = 0
        self.press_start_time = 0
        self.last_click_time = 0
        self.hold_detected = False
        
        self.hold_threshold = 2.0
        self.click_timeout = 0.8
        
        self.click_history = []
        self.action_pending = False
        self.action_timer = None
    
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
            
        except Exception as e:
            print(f"Failed to connect to EchoVR: {e}")
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
            return -1
    
    def process_clicks(self, mp3_player):
        if not self.click_history:
            return
        
        current_time = time.time()
        
        if len(self.click_history) >= 3:
            first_click_time = self.click_history[0]
            last_click_time = self.click_history[-1]
            total_time = last_click_time - first_click_time
            
            click_count = len(self.click_history)
            
            if click_count == 3 and total_time < 0.8:
                print("3 clicks detected - previous song")
                if mp3_player.playing:
                    mp3_player.previous_song()
                else:
                    mp3_player.previous_song()
                    mp3_player.play()
                self.click_history = []
            
            elif click_count == 4 and total_time < 1.0:
                print("4 clicks detected - next song")
                if mp3_player.playing:
                    mp3_player.next_song()
                else:
                    mp3_player.next_song()
                    mp3_player.play()
                self.click_history = []
            
            elif click_count > 4:
                self.click_history = []
    
    def check_button_actions(self, mp3_player):
        current_state = self.read_button_state()
        if current_state < 0:
            return
        
        current_time = time.time()
        
        if current_state == 1 and self.last_state == 0:
            self.press_start_time = current_time
            self.last_click_time = current_time
            self.hold_detected = False
        
        elif current_state == 1 and self.last_state == 1:
            hold_duration = current_time - self.press_start_time
            
            if hold_duration >= self.hold_threshold and not self.hold_detected:
                print("Long hold detected - toggle pause")
                mp3_player.toggle_play()
                self.hold_detected = True
                self.click_history = []
                if self.action_timer:
                    self.action_timer.cancel()
                    self.action_timer = None
        
        elif current_state == 0 and self.last_state == 1:
            press_duration = current_time - self.press_start_time
            
            if press_duration < 0.5 and not self.hold_detected:
                current_time = time.time()
                
                if self.click_history:
                    time_since_last = current_time - self.click_history[-1]
                    if time_since_last > 1.0:
                        self.click_history = []
                
                self.click_history.append(current_time)
                
                if len(self.click_history) > 4:
                    self.click_history = self.click_history[-4:]
                
                if self.action_timer:
                    self.action_timer.cancel()
                
                self.action_timer = threading.Timer(0.5, lambda: self.process_clicks(mp3_player))
                self.action_timer.daemon = True
                self.action_timer.start()
        
        self.last_state = current_state

class MP3Player:
    def __init__(self, gui=None):
        pygame.mixer.init()
        self.playlist = []
        self.song_names = []
        self.current_index = 0
        self.playing = False
        self.paused = False
        self.loop = False
        self.volume = 0.7
        self.current_song = None
        self.echo_detector = EchoVRButtonDetector()
        self.gui = gui
        self.config = ConfigManager()
        
    def load_folder(self, folder_path):
        self.playlist = []
        self.song_names = []
        
        supported_formats = ['.mp3', '.wav', '.ogg', '.flac']
        
        try:
            if not os.path.exists(folder_path):
                print(f"Folder doesn't exist: {folder_path}")
                return False
                
            files_loaded = 0
            for file in os.listdir(folder_path):
                file_lower = file.lower()
                if any(file_lower.endswith(fmt) for fmt in supported_formats):
                    full_path = os.path.join(folder_path, file)
                    self.playlist.append(full_path)
                    name = os.path.splitext(file)[0]
                    self.song_names.append(name)
                    files_loaded += 1
            
            if files_loaded > 0:
                self.config.set_last_folder(folder_path)
                
                saved_index = self.config.get_current_index()
                if 0 <= saved_index < len(self.playlist):
                    self.current_index = saved_index
                else:
                    self.current_index = 0
                    self.config.set_current_index(0)
                
                print(f"Loaded {files_loaded} songs from {folder_path}")
                return True
            else:
                print(f"No supported audio files found in {folder_path}")
                return False
                
        except Exception as e:
            print(f"Error loading folder {folder_path}: {e}")
            return False
    
    def load_from_config(self):
        last_folder = self.config.get_last_folder()
        if last_folder and os.path.exists(last_folder):
            print(f"Auto-loading songs from last folder: {last_folder}")
            return self.load_folder(last_folder)
        return False
    
    def play(self, index=None):
        if not self.playlist:
            return False
            
        if self.playing:
            self.stop()
        
        if index is not None:
            self.current_index = index
            
        if 0 <= self.current_index < len(self.playlist):
            self.current_song = self.playlist[self.current_index]
            try:
                pygame.mixer.music.load(self.current_song)
                pygame.mixer.music.set_volume(self.volume)
                pygame.mixer.music.play()
                self.playing = True
                self.paused = False
                
                self.config.set_current_index(self.current_index)
                
                if self.gui:
                    self.gui.update_song_list_selection(self.current_index)
                    self.gui.update_current_song_display()
                
                print(f"Playing: {self.song_names[self.current_index]}")
                return True
            except Exception as e:
                print(f"Error playing {self.current_song}: {e}")
                return False
        return False
    
    def stop(self):
        if self.playing:
            pygame.mixer.music.stop()
            self.playing = False
            self.paused = False
            if self.gui:
                self.gui.update_current_song_display()
    
    def pause(self):
        if self.playing and not self.paused:
            pygame.mixer.music.pause()
            self.paused = True
            if self.gui:
                self.gui.update_current_song_display()
    
    def unpause(self):
        if self.playing and self.paused:
            pygame.mixer.music.unpause()
            self.paused = False
            if self.gui:
                self.gui.update_current_song_display()
    
    def toggle_play(self):
        if self.playing:
            if self.paused:
                self.unpause()
            else:
                self.pause()
        else:
            self.play()
    
    def next_song(self):
        if not self.playlist:
            return
        self.stop()
        self.current_index = (self.current_index + 1) % len(self.playlist)
        self.play()
    
    def previous_song(self):
        if not self.playlist:
            return
        self.stop()
        self.current_index = (self.current_index - 1) % len(self.playlist)
        self.play()
    
    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, volume))
        if self.playing:
            pygame.mixer.music.set_volume(self.volume)
    
    def toggle_loop(self):
        self.loop = not self.loop
        self.config.set_loop(self.loop)
        return self.loop
    
    def check_song_end(self):
        if self.playing and not pygame.mixer.music.get_busy() and not self.paused:
            if self.loop:
                self.play()
            else:
                self.next_song()
            return True
        return False

class DarkRoundedGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("EchoVR Soundboard")
        self.root.geometry("450x550")
        self.root.configure(bg='#1a1a1a')
        
        self.config = ConfigManager()
        
        self.player = MP3Player(gui=self)
        
        self.setup_styles()
        self.create_widgets()
        
        self.load_config_settings()
        
        self.center_window()
        
        self.connect_to_echovr()
        self.start_echo_monitoring()
        self.check_song_end()
        
        self.auto_load_songs()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        bg_color = '#1a1a1a'
        fg_color = '#ffffff'
        accent_color = '#4a90e2'
        hover_color = '#357abd'
        
        self.style.configure('Title.TLabel', 
                           background=bg_color, 
                           foreground=accent_color,
                           font=('Arial', 14, 'bold'))
        
        self.style.configure('Song.TLabel',
                           background=bg_color,
                           foreground=fg_color,
                           font=('Arial', 11))
        
        self.style.configure('Status.TLabel',
                           background=bg_color,
                           foreground='#888888',
                           font=('Arial', 9))
        
        self.style.configure('Control.TButton',
                           background=accent_color,
                           foreground=fg_color,
                           borderwidth=0,
                           font=('Arial', 12),
                           padding=8)
        
        self.style.map('Control.TButton',
                      background=[('active', hover_color)])
        
        self.style.configure('Folder.TButton',
                           background='#333333',
                           foreground=fg_color,
                           borderwidth=0,
                           font=('Arial', 10),
                           padding=6)
        
        self.style.map('Folder.TButton',
                      background=[('active', '#444444')])
    
    def create_rounded_rectangle(self, canvas, x1, y1, x2, y2, radius=20, **kwargs):
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)
    
    def create_widgets(self):
        self.canvas = tk.Canvas(self.root, 
                               bg='#1a1a1a', 
                               highlightthickness=0,
                               width=450, 
                               height=550)
        self.canvas.pack(fill='both', expand=True)
        
        self.bg_rect = self.create_rounded_rectangle(self.canvas, 
                                                    5, 5, 445, 545,
                                                    radius=20,
                                                    fill='#1a1a1a',
                                                    outline='#333333',
                                                    width=2)
        
        self.title_label = ttk.Label(self.canvas,
                                   text="EchoVR Soundboard",
                                   style='Title.TLabel')
        self.title_label.place(x=225, y=30, anchor='center')
        
        self.echo_status = ttk.Label(self.canvas,
                                    text="EchoVR: Disconnected",
                                    style='Status.TLabel')
        self.echo_status.place(x=225, y=60, anchor='center')
        
        self.current_song_label = ttk.Label(self.canvas,
                                          text="No music folder selected",
                                          style='Song.TLabel',
                                          wraplength=400,
                                          anchor='center')
        self.current_song_label.place(x=225, y=95, anchor='center')
        
        self.folder_status = ttk.Label(self.canvas,
                                     text="",
                                     style='Status.TLabel')
        self.folder_status.place(x=225, y=120, anchor='center')
        
        list_frame = tk.Frame(self.canvas, bg='#2d2d2d', bd=0)
        list_frame.place(x=25, y=140, width=400, height=180)
        
        list_scrollbar = Scrollbar(list_frame)
        list_scrollbar.pack(side='right', fill='y')
        
        self.song_listbox = Listbox(
            list_frame,
            bg='#252525',
            fg='#ffffff',
            selectbackground='#4a90e2',
            selectforeground='#ffffff',
            font=('Arial', 10),
            borderwidth=0,
            highlightthickness=0,
            yscrollcommand=list_scrollbar.set,
            cursor='hand2'
        )
        self.song_listbox.pack(side='left', fill='both', expand=True, padx=5, pady=5)
        list_scrollbar.config(command=self.song_listbox.yview)
        self.song_listbox.bind('<<ListboxSelect>>', self.on_song_select)
        
        control_frame = tk.Frame(self.canvas, bg='#1a1a1a')
        control_frame.place(x=25, y=330, width=400, height=60)
        
        self.prev_btn = ttk.Button(control_frame,
                                 text="⏮",
                                 command=self.player.previous_song,
                                 style='Control.TButton',
                                 width=4)
        self.prev_btn.pack(side='left', padx=5)
        
        self.play_btn = ttk.Button(control_frame,
                                 text="▶",
                                 command=self.player.toggle_play,
                                 style='Control.TButton',
                                 width=4)
        self.play_btn.pack(side='left', padx=5)
        
        self.next_btn = ttk.Button(control_frame,
                                 text="⏭",
                                 command=self.player.next_song,
                                 style='Control.TButton',
                                 width=4)
        self.next_btn.pack(side='left', padx=5)
        
        self.stop_btn = ttk.Button(control_frame,
                                 text="⏹",
                                 command=self.player.stop,
                                 style='Control.TButton',
                                 width=4)
        self.stop_btn.pack(side='left', padx=5)
        
        self.loop_btn = ttk.Button(control_frame,
                                 text="🔁",
                                 command=self.toggle_loop,
                                 style='Control.TButton',
                                 width=4)
        self.loop_btn.pack(side='left', padx=5)
        
        volume_frame = tk.Frame(self.canvas, bg='#1a1a1a')
        volume_frame.place(x=25, y=400, width=400, height=50)
        
        volume_label = ttk.Label(volume_frame,
                               text="Volume:",
                               style='Song.TLabel')
        volume_label.pack(side='left', padx=(0, 10))
        
        self.volume_var = tk.IntVar(value=70)
        self.volume_slider = tk.Scale(volume_frame,
                                    from_=0,
                                    to=100,
                                    orient='horizontal',
                                    variable=self.volume_var,
                                    command=self.update_volume,
                                    bg='#1a1a1a',
                                    fg='#ffffff',
                                    troughcolor='#333333',
                                    highlightbackground='#1a1a1a',
                                    length=250,
                                    showvalue=False)
        self.volume_slider.pack(side='left')
        
        self.volume_label = ttk.Label(volume_frame,
                                    text="70%",
                                    style='Song.TLabel')
        self.volume_label.pack(side='left', padx=10)
        
        self.folder_btn = ttk.Button(self.canvas,
                                   text="📁 Select Music Folder",
                                   command=self.select_folder,
                                   style='Folder.TButton')
        self.folder_btn.place(x=225, y=460, anchor='center')
        
        info_text = "EchoVR Mute Button: • 3 Clicks = Previous Song • 4 Clicks = Next Song • Hold 2s = Pause/Play"
        self.info_label = ttk.Label(self.canvas,
                                  text=info_text,
                                  style='Status.TLabel',
                                  justify='center')
        self.info_label.place(x=225, y=500, anchor='center')
        
        close_label = ttk.Label(self.canvas,
                              text="Right-click title to close",
                              style='Status.TLabel')
        close_label.place(x=225, y=520, anchor='center')
        
        self.canvas.bind("<Button-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.title_label.bind("<Button-1>", self.start_drag)
        self.title_label.bind("<B1-Motion>", self.drag)
        
        self.canvas.bind("<Button-3>", lambda e: self.close_app())
        self.title_label.bind("<Button-3>", lambda e: self.close_app())
    
    def start_drag(self, event):
        self.root.x = event.x
        self.root.y = event.y
    
    def drag(self, event):
        deltax = event.x - self.root.x
        deltay = event.y - self.root.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")
    
    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'+{x}+{y}')
    
    def load_config_settings(self):
        volume = self.config.get_volume()
        self.volume_var.set(volume)
        self.player.set_volume(volume / 100.0)
        self.volume_label.config(text=f"{volume}%")
        
        loop_enabled = self.config.get_loop()
        if loop_enabled:
            self.player.loop = True
            self.loop_btn.config(text="🔂")
        else:
            self.player.loop = False
            self.loop_btn.config(text="🔁")
    
    def auto_load_songs(self):
        if self.player.load_from_config():
            self.refresh_song_list()
            last_folder = self.config.get_last_folder()
            folder_name = os.path.basename(last_folder) if last_folder else "Unknown"
            self.folder_status.config(text=f"Loaded from: {folder_name}")
            self.current_song_label.config(
                text=f"Ready to play • {len(self.player.playlist)} songs loaded"
            )
            saved_index = self.config.get_current_index()
            if 0 <= saved_index < len(self.player.playlist):
                self.update_song_list_selection(saved_index)
    
    def select_folder(self):
        last_folder = self.config.get_last_folder()
        initial_dir = last_folder if os.path.exists(last_folder) else None
        
        folder_path = filedialog.askdirectory(
            title="Select Music Folder",
            initialdir=initial_dir
        )
        
        if folder_path and self.player.load_folder(folder_path):
            self.refresh_song_list()
            folder_name = os.path.basename(folder_path)
            self.folder_status.config(text=f"Folder: {folder_name}")
            self.update_status_message(f"Loaded {len(self.player.playlist)} songs from {folder_name}")
    
    def refresh_song_list(self):
        self.song_listbox.delete(0, tk.END)
        for i, song_name in enumerate(self.player.song_names):
            self.song_listbox.insert(tk.END, f"{i+1:02d}. {song_name}")
    
    def update_song_list_selection(self, index):
        self.song_listbox.selection_clear(0, tk.END)
        if 0 <= index < self.song_listbox.size():
            self.song_listbox.selection_set(index)
            self.song_listbox.see(index)
    
    def on_song_select(self, event):
        selection = self.song_listbox.curselection()
        if selection:
            self.player.play(selection[0])
    
    def update_volume(self, value):
        volume = int(value) / 100.0
        self.player.set_volume(volume)
        self.volume_label.config(text=f"{int(value)}%")
        self.config.set_volume(int(value))
    
    def toggle_loop(self):
        loop_enabled = self.player.toggle_loop()
        self.loop_btn.config(text="🔂" if loop_enabled else "🔁")
    
    def update_current_song_display(self):
        if self.player.playing:
            status = "⏸" if self.player.paused else "▶"
            if self.player.current_song:
                song_name = os.path.splitext(os.path.basename(self.player.current_song))[0]
                current = self.player.current_index + 1
                total = len(self.player.playlist)
                self.current_song_label.config(
                    text=f"{status} {song_name}\nTrack {current}/{total}"
                )
        else:
            if self.player.playlist:
                total = len(self.player.playlist)
                self.current_song_label.config(
                    text=f"Ready • {total} songs loaded"
                )
            else:
                self.current_song_label.config(text="Select a folder to load music")
    
    def update_status_message(self, message):
        self.current_song_label.config(text=message)
        self.root.after(3000, lambda: self.update_current_song_display() if self.player.playlist else None)
    
    def connect_to_echovr(self):
        self.echo_connected = self.player.echo_detector.connect_to_echo()
        status = "Connected" if self.echo_connected else "Disconnected"
        color = "#48bb78" if self.echo_connected else "#f56565"
        self.echo_status.config(text=f"EchoVR: {status}", foreground=color)
        if not self.echo_connected:
            self.root.after(5000, self.connect_to_echovr)
    
    def monitor_echo_buttons(self):
        while hasattr(self, 'root'):
            if self.player.echo_detector.echo_connected:
                self.player.echo_detector.check_button_actions(self.player)
                self.root.after(0, self.update_ui_state)
            else:
                if not hasattr(self, '_reconnect_attempt') or self._reconnect_attempt < time.time():
                    self._reconnect_attempt = time.time() + 5
                    self.connect_to_echovr()
            time.sleep(0.02)
    
    def start_echo_monitoring(self):
        self.detection_thread = threading.Thread(target=self.monitor_echo_buttons, daemon=True)
        self.detection_thread.start()
    
    def update_ui_state(self):
        if self.player.playing:
            self.play_btn.config(text="⏸" if not self.player.paused else "▶")
        else:
            self.play_btn.config(text="▶")
    
    def check_song_end(self):
        self.player.check_song_end()
        self.root.after(100, self.check_song_end)
    
    def on_closing(self):
        self.close_app()
    
    def close_app(self):
        if hasattr(self.player, 'current_index'):
            self.config.set_current_index(self.player.current_index)
        
        self.player.stop()
        pygame.mixer.quit()
        
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()

def main():
    app = DarkRoundedGUI()
    app.run()

if __name__ == "__main__":
    main()
