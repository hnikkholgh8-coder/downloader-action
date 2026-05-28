import os
import json
import time
import threading
import sys
from dataclasses import dataclass
from typing import Optional, List

# وارد کردن ابزارهای PyQt6
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QFrame, QLabel, QPushButton, QTextEdit, QLineEdit, 
    QComboBox, QGridLayout, QMessageBox, QMenu, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint
from PyQt6.QtGui import QIcon, QAction, QCursor, QPixmap, QPainter, QColor

# در صورت اجرا روی ویندوز، کتابخانه رجیستری وارد می‌شود
if sys.platform == "win32":
    import winreg

# =====================================================================
# فایل تنظیمات و پرامپت‌های پیش‌فرض سیستم
# =====================================================================
CONFIG_FILE = "config.json"
OLLAMA_API_TOKEN: Optional[str] = "YOUR_OLLAMA_SECURE_TOKEN_HERE"

DEFAULT_MODES = {
    "correction": {
        "label": "ویراستاری رسمی",
        "prompt": (
            "You are an elite professional Persian editor. Your task is to rewrite the input text "
            "into a highly polished, formal, elegant, and grammatically perfect Persian. "
            "You must correct every single spelling mistake, typo (e.g., 'کناز' to 'کنار', 'ارتباطبا' to 'ارتباط با'), "
            "spacing issue (use correct نیم‌فاصله), and grammatical error. "
            "Crucially, preserve all core objectives, details, and nuances of the original text. "
            "Return ONLY the rewritten Persian text. Do not write any conversational filler, intro, or explanations."
        )
    },
    "spelling": {
        "label": "غلط‌گیری املایی",
        "prompt": (
            "You are a strict Persian spelling corrector. Your ONLY task is to find and correct spelling mistakes, "
            "typos, and keyboard slips in the input text (for example, correcting 'کناز' to 'کنار' and 'ارتباطبا' to 'ارتباط با'). "
            "Do NOT rewrite the sentences, do NOT change the style, do NOT make it more formal if it's informal. "
            "Keep the text exactly as it is, but with perfect spelling and typos fixed. "
            "Return ONLY the corrected text. Do not write any explanations, intro, or outro."
        )
    },
    "translation": {
        "label": "ترجمه هوشمند",
        "prompt_to_fa": (
            "You are an advanced bilingual translator. Translate the following English text into fluent, "
            "natural, and clear Persian. Return ONLY the translated Persian text. "
            "Absolutely no conversational filler, no introductions, no explanations, and no markdown formatting."
        ),
        "prompt_to_en": (
            "You are an advanced bilingual translator. Translate the following Persian text into fluent, "
            "natural, and clear English. Return ONLY the translated English text. "
            "Absolutely no conversational filler, no introductions, no explanations, and no markdown formatting."
        )
    },
    "summary": {
        "label": "خلاصه‌سازی",
        "prompt": (
            "You are an expert summarizer. Summarize the following text concisely and clearly "
            "in the same language as the input. Return ONLY the summary. "
            "Absolutely no conversational filler, no introductions, no explanations, and no markdown formatting."
        )
    },
    "official_letter": {
        "label": "نامه اداری",
        "prompt": (
            "شما یک کارشناس خبره در نگارش مکاتبات و نامه‌های اداری و رسمی هستید. "
            "با توجه به اهداف، دغدغه‌ها یا نکات کلیدی مطرح شده در متن ورودی، یک نامه اداری بسیار محترمانه، "
            "سنجیده، با لحن رسمی و ساختار استاندارد (شامل بخش‌های بسمه تعالی، گیرنده، موضوع، متن نامه و ارادت) بنویسید. "
            "از متغیرهایی مانند [نام گیرنده]، [تاریخ] و [موضوع] در متن استفاده کنید. "
            "فقط و فقط متن نامه نهایی را بدون هیچ‌گونه مقدمه، توضیحات جانبی یا پی‌نوشت بازگردانید."
        )
    }
}

# =====================================================================
# کتابخانه‌های مدیریت کیبورد
# =====================================================================
from pynput import keyboard
from pynput.keyboard import Key, Controller
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
    modes: Optional[dict] = None

    def __post_init__(self):
        if self.modes is None:
            self.modes = DEFAULT_MODES.copy()

    def to_dict(self) -> dict:
        return {
            "ollama_host": self.ollama_host,
            "ollama_port": self.ollama_port,
            "hotkey_str": self.hotkey_str,
            "default_model": self.default_model,
            "modes": self.modes
        }

    @classmethod
    def load(cls) -> "AppConfig":
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "modes" not in data or not isinstance(data["modes"], dict):
                        data["modes"] = DEFAULT_MODES.copy()
                    return cls(**data)
            except Exception:
                pass
        config = cls()
        config.save()
        return config

    def save(self) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

# =====================================================================
# تشخیص زبان متن
# =====================================================================
def is_text_mostly_persian(text: str) -> bool:
    persian_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F')
    total_chars = len(text.strip()) or 1
    return (persian_chars / total_chars) > 0.25

# =====================================================================
# شیوه استایل‌دهی سراسری برنامه (QSS)
# =====================================================================
QSS = """
QWidget {
    background-color: #1E1E2E;
    color: #CDD6F4;
    font-family: 'Calibri', 'Segoe UI', 'Tahoma', sans-serif;
    font-size: 13px;
}
QFrame#HeaderFrame {
    background-color: #11111B;
    border-bottom: 1px solid #313244;
}
QLabel#TitleLabel {
    color: #89B4FA;
    font-weight: bold;
    font-size: 14px;
}
QPushButton {
    background-color: #313244;
    color: #CDD6F4;
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #45475A;
}
QPushButton#CloseBtn {
    background-color: transparent;
    color: #F38BA8;
    font-size: 14px;
}
QPushButton#CloseBtn:hover {
    background-color: #F38BA8;
    color: #11111B;
}
QPushButton#AcceptButton {
    background-color: #A6E3A1;
    color: #11111B;
}
QPushButton#AcceptButton:hover {
    background-color: #94E2D5;
}
QPushButton#CancelButton {
    background-color: #45475A;
    color: #F38BA8;
}
QPushButton#CancelButton:hover {
    background-color: #F38BA8;
    color: #11111B;
}
QTextEdit {
    background-color: #252538;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 10px;
    font-size: 15px;
    line-height: 24px;
}
QLineEdit#PreviewLine {
    background-color: #11111B;
    border: 1px solid #313244;
    border-radius: 4px;
    color: #A6ADC8;
    padding: 5px;
}
QComboBox {
    background-color: #313244;
    color: #CDD6F4;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 3px 20px 3px 5px;
}
QComboBox QAbstractItemView {
    background-color: #11111B;
    selection-background-color: #89B4FA;
    selection-color: #11111B;
}
"""

# =====================================================================
# هدر بار سفارشی با قابلیت درگ کردن پنجره بدون فریم
# =====================================================================
class HeaderBar(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_win = parent
        self.setObjectName("HeaderFrame")
        self.setFixedHeight(38)
        self._drag_position = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.parent_win.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_position is not None:
            self.parent_win.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_position = None

# =====================================================================
# پنجره شناور مستقل هوشمند
# =====================================================================
class FloatingWindow(QWidget):
    def __init__(self, captured_text: str, config: AppConfig, available_models: List[str]):
        super().__init__()
        self.captured_text = captured_text
        self.config = config
        self.available_models = available_models
        
        # مشخص کردن حالت پیش‌فرض اول سیستم
        self.current_mode = "correction"
        if self.config.modes:
            available_modes = list(self.config.modes.keys())
            if "correction" in available_modes:
                self.current_mode = "correction"
            elif available_modes:
                self.current_mode = available_modes[0]

        # تنظیم ویژگی بدون فریم و همواره بالا بودن پنجره
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(QSS)

        # ابعاد دقیق پنجره
        self.resize(680, 560)
        
        # تنظیم موقعیت پنجره بر اساس موقعیت ماوس
        cursor_pos = QCursor.pos()
        target_x = cursor_pos.x() + 15
        target_y = cursor_pos.y() + 15
        
        screen = QApplication.primaryScreen().geometry()
        if target_x + self.width() > screen.width():
            target_x = cursor_pos.x() - self.width() - 15
        if target_y + self.height() > screen.height():
            target_y = cursor_pos.y() - self.height() - 15

        self.move(max(10, target_x), max(10, target_y))

        self.setup_ui()
        self.start_processing_pipeline()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.setSpacing(0)

        # ۱. طراحی هدر بار سفارشی
        header = HeaderBar(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 10, 0)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("CloseBtn")
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)

        header_layout.addStretch()

        title_lbl = QLabel("دستیار هوشمند متن AI")
        title_lbl.setObjectName("TitleLabel")
        header_layout.addWidget(title_lbl)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)
        self.status_dot.setStyleSheet("border-radius: 6px; background-color: #F38BA8;")
        header_layout.addWidget(self.status_dot)

        main_layout.addWidget(header)

        # فریم میانی محتوا
        content_frame = QFrame()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(10)

        # ۲. کنترلر بالایی مدل
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        self.model_combo = QComboBox()
        for m in self.available_models:
            self.model_combo.addItem(m)
        self.model_combo.setCurrentText(self.config.default_model)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        
        control_layout.addWidget(self.model_combo)
        control_layout.addStretch()
        
        model_label = QLabel("مدل فعال:")
        control_layout.addWidget(model_label)
        content_layout.addLayout(control_layout)

        # ۳. باکس پیش‌نمایش متن ورودی با چیدمان نیتیو راست‌به‌چپ
        preview_snippet = (self.captured_text[:110] + '...') if len(self.captured_text) > 110 else self.captured_text
        self.preview_lbl = QLineEdit()
        self.preview_lbl.setObjectName("PreviewLine")
        self.preview_lbl.setReadOnly(True)
        self.preview_lbl.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.preview_lbl.setText(f"متن ورودی: {preview_snippet}")
        content_layout.addWidget(self.preview_lbl)

        # ۴. تب‌بند کلیدها با چیدمان جدولی منظم ۴ ستونه و شکست ردیف پویا
        tab_widget = QWidget()
        tab_layout = QGridLayout(tab_widget)
        tab_layout.setContentsMargins(0, 5, 0, 5)
        tab_layout.setSpacing(6)

        MAX_COLUMNS = 4
        self.mode_buttons = {}

        for index, (mode_id, mode_info) in enumerate(self.config.modes.items()):
            row = index // MAX_COLUMNS
            col = index % MAX_COLUMNS
            col_rtl = MAX_COLUMNS - 1 - col  # چیدمان منظم بر اساس ساختار راست‌چین فارسی
            
            btn = QPushButton(mode_info.get("label", mode_id))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            if mode_id == self.current_mode:
                btn.setStyleSheet("background-color: #89B4FA; color: #11111B;")
            else:
                btn.setStyleSheet("background-color: #313244; color: #CDD6F4;")
                
            btn.clicked.connect(lambda checked, m=mode_id: self.set_mode(m))
            tab_layout.addWidget(btn, row, col_rtl)
            self.mode_buttons[mode_id] = btn

        content_layout.addWidget(tab_widget)

        # ۵. باکس نمایش خروجی با دایرکشن راست‌چین کاملاً طبیعی و نیتیو
        self.text_area = QTextEdit()
        self.text_area.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        content_layout.addWidget(self.text_area)

        # ۶. فریم دکمه‌های پایینی عملیات
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(0, 5, 0, 0)
        
        accept_btn = QPushButton("✓ اعمال و جایگذاری")
        accept_btn.setObjectName("AcceptButton")
        accept_btn.setFixedHeight(36)
        accept_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        accept_btn.clicked.connect(self.on_paste_replace)
        
        copy_btn = QPushButton("کپی خروجی")
        copy_btn.setFixedHeight(36)
        copy_btn.setFixedWidth(110)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self.on_copy)

        cancel_btn = QPushButton("بیخیال")
        cancel_btn.setObjectName("CancelButton")
        cancel_btn.setFixedHeight(36)
        cancel_btn.setFixedWidth(90)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.close)

        btn_bar.addWidget(cancel_btn)
        btn_bar.addWidget(copy_btn)
        btn_bar.addWidget(accept_btn)
        content_layout.addLayout(btn_bar)

        main_layout.addWidget(content_frame)

    def on_model_changed(self, model_name: str):
        self.config.default_model = model_name
        self.config.save()
        self.trigger_processing()

    def set_mode(self, selected_mode: str):
        self.current_mode = selected_mode
        for m, btn in self.mode_buttons.items():
            if m == selected_mode:
                btn.setStyleSheet("background-color: #89B4FA; color: #11111B;")
            else:
                btn.setStyleSheet("background-color: #313244; color: #CDD6F4;")
        self.trigger_processing()

    def trigger_processing(self):
        self.text_area.setReadOnly(True)
        self.text_area.setPlainText("در حال پردازش و بهینه‌سازی متن توسط هوش مصنوعی...\nلطفاً شکیبا باشید.")
        
        target_model = self.model_combo.currentText()

        def response_callback(response_text: str, is_success: bool):
            self.text_area.setReadOnly(False)
            self.text_area.setPlainText(response_text)

        threading.Thread(
            target=self.parent_api_call_bridge,
            args=(self.captured_text, target_model, self.current_mode, response_callback),
            daemon=True
        ).start()

    def parent_api_call_bridge(self, text, model, mode, callback):
        url = f"http://{self.config.ollama_host}:{self.config.ollama_port}/api/generate"
        mode_info = self.config.modes.get(mode, {})
        
        if "prompt_to_fa" in mode_info and "prompt_to_en" in mode_info:
            if is_text_mostly_persian(text):
                system_prompt = mode_info["prompt_to_en"]
            else:
                system_prompt = mode_info["prompt_to_fa"]
        else:
            system_prompt = mode_info.get("prompt", "You are a helpful assistant.")

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
                QTimer.singleShot(0, lambda: callback(result_text, True))
        except urllib.error.URLError:
            funny_error = (
                "عذر می‌خوام! 😅 مثل اینکه هوش مصنوعی در حال چرت زدنه یا کلاً خاموشه!\n\n"
                "لطفاً با آقای حسنی تماس بگیر تا زنده‌اش کنه. ☎️ داخلیش ۹۰۱ هست!"
            )
            QTimer.singleShot(0, lambda: callback(funny_error, False))
        except Exception as e:
            QTimer.singleShot(0, lambda: callback(f"خطای پردازش ناموفق:\n{str(e)}", False))

    def on_copy(self):
        content = self.text_area.toPlainText().strip()
        if content and "در حال پردازش" not in content and "عذر می‌خوام" not in content:
            QApplication.clipboard().setText(content)

    def on_paste_replace(self):
        content = self.text_area.toPlainText().strip()
        if content and "در حال پردازش" not in content and "عذر می‌خوام" not in content:
            QApplication.clipboard().setText(content)
            self.close()
            
            def run_async_paste():
                time.sleep(0.2)
                keyboard_controller.press(Key.ctrl)
                keyboard_controller.press('v')
                time.sleep(0.05)
                keyboard_controller.release('v')
                keyboard_controller.release(Key.ctrl)

            threading.Thread(target=run_async_paste, daemon=True).start()

    def start_processing_pipeline(self):
        def on_ping_complete(online: bool):
            if online:
                self.status_dot.setStyleSheet("border-radius: 6px; background-color: #A6E3A1;")
            else:
                self.status_dot.setStyleSheet("border-radius: 6px; background-color: #F38BA8;")
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
                    QTimer.singleShot(0, lambda: callback(True))
                    return
            QTimer.singleShot(0, lambda: callback(False))
        except Exception:
            QTimer.singleShot(0, lambda: callback(False))

# =====================================================================
# پنجره تنظیمات سیستم به سبک مدرن Qt
# =====================================================================
class SettingsWindow(QWidget):
    def __init__(self, config: AppConfig, start_hotkey_listener_cb):
        super().__init__()
        self.config = config
        self.start_hotkey_listener_cb = start_hotkey_listener_cb
        
        self.setWindowTitle("تنظیمات سیستم")
        self.setFixedSize(400, 320)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(QSS)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(QLabel("آدرس آی‌پی سرور Ollama:"))
        self.host_entry = QLineEdit()
        self.host_entry.setText(self.config.ollama_host)
        layout.addWidget(self.host_entry)

        layout.addWidget(QLabel("پورت سرور:"))
        self.port_entry = QLineEdit()
        self.port_entry.setText(self.config.ollama_port)
        layout.addWidget(self.port_entry)

        layout.addWidget(QLabel("کلید میانبر سیستم (مانند <ctrl>+<alt>+x):"))
        self.hotkey_entry = QLineEdit()
        self.hotkey_entry.setText(self.config.hotkey_str)
        layout.addWidget(self.hotkey_entry)

        layout.addSpacing(15)

        save_btn = QPushButton("ذخیره تنظیمات")
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)

    def save_settings(self):
        self.config.ollama_host = self.host_entry.text().strip()
        self.config.ollama_port = self.port_entry.text().strip()
        
        old_hotkey = self.config.hotkey_str
        new_hotkey = self.hotkey_entry.text().strip()
        self.config.hotkey_str = new_hotkey
        self.config.save()
        
        if old_hotkey != new_hotkey:
            self.start_hotkey_listener_cb()
            
        self.close()
        QMessageBox.information(self, "ذخیره موفق", "تنظیمات با موفقیت ذخیره شد و میانبر جدید فعال گردید.")

# =====================================================================
# کلاس سیگنال‌ها برای ارتباط امن threadها با رابط کاربری اصلی
# =====================================================================
class ThreadBridge(QObject):
    captured = pyqtSignal(str)
    no_selection = pyqtSignal()

# =====================================================================
# کلاس اصلی مدیریت برنامه و سیستم ترِی بومی
# =====================================================================
class ModernAssistantApp(QObject):
    def __init__(self, q_app: QApplication):
        super().__init__()
        self.q_app = q_app
        self.config = AppConfig.load()
        
        self.available_models: List[str] = [self.config.default_model, "llama3"]
        self.listener: Optional[keyboard.Listener] = None
        self.tray_icon: Optional[QSystemTrayIcon] = None
        
        # تعریف بریج جهت دریافت تسک‌ها از threadهای دیگر و اجرای امن در ترد اصلی رابط کاربری
        self.bridge = ThreadBridge()
        self.bridge.captured.connect(self.show_floating_window)
        self.bridge.no_selection.connect(self.show_no_selection_warning)
        
        self.start_hotkey_listener()
        self.setup_tray_icon()

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
        # انجام فرآیند کپچر در Thread مجزا جهت جلوگیری از فریز شدن سیستم
        def async_capture():
            selected_text = self.capture_selected_text()
            if selected_text:
                self.bridge.captured.emit(selected_text)
            else:
                self.bridge.no_selection.emit()
        
        threading.Thread(target=async_capture, daemon=True).start()

    def show_floating_window(self, selected_text: str):
        self.win = FloatingWindow(selected_text, self.config, self.available_models)
        self.win.show()

    def show_no_selection_warning(self):
        msg = QMessageBox()
        msg.setWindowTitle("عدم شناسایی متن")
        msg.setText("متنی جهت ویرایش یافت نشد.\nلطفاً ابتدا بخشی از یک متن را در نرم‌افزار خود به حالت انتخاب (Highlight) درآورید و سپس کلید میانبر را فشار دهید.")
        msg.setStyleSheet(QSS)
        msg.exec()

    def capture_selected_text(self) -> Optional[str]:
        time.sleep(0.3)
        clipboard = QApplication.clipboard()
        
        try:
            old_clip = clipboard.text()
        except Exception:
            old_clip = ""

        clipboard.clear()

        keyboard_controller.press(Key.ctrl)
        keyboard_controller.press('c')
        time.sleep(0.15)
        keyboard_controller.release('c')
        keyboard_controller.release(Key.ctrl)
        time.sleep(0.1)

        try:
            new_clip = clipboard.text()
            if new_clip and new_clip.strip():
                return new_clip.strip()
        except Exception:
            pass
        return None

    def create_tray_icon(self) -> QIcon:
        """ترسیم بومی آیکون ترِی بدون نیاز به لود عکس یا وابستگی به PIL"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#89B4FA"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(12, 12, 40, 40)
        painter.end()
        
        return QIcon(pixmap)

    def setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.create_tray_icon())
        self.tray_icon.setToolTip("دستیار هوشمند متن")

        tray_menu = QMenu()
        tray_menu.setStyleSheet(QSS)

        settings_action = QAction("تنظیمات", self)
        settings_action.triggered.connect(self.show_settings_window)
        tray_menu.addAction(settings_action)

        exit_action = QAction("خروج", self)
        exit_action.triggered.connect(self.cleanup_and_exit)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def show_settings_window(self):
        self.settings_win = SettingsWindow(self.config, self.start_hotkey_listener)
        self.settings_win.show()

    def cleanup_and_exit(self):
        if self.listener:
            self.listener.stop()
        if self.tray_icon:
            self.tray_icon.hide()
        self.q_app.quit()

# =====================================================================
# تنظیم استارت‌آپ خودکار ویندوز
# =====================================================================
def register_in_startup() -> bool:
    if sys.platform != "win32":
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
    if len(sys.argv) > 1 and sys.argv[1] == "--startup":
        success = register_in_startup()
        if success:
            print("برنامه با موفقیت به استارت‌آپ ویندوز اضافه شد.")
        else:
            print("عملیات ناموفق بود.")
        sys.exit(0)

    # شروع موتور اصلی برنامه Qt
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    
    app = ModernAssistantApp(qt_app)
    
    sys.exit(qt_app.exec())
