import re
import time
from PIL import Image, ImageDraw
import pyperclip
from pynput.keyboard import Controller, Key, GlobalHotKeys
import pystray

# نقشه نگاشت کاراکترها (استاندارد کیبورد فارسی و انگلیسی)
EN_TO_FA = {
    'q': 'ض', 'w': 'ص', 'e': 'ث', 'r': 'ق', 't': 'ف', 'y': 'غ', 'u': 'ع', 'i': 'ه', 'o': 'خ', 'p': 'ح', '[': 'ج', ']': 'چ',
    'a': 'ش', 's': 'س', 'd': 'ی', 'f': 'ب', 'g': 'ل', 'h': 'ا', 'j': 'ت', 'k': 'ن', 'l': 'م', ';': 'ک', "'": 'گ',
    'z': 'ظ', 'x': 'ط', 'c': 'ز', 'v': 'ر', 'b': 'ذ', 'n': 'د', 'm': 'پ', ',': 'و', '.': '٫', '/': '؟', '\\': 'ژ',
    'Q': 'َ', 'W': 'ً', 'E': 'ُ', 'R': 'ٌ', 'T': 'لإ', 'Y': 'إ', 'U': 'أ', 'I': 'دّ', 'O': 'خ', 'P': 'ج', '{': 'ج', '}': 'چ',
    'A': 'ِ', 'S': 'ٍ', 'D': 'ی', 'F': 'ب', 'G': 'لأ', 'H': 'آ', 'J': 'ت', 'K': '«', 'L': '»', ':': 'ک', '"': 'گ',
    'Z': 'ة', 'X': 'ی', 'C': 'ژ', 'V': 'ر', 'B': 'لا', 'N': 'آ', 'M': 'ء', '<': 'و', '>': '.', '?': '؟', '|': 'ژ'
}

# ساخت نقشه معکوس برای تبدیل فارسی به انگلیسی
FA_TO_EN = {v: k for k, v in EN_TO_FA.items()}
FA_TO_EN.update({
    '؛': ';',
    'ی': 'd',
    'ک': ';',
    'گ': "'",
    'ٔ': 'U',
    'ء': 'm',
    'أ': 'U',
    'إ': 'Y',
    'ؤ': 'V',
    '«': 'K',
    '»': 'L',
    '؟': '?',
    '٫': '.',
    '٪': '%',
    '﷼': '$',
})

keyboard = Controller()

def convert_text(text):
    if not text:
        return text

    # شمارش تعداد کاراکترهای فارسی برای تشخیص زبان مبدا
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
    # ۱. وقفه کوتاه برای رها شدن کلیدهای فشرده‌شده توسط کاربر
    time.sleep(0.3)

    # ۲. رها کردن نرم‌افزاری کلیدهای کنترلی جهت جلوگیری از تداخل
    keyboard.release(Key.ctrl)
    keyboard.release(Key.shift)
    keyboard.release(Key.alt)

    # ۳. ذخیره مقدار فعلی کلیپ‌بورد برای بازیابی بعدی
    old_clipboard = pyperclip.paste()
    pyperclip.copy("")  # خالی کردن موقت

    # ۴. شبیه‌سازی Ctrl+C برای کپی کردن متن انتخاب‌شده
    with keyboard.pressed(Key.ctrl):
        keyboard.press('c')
        keyboard.release('c')

    # ۵. صبر برای انتقال متن به کلیپ‌بورد
    time.sleep(0.15)
    selected_text = pyperclip.paste()

    if not selected_text:
        # اگر متنی انتخاب نشده بود، کلیپ‌بورد قبلی را برمی‌گرداند
        pyperclip.copy(old_clipboard)
        return

    # ۶. اصلاح متن بر اساس مپینگ کاراکترها
    corrected_text = convert_text(selected_text)

    # ۷. قرار دادن متن اصلاح‌شده در کلیپ‌بورد
    pyperclip.copy(corrected_text)

    # ۸. شبیه‌سازی Ctrl+V برای جایگزینی متن جدید
    with keyboard.pressed(Key.ctrl):
        keyboard.press('v')
        keyboard.release('v')

    # ۹. صبر برای اتمام عملیات پیست و بازیابی کلیپ‌بورد اصلی کاربر
    time.sleep(0.15)
    pyperclip.copy(old_clipboard)

# ایجاد آیکون ساده به صورت گرافیکی برای نمایش در System Tray
def create_image():
    image = Image.new('RGB', (64, 64), color=(41, 128, 185))
    dc = ImageDraw.Draw(image)
    # رسم طرح ساده از کیبورد روی آیکون
    dc.rectangle([10, 20, 54, 44], outline=(255, 255, 255), width=3)
    dc.rectangle([15, 25, 23, 30], fill=(255, 255, 255))
    dc.rectangle([27, 25, 35, 30], fill=(255, 255, 255))
    dc.rectangle([39, 25, 47, 30], fill=(255, 255, 255))
    dc.rectangle([20, 34, 44, 39], fill=(255, 255, 255))
    return image

def setup_tray():
    def on_exit(icon, item):
        icon.stop()
        hotkey_listener.stop()

    icon_image = create_image()
    menu = pystray.Menu(pystray.MenuItem('Exit', on_exit))
    
    # تنظیم ابزارک آیکون و پیغام شناور (Tooltip)
    tooltip_text = "من زنده‌ام!\nمتن را انتخاب کنید و کلیدهای Ctrl+Shift+K را فشار دهید."
    icon = pystray.Icon("keyboard_converter", icon_image, title=tooltip_text, menu=menu)
    icon.run()

if __name__ == "__main__":
    # تعریف و اجرای لیسنر کلید میانبر به صورت پس‌زمینه
    hotkey_listener = GlobalHotKeys({
        '<ctrl>+<shift>+k': on_activate
    })
    hotkey_listener.start()

    # اجرای آیکون System Tray در ترد اصلی
    setup_tray()
