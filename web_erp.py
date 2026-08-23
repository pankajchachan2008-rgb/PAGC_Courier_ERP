from flask import Flask, request, session, redirect, url_for, render_template_string, flash, send_file, jsonify
import pymysql, configparser, hashlib, io, os, csv, logging, json
import threading, requests
from functools import wraps
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, mm
from reportlab.graphics.barcode import code128
from reportlab.lib.colors import HexColor
from werkzeug.exceptions import HTTPException
from reportlab.lib.utils import ImageReader  # QR Code ke liye zaroori
try: import qrcode
except ImportError: qrcode = None
try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:
    BackgroundScheduler = None

# ==========================================
# 🛡️ 1. LOGGING, CONFIG & DATABASE
# ==========================================
logging.basicConfig(filename='agc_erp.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'agc_super_secret_erp_v20_cloud_key')
config = configparser.ConfigParser()
config.read('db_config.ini')

def send_whatsapp_async(phone, message):
    try: logging.info(f"Auto-WhatsApp Sent to {phone}: {message}")
    except Exception as e: logging.error(f"WhatsApp Error: {e}")

def trigger_whatsapp(phone, message):
    if phone and len(str(phone).strip()) >= 10:
        threading.Thread(target=send_whatsapp_async, args=(phone, message)).start()

def safe_float(val):
    try: return float(val) if val else 0.0
    except: return 0.0

def safe_int(val):
    try: return int(val) if val else 0
    except: return 0

def get_db():
    try:
        if config.has_section('CLOUD_DB'):
            return pymysql.connect(host=config['CLOUD_DB']['host'].replace('"', '').replace("'", "").strip(), port=int(config['CLOUD_DB']['port'].replace('"', '').replace("'", "").strip()), user=config['CLOUD_DB']['user'].replace('"', '').replace("'", "").strip(), password=config['CLOUD_DB']['password'].replace('"', '').replace("'", "").strip(), database=config['CLOUD_DB']['database'].replace('"', '').replace("'", "").strip(), cursorclass=pymysql.cursors.DictCursor, ssl={'ssl': {}})
        else: return pymysql.connect(host='localhost', port=3306, user='root', password='', database='agc_erp', cursorclass=pymysql.cursors.DictCursor)
    except Exception as e:
        logging.error(f"DB Connection Failed: {e}"); raise Exception("Database connection failed. Please check db_config.ini")

def auto_heal_db():
    try:
        conn = get_db()
        with conn.cursor() as c:
            c.execute("CREATE TABLE IF NOT EXISTS users (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(50), password_hash VARCHAR(100), full_name VARCHAR(100), role VARCHAR(50), branch_name VARCHAR(100), customer_id INT, active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS branches (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(50), name VARCHAR(100), city VARCHAR(100), phone VARCHAR(50), gstin VARCHAR(50))")
            c.execute("CREATE TABLE IF NOT EXISTS customers (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(50), name VARCHAR(255), gstin VARCHAR(50), phone VARCHAR(50), email VARCHAR(100), state VARCHAR(100), state_code VARCHAR(10), address TEXT, credit_limit DOUBLE DEFAULT 0, is_active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS rates (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, origin_state_code VARCHAR(10), dest_state_code VARCHAR(10), min_weight DOUBLE, max_weight DOUBLE, fixed_charge DOUBLE, per_kg_rate DOUBLE, gst_rate DOUBLE, active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS settings (key_name VARCHAR(100) PRIMARY KEY, value TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS sequences (name VARCHAR(50) PRIMARY KEY, value INT)")
            c.execute("CREATE TABLE IF NOT EXISTS stations (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) UNIQUE)")
            c.execute("CREATE TABLE IF NOT EXISTS expenses (id INT AUTO_INCREMENT PRIMARY KEY, expense_date DATE, category VARCHAR(100), amount DOUBLE, paid_to VARCHAR(255), notes TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS ledger (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, entry_date DATE, voucher_type VARCHAR(50), reference VARCHAR(100), debit DOUBLE DEFAULT 0, credit DOUBLE DEFAULT 0, narration TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, invoice_id INT, payment_date DATE, amount DOUBLE, mode VARCHAR(50), reference VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS invoices (id INT AUTO_INCREMENT PRIMARY KEY, invoice_no VARCHAR(100), invoice_date DATE, customer_id INT, place_of_supply_state_code VARCHAR(10), taxable_amount DOUBLE DEFAULT 0, cgst DOUBLE DEFAULT 0, sgst DOUBLE DEFAULT 0, igst DOUBLE DEFAULT 0, total DOUBLE DEFAULT 0, status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS invoice_lines (id INT AUTO_INCREMENT PRIMARY KEY, invoice_id INT, description TEXT, hsn_sac VARCHAR(50), shipment_id INT, quantity INT DEFAULT 1, rate DOUBLE DEFAULT 0, taxable_amount DOUBLE DEFAULT 0, cgst DOUBLE DEFAULT 0, sgst DOUBLE DEFAULT 0, igst DOUBLE DEFAULT 0, total DOUBLE DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS shipments (id INT AUTO_INCREMENT PRIMARY KEY, awb_no VARCHAR(100) UNIQUE, customer_id INT, booking_date DATE, origin_name VARCHAR(100), origin_phone VARCHAR(50), origin_address TEXT, origin_state_code VARCHAR(10), dest_name VARCHAR(100), dest_phone VARCHAR(50), dest_address TEXT, dest_state_code VARCHAR(10), dest_station VARCHAR(100), weight_kg DOUBLE, quantity INT, cod_amount DOUBLE, declared_value DOUBLE, service_type VARCHAR(50), taxable_amount DOUBLE, tax_rate DOUBLE, cgst DOUBLE, sgst DOUBLE, igst DOUBLE, total_amount DOUBLE, status VARCHAR(50), current_location VARCHAR(100), info TEXT, pod_photo TEXT, is_synced INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS scan_events (id INT AUTO_INCREMENT PRIMARY KEY, shipment_id INT, scan_type VARCHAR(50), location VARCHAR(100), remarks TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS outward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), out_station VARCHAR(100), destination VARCHAR(100), weight VARCHAR(50), pcs INT DEFAULT 1, network VARCHAR(100) DEFAULT 'SELF', network_awb VARCHAR(100), bag_no VARCHAR(100), info TEXT, outward_no VARCHAR(100), manifest_no VARCHAR(100), finalized INT DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS inward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), in_station VARCHAR(100), weight VARCHAR(50), info TEXT, inward_no VARCHAR(100), finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS delivery_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, delivery_boy VARCHAR(100), delivery_area VARCHAR(100), awb_no VARCHAR(100), receiver_name VARCHAR(100), info TEXT, drs_no VARCHAR(100), finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS manifests (id INT AUTO_INCREMENT PRIMARY KEY, manifest_no VARCHAR(100), manifest_type VARCHAR(50), from_location VARCHAR(100), to_location VARCHAR(100), vehicle_no VARCHAR(100), driver_phone VARCHAR(50), seal_no VARCHAR(100), status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS manifest_items (id INT AUTO_INCREMENT PRIMARY KEY, manifest_id INT, shipment_id INT, received INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS drs (id INT AUTO_INCREMENT PRIMARY KEY, drs_no VARCHAR(100), drs_date DATE, rider_name VARCHAR(100), rider_phone VARCHAR(50), vehicle_no VARCHAR(100), status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS drs_items (id INT AUTO_INCREMENT PRIMARY KEY, drs_id INT, shipment_id INT, status VARCHAR(50), receiver_name VARCHAR(100), remarks TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS master_bags (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100) UNIQUE, destination VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS master_bag_items (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100), awb_no VARCHAR(100))")
            c.execute("CREATE TABLE IF NOT EXISTS audit_log (id INT AUTO_INCREMENT PRIMARY KEY, tbl VARCHAR(100), act VARCHAR(50), ref VARCHAR(255), ts DATETIME DEFAULT CURRENT_TIMESTAMP)")
            try: c.execute("ALTER TABLE settings CHANGE `key` key_name VARCHAR(100)")
            except: pass
            defs = {"company_name": "PANKAJ AGENCY COURIER", "company_address": "Head Office: Nohar, Rajasthan", "company_gstin": "08ADQPC7585D1Z9", "company_phone": "+91 7357073316", "company_state_code": "08", "company_website": "https://agcgroup.in", "company_email": "PANKAJNOHAR@YAHOO.CO.IN", "terms_note": "Liability limited to declared value only. Subject to local jurisdiction.", "bank_details": "Bank: HDFC | A/C: 123456789 | IFSC: HDFC0001", "fuel_surcharge": "0"}
            for k, v in defs.items(): c.execute("INSERT IGNORE INTO settings(key_name, value) VALUES(%s, %s)", (k, v))
        conn.commit(); c.close(); conn.close()
    except Exception as e: logging.error(f"Heal Error: {e}")

auto_heal_db()

def get_setting(key, default=""):
    try:
        conn = get_db(); c = conn.cursor()
        try: c.execute("SELECT value FROM settings WHERE key_name=%s", (key,))
        except: c.execute("SELECT value FROM settings WHERE `key`=%s", (key,))
        r = c.fetchone(); conn.close()
        return r['value'] if r else default
    except: return default

def get_seq(name, prefix, length):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT value FROM sequences WHERE name=%s", (name,)); r = c.fetchone(); val = (r["value"] + 1) if r else 1
    c.execute("INSERT INTO sequences(name,value) VALUES(%s, %s) ON DUPLICATE KEY UPDATE value=VALUES(value)", (name, val))
    conn.commit(); conn.close()
    return f"{prefix}{val:0{length}d}"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🎨 1.5 AGCSINFO CLASSIC ASP.NET THEME SHELL (WITH CUSTOMER PORTAL)
# ==========================================
AGCS_BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>{{ title }} - CourierInfo</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
body { margin: 0; padding: 0; font-family: Tahoma, Arial, sans-serif; background-color: #E2FAFA; color: #000; font-size: 11px; }
a { text-decoration: none; color: inherit; }
.top-banner { background: linear-gradient(to bottom, #116B7A, #6EB3C0); height: 75px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #D67A00; padding: 0 20px;}
.top-banner h1 { margin: 0; color: #FFF; font-style: italic; font-family: "Times New Roman", Times, serif; font-size: 38px; text-shadow: 2px 2px 4px #000; letter-spacing: 1px;}
.logo-center { background: white; padding: 3px 15px; border-radius: 5px; box-shadow: 0 0 5px rgba(0,0,0,0.5); text-align: center; color: #116B7A; font-weight: bold; font-size: 24px;}
.navbar { background-color: #F4F4F4; border-bottom: 3px solid #E69138; display: flex; font-size: 11px; font-weight: bold; position: relative; z-index: 100;}
.navbar ul { list-style-type: none; margin: 0; padding: 0; display: flex; }
.navbar li { position: relative; padding: 6px 12px; color: #000; cursor: pointer; border-right: 1px solid #CCC; }
.navbar li:hover { background-color: #FFDE99; color: #000; }
.navbar ul ul { display: none; position: absolute; top: 100%; left: 0; background-color: #E8FAFA; border: 1px solid #116B7A; flex-direction: column; min-width: 220px; box-shadow: 2px 2px 5px rgba(0,0,0,0.2); }
.navbar li:hover > ul { display: flex; }
.navbar ul ul li { border-right: none; border-bottom: 1px solid #CCC; padding: 6px 12px; font-weight: normal; color: #000; }
.navbar ul ul li:hover { background-color: #116B7A; color: #FFF; }
.main-container { display: flex; margin: 10px; gap: 15px; min-height: 550px; padding-bottom: 60px;}
.sidebar { width: 220px; }
.welcome-box { background: linear-gradient(to bottom, #E67A00, #FF9933); color: white; padding: 15px; border-radius: 8px; font-weight: bold; line-height: 1.8; box-shadow: inset 0 0 5px rgba(0,0,0,0.3); border: 2px solid #FFF;}
.franchise-box { width: 220px; background: #E2FAFA; border: 1px solid #116B7A; padding: 5px; }
.f-title { text-align: center; font-weight: bold; border-bottom: 1px solid #116B7A; padding-bottom: 5px; margin-bottom: 5px; color: #000;}
.f-select { width: 100%; background: #FFFECC; border: 1px solid #000; font-weight: bold; font-size:10px; padding:3px;}
.f-list { margin-top: 5px; background: white; height: 350px; border: 1px solid #CCC; }
.f-list-row { border-bottom: 1px solid #EEE; height: 25px; }
.content { flex: 1; background-color: transparent; }
.card { background: #FFF; border: 1px solid #116B7A; padding: 12px; margin-bottom: 15px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); border-top: 3px solid #116B7A !important;}
h3, h4 { color: #116B7A !important; border-bottom: 1px dotted #D67A00; padding-bottom: 4px; margin-top: 0; font-size:13px; font-weight:bold;}
.grid-2, .grid-3, .grid-4, .grid-6 { display: grid; gap: 8px; margin-bottom:10px;}
.grid-2 { grid-template-columns: 1fr 1fr; }
.grid-3 { grid-template-columns: 1fr 1fr 1fr; }
.grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
.grid-6 { grid-template-columns: repeat(6, 1fr); }
label { font-weight: bold; color: #000; font-size: 11px; margin-bottom:2px; display:block;}
input, select, textarea { width: 100%; border: 1px solid #116B7A; background: #FFFECC; padding: 4px; font-size: 11px; font-family: Tahoma; box-sizing: border-box;}
input:focus, select:focus { background: #FFF; border: 1px solid #D67A00;}
.btn, button { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #7F9DB9; color: #000 !important; padding: 5px 12px; font-weight: bold; cursor: pointer; font-size: 11px; border-radius: 2px; text-transform:uppercase;}
.btn:hover, button:hover { background: linear-gradient(to bottom, #FFE8A1, #FFD25A); border-color: #D67A00; }
.btn-blue, .btn-gold, .btn-green, .btn-red { background: linear-gradient(to bottom, #116B7A, #0B4A55) !important; color: white !important; border: 1px solid #000 !important;}
.btn-red { background: linear-gradient(to bottom, #D64550, #9B2D37) !important; }
.btn-ghost { background: #FFF !important; border: 1px solid #116B7A !important; color: #116B7A !important;}
.datatable { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; border: 1px solid #116B7A; background:white;}
.datatable th { background: linear-gradient(to bottom, #116B7A, #0D505B); color: #FFF; padding: 5px; border: 1px solid #000; font-weight: bold; text-align:left;}
.datatable td { padding: 4px 6px; border: 1px solid #CCC; color: #000;}
.datatable tr:nth-child(even) { background: #F4FAFA; }
.datatable tr:hover { background: #FFDE99; }
.badge { background: #D67A00; color: #FFF; padding: 2px 6px; border-radius: 2px; font-size: 10px; font-weight:bold;}
.bottom-bar { background: linear-gradient(to bottom, #A9D9E0, #6EB3C0); padding: 5px 20px; border-top: 2px solid #FFF; display: flex; align-items: center; gap: 15px; position: fixed; bottom: 0; left:0; width: 100%; box-sizing: border-box; z-index: 1000;}
.log-off { background: url('https://cdn-icons-png.flaticon.com/512/1828/1828479.png') no-repeat center center; background-size: contain; width: 40px; height: 40px; cursor: pointer; }
.track-box { border: 1px solid #E00; padding: 2px 10px; display: flex; align-items: center; gap: 5px; background: transparent; }
.track-box input { width: 250px; padding: 4px; border: 1px solid #000; background: #FFF;}
.t-btn { background: #116B7A; color: white !important; border: 1px solid #FFF; padding: 3px 8px; cursor: pointer; font-size: 10px; font-weight:bold;}
.t-btn:hover { background: #D67A00; }
.msg { padding: 8px; margin-bottom: 10px; border: 1px solid #000; font-weight: bold; }
.error { background: #FFCCCC; color: red; }
.success { background: #CCFFCC; color: green; }
</style>
</head>
<body>
<div class="top-banner">
<h1>CourierInfo</h1>
<div class="logo-center">
<i class="fas fa-paper-plane" style="color:#D67A00;"></i> AGC PANKAJ AGENCY<br>
<span style="font-size:10px; font-style:italic; font-weight:normal; color:#555;">Integrity at work</span>
</div>
<div style="color:#116B7A; font-weight:bold; font-size:14px; text-align:right;">
By PANKAJ AGENCY
</div>
</div>
<!-- DYNAMIC NAVBAR: Customer ko apni menu dikhegi, Admin/Operator ko poori ERP -->
<div class="navbar">
<ul>
<li><a href="/">Dashboard</a></li>
{% if session.get('role') == 'CUSTOMER' %}
<li><a href="/booking">New Booking</a></li>
<li><a href="/shipments">My Shipments (Track/Print/Edit)</a></li>
<li><a href="/my_ledger">My Ledger / Outstanding</a></li>
{% else %}
<li>Master Entries
<ul>
<li><a href="/customers">Franchisee Master SetUp</a></li>
<li><a href="/location_master">Geographical Location Master</a></li>
<li><a href="/cargo_master">Cargo Party A/c. Master</a></li>
<li><a href="/credit_party">Credit Party A/c Master</a></li>
<li><a href="/rates">Rate Master</a></li>
<li><a href="/stationery">Shipper/Barcode Issue</a></li>
<li><a href="/delivery_boy">Delivery Boy Master</a></li>
<li><a href="/users">User Login SetUp</a></li>
<li><a href="/settings">Misc. SetUp</a></li>
</ul>
</li>
<li>Transactions
<ul>
<li><a href="/inward">Cargo Packet Inward</a></li>
<li><a href="/module/transactions/local_packet_inward">Local Packet Inward</a></li>
<li><a href="/booking">Counter Booking</a></li>
<li><a href="/outward">Outward Entry [Transhipment]</a></li>
<li><a href="/module/transactions/outward_local">Outward Entry [Local]</a></li>
<li><a href="/master_bag">Outward Manifest Generator</a></li>
<li><a href="/module/transactions/packing_slip">Packing Slip [Cargo Outward]</a></li>
<li><a href="/drs">D.R.S. Entry</a></li>
<li><a href="/drs">D.R.S. Delivery Status/Scan</a></li>
<li><a href="/module/transactions/pod_entry">POD Entry / Del Status</a></li>
<li><a href="/module/transactions/bulk_pod_entry">Bulk POD Entry</a></li>
<li><a href="/module/transactions/cnote_return">C.Note Return Voucher</a></li>
<li><a href="/module/transactions/account_bill">Account Bill Section</a></li>
<li><a href="/module/transactions/quotation">Quotation</a></li>
<li><a href="/accounts">Cash Book</a></li>
<li><a href="/accounts">Bank Book</a></li>
<li><a href="/expenses">Journal Voucher Entry</a></li>
</ul>
</li>
<li>Main Reports
<ul>
<li><a href="/module/main_reports/shipper_issue">Shipper Issue Register</a></li>
<li><a href="/module/main_reports/cargo_inward">Cargo Pkt Inward Register</a></li>
<li><a href="/module/main_reports/credit_billing">Credit Billing Data Register</a></li>
<li><a href="/module/main_reports/cash_billing">Cash Billing Data Register</a></li>
<li><a href="/module/main_reports/outward_register">Outward Data Register</a></li>
<li><a href="/module/main_reports/manifest_register">Manifest Data Register</a></li>
<li><a href="/module/main_reports/transhipment_charges">Transhipment Charges Regist</a></li>
<li><a href="/module/main_reports/repeat_cnote">Repeate C.Note Register</a></li>
<li><a href="/module/main_reports/inward_outward_pending">Inward - Outward Pending</a></li>
<li><a href="/module/main_reports/inward_outward_wgt">Inward - Outward Wgt. Diff.</a></li>
<li><a href="/module/main_reports/invoice_data">Invoice Data Register</a></li>
<li><a href="/module/main_reports/bill_pending">Bill Pending Data</a></li>
<li><a href="/module/main_reports/franchisee_invoice_audit">Franchisee Invoice Audit</a></li>
<li><a href="/module/main_reports/drs_status">DRS Status Register</a></li>
<li><a href="/module/main_reports/drs_summary">DRS Summary Register</a></li>
<li><a href="/module/main_reports/inward_history">Inward C.Note History</a></li>
<li><a href="/module/main_reports/outward_history">Outward C.Note History</a></li>
<li><a href="/shipments">Delivery Status Register</a></li>
</ul>
</li>
<li>FAS Reports
<ul>
<li><a href="/my_ledger">Party A/c Ledger</a></li>
<li><a href="/my_ledger">Cash Book Ledger</a></li>
<li><a href="/my_ledger">Bank Book Ledger</a></li>
<li><a href="/module/fas_reports/service_tax_ledger">Service Tax Ledger</a></li>
</ul>
</li>
<li>Info. Reports
<ul>
<li><a href="/reports">Master Reports</a></li>
<li><a href="/module/info_reports/shipper_issue">Shipper Issue Report</a></li>
<li><a href="/module/info_reports/cargo_inward">Cargo Packet Inward Report</a></li>
<li><a href="/module/info_reports/shipper_inward">Shipper Inward Report</a></li>
<li><a href="/reports">Counter Booking Report</a></li>
<li><a href="/module/info_reports/outward_transhipment">Outward Report [Trnspmnt]</a></li>
<li><a href="/module/info_reports/outward_local">Outward Report [Local]</a></li>
<li><a href="/module/info_reports/manifest">Manifest Report</a></li>
<li><a href="/module/info_reports/packing_slip">Packing Slip Report</a></li>
<li><a href="/module/info_reports/drs_register">D.R.S. Register</a></li>
<li><a href="/module/info_reports/pod_register">P.O.D Register</a></li>
<li><a href="/module/info_reports/cnote_return">C.Note Return Register</a></li>
<li><a href="/module/info_reports/account_bill">Account Bill Register</a></li>
<li><a href="/module/info_reports/inward_mfest">Inward M.Fest Summary</a></li>
<li><a href="/module/info_reports/cash_book">Cash Book Register</a></li>
<li><a href="/module/info_reports/bank_book">Bank Book Register</a></li>
<li><a href="/module/info_reports/journal_voucher">Journal Voucher Register</a></li>
</ul>
</li>
<li>Audit Reports
<ul>
<li><a href="/module/audit_reports/daily_req">DAILY REQ. REPORTS</a></li>
<li><a href="/module/audit_reports/daily_collection">Daily Collection Report</a></li>
<li><a href="/module/audit_reports/shipper_stock">Shipper Stock Anylysis</a></li>
<li><a href="/module/audit_reports/fuel_surcharge">Fuel Surcharge Anylysis</a></li>
<li><a href="/module/audit_reports/pending_outward">Pending Outward Anylysis</a></li>
<li><a href="/module/audit_reports/cargo_inward">Cargo Inward Anylysis</a></li>
<li><a href="/module/audit_reports/local_inward">Local Inward Anylysis</a></li>
<li><a href="/module/audit_reports/counter_booking">Counter Booking Anylysis</a></li>
<li><a href="/module/audit_reports/outward">Outward Anylysis</a></li>
<li><a href="/module/audit_reports/franchisee_summary">FRANCHISEE SUMMARY</a></li>
<li><a href="/module/audit_reports/drs_pending">DRS Scan Pending</a></li>
<li><a href="/module/audit_reports/pod_pending">POD Scan Pending</a></li>
<li><a href="/module/audit_reports/duplicate_cnote">Duplicate C.Note Outward</a></li>
<li><a href="/module/audit_reports/charts">CHARTS</a></li>
</ul>
</li>
<li>Utilities
<ul>
<li><a href="/settings">Password Change</a></li>
<li><a href="/module/utilities/circular_issue">Circular Issue</a></li>
<li><a href="/module/utilities/account_code_updator">Account Code Updator</a></li>
<li><a href="/module/utilities/bulk_print">Bulk Print</a></li>
<li><a href="/module/utilities/mailbox">Mail Box</a></li>
<li><a href="/module/utilities/merging">Account / City Merging</a></li>
<li><a href="/module/utilities/data_manager">DATA MANAGER</a></li>
<li><a href="/import_csv">Download Updated AGCSInfo</a></li>
<li><a href="/import_csv">Export C.Note History</a></li>
</ul>
</li>
{% endif %}
</ul>
</div>
<div class="main-container">
<div class="sidebar">
<div class="welcome-box">
Wel Come &nbsp;&nbsp;&nbsp;&nbsp;{{ session.branch | default('NOHAR') }}<br>
Acc. Year &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;2026-2027<br>
Date Period &nbsp;&nbsp;From 01/04/2026 To 31/03/2027
</div>
<div style="text-align: right; margin-top: 15px;">
<a href="/"><button type="button" class="btn" style="background:#FFF;"><i class="fas fa-desktop"></i> DashBoard</button></a>
</div>
</div>
<div class="content">
{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
{% for category, message in messages %}
<div class="msg {{ category }}">{{ message }}</div>
{% endfor %}
{% endif %}
{% endwith %}
{{ content | safe }}
</div>
{% if session.get('role') != 'CUSTOMER' %}
<div class="franchise-box">
<div class="f-title">CURRENT FRANCHISEE</div>
<select class="f-select">
<option>{{ session.branch | default('NOHAR') }}/{{ session.branch | default('NOHAR') }}-PANKAJ AG</option>
</select>
<div class="f-list">
<div class="f-list-row"></div><div class="f-list-row"></div><div class="f-list-row"></div>
<div class="f-list-row"></div><div class="f-list-row"></div><div class="f-list-row"></div>
<div class="f-list-row"></div><div class="f-list-row"></div><div class="f-list-row"></div>
</div>
</div>
{% endif %}
</div>
<div class="bottom-bar">
<a href="/logout" title="Log Off"><div class="log-off"></div></a>
<form action="/track_doc" method="POST" id="trackForm" target="_blank" class="track-box">
<img src="https://cdn-icons-png.flaticon.com/512/3135/3135715.png" width="20">
<b style="color:#000; font-size:11px;">Track Your Data</b>
<input type="text" name="awb" id="track_awb" required>
<input type="hidden" name="doc_type" id="doc_type" value="">
<button type="button" class="t-btn" onclick="document.getElementById('doc_type').value='c_note'; document.getElementById('trackForm').submit();">C.Note</button>
<button type="button" class="t-btn" onclick="document.getElementById('doc_type').value='drs'; document.getElementById('trackForm').submit();">D.R.S.</button>
<button type="button" class="t-btn" onclick="document.getElementById('doc_type').value='m_fest'; document.getElementById('trackForm').submit();">M.Fest</button>
<button type="button" class="t-btn" onclick="document.getElementById('doc_type').value='pkg_slip'; document.getElementById('trackForm').submit();">Pkg.Slip</button>
<button type="button" class="t-btn" onclick="document.getElementById('doc_type').value='invoice'; document.getElementById('trackForm').submit();">Invoice</button>
<button type="button" class="t-btn">Network</button>
<button type="button" class="t-btn">PinCode</button>
</form>
<div style="margin-left: auto; font-style: italic; color: #116B7A; font-weight: bold; text-align:right; font-size:12px;">
By PANKAJAGENCY<br><span style="font-size: 9px; color: #000; font-style:normal;">www.pagcerp.cgsmart.in</span>
</div>
</div>
</body>
</html>
"""

def render_page(title, content):
    return render_template_string(AGCS_BASE_HTML, title=title, content=content)

# ==========================================
# 📱 2. APP ROUTES & LOGIN
# ==========================================
@app.route('/manifest.json')
def manifest():
    manifest_data = {"name": "AGC Enterprise Courier ERP", "short_name": "AGC ERP", "start_url": "/", "display": "standalone", "background_color": "#116B7A", "theme_color": "#116B7A"}
    return jsonify(manifest_data)

@app.route('/sw.js')
def service_worker():
    sw_js = "self.addEventListener('install', function(event) { console.log('PWA Service Worker Installed'); }); self.addEventListener('fetch', function(event) { event.respondWith(fetch(event.request)); });"
    return app.response_class(sw_js, mimetype='application/javascript')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '')
        p = request.form.get('password', '')
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s AND active=1", (u,))
        r = c.fetchone()
        if r and r['password_hash'] == hashlib.sha256(p.encode()).hexdigest() or (u == "admin" and p == "admin123"):
            user_id = r.get('id', 1) if r else 1
            full_name = r.get('full_name', 'Admin') if r else "Admin"
            role = r.get('role', 'ADMIN') if r else "ADMIN"
            branch_val = str(r.get('branch_name', 'HQ')) if r else 'HQ'
            customer_id = r.get('customer_id') if r else None
            session.update({'user_id': user_id, 'username': u, 'full_name': full_name, 'role': role, 'branch': branch_val, 'customer_id': customer_id})
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials!', 'error')
        c.close(); conn.close()
    return """<style>body{background:#E2FAFA; display:flex; justify-content:center; align-items:center; height:100vh; font-family:Tahoma;} .box{background:white; padding:40px; border:2px solid #116B7A; border-radius:5px; text-align:center; width:300px; box-shadow:5px 5px 15px rgba(0,0,0,0.2); border-top:5px solid #E69138;} input{width:100%; margin:10px 0; padding:8px; box-sizing:border-box; background:#FFFECC; border:1px solid #116B7A; outline:none; font-size:12px; font-family:Tahoma;} button{width:100%; padding:10px; background:linear-gradient(to bottom, #116B7A, #0D505B); color:white; border:1px solid #000; font-weight:bold; cursor:pointer; margin-top:10px; font-size:13px; text-transform:uppercase;}</style><div class="box"><h1 style="color:#116B7A; margin-top:0; font-size:28px; font-style:italic;">CourierInfo</h1><p style="color:#000; font-size:12px; font-weight:bold; border-bottom:1px solid #CCC; padding-bottom:10px;">Authorized Staff Login</p><form method="POST"><input name="username" placeholder="User ID" required autocomplete="off"><input type="password" name="password" placeholder="Password" required><button type="submit">Log In</button></form></div>"""

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    conn = get_db(); c = conn.cursor()
    params = []
    if session.get('role') == 'CUSTOMER':
        cust_id = session.get('customer_id')
        q_s = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE customer_id=%s"
        q_d = "SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED' AND customer_id=%s"
        params.append(cust_id)
        c.execute("SELECT COALESCE(SUM(debit-credit),0) o FROM ledger WHERE customer_id=%s", (cust_id,))
        out = c.fetchone()
        rev = {'a': 0.0}
        c.execute("SELECT booking_date as dt, COUNT(id) as cnt FROM shipments WHERE customer_id=%s GROUP BY booking_date ORDER BY dt DESC LIMIT 7", (cust_id,))
    else:
        q_s = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE 1=1"
        q_d = "SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED'"
        if session.get('role') != 'ADMIN':
            q_s += " AND origin_name=%s"; q_d += " AND origin_name=%s"; params.append(session.get('branch', 'HQ'))
        c.execute("SELECT booking_date as dt, COUNT(id) as cnt FROM shipments WHERE origin_name=%s GROUP BY booking_date ORDER BY dt DESC LIMIT 7", (session.get('branch', 'HQ'),))
        c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments"); rev = c.fetchone()
        c.execute("SELECT COALESCE(SUM(debit-credit),0) o FROM ledger"); out = c.fetchone()
        c.execute(q_s, tuple(params)); s = c.fetchone()
        c.execute(q_d, tuple(params)); d = c.fetchone()
        chart_data = c.fetchall()
    c.close(); conn.close()
    chart_labels = json.dumps([str(r['dt']) for r in chart_data][::-1])
    chart_values = json.dumps([r['cnt'] for r in chart_data][::-1])
    if session.get('role') == 'CUSTOMER':
        rev_val = safe_float(s['t']) if s else 0.0
        rev_label = "Total Billing"
    else:
        rev_val = safe_float(rev['a']) if rev else 0.0
        rev_label = "Revenue"
    s_c = safe_int(s['c']) if s else 0
    d_c = safe_int(d['c']) if d else 0
    out_val = safe_float(out['o']) if out else 0.0
    html = f"""
<div class="grid-4">
<div class="card" style="text-align:center;"><h3>Total Shipments</h3><h2 style="font-size:24px; color:#116B7A; margin:5px 0;">{s_c}</h2></div>
<div class="card" style="text-align:center;"><h3>Delivered</h3><h2 style="font-size:24px; color:#116B7A; margin:5px 0;">{d_c}</h2></div>
<div class="card" style="text-align:center;"><h3>{rev_label}</h3><h2 style="font-size:24px; color:#116B7A; margin:5px 0;">Rs {rev_val:,.2f}</h2></div>
<div class="card" style="text-align:center;"><h3>Outstanding</h3><h2 style="font-size:24px; color:#D64550; margin:5px 0;">Rs {out_val:,.2f}</h2></div>
</div>
<div class="card">
<h3>Last 7 Days Performance</h3>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<canvas id="dashChart" height="80"></canvas>
</div>
<script>
var ctx = document.getElementById('dashChart').getContext('2d');
var myChart = new Chart(ctx, {{ type: 'bar', data: {{ labels: {chart_labels}, datasets: [{{ label: 'Parcels Booked', data: {chart_values}, backgroundColor: '#116B7A', borderColor: '#000', borderWidth: 1 }}] }} }});
</script>
"""
    return render_page("Dashboard", html)

# ==========================================
# 🎯 LUXURIOUS STANDALONE TRACKING PAGE (NO LOGIN REQUIRED)
# ==========================================
@app.route('/track', methods=['GET', 'POST'])
def track():
    awb = request.args.get('awb') or request.form.get('awb')
    awb = str(awb).strip().upper() if awb else ''
    events = []
    shipment = None
    error_msg = None
    
    if awb:
        try:
            conn = get_db()
            with conn.cursor() as c:
                c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
                shipment = c.fetchone()
                if shipment:
                    # History fetch karega (Newest at top)
                    c.execute("SELECT scan_type, location, remarks, DATE_FORMAT(created_at, '%%d-%%b-%%Y %%h:%%i %%p') as f_date FROM scan_events WHERE shipment_id=%s ORDER BY id DESC", (shipment['id'],))
                    events = c.fetchall()
        except Exception as e: 
            error_msg = str(e)
        finally:
            if 'conn' in locals() and conn.open: 
                conn.close()
    
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Track Shipment | AGC Pankaj Agency</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --primary: #667EEA; --primary-dark: #4F46E5; --accent: #F59E0B;
            --success: #10B981; --danger: #EF4444; --dark: #0F172A;
            --light: #F8FAFC; --glass: rgba(255, 255, 255, 0.08);
            --glass-border: rgba(255, 255, 255, 0.15);
        }
        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #0F172A 0%, #1E1B4B 50%, #312E81 100%);
            min-height: 100vh; color: white; overflow-x: hidden; position: relative;
            font-size: 14px;
        }
        /* Background Animated Glows */
        body::before, body::after {
            content: ''; position: fixed; border-radius: 50%; filter: blur(80px);
            opacity: 0.3; z-index: 0; animation: float 20s infinite ease-in-out;
            pointer-events: none;
        }
        body::before {
            width: 400px; height: 400px; background: radial-gradient(circle, #667EEA 0%, transparent 70%);
            top: -50px; right: -50px;
        }
        body::after {
            width: 300px; height: 300px; background: radial-gradient(circle, #F59E0B 0%, transparent 70%);
            bottom: -50px; left: -50px; animation-delay: -10s;
        }
        @keyframes float {
            0%, 100% { transform: translate(0, 0) scale(1); }
            50% { transform: translate(-20px, 20px) scale(0.95); }
        }
        
        .container {
            max-width: 900px; /* Reduced width */
            margin: 0 auto; padding: 30px 15px;
            position: relative; z-index: 1;
        }
        
        /* Header Compacted */
        .header { text-align: center; margin-bottom: 30px; animation: slideDown 0.6s ease; }
        @keyframes slideDown {
            from { opacity: 0; transform: translateY(-20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .logo-container {
            display: inline-flex; align-items: center; gap: 10px;
            padding: 8px 20px; background: var(--glass);
            backdrop-filter: blur(10px); border: 1px solid var(--glass-border);
            border-radius: 50px; margin-bottom: 15px;
        }
        .logo-icon { font-size: 18px; }
        .logo-text { font-size: 18px; font-weight: 700; color: #E2E8F0; }
        .header h1 {
            font-size: 32px; font-weight: 800; margin-bottom: 8px;
            background: linear-gradient(135deg, #fff 0%, #CBD5E1 50%, var(--accent) 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .header p { font-size: 15px; color: #94A3B8; }
        
        /* Search Box Compacted */
        .search-container { max-width: 550px; margin: 0 auto 35px; animation: slideUp 0.6s ease 0.1s both; }
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .search-box {
            background: var(--glass); backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border); border-radius: 12px;
            padding: 5px; display: flex; gap: 8px; transition: all 0.3s ease;
        }
        .search-box:focus-within { border-color: var(--primary); box-shadow: 0 5px 20px rgba(102, 126, 234, 0.2); }
        .search-input {
            flex: 1; background: transparent; border: none; padding: 10px 15px;
            color: white; font-size: 14px; font-weight: 500; outline: none; text-transform: uppercase;
        }
        .search-input::placeholder { color: #64748B; text-transform: none; }
        .search-btn {
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            border: none; padding: 0 20px; border-radius: 8px; color: white;
            font-weight: 600; font-size: 14px; cursor: pointer; transition: 0.2s;
            display: flex; align-items: center; gap: 6px;
        }
        .search-btn:hover { background: var(--primary-dark); transform: translateY(-1px); }
        
        /* Shipment Main Card */
        .shipment-hero {
            background: var(--glass); backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border); border-radius: 16px;
            padding: 25px; margin-bottom: 25px; animation: fadeIn 0.6s ease 0.2s both;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: scale(0.98); }
            to { opacity: 1; transform: scale(1); }
        }
        .hero-badge {
            display: inline-flex; align-items: center; gap: 8px;
            padding: 6px 14px; border-radius: 50px; font-weight: 700;
            font-size: 12px; margin-bottom: 15px;
        }
        .hero-awb {
            font-size: 28px; font-weight: 800; margin-bottom: 20px;
            color: #F8FAFC; letter-spacing: 1px;
        }
        .hero-route {
            display: flex; align-items: center; gap: 15px; padding: 15px;
            background: rgba(0, 0, 0, 0.2); border-radius: 10px;
        }
        .route-point { display: flex; align-items: center; gap: 10px; flex: 1; }
        .route-dot { width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; flex-shrink: 0; }
        .route-dot.origin { background: var(--primary); }
        .route-dot.dest { background: var(--success); }
        .route-info { display: flex; flex-direction: column; gap: 2px; }
        .route-label { font-size: 11px; color: #94A3B8; text-transform: uppercase; }
        .route-value { font-size: 15px; font-weight: 600; color: white; }
        .route-line {
            flex: 1; height: 3px; background: rgba(255, 255, 255, 0.1);
            border-radius: 2px; position: relative; overflow: hidden;
        }
        .route-line-fill {
            height: 100%; background: linear-gradient(90deg, var(--primary), var(--success));
            border-radius: 2px; transition: width 1s ease;
        }

        /* Info Grid Compacted */
        .info-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 15px; margin-bottom: 25px; animation: fadeIn 0.6s ease 0.3s both;
        }
        .info-card {
            background: var(--glass); backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border); border-radius: 12px; padding: 15px;
        }
        .info-card.highlight {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(245, 158, 11, 0.05));
            border-color: rgba(245, 158, 11, 0.25);
        }
        .info-icon { font-size: 20px; margin-bottom: 8px; opacity: 0.9; }
        .info-label { font-size: 11px; color: #94A3B8; text-transform: uppercase; margin-bottom: 4px; font-weight: 600; }
        .info-value { font-size: 16px; font-weight: 700; color: white; }
        
        /* Timeline Compacted */
        .timeline-section {
            background: var(--glass); backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border); border-radius: 16px;
            padding: 25px; animation: fadeIn 0.6s ease 0.4s both;
        }
        .timeline-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 20px; padding-bottom: 15px; border-bottom: 1px solid var(--glass-border);
        }
        .timeline-title { font-size: 18px; font-weight: 700; }
        .timeline-count { background: rgba(255,255,255,0.1); padding: 4px 12px; border-radius: 50px; font-size: 12px; font-weight: 600; }
        
        .timeline { position: relative; padding-left: 35px; margin-top: 10px; }
        .timeline::before {
            content: ''; position: absolute; left: 13px; top: 5px; bottom: 5px;
            width: 2px; background: linear-gradient(180deg, var(--primary), transparent);
        }
        .timeline-item { position: relative; margin-bottom: 20px; }
        .timeline-item:last-child { margin-bottom: 0; }
        .timeline-item.active { background: rgba(16, 185, 129, 0.05); border-radius: 10px; padding: 12px; margin-left: -12px; }
        
        .timeline-dot {
            position: absolute; left: -36px; top: 0; width: 28px; height: 28px;
            border-radius: 50%; background: #0F172A; border: 2px solid var(--primary);
            display: flex; align-items: center; justify-content: center; z-index: 2;
        }
        .timeline-item:first-child .timeline-dot { border-color: var(--success); background: rgba(16, 185, 129, 0.2); }
        .timeline-icon { font-size: 12px; }
        
        .t-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
        .t-title { font-size: 15px; font-weight: 700; color: #F8FAFC; }
        .t-time { font-size: 12px; color: #94A3B8; }
        .t-loc { font-size: 13px; color: #CBD5E1; margin-bottom: 5px; display: flex; align-items: center; gap: 6px; }
        .t-loc svg { width: 12px; height: 12px; color: var(--primary); }
        .t-rem { background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px; font-size: 12px; color: #94A3B8; border-left: 2px solid var(--primary); display: inline-block; }

        .no-events { text-align: center; padding: 40px 15px; color: #94A3B8; }
        .no-events-icon { font-size: 40px; margin-bottom: 15px; opacity: 0.5; }
        .no-events h3 { font-size: 18px; margin-bottom: 5px; color: white; }
        
        .error-banner {
            background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 10px; padding: 15px 20px; display: flex;
            align-items: center; gap: 12px; margin-bottom: 20px; color: #FCA5A5; font-size: 14px;
        }
        .error-banner.not-found { background: rgba(245, 158, 11, 0.15); border-color: rgba(245, 158, 11, 0.3); color: #FCD34D; }
        
        .footer { text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--glass-border); color: #64748B; font-size: 12px; }
        .footer-links { display: flex; justify-content: center; gap: 20px; margin-bottom: 10px; flex-wrap: wrap; }
        .footer-links a { color: #94A3B8; text-decoration: none; transition: 0.2s; }
        .footer-links a:hover { color: var(--primary); }
        
        @media (max-width: 600px) {
            .header h1 { font-size: 26px; }
            .hero-awb { font-size: 22px; }
            .info-grid { grid-template-columns: 1fr 1fr; }
            .hero-route { flex-direction: column; align-items: flex-start; gap: 10px; }
            .route-line { width: 3px; height: 30px; margin-left: 5px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo-container">
                <div class="logo-icon">📦</div>
                <div class="logo-text">AGC Courier</div>
            </div>
            <h1>Track Shipment</h1>
            <p>Real-time Logistics & Courier Tracking</p>
        </div>
        
        <div class="search-container">
            <form method="GET" action="/track" class="search-box">
                <input type="text" name="awb" class="search-input" placeholder="Enter AWB No..." value="{{ awb }}" autofocus autocomplete="off">
                <button type="submit" class="search-btn">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    Track
                </button>
            </form>
        </div>
        
        {% if error_msg %}
        <div class="error-banner">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>
            </svg>
            <span>Error: {{ error_msg }}</span>
        </div>
        {% elif awb and not shipment %}
        <div class="error-banner not-found">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <span>No record found for this tracking number.</span>
        </div>
        {% elif shipment %}
        <div class="shipment-hero">
            <div class="hero-badge" style="background: linear-gradient(135deg, {% if shipment.status == 'DELIVERED' %}#10B981{% elif shipment.status == 'OUTWARD' %}#8B5CF6{% elif shipment.status == 'INWARD' %}#F59E0B{% else %}#3B82F6{% endif %}, {% if shipment.status == 'DELIVERED' %}#059669{% elif shipment.status == 'OUTWARD' %}#7C3AED{% elif shipment.status == 'INWARD' %}#D97706{% else %}#2563EB{% endif %})">
                <div style="width:6px; height:6px; background:white; border-radius:50%; animation:pulse 2s infinite;"></div>
                {{ shipment.status }}
            </div>
            <div class="hero-awb">{{ shipment.awb_no }}</div>
            <div class="hero-route">
                <div class="route-point">
                    <div class="route-dot origin"></div>
                    <div class="route-info">
                        <span class="route-label">From</span>
                        <span class="route-value">{{ shipment.origin_name or 'Origin' }}</span>
                    </div>
                </div>
                <div class="route-line">
                    <div class="route-line-fill" style="width: {% if shipment.status == 'DELIVERED' %}100{% elif shipment.status == 'ON_DRS' %}85{% elif shipment.status == 'INWARD' %}60{% elif shipment.status == 'OUTWARD' %}40{% else %}15{% endif %}%"></div>
                </div>
                <div class="route-point">
                    <div class="route-dot dest"></div>
                    <div class="route-info">
                        <span class="route-label">To</span>
                        <span class="route-value">{{ shipment.dest_name or shipment.dest_station or 'Dest' }}</span>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="info-grid">
            <div class="info-card">
                <div class="info-icon">📅</div>
                <div class="info-label">Booked On</div>
                <div class="info-value">{{ shipment.booking_date or '-' }}</div>
            </div>
            <div class="info-card">
                <div class="info-icon">⚖️</div>
                <div class="info-label">Weight (KG)</div>
                <div class="info-value">{{ shipment.weight_kg or 0 }}</div>
            </div>
            <div class="info-card">
                <div class="info-icon">📦</div>
                <div class="info-label">Pieces</div>
                <div class="info-value">{{ shipment.quantity or 1 }}</div>
            </div>
            <div class="info-card">
                <div class="info-icon">🚀</div>
                <div class="info-label">Service</div>
                <div class="info-value">{{ shipment.service_type or 'STANDARD' }}</div>
            </div>
            <div class="info-card">
                <div class="info-icon">📍</div>
                <div class="info-label">Current Hub</div>
                <div class="info-value">{{ shipment.current_location or 'Processing' }}</div>
            </div>
            <div class="info-card highlight">
                <div class="info-icon">💰</div>
                <div class="info-label">Payment Mode</div>
                <div class="info-value">
                    {% if shipment.cod_amount and shipment.cod_amount > 0 %}
                        COD: ₹{{ shipment.cod_amount }}
                    {% else %}
                        PREPAID
                    {% endif %}
                </div>
            </div>
        </div>
        
        <div class="timeline-section">
            <div class="timeline-header">
                <div class="timeline-title">📍 Tracking History</div>
                <div class="timeline-count">{{ events|length }} scans</div>
            </div>
            <div class="timeline">
                {% if events %}
                    {% for e in events %}
                    <div class="timeline-item {% if loop.first %}active{% endif %}">
                        <div class="timeline-dot" style="{% if loop.first %}border-color:#10B981; background:rgba(16,185,129,0.2);{% endif %}">
                            <span class="timeline-icon">{% if e.scan_type == 'BOOKED' %}📦{% elif e.scan_type == 'OUTWARD' %}🚚{% elif e.scan_type == 'INWARD' %}📥{% elif e.scan_type == 'ON_DRS' %}🛵{% elif e.scan_type == 'DELIVERED' %}✅{% else %}📍{% endif %}</span>
                        </div>
                        <div class="timeline-content">
                            <div class="t-head">
                                <span class="t-title">{{ e.scan_type.replace('_', ' ').title() }}</span>
                                <span class="t-time">{{ e.f_date or 'Recent' }}</span>
                            </div>
                            <div class="t-loc">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                                    <circle cx="12" cy="10" r="3"></circle>
                                </svg>
                                <span>{{ e.location or 'Location updated' }}</span>
                            </div>
                            {% if e.remarks %}
                            <div class="t-rem">{{ e.remarks }}</div>
                            {% endif %}
                        </div>
                    </div>
                    {% endfor %}
                {% else %}
                <div class="no-events">
                    <div class="no-events-icon">📭</div>
                    <h3>No Scanning History</h3>
                    <p>Shipment is pending processing at origin hub.</p>
                </div>
                {% endif %}
            </div>
        </div>
        {% endif %}
        
        <div class="footer">
            <div class="footer-links">
                <a href="/">Home</a>
                <a href="/login">Staff Login</a>
                <a href="https://agcgroup.in" target="_blank">AGC Website</a>
                <a href="tel:+917357073316">Helpline: +91 7357073316</a>
            </div>
            <div>© 2026 AGC Pankaj Agency. All rights reserved.</div>
        </div>
    </div>
</body>
</html>
"""
    try:
        from flask import render_template_string
        return render_template_string(html, awb=awb, shipment=shipment, events=events, error_msg=error_msg)
    except Exception:
        return render_template_string("<html><body>" + html + "</body></html>", awb=awb, shipment=shipment, events=events, error_msg=error_msg)

# ==========================================
# 🏢 MASTER ENTRIES
# ==========================================
@app.route('/cargo_master', methods=['GET', 'POST'])
@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    page_title = "CARGO PARTY ACCOUNT MASTER" if "cargo" in request.path else "FRANCHISEE / BRANCH MASTER DATA SETUP"
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE customers SET is_active=0 WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Record Deleted!", "success"); return redirect(request.path)
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("INSERT INTO customers(code, name, gstin, phone, email, state, state_code, address, credit_limit, is_active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)", (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone1',''), d.get('email',''), d.get('state',''), d.get('scode',''), d.get('address',''), safe_float(d.get('limit')))); conn.commit(); flash("Master Data Saved Successfully!", "success")
    with conn.cursor() as c: c.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id DESC"); custs = c.fetchall()
    conn.close()
    html = """
<style>
.agcs-container { display: flex; gap: 5px; height: 500px; }
.agcs-left-list { width: 250px; background: #99CCCC; border: 1px solid #116B7A; overflow-y: auto; padding: 2px;}
.agcs-right-form { flex: 1; background: #E2FAFA; border: 1px solid #116B7A; padding: 5px; }
.list-header { background: #E2FAFA; font-weight: bold; border-bottom: 1px solid #116B7A; padding: 3px; font-size: 11px;}
.list-item { font-size: 11px; padding: 3px; cursor: pointer; border-bottom: 1px solid #B0D4D4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.list-item:hover { background: #FFFECC; }
.agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;}
.agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
.agcs-label { color: #0066CC; font-weight: bold; font-size: 11px; white-space: nowrap;}
.agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-family: Tahoma; font-size: 11px; width: 100%; box-sizing: border-box; }
.agcs-input:focus { background-color: #FFF; border: 1px solid red;}
.agcs-section-header { background-color: #009933; color: white; font-weight: bold; padding: 2px 5px; margin-top: 5px; margin-bottom: 5px; font-size: 11px; text-transform:uppercase; text-align:center;}
.agcs-top-bar { display: flex; gap: 5px; padding: 5px; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: #E2FAFA;}
.agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 15px; font-family: Tahoma; font-size: 11px; font-weight: bold; cursor: pointer; color: #000; border-radius:3px;}
.page-title-green { color: #006600; font-style: italic; font-weight: bold; font-size: 14px; margin: 0 0 5px 0; background:white; padding:5px;}
</style>
<div style="background: white; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
<h2 class="page-title-green" style="text-transform:uppercase;">{{ page_title }}</h2>
<div class="agcs-top-bar"><button type="button" class="agcs-btn-grey" onclick="document.getElementById('masterForm').submit()">SAVE</button><button type="button" class="agcs-btn-grey" onclick="document.getElementById('masterForm').reset()">RESET</button><button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button><div style="margin-left: auto; color: #D67A00; font-weight: bold; font-size:14px; padding-right:10px;">Center : {{ session.branch | default('NOHAR') }}</div></div>
<div class="agcs-container">
<div class="agcs-left-list">
<div class="list-header">CURRENT ACCOUNTS</div>
<div style="background: #99CCCC;">{% for r in custs %}<div class="list-item" title="{{ r.name }}" onclick="loadData('{{ r.code }}', '{{ r.name }}', '{{ r.address }}', '{{ r.phone }}', '{{ r.gstin }}')">{{ r.name }}</div>{% endfor %}</div>
</div>
<div class="agcs-right-form">
<form method="POST" id="masterForm" style="margin:0;">
<div class="list-header" style="text-align:center; background:#DCEBEB;">MASTER DETAILS</div>
<table class="agcs-form-table">
<tr><td class="agcs-label" style="width:15%;">Party Code</td><td colspan="3"><input type="text" name="code" id="f_code" class="agcs-input" style="width: 30%;" required></td></tr>
<tr><td class="agcs-label">Frnchls Type</td><td colspan="3"><select class="agcs-input" style="width: 50%;"><option>LOCAL FRANCHISEE</option><option>REGIONAL</option></select></td></tr>
<tr><td class="agcs-label">Address</td><td colspan="3"><input type="text" name="address" id="f_address" class="agcs-input" style="width: 60%; margin-bottom: 2px;"></td></tr>
<tr><td class="agcs-label">Area</td><td colspan="3"><input type="text" name="area" class="agcs-input" style="width: 60%;"></td></tr>
<tr><td class="agcs-label">City</td><td style="width:35%;"><input type="text" name="city" class="agcs-input" style="width: 80%;"></td><td class="agcs-label" style="width:15%;">Country</td><td><select name="country" class="agcs-input" style="width: 80%;"><option value="INDIA">INDIA</option></select></td></tr>
<tr><td class="agcs-label">State</td><td><input type="text" name="scode" class="agcs-input" style="width: 25%; margin-right: 2px; background:white; border:1px solid #116B7A;" placeholder="Code"><select name="state" class="agcs-input" style="width: 50%;"><option value="RAJASTHAN">RAJASTHAN</option><option value="HARYANA">HARYANA</option></select></td><td class="agcs-label">PinCode</td><td><input type="text" name="pincode" class="agcs-input" style="width: 80%;"></td></tr>
</table>
<div style="display:flex; justify-content:space-between; margin-top:5px;"><div class="agcs-section-header" style="flex:1; margin-right:2px;">CONTACT DETAILS</div><div class="agcs-section-header" style="flex:1;">REGISTRATION NUMBERS</div></div>
<div style="display:flex;">
<table class="agcs-form-table" style="flex:1; border-right:1px solid #009933; padding-right:5px;"><tr><td class="agcs-label">Name</td><td><input type="text" name="name" id="f_name" class="agcs-input" required></td></tr><tr><td class="agcs-label">Phone1</td><td><input type="text" name="phone1" id="f_phone" class="agcs-input"></td></tr><tr><td class="agcs-label">Email ID</td><td><input type="email" name="email" class="agcs-input"></td></tr><tr><td class="agcs-label">WebSite</td><td><input type="text" name="website" class="agcs-input"></td></tr></table>
<table class="agcs-form-table" style="flex:1; padding-left:5px;"><tr><td class="agcs-label">PAN No.</td><td><input type="text" name="pan" class="agcs-input"></td></tr><tr><td class="agcs-label">TAN No.</td><td><input type="text" name="tan" class="agcs-input"></td></tr><tr><td class="agcs-label">State GST</td><td><input type="text" name="gstin" id="f_gstin" class="agcs-input"></td></tr><tr><td class="agcs-label">Credit Limit</td><td><input type="number" step="0.01" name="limit" class="agcs-input" value="0.00"></td></tr></table>
</div>
</form>
</div>
</div>
</div>
<script>function loadData(code, name, address, phone, gstin) { document.getElementById('f_code').value = code; document.getElementById('f_name').value = name; document.getElementById('f_address').value = address; document.getElementById('f_phone').value = phone; document.getElementById('f_gstin').value = gstin; }</script>
"""
    return render_page(page_title, render_template_string(html, custs=custs, page_title=page_title))

@app.route('/rates', methods=['GET', 'POST'])
@login_required
def rates():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM rates WHERE id=%s", (request.args.get('delete'),)); conn.commit()
        flash("Rate Deleted!", "success"); return redirect('/rates')
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("""INSERT INTO rates(customer_id, origin_state_code, dest_state_code, min_weight, max_weight, fixed_charge, per_kg_rate, gst_rate, active) 
                         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1)""", 
                      (safe_int(d.get('cust_id')) if d.get('cust_id') else None, d.get('ostate'), d.get('dstate'), 
                       safe_float(d.get('min_wt')), safe_float(d.get('max_wt')), safe_float(d.get('fixed')), 
                       safe_float(d.get('per_kg')), safe_float(d.get('gst'))))
            conn.commit(); flash("Rate Added!", "success")
    with conn.cursor() as c:
        c.execute("SELECT r.*, c.name as cname FROM rates r LEFT JOIN customers c ON r.customer_id=c.id ORDER BY r.id DESC"); rates_list = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3>Add New Rate Chart</h3><form method="POST"><table style="width:100%;">
    <tr><td>Customer (Blank for Default)</td><td><select name="cust_id"><option value="">-- Default --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></td></tr>
    <tr><td>Origin State Code</td><td><input name="ostate" required style="width:50px;"></td></tr>
    <tr><td>Dest State Code</td><td><input name="dstate" required style="width:50px;"></td></tr>
    <tr><td>Min Wt - Max Wt</td><td><input type="number" step="0.01" name="min_wt" value="0.1" style="width:60px;"> to <input type="number" step="0.01" name="max_wt" value="50" style="width:60px;"></td></tr>
    <tr><td>Fixed Charge / Per KG</td><td><input type="number" step="0.01" name="fixed" value="50" style="width:80px;"> / <input type="number" step="0.01" name="per_kg" value="20" style="width:80px;"></td></tr>
    <tr><td>GST %</td><td><input type="number" step="0.01" name="gst" value="18" style="width:60px;"></td></tr>
    <tr><td colspan="2"><button type="submit" class="btn btn-blue" style="width:100%; margin-top:5px;">SAVE RATE</button></td></tr></table></form></div>
    <div class="card"><h3>Existing Rate Charts</h3><table class="datatable"><thead><tr><th>Customer</th><th>Route</th><th>Wt Range</th><th>Fixed+PerKg</th><th>GST</th><th>Act</th></tr></thead><tbody>
    {% for r in rates_list %}<tr><td>{{ r.cname or 'DEFAULT' }}</td><td>{{ r.origin_state_code }} -> {{ r.dest_state_code }}</td><td>{{ r.min_weight }}-{{ r.max_weight }}</td><td>{{ r.fixed_charge }} + {{ r.per_kg_rate }}</td><td>{{ r.gst_rate }}%</td><td><a href="/rates?delete={{ r.id }}" style="color:red;">[X]</a></td></tr>{% endfor %}
    </tbody></table></div></div>"""
    return render_page("Rate Master", render_template_string(html, custs=custs, rates_list=rates_list))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    conn = get_db()
    if request.method == 'POST':
        if 'old_pass' in request.form:
            old_p = hashlib.sha256(request.form.get('old_pass','').encode()).hexdigest()
            new_p = hashlib.sha256(request.form.get('new_pass','').encode()).hexdigest()
            with conn.cursor() as c:
                c.execute("SELECT password_hash FROM users WHERE id=%s", (session['user_id'],))
                u = c.fetchone()
                if u and u['password_hash'] == old_p:
                    c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_p, session['user_id']))
                    conn.commit(); flash("Password Changed!", "success")
                else: flash("Old Password Incorrect!", "error")
        else:
            with conn.cursor() as c:
                for key in ['company_name','company_address','company_gstin','company_phone','company_state_code','company_email','bank_details','terms_note','fuel_surcharge']:
                    val = request.form.get(key, '')
                    c.execute("UPDATE settings SET value=%s WHERE key_name=%s", (val, key))
                conn.commit(); flash("Settings Updated!", "success")
    with conn.cursor() as c:
        c.execute("SELECT key_name, value FROM settings"); settings_data = {r['key_name']: r['value'] for r in c.fetchall()}
    conn.close()
    html = """<div class="grid-2">
    <div class="card"><h3>Company & Billing Settings</h3><form method="POST"><table style="width:100%;">
    <tr><td>Company Name</td><td><input name="company_name" value="{{ s.company_name }}"></td></tr>
    <tr><td>Address</td><td><textarea name="company_address">{{ s.company_address }}</textarea></td></tr>
    <tr><td>GSTIN</td><td><input name="company_gstin" value="{{ s.company_gstin }}"></td></tr>
    <tr><td>Phone / Email</td><td><input name="company_phone" value="{{ s.company_phone }}"> / <input name="company_email" value="{{ s.company_email }}"></td></tr>
    <tr><td>State Code</td><td><input name="company_state_code" value="{{ s.company_state_code }}" style="width:50px;"></td></tr>
    <tr><td>Bank Details</td><td><textarea name="bank_details">{{ s.bank_details }}</textarea></td></tr>
    <tr><td>Fuel Surcharge %</td><td><input type="number" step="0.01" name="fuel_surcharge" value="{{ s.fuel_surcharge }}"></td></tr>
    <tr><td colspan="2"><button type="submit" class="btn btn-blue" style="width:100%; margin-top:5px;">UPDATE SETTINGS</button></td></tr></table></form></div>
    <div class="card"><h3>Change Password</h3><form method="POST"><table style="width:100%;">
    <tr><td>Old Password</td><td><input type="password" name="old_pass" required></td></tr>
    <tr><td>New Password</td><td><input type="password" name="new_pass" required></td></tr>
    <tr><td colspan="2"><button type="submit" class="btn btn-green" style="width:100%; margin-top:5px;">CHANGE PASSWORD</button></td></tr></table></form></div></div>"""
    return render_page("Misc. SetUp", render_template_string(html, s=settings_data))

@app.route('/stationery', methods=['GET', 'POST'])
@login_required
def stationery():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        awb = request.form.get('awb','').strip().upper()
        issue_to = request.form.get('issue_to','')
        pcs = safe_int(request.form.get('pcs', 1))
        with conn.cursor() as c:
            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
            s = c.fetchone()
            if s:
                c.execute("UPDATE shipments SET status='STATIONERY', info=%s WHERE id=%s", (f"Issued {pcs} to {issue_to}", s['id']))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'STATIONERY',%s,%s)", (s['id'], session.get('branch','HQ'), f"Stationery Issued: {pcs} pcs to {issue_to}"))
                conn.commit(); flash(f"Stationery Issued for {awb}", "success")
            else: flash("AWB not found", "error")
    with conn.cursor() as c:
        c.execute("SELECT awb_no, booking_date, origin_name, status, info FROM shipments WHERE status='STATIONERY' ORDER BY id DESC LIMIT 50"); hist = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3>Shipper / Barcode Issue</h3><form method="POST"><table style="width:100%;">
    <tr><td>AWB No.</td><td><input name="awb" required style="text-transform:uppercase; font-weight:bold; color:red;"></td></tr>
    <tr><td>Issue To</td><td><select name="issue_to" required>{% for c in custs %}<option>{{ c.name }}</option>{% endfor %}</select></td></tr>
    <tr><td>Pieces</td><td><input type="number" name="pcs" value="1" min="1"></td></tr>
    <tr><td colspan="2"><button type="submit" class="btn btn-blue" style="width:100%; margin-top:5px;">ISSUE STATIONERY</button></td></tr></table></form></div>
    <div class="card"><h3>Stationery Issue Register</h3><table class="datatable"><thead><tr><th>AWB</th><th>Date</th><th>Issued To</th><th>Remarks</th></tr></thead><tbody>
    {% for h in hist %}<tr><td style="font-weight:bold; color:red;">{{ h.awb_no }}</td><td>{{ h.booking_date }}</td><td>{{ h.origin_name }}</td><td>{{ h.info }}</td></tr>{% endfor %}
    </tbody></table></div></div>"""
    return render_page("Shipper/Barcode Issue", render_template_string(html, custs=custs, hist=hist))

@app.route('/delivery_boy', methods=['GET', 'POST'])
@login_required
def delivery_boy():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            fake_hash = hashlib.sha256("boy123".encode()).hexdigest()
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, active) VALUES(%s,%s,%s,'DELIVERY',%s,1)", (d.get('code',''), fake_hash, d.get('name',''), session.get('branch','HQ')))
            conn.commit(); flash("Delivery Boy Saved Successfully!", "success")
    with conn.cursor() as c: c.execute("SELECT * FROM users WHERE role='DELIVERY' ORDER BY id DESC"); boys = c.fetchall()
    conn.close()
    html = """
<style>.agcs-container { display: flex; gap: 5px; height: 500px; } .agcs-left-list { width: 250px; background: #99CCCC; border: 1px solid #116B7A; overflow-y: auto; padding: 2px;} .agcs-right-form { flex: 1; background: #E2FAFA; border: 1px solid #116B7A; padding: 5px; } .list-header { background: #E2FAFA; font-weight: bold; border-bottom: 1px solid #116B7A; padding: 3px; font-size: 11px; color: #006600; font-style: italic;} .list-item { font-size: 11px; padding: 3px; cursor: pointer; border-bottom: 1px solid #B0D4D4; font-weight: bold;} .list-item:hover { background: #FFFECC; } .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;} .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;} .agcs-label { color: #0066CC; font-weight: bold; font-size: 11px; white-space: nowrap;} .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-family: Tahoma; font-size: 11px; width: 100%; box-sizing: border-box; } .agcs-top-bar { display: flex; gap: 5px; padding: 5px; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: #E2FAFA;} .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 15px; font-family: Tahoma; font-size: 11px; font-weight: bold; cursor: pointer; color: #000; border-radius:3px;} .page-title-green { color: #006600; font-style: italic; font-weight: bold; font-size: 14px; margin: 0 0 5px 0; background:white; padding:5px;}</style>
<div style="background: white; border: 1px solid #116B7A; border-top: 3px solid #116B7A;"><h2 class="page-title-green">DELIVERY BOY MASTER ENTRY</h2><div class="agcs-top-bar"><button type="button" class="agcs-btn-grey" onclick="document.getElementById('masterForm').submit()">SAVE</button><button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button><div style="margin-left: auto; color: #D67A00; font-weight: bold; font-size:14px; padding-right:10px;">Center : {{ session.branch | default('NOHAR') }}</div></div><div class="agcs-container"><div class="agcs-left-list"><div class="list-header" style="color:black; font-style:normal;">CURRENT DELIVERY BOY</div><div style="background: #99CCCC;">{% for b in boys %}<div class="list-item" onclick="loadBoy('{{ b.username }}', '{{ b.full_name }}')">{{ b.full_name | upper }}</div>{% endfor %}</div></div><div class="agcs-right-form"><form method="POST" id="masterForm" style="margin:0;"><div class="list-header" style="text-align:center; background:#DCEBEB; color:black; font-style:normal;">DELIVERY BOY'S DETAILS</div><table class="agcs-form-table" style="width: 80%; margin: 10px auto;"><tr><td class="agcs-label" style="width:20%;">Boy Code</td><td colspan="3"><input type="text" name="code" id="b_code" class="agcs-input" style="width: 30%;" required></td></tr><tr><td class="agcs-label">Full Name</td><td colspan="3"><input type="text" name="name" id="b_name" class="agcs-input" style="width: 80%;" required></td></tr><tr><td class="agcs-label">Address</td><td colspan="3"><input type="text" name="address" class="agcs-input" style="width: 100%; margin-bottom: 2px;"></td></tr><tr><td class="agcs-label">Area</td><td><input type="text" name="area" class="agcs-input" style="width: 90%;"></td><td class="agcs-label" style="text-align:right;">City</td><td><input type="text" class="agcs-input" style="width: 90%;"></td></tr><tr><td class="agcs-label">State</td><td><input type="text" class="agcs-input" style="width: 90%;"></td><td class="agcs-label" style="text-align:right;">PinCode</td><td><input type="text" class="agcs-input" style="width: 90%;"></td></tr><tr><td class="agcs-label">Phone No.</td><td><input type="text" name="phone" class="agcs-input" style="width: 90%;"></td><td class="agcs-label" style="text-align:right;">Mobile No</td><td><input type="text" class="agcs-input" style="width: 90%;"></td></tr></table></form></div></div></div><script>function loadBoy(code, name) { document.getElementById('b_code').value = code; document.getElementById('b_name').value = name;}</script>
"""
    return render_page("Delivery Boy Master", render_template_string(html, boys=boys))

@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE users SET active=0 WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("User Deactivated!", "success"); return redirect('/users')
    if request.method == 'POST':
        d = request.form; b = str(d.get('branch', '')).upper(); cid = safe_int(d.get('customer_id')) if d.get('customer_id') else None
        with conn.cursor() as c:
            c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (b,))
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, customer_id, active) VALUES(%s,%s,%s,%s,%s,%s,1)", (d.get('username',''), hashlib.sha256(d.get('password','').encode()).hexdigest(), d.get('full_name',''), d.get('role',''), b, cid))
            conn.commit(); flash("User Added Successfully!", "success")
    with conn.cursor() as c:
        c.execute("SELECT * FROM users ORDER BY id DESC"); u_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); branches = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    html = """
<style>.agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;} .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;} .agcs-label { color: #003366; font-weight: bold; width: 120px; font-size: 11px;} .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; } .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;} .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;} .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}</style>
<div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;"><h2 class="page-title-green">USER LOGIN SETUP (ADMIN / USER CREATION)</h2><form method="POST"><div class="agcs-top-bar"><button type="submit" class="agcs-btn-grey">SAVE</button><button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button></div><div style="background: #E2FAFA; padding: 2px;"><table class="agcs-form-table" style="width:60%; margin:auto; border:1px solid #116B7A; background:white;"><tr><td colspan="2" style="background:#116B7A; color:white; font-weight:bold; text-align:center;">User Account Details</td></tr><tr><td class="agcs-label" style="padding-top:10px;">Username</td><td style="padding-top:10px;"><input type="text" name="username" class="agcs-input" required></td></tr><tr><td class="agcs-label">Password</td><td><input type="password" name="password" class="agcs-input" required></td></tr><tr><td class="agcs-label">Full Name</td><td><input type="text" name="full_name" class="agcs-input" required></td></tr><tr><td class="agcs-label">Role / Access</td><td><select name="role" class="agcs-input"><option>OPERATOR</option><option>ADMIN</option><option>ACCOUNTANT</option><option>CUSTOMER</option></select></td></tr><tr><td class="agcs-label">Branch / Station</td><td><input type="text" name="branch" list="brlist" class="agcs-input" required><datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist></td></tr><tr><td class="agcs-label" style="padding-bottom:10px;">Link Customer (B2B)</td><td style="padding-bottom:10px;"><select name="customer_id" class="agcs-input"><option value="">-- None --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></td></tr></table></div></form><div style="background: white; border: 1px solid #116B7A; margin-top: 15px;"><div style="height: 250px; overflow-y: auto;"><table class="datatable" style="width: 100%; border: none; margin: 0;"><thead style="position: sticky; top: 0;"><tr><th>Username</th><th>Full Name</th><th>Role</th><th>Branch</th><th>Act</th></tr></thead><tbody>{% for u in u_list %}<tr><td><strong>{{ u.username }}</strong></td><td>{{ u.full_name }}</td><td>{{ u.role }}</td><td>{{ u.branch_name }}</td><td>{% if u.active %}<a href="/users?delete={{ u.id }}" style="color:red; font-weight:bold;">[Del]</a>{% else %}Inactive{% endif %}</td></tr>{% endfor %}</tbody></table></div></div></div>
"""
    return render_page("User Login SetUp", render_template_string(html, u_list=u_list, branches=branches, custs=custs))

@app.route('/location_master', methods=['GET', 'POST'])
@login_required
def location_master():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip().upper()
        scode = request.form.get('state_code', '').strip().upper()
        if name:
            with conn.cursor() as c:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (name,))
                conn.commit(); flash(f"Location {name} Saved!", "success")
    with conn.cursor() as c: c.execute("SELECT id, name FROM stations ORDER BY id DESC LIMIT 100"); stations_list = c.fetchall()
    conn.close()
    html = """<style>.agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px; background: #E2FAFA;} .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;} .agcs-label { color: #003366; font-weight: bold; width: 150px; font-size: 11px;} .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; } .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;} .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;} .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}</style><div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;"><h2 class="page-title-green">GEOGRAPHICAL LOCATION MASTER</h2><form method="POST"><div class="agcs-top-bar"><button type="submit" class="agcs-btn-grey">SAVE</button><button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button></div><div style="background: #E2FAFA; padding: 2px;"><table class="agcs-form-table"><tr><td class="agcs-label">Location / Station Name</td><td><input type="text" name="name" class="agcs-input" style="width: 50%; color:blue; font-weight:bold;" required></td></tr><tr><td class="agcs-label">State Code (Optional)</td><td><input type="text" name="state_code" class="agcs-input" style="width: 20%;"></td></tr><tr><td class="agcs-label">Hub / Direct</td><td><select class="agcs-input" style="width:30%;"><option>HUB</option><option>DIRECT</option></select></td></tr></table></div></form><div style="background: white; border: 1px solid #116B7A; margin-top: 15px;"><div style="height: 250px; overflow-y: auto;"><table class="datatable" style="width: 100%; border: none; margin: 0;"><thead style="position: sticky; top: 0;"><tr><th>ID</th><th>Station Name</th><th>Act</th></tr></thead><tbody>{% for r in s_list %}<tr><td>{{ r.id }}</td><td style="color: blue; font-weight: bold;">{{ r.name }}</td><td style="text-align:center;"><a href="#" style="color:red;">[Edit]</a></td></tr>{% endfor %}</tbody></table></div></div></div>"""
    return render_page("Geographical Location Master", render_template_string(html, s_list=stations_list))

@app.route('/credit_party', methods=['GET', 'POST'])
@login_required
def credit_party():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("INSERT INTO customers(code, name, gstin, phone, address, credit_limit, is_active) VALUES(%s,%s,%s,%s,%s,%s,1)", (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone',''), d.get('address',''), safe_float(d.get('limit'))))
            conn.commit(); flash("Credit Party Saved!", "success")
    with conn.cursor() as c: c.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id DESC LIMIT 50"); custs = c.fetchall()
    conn.close()
    html = """<style>.agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px; background: #E2FAFA;} .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;} .agcs-label { color: #003366; font-weight: bold; width: 120px; font-size: 11px;} .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; } .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;} .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;} .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}</style><div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;"><h2 class="page-title-green">CREDIT PARTY A/C MASTER</h2><form method="POST"><div class="agcs-top-bar"><button type="submit" class="agcs-btn-grey">SAVE</button><button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button></div><div style="background: #E2FAFA; padding: 2px;"><table class="agcs-form-table"><tr><td class="agcs-label">Party Name</td><td colspan="3"><input type="text" name="name" class="agcs-input" style="width: 60%; color:blue; font-weight:bold;" required></td></tr><tr><td class="agcs-label">A/c Code</td><td colspan="3"><input type="text" name="code" class="agcs-input" style="width: 30%;" required></td></tr><tr><td class="agcs-label">Address</td><td colspan="3"><input type="text" name="address" class="agcs-input" style="width: 60%;"></td></tr><tr><td class="agcs-label">Phone</td><td><input type="text" name="phone" class="agcs-input" style="width: 80%;"></td><td class="agcs-label" style="text-align:right;">GSTIN</td><td><input type="text" name="gstin" class="agcs-input" style="width: 80%;"></td></tr><tr><td class="agcs-label">Credit Limit (Rs)</td><td colspan="3"><input type="number" step="0.01" name="limit" class="agcs-input" value="0.00" style="width: 30%;"></td></tr></table></div></form><div style="background: white; border: 1px solid #116B7A; margin-top: 15px;"><div style="height: 250px; overflow-y: auto;"><table class="datatable" style="width: 100%; border: none; margin: 0;"><thead style="position: sticky; top: 0;"><tr><th>Code</th><th>Name</th><th>Phone</th><th>GSTIN</th><th>Limit</th></tr></thead><tbody>{% for r in custs %}<tr><td>{{ r.code }}</td><td style="color: blue; font-weight: bold;">{{ r.name }}</td><td>{{ r.phone }}</td><td>{{ r.gstin }}</td><td>{{ r.credit_limit }}</td></tr>{% endfor %}</tbody></table></div></div></div>"""
    return render_page("Credit Party A/c Master", render_template_string(html, custs=custs))

# ==========================================
# 📦 6. TRANSACTIONS & BOOKING
# ==========================================
@app.route('/api/calc_rate', methods=['POST'])
@login_required
def api_calc_rate():
    d = request.json; cid = safe_int(d.get('cust_id')) if d.get('cust_id') else None; ost = d.get('ostate', ''); dst = d.get('dstate', ''); wt = safe_float(d.get('wt')); fr = safe_float(d.get('fr')); tx = safe_float(d.get('tax'))
    if fr == 0.0:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM rates WHERE customer_id=%s AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (cid, ost, dst, wt)); r = c.fetchone()
        if not r: c.execute("SELECT * FROM rates WHERE customer_id IS NULL AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (ost, dst, wt)); r = c.fetchone()
        c.close(); conn.close()
        if r: fr = safe_float(r['fixed_charge']) + (wt * safe_float(r['per_kg_rate'])); tx = safe_float(r['gst_rate'])
        else: fr = wt * 25.0
    fuel = safe_float(get_setting("fuel_surcharge", "0")); taxable = fr * (1 + (fuel/100)); gst_amt = taxable * (tx/100); total = taxable + gst_amt
    return jsonify({"freight": round(fr,2), "taxable": round(taxable,2), "gst": round(gst_amt,2), "total": round(total,2), "tax_rate": tx})

@app.route('/api/get_awb_info/<awb>', methods=['GET'])
@login_required
def api_get_awb_info(awb):
    conn = get_db()
    with conn.cursor() as c: c.execute("SELECT dest_station, dest_name, weight_kg FROM shipments WHERE awb_no=%s", (awb.upper(),)); s = c.fetchone()
    conn.close()
    if s: return jsonify({"success": True, "dest_station": s['dest_station'], "dest_name": s['dest_name'], "weight": s['weight_kg']})
    return jsonify({"success": False})

@app.route('/booking', methods=['GET', 'POST'])
@login_required
def booking():
    conn = get_db()
    if request.method == 'POST':
        d = request.form; fr = safe_float(d.get('fr')); tax = safe_float(d.get('tax', 18)); wt = safe_float(d.get('wt', 1))
        fuel = safe_float(get_setting("fuel_surcharge", "0")); taxable = fr * (1 + (fuel/100)); gst = taxable * (tax / 100); tot = taxable + gst
        cgst = sgst = igst = 0
        if str(d.get('ostate','')).strip().upper() == str(d.get('dstate','')).strip().upper(): cgst = sgst = gst / 2
        else: igst = gst
        with conn.cursor() as c:
            try:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d.get('dstat','').upper(),))
                cid = session.get('customer_id') if session.get('role') == 'CUSTOMER' else (safe_int(d.get('cust_id')) if d.get('cust_id') else None)
                awb = d.get('awb','').upper()
                c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, origin_phone, origin_address, origin_state_code, dest_name, dest_phone, dest_address, dest_state_code, dest_station, weight_kg, quantity, cod_amount, declared_value, service_type, taxable_amount, tax_rate, cgst, sgst, igst, total_amount, info, status, current_location, is_synced)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s, 0)""",
                          (awb, cid, d.get('date',''), d.get('oname',''), d.get('ophone',''), d.get('oaddr',''), d.get('ostate',''), d.get('dname',''), d.get('dphone',''), d.get('daddr',''), d.get('dstate',''), d.get('dstat','').upper(), wt, safe_int(d.get('pcs', 1)), safe_float(d.get('cod')), safe_float(d.get('dec')), d.get('srv','SURFACE'), taxable, tax, cgst, sgst, igst, tot, d.get('info',''), session.get('branch','HQ')))
                sid = c.lastrowid
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'BOOKED',%s,'Booked at counter')", (sid, session.get('branch','HQ')))
                if cid: c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (cid, d.get('date',''), awb, tot, f"Booking {awb}"))
                conn.commit(); flash(f"AWB {awb} Booked! Total: Rs {tot:.2f}", "success")
            except Exception as e: flash(f"Error: {e}", "error")
    with conn.cursor() as c:
        c.execute("SELECT id, name, phone, state_code FROM customers WHERE is_active=1"); custs = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
        my_cust = None
        if session.get('role') == 'CUSTOMER':
            c.execute("SELECT id, name, phone, state_code, address FROM customers WHERE id=%s", (session.get('customer_id'),))
            my_cust = c.fetchone()
        q_recent = """SELECT s.id, s.awb_no, COALESCE(c.name,'') as customer_name, COALESCE(s.dest_station,'') as dest_station,
CONCAT(COALESCE(s.dest_name,''), ' (', COALESCE(s.dest_state_code,''), ')') as destination,
s.weight_kg, COALESCE(s.cgst+s.sgst+s.igst,0) as gst, s.total_amount, s.status, s.booking_date
FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id"""
        params_recent = []
        if session.get('role') == 'CUSTOMER':
            q_recent += " WHERE s.customer_id = %s"; params_recent.append(session.get('customer_id'))
        elif session.get('role') != 'ADMIN':
            q_recent += " WHERE s.origin_name = %s"; params_recent.append(session.get('branch', 'HQ'))
        q_recent += " ORDER BY s.id DESC LIMIT 50"
        c.execute(q_recent, tuple(params_recent)); recent = c.fetchall()
    conn.close()
    html = """
<style>
.agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px; background: #E2FAFA;}
.agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
.agcs-label { color: #003366; font-weight: bold; width: 100px; font-size: 11px; text-align:right;}
.agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
.agcs-section-header { background-color: #009933; color: white; font-weight: bold; padding: 3px 5px; margin-top: 5px; margin-bottom: 5px; font-size: 11px;}
.agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
.agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;}
.page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
</style>
<div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
<h2 class="page-title-green">COUNTER BOOKING ENTRY</h2>
<form method="POST" id="bkForm" style="margin:0;">
<div class="agcs-top-bar">
<button type="submit" class="agcs-btn-grey">SAVE</button>
<button type="button" class="agcs-btn-grey" onclick="document.getElementById('bkForm').reset()">RESET</button>
<button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
</div>
<table class="agcs-form-table" style="border:1px solid #116B7A; background:white; margin-bottom:10px;">
<tr>
<td class="agcs-label" style="text-align:left;">Booking Date</td><td><input type="date" name="date" id="bdt" required class="agcs-input" style="color:blue; font-weight:bold; width:120px;"></td>
<td class="agcs-label" style="color:red; font-size:12px;">C.Note No.</td><td><input name="awb" required class="agcs-input" style="font-weight:bold; color:red; text-transform:uppercase; width:150px;"></td>
<td class="agcs-label">Customer A/c</td>
<td>
{% if session.get('role') == 'CUSTOMER' %}
<input type="hidden" name="cust_id" id="cid" value="{{ my_cust.id }}" data-state="{{ my_cust.state_code }}">
<input value="{{ my_cust.name }}" readonly class="agcs-input" style="background:#EEE; font-weight:bold; width:200px;">
{% else %}
<select name="cust_id" id="cid" onchange="fetchRate()" class="agcs-input" style="width:200px;"><option value="">-- Cash Booking --</option>{% for c in custs %}<option value="{{ c.id }}" data-state="{{ c.state_code }}">{{ c.name }}</option>{% endfor %}</select>
{% endif %}
</td>
</tr>
</table>
<div style="display:flex; gap:10px;">
<div style="flex:1; border:1px solid #009933; background:white;">
<div class="agcs-section-header" style="color:#D67A00; background:#FFF; border-bottom:1px solid #D67A00;">CONSIGNOR DETAILS</div>
<table class="agcs-form-table">
<tr><td class="agcs-label">Name</td><td><input name="oname" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.name }}{% else %}{{ session.get('branch', 'HQ') }}{% endif %}" class="agcs-input" required></td></tr>
<tr><td class="agcs-label">Phone</td><td><input name="ophone" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.phone }}{% endif %}" class="agcs-input"></td></tr>
<tr><td class="agcs-label">State Code</td><td><input name="ostate" id="ost" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.state_code }}{% else %}RJ{% endif %}" onchange="fetchRate()" class="agcs-input" style="width:60px;"></td></tr>
<tr><td class="agcs-label">Address</td><td><input name="oaddr" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.address }}{% endif %}" class="agcs-input"></td></tr>
</table>
</div>
<div style="flex:1; border:1px solid #009933; background:white;">
<div class="agcs-section-header" style="color:#116B7A; background:#FFF; border-bottom:1px solid #116B7A;">CONSIGNEE DETAILS</div>
<table class="agcs-form-table">
<tr><td class="agcs-label">Name</td><td><input name="dname" class="agcs-input" required></td></tr>
<tr><td class="agcs-label">Phone</td><td><input name="dphone" class="agcs-input" required></td></tr>
<tr><td class="agcs-label">Station</td><td><input name="dstat" list="stations" class="agcs-input" required style="text-transform:uppercase; font-weight:bold;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></td></tr>
<tr><td class="agcs-label">State Code</td><td><input name="dstate" id="dst" onchange="fetchRate()" class="agcs-input" style="width:60px;"></td></tr>
<tr><td class="agcs-label">Address</td><td><input name="daddr" class="agcs-input"></td></tr>
</table>
</div>
</div>
<div style="border:1px solid #009933; background:white; margin-top:10px;">
<div class="agcs-section-header">CHARGE DETAILS</div>
<table class="agcs-form-table">
<tr>
<td class="agcs-label" style="text-align:left; width:50px;">Weight</td><td><input type="number" step="0.01" name="wt" id="wt" value="1.0" required oninput="fetchRate()" class="agcs-input" style="width:60px; font-weight:bold;"></td>
<td class="agcs-label" style="width:50px;">Pieces</td><td><input type="number" name="pcs" value="1" required class="agcs-input" style="width:50px;"></td>
<td class="agcs-label" style="width:50px;">Service</td><td><select name="srv" class="agcs-input" style="width:100px;"><option>SURFACE</option><option>AIR</option></select></td>
<td class="agcs-label" style="width:50px;">Freight</td><td><input type="number" step="0.01" name="fr" id="fr" value="0.0" oninput="manualCalc()" required class="agcs-input" style="width:80px; text-align:right;"></td>
<td class="agcs-label" style="width:40px;">Tax%</td><td><input type="number" name="tax" id="tax" value="18" oninput="manualCalc()" required class="agcs-input" style="width:50px; text-align:right;"></td>
<td class="agcs-label" style="width:50px;">Total(Rs)</td><td><input type="number" step="0.01" name="amt" id="amt" value="0.0" readonly class="agcs-input" style="width:90px; text-align:right; font-weight:bold; color:red;"></td>
</tr>
<tr><td colspan="12"><div id="calc_hint" style="color:#D67A00; font-weight:bold; font-size:10px; text-align:right; padding-right:10px;">Auto-Rate API Loading...</div></td></tr>
</table>
</div>
</form>
<div style="border: 1px solid #116B7A; background: white; margin-top: 15px;">
<div style="background: #116B7A; color: white; font-weight: bold; padding: 5px;">Recent Bookings Register</div>
<div style="height: 180px; overflow-y: auto;">
<table class="datatable" style="width: 100%; border: none; margin: 0;">
<thead style="position: sticky; top: 0;"><tr><th>C.Note No</th><th>Party A/c</th><th>Station</th><th>Weight</th><th>Amount</th><th>Act</th></tr></thead>
<tbody>
{% for r in recent %}<tr><td style="font-weight:bold; color:red;">{{ r.awb_no }}</td><td style="color:blue;">{{ r.customer_name }}</td><td>{{ r.dest_station }}</td><td>{{ r.weight_kg }}</td><td style="font-weight:bold;">{{ r.total_amount }}</td><td><a href="/edit_shipment/{{ r.id }}" style="color:blue; font-weight:bold; text-decoration:none;">[Edit]</a></td></tr>{% endfor %}
</tbody>
</table>
</div>
</div>
</div>
<script>
document.getElementById('bdt').valueAsDate = new Date();
function fetchRate() {
let cid = document.getElementById('cid').value;
if(cid) {
let opt = document.getElementById('cid').options[document.getElementById('cid').selectedIndex];
if(opt){document.getElementById('ost').value = opt.getAttribute('data-state');}
}
let data = { cust_id: cid, ostate: document.getElementById('ost').value, dstate: document.getElementById('dst').value, wt: document.getElementById('wt').value, fr: 0 };
fetch('/api/calc_rate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) }).then(r => r.json()).then(res => { document.getElementById('fr').value = res.freight; document.getElementById('tax').value = res.tax_rate; document.getElementById('amt').value = res.total; document.getElementById('calc_hint').innerText = `Taxable: Rs ${res.taxable} | GST: Rs ${res.gst}`; });
}
function manualCalc() {
let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0; document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); document.getElementById('calc_hint').innerText = "Manual Edit Applied";
}
if(document.getElementById('cid').tagName === 'INPUT') { fetchRate(); }
</script>
"""
    return render_page("Counter Booking", render_template_string(html, custs=custs, stations=stations, recent=recent, my_cust=my_cust))

@app.route('/edit_shipment/<int:sid>', methods=['GET', 'POST'])
@login_required
def edit_shipment(sid):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM shipments WHERE id=%s", (sid,))
        s = c.fetchone()
        if not s: flash("Not found", "error"); return redirect('/shipments')
        if session.get('role') == 'CUSTOMER':
            if s['customer_id'] != session.get('customer_id'):
                flash("Unauthorized", "error"); return redirect('/shipments')
            if s['status'] != 'BOOKED':
                flash("Cannot edit a dispatched shipment.", "error"); return redirect('/shipments')
        if request.method == 'POST':
            d = request.form; fr = safe_float(d.get('fr')); tax = safe_float(d.get('tax', 18)); wt = safe_float(d.get('wt', 1))
            fuel = safe_float(get_setting("fuel_surcharge", "0")); taxable = fr * (1 + (fuel/100)); gst = taxable * (tax / 100); tot = taxable + gst
            cgst = sgst = igst = 0
            if str(d.get('ostate','')).strip().upper() == str(d.get('dstate','')).strip().upper(): cgst = sgst = gst / 2
            else: igst = gst
            with conn.cursor() as c:
                try:
                    c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d.get('dstat','').upper(),))
                    new_status = d.get('status', 'BOOKED') if session.get('role') != 'CUSTOMER' else 'BOOKED'
                    new_loc = d.get('location', '') if session.get('role') != 'CUSTOMER' else s['current_location']
                    c.execute("""UPDATE shipments SET awb_no=%s, booking_date=%s, origin_name=%s, origin_phone=%s, origin_address=%s, origin_state_code=%s, dest_name=%s, dest_phone=%s, dest_address=%s, dest_state_code=%s, dest_station=%s, weight_kg=%s, quantity=%s, cod_amount=%s, declared_value=%s, service_type=%s, taxable_amount=%s, tax_rate=%s, cgst=%s, sgst=%s, igst=%s, total_amount=%s, info=%s, status=%s, current_location=%s WHERE id=%s""", (d.get('awb','').upper(), d.get('date',''), d.get('oname',''), d.get('ophone',''), d.get('oaddr',''), d.get('ostate',''), d.get('dname',''), d.get('dphone',''), d.get('daddr',''), d.get('dstate',''), d.get('dstat','').upper(), wt, safe_int(d.get('pcs', 1)), safe_float(d.get('cod')), safe_float(d.get('dec')), d.get('srv','SURFACE'), taxable, tax, cgst, sgst, igst, tot, d.get('info',''), new_status, new_loc, sid))
                    if s['status'] != new_status or s['current_location'] != new_loc:
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,%s,%s,'Updated via Edit Panel')", (sid, new_status, new_loc))
                    conn.commit(); flash("Updated!", "success")
                except Exception as e: flash(f"Error: {e}", "error")
            return redirect('/booking' if session.get('role') != 'CUSTOMER' else '/shipments')
    with conn.cursor() as c: c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
    conn.close()
    html = """
<style>
.agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;}
.agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
.agcs-label { color: #003366; font-weight: bold; width: 100px; font-size: 11px; text-align:right;}
.agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
.agcs-section-header { background-color: #009933; color: white; font-weight: bold; padding: 3px 5px; margin-top: 5px; margin-bottom: 5px; font-size: 11px;}
.agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
.agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;}
.page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
</style>
<div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
<h2 class="page-title-green">EDIT CONSIGNMENT: {{ s.awb_no }}</h2>
<form method="POST" id="editForm" style="margin:0;">
<div class="agcs-top-bar">
<button type="submit" class="agcs-btn-grey">UPDATE</button>
<button type="button" class="agcs-btn-grey" onclick="window.location.href='{% if session.role == "CUSTOMER" %}/shipments{% else %}/booking{% endif %}'">CANCEL</button>
</div>
<table class="agcs-form-table" style="border:1px solid #116B7A; background:white; margin-bottom:10px;">
<tr>
<td class="agcs-label" style="text-align:left;">Booking Date</td><td><input type="date" name="date" value="{{ s.booking_date }}" required class="agcs-input" style="color:blue; font-weight:bold; width:120px;"></td>
<td class="agcs-label" style="color:red; font-size:12px;">C.Note No.</td><td><input name="awb" value="{{ s.awb_no }}" required class="agcs-input" style="font-weight:bold; color:red; text-transform:uppercase; width:150px;"></td>
{% if session.get('role') != 'CUSTOMER' %}
<td class="agcs-label">Status</td><td><select name="status" class="agcs-input" style="color:red; font-weight:bold; width:150px;"><option {% if s.status == 'BOOKED' %}selected{% endif %}>BOOKED</option><option {% if s.status == 'OUTWARD' %}selected{% endif %}>OUTWARD</option><option {% if s.status == 'INWARD' %}selected{% endif %}>INWARD</option><option {% if s.status == 'ON_DRS' %}selected{% endif %}>ON_DRS</option><option {% if s.status == 'DELIVERED' %}selected{% endif %}>DELIVERED</option></select></td>
<td class="agcs-label">Location</td><td><input name="location" value="{{ s.current_location or '' }}" class="agcs-input" style="width:150px;"></td>
{% endif %}
</tr>
</table>
<div style="display:flex; gap:10px;">
<div style="flex:1; border:1px solid #009933; background:white;">
<div class="agcs-section-header" style="color:#D67A00; background:#FFF; border-bottom:1px solid #D67A00;">CONSIGNOR DETAILS</div>
<table class="agcs-form-table">
<tr><td class="agcs-label">Name</td><td><input name="oname" value="{{ s.origin_name or '' }}" class="agcs-input" required></td></tr>
<tr><td class="agcs-label">Phone</td><td><input name="ophone" value="{{ s.origin_phone or '' }}" class="agcs-input"></td></tr>
<tr><td class="agcs-label">State Code</td><td><input name="ostate" id="ost" value="{{ s.origin_state_code or '' }}" onchange="manualCalc()" class="agcs-input" style="width:60px;"></td></tr>
<tr><td class="agcs-label">Address</td><td><input name="oaddr" value="{{ s.origin_address or '' }}" class="agcs-input"></td></tr>
</table>
</div>
<div style="flex:1; border:1px solid #009933; background:white;">
<div class="agcs-section-header" style="color:#116B7A; background:#FFF; border-bottom:1px solid #116B7A;">CONSIGNEE DETAILS</div>
<table class="agcs-form-table">
<tr><td class="agcs-label">Name</td><td><input name="dname" value="{{ s.dest_name or '' }}" class="agcs-input" required></td></tr>
<tr><td class="agcs-label">Phone</td><td><input name="dphone" value="{{ s.dest_phone or '' }}" class="agcs-input" required></td></tr>
<tr><td class="agcs-label">Station</td><td><input name="dstat" list="stations" value="{{ s.dest_station or '' }}" class="agcs-input" required style="text-transform:uppercase; font-weight:bold;"><datalist id="stations">{% for st in stations %}<option value="{{ st.name }}">{% endfor %}</datalist></td></tr>
<tr><td class="agcs-label">State Code</td><td><input name="dstate" id="dst" value="{{ s.dest_state_code or '' }}" onchange="manualCalc()" class="agcs-input" style="width:60px;"></td></tr>
<tr><td class="agcs-label">Address</td><td><input name="daddr" value="{{ s.dest_address or '' }}" class="agcs-input"></td></tr>
</table>
</div>
</div>
<div style="border:1px solid #009933; background:white; margin-top:10px;">
<div class="agcs-section-header">CHARGE DETAILS</div>
<table class="agcs-form-table">
<tr>
<td class="agcs-label" style="text-align:left; width:50px;">Weight</td><td><input type="number" step="0.01" name="wt" id="wt" value="{{ s.weight_kg or 1 }}" required oninput="manualCalc()" class="agcs-input" style="width:60px; font-weight:bold;"></td>
<td class="agcs-label" style="width:50px;">Pieces</td><td><input type="number" name="pcs" value="{{ s.quantity or 1 }}" required class="agcs-input" style="width:50px;"></td>
<td class="agcs-label" style="width:50px;">Service</td><td><select name="srv" class="agcs-input" style="width:100px;"><option {% if s.service_type == 'SURFACE' %}selected{% endif %}>SURFACE</option><option {% if s.service_type == 'AIR' %}selected{% endif %}>AIR</option></select></td>
<td class="agcs-label" style="width:50px;">Freight</td><td><input type="number" step="0.01" name="fr" id="fr" value="{{ s.taxable_amount or 0 }}" oninput="manualCalc()" required class="agcs-input" style="width:80px; text-align:right;"></td>
<td class="agcs-label" style="width:40px;">Tax%</td><td><input type="number" name="tax" id="tax" value="{{ s.tax_rate or 18 }}" oninput="manualCalc()" required class="agcs-input" style="width:50px; text-align:right;"></td>
<td class="agcs-label" style="width:50px;">Total(Rs)</td><td><input type="number" step="0.01" name="amt" id="amt" value="{{ s.total_amount or 0 }}" readonly class="agcs-input" style="width:90px; text-align:right; font-weight:bold; color:red;"></td>
</tr>
<tr><td colspan="12"><div id="calc_hint" style="color:#D67A00; font-weight:bold; font-size:10px; text-align:right; padding-right:10px;">Manual Edit Mode</div></td></tr>
</table>
</div>
</form>
</div>
<script>function manualCalc() { let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0; document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); }</script>
"""
    return render_page(f"Edit C.Note: {s['awb_no']}", render_template_string(html, s=s, stations=stations, session=session))

@app.route('/shipments', methods=['GET', 'POST'])
@login_required
def shipments():
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("SELECT customer_id, status FROM shipments WHERE id=%s", (request.args.get('delete'),))
            ship = c.fetchone()
            if ship:
                if session.get('role') == 'CUSTOMER' and (ship['customer_id'] != session.get('customer_id') or ship['status'] != 'BOOKED'):
                    flash("Cannot delete this shipment.", "error")
                else:
                    c.execute("DELETE FROM scan_events WHERE shipment_id=%s", (request.args.get('delete'),))
                    c.execute("DELETE FROM shipments WHERE id=%s", (request.args.get('delete'),))
                    conn.commit(); flash("Shipment Deleted!", "success")
        return redirect('/shipments')
    with conn.cursor() as c:
        q = """SELECT s.id, s.awb_no, s.booking_date, s.dest_name, s.dest_station,
s.weight_kg, s.status, s.info, s.total_amount, s.dest_phone, c.phone as cphone
FROM shipments s LEFT JOIN customers c ON s.customer_id = c.id WHERE 1=1"""
        params = []
        if session.get('role') == 'CUSTOMER':
            q += " AND s.customer_id=%s"; params.append(session.get('customer_id'))
        elif session.get('role') != 'ADMIN':
            q += " AND s.origin_name=%s"; params.append(session.get('branch', 'HQ'))
        q += " ORDER BY s.id DESC LIMIT 500"
        c.execute(q, tuple(params)); rows = c.fetchall()
    conn.close()
    html = """
<style>
.agcs-grid { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; border: 1px solid #116B7A; background:white;}
.agcs-grid th { background: linear-gradient(to bottom, #116B7A, #0D505B); color: #FFF; padding: 5px; border: 1px solid #000; text-align:left;}
.agcs-grid td { padding: 4px 6px; border: 1px solid #CCC; color: #000;}
.agcs-grid tr:nth-child(even) { background: #F4FAFA; }
.agcs-grid tr:hover { background: #FFFECC; }
</style>
<div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
<h2 style="color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;">{% if session.role == 'CUSTOMER' %}MY SHIPMENTS{% else %}DELIVERY STATUS REGISTER{% endif %}</h2>
<div style="background: white; border: 1px solid #116B7A; margin-top: 5px;">
<div style="height: 450px; overflow-y: auto;">
<table class="agcs-grid">
<thead style="position: sticky; top: 0;">
<tr><th>ID</th><th>C.Note</th><th>Date</th><th>Dest</th><th>Station</th><th>Wt</th><th>Status</th><th>Total</th><th>Options</th></tr>
</thead>
<tbody>
{% for r in rows %}<tr>
<td>{{ r.id }}</td><td style="font-weight:bold; color:red;">{{ r.awb_no }}</td><td>{{ r.booking_date }}</td><td>{{ str(r.dest_name or '') }}</td><td>{{ str(r.dest_station or '') }}</td><td>{{ r.weight_kg }}</td>
<td style="font-weight:bold;">{{ r.status }}</td><td style="font-weight:bold;">{{ r.total_amount or 0 }}</td>
<td>
{% if session.get('role') != 'CUSTOMER' or r.status == 'BOOKED' %}
<a href="/edit_shipment/{{ r.id }}" style="color:blue; font-weight:bold; text-decoration:none;">[Edit]</a>
{% endif %}
<a href="/print/label/{{ r.awb_no }}" target="_blank" style="color:green; font-weight:bold; text-decoration:none;">[Lbl]</a>
<a href="/print/receipt/{{ r.awb_no }}" target="_blank" style="color:green; font-weight:bold; text-decoration:none;">[Rec]</a>
{% if session.get('role') != 'CUSTOMER' or r.status == 'BOOKED' %}
<a href="/shipments?delete={{ r.id }}" style="color:red; font-weight:bold; text-decoration:none;" onclick="return confirm('Delete?');">[Del]</a>
{% endif %}
</td>
</tr>{% endfor %}
</tbody>
</table>
</div>
</div>
</div>
"""
    return render_page("Transactions Data", render_template_string(html, rows=rows, str=str, session=session))

@app.route('/my_ledger')
@login_required
def my_ledger():
    if session.get('role') != 'CUSTOMER': return redirect('/')
    conn = get_db(); cid = session.get('customer_id')
    with conn.cursor() as c:
        c.execute("SELECT * FROM ledger WHERE customer_id=%s ORDER BY entry_date DESC", (cid,))
        l_data = c.fetchall()
        c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (cid,))
        r = c.fetchone(); c_bal = safe_float(r['b']) if r else 0.0
    conn.close()
    html = """
<style>
.agcs-grid { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; border: 1px solid #116B7A; background:white;}
.agcs-grid th { background: linear-gradient(to bottom, #116B7A, #0D505B); color: #FFF; padding: 5px; border: 1px solid #000; text-align:left;}
.agcs-grid td { padding: 4px 6px; border: 1px solid #CCC; color: #000;}
.agcs-grid tr:nth-child(even) { background: #F4FAFA; }
.agcs-grid tr:hover { background: #FFFECC; }
</style>
<div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
<h2 style="color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;">MY ACCOUNT LEDGER <a href="/print/statement/{{ session.get('customer_id') }}" target="_blank" style="float:right; color:blue; font-size:11px; font-style:normal;">[Print PDF]</a></h2>
<div style="background:#FFF; padding:5px; border:1px solid #CCC; margin-bottom:10px; font-weight:bold; color:red; text-align:right;">Outstanding Balance: Rs {{ c_bal }}</div>
<div style="background: white; border: 1px solid #116B7A; height: 400px; overflow-y: auto;">
<table class="agcs-grid">
<thead style="position: sticky; top: 0;"><tr><th>Date</th><th>Voucher</th><th>Ref</th><th>Debit (Rs)</th><th>Credit (Rs)</th><th>Narration</th></tr></thead>
<tbody>{% for l in l_data %}<tr><td>{{ l.entry_date }}</td><td>{{ l.voucher_type }}</td><td>{{ l.reference }}</td><td style="color:red; font-weight:bold;">{{ l.debit }}</td><td style="color:green; font-weight:bold;">{{ l.credit }}</td><td>{{ l.narration }}</td></tr>{% endfor %}</tbody>
</table>
</div>
</div>
"""
    return render_page("My Ledger", render_template_string(html, l_data=l_data, c_bal=c_bal, session=session))

# ==========================================
#  8. OUTWARD HUB & EXCEL IMPORT
# ==========================================
@app.route('/import_csv', methods=['GET', 'POST'])
@login_required
def import_csv():
    if session.get('role') != 'ADMIN': return redirect('/')
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'): flash("Invalid CSV file", "error"); return redirect('/import_csv')
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None); reader = csv.DictReader(stream); headers = {k.strip().lower(): k for k in reader.fieldnames if k}
        conn = get_db(); added = 0
        with conn.cursor() as c:
            for row in reader:
                awb = row.get(headers.get("awb", "AWB")) or row.get("AWB")
                if not awb: continue
                awb = str(awb).strip().upper(); c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                if c.fetchone(): continue
                dest = row.get(headers.get("dest", "Dest")) or row.get("Dest Station", "UNKNOWN"); wt = row.get(headers.get("weight", "Weight")) or "1"; tot = row.get(headers.get("amount", "Amount")) or "0"; d = datetime.now().strftime("%Y-%m-%d")
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest.upper(),))
                c.execute("INSERT INTO shipments(awb_no, dest_name, dest_station, weight_kg, total_amount, booking_date, status, current_location, service_type, origin_name) VALUES(%s, %s, %s, %s, %s, %s, 'BOOKED', 'Origin', 'SURFACE', %s)", (awb, dest, dest.upper(), safe_float(wt), safe_float(tot), d, session.get('branch','HQ')))
                added += 1
            conn.commit()
        conn.close(); flash(f"Import Complete! {added} Booked.", "success")
    html = """<div class="card"><h3>Bulk CSV Import</h3><form method="POST" enctype="multipart/form-data"><input type="file" name="file" accept=".csv" required style="margin-bottom:10px;"><button type="submit" class="btn btn-blue">Start Import</button></form></div>"""
    return render_page("Excel Import", render_template_string(html))

@app.route('/print/invoice/<int:inv_id>')
@login_required
def print_invoice_pdf(inv_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT i.*, c.name as cname, c.gstin as cgstin, c.address as caddr, c.state_code as cstate FROM invoices i JOIN customers c ON i.customer_id=c.id WHERE i.id=%s", (inv_id,)); inv = c.fetchone()
    c.execute("SELECT il.*, s.awb_no FROM invoice_lines il LEFT JOIN shipments s ON il.shipment_id=s.id WHERE il.invoice_id=%s", (inv_id,)); lines = c.fetchall()
    c.close(); conn.close()
    if not inv: return "Invoice Not Found"

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFillColor(HexColor("#004B87")); cv.rect(0, 800, 600, 45, fill=1, stroke=0)
    cv.setFillColor(HexColor("#FFFFFF")); cv.setFont("Helvetica-Bold", 16); cv.drawCentredString(300, 815, str(get_setting('company_name', 'AGC')))
    cv.setFont("Helvetica", 9); cv.drawCentredString(300, 802, f"{get_setting('company_address', '')} | GSTIN: {get_setting('company_gstin', '')}")
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 14); cv.drawCentredString(300, 770, "TAX INVOICE")
    cv.setFont("Helvetica", 10); cv.drawString(40, 745, f"Invoice No: {inv['invoice_no']}"); cv.drawRightString(560, 745, f"Date: {inv['invoice_date']}")
    cv.drawString(40, 725, f"Bill To: {inv['cname']}"); cv.drawString(40, 710, f"Address: {inv['caddr']}")
    cv.drawString(40, 695, f"Customer GSTIN: {inv['cgstin']} | State: {inv['cstate']}")
    y = 660; cv.setFillColor(HexColor("#E1E6EE")); cv.rect(40, y, 520, 20, fill=1, stroke=0)
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 9)
    cv.drawString(45, y+6, "AWB No"); cv.drawString(120, y+6, "Description"); cv.drawString(280, y+6, "Taxable"); cv.drawString(350, y+6, "CGST"); cv.drawString(410, y+6, "SGST"); cv.drawString(470, y+6, "IGST"); cv.drawString(520, y+6, "Total")
    y -= 20; cv.setFont("Helvetica", 9)
    for l in lines:
        cv.drawString(45, y, str(l['awb_no'])); cv.drawString(120, y, str(l['description'])[:25])
        cv.drawString(280, y, f"{l['taxable_amount']}"); cv.drawString(350, y, f"{l['cgst']}"); cv.drawString(410, y, f"{l['sgst']}"); cv.drawString(470, y, f"{l['igst']}")
        cv.setFont("Helvetica-Bold"); cv.drawString(520, y, f"{l['total']}"); cv.setFont("Helvetica")
        y -= 15
        if y < 100: cv.showPage(); y = 800
    cv.line(40, y-10, 560, y-10); y -= 30
    cv.setFont("Helvetica-Bold", 11)
    cv.drawString(300, y, f"Total Taxable: Rs {inv['taxable_amount']}")
    cv.drawString(300, y-20, f"CGST: Rs {inv['cgst']} | SGST: Rs {inv['sgst']} | IGST: Rs {inv['igst']}")
    cv.setFillColor(HexColor("#D97706")); cv.setFont("Helvetica-Bold", 14)
    cv.drawString(300, y-45, f"Grand Total: Rs {inv['total']}")
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica", 9)
    cv.drawString(40, 100, f"Bank Details: {get_setting('bank_details', '')}")
    cv.drawString(40, 80, str(get_setting('terms_note', '')))
    cv.drawRightString(560, 100, f"For {get_setting('company_name', 'AGC')}"); cv.drawRightString(560, 80, "Authorised Signatory")
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Invoice_{inv['invoice_no'].replace('/', '_')}.pdf", mimetype='application/pdf')

# ==========================================
# 📊 12. DYNAMIC REPORTS ENGINE
# ==========================================
@app.route('/module/<category>/<action>', methods=['GET', 'POST'])
@login_required
def dynamic_module(category, action):
    title_category = category.replace('_', ' ').upper()
    title_action = action.replace('_', ' ').upper()
    page_title = f"{title_action} [{title_category}]"
    data_found = False; table_headers = []; table_rows = []
    
    conn = get_db()
    with conn.cursor() as c:
        # Pura q_map 'with' block ke andar indented (andar) hona chahiye
        q_map = {
            'cash_billing_register': ("SELECT awb_no, booking_date, dest_name, weight_kg, total_amount FROM shipments WHERE customer_id IS NULL LIMIT 100", ["AWB", "Date", "Dest", "Weight", "Total Amount"]),
            'credit_billing': ("SELECT s.awb_no, s.booking_date, c.name, s.total_amount FROM shipments s JOIN customers c ON s.customer_id=c.id WHERE s.customer_id IS NOT NULL LIMIT 100", ["AWB", "Date", "Customer", "Amount"]),
            'transhipment_charges': ("SELECT awb_no, dest_station, weight_kg, total_amount FROM shipments WHERE status='OUTWARD' LIMIT 100", ["AWB", "Dest Station", "Weight", "Amount"]),
            'inward_outward_pending': ("SELECT awb_no, booking_date, status, current_location FROM shipments WHERE status IN ('BOOKED', 'OUTWARD', 'INWARD') LIMIT 100", ["AWB", "Date", "Status", "Location"]),
            'inward_outward_wgt': ("SELECT awb_no, weight_kg FROM shipments WHERE weight_kg > 0 LIMIT 100", ["AWB", "Weight"]),
            'invoice_data': ("SELECT invoice_no, invoice_date, total, status FROM invoices ORDER BY id DESC LIMIT 100", ["Invoice No", "Date", "Total", "Status"]),
            'bill_pending': ("SELECT invoice_no, invoice_date, total, status FROM invoices WHERE status='UNPAID'", ["Invoice No", "Date", "Total Amount", "Status"]),
            'franchisee_invoice_audit': ("SELECT origin_name, COUNT(*) as docs, SUM(total_amount) as total FROM shipments GROUP BY origin_name", ["Branch", "Docs", "Total"]),
            'drs_status': ("SELECT drs_no, drs_date, rider_name, status FROM drs", ["DRS No", "Date", "Delivery Boy", "Status"]),
            'drs_summary': ("SELECT drs_no, rider_name, status FROM drs", ["DRS No", "Rider", "Status"]),
            'inward_history': ("SELECT entry_date, awb_no, origin_station, in_station FROM inward_register ORDER BY id DESC LIMIT 100", ["Date", "AWB", "Origin", "In-Station"]),
            'outward_history': ("SELECT entry_date, awb_no, out_station, destination FROM outward_register ORDER BY id DESC LIMIT 100", ["Date", "AWB", "Out-Station", "Dest"]),
            'cargo_inward': ("SELECT entry_date, awb_no, origin_station, in_station, weight FROM inward_register LIMIT 100", ["Date", "AWB", "Origin", "In-Station", "Weight"]),
            'outward_register': ("SELECT entry_date, awb_no, out_station, destination, weight FROM outward_register LIMIT 100", ["Date", "AWB", "Out-Station", "Dest", "Weight"]),
            'manifest_register': ("SELECT manifest_no, manifest_type, from_location, to_location, status, created_at FROM manifests LIMIT 100", ["Manifest No", "Type", "Origin", "Destination", "Status", "Date"]),
            'repeat_cnote': ("SELECT awb_no, COUNT(*) as cnt FROM shipments GROUP BY awb_no HAVING cnt > 1", ["AWB No", "Duplicate Count"]),
            'daily_collection': ("SELECT payment_date, mode, SUM(amount) as total_collected FROM payments GROUP BY payment_date, mode", ["Date", "Payment Mode", "Total Collected"]),
            'daily_req': ("SELECT booking_date, COUNT(*) as bookings, SUM(total_amount) as revenue FROM shipments GROUP BY booking_date ORDER BY booking_date DESC LIMIT 30", ["Date", "Bookings", "Revenue"]),
            'counter_booking': ("SELECT awb_no, booking_date, dest_name, total_amount FROM shipments LIMIT 100", ["AWB", "Date", "Dest", "Amount"]),
            'shipper_issue': ("SELECT awb_no, booking_date, origin_name, status FROM shipments WHERE status='STATIONERY' LIMIT 100", ["AWB", "Issue Date", "Issued To", "Status"]),
            'shipper_stock': ("SELECT origin_name, COUNT(*) as stock FROM shipments WHERE status='STATIONERY' GROUP BY origin_name", ["Branch/Shipper", "Unused Stock"]),
            'shipper_inward': ("SELECT entry_date, awb_no, origin_station FROM inward_register LIMIT 100", ["Date", "AWB", "Origin"]),
            'outward_transhipment': ("SELECT entry_date, awb_no, destination, weight FROM outward_register LIMIT 100", ["Date", "AWB", "Dest", "Weight"]),
            'outward_local': ("SELECT entry_date, awb_no, destination, weight FROM outward_register WHERE network='LOCAL' LIMIT 100", ["Date", "AWB", "Dest", "Weight"]),
            'manifest': ("SELECT manifest_no, created_at, from_location, to_location FROM manifests LIMIT 100", ["Manifest No", "Date", "From", "To"]),
            'packing_slip': ("SELECT awb_no, dest_station, weight_kg FROM shipments WHERE status='OUTWARD' LIMIT 100", ["AWB", "Dest", "Weight"]),
            'drs_register': ("SELECT drs_no, drs_date, rider_name FROM drs LIMIT 100", ["DRS No", "Date", "Rider"]),
            'pod_register': ("SELECT s.awb_no, s.dest_name, se.remarks, se.created_at FROM scan_events se JOIN shipments s ON se.shipment_id=s.id WHERE se.scan_type='DELIVERED' LIMIT 100", ["AWB", "Dest Name", "Receiver", "Date"]),
            'pod_entry': ("SELECT s.awb_no, s.dest_name FROM shipments s WHERE s.status='ON_DRS' LIMIT 100", ["AWB", "Dest Name"]),
            'bulk_pod_entry': ("SELECT s.awb_no, s.dest_name FROM shipments s WHERE s.status='ON_DRS' LIMIT 100", ["AWB", "Dest Name"]),
            'cnote_return': ("SELECT awb_no, booking_date, dest_name FROM shipments WHERE status='RETURNED' LIMIT 100", ["AWB", "Date", "Dest"]),
            'account_bill': ("SELECT invoice_no, invoice_date, total FROM invoices LIMIT 100", ["Invoice", "Date", "Total"]),
            'quotation': ("SELECT id, awb_no, total_amount FROM shipments LIMIT 100", ["ID", "AWB", "Amount"]),
            'local_packet_inward': ("SELECT entry_date, awb_no, in_station FROM inward_register LIMIT 100", ["Date", "AWB", "Station"]),
            'inward_mfest': ("SELECT inward_no, MIN(entry_date) as d, COUNT(*) as c FROM inward_register WHERE finalized=1 GROUP BY inward_no", ["Inward No", "Date", "Docs"]),
            'cash_book': ("SELECT payment_date, mode, SUM(amount) as total FROM payments WHERE mode='CASH' GROUP BY payment_date, mode", ["Date", "Mode", "Total"]),
            'bank_book': ("SELECT payment_date, mode, SUM(amount) as total FROM payments WHERE mode='BANK' GROUP BY payment_date, mode", ["Date", "Mode", "Total"]),
            'journal_voucher': ("SELECT expense_date, category, amount FROM expenses LIMIT 100", ["Date", "Category", "Amount"]),
            'service_tax_ledger': ("SELECT invoice_date, taxable_amount, cgst, sgst, igst FROM invoices LIMIT 100", ["Date", "Taxable", "CGST", "SGST", "IGST"]),
            'fuel_surcharge': ("SELECT booking_date, SUM(total_amount) as total FROM shipments GROUP BY booking_date ORDER BY booking_date DESC LIMIT 30", ["Date", "Total"]),
            'pending_outward': ("SELECT awb_no, booking_date, status FROM shipments WHERE status='BOOKED' LIMIT 100", ["AWB", "Date", "Status"]),
            'franchisee_summary': ("SELECT origin_name, COUNT(*) as docs, SUM(total_amount) as rev FROM shipments GROUP BY origin_name", ["Branch", "Docs", "Revenue"]),
            'drs_pending': ("SELECT awb_no FROM shipments WHERE status='ON_DRS' LIMIT 100", ["AWB"]),
            'pod_pending': ("SELECT awb_no FROM shipments WHERE status IN ('INWARD', 'OUTWARD') LIMIT 100", ["AWB"]),
            'duplicate_cnote': ("SELECT awb_no, COUNT(*) as cnt FROM shipments GROUP BY awb_no HAVING cnt > 1", ["AWB No", "Duplicate Count"]),
            'charts': ("SELECT booking_date, COUNT(*) as c FROM shipments GROUP BY booking_date ORDER BY booking_date DESC LIMIT 30", ["Date", "Count"]),
            'circular_issue': ("SELECT id, awb_no, info FROM shipments WHERE info LIKE '%circular%' LIMIT 100", ["ID", "AWB", "Info"]),
            'account_code_updator': ("SELECT id, code, name FROM customers LIMIT 100", ["ID", "Code", "Name"]),
            'bulk_print': ("SELECT awb_no FROM shipments ORDER BY id DESC LIMIT 100", ["AWB"]),
            'mailbox': ("SELECT id, awb_no, info FROM shipments LIMIT 100", ["ID", "AWB", "Info"]),
            'merging': ("SELECT id, name FROM customers LIMIT 100", ["ID", "Name"]),
            'data_manager': ("SELECT 'Shipments' as tbl, COUNT(*) as cnt FROM shipments UNION SELECT 'Customers', COUNT(*) FROM customers UNION SELECT 'Invoices', COUNT(*) FROM invoices", ["Table", "Count"])
        }

        if action in q_map:
            c.execute(q_map[action][0])
            rows = c.fetchall()
            if rows:
                data_found = True
                table_headers = q_map[action][1]
                table_rows = [[str(val) for val in r.values()] for r in rows]
        else:
            table_headers = ["Module Information", "System Status", "Action Required"]
            table_rows = [[f"'{title_action}' module linked.", "Pending Mapping", f"Add '{action}' in web_erp.py q_map"]]
            data_found = True
    conn.close()
    html = """
<style>
.agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px; background: #E2FAFA;}
.agcs-label { color: #003366; font-weight: bold; width: 150px; font-size: 11px;}
.agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
.agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
.agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 3px 15px; font-weight: bold; cursor: pointer; color: #000; font-size:11px; border-radius:3px; text-transform:uppercase;}
.page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 14px; margin: 0 0 5px 0; background:white; padding:5px; text-transform:uppercase;}
.agcs-grid { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; border: 1px solid #116B7A; background:white;}
.agcs-grid th { background: linear-gradient(to bottom, #116B7A, #0D505B); color: #FFF; padding: 5px; border: 1px solid #000; text-align:left;}
.agcs-grid td { padding: 4px 6px; border: 1px solid #CCC; color: #000;}
</style>
<div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
<h2 class="page-title-green">{{ title }}</h2>
<div class="agcs-top-bar"><button type="button" class="agcs-btn-grey" onclick="window.print()">PRINT REPORT</button><button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button><div style="margin-left: auto; color: #D67A00; font-weight: bold; font-size:12px; padding-right:10px;">Center : {{ session.branch | default('NOHAR') }}</div></div>
<div style="background: #E2FAFA; padding: 5px; border: 1px solid #CCC; margin-bottom: 10px;">
<form method="GET" style="margin:0; display:flex; gap:10px; align-items:center;">
<span class="agcs-label" style="width:auto;">From Date:</span><input type="date" name="from_date" class="agcs-input" style="width:120px;" value="{{ current_date }}">
<span class="agcs-label" style="width:auto;">To Date:</span><input type="date" name="to_date" class="agcs-input" style="width:120px;" value="{{ current_date }}">
<button type="submit" class="agcs-btn-grey" style="padding:2px 10px;">SHOW</button>
</form>
</div>
<div style="background: white; border: 1px solid #116B7A; height: 380px; overflow-y: auto;">
{% if has_data %}
<table class="agcs-grid"><thead style="position: sticky; top: 0;"><tr>{% for h in headers %}<th>{{ h }}</th>{% endfor %}</tr></thead><tbody>{% for row in rows %}<tr>{% for cell in row %}<td>{{ cell }}</td>{% endfor %}</tr>{% endfor %}</tbody></table>
{% else %}
<div style="padding:20px; text-align:center; color:red; font-weight:bold; font-size:14px;">No Data Found For Selected Criteria.</div>
{% endif %}
</div>
</div>
"""
    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_page(page_title, render_template_string(html, title=page_title, has_data=data_found, headers=table_headers, rows=table_rows, current_date=current_date, session=session))

# ==========================================
# 🔄 15. UNIVERSAL TWO-WAY SYNC API
# ==========================================
@app.route('/api/sync/download', methods=['GET', 'POST'])
def sync_download():
    """
    Desktop App ko poora latest data (all tables & all new columns) 
    JSON format me securely bhejne ke liye.
    """
    conn = get_db()
    response_data = {}
    
    # Ye saari tables Cloud se Local aayengi
    tables_to_sync = [
        'users', 'branches', 'customers', 'rates', 'stations', 'expenses', 
        'ledger', 'payments', 'invoices', 'invoice_lines', 'shipments', 
        'scan_events', 'outward_register', 'inward_register', 'delivery_register', 
        'manifests', 'manifest_items', 'drs', 'drs_items', 'master_bags', 'master_bag_items'
    ]
    
    try:
        with conn.cursor() as c:
            for tbl in tables_to_sync:
                try:
                    c.execute(f"SELECT * FROM {tbl}")
                    rows = c.fetchall()
                    # Datetime objects ko JSON me convert karne ke liye string banate hain
                    clean_rows = []
                    for row in rows:
                        clean_row = {}
                        for key, value in row.items():
                            import datetime
                            if isinstance(value, datetime.date) or isinstance(value, datetime.datetime):
                                clean_row[key] = str(value)
                            else:
                                clean_row[key] = value
                        clean_rows.append(clean_row)
                    response_data[tbl] = clean_rows
                except Exception as e:
                    logging.error(f"Sync error on table {tbl}: {e}")
                    response_data[tbl] = []
                    
        return jsonify({"success": True, "data": response_data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        conn.close()

# ==========================================
#  DO NOT TOUCH - FLASK RUN
# ==========================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)
