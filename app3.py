import os
import json
import time
import threading
import sys
import logging
import re
import difflib
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from typing import Optional, List

# وارد کردن ابزارهای PyQt6 با مدیریت خطا
try:
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
        QFrame, QLabel, QPushButton, QTextEdit, QLineEdit, 
        QComboBox, QGridLayout, QMessageBox, QMenu, QSystemTrayIcon
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint
    from PyQt6.QtGui import QIcon, QAction, QCursor, QPixmap, QPainter, QColor
except ImportError as e:
    print(f"Error importing PyQt6: {e}. Please install PyQt6 using 'pip install PyQt6'")
    sys.exit(1)

# وارد کردن کتابخانه‌های مدیریت کیبورد با مدیریت خطا
try:
    from pynput import keyboard
    from pynput.keyboard import Key, Controller
except ImportError as e:
    print(f"Error importing pynput: {e}. Please install pynput using 'pip install pynput'")
    sys.exit(1)

# وارد کردن کتابخانه requests با مدیریت خطا
try:
    import requests
except ImportError as e:
    print(f"Error importing requests: {e}. Please install requests using 'pip install requests'")
    sys.exit(1)

if sys.platform == "win32":
    import winreg

# =====================================================================
# مسیر استاندارد ذخیره‌سازی داده‌های برنامه در AppData
# =====================================================================
APPDATA_DIR = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AI-Text-Assistant")
try:
    os.makedirs(APPDATA_DIR, exist_ok=True)
except Exception as e:
    pass

CONFIG_FILE = os.path.join(APPDATA_DIR, "config.json")
OLLAMA_API_TOKEN: Optional[str] = "YOUR_OLLAMA_SECURE_TOKEN_HERE"

# =====================================================================
# تنظیمات لاگ سیستم و چرخش خودکار فایل لاگ (۱۰ مگابایت حجم و چرخش ۲۰تایی)
# حذف خروجی StreamHandler جهت بیلد تمیز با Nuitka
# =====================================================================
log_file_path = os.path.join(APPDATA_DIR, "assistant_debug.log")
file_logger_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=10 * 1024 * 1024,  # معادل ۱۰ مگابایت حد نصاب حجم فایل
    backupCount=20,             # حفظ فایل‌های پشتیبان تا ۲۰ دوره
    encoding="utf-8"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[file_logger_handler]
)
logger = logging.getLogger("AI-Assistant")

# =====================================================================
# شیوه استایل‌دهی سراسری برنامه (QSS)
# =====================================================================
QSS = """
QWidget {
    background-color: #1E1E2E;
    color: #CDD6F4;
    font-family: 'Calibri', 'B Nazanin', 'Segoe UI', 'Tahoma', sans-serif;
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
    font-size: 13px;
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
    font-size: 13px;
}
QPushButton#AcceptButton:hover {
    background-color: #94E2D5;
}
QPushButton#CancelButton {
    background-color: #45475A;
    color: #F38BA8;
    font-size: 13px;
}
QPushButton#CancelButton:hover {
    background-color: #F38BA8;
    color: #11111B;
}
QPushButton#RetryButton {
    background-color: #F9E2AF;
    color: #11111B;
    font-size: 13px;
}
QPushButton#RetryButton:hover {
    background-color: #F5E0DC;
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
    font-size: 12px;
}
QComboBox {
    background-color: #313244;
    color: #CDD6F4;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 3px 20px 3px 5px;
    font-size: 12px;
}
QComboBox QAbstractItemView {
    background-color: #11111B;
    selection-background-color: #89B4FA;
    selection-color: #11111B;
    font-size: 12px;
}
"""

DEFAULT_MODES = {
    "correction": {
        "label": "ویراستاری رسمی",
        "model": "gemma3:1b",
        "prompt": (
            "SYSTEM MANDATE: You are a professional Persian copyeditor. Rewrite the input text "
            "into polished, grammatically flawless, elegant, and formal Persian.\n"
            "STRICT RULES:\n"
            "- Correct spelling mistakes, grammatical errors, and typos.\n"
            "- Apply proper Persian spacing and standard pseudo-spaces (use نیم‌فاصله where appropriate).\n"
            "- Maintain all core objectives, facts, and underlying context of the source text.\n"
            "- CRITICAL: Do NOT write any conversational text, introductory remarks, explanations, or notes. "
            "Output ONLY the corrected text payload."
        )
    },
    "spelling": {
        "label": "غلط‌گیری املایی",
        "model": "gemma3:1b",
        "prompt": (
            "SYSTEM MANDATE: You are an objective Persian spelling correction engine. Your task is to identify "
            "and fix literal orthographic errors, typos, and keyboard slips in the input text.\n"
            "STRICT RULES:\n"
            "- Fix literal typos (e.g., correcting 'کناز' to 'کنار' and 'ارتباطبا' to 'ارتباط با').\n"
            "- Never change the stylistic flow of the text; do not make casual text formal.\n"
            "- Do not rewrite structural sentences or alter the author's choice of words.\n"
            "- CRITICAL: Output ONLY the spelling-corrected plain text. "
            "Do not output markdown code-blocks, notes, or intros."
        )
    },
    "translation": {
        "label": "ترجمه هوشمند",
        "model": "translategemma:4b",
        "prompt_to_fa": (
            "SYSTEM MANDATE: You are an expert English-to-Persian translator. "
            "Translate the source text into fluent, natural, and accurate Persian prose.\n"
            "STRICT RULES:\n"
            "- Preserve exact source formatting, paragraph structures, and data.\n"
            "- Do not translate proper technical terminology unless standard Persian equivalents exist.\n"
            "- CRITICAL: Return ONLY the Persian translation. Do not write intros, explanations, or meta-comments."
        ),
        "prompt_to_en": (
            "SYSTEM MANDATE: You are an expert Persian-to-English translator. "
            "Translate the source text into fluent, natural, and accurate English prose.\n"
            "STRICT RULES:\n"
            "- Preserve exact source formatting, paragraph structures, and data.\n"
            "- CRITICAL: Return ONLY the English translation. Do not write intros, explanations, or meta-comments."
        )
    },
    "summary": {
        "label": "خلاصه‌سازی",
        "model": "gemma3:1b",
        "prompt": (
            "SYSTEM MANDATE: You are a precise summarizing utility. Condense the input text, extracting "
            "only the critical arguments, essential details, and core context in the same language as the input.\n"
            "STRICT RULES:\n"
            "- Keep the output highly concise, direct, and structured.\n"
            "- CRITICAL: Output ONLY the summary. Do not include markdown wraps, greeting headers, or post-process explanations."
        )
    },
    "official_letter": {
        "label": "نامه اداری",
        "model": "gemma3:1b",
        "prompt": (
            "دستورالعمل سیستم: شما یک متخصص ارشد در نگارش مکاتبات اداری، حقوقی و رسمی هستید. "
            "متن ورودی را بازنویسی کرده و آن را در قالب یک نامه اداری سنجیده، بسیار محترمانه و قانون‌مند فرمت‌دهی کنید.\n"
            "قوانین جدی:\n"
            "- از تظاهر به گفتگو با کاربر، تعارفات اضافی در ابتدا یا انتهای خروجی هوش مصنوعی خودداری کنید.\n"
            "- صرفاً نامه نهایی را با رعایت ساختار پاراگراف‌بندی و فاصله‌گذاری مناسب خروجی دهید."
        )
    }
}

keyboard_controller = Controller()

# =====================================================================
# مدیریت تنظیمات نرم‌افزار
# =====================================================================
@dataclass
class AppConfig:
    ollama_host: str = "192.168.20.65"
    ollama_port: str = "11434"
    hotkey_str: str = "<ctrl>+<alt>+x"
    default_model: str = "gemma3:1b"
    last_active_mode: str = "correction"  # فیلد جدید جهت نگهداری آخرین تب فعال کاربر
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
            "last_active_mode": self.last_active_mode,
            "modes": self.modes
        }

    @classmethod
    def load(cls) -> "AppConfig":
        logger.info("آغاز بارگذاری تنظیمات سیستم (آبشاری)...")
        
        # ۱. تلاش برای دریافت از آدرس آنلاین با تایم‌اوت کوتاه
        remote_url = "http://botconf.dev.expplus.ir"
        try:
            response = requests.get(remote_url, timeout=3.5)
            if response.status_code == 200:
                data = response.json()
                logger.info("پیکربندی با موفقیت از سرور آنلاین دریافت و اعمال شد.")
                config = cls(**data)
                config.save()
                return config
        except Exception as e:
            logger.warning(f"عدم امکان برقراری ارتباط با سرور آنلاین دریافت کانفیگ: {e}")

        # ۲. تلاش برای خواندن فایل لوکال ذخیره شده در AppData
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "modes" not in data or not isinstance(data["modes"], dict):
                        data["modes"] = DEFAULT_MODES.copy()
                    if "last_active_mode" not in data:
                        data["last_active_mode"] = "correction"
                    logger.info("تنظیمات با موفقیت از فایل محلی AppData لود گردید.")
                    return cls(**data)
            except Exception as e:
                logger.error(f"خطا در تجزیه فایل محلی تنظیمات: {e}")
        
        # ۳. استفاده از پیش‌فرض‌های هاردکد شده برنامه در صورت عدم دسترسی به بقیه موارد
        logger.info("ساخت فایل پیکربندی پیش‌فرض در مسیر سیستم...")
        config = cls()
        config.save()
        return config

    def save(self) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=4, ensure_ascii=False)
            logger.info("تنظیمات در فایل لوکال آپدیت گردید.")
        except Exception as e:
            logger.error(f"خطا در ثبت و نگهداری فایل تنظیمات: {e}")

# =====================================================================
# ابزار مقایسه متون جهت تشخیص و هایلایت تفاوت‌ها با حفظ ساختار خطوط
# =====================================================================
def highlight_differences(original: str, corrected: str) -> str:
    """تولید خروجی HTML برای هایلایت تغییرات با حفظ دقیق شکستگی خطوط"""
    try:
        def tokenize(text):
            return re.findall(r'\S+|\n', text)
            
        orig_tokens = tokenize(original)
        corr_tokens = tokenize(corrected)
        matcher = difflib.SequenceMatcher(None, orig_tokens, corr_tokens)
        html_output = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for tok in orig_tokens[i1:i2]:
                    if tok == '\n':
                        html_output.append('<br>')
                    else:
                        html_output.append(tok)
            elif tag == 'replace':
                del_span = " ".join(orig_tokens[i1:i2]).replace('\n', '<br>')
                ins_span = " ".join(corr_tokens[j1:j2]).replace('\n', '<br>')
                html_output.append(f'<span style="background-color: #F38BA8; color: #11111B; text-decoration: line-through;">{del_span}</span>')
                html_output.append(f'<span style="background-color: #A6E3A1; color: #11111B; font-weight: bold;">{ins_span}</span>')
            elif tag == 'delete':
                del_span = " ".join(orig_tokens[i1:i2]).replace('\n', '<br>')
                html_output.append(f'<span style="background-color: #F38BA8; color: #11111B; text-decoration: line-through;">{del_span}</span>')
            elif tag == 'insert':
                ins_span = " ".join(corr_tokens[j1:j2]).replace('\n', '<br>')
                html_output.append(f'<span style="background-color: #A6E3A1; color: #11111B; font-weight: bold;">{ins_span}</span>')

        raw_html = " ".join(html_output)
        raw_html = raw_html.replace(" <br> ", "<br>").replace(" <br>", "<br>").replace("<br> ", "<br>")
        return raw_html
    except Exception as e:
        logger.error(f"Error highlighting diffs: {e}")
        return corrected.replace('\n', '<br>')

# =====================================================================
# تشخیص زبان متن
# =====================================================================
def is_text_mostly_persian(text: str) -> bool:
    try:
        persian_chars = sum(1 for char in text if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F')
        total_chars = len(text.strip()) or 1
        return (persian_chars / total_chars) > 0.25
    except Exception:
        return True

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
# کلاس سیگنال‌ها برای ترد پس‌زمینه پنجره شناور خروجی
# =====================================================================
class ProcessingSignals(QObject):
    ping_result = pyqtSignal(bool)
    api_result = pyqtSignal(str, bool, int)

# =====================================================================
# پنجره شناور مستقل هوشمند
# =====================================================================
class FloatingWindow(QWidget):
    def __init__(self, captured_text: str, config: AppConfig, available_models: List[str]):
        super().__init__()
        logger.info("در حال ساخت رابط کاربری شناور...")
        self.captured_text = captured_text
        self.config = config
        self.available_models = available_models
        self.raw_output_text = ""
        
        self.response_cache = {}
        self.current_request_id = 0
        
        # بازخوانی آخرین تب فعال ذخیره شده در فایل تنظیمات به عنوان پیش‌فرض باز شدن برنامه
        self.current_mode = self.config.last_active_mode
        if self.config.modes and self.current_mode not in self.config.modes:
            available_modes = list(self.config.modes.keys())
            if "correction" in available_modes:
                self.current_mode = "correction"
            elif available_modes:
                self.current_mode = available_modes[0]

        self.signals = ProcessingSignals()
        self.signals.ping_result.connect(self.on_ping_complete)
        self.signals.api_result.connect(self.on_api_complete)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setStyleSheet(QSS)
        self.resize(680, 580)
        
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

        # هدر بار
        header = HeaderBar(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 10, 0)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("CloseBtn")
        close_btn.setFixedSize(30, 30)
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)

        header_layout.addStretch()

        title_lbl = QLabel("دستیار هوشمند اکسیرپویان")
        title_lbl.setObjectName("TitleLabel")
        header_layout.addWidget(title_lbl)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)
        self.status_dot.setStyleSheet("border-radius: 6px; background-color: #F38BA8;")
        header_layout.addWidget(self.status_dot)

        main_layout.addWidget(header)

        # فریم اصلی محتوا
        content_frame = QFrame()
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(10)

        # کنترلر مدل فعال
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        self.model_combo = QComboBox()
        for m in self.available_models:
            self.model_combo.addItem(m)
        self.model_combo.setCurrentText(self.get_current_task_model())
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        
        control_layout.addWidget(self.model_combo)
        control_layout.addStretch()
        
        model_label = QLabel("مدل اختصاصی حالت:")
        control_layout.addWidget(model_label)
        content_layout.addLayout(control_layout)

        # نمایش پیش‌نمایش متن ورودی
        preview_snippet = (self.captured_text[:110] + '...') if len(self.captured_text) > 110 else self.captured_text
        self.preview_lbl = QLineEdit()
        self.preview_lbl.setObjectName("PreviewLine")
        self.preview_lbl.setReadOnly(True)
        self.preview_lbl.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.preview_lbl.setText(f"متن ورودی: {preview_snippet}")
        content_layout.addWidget(self.preview_lbl)

        # تب‌های چیدمان کلیدها
        tab_widget = QWidget()
        tab_layout = QGridLayout(tab_widget)
        tab_layout.setContentsMargins(0, 5, 0, 5)
        tab_layout.setSpacing(6)

        MAX_COLUMNS = 4
        self.mode_buttons = {}

        for index, (mode_id, mode_info) in enumerate(self.config.modes.items()):
            row = index // MAX_COLUMNS
            col = index % MAX_COLUMNS
            col_rtl = MAX_COLUMNS - 1 - col
            
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

        # باکس اصلی نمایش خروجی با جهت‌یابی مناسب راست‌به‌چپ
        self.text_area = QTextEdit()
        self.text_area.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        content_layout.addWidget(self.text_area)

        # برچسب پس‌زمینه نمایش نام مدل استفاده شده
        self.bg_model_info_lbl = QLabel()
        self.bg_model_info_lbl.setStyleSheet("color: #585b70; font-size: 11px; background: transparent; font-style: italic;")
        self.bg_model_info_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        content_layout.addWidget(self.bg_model_info_lbl)

        # نوار کلیدها در پایین پنجره
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(0, 5, 0, 0)
        
        accept_btn = QPushButton("✓ اعمال و جایگذاری")
        accept_btn.setObjectName("AcceptButton")
        accept_btn.setFixedHeight(36)
        accept_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        accept_btn.clicked.connect(self.on_paste_replace)
        
        copy_btn = QPushButton("کپی خروجی")
        copy_btn.setFixedHeight(36)
        copy_btn.setFixedWidth(100)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self.on_copy)

        retry_btn = QPushButton("↻ تلاش مجدد")
        retry_btn.setObjectName("RetryButton")
        retry_btn.setFixedHeight(36)
        retry_btn.setFixedWidth(100)
        retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        retry_btn.clicked.connect(self.on_retry_clicked)

        cancel_btn = QPushButton("بیخیال")
        cancel_btn.setObjectName("CancelButton")
        cancel_btn.setFixedHeight(36)
        cancel_btn.setFixedWidth(80)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.close)

        btn_bar.addWidget(cancel_btn)
        btn_bar.addWidget(retry_btn)
        btn_bar.addWidget(copy_btn)
        btn_bar.addWidget(accept_btn)
        content_layout.addLayout(btn_bar)

        main_layout.addWidget(content_frame)

    def get_current_task_model(self) -> str:
        try:
            mode_info = self.config.modes.get(self.current_mode, {})
            return mode_info.get("model", self.config.default_model)
        except Exception:
            return self.config.default_model

    def on_model_changed(self, model_name: str):
        try:
            logger.info(f"به‌روزرسانی مدل اختصاصی تسک به {model_name}")
            if self.current_mode in self.config.modes:
                self.config.modes[self.current_mode]["model"] = model_name
                self.config.save()
                
            if self.current_mode in self.response_cache:
                del self.response_cache[self.current_mode]
                
            self.trigger_processing()
        except Exception as e:
            logger.error(f"Error handling model change: {e}")

    def set_mode(self, selected_mode: str):
        try:
            logger.info(f"حالت تغییر یافت به: {selected_mode}")
            self.current_mode = selected_mode
            
            # ذخیره تب فعال فعلی به عنوان آخرین سربرگ انتخابی در فایل تنظیمات
            self.config.last_active_mode = selected_mode
            self.config.save()
            
            self.model_combo.blockSignals(True)
            self.model_combo.setCurrentText(self.get_current_task_model())
            self.model_combo.blockSignals(False)

            for m, btn in self.mode_buttons.items():
                if m == selected_mode:
                    btn.setStyleSheet("background-color: #89B4FA; color: #11111B;")
                else:
                    btn.setStyleSheet("background-color: #313244; color: #CDD6F4;")
            
            if self.current_mode in self.response_cache:
                logger.info("خروجی از حافظه کش خوانده شد.")
                self.render_response_content(self.response_cache[self.current_mode], True)
            else:
                self.trigger_processing()
        except Exception as e:
            logger.error(f"Error switching modes: {e}")

    def on_retry_clicked(self):
        try:
            if self.current_mode in self.response_cache:
                del self.response_cache[self.current_mode]
            self.trigger_processing()
        except Exception as e:
            logger.error(f"Error handling retry click: {e}")

    def trigger_processing(self):
        try:
            self.text_area.setReadOnly(True)
            self.text_area.setPlainText("در حال پردازش و بهینه‌سازی متن توسط هوش مصنوعی...\nلطفاً شکیبا باشید.")
            self.bg_model_info_lbl.setText("")
            
            self.current_request_id += 1
            request_id_to_send = self.current_request_id
            
            target_model = self.get_current_task_model()
            threading.Thread(
                target=self.parent_api_call_bridge,
                args=(self.captured_text, target_model, self.current_mode, request_id_to_send),
                daemon=True
            ).start()
        except Exception as e:
            logger.error(f"Error triggering processing thread: {e}")

    def parent_api_call_bridge(self, text, model, mode, request_id):
        url = f"http://{self.config.ollama_host}:{self.config.ollama_port}/api/generate"
        logger.info(f"ارسال درخواست {request_id} به وب‌سرویس {url} با مدل {model}")
        
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
            response = requests.post(url, json=payload, headers=headers, timeout=40)
            if response.status_code == 200:
                res_data = response.json()
                result_text = res_data.get("response", "خطای دریافت پاسخ").strip()
                self.signals.api_result.emit(result_text, True, request_id)
            else:
                self.signals.api_result.emit(f"خطای سرور Ollama: کد {response.status_code}", False, request_id)
        except requests.exceptions.RequestException as e:
            logger.error(f"عدم امکان اتصال به سرویس محلی Ollama: {e}")
            funny_error = (
                "عذر می‌خوام! 😅 مثل اینکه هوش مصنوعی در حال چرت زدنه یا کلاً خاموشه!\n\n"
                "لطفاً با آقای حسنی تماس بگیر تا زنده‌اش کنه. ☎️ داخلیش ۹۰۱ هست!"
            )
            self.signals.api_result.emit(funny_error, False, request_id)
        except Exception as e:
            logger.error(f"Error running inference logic: {e}")
            self.signals.api_result.emit(f"خطای پردازش ناموفق:\n{str(e)}", False, request_id)

    def on_api_complete(self, response_text: str, is_success: bool, request_id: int):
        try:
            if request_id != self.current_request_id:
                logger.warning(f"پاسخ منقضی شده درخواست {request_id} دریافت شد اما نادیده گرفته شد. شناسه فعلی: {self.current_request_id}")
                return

            if is_success:
                self.response_cache[self.current_mode] = response_text

            self.render_response_content(response_text, is_success)
        except Exception as e:
            logger.error(f"Error handling api completed event: {e}")

    def render_response_content(self, response_text: str, is_success: bool):
        try:
            self.text_area.setReadOnly(False)
            self.raw_output_text = response_text
            
            if is_success:
                if self.current_mode == "spelling":
                    diff_html = highlight_differences(self.captured_text, response_text)
                    styled_html = f'<div style="white-space: pre-wrap; font-family: Calibri, B Nazanin, Tahoma, sans-serif;">{diff_html}</div>'
                    self.text_area.setHtml(styled_html)
                else:
                    self.text_area.setPlainText(response_text)
                
                active_model = self.get_current_task_model()
                self.bg_model_info_lbl.setText(f"تولید شده با مدل: {active_model}")
            else:
                self.text_area.setPlainText(response_text)
                self.bg_model_info_lbl.setText("")
        except Exception as e:
            logger.error(f"Error rendering content into text area: {e}")

    def on_copy(self):
        try:
            content = self.raw_output_text if self.raw_output_text else self.text_area.toPlainText().strip()
            if content and "در حال پردازش" not in content and "عذر می‌خوام" not in content:
                logger.info("کپی خروجی در کلیپ‌بورد.")
                QApplication.clipboard().setText(content)
        except Exception as e:
            logger.error(f"Error copying to clipboard: {e}")

    def on_paste_replace(self):
        try:
            content = self.raw_output_text if self.raw_output_text else self.text_area.toPlainText().strip()
            if content and "در حال پردازش" not in content and "عذر می‌خوام" not in content:
                logger.info("تلاش برای جایگذاری خروجی متن...")
                QApplication.clipboard().setText(content)
                self.close()
                
                def run_async_paste():
                    try:
                        time.sleep(0.25)
                        keyboard_controller.press(Key.ctrl)
                        keyboard_controller.press('v')
                        time.sleep(0.05)
                        keyboard_controller.release('v')
                        keyboard_controller.release(Key.ctrl)
                    except Exception as child_ex:
                        logger.error(f"خطای شبیه‌سازی کلید پیست: {child_ex}")

                threading.Thread(target=run_async_paste, daemon=True).start()
        except Exception as e:
            logger.error(f"Error executing auto replacement: {e}")

    def start_processing_pipeline(self):
        threading.Thread(
            target=self.check_connection_internal,
            daemon=True
        ).start()

    def check_connection_internal(self):
        url_root = f"http://{self.config.ollama_host}:{self.config.ollama_port}/"
        url_tags = f"http://{self.config.ollama_host}:{self.config.ollama_port}/api/tags"
        
        headers = {}
        if OLLAMA_API_TOKEN and OLLAMA_API_TOKEN != "YOUR_OLLAMA_SECURE_TOKEN_HERE":
            headers["Authorization"] = f"Bearer {OLLAMA_API_TOKEN}"
            
        try:
            response = requests.get(url_root, headers=headers, timeout=4)
            if response.status_code == 200:
                try:
                    tags_res = requests.get(url_tags, headers=headers, timeout=4)
                    if tags_res.status_code == 200:
                        models = [m["name"] for m in tags_res.json().get("models", [])]
                        if models:
                            self.available_models = models
                except Exception as e:
                    logger.warning(f"عدم امکان واکشی لیست مدل‌ها: {e}")
                self.signals.ping_result.emit(True)
                return
            self.signals.ping_result.emit(False)
        except Exception as e:
            logger.warning(f"پینگ سرور با خطا روبرو شد: {e}")
            self.signals.ping_result.emit(False)

    def on_ping_complete(self, online: bool):
        try:
            if online:
                self.status_dot.setStyleSheet("border-radius: 6px; background-color: #A6E3A1;")
                
                self.model_combo.blockSignals(True)
                self.model_combo.clear()
                for m in self.available_models:
                    self.model_combo.addItem(m)
                self.model_combo.setCurrentText(self.get_current_task_model())
                self.model_combo.blockSignals(False)
            else:
                self.status_dot.setStyleSheet("border-radius: 6px; background-color: #F38BA8;")
            
            self.trigger_processing()
        except Exception as e:
            logger.error(f"Error handling ping evaluation: {e}")

# =====================================================================
# کلاس سیگنال‌ها برای ارتباط امن threadها با رابط کاربری اصلی
# =====================================================================
class ThreadBridge(QObject):
    trigger_capture = pyqtSignal()
    trigger_config_reload = pyqtSignal()

# =====================================================================
# کلاس اصلی مدیریت برنامه و سیستم ترِی بومی
# =====================================================================
class ModernAssistantApp(QObject):
    def __init__(self, q_app: QApplication):
        super().__init__()
        logger.info("آغاز فرآیند دستیار هوشمند...")
        self.q_app = q_app
        self.config = AppConfig.load()
        self._last_mtime = self.get_config_mtime()
        
        self.available_models: List[str] = [self.config.default_model, "gemma3:1b"]
        self.listener: Optional[keyboard.Listener] = None
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self.win = None
        
        self.bridge = ThreadBridge()
        self.bridge.trigger_capture.connect(self.run_capture_on_main_thread)
        self.bridge.trigger_config_reload.connect(self.on_config_reload_triggered)
        
        self.start_hotkey_listener()
        self.setup_tray_icon()
        self.setup_config_polling()

    def get_config_mtime(self) -> float:
        try:
            if os.path.exists(CONFIG_FILE):
                return os.path.getmtime(CONFIG_FILE)
        except Exception as e:
            logger.error(f"Error checking config mtime: {e}")
        return 0.0

    def setup_config_polling(self):
        self.config_timer = QTimer(self)
        self.config_timer.timeout.connect(self.poll_config_updates)
        self.config_timer.start(300000)

    def poll_config_updates(self):
        threading.Thread(target=self._async_config_checker, daemon=True).start()

    def _async_config_checker(self):
        config_changed = False
        remote_url = "http://botconf.dev.expplus.ir"
        try:
            response = requests.get(remote_url, timeout=3.5)
            if response.status_code == 200:
                remote_data = response.json()
                if remote_data != self.config.to_dict():
                    self.config = AppConfig(**remote_data)
                    self.config.save()
                    config_changed = True
                    logger.info("تنظیمات با نسخه سرور آنلاین همگام شد.")
        except Exception:
            pass

        if not config_changed:
            current_mtime = self.get_config_mtime()
            if current_mtime > self._last_mtime:
                self._last_mtime = current_mtime
                config_changed = True
                logger.info("تغییر فایل محلی تشخیص داده شد.")

        if config_changed:
            self.bridge.trigger_config_reload.emit()

    def on_config_reload_triggered(self):
        try:
            self.config = AppConfig.load()
            logger.info("تغییرات تنظیمات سیستم با موفقیت روی برنامه اعمال گردید.")
            self.start_hotkey_listener()
        except Exception as e:
            logger.error(f"Error reloading config: {e}")

    def start_hotkey_listener(self):
        try:
            if self.listener:
                self.listener.stop()
            
            logger.info(f"ثبت کلید میانبر: {self.config.hotkey_str}")
            hotkey_map = {
                self.config.hotkey_str: self.on_hotkey_triggered
            }
            self.listener = keyboard.GlobalHotKeys(hotkey_map)
            self.listener.start()
        except Exception as e:
            logger.error(f"خطا در ایجاد هوک کیبورد سیستم: {e}")

    def on_hotkey_triggered(self):
        self.bridge.trigger_capture.emit()

    def run_capture_on_main_thread(self):
        try:
            selected_text = self.capture_selected_text()
            if selected_text:
                self.show_floating_window(selected_text)
            else:
                self.show_no_selection_warning()
        except Exception as e:
            logger.error(f"Error running capture flow on main thread: {e}")

    def show_floating_window(self, selected_text: str):
        try:
            if self.win:
                try:
                    self.win.close()
                except Exception:
                    pass
            self.win = FloatingWindow(selected_text, self.config, self.available_models)
            self.win.show()
        except Exception as e:
            logger.error(f"Error showing main window: {e}")

    def show_no_selection_warning(self):
        try:
            msg = QMessageBox()
            msg.setWindowTitle("عدم شناسایی متن")
            msg.setText("متنی جهت ویرایش یافت نشد.\nلطفاً ابتدا بخشی از یک متن را در نرم‌افزار خود به حالت انتخاب (Highlight) درآورید و سپس کلید میانبر را فشار دهید.")
            msg.setStyleSheet(QSS)
            msg.exec()
        except Exception as e:
            logger.error(f"Error showing warning: {e}")

    def capture_selected_text(self) -> Optional[str]:
        try:
            time.sleep(0.25)
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

            new_clip = clipboard.text()
            if new_clip and new_clip.strip():
                return new_clip.strip()
        except Exception as e:
            logger.error(f"Error copying from active application: {e}")
        return None

    def create_tray_icon(self) -> QIcon:
        try:
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor("#89B4FA"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(12, 12, 40, 40)
            painter.end()
            return QIcon(pixmap)
        except Exception as e:
            logger.error(f"Error creating tray icon: {e}")
            return QIcon()

    def setup_tray_icon(self):
        try:
            logger.info("در حال تنظیم منوی Tray...")
            self.tray_icon = QSystemTrayIcon(self)
            self.tray_icon.setIcon(self.create_tray_icon())
            self.tray_icon.setToolTip("من سالم و سرحال در خدمت شما هستم")

            tray_menu = QMenu()
            tray_menu.setStyleSheet(QSS)

            exit_action = QAction("خروج", self)
            exit_action.triggered.connect(self.cleanup_and_exit)
            tray_menu.addAction(exit_action)

            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.show()
        except Exception as e:
            logger.error(f"Error in tray setup: {e}")

    def cleanup_and_exit(self):
        try:
            logger.info("خروج از برنامه...")
            if self.listener:
                self.listener.stop()
            if self.tray_icon:
                self.tray_icon.hide()
            self.q_app.quit()
        except Exception as e:
            logger.error(f"Error during application shutdown: {e}")
            sys.exit(0)

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
        logger.error(f"خطا در رجیستری ویندوز برای استارت‌آپ: {e}")
        return False

# =====================================================================
# شروع اجرای نرم‌افزار
# =====================================================================
if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--startup":
            success = register_in_startup()
            if success:
                logger.info("برنامه به منوی استارت‌آپ ویندوز اضافه شد.")
            sys.exit(0)

        qt_app = QApplication(sys.argv)
        qt_app.setQuitOnLastWindowClosed(False)
        
        app = ModernAssistantApp(qt_app)
        sys.exit(qt_app.exec())
    except Exception as e:
        logger.fatal(f"Fatal error in startup logic: {e}")
