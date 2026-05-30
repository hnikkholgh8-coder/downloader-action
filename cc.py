import sys
import os
import re
import time
from PIL import Image, ImageDraw
import pyperclip
from pynput.keyboard import Controller, Key, GlobalHotKeys
import pystray

# نگاشت منطبق بر کیبورد فارسی استاندارد ویندوز (Windows Layout)
EN_TO_FA = {
    'q': 'ض', 'w': 'ص', 'e': 'ث', 'r': 'ق', 't': 'ف', 'y': 'غ', 'u': 'ع', 'i': 'ه', 'o': 'خ', 'p': 'ح', '[': 'ج', ']': 'چ', '\\': 'پ',
    'a': 'ش', 's': 'س', 'd': 'ی', 'f': 'ب', 'g': 'ل', 'h': 'ا', 'j': 'ت', 'k': 'ن', 'l': 'م', ';': 'ک', "'": 'گ',
    'z': 'ظ', 'x': 'ط', 'c': 'ز', 'v': 'ر', 'b': 'ذ', 'n': 'د', 'm': 'ئ', ',': 'و', '.': '.', '/': '/',
    'Q': 'َ', 'W': 'ً', 'E': 'ُ', 'R': 'ٌ', 'T': 'لإ', 'Y': 'إ', 'U': 'أ', 'I': 'ِ', 'O': 'ٍ', 'P': 'ّ', '{': '[', '}': ']', '|': 'ژ',
    'A': 'ِ', 'S': 'ٍ', 'D': ']', 'F': '[', 'G': 'لأ', 'H': 'آ', 'J': 'ـ', 'K': '«', 'L': '»', ':': ':', '"': '"',
    'Z': 'ة', 'X': 'ی', 'C': 'ژ', 'V': 'ؤ', 'B': 'لا', 'N': 'أ', 'M': 'ء', '<': '>', '>': '<', '?': '؟'
}

# نگاشت صریح و بدون تداخل فارسی به انگلیسی (اولویت با حروف کوچک)
FA_TO_EN = {
    'ض': 'q', 'ص': 'w', 'ث': 'e', 'ق': 'r', 'ف': 't', 'غ': 'y', 'ع': 'u', 'ه': 'i', 'خ': 'o', 'ح': 'p', 'ج': '[', 'چ': ']', 'پ': '\\',
    'ش': 'a', 'س': 's', 'ی': 'd', 'ب': 'f', 'ل': 'g', 'ا': 'h', 'ت': 'j', 'ن': 'k', 'م': 'l', 'ک': ';', 'گ': "'",
    'ظ': 'z', 'ط': 'x', 'ز': 'c', 'ر': 'v', 'ذ': 'b', 'د': 'n', 'ئ': 'm', 'و': ',', '٫': '.', '؟': '?',
    
    # کاراکترهایی که حتماً با شیفت تایپ می‌شوند
    'آ': 'H',
    'ژ': 'C',  # Shift + C در ویندوز
    'ء': 'M',
    'أ': 'N',
    'إ': 'B',
    'ؤ': 'V',
    '«': 'K',
    '»': 'L',
    'ة': 'Z',
    '؛': ';',
    'ي': 'd',
    'ك': ';',
}

keyboard = Controller()

def safe_clip_get(retries=5, delay=0.05):
    for _ in range(retries):
        try:
            return pyperclip.paste()
        except Exception:
            time.sleep(delay)
    return ""

def safe_clip_set(text, retries=5, delay=0.05):
    for _ in range(retries):
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            time.sleep(delay)
    return False

def convert_text(text):
    if not text:
        return text

    # شمارش حروف الفبا جهت تشخیص زبان مبدا
    fa_count = len(re.findall(r'[\u0600-\u06FF]', text))
    en_count = len(re.findall(r'[a-zA-Z]', text))

    result = []
    if fa_count >= en_count:
        # تبدیل فارسی به انگلیسی با اولویت حروف کوچک تعیین شده
        for char in text:
            result.append(FA_TO_EN.get(char, char))
    else:
        # تبدیل انگلیسی به فارسی با تفکیک حروف بزرگ و کوچک
        for char in text:
            result.append(EN_TO_FA.get(char, char))

    return "".join(result)

def on_activate():
    try:
        time.sleep(0.3)

        # آزاد کردن کلیدهای کنترلی سیستم جهت پیشگیری از قفل شدن کلیدها
        for key in [Key.ctrl, Key.shift, Key.alt, Key.cmd]:
            try:
                keyboard.release(key)
            except Exception:
                pass

        old_clipboard = safe_clip_get()
        safe_clip_set("")

        # شبیه‌سازی کپی
        keyboard.press(Key.ctrl)
        keyboard.press('c')
        time.sleep(0.08)
        keyboard.release('c')
        keyboard.release(Key.ctrl)

        time.sleep(0.12)
        selected_text = safe_clip_get()

        if not selected_text.strip():
            safe_clip_set(old_clipboard)
            return

        corrected_text = convert_text(selected_text)

        if safe_clip_set(corrected_text):
            # شبیه‌سازی چسباندن
            keyboard.press(Key.ctrl)
            keyboard.press('v')
            time.sleep(0.08)
            keyboard.release('v')
            keyboard.release(Key.ctrl)

        time.sleep(0.15)
        safe_clip_set(old_clipboard)

    except Exception as e:
        # مدیریت خطاهای احتمالی سیستم‌عامل برای پایداری پردازش پس‌زمینه
        pass

def create_image():
    image = Image.new('RGB', (64, 64), color=(44, 62, 80))
    dc = ImageDraw.Draw(image)
    dc.rectangle([10, 22, 54, 42], outline=(236, 240, 241), width=3)
    dc.rectangle([15, 27, 21, 31], fill=(236, 240, 241))
    dc.rectangle([25, 27, 31, 31], fill=(236, 240, 241))
    dc.rectangle([35, 27, 41, 31], fill=(236, 240, 241))
    dc.rectangle([20, 35, 44, 38], fill=(236, 240, 241))
    return image

def setup_tray():
    def on_exit(icon, item):
        icon.stop()
        hotkey_listener.stop()

    icon_image = create_image()
    menu = pystray.Menu(pystray.MenuItem('Exit', on_exit))
    
    tooltip_text = "من زنده‌ام!\nمتن را انتخاب کنید و کلیدهای Ctrl+Shift+K را بزنید."
    
    icon = pystray.Icon("keyboard_converter", icon_image, title=tooltip_text, menu=menu)
    icon.run()

def add_to_startup():
    """افزودن برنامه به استارتاپ ویندوز از طریق رجیستری کاربر جاری"""
    if os.name != 'nt':
        print("ثبت در استارتاپ فقط در سیستم‌عامل ویندوز پشتیبانی می‌شود.")
        return False
    
    import winreg
    
    # تعیین مسیر دقیق برنامه (چه به صورت اسکریپت پایتون و چه فایل exe کامپایل شده)
    if getattr(sys, 'frozen', False):
        app_path = os.path.abspath(sys.executable)
    else:
        app_path = f'"{os.path.abspath(sys.executable)}" "{os.path.abspath(sys.argv[0])}"'
        
    key_name = "WinKeyboardConverter"
    
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, key_name, 0, winreg.REG_SZ, app_path)
        winreg.CloseKey(key)
        print("برنامه با موفقیت به استارتاپ ویندوز اضافه شد.")
        return True
    except Exception as e:
        print(f"خطا در ثبت استارتاپ: {e}")
        return False

if __name__ == "__main__":
    # بررسی سوئیچ استارتاپ
    if "--startup" in sys.argv:
        add_to_startup()

    # راه‌اندازی لیسنر
    hotkey_listener = GlobalHotKeys({
        '<ctrl>+<shift>+k': on_activate
    })
    hotkey_listener.start()

    # اجرای آیکون Tray
    setup_tray()
