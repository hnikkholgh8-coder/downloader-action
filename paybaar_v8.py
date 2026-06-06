import sys
import os
import re
import logging
import argparse
import urllib.parse
import shutil
import subprocess
import ctypes
import glob
from datetime import datetime
import threading
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

# ==========================================
# 1. OS & Environment Setup
# ==========================================
IS_WINDOWS = (sys.platform == 'win32')

if IS_WINDOWS:
    try:
        import win32gui
        import win32con
        import win32api
        import win32service
        import win32serviceutil
        import win32event
        import servicemanager
        from ctypes import wintypes
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False
else:
    HAS_WIN32 = False

import requests
from sqlalchemy import create_engine, Column, String, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError, OperationalError
from apscheduler.schedulers.background import BackgroundScheduler

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    import tkinter.font as tkfont
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(BASE_DIR, "paybaar_service.log")
SQLITE_DB_PATH = os.path.join(BASE_DIR, "paybaar_cache.db")

# ==========================================
# 2. Enterprise Logging System
# ==========================================
logger = logging.getLogger("PaybaarEnterprise")
logger.setLevel(logging.INFO)
if logger.hasHandlers():
    logger.handlers.clear()

try:
    log_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=20, encoding='utf-8')
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s')
    log_handler.setFormatter(log_formatter)
    logger.addHandler(log_handler)
except Exception as log_err:
    sys.stderr.write(f"Critical: Cannot initialize logging: {log_err}\n")

# ==========================================
# 3. DPAPI Encryption (Machine-Level)
# ==========================================
# فلگ CRYPTPROTECT_LOCAL_MACHINE اضافه شد تا سرویس (LocalSystem) و GUI (Admin) بتوانند دیتای هم را بخوانند
CRYPTPROTECT_LOCAL_MACHINE = 0x04

if IS_WINDOWS and HAS_WIN32:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    def encrypt_secret(plain_text: str) -> str:
        if not plain_text: return plain_text
        try:
            data = plain_text.encode('utf-8')
            data_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
            data_out = DATA_BLOB()
            result = ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(data_in), u"PaybaarSecretKey", None, None, None, CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(data_out)
            )
            if not result: raise ctypes.WinError()
            encrypted_bytes = ctypes.string_at(data_out.pbData, data_out.cbData)
            ctypes.windll.kernel32.LocalFree(data_out.pbData)
            return encrypted_bytes.hex()
        except Exception as e:
            logger.error(f"DPAPI Encryption failed: {e}")
            return plain_text

    def decrypt_secret(hex_string: str) -> str:
        if not hex_string or not all(c in '0123456789abcdefABCDEF' for c in hex_string): return hex_string
        try:
            data = bytes.fromhex(hex_string)
            data_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
            data_out = DATA_BLOB()
            result = ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(data_in), None, None, None, None, CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(data_out)
            )
            if not result: raise ctypes.WinError()
            decrypted_bytes = ctypes.string_at(data_out.pbData, data_out.cbData)
            ctypes.windll.kernel32.LocalFree(data_out.pbData)
            return decrypted_bytes.decode('utf-8')
        except Exception:
            return hex_string
else:
    def encrypt_secret(plain_text: str) -> str: return urllib.parse.quote(plain_text)
    def decrypt_secret(hex_string: str) -> str:
        try: return urllib.parse.unquote(hex_string)
        except: return hex_string

# ==========================================
# 4. Configuration & Database Models
# ==========================================
def discover_mysqldump():
    env_path = shutil.which("mysqldump")
    if env_path: return env_path
    for loc in ["c:\\xampp\\mysql\\bin\\mysqldump.exe", "C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin\\mysqldump.exe", "D:\\xampp\\mysql\\bin\\mysqldump.exe"]:
        if os.path.exists(loc): return loc
    return "mysqldump"

DEFAULT_CONFIG = {
    "db_host": "192.168.20.5", "db_user": "root", "db_pass": "Admin1@WB2024",
    "db_name": "weighbridge", "api_url": "https://road.paybaar.com/api/bol/issued",
    "api_auth": "Basic ODIxMTAwMDExMzpHZiNScGEwI09PYWtwVjdzJUlvfA==",
    "mysqldump_path": discover_mysqldump(), "backup_dir": "D:\\"
}

Base = declarative_base()

class SystemSetting(Base):
    __tablename__ = 'system_settings'
    key = Column(String(100), primary_key=True)
    value = Column(Text)

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
    sync_attempts = Column(Integer, default=0)

# ==========================================
# 5. Database Connection Management
# ==========================================
class DBManager:
    def __init__(self):
        self.sqlite_engine = None
        self.mysql_engine = None
        self.SqliteSession = None
        self.MysqlSession = None
        self.mysql_connected = False

    def init_sqlite(self):
        try:
            self.sqlite_engine = create_engine(f"sqlite:///{SQLITE_DB_PATH}", connect_args={"timeout": 15, "check_same_thread": False})
            self.SqliteSession = sessionmaker(bind=self.sqlite_engine)
            Base.metadata.create_all(self.sqlite_engine)
        except Exception as e:
            logger.critical(f"SQLite init failed: {e}")

    def init_mysql(self, config):
        escaped_password = urllib.parse.quote_plus(config["db_pass"])
        mysql_conn_str = f"mysql+pymysql://{config['db_user']}:{escaped_password}@{config['db_host']}/{config['db_name']}?charset=utf8mb4"
        try:
            # تنظیمات Pool برای جلوگیری از Deadlock و Timeout
            self.mysql_engine = create_engine(
                mysql_conn_str, pool_recycle=280, pool_pre_ping=True, pool_size=10, max_overflow=20, connect_args={"connect_timeout": 5}
            )
            self.MysqlSession = sessionmaker(bind=self.mysql_engine)
            with self.mysql_engine.connect():
                self.mysql_connected = True
            Base.metadata.create_all(self.mysql_engine)
        except Exception as e:
            self.mysql_connected = False
            logger.warning(f"MySQL connection unavailable. Running in offline mode. Error: {e}")

db = DBManager()

@contextmanager
def session_scope(session_factory):
    """Provide a transactional scope around a series of operations."""
    if not session_factory: raise ValueError("Session factory is None")
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def load_config():
    config = DEFAULT_CONFIG.copy()
    if not db.SqliteSession: return config
    try:
        with session_scope(db.SqliteSession) as session:
            rows = session.query(SystemSetting).all()
            if rows:
                db_keys = {row.key: row.value for row in rows}
                for k in config.keys():
                    if k in db_keys and db_keys[k] is not None and str(db_keys[k]).strip() != "":
                        val = db_keys[k]
                        if k in ["db_pass", "api_auth"]: val = decrypt_secret(val)
                        config[k] = val
            else:
                for k, v in config.items():
                    store_val = encrypt_secret(v) if k in ["db_pass", "api_auth"] else v
                    session.add(SystemSetting(key=k, value=store_val))
    except Exception as e:
        logger.error(f"Error loading config: {e}")
    return config

def save_config(config_data):
    if not db.SqliteSession: return
    try:
        with session_scope(db.SqliteSession) as session:
            for k, v in config_data.items():
                store_val = encrypt_secret(v) if k in ["db_pass", "api_auth"] else v
                setting = session.query(SystemSetting).filter_by(key=k).first()
                if setting: setting.value = store_val
                else: session.add(SystemSetting(key=k, value=store_val))
        logger.info("Configuration saved successfully.")
        db.init_mysql(load_config()) # Re-init MySQL with new config
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

# ==========================================
# 6. Data Parsing & Business Logic
# ==========================================
def convert_numbers(input_string):
    numerals = {'۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
                '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'}
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

def create_paybaar_obj(item, n1, l, n2, info_str):
    """تولید آبجکت دیتابیس بر اساس منطق پارس ثابت"""
    return Paybaar(
        bol_number=item['bol_number'], bol_serial_number=item['bol_serial_number'],
        bol_date=item['bol_date'], bol_time=item['bol_time'], bol_weight=item['bol_weight'],
        commodity=item['commodity'], package_type=item['package_type'],
        first_driver_name=item['driver_info']['first_driver']['name'],
        first_driver_national_code=item['driver_info']['first_driver']['national_code'],
        first_driver_cell_number=item['driver_info']['first_driver']['cell_number'],
        first_driver_smart_card=item['driver_info']['first_driver']['first_driver_smart_card'],
        second_driver_name=item['driver_info']['second_driver']['name'],
        second_driver_national_code=item['driver_info']['second_driver']['national_code'],
        second_driver_cell_number=item['driver_info']['second_driver']['cell_number'],
        second_driver_smart_card=item['driver_info']['second_driver']['second_driver_smart_card'],
        sender_name=item['sender']['name'], sender_company_identity=item['sender']['company_identity'],
        sender_postal_code=item['sender']['postal_code'], sender_address=item['sender']['address'],
        cargo_name=item['cargo']['name'], receiver_name=item['receiver']['name'],
        receiver_company_identity=item['receiver']['company_identity'],
        receiver_postal_code=item['receiver']['postal_code'], receiver_address=item['receiver']['address'],
        car_type=item['car']['car_type'], license_number=item['car']['license_number'],
        car_tag_n1=n1, car_tag_n2=n2, car_tag_l=l,
        car_tag_decode=item['car']['car_tag'].encode('utf-8').decode('unicode_escape'),
        car_tag=item['car']['car_tag'], car_tag_code=item['car']['car_tag_code'],
        car_tag_place=item['car']['car_tag_place'],
        total_remaining_fare=item['financial_information']['total_remaining_fare'],
        information=info_str
    )

def save_to_sqlite(item, n1, l, n2, info_str):
    if not db.SqliteSession: return
    try:
        with session_scope(db.SqliteSession) as session:
            if not session.query(Paybaar).filter_by(bol_number=item['bol_number']).first():
                session.add(create_paybaar_obj(item, n1, l, n2, info_str))
                logger.info(f"Buffered record {item['bol_number']} in local SQLite cache.")
    except Exception as e:
        logger.error(f"Failed to buffer record to SQLite: {e}")

def sync_sqlite_to_mysql():
    """انتقال امن داده‌ها از SQLite به MySQL بدون ایجاد Deadlock"""
    if not db.mysql_connected or not db.SqliteSession or not db.MysqlSession: return
    
    try:
        with session_scope(db.SqliteSession) as sqlite_session:
            pending_records = sqlite_session.query(Paybaar).filter(Paybaar.sync_attempts < 5).limit(50).all()
            if not pending_records: return
            
            for record in pending_records:
                sync_success = False
                try:
                    # استفاده از سشن مجزا برای هر رکورد در MySQL برای جلوگیری از قفل شدن Pool
                    with session_scope(db.MysqlSession) as mysql_session:
                        if not mysql_session.query(Paybaar).filter_by(bol_number=record.bol_number).first():
                            # کپی رکورد از SQLite به MySQL
                            mysql_session.add(create_paybaar_obj(record.__dict__, record.car_tag_n1, record.car_tag_l, record.car_tag_n2, record.information))
                    sync_success = True
                except IntegrityError:
                    sync_success = True # از قبل وجود داشته، پس موفق در نظر می‌گیریم تا از SQLite پاک شود
                except Exception as e:
                    record.sync_attempts += 1
                    logger.error(f"Failed to sync record {record.bol_number} to MySQL: {e}")
                
                if sync_success:
                    sqlite_session.delete(record)
                    
    except Exception as e:
        logger.error(f"Sync process encountered an error: {e}")

def fetch_and_store():
    """واکشی اطلاعات از API و ذخیره‌سازی (بدون هیچگونه Popup)"""
    logger.info("Executing API fetch operation...")
    conf = load_config()
    
    # بررسی وضعیت اتصال MySQL قبل از شروع
    if db.mysql_engine:
        try:
            with db.mysql_engine.connect(): db.mysql_connected = True
        except Exception: db.mysql_connected = False

    if db.mysql_connected: sync_sqlite_to_mysql()

    try:
        response = requests.get(conf["api_url"], headers={"Content-Type": "application/json", "Authorization": conf["api_auth"]}, timeout=15)
        if response.status_code == 200:
            data = response.json()
            info_str = str(data.get('information', ''))
            
            for item in data.get('data', []):
                if (item['sender']['company_identity'] == '10780091584') or ("اکسیر پویان" in item['receiver']['name']):
                    continue
                
                n1, l, n2 = split_car_tag(item['car']['car_tag'])
                n1_val = int(convert_numbers(n1)) if n1 else None
                n2_val = int(convert_numbers(n2)) if n2 else None
                
                saved_to_mysql = False
                if db.mysql_connected and db.MysqlSession:
                    try:
                        with session_scope(db.MysqlSession) as session:
                            if not session.query(Paybaar).filter_by(bol_number=item['bol_number']).first():
                                session.add(create_paybaar_obj(item, n1_val, l, n2_val, info_str))
                        saved_to_mysql = True
                    except Exception as e:
                        logger.warning(f"MySQL insert failed for {item['bol_number']}, falling back to SQLite: {e}")
                
                if not saved_to_mysql:
                    save_to_sqlite(item, n1_val, l, n2_val, info_str)
        else:
            logger.error(f"API returned status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Fetch routine exception: {e}")

def sql_backup():
    """تهیه نسخه پشتیبان با مدیریت خطای هوشمند (بدون کرش در صورت نبود mysqldump)"""
    conf = load_config()
    if not os.path.exists(conf["mysqldump_path"]):
        logger.warning(f"mysqldump tool not found at {conf['mysqldump_path']}. Backup skipped.")
        return
    if not os.path.isdir(conf["backup_dir"]):
        logger.warning(f"Backup directory {conf['backup_dir']} does not exist. Backup skipped.")
        return
        
    try:
        # پاکسازی بکاپ‌های قدیمی
        backup_pattern = os.path.join(conf["backup_dir"], "weighbridge_*.sql")
        backup_files = sorted(glob.glob(backup_pattern), key=os.path.getctime)
        if len(backup_files) > 200:
            for file in backup_files[:-200]: os.remove(file)

        # ایجاد بکاپ جدید
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(conf["backup_dir"], f"weighbridge_{timestamp}.sql")
        command = f'"{conf["mysqldump_path"]}" -u {conf["db_user"]} -p{conf["db_pass"]} -h {conf["db_host"]} {conf["db_name"]} > "{backup_file}"'
        subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        logger.info(f"Database backup created: {backup_file}")
    except Exception as e:
        logger.error(f"Backup operation failed: {e}")

# ==========================================
# 7. Windows Service Implementation
# ==========================================
if IS_WINDOWS and HAS_WIN32:
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
            self.scheduler.shutdown(wait=False)
            self.running = False
            logger.info("Service is stopping...")

        def SvcDoRun(self):
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED, (self._svc_name_, ''))
            logger.info("Service started successfully in Session 0.")
            
            db.init_sqlite()
            db.init_mysql(load_config())
            
            # اجرای اولیه
            fetch_and_store()
            sql_backup()
            
            # تنظیم زمان‌بندی
            self.scheduler.add_job(func=fetch_and_store, trigger="interval", minutes=1)
            self.scheduler.add_job(func=sql_backup, trigger="interval", minutes=10)
            self.scheduler.start()

            while self.running:
                rc = win32event.WaitForSingleObject(self.hWaitStop, 5000)
                if rc == win32event.WAIT_OBJECT_0: break

def check_service_status():
    if not IS_WINDOWS or not HAS_WIN32: return "غیرفعال (محیط غیر ویندوزی)"
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        h_service = win32service.OpenService(scm, "PaybaarFetchService", win32service.SERVICE_QUERY_STATUS)
        status_info = win32service.QueryServiceStatus(h_service)
        win32service.CloseServiceHandle(h_service)
        win32service.CloseServiceHandle(scm)
        
        state = status_info[1]
        if state == win32service.SERVICE_RUNNING: return "فعال و در حال اجرا 🟢"
        elif state == win32service.SERVICE_STOPPED: return "نصب شده (غیرفعال) 🟡"
        elif state == win32service.SERVICE_START_PENDING: return "در حال راه‌اندازی... ⏳"
        else: return "در حال تغییر وضعیت 🟡"
    except Exception:
        return "نصب نشده روی این سیستم 🔴"

def manage_service(action):
    if not IS_WINDOWS or not HAS_WIN32: return False, "فقط در ویندوز پشتیبانی می‌شود."
    try:
        exe_path = os.path.abspath(sys.argv[0])
        if action == "install":
            win32serviceutil.InstallService(
                None, "PaybaarFetchService", "Paybaar API Weighbridge Data Fetcher",
                description="سرویس واکشی خودکار داده‌ها از وب‌سرویس پایبار",
                exeName=f'"{exe_path}"', exeArgs="--run-as-service", startType=win32service.SERVICE_AUTO_START
            )
            return True, "سرویس با موفقیت نصب شد."
        elif action == "start":
            win32serviceutil.StartService("PaybaarFetchService")
            return True, "سرویس استارت شد."
        elif action == "uninstall":
            try: win32serviceutil.StopService("PaybaarFetchService")
            except: pass
            win32serviceutil.RemoveService("PaybaarFetchService")
            return True, "سرویس حذف شد."
    except Exception as e:
        return False, f"خطا در عملیات سرویس: {e}"

# ==========================================
# 8. GUI Application (Monitor Only)
# ==========================================
if HAS_GUI:
    class SettingsApp:
        def __init__(self, root):
            self.root = root
            self.root.title("مدیریت و پیکربندی سیستم پایبار")
            self.root.geometry("680x640")
            self.root.resizable(False, False)
            self.bg_color = "#f8fafc"
            self.root.configure(bg=self.bg_color)
            
            self.config = load_config()
            self.create_widgets()
            self.refresh_live_status()

        def create_widgets(self):
            main_frame = tk.Frame(self.root, bg=self.bg_color, padx=25, pady=20)
            main_frame.pack(fill=tk.BOTH, expand=True)

            status_frame = tk.LabelFrame(main_frame, text=" وضعیت سیستم (مانیتورینگ) ", bg=self.bg_color, padx=15, pady=10)
            status_frame.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 20))

            self.lbl_service_status = tk.Label(status_frame, text="سرویس ویندوز: درحال پایش...", bg=self.bg_color, fg="#0284c7")
            self.lbl_service_status.grid(row=0, column=0, sticky="w", padx=10)
            
            self.lbl_sqlite_status = tk.Label(status_frame, text="بافر آفلاین: درحال پایش...", bg=self.bg_color, fg="#475569")
            self.lbl_sqlite_status.grid(row=0, column=1, sticky="e", padx=10)

            fields = [
                ("آدرس سرور دیتابیس:", "db_host", False), ("نام دیتابیس:", "db_name", False),
                ("نام کاربری دیتابیس:", "db_user", False), ("گذرواژه دیتابیس:", "db_pass", True),
                ("هدر اعتبارسنجی (API Auth):", "api_auth", False), ("مسیر Mysqldump:", "mysqldump_path", False),
                ("مسیر بکاپ:", "backup_dir", False)
            ]

            self.entries = {}
            for idx, (label_text, key, is_password) in enumerate(fields):
                tk.Label(main_frame, text=label_text, bg=self.bg_color).grid(row=idx+1, column=1, sticky="e", pady=6)
                entry = ttk.Entry(main_frame, show="*" if is_password else "")
                entry.grid(row=idx+1, column=0, sticky="ew", pady=6)
                entry.insert(0, "********" if is_password else self.config.get(key, ""))
                self.entries[key] = entry

            ops_frame = tk.LabelFrame(main_frame, text=" مدیریت سرویس ", bg=self.bg_color, padx=15, pady=15)
            ops_frame.grid(row=len(fields)+1, column=0, columnspan=2, sticky="we", pady=(20, 15))

            ttk.Button(ops_frame, text="نصب و استارت سرویس", command=self.install_svc).grid(row=0, column=0, padx=5)
            ttk.Button(ops_frame, text="حذف سرویس", command=self.uninstall_svc).grid(row=0, column=1, padx=5)

            ttk.Button(main_frame, text="ذخیره تنظیمات", command=self.save_settings).grid(row=len(fields)+2, column=0, columnspan=2, pady=15, sticky="we")

        def refresh_live_status(self):
            self.lbl_service_status.config(text=f"سرویس ویندوز: {check_service_status()}")
            
            pending_count = 0
            if db.SqliteSession:
                try:
                    with session_scope(db.SqliteSession) as sess:
                        pending_count = sess.query(Paybaar).count()
                except: pass
            
            self.lbl_sqlite_status.config(text=f"بافر آفلاین: {pending_count} رکورد")
            self.root.after(3000, self.refresh_live_status)

        def install_svc(self):
            succ, msg = manage_service("install")
            if succ: manage_service("start")
            messagebox.showinfo("نتیجه", msg, parent=self.root)

        def uninstall_svc(self):
            succ, msg = manage_service("uninstall")
            messagebox.showinfo("نتیجه", msg, parent=self.root)

        def save_settings(self):
            new_config = {}
            for key, entry in self.entries.items():
                val = entry.get()
                new_config[key] = self.config[key] if val == "********" else val
            save_config(new_config)
            messagebox.showinfo("سیستم", "تنظیمات ذخیره شد. سرویس در اجرای بعدی از این تنظیمات استفاده می‌کند.", parent=self.root)

    def run_gui():
        # جلوگیری از اجرای چندباره GUI
        if IS_WINDOWS:
            mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "Global\\PaybaarGUI_Mutex")
            if ctypes.windll.kernel32.GetLastError() == 183: sys.exit(0)
            
        db.init_sqlite() # GUI فقط به SQLite برای خواندن تنظیمات و وضعیت نیاز دارد
        root = tk.Tk()
        app = SettingsApp(root)
        root.mainloop()

# ==========================================
# 9. Main Entry Point
# ==========================================
if __name__ == '__main__':
    # 1. اجرای به عنوان سرویس ویندوز (توسط Service Control Manager فراخوانی می‌شود)
    if IS_WINDOWS and HAS_WIN32 and '--run-as-service' in sys.argv:
        try:
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(PaybaarFetchService)
            servicemanager.StartServiceCtrlDispatcher()
        except Exception as e:
            logger.critical(f"Service dispatcher failed: {e}")
        sys.exit(0)

    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true', help="اجرای مستقیم ورکر (برای لینوکس/داکر)")
    args, _ = parser.parse_known_args()

    # 2. اجرای مستقیم ورکر (بدون سرویس ویندوز)
    if args.headless:
        db.init_sqlite()
        db.init_mysql(load_config())
        scheduler = BackgroundScheduler()
        scheduler.add_job(func=fetch_and_store, trigger="interval", minutes=1)
        scheduler.add_job(func=sql_backup, trigger="interval", minutes=10)
        scheduler.start()
        try:
            while True: time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()
        sys.exit(0)

    # 3. اجرای رابط کاربری (حالت پیش‌فرض با دابل کلیک)
    if IS_WINDOWS:
        # درخواست دسترسی ادمین برای مدیریت سرویس‌ها
        try: is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        except: is_admin = False
        
        if not is_admin:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv[1:]), None, 1)
            sys.exit(0)
            
    if HAS_GUI:
        run_gui()
    else:
        print("GUI libraries not found. Run with --headless to start worker.")
