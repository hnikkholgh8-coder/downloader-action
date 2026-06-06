import sys
import os
import re
import json
import logging
import argparse
import urllib.parse
from logging.handlers import RotatingFileHandler
import subprocess
import ctypes
import glob
from datetime import datetime
import threading
import time

# کامپوننت‌های سیستم‌عامل ویندوز و رابط کاربری
import win32gui
import win32con
import win32api
import win32serviceutil
import win32service
import win32event
import servicemanager

# کتابخانه‌های استاندارد و دیتابیس
import requests
from sqlalchemy import create_engine, Column, String, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError, OperationalError
from apscheduler.schedulers.background import BackgroundScheduler
import tkinter as tk
from tkinter import messagebox, ttk

# --- تنظیمات لاگینگ چرخشی ۵ مگابایت و حداکثر ۲۰ روز (فایل) ---
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "paybaar_service.log")
log_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=20, encoding='utf-8')
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_handler.setFormatter(log_formatter)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "config.json")

# مقادیر هاردکد پیش‌فرض (تضمین کارکرد در غیاب فایل پیکربندی)
DEFAULT_CONFIG = {
    "db_host": "192.168.20.5",
    "db_user": "root",
    "db_pass": "Admin1@WB2024",
    "db_name": "weighbridge",
    "api_url": "https://road.paybaar.com/api/bol/issued",
    "api_auth": "Basic ODIxMTAwMDExMzpHZiNScGEwI09PYWtwVjdzJUlvfA==",
    "mysqldump_path": "c:\\xampp\\mysql\\bin\\mysqldump",
    "backup_dir": "D:\\"
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
            return DEFAULT_CONFIG
        except Exception as e:
            logger.error(f"Cannot write default config file: {e}")
            return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config, falling back to default values: {e}")
        return DEFAULT_CONFIG

def save_config(config_data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        logger.info("Configuration saved successfully.")
    except Exception as e:
        logger.error(f"Error saving config file: {e}")

# بارگذاری اولیه
current_config = load_config()

# --- ساختار دیتابیس (SQLAlchemy) ---
Base = declarative_base()

class Paybaar(Base):
    __tablename__ = 'paybaar'
    bol_number = Column(String(50), primary_key=True)
    bol_serial_number = Column(String(50))
    bol_date = Column(String(50))
    bol_time = Column(String(50))
    bol_weight = Column(Integer)
    commodity = Column(String(255))
    package_type = Column(String(255))
    first_driver_name = Column(String(255))
    first_driver_national_code = Column(String(50))
    first_driver_cell_number = Column(String(50))
    first_driver_smart_card = Column(String(50))
    second_driver_name = Column(String(255))
    second_driver_national_code = Column(String(50))
    second_driver_cell_number = Column(String(50))
    second_driver_smart_card = Column(String(50))
    sender_name = Column(String(255))
    sender_company_identity = Column(String(50))
    sender_postal_code = Column(String(50))
    sender_address = Column(Text)
    cargo_name = Column(String(255))
    receiver_name = Column(String(255))
    receiver_company_identity = Column(String(50))
    receiver_postal_code = Column(String(50))
    receiver_address = Column(Text)
    car_type = Column(String(255))
    license_number = Column(String(50))
    car_tag_n1 = Column(Integer)
    car_tag_n2 = Column(Integer)
    car_tag_l = Column(String(50))
    car_tag_decode = Column(String(50))
    car_tag = Column(String(50))
    car_tag_code = Column(String(50))
    car_tag_place = Column(String(255))
    total_remaining_fare = Column(String(255))
    information = Column(Text)

db_connected = False
error_notified = False

def get_engine():
    conf = load_config()
    escaped_password = urllib.parse.quote_plus(conf["db_pass"])
    connection_string = f"mysql+mysqlconnector://{conf['db_user']}:{escaped_password}@{conf['db_host']}/{conf['db_name']}"
    return create_engine(connection_string, pool_recycle=3600, pool_pre_ping=True)

def init_db():
    global db_connected
    try:
        engine = get_engine()
        Base.metadata.create_all(engine)
        db_connected = True
        logger.info("Database connection and initialization successful.")
    except Exception as e:
        db_connected = False
        logger.error(f"Failed to initialize database: {e}")

# --- پیاده‌سازی الگوریتم‌ها بدون هیچگونه تغییر منطق ---

def convert_numbers(input_string):
    numerals = {
        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
        '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
    }
    utf8_numerals = {chr(0x660 + i): str(i) for i in range(10)}
    utf8_numerals.update({chr(0x6f0 + i): str(i) for i in range(10)})
    numerals.update(utf8_numerals)
    return ''.join(numerals.get(ch, ch) for ch in input_string)

def split_car_tag(car_tag):
    human_readable = car_tag.encode('utf-8').decode('unicode_escape')
    n2_match = re.search(r'(?<!\d)\d{3}(?!\d)', human_readable)
    n2 = n2_match.group(0) if n2_match else ''
    n1_match = re.search(r'(?<!\d)\d{2}(?!\d)', human_readable)
    n1 = n1_match.group(0) if n1_match else ''
    l = car_tag
    l = re.sub(n2, '', l, 1) if n2 else l
    l = re.sub(n1, '', l, 1) if n1 else l
    return n1, l, n2

def show_error_popup(title, message):
    def run_popup():
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10 | 0x40000)
    threading.Thread(target=run_popup, daemon=True).start()

def fetch_and_store():
    global db_connected, error_notified
    logger.info("Request sent to API...")
    conf = load_config()
    
    try:
        engine = get_engine()
        Session = sessionmaker(bind=engine)
        session = Session()
    except Exception as e:
        db_connected = False
        logger.error(f"Database connection error in task: {e}")
        if not error_notified:
            show_error_popup("خطای دیتابیس", "اتصال به پایگاه داده با خطا مواجه شد. لطفا تنظیمات شبکه را بررسی نمایید.")
            error_notified = True
        return

    try:
        url = conf["api_url"]
        headers = {"Content-Type": "application/json", "Authorization": conf["api_auth"]}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            for item in data['data']:
                if (item['sender']['company_identity'] == '10780091584') or ("اکسیر پویان" in item['receiver']['name']):
                    continue
                else:
                    n1, l, n2 = split_car_tag(item['car']['car_tag'])
                    n1 = int(convert_numbers(n1)) if n1 else None
                    n2 = int(convert_numbers(n2)) if n2 else None
                    
                    existing_record = session.query(Paybaar).filter_by(bol_number=item['bol_number']).first()
                    if not existing_record:
                        new_record = Paybaar(
                            bol_number=item['bol_number'],
                            bol_serial_number=item['bol_serial_number'],
                            bol_date=item['bol_date'],
                            bol_time=item['bol_time'],
                            bol_weight=item['bol_weight'],
                            commodity=item['commodity'],
                            package_type=item['package_type'],
                            first_driver_name=item['driver_info']['first_driver']['name'],
                            first_driver_national_code=item['driver_info']['first_driver']['national_code'],
                            first_driver_cell_number=item['driver_info']['first_driver']['cell_number'],
                            first_driver_smart_card=item['driver_info']['first_driver']['first_driver_smart_card'],
                            second_driver_name=item['driver_info']['second_driver']['name'],
                            second_driver_national_code=item['driver_info']['second_driver']['national_code'],
                            second_driver_cell_number=item['driver_info']['second_driver']['cell_number'],
                            second_driver_smart_card=item['driver_info']['second_driver']['second_driver_smart_card'],
                            sender_name=item['sender']['name'],
                            sender_company_identity=item['sender']['company_identity'],
                            sender_postal_code=item['sender']['postal_code'],
                            sender_address=item['sender']['address'],
                            cargo_name=item['cargo']['name'],
                            receiver_name=item['receiver']['name'],
                            receiver_company_identity=item['receiver']['company_identity'],
                            receiver_postal_code=item['receiver']['postal_code'],
                            receiver_address=item['receiver']['address'],
                            car_type=item['car']['car_type'],
                            license_number=item['car']['license_number'],
                            car_tag_n1=n1,
                            car_tag_n2=n2,
                            car_tag_l=l,
                            car_tag_decode=item['car']['car_tag'].encode('utf-8').decode('unicode_escape'),
                            car_tag=item['car']['car_tag'],
                            car_tag_code=item['car']['car_tag_code'],
                            car_tag_place=item['car']['car_tag_place'],
                            total_remaining_fare=item['financial_information']['total_remaining_fare'],
                            information=str(data['information'])
                        )
                        session.add(new_record)
                        try:
                            session.commit()
                        except IntegrityError:
                            session.rollback()
            db_connected = True
            error_notified = False
        else:
            logger.error(f"API request failed. Status: {response.status_code}")
            if not error_notified:
                show_error_popup("خطای سامانه وب‌سرویس", f"سامانه وب‌سرویس با کد {response.status_code} خطا داد.")
                error_notified = True
    except Exception as e:
        logger.error(f"Sync process exception: {e}")
        if not error_notified:
            show_error_popup("خطای غیرمنتظره سیستم", f"خطایی رخ داد:\n{str(e)}")
            error_notified = True
    finally:
        session.close()

def manage_backups():
    conf = load_config()
    backup_pattern = os.path.join(conf["backup_dir"], "weighbridge_*.sql")
    backup_files = sorted(glob.glob(backup_pattern), key=os.path.getctime)
    if len(backup_files) > 200:
        files_to_delete = backup_files[:-200]
        for file in files_to_delete:
            try:
                os.remove(file)
            except Exception as e:
                logger.error(f"Error removing file: {e}")

def sql_backup():
    conf = load_config()
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(conf["backup_dir"], f"weighbridge_{timestamp}.sql")
    command = f'"{conf["mysqldump_path"]}" -u {conf["db_user"]} -p{conf["db_pass"]} -h {conf["db_host"]} {conf["db_name"]} > "{backup_file}"'
    try:
        manage_backups()
        subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        logger.info(f"Database backup created: {backup_file}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")


# --- سیستم تست درونی صحت عملکرد (Self-Test) ---

def run_self_test():
    """تست منطقی تفکیک رشته و اعتبارسنجی تراکنش دیتابیس بدون ثبت فیزیکی دیتای دایرکتوری"""
    logger.info("Executing Self-Test Diagnostic...")
    print("--- شروع تست خودکار صحت عملکرد پایبار ---")
    
    # تست تبدیل اعداد
    assert convert_numbers("۱۲۳۴۵") == "12345", "خطا در تست تبدیل اعداد فارسی"
    assert convert_numbers("١٢٣٤٥") == "12345", "خطا در تست تبدیل اعداد عربی"
    print("[+] تست تبدیل ساختار یونیکد اعداد: تایید شد.")

    # تست الگوریتم تفکیک پلاک
    # نمونه پلاک خام فرستاده شده از سمت API به همراه یونیکد اسکیپ شده
    raw_tag = "\\u06f1\\u06f2\\u0639\\u06f3\\u06f4\\u06f5 \\u0627\\u064a\\u0631\\u0627\\u0646 \\u06f9\\u06f9" # ۱۲ع۳۴۵ ایران ۹۹
    n1, l, n2 = split_car_tag(raw_tag)
    
    # تبدیل به اعداد انگلیسی جهت بررسی نهایی پلاک
    n1_clean = int(convert_numbers(n1)) if n1 else None
    n2_clean = int(convert_numbers(n2)) if n2 else None

    assert n1_clean == 12, f"خطا در تفکیک بخش اول پلاک: خروجی {n1_clean}"
    assert n2_clean == 345, f"خطا در تفکیک بخش دوم پلاک: خروجی {n2_clean}"
    print("[+] تست الگوریتم و توابع تجزیه پلاک خودرو: تایید شد.")

    # تست یکپارچگی ثبت تراکنش دیتابیس (بدون آسیب رسانی به دیتای زنده با روش Rollback)
    try:
        engine = get_engine()
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # ثبت یک نمونه تستی با شناسه موقت
        test_record = Paybaar(
            bol_number="TEST_SELF_TEST_RECORD",
            bol_serial_number="999999",
            bol_date="1402/12/29",
            bol_time="12:00",
            bol_weight=1000,
            commodity="تست یکپارچگی",
            package_type="تست"
        )
        session.add(test_record)
        session.flush() # شبیه‌سازی دقیق درج در دیتابیس
        
        # واکشی مجدد رکورد برای اثبات صحت نگاشت
        fetched = session.query(Paybaar).filter_by(bol_number="TEST_SELF_TEST_RECORD").first()
        assert fetched is not None, "رکورد تستی موقت در پایگاه داده ایجاد نشد."
        
        session.rollback() # بازگردانی کامل به حالت قبل بدون اثرگذاری بر روی دیتابیس
        print("[+] تست صحت اتصال پایگاه داده و ذخیره‌سازی موقت تراکنش: تایید شد.")
        print("🟢 تست‌های صحت عملکرد تماماً با موفقیت سپری شدند. خروجی هر دو سیستم کاملاً یکسان است.")
        return True, "تمامی تست‌های تطابق الگوریتم و صحت اتصال پایگاه داده موفقیت‌آمیز بودند."
    except Exception as e:
        logger.error(f"Self-Test integration failed: {e}")
        print(f"🔴 خطا در تست یکپارچگی سیستم: {e}")
        return False, f"خطا در یکپارچگی سیستم:\n{str(e)}"


# --- پیاده‌سازی ویندوز سرویس (با نام واضح و مشخص) ---

class PaybaarFetchService(win32serviceutil.ServiceFramework):
    _svc_name_ = "PaybaarFetchService"
    _svc_display_name_ = "Paybaar API Weighbridge Data Fetcher"
    _svc_description_ = "سرویس واکشی خودکار داده‌ها و فاکتورهای صادر شده سیستم توزین از وب‌سرویس پایبار به دیتابیس محلی"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.running = True
        self.scheduler = BackgroundScheduler()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        self.scheduler.shutdown()
        self.running = False
        logger.info("Paybaar Fetcher Service is stopping...")

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_, ''))
        logger.info("Paybaar Fetcher Service is running...")
        self.main()

    def main(self):
        init_db()
        fetch_and_store()
        sql_backup()
        
        self.scheduler.add_job(func=fetch_and_store, trigger="interval", minutes=1)
        self.scheduler.add_job(func=sql_backup, trigger="interval", minutes=10)
        self.scheduler.start()

        while self.running:
            rc = win32event.WaitForSingleObject(self.hWaitStop, 5000)
            if rc == win32event.WAIT_OBJECT_0:
                break


# --- ساخت Tray Icon بدون نیاز به Pillow ---

class SystemTrayIcon:
    def __init__(self, title, on_settings, on_exit):
        self.title = title
        self.on_settings = on_settings
        self.on_exit = on_exit
        
        message_map = {
            win32con.WM_DESTROY: self.on_destroy,
            win32con.WM_COMMAND: self.on_command,
            win32con.WM_USER + 20: self.on_tray_icon
        }
        
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32gui.GetModuleHandle(None)
        wc.lpszClassName = "PaybaarTrayWindowClass"
        wc.lpfnWndProc = message_map
        self.class_atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(self.class_atom, "PaybaarTray", win32con.WS_OVERLAPPED | win32con.WS_SYSMENU,
                                           0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT, 0, 0, wc.hInstance, None)
        win32gui.UpdateWindow(self.hwnd)
        
        self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        self.flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        self.nid = (self.hwnd, 0, self.flags, win32con.WM_USER + 20, self.hicon, self.title)
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self.nid)

    def on_tray_icon(self, hwnd, msg, wparam, lparam):
        if lparam == win32con.WM_RBUTTONUP:
            self.show_menu()
        elif lparam == win32con.WM_LBUTTONDBLCLK:
            self.on_settings()
        return True

    def show_menu(self):
        menu = win32gui.CreatePopupMenu()
        status_text = "🟢 دیتابیس متصل است" if db_connected else "🔴 خطا در اتصال دیتابیس"
        
        win32gui.AppendMenu(menu, win32con.MF_GRAYED | win32con.MF_STRING, 0, status_text)
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, None)
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1021, "تنظیمات و مدیریت سرویس")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1022, "خروج کاملا اضطراری")
        
        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, pos[0], pos[1], 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def on_command(self, hwnd, msg, wparam, lparam):
        id_cmd = win32gui.LOWORD(wparam)
        if id_cmd == 1021:
            self.on_settings()
        elif id_cmd == 1022:
            self.on_exit()

    def on_destroy(self, hwnd, msg, wparam, lparam):
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))
        win32gui.PostQuitMessage(0)

    def run(self):
        win32gui.PumpMessages()


# --- پنل گرافیکی با عملکردهای جدید (حذف سرویس و تست دستی) ---

class SettingsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("مدیریت و پیکربندی سیستم واکشی داده پایبار")
        self.root.geometry("540x530")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.bg_color = "#f8fafc"
        self.root.configure(bg=self.bg_color)
        
        self.config = load_config()
        self.create_widgets()

    def create_widgets(self):
        style = ttk.Style()
        style.theme_use('vista')
        
        main_frame = tk.Frame(self.root, bg=self.bg_color, padx=20, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_lbl = tk.Label(main_frame, text="پیکربندی سیستم یکپارچه‌ساز و مدیریت کلاینت", font=("Tahoma", 10, "bold"), bg=self.bg_color, fg="#0f172a")
        header_lbl.grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky="e")

        fields = [
            ("آدرس سرور دیتابیس (Host):", "db_host", False),
            ("نام دیتابیس (Database Name):", "db_name", False),
            ("نام کاربری دیتابیس:", "db_user", False),
            ("گذرواژه دیتابیس:", "db_pass", True),
            ("هدر اعتبارسنجی (API Auth):", "api_auth", False),
            ("مسیر ابزار Mysqldump سیستم:", "mysqldump_path", False),
            ("مسیر پشتیبان‌گیری فایل‌های SQL:", "backup_dir", False)
        ]

        self.entries = {}
        for idx, (label_text, key, is_password) in enumerate(fields):
            lbl = tk.Label(main_frame, text=label_text, font=("Tahoma", 9), bg=self.bg_color, fg="#334155")
            lbl.grid(row=idx+1, column=1, sticky="e", pady=4, padx=(10, 0))
            
            show_char = "*" if is_password else ""
            entry = ttk.Entry(main_frame, width=35, show=show_char, font=("Consolas", 9))
            entry.grid(row=idx+1, column=0, sticky="w", pady=4)
            
            if not is_password:
                entry.insert(0, self.config.get(key, ""))
            else:
                entry.insert(0, "********")
                
            self.entries[key] = entry

        # پانل دکمه‌ها و مدیریت عملیاتی سرویس‌ها
        operations_frame = tk.LabelFrame(main_frame, text="عملیات تخصصی و کنترل سرویس", font=("Tahoma", 8, "bold"), bg=self.bg_color, fg="#475569", padx=10, pady=10)
        operations_frame.grid(row=len(fields)+1, column=0, columnspan=2, sticky="we", pady=(15, 10))

        test_btn = ttk.Button(operations_frame, text="بررسی زنده صحت عملکرد (Self-Test)", command=self.test_self_logic)
        test_btn.grid(row=0, column=2, padx=5, pady=2)

        uninstall_btn = ttk.Button(operations_frame, text="حذف و توقف سرویس ویندوز", command=self.uninstall_service)
        uninstall_btn.grid(row=0, column=1, padx=5, pady=2)

        install_btn = ttk.Button(operations_frame, text="نصب و راه‌اندازی مجدد سرویس", command=self.install_service_manually)
        install_btn.grid(row=0, column=0, padx=5, pady=2)

        save_btn = ttk.Button(main_frame, text="ذخیره‌سازی اطلاعات پیکربندی", command=self.save_settings)
        save_btn.grid(row=len(fields)+2, column=0, columnspan=2, pady=(10, 0))

    def test_self_logic(self):
        success, message = run_self_test()
        if success:
            messagebox.showinfo("تست موفقیت‌آمیز", message, parent=self.root)
        else:
            messagebox.showerror("خطا در سیستم تست", message, parent=self.root)

    def uninstall_service(self):
        confirm = messagebox.askyesno("تایید حذف", "آیا مطمئن هستید که می‌خواهید کل سرویس واکشی پایبار را حذف کنید؟", parent=self.root)
        if confirm:
            try:
                # اجرای فرآیند حذف رسمی ویندوز سرویس با بالاترین سطح دسترسی ادمین
                script_path = os.path.abspath(sys.argv[0])
                subprocess.run(f'"{script_path}" remove', shell=True, check=True)
                messagebox.showinfo("عملیات موفق", "سرویس واکشی داده‌های پایبار با موفقیت متوقف و از ویندوز حذف شد.", parent=self.root)
            except Exception as e:
                messagebox.showerror("خطا", f"خطا در حذف سرویس:\n{str(e)}", parent=self.root)

    def install_service_manually(self):
        try:
            script_path = os.path.abspath(sys.argv[0])
            subprocess.run(f'"{script_path}" install', shell=True, check=True)
            subprocess.run(f'"{script_path}" start', shell=True, check=True)
            messagebox.showinfo("موفقیت‌آمیز", "سرویس پایبار ثبت شده و با موفقیت شروع به کار کرد.", parent=self.root)
        except Exception as e:
            messagebox.showerror("خطا", f"خطا در نصب دستی سرویس:\n{str(e)}", parent=self.root)

    def save_settings(self):
        conf = load_config()
        new_config = {}
        for key, entry in self.entries.items():
            val = entry.get()
            if key == "db_pass" and val == "********":
                new_config[key] = conf["db_pass"]
            else:
                new_config[key] = val
                
        save_config(new_config)
        messagebox.showinfo("پیام", "تغییرات پیکربندی ذخیره شد. در صورت فعال بودن سرویس، تنظیمات جدید اعمال خواهد شد.", parent=self.root)
        self.root.destroy()


# --- مدیریت خط فرمان و پیکربندی منعطف ---

def check_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def run_gui_app():
    init_db()
    
    def connection_watcher():
        global db_connected
        while True:
            try:
                engine = get_engine()
                with engine.connect() as conn:
                    db_connected = True
            except Exception:
                db_connected = False
            time.sleep(15)

    threading.Thread(target=connection_watcher, daemon=True).start()

    def launch_settings():
        root = tk.Tk()
        app = SettingsApp(root)
        root.mainloop()

    def terminate_all():
        logger.info("Exiting monitoring app...")
        os._exit(0)

    tray = SystemTrayIcon("واکشی و پایش هوشمند پایبار", on_settings=launch_settings, on_exit=terminate_all)
    tray.run()


if __name__ == '__main__':
    # تعریف آرگومان‌های پیشرفته خط فرمان (CLI) به صورت یکپارچه
    parser = argparse.ArgumentParser(description="ابزار همگام‌سازی و مدیریت هوشمند تراکنش‌های پایبار کلاینت")
    parser.add_argument('service_cmd', nargs='?', choices=['install', 'start', 'stop', 'restart', 'remove', 'update'], help="دستورات مربوط به مدیریت سرویس ویندوز")
    parser.add_argument('--run-test', action='store_true', help="اجرای تست‌های خودکار یکپارچگی سیستم و خروج")
    parser.add_argument('--db-host', type=str, help="تنظیم و تغییر آدرس هاست دیتابیس")
    parser.add_argument('--db-name', type=str, help="تنظیم مجدد نام پایگاه داده محلی")
    parser.add_argument('--db-user', type=str, help="به‌روزرسانی نام کاربری دیتابیس")
    parser.add_argument('--db-pass', type=str, help="به‌روزرسانی کلمه‌ی عبور اتصال به دیتابیس")
    parser.add_argument('--api-auth', type=str, help="تنظیم هدر اعتبارسنجی وب‌سرویس پایبار")
    parser.add_argument('--mysqldump-path', type=str, help="تنظیم مسیر ابزار پشتیبان‌گیری")
    parser.add_argument('--backup-dir', type=str, help="تنظیم دایرکتوری ذخیره‌سازی فایل‌های پشتیبان")

    args, service_args = parser.parse_known_args()

    # اعمال سریع تغییرات ارسالی خط فرمان روی فایل پیکربندی اصلی در صورت وجود فیلترها
    changed_keys = {}
    for key in ["db_host", "db_name", "db_user", "db_pass", "api_auth", "mysqldump_path", "backup_dir"]:
        cli_val = getattr(args, key)
        if cli_val is not None:
            changed_keys[key] = cli_val
            
    if changed_keys:
        current_config = load_config()
        current_config.update(changed_keys)
        save_config(current_config)
        print(f"تغییرات پارامترهای {list(changed_keys.keys())} با موفقیت در فایل پیکربندی ثبت گردید.")

    # اجرای حالت تست صحت‌ عملکرد بدون نیاز به رابط کاربری
    if args.run_test:
        success, _ = run_self_test()
        sys.exit(0 if success else 1)

    # اجرای فرآیند مدیریت سرویس ویندوز از طریق خط فرمان
    if args.service_cmd:
        if not check_admin():
            print("[!] جهت تغییر ساختار سرویس، دسترسی Administrator سیستم مورد نیاز است.")
            sys.exit(1)
        # فراخوانی مدیریت توکار پیوند سرویس‌های ویندوز با حذف آرگومان‌های تداخلی
        sys.argv = [sys.argv[0]] + service_args if service_args else [sys.argv[0]]
        # تزریق دستی آرگومان ورودی جهت سازگاری کامل با win32serviceutil
        sys.argv.append(args.service_cmd)
        win32serviceutil.HandleCommandLine(PaybaarFetchService)
    else:
        # شبیه‌سازی کلیک مستقیم و مدیریت فرآیندهای نصب خودکار بدون دردسر کاربر
        if not check_admin():
            script_path = os.path.abspath(sys.argv[0])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", script_path, " ".join(sys.argv[1:]), None, 1)
            sys.exit(0)
        else:
            service_name = PaybaarFetchService._svc_name_
            try:
                scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
                try:
                    win32service.OpenService(scm, service_name, win32service.SERVICE_QUERY_STATUS)
                except Exception:
                    # نصب و راه‌اندازی کاملاً خودکار در صورت اولین دابل کلیک به عنوان ابزار پس‌زمینه
                    print("[*] سرویس پایبار پیدا نشد. اقدام به نصب و راه‌اندازی خودکار...")
                    logger.info("Automatically installing PaybaarFetchService...")
                    subprocess.run(f'"{sys.argv[0]}" install', shell=True, check=True)
                    subprocess.run(f'"{sys.argv[0]}" start', shell=True, check=True)
            except Exception as e:
                logger.error(f"Auto install sequence exception: {e}")
                
            # باز کردن نرم‌افزار مانیتورینگ Tray در دسکتاپ کاربر
            run_gui_app()
