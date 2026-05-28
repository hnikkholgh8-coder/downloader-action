import re
import time
from PIL import Image, ImageDraw
import pyperclip
from pynput.keyboard import Controller, Key, GlobalHotKeys
import pystray

# نگاشت منطبق بر کیبورد فارسی استاندارد ویندوز (Windows Layout)
EN_TO_FA = {
    # حروف کوچک انگلیسی به فارسی
    'q': 'ض', 'w': 'ص', 'e': 'ث', 'r': 'ق', 't': 'ف', 'y': 'غ', 'u': 'ع', 'i': 'ه', 'o': 'خ', 'p': 'ح', '[': 'ج', ']': 'چ', '\\': 'پ',
    'a': 'ش', 's': 'س', 'd': 'ی', 'f': 'ب', 'g': 'ل', 'h': 'ا', 'j': 'ت', 'k': 'ن', 'l': 'م', ';': 'ک', "'": 'g',
    'z': 'ظ', 'x': 'ط', 'c': 'ز', 'v': 'ر', 'b': 'ذ', 'n': 'د', 'm': 'ئ', ',': 'و', '.': '٫', '/': '؟',
    
    # حروف بزرگ انگلیسی (با Shift) به فارسی
    'Q': 'َ', 'W': 'ً', 'E': 'ُ', 'R': 'ٌ', 'T': 'لإ', 'Y': 'إ', 'U': 'أ', 'I': 'ِ', 'O': 'ٍ', 'P': 'ّ', '{': '[', '}': ']', '|': 'ژ',
    'A': 'ِ', 'S': 'ٍ', 'D': ']', 'F': '[', 'G': 'لأ', 'H': 'آ', 'J': 'ـ', 'K': '«', 'L': '»', ':': ':', '"': '"',
    'Z': 'ة', 'X': 'ی', 'C': 'ژ', 'V': 'ؤ', 'B': 'لا', 'N': 'أ', 'M': 'ء', '<': '>', '>': '<', '?': '؟'
}

# نگاشت معکوس فارسی به انگلیسی
FA_TO_EN = {
    'ض': 'q', 'ص': 'w', 'ث': 'e', 'ق': 'r', 'ف': 't', 'غ': 'y', 'ع': 'u', 'ه': 'i', 'خ': 'o', 'ح': 'p', 'ج': '[', 'چ': ']', 'پ': '\\',
    'ش': 'a', 'س': 's', 'ی': 'd', 'ب': 'f', 'ل': 'g', 'ا': 'h', 'ت': 'j', 'ن': 'k', 'م': 'l', 'ک': ';', 'گ': "'",
    'ظ': 'z', 'ط': 'x', 'ز': 'c', 'ر': 'v', 'ذ': 'b', 'د': 'n', 'ئ': 'm', 'و': ',', '٫': '.', '؟': '?',
    
    # کاراکترهای خاص و حالت‌های Shift فارسی به انگلیسی
    'آ': 'H',
    'ژ': 'C',  # معادل کلید استاندارد ویندوز Shift+C
    'ء': 'M',
    'أ': 'N',
    'إ': 'B',
    'ؤ': 'V',
    '«': 'K',
    '»': 'L',
    'ة': 'Z',
    '؛': ';',
    'ي': 'd',  # پشتیبانی از ی عربی
    'ك': ';',  # پشتیبانی از ک عربی
}

keyboard = Controller()

def safe_clip_get(retries=5, delay=0.05):
    """خواندن امن از کلیپ‌بورد با سیستم تلاش مجدد جهت جلوگیری از تداخل برنامه‌های دیگر"""
    for _ in range(retries):
        try:
            return pyperclip.paste()
        except Exception:
            time.sleep(delay)
    return ""

def safe_clip_set(text, retries=5, delay=0.05):
    """نوشتن امن در کلیپ‌بورد با سیستم تلاش مجدد"""
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

    # تشخیص زبان مبدا بر اساس تعداد کاراکترهای فارسی موجود در متن
    fa_count = len(re.findall(r'[\u0600-\u06FF]', text))
    en_count = len(re.findall(r'[a-zA-Z]', text))

    result = []
    if fa_count >= en_count:
        # تبدیل فارسی به انگلیسی
        for char in text:
            result.append(FA_TO_EN.get(char, char))
    else:
        # تبدیل انگلیسی به فارسی
        for char in text:
            result.append(EN_TO_FA.get(char, char))

    return "".join(result)

def on_activate():
    try:
        # ۱. وقفه اولیه برای رها شدن کلیدهای فیزیکی کاربر
        time.sleep(0.3)

        # ۲. رها کردن نرم‌افزاری تمام کلیدهای اصلاح‌کننده جهت اطمینان
        for key in [Key.ctrl, Key.shift, Key.alt, Key.cmd]:
            try:
                keyboard.release(key)
            except Exception:
                pass

        # ۳. پشتیبان‌گیری از کلیپ‌بورد فعلی
        old_clipboard = safe_clip_get()
        safe_clip_set("")

        # ۴. شبیه‌سازی فشرده شدن Ctrl+C
        keyboard.press(Key.ctrl)
        keyboard.press('c')
        time.sleep(0.08)
        keyboard.release('c')
        keyboard.release(Key.ctrl)

        # ۵. مکث کوتاه برای دریافت داده توسط سیستم‌عامل
        time.sleep(0.12)
        selected_text = safe_clip_get()

        if not selected_text.strip():
            # در صورت عدم انتخاب متن، مقدار کلیپ‌بورد بازیابی می‌شود
            safe_clip_set(old_clipboard)
            return

        # ۶. پردازش و اصلاح متن بر اساس قواعد جدید
        corrected_text = convert_text(selected_text)

        # ۷. قرار دادن متن جدید در کلیپ‌بورد و شبیه‌سازی Ctrl+V
        if safe_clip_set(corrected_text):
            keyboard.press(Key.ctrl)
            keyboard.press('v')
            time.sleep(0.08)
            keyboard.release('v')
            keyboard.release(Key.ctrl)

        # ۸. بازیابی مقدار قبلی کلیپ‌بورد پس از اتمام فرآیند
        time.sleep(0.15)
        safe_clip_set(old_clipboard)

    except Exception as e:
        # لاگ بی سروصدا برای پایداری برنامه در صورت بروز خطای ناشناخته سیستم‌عامل
        print(f"Error during execution: {e}")

def create_image():
    """ایجاد یک آیکون ساده کیبورد در حافظه بدون نیاز به فایل خارجی"""
    image = Image.new('RGB', (64, 64), color=(44, 62, 80)) # پس‌زمینه تیره
    dc = ImageDraw.Draw(image)
    # رسم بدنه کیبورد با رنگ روشن
    dc.rectangle([10, 22, 54, 42], outline=(236, 240, 241), width=3)
    dc.rectangle([15, 27, 21, 31], fill=(236, 240, 241))
    dc.rectangle([25, 27, 31, 31], fill=(236, 240, 241))
    dc.rectangle([35, 27, 41, 31], fill=(236, 240, 241))
    dc.rectangle([20, 35, 44, 38], fill=(236, 240, 241)) # دکمه اسپیس
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

if __name__ == "__main__":
    # راه‌اندازی لیسنر کلیدهای میانبر به صورت یک ترد پس‌زمینه امن
    hotkey_listener = GlobalHotKeys({
        '<ctrl>+<shift>+k': on_activate
    })
    hotkey_listener.start()

    # اجرای آیکون منوی Tray سیستم
    setup_tray()
