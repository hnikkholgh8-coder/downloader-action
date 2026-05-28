import os
import json
import time
import threading
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional, List

# در صورت اجرا روی ویندوز، کتابخانه رجیستری وارد می‌شود
if sys.platform == "win32":
    import winreg

# =====================================================================
# تنظیمات امنیتی اولیه
# =====================================================================
OLLAMA_API_TOKEN: Optional[str] = "YOUR_OLLAMA_SECURE_TOKEN_HERE"

PROMPTS = {
    "correction": (
        "You are an elite professional Persian editor. Your task is to rewrite the input text "
        "into a highly polished, formal, elegant, and grammatically perfect Persian. "
        "You must correct every single spelling mistake, typo (e.g., 'کناز' to 'کنار', 'ارتباطبا' to 'ارتباط با'), "
        "spacing issue (use correct نیم‌فاصله), and grammatical error. "
        "Crucially, preserve all core objectives, details, and nuances of the original text. "
        "Return ONLY the rewritten Persian text. Do not write any conversational filler, intro, or explanations."
    ),
    "spelling": (
        "You are a strict Persian spelling corrector. Your ONLY task is to find and correct spelling mistakes, "
        "typos, and keyboard slips in the input text (for example, correcting 'کناز' to 'کنار' and 'ارتباطبا' to 'ارتباط با'). "
        "Do NOT rewrite the sentences, do NOT change the style, do NOT make it more formal if it's informal. "
        "Keep the text exactly as it is, but with perfect spelling and typos fixed. "
        "Return ONLY the corrected text. Do not write any explanations, intro, or outro."
    ),
    "translation_to_fa": (
        "You are an advanced bilingual translator. Translate the following English text into fluent, "
        "natural, and clear Persian. Return ONLY the translated Persian text. "
        "Absolutely no conversational filler, no introductions, no explanations, and no markdown formatting."
    ),
    "translation_to_en": (
        "You are an advanced bilingual translator. Translate the following Persian text into fluent, "
        "natural, and clear English. Return ONLY the translated English text. "
        "Absolutely no conversational filler, no introductions, no explanations, and no markdown formatting."
    ),
    "summary": (
        "You are an expert summarizer. Summarize the following text concisely and clearly "
        "in the same language as the input. Return ONLY the summary. "
        "Absolutely no conversational filler, no introductions, no explanations, and no markdown formatting."
    ),
    "official_letter": (
        "شما یک کارشناس خبره در نگارش مکاتبات و نامه‌های اداری و رسمی هستید. "
        "با توجه به اهداف، دغدغه‌ها یا نکات کلیدی مطرح شده در متن ورودی، یک نامه اداری بسیار محترمانه، "
        "سنجیده، با لحن رسمی و ساختار استاندارد (شامل بخش‌های بسمه تعالی، گیرنده، موضوع، متن نامه و ارادت) بنویسید. "
        "از متغیرهایی مانند [نام گیرنده]، [تاریخ] و [موضوع] در متن استفاده کنید. "
        "فقط و فقط متن نامه نهایی را بدون هیچ‌گونه مقدمه، توضیحات جانبی یا پی‌نوشت بازگردانید."
    )
}

# =====================================================================
# کتابخانه‌های سیستم‌عامل و مانیتورینگ کیبورد
# =====================================================================
from pynput import keyboard
from pynput.keyboard import Key, Controller
import pystray
from PIL import Image, ImageDraw

CONFIG_FILE = "config.json"
keyboard_controller = Controller()

# =====================================================================
# مدیریت تنظیمات نرم‌افزار
# =====================================================================
@dataclass
class AppConfig:
    ollama_host: str = "192.168.20.65"
    ollama_port: str = "11434"
    hotkey_str: str = "<ctrl>+<alt>+x"
    default_model: str = "translategemma:4b"

    def to_dict(self) -> dict:
        return {
            "ollama_host": self.ollama_host,
            "ollama_port": self.ollama_port,
            "hotkey_str": self.hotkey_str,
            "default_model": self.default_model
        }

    @classmethod
    def load(cls) -> "AppConfig":
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return cls(**data)
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

# =====================================================================
# توابع کاربردی بهبود نگارش و راست‌چین‌سازی جفت‌جهته یونیکد
# =====================================================================
def is_text_mostly_persian(text: str) -> bool:
    persian_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F')
    total_chars = len(text.strip()) or 1
    return (persian_chars / total_chars) > 0.25

def apply_unicode_rtl(text: str) -> str:
    """اعمال کاراکترهای کنترل جهت یونیکد (RLE و PDF) جهت رفع به‌هم‌ریختگی کلمات انگلیسی در متون فارسی"""
    if not text:
        return ""
    lines = text.split('\n')
    processed_lines = []
    for line in lines:
        if line.strip():
            # احاطه کردن خط با کاراکترهای جهت‌دهی راست‌به‌چپ برای اصلاح چینش عبارات ترکیبی
            new_line = f"\u202b{line}\u202c"
            processed_lines.append(new_line)
        else:
            processed_lines.append(line)
    return '\n'.join(processed_lines)

def get_best_system_font() -> str:
    root_temp = tk.Tk()
    root_temp.withdraw()
    available_fonts = [f.lower() for f in tkfont.families()]
    root_temp.destroy()
    
    preferences = ["calibri", "b nazanin", "2 nazanin", "tahoma", "segoe ui", "arial"]
    for font in preferences:
        if font in available_fonts:
            return font
    return "system"

# =====================================================================
# پنجره شناور مستقل (پشتیبانی از باز شدن همزمان چند پنجره)
# =====================================================================
class FloatingWindow(tk.Toplevel):
    def __init__(self, parent, captured_text: str, config: AppConfig, available_models: List[str], app_font: str):
        super().__init__(parent)
        self.captured_text = captured_text
        self.config = config
        self.available_models = available_models
        self.app_font = app_font
        self.current_mode = "correction"
        self._drag_data = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        
        # پالت رنگ مدرن تیره عمیق
        self.bg_color = "#1E1E2E"
        self.header_color = "#11111B"
        self.text_color = "#CDD6F4"
        self.accent_color = "#89B4FA"
        self.border_color = "#313244"
        self.button_active_bg = "#89B4FA"
        self.button_inactive_bg = "#313244"

        self.configure(bg=self.border_color)
        
        self.main_container = tk.Frame(self, bg=self.bg_color)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # ابعاد پنجره
        width, height = 680, 540
        mx, my = self.winfo_pointerx(), self.winfo_pointery()
        
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        target_x = mx + 15
        target_y = my + 15
        
        if target_x + width > screen_width:
            target_x = mx - width - 15
        if target_y + height > screen_height:
            target_y = my - height - 15
            
        target_x = max(10, target_x)
        target_y = max(10, target_y)

        self.geometry(f"{width}x{height}+{target_x}+{target_y}")

        self.setup_ui()
        self.start_processing_pipeline()

    def setup_ui(self):
        # ۱. هدر بالای پنجره
        header = tk.Frame(self.main_container, bg=self.header_color, height=38)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        self.status_dot = tk.Canvas(header, width=12, height=12, bg=self.header_color, bd=0, highlightthickness=0)
        self.status_dot.pack(side=tk.RIGHT, padx=(5, 12))
        self.dot_id = self.status_dot.create_oval(2, 2, 10, 10, fill="#F38BA8")

        title_lbl = tk.Label(header, text="دستیار هوشمند متن AI", fg=self.accent_color, bg=self.header_color, 
                             font=(self.app_font, 9, "bold"))
        title_lbl.pack(side=tk.RIGHT)

        close_btn = tk.Button(header, text="✕", bg=self.header_color, fg="#F38BA8", bd=0, 
                              activebackground="#F38BA8", activeforeground="#11111B",
                              font=(self.app_font, 10, "bold"), cursor="hand2", command=self.destroy)
        close_btn.pack(side=tk.LEFT, fill=tk.Y, padx=5)

        def start_drag(event): self._drag_data = {"x": event.x, "y": event.y}
        def stop_drag(event): self._drag_data = None
        def do_drag(event):
            dx, dy = event.x - self._drag_data["x"], event.y - self._drag_data["y"]
            self.geometry(f"+{self.winfo_x() + dx}+{self.winfo_y() + dy}")

        header.bind("<ButtonPress-1>", start_drag)
        header.bind("<ButtonRelease-1>", stop_drag)
        header.bind("<B1-Motion>", do_drag)

        # ۲. کنترلر بالایی و دراپ‌دان تخت مدل‌ها
        control_panel = tk.Frame(self.main_container, bg=self.bg_color)
        control_panel.pack(fill=tk.X, padx=12, pady=(10, 2))

        model_label = tk.Label(control_panel, text="مدل فعال:", fg=self.text_color, bg=self.bg_color, font=(self.app_font, 8, "bold"))
        model_label.pack(side=tk.RIGHT, padx=(5, 0))

        self.selected_model_var = tk.StringVar(value=self.config.default_model)
        
        self.model_dropdown_btn = tk.Label(
            control_panel, 
            text=f" {self.selected_model_var.get()}  ▼ ", 
            bg=self.button_inactive_bg, 
            fg=self.text_color, 
            relief="flat", 
            padx=8, 
            pady=4, 
            cursor="hand2", 
            font=(self.app_font, 8, "bold")
        )
        self.model_dropdown_btn.pack(side=tk.RIGHT)

        def show_custom_menu(event):
            menu = tk.Menu(self, tearoff=0, bg="#11111B", fg="#CDD6F4", 
                           activebackground="#89B4FA", activeforeground="#11111B", bd=1, relief="flat")
            for m in self.available_models:
                menu.add_command(label=f"  {m}  ", command=lambda model_name=m: on_model_selected(model_name))
            menu.post(event.x_root, event.y_root)

        def on_model_selected(model_name: str):
            self.selected_model_var.set(model_name)
            self.model_dropdown_btn.config(text=f" {model_name}  ▼ ")
            self.config.default_model = model_name
            self.config.save()
            self.trigger_processing()

        self.model_dropdown_btn.bind("<Button-1>", show_custom_menu)

        # ۳. باکس پیش‌نمایش متن ورودی
        preview_frame = tk.Frame(self.main_container, bg=self.header_color, highlightthickness=1, highlightbackground=self.border_color)
        preview_frame.pack(fill=tk.X, padx=12, pady=5)
        
        preview_snippet = (self.captured_text[:110] + '...') if len(self.captured_text) > 110 else self.captured_text
        preview_lbl = tk.Label(preview_frame, text=f"متن ورودی: {preview_snippet}", fg="#A6ADC8", 
                               bg=self.header_color, justify="right", anchor="e", font=(self.app_font, 8, "italic"))
        preview_lbl.pack(fill=tk.X, padx=8, pady=6)

        # ۴. تب‌بند انتخاب حالت‌ها
        tab_frame = tk.Frame(self.main_container, bg=self.bg_color)
        tab_frame.pack(fill=tk.X, padx=12, pady=5)

        self.mode_buttons = {}

        def set_mode(selected_mode: str):
            self.current_mode = selected_mode
            for m, btn in self.mode_buttons.items():
                if m == selected_mode:
                    btn.configure(bg=self.button_active_bg, fg="#11111B")
                else:
                    btn.configure(bg=self.button_inactive_bg, fg=self.text_color)
            self.trigger_processing()

        btn_correction = tk.Button(tab_frame, text="ویراستاری رسمی", bd=0, padx=6, pady=4, cursor="hand2", font=(self.app_font, 8, "bold"), command=lambda: set_mode("correction"))
        btn_correction.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(4, 0))
        self.mode_buttons["correction"] = btn_correction

        btn_spelling = tk.Button(tab_frame, text="غلط‌گیری املایی", bd=0, padx=6, pady=4, cursor="hand2", font=(self.app_font, 8, "bold"), command=lambda: set_mode("spelling"))
        btn_spelling.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(4, 0))
        self.mode_buttons["spelling"] = btn_spelling

        btn_translation = tk.Button(tab_frame, text="ترجمه هوشمند", bd=0, padx=6, pady=4, cursor="hand2", font=(self.app_font, 8, "bold"), command=lambda: set_mode("translation"))
        btn_translation.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(4, 0))
        self.mode_buttons["translation"] = btn_translation

        btn_summary = tk.Button(tab_frame, text="خلاصه‌سازی", bd=0, padx=6, pady=4, cursor="hand2", font=(self.app_font, 8, "bold"), command=lambda: set_mode("summary"))
        btn_summary.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(4, 0))
        self.mode_buttons["summary"] = btn_summary

        btn_letter = tk.Button(tab_frame, text="نامه اداری", bd=0, padx=6, pady=4, cursor="hand2", font=(self.app_font, 8, "bold"), command=lambda: set_mode("official_letter"))
        btn_letter.pack(side=tk.RIGHT, expand=True, fill=tk.X)
        self.mode_buttons["official_letter"] = btn_letter

        self.mode_buttons[self.current_mode].configure(bg=self.button_active_bg, fg="#11111B")

        # ۵. فریم دکمه‌های پایینی (پک اولویت‌دار جهت جلوگیری از جابه‌جایی و پنهان شدن)
        btn_bar = tk.Frame(self.main_container, bg=self.bg_color)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=12, pady=(0, 12))

        def on_copy():
            try:
                content = self.text_area.get("1.0", tk.END).strip()
                content_clean = content.replace('\u202b', '').replace('\u202c', '').replace('\u200f', '')
                if content_clean and "در حال پردازش" not in content_clean and "عذر می‌خوام" not in content_clean:
                    self.clipboard_clear()
                    self.clipboard_append(content_clean)
                    self.update()
                    copy_btn.config(text="✓ کپی شد", fg="#A6E3A1")
                    self.after(1500, lambda: copy_btn.config(text="کپی خروجی", fg=self.text_color))
            except Exception:
                pass

        def on_paste_replace():
            try:
                content = self.text_area.get("1.0", tk.END).strip()
                content_clean = content.replace('\u202b', '').replace('\u202c', '').replace('\u200f', '')
                if content_clean and "در حال پردازش" not in content_clean and "عذر می‌خوام" not in content_clean:
                    # ۱. کپی خروجی تمیز در کلیپ‌بورد سیستم
                    self.clipboard_clear()
                    self.clipboard_append(content_clean)
                    self.update()
                    
                    # ۲. بستن فوری پنجره جاری جهت حفظ پایداری کامل Thread اصلی تیکینتر
                    self.destroy()
                    
                    # ۳. شبیه‌سازی مطمئن Paste در یک Thread پس‌زمینه
                    def run_async_paste():
                        time.sleep(0.2)  # زمان برای انتقال فوکوس فعال به نرم‌افزار هدف
                        keyboard_controller.press(Key.ctrl)
                        keyboard_controller.press('v')
                        time.sleep(0.05)
                        keyboard_controller.release('v')
                        keyboard_controller.release(Key.ctrl)

                    threading.Thread(target=run_async_paste, daemon=True).start()
            except Exception:
                pass

        cancel_btn = tk.Button(btn_bar, text="بیخیال", bg="#45475A", fg="#F38BA8",
                               activebackground="#F38BA8", activeforeground="#11111B",
                               bd=0, height=2, width=10, cursor="hand2", font=(self.app_font, 9, "bold"),
                               command=self.destroy)
        cancel_btn.pack(side=tk.LEFT)

        copy_btn = tk.Button(btn_bar, text="کپی خروجی", bg=self.button_inactive_bg, fg=self.text_color,
                             activebackground=self.accent_color, activeforeground=self.header_color,
                             bd=0, height=2, width=14, cursor="hand2", font=(self.app_font, 9, "bold"),
                             command=on_copy)
        copy_btn.pack(side=tk.LEFT, padx=6)

        accept_btn = tk.Button(btn_bar, text="✓ اعمال و جایگذاری", bg="#A6E3A1", fg="#11111B",
                               activebackground="#94E2D5", activeforeground="#11111B",
                               bd=0, height=2, cursor="hand2", font=(self.app_font, 9, "bold"),
                               command=on_paste_replace)
        accept_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        # ۶. باکس نمایش خروجی (در آخرین مرحله پک می‌شود تا مابقی فضا را بگیرد)
        text_frame = tk.Frame(self.main_container, bg=self.bg_color)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(5, 12))

        self.text_area = tk.Text(text_frame, wrap=tk.WORD, bg="#252538", fg=self.text_color,
                                 insertbackground=self.text_color, bd=0, highlightthickness=1,
                                 highlightbackground=self.border_color, highlightcolor=self.accent_color,
                                 font=(self.app_font, 13), padx=12, pady=12, spacing2=8)
        self.text_area.pack(fill=tk.BOTH, expand=True)
        self.text_area.tag_configure("rtl", justify="right")

    def trigger_processing(self):
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert(tk.END, apply_unicode_rtl("در حال پردازش و بهینه‌سازی متن توسط هوش مصنوعی...\nلطفاً شکیبا باشید."), "rtl")
        self.text_area.config(state=tk.DISABLED)

        target_model = self.selected_model_var.get()

        def response_callback(response_text: str, is_success: bool):
            if self.winfo_exists():
                self.text_area.config(state=tk.NORMAL)
                self.text_area.delete("1.0", tk.END)
                
                # تراز کردن بی نقص جهت نگارش نقاط و عبارات انگلیسی
                rtl_styled_text = apply_unicode_rtl(response_text)
                
                self.text_area.insert(tk.END, rtl_styled_text, "rtl")
                self.text_area.config(state=tk.DISABLED)

        threading.Thread(
            target=self.parent_api_call_bridge,
            args=(self.captured_text, target_model, self.current_mode, response_callback),
            daemon=True
        ).start()

    def parent_api_call_bridge(self, text, model, mode, callback):
        url = f"http://{self.config.ollama_host}:{self.config.ollama_port}/api/generate"
        
        if mode == "correction":
            system_prompt = PROMPTS["correction"]
        elif mode == "spelling":
            system_prompt = PROMPTS["spelling"]
        elif mode == "translation":
            if is_text_mostly_persian(text):
                system_prompt = PROMPTS["translation_to_en"]
            else:
                system_prompt = PROMPTS["translation_to_fa"]
        elif mode == "summary":
            system_prompt = PROMPTS["summary"]
        else:
            system_prompt = PROMPTS["official_letter"]

        payload = {
            "model": model,
            "prompt": f"{system_prompt}\n\n[INPUT TEXT]:\n{text}",
            "stream": False,
            "options": {"temperature": 0.15}
        }
        
        headers = {"Content-Type": "application/json"}
        if OLLAMA_API_TOKEN and OLLAMA_API_TOKEN != "YOUR_OLLAMA_SECURE_TOKEN_HERE":
            headers["Authorization"] = f"Bearer {OLLAMA_API_TOKEN}"

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            
            with urllib.request.urlopen(req, timeout=40) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                result_text = res_data.get("response", "خطای دریافت پاسخ").strip()
                self.after(0, lambda: callback(result_text, True))
        except urllib.error.URLError:
            funny_error = (
                "عذر می‌خوام! 😅 مثل اینکه هوش مصنوعی در حال چرت زدنه یا کلاً خاموشه!\n\n"
                "لطفاً با آقای حسنی تماس بگیر تا زنده‌اش کنه. ☎️ داخلیش ۹۰۱ هست!"
            )
            self.after(0, lambda: callback(funny_error, False))
        except Exception as e:
            self.after(0, lambda: callback(f"خطای پردازش ناموفق:\n{str(e)}", False))

    def start_processing_pipeline(self):
        def on_ping_complete(online: bool):
            if self.winfo_exists():
                if online:
                    self.status_dot.itemconfig(self.dot_id, fill="#A6E3A1")  # سبز
                else:
                    self.status_dot.itemconfig(self.dot_id, fill="#F38BA8")  # قرمز
                self.trigger_processing()

        threading.Thread(
            target=self.check_connection_internal,
            args=(on_ping_complete,),
            daemon=True
        ).start()

    def check_connection_internal(self, callback):
        url_root = f"http://{self.config.ollama_host}:{self.config.ollama_port}/"
        url_tags = f"http://{self.config.ollama_host}:{self.config.ollama_port}/api/tags"
        
        headers = {}
        if OLLAMA_API_TOKEN and OLLAMA_API_TOKEN != "YOUR_OLLAMA_SECURE_TOKEN_HERE":
            headers["Authorization"] = f"Bearer {OLLAMA_API_TOKEN}"
            
        try:
            req_root = urllib.request.Request(url_root, headers=headers, method="GET")
            with urllib.request.urlopen(req_root, timeout=3) as r:
                if r.status == 200:
                    try:
                        req_tags = urllib.request.Request(url_tags, headers=headers, method="GET")
                        with urllib.request.urlopen(req_tags, timeout=3) as r_tags:
                            res = json.loads(r_tags.read().decode("utf-8"))
                            models = [m["name"] for m in res.get("models", [])]
                            if models:
                                self.available_models = models
                    except Exception:
                        pass
                    self.after(0, lambda: callback(True))
                    return
            self.after(0, lambda: callback(False))
        except Exception:
            self.after(0, lambda: callback(False))

# =====================================================================
# کلاس اصلی مدیریت برنامه و سیستم ترِی
# =====================================================================
class ModernAssistantApp:
    def __init__(self):
        self.config = AppConfig.load()
        self.root = tk.Tk()
        self.root.withdraw()
        
        self.app_font = get_best_system_font()
        self.available_models: List[str] = [self.config.default_model, "llama3"]
        
        self.listener: Optional[keyboard.Listener] = None
        self.tray_icon: Optional[pystray.Icon] = None
        
        self.start_hotkey_listener()
        self.start_tray_icon()

    def start_hotkey_listener(self):
        if self.listener:
            self.listener.stop()
        
        hotkey_map = {
            self.config.hotkey_str: self.on_hotkey_triggered
        }
        try:
            self.listener = keyboard.GlobalHotKeys(hotkey_map)
            self.listener.start()
        except Exception as e:
            print(f"Failed to bind hotkey: {e}")

    def on_hotkey_triggered(self):
        threading.Thread(target=self.process_pipeline, daemon=True).start()

    def process_pipeline(self):
        selected_text = self.capture_selected_text()
        if not selected_text:
            self.root.after(0, lambda: messagebox.showwarning(
                "عدم شناسایی متن", 
                "متنی جهت ویرایش یافت نشد.\nلطفاً ابتدا بخشی از یک متن را در نرم‌افزار خود به حالت انتخاب (Highlight) درآورید و سپس کلید میانبر را فشار دهید."
            ))
            return
        
        self.root.after(0, lambda: FloatingWindow(
            self.root, selected_text, self.config, self.available_models, self.app_font
        ))

    def capture_selected_text(self) -> Optional[str]:
        time.sleep(0.3)
        try:
            old_clip = self.root.clipboard_get()
        except Exception:
            old_clip = ""

        self.root.clipboard_clear()
        self.root.update()

        keyboard_controller.press(Key.ctrl)
        keyboard_controller.press('c')
        time.sleep(0.15)
        keyboard_controller.release('c')
        keyboard_controller.release(Key.ctrl)
        time.sleep(0.1)

        try:
            new_clip = self.root.clipboard_get()
            if new_clip and new_clip.strip():
                return new_clip.strip()
        except Exception:
            pass
        return None

    def show_settings_window(self):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("تنظیمات سیستم")
        settings_win.geometry("400x340")
        settings_win.resizable(False, False)
        settings_win.configure(bg="#1E1E2E")
        
        style = ttk.Style(settings_win)
        style.theme_use("clam")
        style.configure(".", background="#1E1E2E", foreground="#CDD6F4", font=(self.app_font, 9))
        style.configure("TLabel", background="#1E1E2E", foreground="#CDD6F4")
        style.configure("TButton", background="#313244", foreground="#CDD6F4", borderwidth=0)
        style.map("TButton", background=[("active", "#89B4FA")], foreground=[("active", "#11111B")])

        ttk.Label(settings_win, text="آدرس آی‌پی سرور Ollama:", font=(self.app_font, 9, "bold")).pack(anchor=tk.E, padx=20, pady=(20, 2))
        host_entry = ttk.Entry(settings_win, width=35, justify="center")
        host_entry.pack(fill=tk.X, padx=20, pady=5)
        host_entry.insert(0, self.config.ollama_host)

        ttk.Label(settings_win, text="پورت سرور:", font=(self.app_font, 9, "bold")).pack(anchor=tk.E, padx=20, pady=(10, 2))
        port_entry = ttk.Entry(settings_win, width=35, justify="center")
        port_entry.pack(fill=tk.X, padx=20, pady=5)
        port_entry.insert(0, self.config.ollama_port)

        ttk.Label(settings_win, text="کلید میانبر سیستم (مانند <ctrl>+<alt>+x):", font=(self.app_font, 9, "bold")).pack(anchor=tk.E, padx=20, pady=(10, 2))
        hotkey_entry = ttk.Entry(settings_win, width=35, justify="center")
        hotkey_entry.pack(fill=tk.X, padx=20, pady=5)
        hotkey_entry.insert(0, self.config.hotkey_str)

        def save_settings():
            self.config.ollama_host = host_entry.get().strip()
            self.config.ollama_port = port_entry.get().strip()
            old_hotkey = self.config.hotkey_str
            new_hotkey = hotkey_entry.get().strip()
            self.config.hotkey_str = new_hotkey
            self.config.save()
            
            if old_hotkey != new_hotkey:
                self.start_hotkey_listener()
            
            settings_win.destroy()
            messagebox.showinfo("ذخیره موفق", "تنظیمات با موفقیت ذخیره شد و میانبر جدید فعال گردید.")

        save_btn = ttk.Button(settings_win, text="ذخیره تنظیمات", command=save_settings)
        save_btn.pack(pady=25)
        settings_win.attributes("-topmost", True)

    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color='#1E1E2E')
        dc = ImageDraw.Draw(image)
        dc.ellipse([(12, 12), (52, 52)], fill='#89B4FA')
        return image

    def start_tray_icon(self):
        def on_clicked(icon, item):
            if str(item) == "تنظیمات":
                self.root.after(0, self.show_settings_window)
            elif str(item) == "خروج":
                self.cleanup_and_exit()

        menu = pystray.Menu(
            pystray.MenuItem("تنظیمات", on_clicked),
            pystray.MenuItem("خروج", on_clicked)
        )
        
        self.tray_icon = pystray.Icon("AI-Assistant", self.create_tray_image(), "دستیار هوشمند متن", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def cleanup_and_exit(self):
        if self.listener:
            self.listener.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()

    def run(self):
        self.root.mainloop()

# =====================================================================
# تنظیم استارت‌آپ خودکار ویندوز
# =====================================================================
def register_in_startup() -> bool:
    """اضافه کردن برنامه به استارت‌آپ ویندوز در رجیستری برای اجرای خودکار پس‌زمینه"""
    if sys.platform != "win32":
        print("سیستم‌عامل ویندوز نیست.")
        return False
    try:
        exe_path = os.path.abspath(sys.argv[0])
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "AI-Text-Assistant", 0, winreg.REG_SZ, f'"{exe_path}"')
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"خطا در ثبت استارت‌آپ: {e}")
        return False

# =====================================================================
# شروع اجرای نرم‌افزار
# =====================================================================
if __name__ == "__main__":
    # اگر برنامه با فلگ --startup فراخوانی شود، آدرس خود را در رجیستری ویندوز ثبت می‌کند و بسته می‌شود
    if len(sys.argv) > 1 and sys.argv[1] == "--startup":
        success = register_in_startup()
        if success:
            print("برنامه با موفقیت به استارت‌آپ ویندوز اضافه شد.")
        else:
            print("عملیات ناموفق بود.")
        sys.exit(0)

    app = ModernAssistantApp()
    app.run()
