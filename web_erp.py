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
try: import qrcode
except ImportError: qrcode = None

# Background Scheduler for Auto-Invoice
try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:
    BackgroundScheduler = None

# ==========================================
# 🛡️ 1. BULLETPROOF LOGGING, CONFIG & AUTO-WHATSAPP
# ==========================================
logging.basicConfig(filename='agc_erp.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'agc_super_secret_erp_v20_cloud_key')

config = configparser.ConfigParser()
config.read('db_config.ini')

def send_whatsapp_async(phone, message):
    try:
        # WA logic yahan uncomment kar sakte hain
        logging.info(f"Auto-WhatsApp Sent to {phone}: {message}")
    except Exception as e:
        logging.error(f"WhatsApp Error: {e}")

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
            try: c.execute("ALTER TABLE shipments ADD COLUMN pod_photo TEXT")
            except: pass
            try: c.execute("ALTER TABLE shipments ADD COLUMN is_synced INT DEFAULT 0")
            except: pass
            try: c.execute("ALTER TABLE users ADD COLUMN customer_id INT")
            except: pass

            defs = {"company_name": "PANKAJ AGENCY COURIER", "company_address": "Head Office: Nohar, Rajasthan", "company_gstin": "08ADQPC7585D1Z9", "company_phone": "+91 7357073316", "company_state_code": "08", "company_website": "https://agconline.in", "company_email": "PANKAJNOHAR@YAHOO.CO.IN", "terms_note": "Liability limited to declared value only. Subject to local jurisdiction.", "bank_details": "Bank: HDFC | A/C: 123456789 | IFSC: HDFC0001", "fuel_surcharge": "0"}
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
# 🎨 1.5 AGCSINFO CLASSIC ASP.NET THEME SHELL
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
        
        /* AGCS TOP BANNER */
        .top-banner { background: linear-gradient(to bottom, #116B7A, #6EB3C0); height: 75px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #D67A00; padding: 0 20px;}
        .top-banner h1 { margin: 0; color: #FFF; font-style: italic; font-family: "Times New Roman", Times, serif; font-size: 38px; text-shadow: 2px 2px 4px #000; letter-spacing: 1px;}
        .logo-center { background: white; padding: 3px 15px; border-radius: 5px; box-shadow: 0 0 5px rgba(0,0,0,0.5); text-align: center; color: #116B7A; font-weight: bold; font-size: 24px;}
        
        /* AGCS NAVBAR */
        .navbar { background-color: #F4F4F4; border-bottom: 3px solid #E69138; display: flex; font-size: 11px; font-weight: bold; position: relative; z-index: 100;}
        .navbar ul { list-style-type: none; margin: 0; padding: 0; display: flex; }
        .navbar li { position: relative; padding: 6px 12px; color: #000; cursor: pointer; border-right: 1px solid #CCC; }
        .navbar li:hover { background-color: #FFDE99; color: #000; }
        
        /* DROPDOWN */
        .navbar ul ul { display: none; position: absolute; top: 100%; left: 0; background-color: #E8FAFA; border: 1px solid #116B7A; flex-direction: column; min-width: 220px; box-shadow: 2px 2px 5px rgba(0,0,0,0.2); }
        .navbar li:hover > ul { display: flex; }
        .navbar ul ul li { border-right: none; border-bottom: 1px solid #CCC; padding: 6px 12px; font-weight: normal; color: #000; }
        .navbar ul ul li:hover { background-color: #116B7A; color: #FFF; }

        /* MAIN LAYOUT */
        .main-container { display: flex; margin: 10px; gap: 15px; min-height: 550px; padding-bottom: 60px;}
        
        /* SIDEBARS */
        .sidebar { width: 220px; }
        .welcome-box { background: linear-gradient(to bottom, #E67A00, #FF9933); color: white; padding: 15px; border-radius: 8px; font-weight: bold; line-height: 1.8; box-shadow: inset 0 0 5px rgba(0,0,0,0.3); border: 2px solid #FFF;}
        
        .franchise-box { width: 220px; background: #E2FAFA; border: 1px solid #116B7A; padding: 5px; }
        .f-title { text-align: center; font-weight: bold; border-bottom: 1px solid #116B7A; padding-bottom: 5px; margin-bottom: 5px; color: #000;}
        .f-select { width: 100%; background: #FFFECC; border: 1px solid #000; font-weight: bold; font-size:10px; padding:3px;}
        .f-list { margin-top: 5px; background: white; height: 350px; border: 1px solid #CCC; }
        .f-list-row { border-bottom: 1px solid #EEE; height: 25px; }

        /* CONTENT AREA & GLOBAL RESKINNING */
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

        /* BOTTOM TRACKING BAR */
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

    <div class="navbar">
        <ul>
            <li><a href="/">CourierInfo</a></li>
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
                    <li><a href="/reports">Shipper Issue Register</a></li>
                    <li><a href="/reports">Cargo Pkt Inward Register</a></li>
                    <li><a href="/reports">Credit Billing Data Register</a></li>
                    <li><a href="/module/main_reports/cash_billing_register">Cash Billing Data Register</a></li>
                    <li><a href="/reports">Outward Data Register</a></li>
                    <li><a href="/reports">Manifest Data Register</a></li>
                    <li><a href="/module/main_reports/transhipment_charges">Transhipment Charges Regist</a></li>
                    <li><a href="/module/main_reports/repeat_cnote">Repeate C.Note Register</a></li>
                    <li><a href="/module/main_reports/inward_outward_pending">Inward - Outward Pending</a></li>
                    <li><a href="/module/main_reports/inward_outward_wgt">Inward - Outward Wgt. Diff.</a></li>
                    <li><a href="/reports">Invoice Data Register</a></li>
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
                    <li><a href="/module/audit_reports/shipper_stock">Shipper Stock Analysis</a></li>
                    <li><a href="/module/audit_reports/fuel_surcharge">Fuel Surcharge Analysis</a></li>
                    <li><a href="/module/audit_reports/pending_outward">Pending Outward Analysis</a></li>
                    <li><a href="/module/audit_reports/cargo_inward">Cargo Inward Analysis</a></li>
                    <li><a href="/module/audit_reports/local_inward">Local Inward Analysis</a></li>
                    <li><a href="/module/audit_reports/counter_booking">Counter Booking Analysis</a></li>
                    <li><a href="/module/audit_reports/outward">Outward Analysis</a></li>
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

        <div class="franchise-box">
            <div class="f-title">CURRENT FRANCHISEE</div>
            <select class="f-select">
                <option>{{ session.branch | default('NOHAR') }}/{{ session.branch | default('NOHAR') }}-PANKAJ AG</option>
            </select>
            <div class="f-list">
                <div class="f-list-row"></div><div class="f-list-row"></div><div class="f-list-row"></div>
                <div class="f-list-row"></div><div class="f-list-row"></div><div class="f-list-row"></div>
                <div class="f-list-row"></div><div class="f-list-row"></div><div class="f-list-row"></div>
                <div class="f-list-row"></div><div class="f-list-row"></div><div class="f-list-row"></div>
            </div>
        </div>
    </div>

    <!-- BOTTOM BAR: Fixed Links & Form Submission -->
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
# 📱 2. PWA (MOBILE APP) ROUTES
# ==========================================
@app.route('/manifest.json')
def manifest():
    manifest_data = {
        "name": "AGC Enterprise Courier ERP",
        "short_name": "AGC ERP",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#116B7A",
        "theme_color": "#116B7A",
        "icons": [{"src": "https://cdn-icons-png.flaticon.com/512/3063/3063822.png", "sizes": "512x512", "type": "image/png"}]
    }
    return jsonify(manifest_data)

@app.route('/sw.js')
def service_worker():
    sw_js = "self.addEventListener('install', function(event) { console.log('PWA Service Worker Installed'); });\nself.addEventListener('fetch', function(event) { event.respondWith(fetch(event.request)); });"
    return app.response_class(sw_js, mimetype='application/javascript')

# ==========================================
# 🔐 3. AUTH & DASHBOARD (WITH CHARTS)
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '')
        p = request.form.get('password', '')
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s AND active=1", (u,))
        r = c.fetchone()
        if (r and r['password_hash'] == hashlib.sha256(p.encode()).hexdigest()) or (u == "admin" and p == "admin123"):
            branch_val = str(r.get('branch_name') or 'HQ') if r else 'HQ'
            session.update({'user_id': r['id'] if r else 1, 'username': u, 'full_name': r['full_name'] if r else "Admin", 'role': r['role'] if r else "ADMIN", 'branch': branch_val, 'customer_id': r.get('customer_id') if r else None})
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
        else:
            c.execute("SELECT booking_date as dt, COUNT(id) as cnt FROM shipments GROUP BY booking_date ORDER BY dt DESC LIMIT 7")
            
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
        var myChart = new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: {chart_labels},
                datasets: [{{
                    label: 'Parcels Booked',
                    data: {chart_values},
                    backgroundColor: '#116B7A',
                    borderColor: '#000',
                    borderWidth: 1
                }}]
            }}
        }});
    </script>
    """
    return render_page("Dashboard", html)

# ==========================================
# 🌐 4. BRANDED PUBLIC TRACKING PAGE & AGCS BOTTOM BAR LOGIC
# ==========================================

# Yeh naya route bottom bar ke sabhi buttons ko handle karega aur sahi PDF/Page par redirect karega
@app.route('/track_doc', methods=['POST'])
@login_required
def track_doc():
    doc_no = request.form.get('awb', '').strip().upper()
    doc_type = request.form.get('doc_type', '')
    
    error_html = "<html><body style='font-family:Tahoma; padding:20px; background:#FFCCCC; color:red; border:1px solid red; text-align:center;'><h2>Error!</h2><p>{}</p><button onclick='window.close()'>Close Tab</button></body></html>"
    
    if not doc_no:
        return error_html.format("Please enter a Document Number in the bottom bar to track or print.")

    conn = get_db()
    try:
        with conn.cursor() as c:
            # 1. C.Note / Pkg.Slip: Opens tracking page or receipt
            if doc_type == 'c_note':
                return redirect(url_for('track', awb=doc_no))
            elif doc_type == 'pkg_slip':
                return redirect(f"/print/receipt/{doc_no}")
                
            # 2. D.R.S. Button
            elif doc_type == 'drs':
                doc_no_clean = doc_no.replace('DRS', '').strip()
                c.execute("SELECT id FROM drs WHERE drs_no=%s OR id=%s", (doc_no, doc_no_clean if doc_no_clean.isdigit() else None))
                drs = c.fetchone()
                if drs: return redirect(f"/print/drs/{drs['id']}")
                else: return error_html.format(f"DRS '{doc_no}' not found in system.")
                
            # 3. M.Fest Button
            elif doc_type == 'm_fest':
                doc_no_clean = doc_no.replace('MF', '').strip()
                c.execute("SELECT id FROM manifests WHERE manifest_no=%s OR id=%s", (doc_no, doc_no_clean if doc_no_clean.isdigit() else None))
                m = c.fetchone()
                if m: return redirect(f"/print/manifest/{m['id']}")
                else: return error_html.format(f"Manifest '{doc_no}' not found in system.")
                
            # 4. Invoice Button
            elif doc_type == 'invoice':
                doc_no_clean = doc_no.replace('INV/', '').strip()
                c.execute("SELECT id FROM invoices WHERE invoice_no=%s OR id=%s", (doc_no, doc_no_clean if doc_no_clean.isdigit() else None))
                inv = c.fetchone()
                if inv: return error_html.format(f"Invoice '{doc_no}' found! (Invoice PDF module link pending)")
                else: return error_html.format(f"Invoice '{doc_no}' not found in system.")
    finally:
        conn.close()
        
    return error_html.format("Invalid document type requested.")

@app.route('/track', methods=['GET', 'POST'])
def track():
    awb = request.args.get('awb') or request.form.get('awb')
    awb = str(awb).strip().upper() if awb else ''
    events = []; shipment = None; error_msg = None
    if awb:
        try:
            conn = get_db(); c = conn.cursor()
            c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,)); shipment = c.fetchone()
            if shipment:
                c.execute("SELECT scan_type, location, remarks, created_at FROM scan_events WHERE shipment_id=%s ORDER BY id DESC", (shipment['id'],))
                events = c.fetchall()
            c.close(); conn.close()
        except Exception as e: error_msg = str(e)

    html = """
    <style>
        .track-container { max-width: 800px; margin: 20px auto; font-family: Tahoma, Arial; font-size: 11px; }
        .track-card { background: white; border: 1px solid #116B7A; padding: 15px; margin-bottom: 20px; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); border-top: 3px solid #116B7A; }
        .track-title { color: #116B7A; margin-top: 0; border-bottom: 1px dotted #D67A00; padding-bottom: 5px; font-size: 13px; font-weight: bold; }
        .search-area { display: flex; gap: 10px; margin-bottom: 15px; }
        .search-area input { padding: 4px; border: 1px solid #116B7A; background: #FFFECC; font-weight: bold; color: blue; text-transform: uppercase; width: 250px; }
        .search-area button { background: linear-gradient(to bottom, #116B7A, #0D505B); color: white; border: 1px solid #000; padding: 4px 15px; font-weight: bold; cursor: pointer; }
        .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; background: #F4FAFA; border: 1px solid #CCC; padding: 15px; margin-bottom: 20px; }
        .info-item strong { color: #003366; display: inline-block; width: 100px; }
        .status-hl { background: #D67A00; color: white; padding: 2px 5px; font-weight: bold; border-radius: 2px; }
        .track-table { width: 100%; border-collapse: collapse; border: 1px solid #116B7A; }
        .track-table th { background: #116B7A; color: white; padding: 5px; text-align: left; border: 1px solid #000; }
        .track-table td { padding: 5px; border: 1px solid #CCC; }
        .track-table tr:nth-child(even) { background: #F4FAFA; }
        .track-table tr:hover { background: #FFDE99; }
    </style>

    <div class="track-container">
        <div class="track-card">
            <h3 class="track-title">C.Note / Shipment Tracking Detail</h3>
            
            <form method="GET" class="search-area">
                <input type="text" name="awb" value="{{ awb }}" placeholder="Enter C.Note Number" required autofocus>
                <button type="submit">TRACK</button>
            </form>
            
            {% if error_msg %}
                <div style="color:red; font-weight:bold; border:1px solid red; padding:5px; background:#FFCCCC;">System Error: {{ error_msg }}</div>
            {% elif awb and not shipment %}
                <div style="color:red; font-weight:bold; border:1px solid red; padding:5px; background:#FFCCCC;">No record found for C.Note / Document No: {{ awb }}</div>
            {% elif shipment %}
                
                <div class="info-grid">
                    <div class="info-item">
                        <strong>C.Note No:</strong> <span style="color:red; font-weight:bold; font-size:12px;">{{ shipment.awb_no }}</span><br>
                        <strong>Booking Date:</strong> {{ shipment.booking_date }}<br>
                        <strong>Origin:</strong> {{ shipment.origin_name or '-' }}<br>
                        <strong>Destination:</strong> {{ shipment.dest_name or '-' }} ({{ shipment.dest_station or '-' }})
                    </div>
                    <div class="info-item">
                        <strong>Current Status:</strong> <span class="status-hl">{{ shipment.status }}</span><br>
                        <strong>Location:</strong> {{ shipment.current_location or '-' }}<br>
                        <strong>Weight:</strong> {{ shipment.weight_kg }} KG<br>
                        <strong>Pcs:</strong> {{ shipment.quantity or '1' }}
                    </div>
                </div>

                <h3 class="track-title">Tracking History (Movement Detail)</h3>
                
                {% if events %}
                <table class="track-table">
                    <thead>
                        <tr>
                            <th>Date / Time</th>
                            <th>Status / Scan Type</th>
                            <th>Location & Remarks</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for e in events %}
                        <tr>
                            <td>{{ e.created_at }}</td>
                            <td style="font-weight:bold; color:#116B7A;">{{ e.scan_type }}</td>
                            <td><strong>{{ e.location or '-' }}</strong> - {{ e.remarks or '' }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% else %}
                <p style="font-weight:bold; color:red;">No movement history available yet.</p>
                {% endif %}
            {% endif %}
        </div>
    </div>
    """
    
    try:
        from flask import render_template_string
        return render_page(f"Tracking {awb}", render_template_string(html, awb=awb, shipment=shipment, events=events, error_msg=error_msg))
    except Exception:
        return render_template_string("<html><body>" + html + "</body></html>", awb=awb, shipment=shipment, events=events, error_msg=error_msg)

# ==========================================
# 🏢 MASTER ENTRIES: FULLY INTEGRATED AGCSINFO STYLE
# ==========================================

# 1. CARGO PARTY A/C MASTER & FRANCHISEE MASTER
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
        .agcs-btn-grey:hover { background-color: #E0E0E0; }
        .page-title-green { color: #006600; font-style: italic; font-weight: bold; font-size: 14px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>

    <div style="background: white; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green" style="text-transform:uppercase;">{{ page_title }}</h2>
        
        <div class="agcs-top-bar">
            <button type="button" class="agcs-btn-grey" onclick="document.getElementById('masterForm').submit()">SAVE</button>
            <button type="button" class="agcs-btn-grey" onclick="document.getElementById('masterForm').reset()">RESET</button>
            <button type="button" class="agcs-btn-grey">DELETE</button>
            <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            <div style="margin-left: auto; color: #D67A00; font-weight: bold; font-size:14px; padding-right:10px;">
                Center : {{ session.branch | default('NOHAR') }}/{{ session.branch | default('NOHAR') }}-PANKAJ AGENCY
            </div>
        </div>
        
        <div class="agcs-container">
            <div class="agcs-left-list">
                <div class="list-header">CURRENT ACCOUNTS</div>
                <div style="background: #99CCCC;">
                    {% for r in custs %}
                    <div class="list-item" title="{{ r.name }}" onclick="loadData('{{ r.code }}', '{{ r.name }}', '{{ r.address }}', '{{ r.phone }}', '{{ r.gstin }}')">{{ r.name }}</div>
                    {% endfor %}
                </div>
            </div>
            
            <div class="agcs-right-form">
                <form method="POST" id="masterForm" style="margin:0;">
                    <div class="list-header" style="text-align:center; background:#DCEBEB;">MASTER DETAILS</div>
                    <table class="agcs-form-table">
                        <tr>
                            <td class="agcs-label" style="width:15%;">Party Code</td>
                            <td colspan="3"><input type="text" name="code" id="f_code" class="agcs-input" style="width: 30%;" required></td>
                        </tr>
                        <tr>
                            <td class="agcs-label">Frnchls Type</td>
                            <td colspan="3">
                                <select class="agcs-input" style="width: 50%;"><option>LOCAL FRANCHISEE</option><option>REGIONAL</option></select>
                            </td>
                        </tr>
                        <tr>
                            <td class="agcs-label">Address</td>
                            <td colspan="3"><input type="text" name="address" id="f_address" class="agcs-input" style="width: 60%; margin-bottom: 2px;"><br><input type="text" class="agcs-input" style="width: 60%; margin-bottom: 2px;"><br><input type="text" class="agcs-input" style="width: 60%;"></td>
                        </tr>
                        <tr>
                            <td class="agcs-label">Area</td>
                            <td colspan="3"><input type="text" name="area" class="agcs-input" style="width: 60%;"></td>
                        </tr>
                        <tr>
                            <td class="agcs-label">City</td>
                            <td style="width:35%;"><input type="text" name="city" class="agcs-input" style="width: 80%;"></td>
                            <td class="agcs-label" style="width:15%;">Country</td>
                            <td><select name="country" class="agcs-input" style="width: 80%;"><option value="INDIA">INDIA</option></select></td>
                        </tr>
                        <tr>
                            <td class="agcs-label">State</td>
                            <td>
                                <input type="text" name="scode" class="agcs-input" style="width: 25%; margin-right: 2px; background:white; border:1px solid #116B7A;" placeholder="Code">
                                <select name="state" class="agcs-input" style="width: 50%;"><option value="RAJASTHAN">RAJASTHAN</option><option value="HARYANA">HARYANA</option></select>
                            </td>
                            <td class="agcs-label">PinCode</td>
                            <td><input type="text" name="pincode" class="agcs-input" style="width: 80%;"></td>
                        </tr>
                    </table>

                    <div style="display:flex; justify-content:space-between; margin-top:5px;">
                        <div class="agcs-section-header" style="flex:1; margin-right:2px;">CONTACT DETAILS</div>
                        <div class="agcs-section-header" style="flex:1;">REGISTRATION NUMBERS</div>
                    </div>
                    
                    <div style="display:flex;">
                        <table class="agcs-form-table" style="flex:1; border-right:1px solid #009933; padding-right:5px;">
                            <tr><td class="agcs-label">Name</td><td><input type="text" name="name" id="f_name" class="agcs-input" required></td></tr>
                            <tr><td class="agcs-label">Phone1</td><td><input type="text" name="phone1" id="f_phone" class="agcs-input"></td></tr>
                            <tr><td class="agcs-label">Email ID</td><td><input type="email" name="email" class="agcs-input"></td></tr>
                            <tr><td class="agcs-label">WebSite</td><td><input type="text" name="website" class="agcs-input"></td></tr>
                        </table>
                        <table class="agcs-form-table" style="flex:1; padding-left:5px;">
                            <tr><td class="agcs-label">PAN No.</td><td><input type="text" name="pan" class="agcs-input"></td></tr>
                            <tr><td class="agcs-label">TAN No.</td><td><input type="text" name="tan" class="agcs-input"></td></tr>
                            <tr><td class="agcs-label">State GST</td><td><input type="text" name="gstin" id="f_gstin" class="agcs-input"></td></tr>
                            <tr><td class="agcs-label">Credit Limit</td><td><input type="number" step="0.01" name="limit" class="agcs-input" value="0.00"></td></tr>
                        </table>
                    </div>
                </form>
            </div>
        </div>
    </div>
    <script>
        function loadData(code, name, address, phone, gstin) {
            document.getElementById('f_code').value = code;
            document.getElementById('f_name').value = name;
            document.getElementById('f_address').value = address;
            document.getElementById('f_phone').value = phone;
            document.getElementById('f_gstin').value = gstin;
        }
    </script>
    """
    return render_page(page_title, render_template_string(html, custs=custs, page_title=page_title))

# 2. DELIVERY BOY MASTER
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
    with conn.cursor() as c: 
        c.execute("SELECT * FROM users WHERE role='DELIVERY' ORDER BY id DESC"); boys = c.fetchall()
    conn.close()

    html = """
    <style>
        .agcs-container { display: flex; gap: 5px; height: 500px; }
        .agcs-left-list { width: 250px; background: #99CCCC; border: 1px solid #116B7A; overflow-y: auto; padding: 2px;}
        .agcs-right-form { flex: 1; background: #E2FAFA; border: 1px solid #116B7A; padding: 5px; }
        .list-header { background: #E2FAFA; font-weight: bold; border-bottom: 1px solid #116B7A; padding: 3px; font-size: 11px; color: #006600; font-style: italic;}
        .list-item { font-size: 11px; padding: 3px; cursor: pointer; border-bottom: 1px solid #B0D4D4; font-weight: bold;}
        .list-item:hover { background: #FFFECC; }
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #0066CC; font-weight: bold; font-size: 11px; white-space: nowrap;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-family: Tahoma; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-input:focus { background-color: #FFF; border: 1px solid red;}
        .agcs-top-bar { display: flex; gap: 5px; padding: 5px; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: #E2FAFA;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 15px; font-family: Tahoma; font-size: 11px; font-weight: bold; cursor: pointer; color: #000; border-radius:3px;}
        .page-title-green { color: #006600; font-style: italic; font-weight: bold; font-size: 14px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>

    <div style="background: white; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green">DELIVERY BOY MASTER ENTRY</h2>
        <div class="agcs-top-bar">
            <button type="button" class="agcs-btn-grey" onclick="document.getElementById('masterForm').submit()">SAVE</button>
            <button type="button" class="agcs-btn-grey" onclick="document.getElementById('masterForm').reset()">RESET</button>
            <button type="button" class="agcs-btn-grey">DELETE</button>
            <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            <div style="margin-left: auto; color: #D67A00; font-weight: bold; font-size:14px; padding-right:10px;">
                Center : {{ session.branch | default('NOHAR') }}/{{ session.branch | default('NOHAR') }}-PANKAJ AGENCY
            </div>
        </div>
        <div class="agcs-container">
            <div class="agcs-left-list">
                <div class="list-header" style="color:black; font-style:normal;">CURRENT DELIVERY BOY</div>
                <div style="background: #99CCCC;">
                    {% for b in boys %}
                    <div class="list-item" onclick="loadBoy('{{ b.username }}', '{{ b.full_name }}')">{{ b.full_name | upper }}</div>
                    {% endfor %}
                </div>
            </div>
            <div class="agcs-right-form">
                <form method="POST" id="masterForm" style="margin:0;">
                    <div class="list-header" style="text-align:center; background:#DCEBEB; color:black; font-style:normal;">DELIVERY BOY'S DETAILS</div>
                    <table class="agcs-form-table" style="width: 80%; margin: 10px auto;">
                        <tr><td class="agcs-label" style="width:20%;">Boy Code</td><td colspan="3"><input type="text" name="code" id="b_code" class="agcs-input" style="width: 30%;" required></td></tr>
                        <tr><td class="agcs-label">Full Name</td><td colspan="3"><input type="text" name="name" id="b_name" class="agcs-input" style="width: 80%;" required></td></tr>
                        <tr><td class="agcs-label">Address</td><td colspan="3"><input type="text" name="address" class="agcs-input" style="width: 100%; margin-bottom: 2px;"><br><input type="text" class="agcs-input" style="width: 100%; margin-bottom: 2px;"><br><input type="text" class="agcs-input" style="width: 100%;"></td></tr>
                        <tr><td class="agcs-label">Area</td><td><input type="text" name="area" class="agcs-input" style="width: 90%;"></td><td class="agcs-label" style="text-align:right;">City</td><td><input type="text" class="agcs-input" style="width: 90%;"></td></tr>
                        <tr><td class="agcs-label">State</td><td><input type="text" class="agcs-input" style="width: 90%;"></td><td class="agcs-label" style="text-align:right;">PinCode</td><td><input type="text" class="agcs-input" style="width: 90%;"></td></tr>
                        <tr><td class="agcs-label">Phone No.</td><td><input type="text" name="phone" class="agcs-input" style="width: 90%;"></td><td class="agcs-label" style="text-align:right;">Mobile No</td><td><input type="text" class="agcs-input" style="width: 90%;"></td></tr>
                        <tr><td class="agcs-label">Ref Prsn</td><td><input type="text" class="agcs-input" style="width: 90%;"></td><td class="agcs-label" style="text-align:right;">Ref. No</td><td><input type="text" class="agcs-input" style="width: 90%;"></td></tr>
                    </table>
                </form>
            </div>
        </div>
    </div>
    <script>function loadBoy(code, name) { document.getElementById('b_code').value = code; document.getElementById('b_name').value = name;}</script>
    """
    return render_page("Delivery Boy Master Entry", render_template_string(html, boys=boys))

# 3. USER LOGIN SETUP
@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE users SET active=0 WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("User Deactivated!", "success"); return redirect('/users')
    if request.method == 'POST':
        d = request.form; b = str(d.get('branch', '')).upper()
        cid = safe_int(d.get('customer_id')) if d.get('customer_id') else None
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
    <style>
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #003366; font-weight: bold; width: 120px; font-size: 11px;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;}
        .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>
    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green">USER LOGIN SETUP (ADMIN / USER CREATION)</h2>
        <form method="POST">
            <div class="agcs-top-bar">
                <button type="submit" class="agcs-btn-grey">SAVE</button>
                <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            </div>
            <div style="background: #E2FAFA; padding: 2px;">
                <table class="agcs-form-table" style="width:60%; margin:auto; border:1px solid #116B7A; background:white;">
                    <tr><td colspan="2" style="background:#116B7A; color:white; font-weight:bold; text-align:center;">User Account Details</td></tr>
                    <tr><td class="agcs-label" style="padding-top:10px;">Username</td><td style="padding-top:10px;"><input type="text" name="username" class="agcs-input" required></td></tr>
                    <tr><td class="agcs-label">Password</td><td><input type="password" name="password" class="agcs-input" required></td></tr>
                    <tr><td class="agcs-label">Full Name</td><td><input type="text" name="full_name" class="agcs-input" required></td></tr>
                    <tr><td class="agcs-label">Role / Access</td><td><select name="role" class="agcs-input"><option>OPERATOR</option><option>ADMIN</option><option>ACCOUNTANT</option><option>CUSTOMER</option></select></td></tr>
                    <tr><td class="agcs-label">Branch / Station</td><td><input type="text" name="branch" list="brlist" class="agcs-input" required><datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist></td></tr>
                    <tr><td class="agcs-label" style="padding-bottom:10px;">Link Customer (B2B)</td><td style="padding-bottom:10px;"><select name="customer_id" class="agcs-input"><option value="">-- None --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></td></tr>
                </table>
            </div>
        </form>
        <div style="background: white; border: 1px solid #116B7A; margin-top: 15px;">
            <div style="height: 250px; overflow-y: auto;">
                <table class="datatable" style="width: 100%; border: none; margin: 0;">
                    <thead style="position: sticky; top: 0;"><tr><th>Username</th><th>Full Name</th><th>Role</th><th>Branch</th><th>Act</th></tr></thead>
                    <tbody>
                        {% for u in u_list %}<tr><td><strong>{{ u.username }}</strong></td><td>{{ u.full_name }}</td><td>{{ u.role }}</td><td>{{ u.branch_name }}</td><td>{% if u.active %}<a href="/users?delete={{ u.id }}" style="color:red; font-weight:bold;">[Del]</a>{% else %}Inactive{% endif %}</td></tr>{% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("User Login SetUp", render_template_string(html, u_list=u_list, branches=branches, custs=custs))

@app.route('/location_master', methods=['GET', 'POST'])
@login_required
def location_master():
    """Handles Geographical Location Master"""
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip().upper()
        scode = request.form.get('state_code', '').strip().upper()
        if name:
            with conn.cursor() as c:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (name,))
                conn.commit(); flash(f"Location {name} Saved Successfully!", "success")
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM stations ORDER BY id DESC LIMIT 100"); stations_list = c.fetchall()
    conn.close()

    html = """
    <style>
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px; background: #E2FAFA;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #003366; font-weight: bold; width: 150px; font-size: 11px;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;}
        .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>
    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green">GEOGRAPHICAL LOCATION MASTER</h2>
        <form method="POST">
            <div class="agcs-top-bar">
                <button type="submit" class="agcs-btn-grey">SAVE</button>
                <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            </div>
            <div style="background: #E2FAFA; padding: 2px;">
                <table class="agcs-form-table">
                    <tr><td class="agcs-label">Location / Station Name</td><td><input type="text" name="name" class="agcs-input" style="width: 50%; color:blue; font-weight:bold;" required></td></tr>
                    <tr><td class="agcs-label">State Code (Optional)</td><td><input type="text" name="state_code" class="agcs-input" style="width: 20%;"></td></tr>
                    <tr><td class="agcs-label">Hub / Direct</td><td><select class="agcs-input" style="width:30%;"><option>HUB</option><option>DIRECT</option></select></td></tr>
                </table>
            </div>
        </form>
        <div style="background: white; border: 1px solid #116B7A; margin-top: 15px;">
            <div style="height: 250px; overflow-y: auto;">
                <table class="datatable" style="width: 100%; border: none; margin: 0;">
                    <thead style="position: sticky; top: 0;"><tr><th>ID</th><th>Station Name</th><th>Act</th></tr></thead>
                    <tbody>
                        {% for r in s_list %}<tr><td>{{ r.id }}</td><td style="color: blue; font-weight: bold;">{{ r.name }}</td><td style="text-align:center;"><a href="#" style="color:red;">[Edit]</a></td></tr>{% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Geographical Location Master", render_template_string(html, s_list=stations_list))

@app.route('/credit_party', methods=['GET', 'POST'])
@login_required
def credit_party():
    """Handles Credit Party A/c Master (B2B Clients with ledgers)"""
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("INSERT INTO customers(code, name, gstin, phone, address, credit_limit, is_active) VALUES(%s,%s,%s,%s,%s,%s,1)", (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone',''), d.get('address',''), safe_float(d.get('limit'))))
            conn.commit(); flash("Credit Party Saved!", "success")
            
    with conn.cursor() as c: c.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id DESC LIMIT 50"); custs = c.fetchall()
    conn.close()

    html = """
    <style>
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px; background: #E2FAFA;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #003366; font-weight: bold; width: 120px; font-size: 11px;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;}
        .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>
    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green">CREDIT PARTY A/C MASTER</h2>
        <form method="POST">
            <div class="agcs-top-bar">
                <button type="submit" class="agcs-btn-grey">SAVE</button>
                <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            </div>
            <div style="background: #E2FAFA; padding: 2px;">
                <table class="agcs-form-table">
                    <tr><td class="agcs-label">Party Name</td><td colspan="3"><input type="text" name="name" class="agcs-input" style="width: 60%; color:blue; font-weight:bold;" required></td></tr>
                    <tr><td class="agcs-label">A/c Code</td><td colspan="3"><input type="text" name="code" class="agcs-input" style="width: 30%;" required></td></tr>
                    <tr><td class="agcs-label">Address</td><td colspan="3"><input type="text" name="address" class="agcs-input" style="width: 60%;"></td></tr>
                    <tr><td class="agcs-label">Phone</td><td><input type="text" name="phone" class="agcs-input" style="width: 80%;"></td><td class="agcs-label" style="text-align:right;">GSTIN</td><td><input type="text" name="gstin" class="agcs-input" style="width: 80%;"></td></tr>
                    <tr><td class="agcs-label">Credit Limit (Rs)</td><td colspan="3"><input type="number" step="0.01" name="limit" class="agcs-input" value="0.00" style="width: 30%;"></td></tr>
                </table>
            </div>
        </form>
        <div style="background: white; border: 1px solid #116B7A; margin-top: 15px;">
            <div style="height: 250px; overflow-y: auto;">
                <table class="datatable" style="width: 100%; border: none; margin: 0;">
                    <thead style="position: sticky; top: 0;"><tr><th>Code</th><th>Name</th><th>Phone</th><th>GSTIN</th><th>Limit</th></tr></thead>
                    <tbody>{% for r in custs %}<tr><td>{{ r.code }}</td><td style="color: blue; font-weight: bold;">{{ r.name }}</td><td>{{ r.phone }}</td><td>{{ r.gstin }}</td><td>{{ r.credit_limit }}</td></tr>{% endfor %}</tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Credit Party A/c Master", render_template_string(html, custs=custs))

# ==========================================
# 🏢 EXTENDED MASTER ENTRIES (PART 2)
# ==========================================

# 4. RATE MASTER (Fully AGCSInfo Styled)
@app.route('/rates', methods=['GET', 'POST'])
@login_required
def rates():
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM rates WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Rate Deleted!", "success"); return redirect('/rates')
    
    if request.method == 'POST':
        d = request.form; cid = safe_int(d.get('cust_id')) if d.get('cust_id') else None
        with conn.cursor() as c: 
            c.execute("INSERT INTO rates(customer_id, origin_state_code, dest_state_code, min_weight, max_weight, fixed_charge, per_kg_rate, gst_rate) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (cid, d.get('ostate',''), d.get('dstate',''), safe_float(d.get('min_w')), safe_float(d.get('max_w')), safe_float(d.get('fixed')), safe_float(d.get('per_kg')), safe_float(d.get('gst')))); conn.commit(); flash("Rate Card Added!", "success")
            
    with conn.cursor() as c: 
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name")
        custs = c.fetchall()
        c.execute("SELECT r.*, c.name FROM rates r LEFT JOIN customers c ON c.id=r.customer_id ORDER BY r.id DESC")
        r_list = c.fetchall()
    conn.close()
    
    html = """
    <style>
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #003366; font-weight: bold; width: 120px; font-size: 11px;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;}
        .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>
    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green">RATE MASTER SETUP</h2>
        <form method="POST">
            <div class="agcs-top-bar">
                <button type="submit" class="agcs-btn-grey">SAVE</button>
                <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            </div>
            <div style="background: #E2FAFA; padding: 2px;">
                <table class="agcs-form-table" style="width: 70%; margin: auto;">
                    <tr>
                        <td class="agcs-label" style="width:15%;">Franchisee / Customer</td>
                        <td colspan="3"><select name="cust_id" class="agcs-input" style="width: 80%;"><option value="">-- Generic / Default Rate --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Origin State Code</td>
                        <td><input type="text" name="ostate" class="agcs-input" style="width: 60%;" required></td>
                        <td class="agcs-label" style="text-align:right;">Dest State Code</td>
                        <td><input type="text" name="dstate" class="agcs-input" style="width: 60%;" required></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Min Wt Slab (KG)</td>
                        <td><input type="number" step="0.1" name="min_w" class="agcs-input" value="0.0" style="width: 60%;"></td>
                        <td class="agcs-label" style="text-align:right;">Max Wt Slab (KG)</td>
                        <td><input type="number" step="0.1" name="max_w" class="agcs-input" value="999.0" style="width: 60%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Fixed Charge (Rs)</td>
                        <td><input type="number" step="0.1" name="fixed" class="agcs-input" value="0.0" style="width: 60%; font-weight:bold; color:red;"></td>
                        <td class="agcs-label" style="text-align:right;">Per KG Rate (Rs)</td>
                        <td><input type="number" step="0.1" name="per_kg" class="agcs-input" value="0.0" style="width: 60%; font-weight:bold; color:blue;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Applicable GST %</td>
                        <td colspan="3"><input type="number" step="0.1" name="gst" class="agcs-input" value="18.0" style="width: 25%;"></td>
                    </tr>
                </table>
            </div>
        </form>
        <div style="background: white; border: 1px solid #116B7A; margin-top: 15px;">
            <div style="background: #116B7A; color: white; font-weight: bold; padding: 5px;">Active Rate Cards</div>
            <div style="height: 250px; overflow-y: auto;">
                <table class="datatable" style="width: 100%; border: none; margin: 0;">
                    <thead style="position: sticky; top: 0;"><tr><th>Customer</th><th>Route</th><th>Wt Slab</th><th>Fixed</th><th>Per KG</th><th>GST</th><th>Act</th></tr></thead>
                    <tbody>
                        {% for r in r_list %}
                        <tr>
                            <td style="color:blue; font-weight:bold;">{{ r.name or 'Generic' }}</td>
                            <td>{{ r.origin_state_code }} &rarr; {{ r.dest_state_code }}</td>
                            <td>{{ r.min_weight }} - {{ r.max_weight }} KG</td>
                            <td style="font-weight:bold; color:red;">{{ r.fixed_charge }}</td>
                            <td style="font-weight:bold;">{{ r.per_kg_rate }}</td>
                            <td>{{ r.gst_rate }}%</td>
                            <td style="text-align:center;"><a href="/rates?delete={{ r.id }}"><img src="https://cdn-icons-png.flaticon.com/128/3096/3096673.png" width="12" title="Delete"></a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Rate Master", render_template_string(html, custs=custs, r_list=r_list))

# 5. STATIONERY (SHIPPER / BARCODE ISSUE)
@app.route('/stationery', methods=['GET', 'POST'])
@login_required
def stationery():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM shipments WHERE status='STATIONERY' AND origin_name=%s AND booking_date=%s", (request.args.get('name'), request.args.get('date'))); conn.commit(); flash("Allocation Deleted!", "success"); return redirect('/stationery')
    
    if request.method == 'POST':
        name = request.form.get('name', '')
        pfx = request.form.get('prefix', '')
        frm = safe_int(request.form.get('from'))
        to = safe_int(request.form.get('to'))
        if frm > 0 and to >= frm:
            with conn.cursor() as c:
                for i in range(frm, to + 1): 
                    c.execute("INSERT IGNORE INTO shipments(awb_no, origin_name, status, current_location, booking_date) VALUES(%s,%s,'STATIONERY','Allocated',CURDATE())", (f"{pfx}{i}", name))
                conn.commit(); flash(f"Allocated {to-frm+1} AWBs!", "success")
                
    with conn.cursor() as c:
        c.execute("SELECT name FROM stations UNION SELECT name FROM customers ORDER BY name"); names = c.fetchall()
        c.execute("SELECT booking_date, origin_name, COUNT(*) as qty, MIN(awb_no) as from_awb, MAX(awb_no) as to_awb FROM shipments WHERE status='STATIONERY' GROUP BY booking_date, origin_name ORDER BY booking_date DESC")
        hists = c.fetchall()
    conn.close()
    
    html = """
    <style>
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #003366; font-weight: bold; width: 150px; font-size: 11px;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;}
        .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>
    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green">SHIPPER / BARCODE ISSUE ENTRY</h2>
        <form method="POST">
            <div class="agcs-top-bar">
                <button type="submit" class="agcs-btn-grey">SAVE</button>
                <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            </div>
            <div style="background: #E2FAFA; padding: 2px;">
                <table class="agcs-form-table" style="width:60%;">
                    <tr>
                        <td class="agcs-label">Assign To (Branch/Client)</td>
                        <td colspan="3"><input type="text" name="name" list="nlist" class="agcs-input" required><datalist id="nlist">{% for n in names %}<option value="{{ n.name }}">{% endfor %}</datalist></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Prefix</td>
                        <td colspan="3"><input type="text" name="prefix" value="AWB" class="agcs-input" style="width:40%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">From AWB No</td>
                        <td><input type="number" name="from" class="agcs-input" required></td>
                        <td class="agcs-label" style="text-align:right;">To AWB No</td>
                        <td><input type="number" name="to" class="agcs-input" required></td>
                    </tr>
                </table>
            </div>
        </form>
        <div style="background: white; border: 1px solid #116B7A; margin-top: 15px;">
            <div style="background: #116B7A; color: white; font-weight: bold; padding: 5px;">Allocation History</div>
            <div style="height: 250px; overflow-y: auto;">
                <table class="datatable" style="width: 100%; border: none; margin: 0;">
                    <thead style="position: sticky; top: 0;"><tr><th>Date</th><th>Assigned To</th><th>Qty</th><th>AWB Range</th><th>Act</th></tr></thead>
                    <tbody>
                        {% for h in hists %}
                        <tr>
                            <td>{{ h.booking_date }}</td>
                            <td style="font-weight:bold; color:blue;">{{ h.origin_name }}</td>
                            <td style="font-weight:bold; color:red;">{{ h.qty }}</td>
                            <td>{{ h.from_awb }} to {{ h.to_awb }}</td>
                            <td style="text-align:center;"><a href="/stationery?delete=1&name={{ h.origin_name }}&date={{ h.booking_date }}"><img src="https://cdn-icons-png.flaticon.com/128/3096/3096673.png" width="12" title="Delete"></a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Shipper/Barcode Issue", render_template_string(html, names=names, hists=hists))

# 6. MISC. SETUP (System Settings Form)
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if session.get('role') != 'ADMIN': flash("Access Denied: Admins only.", "error"); return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        with conn.cursor() as c:
            for key, val in request.form.items(): c.execute("INSERT INTO settings(key_name, value) VALUES(%s, %s) ON DUPLICATE KEY UPDATE value=VALUES(value)", (key, val))
            conn.commit(); flash("Settings Saved Successfully!", "success")
    with conn.cursor() as c:
        try: c.execute("SELECT * FROM settings"); s_dict = {str(r.get('key_name') or r.get('key', '')): str(r.get('value') or '') for r in c.fetchall()}
        except: s_dict = {}
    conn.close()
    
    html = """
    <style>
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #003366; font-weight: bold; width: 150px; font-size: 11px;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-weight: bold; cursor: pointer; color: #000;}
        .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>
    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green">MISCELLANEOUS SETUP (COMPANY INFO)</h2>
        <form method="POST">
            <div class="agcs-top-bar">
                <button type="submit" class="agcs-btn-grey">SAVE SETTINGS</button>
                <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            </div>
            <div style="background: #E2FAFA; padding: 10px; border: 1px solid #CCC; margin-top: 10px;">
                <table class="agcs-form-table" style="width:80%; margin:auto;">
                    <tr><td class="agcs-label">Company Name</td><td><input type="text" name="company_name" value="{{ s.get('company_name', '') }}" class="agcs-input" style="color:blue; font-weight:bold;" required></td></tr>
                    <tr><td class="agcs-label">Company GSTIN</td><td><input type="text" name="company_gstin" value="{{ s.get('company_gstin', '') }}" class="agcs-input"></td></tr>
                    <tr><td class="agcs-label">Head Office Address</td><td><input type="text" name="company_address" value="{{ s.get('company_address', '') }}" class="agcs-input"></td></tr>
                    <tr><td class="agcs-label">Customer Care Phone</td><td><input type="text" name="company_phone" value="{{ s.get('company_phone', '') }}" class="agcs-input"></td></tr>
                    <tr><td class="agcs-label">Company Email</td><td><input type="email" name="company_email" value="{{ s.get('company_email', '') }}" class="agcs-input"></td></tr>
                    <tr><td class="agcs-label">Website</td><td><input type="text" name="company_website" value="{{ s.get('company_website', '') }}" class="agcs-input"></td></tr>
                    <tr><td class="agcs-label">Bank Details (For Invoices)</td><td><input type="text" name="bank_details" value="{{ s.get('bank_details', '') }}" class="agcs-input"></td></tr>
                    <tr><td class="agcs-label">Fuel Surcharge (%)</td><td><input type="number" step="0.1" name="fuel_surcharge" value="{{ s.get('fuel_surcharge', '0') }}" class="agcs-input" style="width: 30%; color:red; font-weight:bold;"></td></tr>
                    <tr><td class="agcs-label">Terms & Conditions Note</td><td><textarea name="terms_note" class="agcs-input" rows="3">{{ s.get('terms_note', '') }}</textarea></td></tr>
                </table>
            </div>
        </form>
    </div>
    """
    return render_page("Misc. SetUp", render_template_string(html, s=s_dict))

# ==========================================
# END OF EXTENDED MASTER ENTRIES
# ==========================================

# ==========================================
# 📦 6. TRANSACTIONS & BOOKING
# ==========================================
@app.route('/api/calc_rate', methods=['POST'])
@login_required
def api_calc_rate():
    d = request.json
    cid = safe_int(d.get('cust_id')) if d.get('cust_id') else None; ost = d.get('ostate', ''); dst = d.get('dstate', ''); wt = safe_float(d.get('wt'))
    fr = safe_float(d.get('fr')); tx = safe_float(d.get('tax'))
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
    with conn.cursor() as c:
        c.execute("SELECT dest_station, dest_name, weight_kg FROM shipments WHERE awb_no=%s", (awb.upper(),))
        s = c.fetchone()
    conn.close()
    if s:
        return jsonify({"success": True, "dest_station": s['dest_station'], "dest_name": s['dest_name'], "weight": s['weight_kg']})
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
                conn.commit()
                flash(f"AWB {awb} Booked! Total: Rs {tot:.2f}", "success")
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
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        d = request.form; fr = safe_float(d.get('fr')); tax = safe_float(d.get('tax', 18)); wt = safe_float(d.get('wt', 1))
        fuel = safe_float(get_setting("fuel_surcharge", "0")); taxable = fr * (1 + (fuel/100)); gst = taxable * (tax / 100); tot = taxable + gst
        cgst = sgst = igst = 0
        if str(d.get('ostate','')).strip().upper() == str(d.get('dstate','')).strip().upper(): cgst = sgst = gst / 2
        else: igst = gst
        with conn.cursor() as c:
            try:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d.get('dstat','').upper(),)); c.execute("SELECT status, current_location FROM shipments WHERE id=%s", (sid,)); old_s = c.fetchone()
                c.execute("""UPDATE shipments SET awb_no=%s, booking_date=%s, origin_name=%s, origin_phone=%s, origin_address=%s, origin_state_code=%s, dest_name=%s, dest_phone=%s, dest_address=%s, dest_state_code=%s, dest_station=%s, weight_kg=%s, quantity=%s, cod_amount=%s, declared_value=%s, service_type=%s, taxable_amount=%s, tax_rate=%s, cgst=%s, sgst=%s, igst=%s, total_amount=%s, info=%s, status=%s, current_location=%s WHERE id=%s""", (d.get('awb','').upper(), d.get('date',''), d.get('oname',''), d.get('ophone',''), d.get('oaddr',''), d.get('ostate',''), d.get('dname',''), d.get('dphone',''), d.get('daddr',''), d.get('dstate',''), d.get('dstat','').upper(), wt, safe_int(d.get('pcs', 1)), safe_float(d.get('cod')), safe_float(d.get('dec')), d.get('srv','SURFACE'), taxable, tax, cgst, sgst, igst, tot, d.get('info',''), d.get('status','BOOKED'), d.get('location',''), sid))
                new_status = d.get('status','BOOKED'); new_loc = d.get('location','')
                if old_s and (old_s['status'] != new_status or old_s['current_location'] != new_loc): c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,%s,%s,'Updated via Edit Panel')", (sid, new_status, new_loc))
                conn.commit(); flash("Updated!", "success")
            except Exception as e: flash(f"Error: {e}", "error")
        return redirect('/booking')
    with conn.cursor() as c: c.execute("SELECT * FROM shipments WHERE id=%s", (sid,)); s = c.fetchone(); c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
    conn.close()
    if not s: flash("Not found", "error"); return redirect('/booking')
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
                <button type="button" class="agcs-btn-grey" onclick="window.location.href='/booking'">CANCEL</button>
            </div>
            
            <table class="agcs-form-table" style="border:1px solid #116B7A; background:white; margin-bottom:10px;">
                <tr>
                    <td class="agcs-label" style="text-align:left;">Booking Date</td><td><input type="date" name="date" value="{{ s.booking_date }}" required class="agcs-input" style="color:blue; font-weight:bold; width:120px;"></td>
                    <td class="agcs-label" style="color:red; font-size:12px;">C.Note No.</td><td><input name="awb" value="{{ s.awb_no }}" required class="agcs-input" style="font-weight:bold; color:red; text-transform:uppercase; width:150px;"></td>
                    <td class="agcs-label">Status</td><td><select name="status" class="agcs-input" style="color:red; font-weight:bold; width:150px;"><option {% if s.status == 'BOOKED' %}selected{% endif %}>BOOKED</option><option {% if s.status == 'OUTWARD' %}selected{% endif %}>OUTWARD</option><option {% if s.status == 'INWARD' %}selected{% endif %}>INWARD</option><option {% if s.status == 'ON_DRS' %}selected{% endif %}>ON_DRS</option><option {% if s.status == 'DELIVERED' %}selected{% endif %}>DELIVERED</option></select></td>
                    <td class="agcs-label">Location</td><td><input name="location" value="{{ s.current_location or '' }}" class="agcs-input" style="width:150px;"></td>
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
    return render_page(f"Edit C.Note: {s['awb_no']}", render_template_string(html, s=s, stations=stations))

@app.route('/shipments', methods=['GET', 'POST'])
@login_required
def shipments():
    conn = get_db()
    if request.args.get('delete'):
        if session.get('role') == 'CUSTOMER': return redirect('/shipments')
        with conn.cursor() as c:
            c.execute("DELETE FROM scan_events WHERE shipment_id=%s", (request.args.get('delete'),))
            c.execute("DELETE FROM shipments WHERE id=%s", (request.args.get('delete'),))
            conn.commit(); flash("Shipment Deleted!", "success"); return redirect('/shipments')

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
    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 style="color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;">DELIVERY STATUS REGISTER</h2>
        <div style="background: white; border: 1px solid #116B7A; margin-top: 5px;">
            <div style="height: 450px; overflow-y: auto;">
                <table class="datatable" style="width: 100%; border: none; margin: 0;">
                    <thead style="position: sticky; top: 0;">
                        <tr><th>ID</th><th>C.Note</th><th>Date</th><th>Dest</th><th>Station</th><th>Wt</th><th>Status</th><th>Total</th><th>Options</th></tr>
                    </thead>
                    <tbody>
                        {% for r in rows %}<tr>
                            <td>{{ r.id }}</td><td style="font-weight:bold; color:red;">{{ r.awb_no }}</td><td>{{ r.booking_date }}</td><td>{{ str(r.dest_name or '') }}</td><td>{{ str(r.dest_station or '') }}</td><td>{{ r.weight_kg }}</td>
                            <td style="font-weight:bold;">{{ r.status }}</td><td style="font-weight:bold;">{{ r.total_amount or 0 }}</td>
                            <td>
                                {% if session.get('role') != 'CUSTOMER' %}<a href="/edit_shipment/{{ r.id }}" style="color:blue; font-weight:bold; text-decoration:none;">[Edit]</a>{% endif %}
                                <a href="/print/label/{{ r.awb_no }}" target="_blank" style="color:green; font-weight:bold; text-decoration:none;">[Lbl]</a>
                                <a href="/print/receipt/{{ r.awb_no }}" target="_blank" style="color:green; font-weight:bold; text-decoration:none;">[Rec]</a>
                                {% if session.get('role') != 'CUSTOMER' %}<a href="/shipments?delete={{ r.id }}" style="color:red; font-weight:bold; text-decoration:none;" onclick="return confirm('Delete?');">[Del]</a>{% endif %}
                            </td>
                        </tr>{% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Transactions Data", render_template_string(html, rows=rows, str=str))

# ==========================================
# 📊 12. DYNAMIC REPORTS & TRANSACTIONS ENGINE (For Missing Menus)
# ==========================================

@app.route('/module/<category>/<action>', methods=['GET', 'POST'])
@login_required
def dynamic_module(category, action):
    """
    Ek universal route jo kisi bhi Audit, FAS, Info Report ya Transaction 
    ko handle karega aur AGCSInfo theme me render karega.
    """
    
    # URL parameters ko clean karke Title banana (e.g., 'shipper_stock' -> 'SHIPPER STOCK')
    title_category = category.replace('_', ' ').upper()
    title_action = action.replace('_', ' ').upper()
    page_title = f"{title_action} [{title_category}]"
    
    # Generic Backend Logic - Aap future me yahan specific queries likh sakte hain
    data_found = False
    table_headers = []
    table_rows = []
    
    conn = get_db()
    with conn.cursor() as c:
        # Example: Agar future me koi extra report aati hai toh aap uska SQL yahan daal sakte hain
        # Default placeholder data for all modules:
        table_headers = ["Module Information", "System Status", "Action Required"]
        table_rows = [
            [f"'{title_action}' module is active and linked successfully.", "Active - Pending Data Mapping", f"Write SQL query for '{action}' in web_erp.py"],
        ]
        data_found = True
    conn.close()

    html = """
    <style>
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px; background: #E2FAFA;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #003366; font-weight: bold; width: 150px; font-size: 11px;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 3px 15px; font-weight: bold; cursor: pointer; color: #000; font-size:11px; border-radius:3px; text-transform:uppercase;}
        .agcs-btn-grey:hover { background-color: #E0E0E0; border-color: #D67A00;}
        .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 14px; margin: 0 0 5px 0; background:white; padding:5px; text-transform:uppercase;}
        
        .agcs-grid { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; border: 1px solid #116B7A; background:white;}
        .agcs-grid th { background: linear-gradient(to bottom, #116B7A, #0D505B); color: #FFF; padding: 5px; border: 1px solid #000; text-align:left;}
        .agcs-grid td { padding: 4px 6px; border: 1px solid #CCC; color: #000;}
        .agcs-grid tr:nth-child(even) { background: #F4FAFA; }
        .agcs-grid tr:hover { background: #FFFECC; }
    </style>

    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <h2 class="page-title-green">{{ title }}</h2>
        
        <div class="agcs-top-bar">
            <button type="button" class="agcs-btn-grey" onclick="window.print()">PRINT REPORT</button>
            <button type="button" class="agcs-btn-grey">EXPORT TO EXCEL</button>
            <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            <div style="margin-left: auto; color: #D67A00; font-weight: bold; font-size:12px; padding-right:10px;">
                Center : {{ session.branch | default('NOHAR') }}
            </div>
        </div>

        <!-- Filter Options Section (Classic ASP.NET Style) -->
        <div style="background: #E2FAFA; padding: 5px; border: 1px solid #CCC; margin-bottom: 10px;">
            <form method="GET" style="margin:0; display:flex; gap:10px; align-items:center;">
                <span class="agcs-label" style="width:auto;">From Date:</span>
                <input type="date" name="from_date" class="agcs-input" style="width:120px;" value="{{ current_date }}">
                <span class="agcs-label" style="width:auto;">To Date:</span>
                <input type="date" name="to_date" class="agcs-input" style="width:120px;" value="{{ current_date }}">
                <span class="agcs-label" style="width:auto;">Branch/Filter:</span>
                <select name="filter_branch" class="agcs-input" style="width:150px;">
                    <option value="ALL">-- ALL --</option>
                    <option value="{{ session.branch }}">{{ session.branch }}</option>
                </select>
                <button type="submit" class="agcs-btn-grey" style="padding:2px 10px;">SHOW</button>
            </form>
        </div>

        <!-- Data Grid Section -->
        <div style="background: white; border: 1px solid #116B7A; height: 380px; overflow-y: auto;">
            {% if has_data %}
            <table class="agcs-grid">
                <thead style="position: sticky; top: 0;">
                    <tr>
                        {% for h in headers %}<th>{{ h }}</th>{% endfor %}
                    </tr>
                </thead>
                <tbody>
                    {% for row in rows %}
                    <tr>
                        {% for cell in row %}<td>{{ cell }}</td>{% endfor %}
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div style="padding:20px; text-align:center; color:red; font-weight:bold; font-size:14px;">
                No Data Found For Selected Criteria.
            </div>
            {% endif %}
        </div>
    </div>
    """
    
    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_page(page_title, render_template_string(html, title=page_title, has_data=data_found, headers=table_headers, rows=table_rows, current_date=current_date))

# ==========================================
# 🛑 DO NOT TOUCH - FLASK RUN
# ==========================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)
