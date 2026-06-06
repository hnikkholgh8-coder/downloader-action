import sys
import os
import re
import json
import logging
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

# --- تنظیمات لاگینگ چرخشی ۵ مگابایت و حداکثر ۲۰ فایل ---
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "service_log.log")
log_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=20, encoding='utf-8')
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_handler.setFormatter(log_formatter)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

# مسیر فایل پیکربندی پویا
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "config.json")

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
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return DEFAULT_CONFIG

def save_config(config_data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
        logger.info("Configuration saved successfully.")
    except Exception as e:
        logger.error(f"Error saving config: {e}")

# بارگزاری اولیه پیکربندی
current_config = load_config()

# --- ساختار دیتابیس با استاندارد SQLAlchemy (بدون Flask) ---
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

# متغیر سراسری نگهداری وضعیت ارتباط و هشدار
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

# --- توابع منطق اصلی (کاملاً منطبق بر منطق ارسالی کاربر) ---

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
    """نمایش یک‌باره هشدار فارسی به کاربر در قالب ترد مجزا جهت جلوگیری از بلاک شدن منطق برنامه"""
    def run_popup():
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10 | 0x40000)
    threading.Thread(target=run_popup, daemon=True).start()

def fetch_and_store():
    global db_connected, error_notified
    logger.info("Request sent to API...")
    conf = load_config()
    
    # ارتباط دیتابیس به صورت Dynamic با خواندن آخرین پیکربندی
    try:
        engine = get_engine()
        Session = sessionmaker(bind=engine)
        session = Session()
    except Exception as e:
        db_connected = False
        logger.error(f"Database connection error in task: {e}")
        if not error_notified:
            show_error_popup("خطای دیتابیس", "اتصال به پایگاه داده با خطا مواجه شد. لطفا تنظیمات شبکه و مشخصات سرور را بررسی نمایید.")
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
            error_notified = False  # بازنشانی خطا به محض اولین پاسخ موفق
        else:
            logger.error(f"API request failed. Status code: {response.status_code}")
            if not error_notified:
                show_error_popup("خطای سامانه وب‌سرویس", f"سامانه وب‌سرویس با کد خطای {response.status_code} پاسخ داد.")
                error_notified = True

    except Exception as e:
        logger.error(f"Error in data synchronization process: {e}")
        if not error_notified:
            show_error_popup("خطای سیستمی", f"خطا در سنکرون‌سازی اطلاعات رخ داد:\n{str(e)}")
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
                logger.info(f"Old backup file removed: {file}")
            except Exception as e:
                logger.error(f"Error removing old backup file: {e}")

def sql_backup():
    conf = load_config()
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(conf["backup_dir"], f"weighbridge_{timestamp}.sql")
    
    # ساخت فایل خروجی با فیلتر امنیت اطلاعات کاربری
    command = f'"{conf["mysqldump_path"]}" -u {conf["db_user"]} -p{conf["db_pass"]} -h {conf["db_host"]} {conf["db_name"]} > "{backup_file}"'
    
    try:
        manage_backups()
        subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        logger.info(f"Database backup saved successfully at: {backup_file}")
    except Exception as e:
        logger.error(f"Database backup execution failed: {e}")

# --- پیاده‌سازی ویندوز سرویس ---

class WindowsService(win32serviceutil.ServiceFramework):
    _svc_name_ = "PaybaarBridgeService"
    _svc_display_name_ = "Paybaar Weighbridge Enterprise Service"
    _svc_description_ = "این سرویس همگام‌سازی اطلاعات توزین پایبار با دیتابیس محلی را برعهده دارد."

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
        logger.info("Weighbridge service is stopping...")

    def SvcDoRun(self):
        servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                              servicemanager.PYS_SERVICE_STARTED,
                              (self._svc_name_, ''))
        logger.info("Weighbridge service started successfully.")
        self.main()

    def main(self):
        init_db()
        fetch_and_store()
        sql_backup()
        
        # تعریف جاب‌های پردازشی با تکیه بر منطق اصلی کاربر
        self.scheduler.add_job(func=fetch_and_store, trigger="interval", minutes=1)
        self.scheduler.add_job(func=sql_backup, trigger="interval", minutes=10)
        self.scheduler.start()

        while self.running:
            # زمان خواب کمکی سرویس جهت جلوگیری از مصرف بیهوده منابع پردازشی
            rc = win32event.WaitForSingleObject(self.hWaitStop, 5000)
            if rc == win32event.WAIT_OBJECT_0:
                break


# --- ساخت Tray Icon اختصاصی با توابع خام Win32 بدون وابستگی به Pillow ---

class SystemTrayIcon:
    def __init__(self, title, on_settings, on_exit):
        self.title = title
        self.on_settings = on_settings
        self.on_exit = on_exit
        
        # ثبت کلاس پنجره پنهان ویندوز جهت دریافت پیام‌های Tray
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
        
        # استفاده از آیکون استاندارد و پیش‌فرض سیستم‌عامل ویندوز برای پایداری ۱۰۰ درصدی
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
        
        # ایجاد برچسب وضعیت به صورت داینامیک همراه با کاراکترهای رنگی یونیکد جهت مانیتورینگ آنلاین
        status_text = "🟢 اتصال دیتابیس برقرار است" if db_connected else "🔴 قطع ارتباط با دیتابیس"
        win32gui.AppendMenu(menu, win32con.MF_GRAYED | win32con.MF_STRING, 0, status_text)
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, None)
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1021, "تنظیمات نرم افزار (فارسی)")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1022, "خروج")
        
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


# --- پیاده‌سازی کنترل پنل گرافیکی فارسی به وسیله Tkinter ---

class SettingsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("تنظیمات سرویس هوشمند پایبار")
        self.root.geometry("500x480")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        
        # استایل‌دهی پنجره تنظیمات به رنگ‌های هماهنگ با طراحی سازمانی
        self.bg_color = "#f4f6f9"
        self.root.configure(bg=self.bg_color)
        
        self.config = load_config()
        self.create_widgets()

    def create_widgets(self):
        style = ttk.Style()
        style.theme_use('vista')
        
        main_frame = tk.Frame(self.root, bg=self.bg_color, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_lbl = tk.Label(main_frame, text="پیکربندی سرویس همگام‌ساز توزین", font=("Tahoma", 11, "bold"), bg=self.bg_color, fg="#1e293b")
        header_lbl.grid(row=0, column=0, columnspan=2, pady=(0, 15), sticky="e")

        # ایجاد فیلدهای فرم ورودی اطلاعات با چینش استاندارد و کاربرپسند راست‌به‌چپ
        fields = [
            ("آدرس سرور دیتابیس (Host):", "db_host", False),
            ("نام دیتابیس (Database Name):", "db_name", False),
            ("نام کاربری دیتابیس:", "db_user", False),
            ("گذرواژه دیتابیس:", "db_pass", True),
            ("آدرس هدر وب‌سرویس (API Authorization):", "api_auth", False),
            ("مسیر Mysqldump ویندوز:", "mysqldump_path", False),
            ("مسیر ذخیره‌سازی فایل‌های پشتیبان:", "backup_dir", False)
        ]

        self.entries = {}
        for idx, (label_text, key, is_password) in enumerate(fields):
            lbl = tk.Label(main_frame, text=label_text, font=("Tahoma", 9), bg=self.bg_color, fg="#475569")
            lbl.grid(row=idx+1, column=1, sticky="e", pady=6, padx=(10, 0))
            
            show_char = "*" if is_password else ""
            entry = ttk.Entry(main_frame, width=32, show=show_char, font=("Consolas", 9))
            entry.grid(row=idx+1, column=0, sticky="w", pady=6)
            
            # پر کردن اتوماتیک مقادیر با لود امن فیلدهای مربوطه
            if not is_password:
                entry.insert(0, self.config.get(key, ""))
            else:
                entry.insert(0, "********")  # رمز قبلی به هیچ وجه نشان داده نمی‌شود
                
            self.entries[key] = entry

        # دکمه‌های کنترلی فرم
        btn_frame = tk.Frame(main_frame, bg=self.bg_color)
        btn_frame.grid(row=len(fields)+2, column=0, columnspan=2, pady=(20, 0))

        save_btn = ttk.Button(btn_frame, text="ذخیره تنظیمات", command=self.save_settings)
        save_btn.pack(side=tk.RIGHT, padx=5)

        test_btn = ttk.Button(btn_frame, text="تست اتصال دیتابیس", command=self.test_connection)
        test_btn.pack(side=tk.LEFT, padx=5)

    def test_connection(self):
        conf = load_config()
        # استفاده از مقادیر ویرایش‌شده درون فرم پیش از ذخیره رسمی جهت تست آسان
        host = self.entries["db_host"].get()
        user = self.entries["db_user"].get()
        db_name = self.entries["db_name"].get()
        
        # اگر کاربر پسورد جدیدی وارد کرده باشد از آن استفاده کند در غیر این صورت پسورد ذخیره شده
        raw_pass = self.entries["db_pass"].get()
        password = conf["db_pass"] if raw_pass == "********" else raw_pass
        
        try:
            escaped_pass = urllib.parse.quote_plus(password)
            test_conn = f"mysql+mysqlconnector://{user}:{escaped_pass}@{host}/{db_name}"
            test_engine = create_engine(test_conn, connect_args={'connect_timeout': 5})
            with test_engine.connect() as conn:
                pass
            messagebox.showinfo("موفقیت‌آمیز", "ارتباط با دیتابیس با موفقیت برقرار شد.", parent=self.root)
        except Exception as e:
            messagebox.showerror("خطا در برقراری ارتباط", f"اتصال ناموفق بود:\n{str(e)}", parent=self.root)

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
        messagebox.showinfo("اطلاعات", "تنظیمات جدید ذخیره شد و در چرخه پردازش قرار گرفت.", parent=self.root)
        self.root.destroy()


# --- مدیریت اجرای فرآیندها و سیستم نصب خودکار ---

def check_admin():
    """بررسی برخورداری از مجوز دسترسی Administrator جهت نصب یا مدیریت سرویس‌های ویندوز"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def run_gui_app():
    """اجرای پنل گرافیکی و مستقر کردن آیکون کنار ساعت به صورت مالتی‌تِرد"""
    init_db()
    
    # ساخت کنترلر آنلاین جهت پایش مداوم دیتابیس و نمایش همزمان تغییر وضعیت در Tray
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
        logger.info("Closing application from System Tray...")
        os._exit(0)

    # شروع بکار Tray Icon با قابلیت مانیتورینگ آنلاین دیتابیس بدون مسدود شدن نخ اصلی
    tray = SystemTrayIcon("سرویس یکپارچه‌سازی پایبار", on_settings=launch_settings, on_exit=terminate_all)
    tray.run()

if __name__ == '__main__':
    # در صورتی که برنامه با پارامترهای کنترلر ویندوز سرویس اجرا شود (مانند SCM)
    if len(sys.argv) > 1 and sys.argv[1] in ["install", "update", "start", "stop", "restart", "remove"]:
        if not check_admin():
            logger.error("Admin privileges are required to modify the Windows Service.")
            sys.exit(1)
        # ارجاع درخواست به مدیریت توکار سرویس‌های ویندوز
        win32serviceutil.HandleCommandLine(WindowsService)
    else:
        # اگر کاربر مستقیماً روی فایل exe دابل‌کلیک کند:
        if not check_admin():
            # باز کردن مجدد برنامه با دسترسی Administrator به منظور نصب خودکار سرویس
            script_path = os.path.abspath(sys.argv[0])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", script_path, " ".join(sys.argv[1:]), None, 1)
            sys.exit(0)
        else:
            # مرحله نصب سرویس به صورت خودکار با ورود برای بار اول
            service_name = WindowsService._svc_name_
            try:
                # بررسی اینکه آیا سرویس از قبل ثبت شده است یا خیر
                scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
                try:
                    win32service.OpenService(scm, service_name, win32service.SERVICE_QUERY_STATUS)
                    logger.info("Service already registered.")
                except Exception:
                    # ثبت سرویس در رجیستری ویندوز در صورت عدم وجود
                    logger.info("Installing Windows Service...")
                    subprocess.run([sys.executable, "install"], shell=True, check=True)
                    # پیکربندی وضعیت شروع خودکار سرویس همراه با راه‌اندازی ویندوز
                    subprocess.run([sys.executable, "start"], shell=True, check=True)
                    logger.info("Windows Service registered and started successfully.")
            except Exception as e:
                logger.error(f"Error checking/installing service: {e}")
                
            # در نهایت ابزار مانیتورینگ Tray Icon و تنظیمات فارسی در دسکتاپ کاربر اجرا می‌گردد.
            run_gui_app()
