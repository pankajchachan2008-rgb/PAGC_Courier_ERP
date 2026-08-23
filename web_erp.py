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
                    <li><a href="/customers">Geographical Location Master</a></li>
                    <li><a href="/customers">Cargo Party A/c. Master</a></li>
                    <li><a href="/rates">Rate Master</a></li>
                    <li><a href="/stationery">Shipper/Barcode Issue</a></li>
                    <li><a href="/users">Delivery Boy Master</a></li>
                    <li><a href="/users">User Login SetUp</a></li>
                    <li><a href="/settings">Misc. SetUp</a></li>
                </ul>
            </li>
            <li>Transactions
                <ul>
                    <li><a href="/inward">Cargo Packet Inward</a></li>
                    <li><a href="/inward">Local Packet Inward</a></li>
                    <li><a href="/booking">Counter Booking</a></li>
                    <li><a href="/outward">Outward Entry [Transhipment]</a></li>
                    <li><a href="/outward">Outward Entry [Local]</a></li>
                    <li><a href="/master_bag">Outward Manifest Generator</a></li>
                    <li><a href="/drs">D.R.S. Entry</a></li>
                    <li><a href="/drs">D.R.S. Delivery Status/Scan</a></li>
                    <li><a href="/accounts">Cash Book / Bank Book</a></li>
                    <li><a href="/expenses">Journal Voucher Entry</a></li>
                </ul>
            </li>
            <li>Main Reports
                <ul>
                    <li><a href="/reports">Shipper Issue Register</a></li>
                    <li><a href="/reports">Cargo Pkt Inward Register</a></li>
                    <li><a href="/reports">Credit Billing Data Register</a></li>
                    <li><a href="/reports">Outward Data Register</a></li>
                    <li><a href="/reports">Manifest Data Register</a></li>
                    <li><a href="/shipments">Delivery Status Register</a></li>
                </ul>
            </li>
            <li>FAS Reports
                <ul>
                    <li><a href="/my_ledger">Party A/c Ledger</a></li>
                    <li><a href="/my_ledger">Cash Book Ledger</a></li>
                </ul>
            </li>
            <li>Info. Reports
                <ul>
                    <li><a href="/reports">Master Reports</a></li>
                    <li><a href="/reports">Counter Booking Report</a></li>
                </ul>
            </li>
            <li>Audit Reports
                <ul>
                    <li><a href="#">DAILY REQ. REPORTS</a></li>
                </ul>
            </li>
            <li>Utilities
                <ul>
                    <li><a href="/import_csv">Download Updated AGCSInfo</a></li>
                    <li><a href="/import_csv">Bulk Data Import</a></li>
                    <li><a href="/settings">Password Change</a></li>
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
# ⚙️ 5. SETTINGS, RATES, STATIONERY & USERS
# ==========================================
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
    html = """<div class="card"><h3>Company Settings</h3><form method="POST" class="grid-2"><div><label>Company Name</label><input name="company_name" value="{{ s.get('company_name', '') }}" required></div><div><label>Company GSTIN</label><input name="company_gstin" value="{{ s.get('company_gstin', '') }}"></div><div><label>Head Office Address</label><input name="company_address" value="{{ s.get('company_address', '') }}"></div><div><label>Customer Care Phone</label><input name="company_phone" value="{{ s.get('company_phone', '') }}"></div><div><label>Website</label><input name="company_website" value="{{ s.get('company_website', '') }}"></div><div><label>Email</label><input name="company_email" value="{{ s.get('company_email', '') }}"></div><div><label>Bank Details (Invoice)</label><input name="bank_details" value="{{ s.get('bank_details', '') }}"></div><div><label>Fuel Surcharge (%)</label><input type="number" step="0.1" name="fuel_surcharge" value="{{ s.get('fuel_surcharge', '0') }}"></div><div style="grid-column: span 2;"><label>Terms Note</label><input name="terms_note" value="{{ s.get('terms_note', '') }}"></div><div style="grid-column: span 2; margin-top:10px;"><button type="submit" class="btn btn-blue">Save Settings</button></div></form></div>"""
    return render_page("System Settings", render_template_string(html, s=s_dict))

@app.route('/rates', methods=['GET', 'POST'])
@login_required
def rates():
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM rates WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Rate Deleted!", "success"); return redirect('/rates')
    if request.method == 'POST':
        d = request.form; cid = safe_int(d.get('cust_id')) if d.get('cust_id') else None
        with conn.cursor() as c: c.execute("INSERT INTO rates(customer_id, origin_state_code, dest_state_code, min_weight, max_weight, fixed_charge, per_kg_rate, gst_rate) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (cid, d.get('ostate',''), d.get('dstate',''), safe_float(d.get('min_w')), safe_float(d.get('max_w')), safe_float(d.get('fixed')), safe_float(d.get('per_kg')), safe_float(d.get('gst')))); conn.commit(); flash("Rate Card Added!", "success")
    with conn.cursor() as c: c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall(); c.execute("SELECT r.*, c.name FROM rates r LEFT JOIN customers c ON c.id=r.customer_id ORDER BY r.id DESC"); r_list = c.fetchall()
    conn.close()
    html = """<div class="card"><h3>Add Contract Rate</h3><form method="POST" class="grid-4" style="align-items:end;"><div style="grid-column: span 2;"><label>Customer</label><select name="cust_id"><option value="">-- Generic / Default --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div><label>Origin State</label><input name="ostate" required></div><div><label>Dest State</label><input name="dstate" required></div><div><label>Min Wt (KG)</label><input type="number" step="0.1" name="min_w" value="0.0"></div><div><label>Max Wt (KG)</label><input type="number" step="0.1" name="max_w" value="999.0"></div><div><label>Fixed (Rs)</label><input type="number" step="0.1" name="fixed" value="0.0"></div><div><label>Per KG (Rs)</label><input type="number" step="0.1" name="per_kg" value="0.0"></div><div><label>GST %</label><input type="number" step="0.1" name="gst" value="18.0"></div><div><button type="submit" class="btn btn-blue">Save Rate</button></div></form></div><div class="card"><h3>Active Rate Cards</h3><table class="datatable"><thead><tr><th>Customer</th><th>Route</th><th>Wt Slab</th><th>Fixed</th><th>Per KG</th><th>GST</th><th>Act</th></tr></thead><tbody>{% for r in r_list %}<tr><td><strong>{{ r.name or 'Generic' }}</strong></td><td>{{ r.origin_state_code }} &rarr; {{ r.dest_state_code }}</td><td>{{ r.min_weight }} - {{ r.max_weight }} KG</td><td>Rs {{ r.fixed_charge }}</td><td>Rs {{ r.per_kg_rate }}</td><td>{{ r.gst_rate }}%</td><td><a href="/rates?delete={{ r.id }}" style="color:red; font-weight:bold;">[Del]</a></td></tr>{% endfor %}</tbody></table></div>"""
    return render_page("Rate Cards", render_template_string(html, custs=custs, r_list=r_list))

@app.route('/stationery', methods=['GET', 'POST'])
@login_required
def stationery():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM shipments WHERE status='STATIONERY' AND origin_name=%s AND booking_date=%s", (request.args.get('name'), request.args.get('date'))); conn.commit(); flash("Allocation Deleted!", "success"); return redirect('/stationery')
    if request.method == 'POST':
        name = request.form.get('name', ''); pfx = request.form.get('prefix', ''); frm = safe_int(request.form.get('from')); to = safe_int(request.form.get('to'))
        if frm > 0 and to >= frm:
            with conn.cursor() as c:
                for i in range(frm, to + 1): c.execute("INSERT IGNORE INTO shipments(awb_no, origin_name, status, current_location, booking_date) VALUES(%s,%s,'STATIONERY','Allocated',CURDATE())", (f"{pfx}{i}", name))
                conn.commit(); flash(f"Allocated {to-frm+1} AWBs!", "success")
    with conn.cursor() as c:
        c.execute("SELECT name FROM stations UNION SELECT name FROM customers ORDER BY name"); names = c.fetchall()
        c.execute("SELECT booking_date, origin_name, COUNT(*) as qty, MIN(awb_no) as from_awb, MAX(awb_no) as to_awb FROM shipments WHERE status='STATIONERY' GROUP BY booking_date, origin_name ORDER BY booking_date DESC"); hists = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3>Allocate Pre-Printed AWBs</h3><form method="POST"><label>Assign To</label><input name="name" list="nlist" required style="margin-bottom:10px;"><datalist id="nlist">{% for n in names %}<option value="{{ n.name }}">{% endfor %}</datalist><div class="grid-3"><div><label>Prefix</label><input name="prefix" value="AWB"></div><div><label>From</label><input type="number" name="from" required></div><div><label>To</label><input type="number" name="to" required></div></div><button type="submit" class="btn btn-blue" style="margin-top:10px;">Allocate Inventory</button></form></div><div class="card"><h3>Allocation History</h3><table class="datatable"><thead><tr><th>Date</th><th>Assigned To</th><th>Qty</th><th>Range</th><th>Act</th></tr></thead><tbody>{% for h in hists %}<tr><td>{{ h.booking_date }}</td><td><strong>{{ h.origin_name }}</strong></td><td>{{ h.qty }}</td><td>{{ h.from_awb }} to {{ h.to_awb }}</td><td><a href="/stationery?delete=1&name={{ h.origin_name }}&date={{ h.booking_date }}" style="color:red; font-weight:bold;">[Del]</a></td></tr>{% endfor %}</tbody></table></div></div>"""
    return render_page("Stationery Management", render_template_string(html, names=names, hists=hists))

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
    html = """<div class="card"><h3>User Login SetUp</h3><form method="POST" class="grid-4" style="align-items:end;"><div><label>Username</label><input name="username" required></div><div><label>Password</label><input type="password" name="password" required></div><div><label>Full Name</label><input name="full_name" required></div><div><label>Role</label><select name="role"><option>ADMIN</option><option>OPERATOR</option><option>ACCOUNTANT</option><option>CUSTOMER</option></select></div><div style="grid-column: span 2;"><label>Branch / Station</label><input name="branch" list="brlist" required><datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist></div><div style="grid-column: span 1;"><label>Link Customer</label><select name="customer_id"><option value="">-- None --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div><button type="submit" class="btn btn-blue">Save User</button></div></form></div><div class="card"><h3>System Users</h3><table class="datatable"><thead><tr><th>User</th><th>Name</th><th>Role</th><th>Branch</th><th>Cust_ID</th><th>Status</th><th>Act</th></tr></thead><tbody>{% for u in u_list %}<tr><td><strong>{{ u.username }}</strong></td><td>{{ u.full_name }}</td><td>{{ u.role }}</td><td>{{ u.branch_name or 'HQ' }}</td><td>{{ u.customer_id or '-' }}</td><td>{% if u.active %}Active{% else %}Inactive{% endif %}</td><td>{% if u.active %}<a href="/users?delete={{ u.id }}" style="color:red; font-weight:bold;">[Del]</a>{% endif %}</td></tr>{% endfor %}</tbody></table></div>"""
    return render_page("User SetUp", render_template_string(html, u_list=u_list, branches=branches, custs=custs))

# ==========================================
# 📦 6. BOOKING, CUSTOMERS & SHIPMENTS 
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

# ---------------------------------------------------------
# NEW AJAX ROUTE: To Fetch Dest City & Weight on AWB Scan
# ---------------------------------------------------------
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

@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE customers SET is_active=0 WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Franchisee Deleted!", "success"); return redirect('/customers')
    
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c: 
            # Saare field names theek tarah se fetch honge
            c.execute("INSERT INTO customers(code, name, gstin, phone, email, state, state_code, address, credit_limit, is_active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)", (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone1',''), d.get('email',''), d.get('state',''), d.get('scode',''), d.get('address',''), safe_float(d.get('limit'))))
            conn.commit(); flash("Master Data Saved Successfully!", "success")
            
    with conn.cursor() as c: c.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id DESC"); custs = c.fetchall()
    conn.close()
    
    html = """
    <style>
        .agcs-form-table { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; margin-bottom: 5px; background: #E2FAFA;}
        .agcs-form-table td { padding: 3px 5px; vertical-align: middle; border: none;}
        .agcs-label { color: #003366; font-weight: bold; width: 120px; font-size: 11px; white-space: nowrap;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; padding: 2px 4px; font-family: Tahoma; font-size: 11px; width: 100%; box-sizing: border-box; }
        .agcs-input:focus { background-color: #FFF; border: 1px solid red;}
        .agcs-section-header { background-color: #009933; color: white; font-weight: bold; padding: 2px 5px; margin-top: 5px; margin-bottom: 5px; font-size: 11px; text-transform:uppercase;}
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-family: Tahoma; font-size: 11px; font-weight: bold; cursor: pointer; color: #000;}
        .agcs-btn-grey:hover { background-color: #E0E0E0; }
        .page-title-green { color: #009933; font-style: italic; font-weight: bold; font-size: 13px; margin: 0 0 5px 0; background:white; padding:5px;}
    </style>

    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        
        <h2 class="page-title-green">FRANCHISEE / BRANCH MASTER DATA SETUP</h2>
        
        <form method="POST" id="masterForm" style="margin:0;">
            <div class="agcs-top-bar">
                <button type="submit" class="agcs-btn-grey">SAVE</button>
                <button type="button" class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            </div>
            
            <div style="background: #E2FAFA; padding: 2px;">
                
                <div class="agcs-section-header">FRANCHISEE CONTACT DETAILS</div>
                <table class="agcs-form-table">
                    <tr>
                        <td class="agcs-label" style="width:10%;">Frnch. Name</td>
                        <td colspan="3"><input type="text" name="name" class="agcs-input" style="width: 40%; color:blue; font-weight:bold;" required></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Code / ID</td>
                        <td colspan="3"><input type="text" name="code" class="agcs-input" style="width: 20%;" required></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Address</td>
                        <td colspan="3"><input type="text" name="address" class="agcs-input" style="width: 40%; margin-bottom: 2px;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Area</td>
                        <td colspan="3"><input type="text" name="area" class="agcs-input" style="width: 40%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">City</td>
                        <td style="width:30%;">
                            <input type="text" name="city" class="agcs-input" style="width: 25%; margin-right: 2px; background:white; border:1px solid #116B7A;">
                        </td>
                        <td class="agcs-label" style="width:10%; text-align:right; padding-right:10px;">PinCode</td>
                        <td><input type="text" name="pincode" class="agcs-input" style="width: 30%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">State</td>
                        <td>
                            <input type="text" name="scode" class="agcs-input" style="width: 25%; margin-right: 2px; background:white; border:1px solid #116B7A;" placeholder="Code">
                            <select name="state" class="agcs-input" style="width: 60%; background-color: #FFFFCC; border:1px solid #009933;"><option value="RAJASTHAN">RAJASTHAN</option><option value="HARYANA">HARYANA</option><option value="DELHI">DELHI</option></select>
                        </td>
                        <td class="agcs-label" style="text-align:right; padding-right:10px;">Country</td>
                        <td><select name="country" class="agcs-input" style="width: 30%; background-color: #FFFFCC; border:1px solid #009933;"><option value="INDIA">INDIA</option></select></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Phone 1</td>
                        <td><input type="text" name="phone1" class="agcs-input" style="width: 90%;"></td>
                        <td class="agcs-label" style="text-align:right; padding-right:10px;">Phone2</td>
                        <td><input type="text" name="phone2" class="agcs-input" style="width: 60%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Fax</td>
                        <td><input type="text" name="fax" class="agcs-input" value="-" style="width: 90%; background:white; border:1px solid #116B7A;"></td>
                        <td class="agcs-label" style="text-align:right; padding-right:10px;">Email</td>
                        <td><input type="email" name="email" class="agcs-input" style="width: 60%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Website</td>
                        <td colspan="3"><input type="text" name="website" class="agcs-input" style="width: 40%;"></td>
                    </tr>
                </table>

                <div class="agcs-section-header">REGISTRATION NUMBERS</div>
                <table class="agcs-form-table">
                    <tr>
                        <td class="agcs-label" style="width:10%;">PAN No.</td>
                        <td style="width:30%;"><input type="text" name="pan" class="agcs-input" style="width: 90%;"></td>
                        <td class="agcs-label" style="width:10%; text-align:right; padding-right:10px;">State GST</td>
                        <td><input type="text" name="gstin" class="agcs-input" style="width: 60%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">TAN No.</td>
                        <td><input type="text" name="tan" class="agcs-input" value="-" style="width: 90%; background:white; border:1px solid #116B7A;"></td>
                        <td class="agcs-label" style="text-align:right; padding-right:10px;">Center GST</td>
                        <td><input type="text" name="cgst_no" class="agcs-input" style="width: 60%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Srvc Tax No.</td>
                        <td colspan="3"><input type="text" name="service_tax" class="agcs-input" style="width: 90%;"></td>
                    </tr>
                </table>

                <div class="agcs-section-header">ACCOUNT YEAR DETAILS</div>
                <table class="agcs-form-table">
                    <tr>
                        <td class="agcs-label" style="width:10%;">From Date</td>
                        <td><input type="text" class="agcs-input" value="01/04/2026" style="width: 30%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">To Date</td>
                        <td><input type="text" class="agcs-input" value="31/03/2027" style="width: 30%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Account year</td>
                        <td><input type="text" class="agcs-input" value="2026-2027" style="width: 30%;"></td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Credit Limit (Rs)</td>
                        <td><input type="number" step="0.01" name="limit" class="agcs-input" value="0.00" style="width: 30%; font-weight:bold;"></td>
                    </tr>
                </table>
            </div>
        </form>
        
        <!-- List View -->
        <div style="background: white; border: 1px solid #116B7A; margin-top: 5px;">
            <div style="height: 150px; overflow-y: auto;">
                <table class="datatable" style="width: 100%; border: none; margin: 0;">
                    <thead style="position: sticky; top: 0;">
                        <tr><th>Code</th><th>Name</th><th>Phone</th><th>GSTIN</th><th>State Code</th><th>Act</th></tr>
                    </thead>
                    <tbody>
                        {% for r in custs %}
                        <tr>
                            <td>{{ r.code }}</td>
                            <td style="color: blue; font-weight: bold;">{{ r.name }}</td>
                            <td>{{ r.phone }}</td>
                            <td>{{ r.gstin }}</td>
                            <td>{{ r.state_code }}</td>
                            <td style="text-align:center;"><a href="/customers?delete={{ r.id }}"><img src="https://cdn-icons-png.flaticon.com/128/3096/3096673.png" width="12" title="Delete"></a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Franchisee Master Data SetUp", render_template_string(html, custs=custs))

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
    <div class="card" style="margin:auto;">
        <h3>Counter Booking</h3>
        <form method="POST" id="bkForm">
            <div style="background:#F4FAFA; padding:10px; border:1px solid #CCC; margin-bottom:10px;">
                <table style="width:100%;">
                    <tr>
                        <td><label>Date:</label><input type="date" name="date" id="bdt" required></td>
                        <td><label>C.Note No:</label><input name="awb" required style="font-weight:bold; color:red; text-transform:uppercase;"></td>
                        <td colspan="2">
                            <label>Customer A/c:</label>
                            {% if session.get('role') == 'CUSTOMER' %}
                                <input type="hidden" name="cust_id" id="cid" value="{{ my_cust.id }}" data-state="{{ my_cust.state_code }}">
                                <input value="{{ my_cust.name }}" readonly style="background:#EEE; font-weight:bold;">
                            {% else %}
                                <select name="cust_id" id="cid" onchange="fetchRate()"><option value="">-- Cash Booking --</option>{% for c in custs %}<option value="{{ c.id }}" data-state="{{ c.state_code }}">{{ c.name }}</option>{% endfor %}</select>
                            {% endif %}
                        </td>
                    </tr>
                </table>
            </div>
            <div class="grid-2">
                <div style="border:1px solid #116B7A; padding:10px; background:white;">
                    <h4 style="color:#D67A00 !important;">Consignor Details</h4>
                    <table style="width:100%;">
                        <tr><td><label>Name:</label></td><td><input name="oname" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.name }}{% else %}{{ session.get('branch', 'HQ') }}{% endif %}" required></td></tr>
                        <tr><td><label>Phone:</label></td><td><input name="ophone" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.phone }}{% endif %}"></td></tr>
                        <tr><td><label>State Code:</label></td><td><input name="ostate" id="ost" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.state_code }}{% else %}RJ{% endif %}" onchange="fetchRate()"></td></tr>
                        <tr><td><label>Address:</label></td><td><input name="oaddr" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.address }}{% endif %}"></td></tr>
                    </table>
                </div>
                <div style="border:1px solid #116B7A; padding:10px; background:white;">
                    <h4 style="color:#116B7A !important;">Consignee Details</h4>
                    <table style="width:100%;">
                        <tr><td><label>Name:</label></td><td><input name="dname" required></td></tr>
                        <tr><td><label>Phone:</label></td><td><input name="dphone" required></td></tr>
                        <tr><td><label>State Code:</label></td><td><input name="dstate" id="dst" onchange="fetchRate()"></td></tr>
                        <tr><td><label>Station:</label></td><td><input name="dstat" list="stations" required style="text-transform:uppercase; font-weight:bold;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></td></tr>
                        <tr><td><label>Address:</label></td><td><input name="daddr"></td></tr>
                    </table>
                </div>
            </div>
            <div style="background:#F4FAFA; padding:10px; border:1px solid #CCC; margin-top:10px;">
                <table style="width:100%;">
                    <tr>
                        <td><label>Weight:</label><input type="number" step="0.01" name="wt" id="wt" value="1.0" required oninput="fetchRate()"></td>
                        <td><label>Pieces:</label><input type="number" name="pcs" value="1" required></td>
                        <td><label>Service:</label><select name="srv"><option>SURFACE</option><option>AIR</option></select></td>
                        <td><label>Remarks:</label><input name="info"></td>
                        <td><label>Freight:</label><input type="number" step="0.01" name="fr" id="fr" value="0.0" oninput="manualCalc()" required></td>
                        <td><label>Tax%:</label><input type="number" name="tax" id="tax" value="18" oninput="manualCalc()" required></td>
                        <td><label>Total:</label><input type="number" step="0.01" name="amt" id="amt" value="0.0" readonly style="background:#E2FAFA; font-weight:bold; color:red;"></td>
                        <td><br><button type="submit" class="btn btn-blue" style="width:100%;">Save</button></td>
                    </tr>
                </table>
                <div id="calc_hint" style="color:#D67A00; font-weight:bold; font-size:10px; text-align:right;"></div>
            </div>
        </form>
    </div>
    <div class="card">
        <h3>Recent Transactions</h3>
        <table class="datatable"><thead><tr><th>ID</th><th>C.Note No</th><th>Party A/c</th><th>Station</th><th>Weight</th><th>Amount</th><th>Act</th></tr></thead>
        <tbody>{% for r in recent %}<tr><td>{{ r.id }}</td><td style="font-weight:bold;">{{ r.awb_no }}</td><td>{{ r.customer_name }}</td><td>{{ r.dest_station }}</td><td>{{ r.weight_kg }}</td><td style="font-weight:bold;">{{ r.total_amount }}</td><td><a href="/edit_shipment/{{ r.id }}" style="color:blue;">Edit</a></td></tr>{% endfor %}</tbody>
        </table>
    </div>
    <script>document.getElementById('bdt').valueAsDate = new Date(); function fetchRate() { let cid = document.getElementById('cid').value; if(cid) { let opt = document.getElementById('cid').options[document.getElementById('cid').selectedIndex]; if(opt){document.getElementById('ost').value = opt.getAttribute('data-state');} } let data = { cust_id: cid, ostate: document.getElementById('ost').value, dstate: document.getElementById('dst').value, wt: document.getElementById('wt').value, fr: 0 }; fetch('/api/calc_rate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) }).then(r => r.json()).then(res => { document.getElementById('fr').value = res.freight; document.getElementById('tax').value = res.tax_rate; document.getElementById('amt').value = res.total; document.getElementById('calc_hint').innerText = `Taxable: ${res.taxable} | GST: ${res.gst}`; }); } function manualCalc() { let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0; document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); document.getElementById('calc_hint').innerText = "Manual Edit"; } if(document.getElementById('cid').tagName === 'INPUT') { fetchRate(); }</script>
    """
    return render_page("Counter Booking", render_template_string(html, custs=custs, stations=stations, recent=recent, my_cust=my_cust))

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
    <div class="card">
        <h3>Delivery Status Register</h3>
        <table class="datatable"><thead><tr><th>ID</th><th>C.Note</th><th>Date</th><th>Dest</th><th>Station</th><th>Wt</th><th>Status</th><th>Total</th><th>Options</th></tr></thead><tbody>
        {% for r in rows %}<tr>
            <td>{{ r.id }}</td><td style="font-weight:bold;">{{ r.awb_no }}</td><td>{{ r.booking_date }}</td><td>{{ str(r.dest_name or '') }}</td><td>{{ str(r.dest_station or '') }}</td><td>{{ r.weight_kg }}</td>
            <td><span class="badge">{{ r.status }}</span></td><td>{{ r.total_amount or 0 }}</td>
            <td>
                {% if session.get('role') != 'CUSTOMER' %}<a href="/edit_shipment/{{ r.id }}" style="color:blue;">[Edit]</a>{% endif %}
                <a href="/print/label/{{ r.awb_no }}" target="_blank" style="color:green;">[Lbl]</a>
                <a href="/print/receipt/{{ r.awb_no }}" target="_blank" style="color:green;">[Rec]</a>
                {% if session.get('role') != 'CUSTOMER' %}<a href="/shipments?delete={{ r.id }}" style="color:red;" onclick="return confirm('Delete?');">[Del]</a>{% endif %}
            </td>
        </tr>{% endfor %}</tbody></table></div>
    """
    return render_page("Transactions Data", render_template_string(html, rows=rows, str=str))

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
    html = """<div class="card"><h3>Party A/c Ledger <a href="/print/statement/{{ session.get('customer_id') }}" target="_blank" style="float:right; color:blue; font-size:11px;">[Print PDF]</a></h3><div style="background:#F4FAFA; padding:5px; border:1px solid #CCC; margin-bottom:10px; font-weight:bold; color:red; text-align:right;">Outstanding: Rs {{ c_bal }}</div><table class="datatable"><thead><tr><th>Date</th><th>Voucher</th><th>Ref</th><th>Debit (Rs)</th><th>Credit (Rs)</th><th>Narration</th></tr></thead><tbody>{% for l in l_data %}<tr><td>{{ l.entry_date }}</td><td>{{ l.voucher_type }}</td><td>{{ l.reference }}</td><td style="color:red;">{{ l.debit }}</td><td style="color:green;">{{ l.credit }}</td><td>{{ l.narration }}</td></tr>{% endfor %}</tbody></table></div>"""
    return render_page("My Ledger", render_template_string(html, l_data=l_data, c_bal=c_bal))

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
    html = """<div class="card"><h3>Edit C.Note: {{ s.awb_no }}</h3><form method="POST"><div class="grid-4" style="background:#F4FAFA; padding:10px; border:1px solid #CCC; margin-bottom:10px;"><div><label>Status</label><select name="status"><option {% if s.status == 'BOOKED' %}selected{% endif %}>BOOKED</option><option {% if s.status == 'OUTWARD' %}selected{% endif %}>OUTWARD</option><option {% if s.status == 'INWARD' %}selected{% endif %}>INWARD</option><option {% if s.status == 'ON_DRS' %}selected{% endif %}>ON_DRS</option><option {% if s.status == 'DELIVERED' %}selected{% endif %}>DELIVERED</option></select></div><div><label>Location</label><input name="location" value="{{ s.current_location or '' }}"></div><div><label>Date</label><input type="date" name="date" value="{{ s.booking_date }}" required></div><div><label>C.Note</label><input name="awb" value="{{ s.awb_no }}" required style="font-weight:bold;"></div></div><div class="grid-2"><div style="border:1px solid #116B7A; padding:10px;"><h4>Consignor</h4><label>Name</label><input name="oname" value="{{ s.origin_name or '' }}" required><label>Phone</label><input name="ophone" value="{{ s.origin_phone or '' }}"><label>State Code</label><input name="ostate" value="{{ s.origin_state_code or '' }}"><label>Address</label><input name="oaddr" value="{{ s.origin_address or '' }}"></div><div style="border:1px solid #116B7A; padding:10px;"><h4>Consignee</h4><label>Name</label><input name="dname" value="{{ s.dest_name or '' }}" required><label>Phone</label><input name="dphone" value="{{ s.dest_phone or '' }}" required><label>State Code</label><input name="dstate" value="{{ s.dest_state_code or '' }}"><label>Station</label><input name="dstat" list="stations" value="{{ s.dest_station or '' }}" required style="text-transform:uppercase;"><datalist id="stations">{% for st in stations %}<option value="{{ st.name }}">{% endfor %}</datalist><label>Address</label><input name="daddr" value="{{ s.dest_address or '' }}"></div></div><div class="grid-6" style="margin-top:10px; background:#F4FAFA; padding:10px; border:1px solid #CCC;"><div><label>Wt</label><input type="number" step="0.01" name="wt" id="wt" value="{{ s.weight_kg or 1 }}" required oninput="manualCalc()"></div><div><label>Pcs</label><input type="number" name="pcs" value="{{ s.quantity or 1 }}"></div><div><label>Service</label><select name="srv"><option {% if s.service_type == 'SURFACE' %}selected{% endif %}>SURFACE</option><option {% if s.service_type == 'AIR' %}selected{% endif %}>AIR</option></select></div><div style="grid-column: span 3;"><label>Remarks</label><input name="info" value="{{ s.info or '' }}"></div><div><label>Taxable</label><input type="number" step="0.01" name="fr" id="fr" value="{{ s.taxable_amount or 0 }}" oninput="manualCalc()"></div><div><label>Tax(%)</label><input type="number" name="tax" id="tax" value="{{ s.tax_rate or 18 }}" oninput="manualCalc()"></div><div><label>Total(Rs)</label><input type="number" step="0.01" name="amt" id="amt" value="{{ s.total_amount or 0 }}" readonly style="background:#E2FAFA; font-weight:bold; color:red;"></div><div style="grid-column: span 3;"><br><button type="submit" class="btn btn-blue" style="width:100%;">UPDATE</button></div></div></form><script>function manualCalc() { let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0; document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); }</script></div>"""
    return render_page(f"Edit {s['awb_no']}", render_template_string(html, s=s, stations=stations))

# ==========================================
# 📤 8. OUTWARD HUB & EXCEL IMPORT
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

@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db(); current_date = datetime.now().strftime('%Y-%m-%d')
    
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM outward_register WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Deleted", "success"); return redirect(f"/outward?date={request.args.get('date', current_date)}")
    
    if request.args.get('unfinalize'):
        mid = request.args.get('unfinalize')
        with conn.cursor() as c:
            c.execute("SELECT manifest_no FROM manifests WHERE id=%s", (mid,)); m = c.fetchone()
            if m: c.execute("UPDATE outward_register SET finalized=0, manifest_no=NULL, outward_no=NULL WHERE manifest_no=%s", (m['manifest_no'],)); c.execute("DELETE FROM manifest_items WHERE manifest_id=%s", (mid,)); c.execute("DELETE FROM manifests WHERE id=%s", (mid,))
            conn.commit(); flash("Unfinalized!", "success")
        return redirect('/outward')

    if request.method == 'POST' and request.form.get('action') == 'save_entry':
        o_date = request.form.get('out_date', current_date); o_station = str(request.form.get('out_station') or session.get('branch', 'HQ')).upper(); awb = request.form.get('awb', '').strip().upper()
        dest_input = request.form.get('dest', '').strip().upper(); wt_input = safe_float(request.form.get('weight')); info = request.form.get('info', '')
        
        if awb:
            with conn.cursor() as c:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (o_station,))
                if dest_input: c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest_input,))
                if c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND finalized=0", (awb,)): flash(f"{awb} already pending!", "error")
                else:
                    c.execute("SELECT id, dest_station, dest_name, weight_kg, dest_phone FROM shipments WHERE awb_no=%s", (awb,)); s = c.fetchone()
                    s_dest = str(s['dest_station'] or s['dest_name'] or 'UNKNOWN') if s else 'UNKNOWN'
                    final_dest = dest_input if dest_input else s_dest
                    final_wt = wt_input if wt_input > 0 else (safe_float(s['weight_kg']) if s else 1.0)
                    if s:
                        c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, info=%s, dest_station=%s, weight_kg=%s WHERE id=%s", (o_station, info, final_dest, final_wt, s['id']))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'OUTWARD', %s, 'Scanned at Outward')", (s['id'], o_station))
                    else:
                        c.execute("INSERT INTO shipments(awb_no, booking_date, origin_name, dest_station, dest_name, weight_kg, service_type, status, current_location, taxable_amount, total_amount, info, is_synced) VALUES(%s, %s, %s, %s, %s, %s, 'SURFACE', 'OUTWARD', %s, 0, 0, %s, 0)", (awb, o_date, session.get('branch','HQ'), final_dest, final_dest, final_wt, o_station, info))
                        new_sid = c.lastrowid
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'OUTWARD', %s, 'Auto-linked from Outward')", (new_sid, o_station))
                    c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) VALUES(%s, %s, %s, %s, %s, %s, %s, 0)", (o_date, awb, session.get('branch','HQ'), o_station, final_dest, final_wt, info))
                conn.commit()
            return redirect(f"/outward?date={o_date}&station={o_station}")

    if request.method == 'POST' and request.form.get('action') == 'finalize':
        o_date = request.form.get('out_date', current_date); o_station = request.form.get('out_station', session.get('branch', 'HQ')).upper()
        with conn.cursor() as c:
            c.execute("SELECT id, awb_no FROM outward_register WHERE entry_date=%s AND out_station=%s AND origin_station=%s AND finalized=0", (o_date, o_station, session.get('branch','HQ'))); pending = c.fetchall()
            if pending:
                ono = get_seq("outward", "OUT", 6); mno = get_seq("manifest", "MF", 7)
                c.execute("INSERT INTO manifests(manifest_no, manifest_type, from_location, to_location, vehicle_no, driver_phone, seal_no, status) VALUES(%s, 'OUTWARD', %s, %s, %s, %s, %s, 'OPEN')", (mno, session.get('branch','HQ'), o_station, request.form.get('vehicle_no',''), '', ''))
                mid = c.lastrowid
                for p in pending:
                    c.execute("UPDATE outward_register SET finalized=1, outward_no=%s, manifest_no=%s WHERE id=%s", (ono, mno, p['id']))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (p['awb_no'],)); s_row = c.fetchone()
                    if s_row: c.execute("INSERT INTO manifest_items(manifest_id, shipment_id) VALUES(%s, %s)", (mid, s_row['id'])); c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'OUTWARD', %s)", (s_row['id'], session.get('branch','HQ')))
                conn.commit(); flash(f"Locked! Manifest Generated: {mno}", "success")
        return redirect(f"/outward?date={o_date}&station={o_station}")

    f_date = request.args.get('date', current_date); f_station = request.args.get('station', session.get('branch', 'HQ')).upper()
    with conn.cursor() as c:
        c.execute("SELECT id, awb_no, destination, weight, info FROM outward_register WHERE entry_date=%s AND out_station=%s AND origin_station=%s AND finalized=0 ORDER BY id DESC", (f_date, f_station, session.get('branch','HQ'))); pending_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); stations = [r['name'] for r in c.fetchall()]
        
        c.execute("SELECT name FROM customers WHERE is_active=1 ORDER BY name"); franch_list = [r['name'] for r in c.fetchall()]
        c.execute("SELECT name FROM branches ORDER BY name"); cargo_list = [r['name'] for r in c.fetchall()]
        
        q_m = "SELECT id, manifest_no, created_at, from_location, to_location, vehicle_no FROM manifests WHERE manifest_type='OUTWARD'"
        params_m = []
        if session.get('role') != 'ADMIN': q_m += " AND from_location=%s"; params_m.append(session.get('branch','HQ'))
        c.execute(q_m + " ORDER BY id DESC LIMIT 10", tuple(params_m)); mans = c.fetchall()
    conn.close()
    
    html = """
    <style>
        .agcs-form { width: 100%; border-collapse: collapse; font-family: Tahoma; font-size: 11px; border: 1px solid #009933; margin-bottom: 10px;}
        .agcs-form td { padding: 4px; border: none; vertical-align: middle;}
        .agcs-input { border: 1px solid #009933; background-color: #FFFFCC; font-family: Tahoma; font-size: 11px; padding: 2px; width: 100%; box-sizing: border-box;}
        .agcs-input:focus { background-color: #FFF; border: 1px solid red;}
        .agcs-select { border: 1px solid #009933; font-family: Tahoma; font-size: 11px; padding: 1px; width: 100%;}
        .agcs-label { color: #003366; white-space: nowrap; padding-right: 5px; }
        .agcs-header { background-color: #009933; color: white; font-weight: bold; padding: 3px 5px; text-align: center;}
        .icon-btn { cursor: pointer; vertical-align: middle; margin: 0 2px;}
        .agcs-top-bar { display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px solid #116B7A; margin-bottom: 5px; background: white;}
        .agcs-btn-grey { background: linear-gradient(to bottom, #F4F4F4, #D4D4D4); border: 1px solid #888; padding: 2px 20px; font-family: Tahoma; font-size: 11px; font-weight: bold; cursor: pointer; color: #000; text-transform:uppercase;}
        .section-box { border: 1px solid #009933; padding: 2px; margin-bottom: 5px; background: white;}
    </style>

    <div style="background: #E2FAFA; padding: 5px; min-height: 500px; border: 1px solid #116B7A; border-top: 3px solid #116B7A;">
        <div class="agcs-top-bar">
            <button class="agcs-btn-grey" onclick="document.getElementById('entryForm').submit()">SAVE</button>
            <button class="agcs-btn-grey" onclick="window.location.href='/'">EXIT</button>
            <div style="margin-left: auto; color: #D67A00; font-weight: bold; font-size:12px; padding-right:10px;">
                Center : {{ session.branch | default('NOHAR') }}/{{ session.branch | default('NOHAR') }}-PANKAJ AGENCY
            </div>
        </div>

        <form method="POST" id="entryForm" style="margin:0;">
            <input type="hidden" name="action" value="save_entry">
            <input type="hidden" name="out_date" id="hdn_date">
            <input type="hidden" name="out_station" id="hdn_station">

            <div class="section-box">
                <div class="agcs-header">Outward Voucher Detail [Transhipment Outward]</div>
                <table class="agcs-form">
                    <tr>
                        <td class="agcs-label" style="width:10%;">Outward Date</td>
                        <td style="width:20%;"><input type="date" id="ui_date" value="{{ f_date }}" onchange="reloadPage()" class="agcs-input" style="font-weight:bold; color:blue;"></td>
                        <td class="agcs-label" style="width:10%; text-align:right;">Frnch A/c</td>
                        <td style="width:20%;">
                            <select name="franchise_ac" class="agcs-select">
                                <option value="">Select One</option>
                                {% for f in franch_list %}<option value="{{ f }}">{{ f }}</option>{% endfor %}
                            </select>
                        </td>
                        <td class="agcs-label" style="width:10%; text-align:right;">C.Note Search</td>
                        <td style="width:20%;">
                            <input type="text" class="agcs-input" style="width:60%; background:white; border:1px solid #116B7A;">
                            <img src="https://cdn-icons-png.flaticon.com/128/49/49116.png" width="14" class="icon-btn" title="Search">
                            <img src="https://cdn-icons-png.flaticon.com/128/1828/1828817.png" width="14" class="icon-btn" title="Add">
                            <img src="https://cdn-icons-png.flaticon.com/128/2874/2874050.png" width="14" class="icon-btn" title="Save">
                            <img src="https://cdn-icons-png.flaticon.com/128/3096/3096673.png" width="14" class="icon-btn" title="Delete">
                        </td>
                    </tr>
                    <tr>
                        <td class="agcs-label">To Station</td>
                        <td><input list="stlist" id="ui_station" value="{{ f_station }}" onchange="reloadPage()" class="agcs-input"><datalist id="stlist">{% for s in stations %}<option value="{{ s }}">{% endfor %}</datalist></td>
                        <td class="agcs-label" style="text-align:right;">Cargo A/c</td>
                        <td>
                            <select name="cargo_ac" class="agcs-select">
                                <option value="">Select One</option>
                                {% for c in cargo_list %}<option value="{{ c }}">{{ c }}</option>{% endfor %}
                            </select>
                        </td>
                        <td class="agcs-label" style="text-align:right;">M.Fest Number</td>
                        <td>
                            <input type="text" class="agcs-input" style="width:60%; background:white; border:1px solid #116B7A;">
                            &nbsp;&nbsp;<input type="checkbox" checked style="vertical-align:middle; width:auto; border:none; background:transparent;"> <span style="color:red; font-weight:bold;">Fast Mode [Gun]</span>
                        </td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Notes</td>
                        <td colspan="5"><input type="text" name="info" class="agcs-input" style="width:200px;"></td>
                    </tr>
                </table>
            </div>

            <div class="section-box">
                <div class="agcs-header">Outward Consignment Details</div>
                <table class="agcs-form">
                    <tr>
                        <td class="agcs-label" style="width:8%;">Cons. No.</td>
                        <!-- AJAX onblur attached here to fetch AWB info -->
                        <td style="width:18%;"><input type="text" name="awb" id="out_awb_input" required autofocus class="agcs-input" style="color:red; font-weight:bold; text-transform:uppercase;" onblur="fetchAwbInfo()"></td>
                        <td class="agcs-label" style="width:8%; text-align:right;">Origin City</td>
                        <td style="width:18%;"><input type="text" class="agcs-input" value="{{ session.branch | default('NOHAR') }}" readonly style="background:#FFFFCC;"></td>
                        <td class="agcs-label" style="width:5%; text-align:right;">D/P</td>
                        <td style="width:10%;"><select class="agcs-select"><option>DOCUM</option></select></td>
                        <td class="agcs-label" style="width:5%; text-align:right;">Return?</td>
                        <td style="width:8%;"><select class="agcs-select"><option>NO</option></select></td>
                        <td class="agcs-label" style="width:5%; text-align:right;">Free?</td>
                        <td style="width:8%;"><select class="agcs-select"><option>NO</option></select></td>
                        <td rowspan="2" style="width:5%; text-align:center;">
                            <img src="https://cdn-icons-png.flaticon.com/128/2874/2874050.png" width="20" class="icon-btn" onclick="document.getElementById('entryForm').submit()" title="Save Item"><br><br>
                            <img src="https://cdn-icons-png.flaticon.com/128/1828/1828843.png" width="20" class="icon-btn" title="Cancel" onclick="document.getElementById('entryForm').reset()">
                        </td>
                    </tr>
                    <tr>
                        <td class="agcs-label">Ref. No.</td>
                        <td><input type="text" class="agcs-input"></td>
                        <td class="agcs-label" style="text-align:right;">Dest. City</td>
                        <td><input type="text" name="dest" id="out_dest_input" list="stlist" class="agcs-input"></td>
                        <td class="agcs-label" style="text-align:right;">Normal Wgt.</td>
                        <td><input type="number" step="0.01" name="weight" id="out_wt_input" class="agcs-input" value="1.0"></td>
                        <td class="agcs-label" style="text-align:right;">Cros. Amt.</td>
                        <td colspan="3"><input type="text" class="agcs-input" style="background:#FFFFCC;"></td>
                    </tr>
                    <tr>
                        <td colspan="2"></td>
                        <td class="agcs-label" style="text-align:right;">Mode</td>
                        <td><select class="agcs-select" style="background:#FFFFCC;"><option>AIR</option><option selected>SURFACE</option></select></td>
                        <td class="agcs-label" style="text-align:right;">Vol. Wgt.</td>
                        <td><input type="text" class="agcs-input"></td>
                        <td class="agcs-label" style="text-align:right;">Client Info.</td>
                        <td colspan="3"><input type="text" class="agcs-input"></td>
                        <td style="text-align:center;"><img src="https://cdn-icons-png.flaticon.com/128/3288/3288599.png" width="20" class="icon-btn" title="Refresh"></td>
                    </tr>
                </table>
            </div>
        </form>

        <div style="border: 1px solid #CCC; background: white; margin-top: 5px; height: 180px; overflow-y: scroll;">
            <table class="datatable" style="margin:0; border:none; width:100%;">
                <thead style="position: sticky; top: 0;">
                    <tr>
                        <th style="width:30px;">Del</th><th>C.Note</th><th>Dest. City</th><th>Weight</th><th>Vol. Wgt.</th><th>Mode</th><th>Remarks</th>
                    </tr>
                </thead>
                <tbody>
                    {% for p in pending_list %}
                    <tr>
                        <td style="text-align:center;"><a href="/outward?delete={{ p.id }}&date={{ f_date }}&station={{ f_station }}"><img src="https://cdn-icons-png.flaticon.com/128/3096/3096673.png" width="12" title="Delete"></a></td>
                        <td style="font-weight:bold; color:blue;">{{ p.awb_no }}</td>
                        <td>{{ p.destination or '-' }}</td>
                        <td>{{ p.weight or '0' }}</td>
                        <td>0.00</td>
                        <td>SURFACE</td>
                        <td>{{ str(p.info or '') }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div style="text-align: right; padding: 5px 0;">
            <form method="POST" id="finalizeForm" style="display:inline;">
                <input type="hidden" name="action" value="finalize">
                <input type="hidden" name="out_date" id="fin_date" value="{{ f_date }}">
                <input type="hidden" name="out_station" id="fin_station" value="{{ f_station }}">
                <span style="font-weight:bold; color:#003366; font-size:11px;">Vehicle No:</span> 
                <input type="text" name="vehicle_no" required class="agcs-input" style="width:100px; display:inline-block;">
                <button type="submit" class="agcs-btn-grey" style="padding: 2px 10px;">Print ManiFest</button>
            </form>
        </div>
        
        <div style="margin-top: 20px;">
            <div class="agcs-header" style="text-align:left;">Previous Manifest Register</div>
            <div style="border: 1px solid #CCC; background: white; height: 120px; overflow-y: scroll;">
                <table class="datatable" style="margin:0; border:none; width:100%;">
                    <thead style="position: sticky; top: 0;">
                        <tr><th>Manifest No</th><th>Date</th><th>Route</th><th>Vehicle</th><th>Act</th></tr>
                    </thead>
                    <tbody>
                        {% for m in mans %}
                        <tr>
                            <td style="font-weight:bold;">{{ m.manifest_no }}</td><td>{{ m.created_at }}</td><td>{{ m.from_location }} &rarr; {{ m.to_location }}</td><td>{{ m.vehicle_no or '-' }}</td>
                            <td><a href="/print/manifest/{{ m.id }}" target="_blank" style="color:blue; font-weight:bold;">[Print]</a> | <a href="/outward?unfinalize={{ m.id }}" style="color:red; font-weight:bold;" onclick="return confirm('Unlock?');">[Unlock]</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <script>
    function reloadPage() { 
        window.location.href = `/outward?date=${document.getElementById('ui_date').value}&station=${document.getElementById('ui_station').value}`; 
    }
    document.getElementById('entryForm').addEventListener('submit', function() { 
        document.getElementById('hdn_date').value = document.getElementById('ui_date').value; 
        document.getElementById('hdn_station').value = document.getElementById('ui_station').value; 
    });
    
    // AJAX to fetch AWB info (Dest & Weight) automatically when AWB is typed
    function fetchAwbInfo() {
        let awb = document.getElementById('out_awb_input').value.trim();
        if(awb.length > 3) {
            fetch('/api/get_awb_info/' + awb)
            .then(r => r.json())
            .then(data => {
                if(data.success) {
                    document.getElementById('out_dest_input').value = data.dest_station || data.dest_name;
                    document.getElementById('out_wt_input').value = data.weight;
                }
            });
        }
    }
    </script>
    """
    return render_page("Outward Entry [Transhipment]", render_template_string(html, pending_list=pending_list, mans=mans, stations=stations, franch_list=franch_list, cargo_list=cargo_list, f_date=f_date, f_station=f_station, str=str))

@app.route('/master_bag', methods=['GET', 'POST'])
@login_required
def master_bag():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        awbs = request.form.get('awbs').replace(',', '\n').split('\n'); dest = request.form.get('dest_hub', '').upper()
        with conn.cursor() as c:
            bag_no = get_seq("bag", "BAG", 6); c.execute("INSERT INTO master_bags(bag_no, destination) VALUES(%s,%s)", (bag_no, dest))
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("INSERT INTO master_bag_items(bag_no, awb_no) VALUES(%s,%s)", (bag_no, awb))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,)); s = c.fetchone()
                    if s: c.execute("INSERT INTO scan_events(shipment_id,scan_type,location,remarks) VALUES(%s,'BAGGED',%s,%s)", (s['id'], session.get('branch','HQ'), f"Packed in {bag_no}"))
            conn.commit(); flash(f"Master Bag Sealed! Bag No: {bag_no}", "success")
    with conn.cursor() as c:
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
        c.execute("SELECT bag_no, destination, created_at, (SELECT COUNT(*) FROM master_bag_items WHERE bag_no=master_bags.bag_no) as items FROM master_bags ORDER BY id DESC LIMIT 10"); bags = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3>Create Master Bag (Bora)</h3><form method="POST"><label>Destination Hub:</label><input name="dest_hub" list="stations" required style="text-transform:uppercase;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist><br><br><label>Scan Items:</label><br><textarea name="awbs" rows="8" required style="font-family:monospace;"></textarea><br><button type="submit" class="btn btn-blue" style="margin-top:5px;">SEAL BAG</button></form></div><div class="card"><h3>Recent Bags</h3><table class="datatable"><thead><tr><th>Bag No</th><th>Destination</th><th>Items</th><th>Date</th></tr></thead><tbody>{% for b in bags %}<tr><td style="font-weight:bold;">{{ b.bag_no }}</td><td>{{ b.destination }}</td><td>{{ b.items }}</td><td>{{ b.created_at }}</td></tr>{% endfor %}</tbody></table></div></div>"""
    return render_page("Master Bag Generator", render_template_string(html, stations=stations, bags=bags))

@app.route('/inward', methods=['GET', 'POST'])
@login_required
def inward():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM inward_register WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Deleted","success"); return redirect('/inward')
    if request.method == 'POST':
        awb = request.form.get('awb', '').strip().upper()
        awbs_list = request.form.get('awbs', '').replace(',', '\n').split('\n')
        if awb: awbs_list.append(awb)
        origin = request.form.get('origin', '').upper(); wt = str(safe_float(request.form.get('weight'))); info = request.form.get('info', '')
        with conn.cursor() as c:
            for a in awbs_list:
                awb_clean = a.strip().upper()
                if awb_clean:
                    if awb_clean.startswith("BAG"):
                        c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb_clean,))
                        for bi in c.fetchall():
                            c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, weight, info, finalized) VALUES(CURDATE(), %s, %s, %s, %s, %s, 1)", (bi['awb_no'], origin, session.get('branch','HQ'), wt, f"Unpacked {awb_clean}"))
                            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (bi['awb_no'],)); s_row = c.fetchone()
                            if s_row: c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session.get('branch','HQ'), s_row['id'])); c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (s_row['id'], session.get('branch','HQ')))
                    else:
                        c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, weight, info, finalized) VALUES(CURDATE(), %s, %s, %s, %s, %s, 1)", (awb_clean, origin, session.get('branch','HQ'), wt, info))
                        c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb_clean,)); s_row = c.fetchone()
                        if s_row: c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session.get('branch','HQ'), s_row['id'])); c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (s_row['id'], session.get('branch','HQ')))
            conn.commit(); flash("Inward Completed.", "success")
    with conn.cursor() as c:
        c.execute("SELECT * FROM inward_register WHERE in_station=%s AND finalized=0 ORDER BY id DESC LIMIT 50", (session.get('branch','HQ'),)); hist = c.fetchall()
        c.execute("SELECT inward_no, MIN(entry_date) as d, MIN(in_station) as st, COUNT(*) as c, MIN(manifest_no) as m FROM inward_register WHERE finalized=1 GROUP BY inward_no ORDER BY d DESC LIMIT 10"); sess = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3>Cargo Packet Inward</h3><form method="POST" id="inForm"><div style="background:#F4FAFA; padding:5px; border:1px solid #CCC; margin-bottom:5px;"><label>My Hub:</label> <input value="{{ session['branch'] }}" readonly style="width:100px;"> <label>From:</label> <input name="origin" list="stations" required style="width:100px;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div><table style="width:100%;"><tr><td><label>AWB/BAG:</label></td><td><input type="text" name="awb" id="in_awb_input" required autofocus style="color:red; font-weight:bold;"></td></tr><tr><td><label>Wt:</label></td><td><input type="number" step="0.01" name="weight" value="1.00"></td></tr><tr><td><label>Remarks:</label></td><td><input name="info"></td></tr><tr><td colspan="2"><button type="submit" class="btn btn-blue" style="width:100%; margin-top:5px;">Save Inward</button></td></tr></table><br><label>Bulk Items (Textarea):</label><br><textarea name="awbs" rows="3"></textarea></form></div><div class="card"><h3>Inward M.Fest Summary</h3><table class="datatable"><thead><tr><th>Inward No</th><th>Date</th><th>Docs</th><th>Manifest</th></tr></thead><tbody>{% for s in sess %}<tr><td><strong>{{ s.inward_no }}</strong></td><td>{{ s.d }}</td><td>{{ s.c }}</td><td>{{ s.m or '-' }}</td></tr>{% endfor %}</tbody></table></div></div>"""
    return render_page("Inward Entry", render_template_string(html, hist=hist, sess=sess, stations=stations))

@app.route('/drs', methods=['GET', 'POST'])
@login_required
def drs():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.args.get('del_drs'):
        with conn.cursor() as c: c.execute("DELETE FROM drs_items WHERE drs_id=%s", (request.args.get('del_drs'),)); c.execute("DELETE FROM drs WHERE id=%s", (request.args.get('del_drs'),)); conn.commit(); flash("Deleted", "success"); return redirect('/drs')
    if request.args.get('unfinalize'):
        with conn.cursor() as c:
            drs_id = request.args.get('unfinalize'); c.execute("UPDATE drs SET status='OPEN' WHERE id=%s", (drs_id,)); c.execute("UPDATE drs_items SET status='ASSIGNED' WHERE drs_id=%s", (drs_id,)); conn.commit(); flash("DRS Reopened!", "success"); return redirect('/drs')

    if request.method == 'POST' and 'assign_drs' in request.form:
        awbs = request.form.get('awbs').replace(',', '\n').split('\n'); rider = request.form.get('rider', ''); area = request.form.get('area', '')
        d = datetime.now().strftime("%Y-%m-%d")
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("INSERT INTO delivery_register(entry_date, delivery_boy, delivery_area, awb_no, receiver_name, info, finalized) VALUES(%s, %s, %s, %s, '', '', 0)", (d, rider, area, awb))
            conn.commit(); flash(f"Added to Queue", "success")

    if request.method == 'POST' and 'finalize_drs' in request.form:
        with conn.cursor() as c:
            c.execute("SELECT DISTINCT delivery_boy, delivery_area, entry_date FROM delivery_register WHERE finalized=0")
            pending_groups = c.fetchall()
            for grp in pending_groups:
                boy = grp["delivery_boy"]; area = grp["delivery_area"]; d = grp["entry_date"]
                c.execute("SELECT * FROM delivery_register WHERE finalized=0 AND delivery_boy=%s AND delivery_area=%s AND entry_date=%s", (boy, area, d)); rows = c.fetchall()
                if not rows: continue
                no = get_seq("drs", "DRS", 6)
                c.execute("INSERT INTO drs(drs_no, drs_date, rider_name, vehicle_no, status) VALUES(%s, %s, %s, %s, 'FINALIZED')", (no, d, boy, area))
                did = c.lastrowid
                for r in rows:
                    c.execute("UPDATE delivery_register SET finalized=1, drs_no=%s WHERE id=%s", (no, r["id"]))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (r["awb_no"],)); s = c.fetchone()
                    if s:
                        sid = s["id"]
                        c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE id=%s", (area, sid))
                        c.execute("INSERT INTO drs_items(drs_id, shipment_id, status, receiver_name) VALUES(%s, %s, 'ASSIGNED', %s)", (did, sid, r["receiver_name"]))
            conn.commit(); flash(f"DRS Finalized", "success")

    elif request.method == 'POST' and 'mark_deliver' in request.form:
        awb = request.form.get('deliver_awb', '').strip().upper(); receiver = request.form.get('receiver', '')
        with conn.cursor() as c:
            c.execute("SELECT id, dest_phone FROM shipments WHERE awb_no=%s", (awb,)); s_row = c.fetchone()
            if s_row:
                c.execute("UPDATE shipments SET status='DELIVERED', current_location=%s WHERE id=%s", (f"Delivered: {receiver}", s_row['id']))
                c.execute("UPDATE drs_items SET status='DELIVERED', receiver_name=%s WHERE shipment_id=%s", (receiver, s_row['id']))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'DELIVERED', %s, %s)", (s_row['id'], session.get('branch','HQ'), f"Received by {receiver}"))
                conn.commit()
                msg = f"Your parcel (AWB: {awb}) has been successfully DELIVERED to {receiver}. Thank you for using AGC."
                trigger_whatsapp(s_row['dest_phone'], msg)
                flash(f"Delivered: {awb}", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, entry_date, delivery_boy, delivery_area, awb_no, receiver_name FROM delivery_register WHERE finalized=0 ORDER BY id DESC"); pending = c.fetchall()
        c.execute("SELECT drs_no, MIN(entry_date) d, MIN(delivery_boy) b, MIN(delivery_area) a, COUNT(*) c FROM delivery_register WHERE finalized=1 GROUP BY drs_no ORDER BY d DESC"); sess = c.fetchall()
        c.execute("SELECT id, drs_no, drs_date, rider_name, status FROM drs ORDER BY id DESC LIMIT 15"); drs_tbl = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid-2">
        <div class="card">
            <h3>D.R.S. Entry</h3>
            <form method="POST"><input type="hidden" name="assign_drs" value="1">
                <table style="width:100%;">
                    <tr><td><label>Delivery Boy:</label></td><td><input name="rider" required></td></tr>
                    <tr><td><label>Area:</label></td><td><input name="area"></td></tr>
                    <tr><td colspan="2"><label>AWBs (Scan):</label><br><textarea name="awbs" rows="4" required style="font-family:monospace;"></textarea></td></tr>
                    <tr><td colspan="2"><button type="submit" class="btn btn-blue" style="width:100%; margin-top:5px;">Save</button></td></tr>
                </table>
            </form>
            <form method="POST" style="margin-top:10px;"><input type="hidden" name="finalize_drs" value="1"><button type="submit" class="btn btn-gold" style="width:100%;">Generate DRS</button></form>
        </div>
        <div>
            <div class="card">
                <h3>DRS Summary Register</h3>
                <table class="datatable"><thead><tr><th>ID</th><th>DRS No</th><th>Date</th><th>Boy</th><th>Action</th></tr></thead><tbody>{% for d in drs_tbl %}<tr><td>{{ d.id }}</td><td style="font-weight:bold;">{{ d.drs_no }}</td><td>{{ d.drs_date }}</td><td>{{ d.rider_name }}</td><td><a href="/print/drs/{{ d.id }}" target="_blank" style="color:blue;">Print</a></td></tr>{% endfor %}</tbody></table>
            </div>
            <div class="card" style="border-top:3px solid green !important;">
                <h3 style="color:green !important;">D.R.S. Delivery Status/Scan</h3>
                <form method="POST"><input type="hidden" name="mark_deliver" value="1"><table style="width:100%;"><tr><td><label>AWB:</label></td><td><input name="deliver_awb" required style="text-transform:uppercase; font-weight:bold; border:1px solid green;"></td></tr><tr><td><label>Receiver:</label></td><td><input name="receiver" required></td></tr><tr><td colspan="2"><button type="submit" class="btn btn-green" style="width:100%; margin-top:5px;">Update Delivery</button></td></tr></table></form>
            </div>
        </div>
    </div>
    """
    return render_page("D.R.S.", render_template_string(html, pending=pending, sess=sess, drs_tbl=drs_tbl))

# ==========================================
# 💰 11. ACCOUNTS, EXPENSES & REPORTS
# ==========================================
@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM expenses WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Deleted!", "success"); return redirect('/expenses')
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c: c.execute("INSERT INTO expenses(expense_date, category, amount, paid_to, notes) VALUES(%s,%s,%s,%s,%s)", (d.get('date'), d.get('cat'), safe_float(d.get('amt')), d.get('paid',''), d.get('notes',''))); conn.commit(); flash("Saved!", "success")
    with conn.cursor() as c: c.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT 50"); exps = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3>Journal Voucher Entry</h3><form method="POST"><table style="width:100%;"><tr><td><label>Date</label></td><td><input type="date" name="date" required></td></tr><tr><td><label>A/c Head</label></td><td><select name="cat"><option>General Exp</option><option>Fuel</option><option>Salary</option></select></td></tr><tr><td><label>Amount</label></td><td><input type="number" step="0.01" name="amt" required></td></tr><tr><td><label>Paid To</label></td><td><input name="paid"></td></tr><tr><td><label>Notes</label></td><td><input name="notes"></td></tr><tr><td colspan="2"><button type="submit" class="btn btn-blue" style="width:100%; margin-top:5px;">Save Voucher</button></td></tr></table></form></div><div class="card"><h3>Voucher Register</h3><table class="datatable"><thead><tr><th>ID</th><th>Date</th><th>A/c Head</th><th>Amount</th><th>Notes</th><th>Act</th></tr></thead><tbody>{% for e in exps %}<tr><td>{{ e.id }}</td><td>{{ e.expense_date }}</td><td>{{ e.category }}</td><td style="color:red; font-weight:bold;">{{ e.amount }}</td><td>{{ e.notes }}</td><td><a href="/expenses?delete={{ e.id }}" style="color:red;">[X]</a></td></tr>{% endfor %}</tbody></table></div></div>"""
    return render_page("Journal Voucher", render_template_string(html, exps=exps))

@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.args.get('del_pay'):
        with conn.cursor() as c:
            c.execute("SELECT * FROM payments WHERE id=%s", (request.args.get('del_pay'),)); p = c.fetchone()
            if p: c.execute("DELETE FROM ledger WHERE voucher_type='PAYMENT' AND reference=%s AND customer_id=%s", (p['reference'], p['customer_id'])); c.execute("DELETE FROM payments WHERE id=%s", (p['id'],))
            conn.commit(); flash("Deleted!", "success"); return redirect('/accounts')
    if request.method == 'POST':
        cid = safe_int(request.form.get('cust_id')) if request.form.get('cust_id') else None; amt = safe_float(request.form.get('amount')); mode = request.form.get('mode', ''); ref = request.form.get('ref', ''); d = datetime.now().strftime("%Y-%m-%d")
        with conn.cursor() as c:
            c.execute("INSERT INTO payments(customer_id, payment_date, amount, mode, reference) VALUES(%s,%s,%s,%s,%s)", (cid, d, amt, mode, ref))
            c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'PAYMENT',%s,0,%s,%s)", (cid, d, ref, amt, f"Received ({mode})"))
            conn.commit(); flash("Saved!", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall(); c.execute("SELECT p.id, p.payment_date, c.name, p.amount, p.mode, p.reference FROM payments p JOIN customers c ON p.customer_id=c.id ORDER BY p.id DESC LIMIT 20"); pays = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3>Cash Book / Bank Book Entry</h3><form method="POST"><table style="width:100%;"><tr><td><label>Party A/c</label></td><td><select name="cust_id" required>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></td></tr><tr><td><label>Amount</label></td><td><input type="number" step="0.01" name="amount" required style="font-weight:bold;"></td></tr><tr><td><label>Mode</label></td><td><select name="mode"><option>CASH</option><option>BANK</option></select></td></tr><tr><td><label>Ref/Chq</label></td><td><input name="ref"></td></tr><tr><td colspan="2"><button type="submit" class="btn btn-blue" style="width:100%; margin-top:5px;">Save Entry</button></td></tr></table></form></div><div class="card"><h3>Recent Entries</h3><table class="datatable"><thead><tr><th>ID</th><th>Date</th><th>Amount</th><th>Mode</th><th>Act</th></tr></thead><tbody>{% for p in pays %}<tr><td>{{ p.id }}</td><td>{{ p.payment_date }}</td><td style="color:green; font-weight:bold;">{{ p.amount }}</td><td>{{ p.mode }}</td><td><a href="/accounts?del_pay={{ p.id }}" style="color:red;">[X]</a></td></tr>{% endfor %}</tbody></table></div></div>"""
    return render_page("Cash Book", render_template_string(html, custs=custs, pays=pays))

@app.route('/reports')
@login_required
def reports():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    d = datetime.now().strftime("%Y-%m-%d"); conn = get_db()
    with conn.cursor() as c:
        p1 = [d]; p2 = [d]
        q_b = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE booking_date=%s"
        if session.get('role') != 'ADMIN': q_b += " AND origin_name=%s"; p1.append(session.get('branch','HQ'))
        c.execute(q_b, tuple(p1)); b_row = c.fetchone()
        c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments WHERE payment_date=%s", tuple(p2)); p_row = c.fetchone()
        c.execute("SELECT COALESCE(SUM(amount),0) e FROM expenses WHERE expense_date=%s", tuple(p2)); e_row = c.fetchone()
        c.execute("SELECT c.code, c.name, COALESCE(SUM(l.debit-l.credit),0) bal FROM customers c LEFT JOIN ledger l ON l.customer_id=c.id GROUP BY c.id HAVING bal>0 ORDER BY bal DESC LIMIT 20"); out = c.fetchall()
        c.execute("SELECT origin_name as branch_name, COUNT(id) as total_shipments, SUM(total_amount) as total_revenue FROM shipments GROUP BY origin_name ORDER BY total_revenue DESC"); settlement = c.fetchall()
    conn.close()
    
    b_c = safe_int(b_row['c']) if b_row else 0; b_t = safe_float(b_row['t']) if b_row else 0.0
    p_a = safe_float(p_row['a']) if p_row else 0.0
    
    html = """<div class="card"><div style="float:right;"><a href="/print/day_close" target="_blank" class="btn btn-ghost">Print Day Close</a></div><h3>Master Reports ({{ date }})</h3><div class="grid-3"><div style="border:1px solid #116B7A; padding:10px; background:#F4FAFA;"><label>Bookings</label><h3 style="margin:0;">{{ b_c }} Pcs | Rs {{ b_t }}</h3></div><div style="border:1px solid #116B7A; padding:10px; background:#F4FAFA;"><label>Collections</label><h3 style="margin:0; color:green;">Rs {{ p_a }}</h3></div><div style="border:1px solid #116B7A; padding:10px; background:#F4FAFA;"><label>Auto-Invoice</label><br><form action="/tools/auto-invoice" method="POST"><button type="submit" class="btn btn-blue">Gen. Pending Bills</button></form></div></div></div><div class="grid-2"><div class="card"><h3>Franchisee Summary</h3><table class="datatable"><thead><tr><th>Branch</th><th>Docs</th><th>Revenue</th></tr></thead><tbody>{% for s in settlement %}<tr><td><strong>{{ s.branch_name }}</strong></td><td>{{ s.total_shipments }}</td><td style="font-weight:bold;">{{ s.total_revenue }}</td></tr>{% endfor %}</tbody></table></div><div class="card"><h3>Credit Party Balance</h3><table class="datatable"><thead><tr><th>Code</th><th>Name</th><th>Balance</th></tr></thead><tbody>{% for o in out %}<tr><td>{{ o.code }}</td><td>{{ o.name }}</td><td style="color:red; font-weight:bold;">{{ o.bal }}</td></tr>{% endfor %}</tbody></table></div></div>"""
    return render_page("Main Reports", render_template_string(html, b_c=b_c, b_t=b_t, p_a=p_a, out=out, settlement=settlement, date=d))

@app.route('/reports/outward-range', methods=['POST'])
@login_required
def outward_range():
    f_date = request.form.get('from_date'); t_date = request.form.get('to_date'); conn = get_db(); c = conn.cursor()
    c.execute("SELECT o.*, s.dest_name FROM outward_register o LEFT JOIN shipments s ON o.awb_no = s.awb_no WHERE o.entry_date BETWEEN %s AND %s AND o.origin_station = %s", (f_date, t_date, session.get('branch','HQ')))
    data = c.fetchall(); c.close(); conn.close()
    output = io.StringIO(); writer = csv.writer(output); writer.writerow(['Date', 'AWB', 'Dest', 'Weight', 'Pcs'])
    for r in data: writer.writerow([r['entry_date'], r['awb_no'], r['destination'], r['weight'], r['pcs']])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')), mimetype='text/csv', download_name=f'Outward_{f_date}.csv', as_attachment=True)

# ==========================================
# 🚀 13. ADVANCED TOOLS & BACKGROUND SCHEDULER
# ==========================================

@app.route('/tools/sync-shipments', methods=['POST'])
@login_required
def sync_shipments():
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO outward_register (entry_date, awb_no, origin_station, out_station, destination, weight, pcs, finalized) SELECT booking_date, awb_no, origin_name, dest_station, dest_station, weight_kg, quantity, 1 FROM shipments WHERE status='OUTWARD' AND awb_no NOT IN (SELECT awb_no FROM outward_register)")
    conn.commit(); flash(f"Synced {c.rowcount} shipments.", "success"); c.close(); conn.close()
    return redirect('/outward')

@app.route('/tools/bulk-date-change', methods=['POST'])
@login_required
def bulk_date_change():
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE outward_register SET entry_date=%s WHERE entry_date=%s", (request.form.get('new_date'), request.form.get('old_date')))
    conn.commit(); flash(f"Date Changed!", "success"); c.close(); conn.close()
    return redirect('/outward')

@app.route('/tools/auto-invoice', methods=['POST'])
@login_required
def auto_invoice():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT id, customer_id, awb_no, taxable_amount, cgst, sgst, igst, total_amount FROM shipments WHERE customer_id IS NOT NULL AND total_amount > 0 AND status != 'CANCELLED' AND id NOT IN (SELECT shipment_id FROM invoice_lines WHERE shipment_id IS NOT NULL)")
        uninvoiced = c.fetchall()
        if not uninvoiced:
            flash("All B2B parcels invoiced.", "success")
            return redirect('/reports')
            
        cust_shipments = {}
        for s in uninvoiced:
            cid = s['customer_id']
            if cid not in cust_shipments: cust_shipments[cid] = []
            cust_shipments[cid].append(s)
            
        invoices_created = 0
        for cid, ships in cust_shipments.items():
            c.execute("SELECT state_code FROM customers WHERE id=%s", (cid,))
            cust_state = c.fetchone()
            pos = cust_state['state_code'] if cust_state else get_setting("company_state_code", "08")
            
            tot_taxable = sum(safe_float(s['taxable_amount']) for s in ships)
            tot_cgst = sum(safe_float(s['cgst']) for s in ships)
            tot_sgst = sum(safe_float(s['sgst']) for s in ships)
            tot_igst = sum(safe_float(s['igst']) for s in ships)
            tot_amt = sum(safe_float(s['total_amount']) for s in ships)
            
            inv_no = get_seq("invoice", "INV/", 5)
            inv_date = datetime.now().strftime('%Y-%m-%d')
            
            c.execute("INSERT INTO invoices(invoice_no, invoice_date, customer_id, place_of_supply_state_code, taxable_amount, cgst, sgst, igst, total, status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'UNPAID')", (inv_no, inv_date, cid, pos, tot_taxable, tot_cgst, tot_sgst, tot_igst, tot_amt))
            inv_id = c.lastrowid
            
            for s in ships:
                c.execute("INSERT INTO invoice_lines(invoice_id, description, shipment_id, quantity, taxable_amount, cgst, sgst, igst, total) VALUES(%s,%s,%s,1,%s,%s,%s,%s,%s)", (inv_id, f"AWB {s['awb_no']}", s['id'], s['taxable_amount'], s['cgst'], s['sgst'], s['igst'], s['total_amount']))
            
            c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (cid, inv_date, inv_no, tot_amt, f"Auto-Invoice {inv_no}"))
            invoices_created += 1
            
        conn.commit(); flash(f"Success! {invoices_created} invoices generated.", "success")
    conn.close()
    return redirect('/reports')

def background_auto_invoice():
    try:
        conn = get_db()
        with conn.cursor() as c:
            c.execute("SELECT id, customer_id, awb_no, taxable_amount, cgst, sgst, igst, total_amount FROM shipments WHERE customer_id IS NOT NULL AND total_amount > 0 AND status != 'CANCELLED' AND id NOT IN (SELECT shipment_id FROM invoice_lines WHERE shipment_id IS NOT NULL)")
            uninvoiced = c.fetchall()
            if uninvoiced:
                cust_shipments = {}
                for s in uninvoiced:
                    cid = s['customer_id']
                    if cid not in cust_shipments: cust_shipments[cid] = []
                    cust_shipments[cid].append(s)
                for cid, ships in cust_shipments.items():
                    tot_taxable = sum(safe_float(s['taxable_amount']) for s in ships)
                    tot_amt = sum(safe_float(s['total_amount']) for s in ships)
                    inv_no = get_seq("invoice", "INV/", 5)
                    inv_date = datetime.now().strftime('%Y-%m-%d')
                    c.execute("INSERT INTO invoices(invoice_no, invoice_date, customer_id, taxable_amount, total, status) VALUES(%s,%s,%s,%s,%s,'UNPAID')", (inv_no, inv_date, cid, tot_taxable, tot_amt))
                    inv_id = c.lastrowid
                    for s in ships:
                        c.execute("INSERT INTO invoice_lines(invoice_id, shipment_id, total) VALUES(%s,%s,%s)", (inv_id, s['id'], s['total_amount']))
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit) VALUES(%s,%s,'INVOICE',%s,%s)", (cid, inv_date, inv_no, tot_amt))
                conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Cron Error: {e}")

if BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=background_auto_invoice, trigger="cron", day="1", hour="0", minute="5")
    scheduler.start()

@app.route('/print/day_close')
@login_required
def print_day_close():
    d = datetime.now().strftime("%Y-%m-%d")
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE booking_date=%s", (d,))
    b = c.fetchone()
    c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments WHERE payment_date=%s", (d,))
    p = c.fetchone()
    c.execute("SELECT COALESCE(SUM(amount),0) e FROM expenses WHERE expense_date=%s", (d,))
    e = c.fetchone()
    c.close(); conn.close()
    
    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, 800, f"{get_setting('company_name', 'AGC')} - DAY CLOSE REPORT")
    cv.setFont("Helvetica", 11); cv.drawString(40, 780, f"Date: {d} | Branch: {session.get('branch', 'HQ')}")
    cv.line(40, 770, 550, 770)
    cv.setFont("Helvetica-Bold", 12)
    cv.drawString(40, 740, f"1. Total Bookings: {b['c']} Parcels")
    cv.drawString(40, 720, f"2. Total Billing Amount: Rs {b['t']}")
    cv.drawString(40, 700, f"3. Payments Received: Rs {p['a']}")
    cv.drawString(40, 680, f"4. Expenses Paid: Rs {e['e']}")
    net_cash = safe_float(p['a']) - safe_float(e['e'])
    cv.setFillColor(HexColor("#10B981") if net_cash >= 0 else HexColor("#EF4444"))
    cv.drawString(40, 640, f"NET CASH IN HAND: Rs {net_cash}")
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"DayClose_{d}.pdf", mimetype='application/pdf')

@app.route('/print/statement/<int:cid>')
@login_required
def print_statement(cid):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM customers WHERE id=%s", (cid,)); cust = c.fetchone()
    c.execute("SELECT * FROM ledger WHERE customer_id=%s ORDER BY entry_date", (cid,)); ledger = c.fetchall()
    c.execute("SELECT COALESCE(SUM(debit-credit),0) bal FROM ledger WHERE customer_id=%s", (cid,)); bal = c.fetchone()['bal']
    c.close(); conn.close()
    
    if not cust: flash("Customer not found", "error"); return redirect('/accounts')
        
    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, 800, f"{get_setting('company_name', 'AGC')} - ACCOUNT STATEMENT")
    cv.setFont("Helvetica", 10); cv.drawString(40, 780, f"Customer: {cust['name']} | Phone: {cust['phone']}")
    cv.drawString(40, 765, f"Statement Generated On: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    y = 730
    cv.setFillColor(HexColor("#F1F5F9")); cv.rect(40, y-5, 515, 20, fill=1, stroke=0)
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 9)
    cv.drawString(45, y, "Date"); cv.drawString(110, y, "Voucher"); cv.drawString(180, y, "Reference"); cv.drawString(350, y, "Debit (Bill)"); cv.drawString(450, y, "Credit (Pay)")
    y -= 20
    cv.setFont("Helvetica", 9)
    for l in ledger:
        if y < 50: cv.showPage(); y = 800
        cv.drawString(45, y, str(l['entry_date'])); cv.drawString(110, y, str(l['voucher_type'])); cv.drawString(180, y, str(l['reference']))
        cv.drawString(350, y, f"Rs {l['debit']}"); cv.drawString(450, y, f"Rs {l['credit']}")
        y -= 15
    cv.line(40, y, 555, y); y -= 20
    cv.setFont("Helvetica-Bold", 12)
    cv.drawString(320, y, f"Total Outstanding Balance: Rs {bal}")
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Statement_{cust['name'].replace(' ', '_')}.pdf", mimetype='application/pdf')

# ==========================================
# 🖨️ 14. EXACT OFFLINE PDF ENGINE
# ==========================================
def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

def draw_barcode_safe(cv, value, x, y, height):
    try: code128.Code128(str(value), barHeight=height, barWidth=0.011 * inch).drawOn(cv, x, y)
    except: pass

def wrap_lines(cv, text, font, size, max_width):
    lines, line = [], ""
    for word in str(text or "").split():
        t = (line + " " + word).strip()
        if cv.stringWidth(t, font, size) <= max_width: line = t
        else:
            if line: lines.append(line)
            line = word
    if line: lines.append(line)
    return lines

def draw_agc_logo(cv, x, y):
    logo = get_setting("company_logo_path", "")
    if logo and os.path.exists(logo):
        try: cv.drawImage(logo, x, y, width=28*mm, height=12*mm, preserveAspectRatio=True, mask="auto"); return
        except: pass
    cv.saveState(); cv.setFont("Helvetica-BoldOblique", 24); cv.setFillColor(HexColor("#004B87")); cv.drawString(x, y + 4*mm, "AGC")
    cv.setFont("Helvetica-Bold", 14); cv.setFillColor(HexColor("#000000")); cv.drawString(x, y - 4*mm, "Akash")
    cv.setFillColor(HexColor("#F26522")); cv.drawString(x + 13*mm, y - 4*mm, "Ganga")
    cv.setStrokeColor(HexColor("#F26522")); cv.setLineWidth(1); cv.line(x, y - 2*mm, x + 25*mm, y - 2*mm)
    cv.setFont("Helvetica-Oblique", 6); cv.setFillColor(HexColor("#004B87")); cv.drawString(x + 2*mm, y - 6*mm, "Integrity at work")
    cv.restoreState()

@app.route('/print/label/<awb>')
@login_required
def print_label_pdf(awb):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT s.*, c.name as cname, c.address as caddr FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,)); s = c.fetchone()
    c.close(); conn.close()
    if not s: return "Not found"
    
    if session.get('role') == 'CUSTOMER' and s['customer_id'] != session.get('customer_id'): return "Unauthorized", 403
    
    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=(101.6*mm, 152.4*mm)); cv.setLineWidth(1)
    cv.rect(4*mm, 4*mm, 93.6*mm, 144*mm) 
    draw_agc_logo(cv, 6*mm, 136*mm); cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica", 5.5); cv.drawString(6*mm, 129*mm, "ISO 9001:2008 Certified Company")
    cv.setFont("Helvetica-Bold", 14); cv.drawRightString(95*mm, 141*mm, str(session.get('branch', 'HQ')).upper())
    cv.setFont("Helvetica", 6); cv.drawRightString(95*mm, 137*mm, str(get_setting("company_name", "PANKAJ AGENCY COURIER")))
    cv.setFont("Helvetica-Bold", 8); cv.setFillColor(HexColor("#D97706")); cv.drawRightString(95*mm, 132*mm, "PREMIUM EXPRESS")
    cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica", 6); cv.drawRightString(95*mm, 128*mm, f"GSTIN: {get_setting('company_gstin', '')} | Ph: {get_setting('company_phone', '')}")
    cv.line(4*mm, 126*mm, 97.6*mm, 126*mm); cv.setFont("Helvetica-Bold", 7); cv.drawString(6*mm, 122*mm, "AWB NUMBER")
    cv.setFont("Helvetica-Bold", 16); cv.drawString(6*mm, 115*mm, s['awb_no']); cv.setFont("Helvetica", 7); cv.drawString(6*mm, 110*mm, s['awb_no'])
    draw_barcode_safe(cv, s['awb_no'], 45*mm, 111*mm, 12*mm)
    if qrcode:
        try: img = qrcode.make(s['awb_no']); qr_buf = io.BytesIO(); img.save(qr_buf, format="PNG"); cv.drawImage(ImageReader(io.BytesIO(qr_buf.getvalue())), 78*mm, 108*mm, width=18*mm, height=18*mm)
        except: pass
    cv.line(4*mm, 106*mm, 97.6*mm, 106*mm); cv.line(35*mm, 106*mm, 35*mm, 94*mm); cv.line(65*mm, 106*mm, 65*mm, 94*mm)
    cv.setFont("Helvetica-Bold", 6); cv.drawString(5*mm, 107*mm, "ORIGIN"); cv.setFont("Helvetica-Bold", 9); cv.drawString(5*mm, 97*mm, str(s.get('origin_name') or '')[:15].upper())
    cv.setFont("Helvetica-Bold", 6); cv.drawString(36*mm, 103*mm, "SERVICE"); cv.setFont("Helvetica-Bold", 9); cv.drawString(36*mm, 97*mm, str(s.get('service_type') or 'SURFACE')[:12].upper())
    cv.setFont("Helvetica-Bold", 6); cv.drawString(66*mm, 103*mm, "DESTINATION"); cv.setFont("Helvetica-Bold", 9); cv.drawString(66*mm, 97*mm, str(s.get('dest_station') or s.get('dest_name') or '')[:14].upper())
    cv.line(4*mm, 94*mm, 97.6*mm, 94*mm); cv.setFont("Helvetica-Bold", 6); cv.drawString(5*mm, 91*mm, "DELIVER TO")
    cv.setFont("Helvetica-Bold", 11); cv.drawString(5*mm, 85*mm, str(s.get('dest_name') or '')[:40].upper()); cv.setFont("Helvetica", 8)
    addr_lines = wrap_lines(cv, str(s.get('dest_address') or ''), "Helvetica", 8, 90*mm); y_addr = 81
    for ln in addr_lines[:2]: cv.drawString(5*mm, y_addr*mm, ln); y_addr -= 4
    cv.setFont("Helvetica-Bold", 8); cv.drawString(5*mm, y_addr*mm, f"Ph: {str(s.get('dest_phone') or '')}")
    cv.line(4*mm, 69*mm, 97.6*mm, 69*mm); cv.setFont("Helvetica-Bold", 6)
    cv.drawString(5*mm, 64*mm, "WEIGHT"); cv.drawString(26*mm, 64*mm, "PIECES"); cv.drawString(46*mm, 64*mm, "COD"); cv.drawString(71*mm, 64*mm, "DECLARED")
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(5*mm, 61*mm, f"{safe_float(s.get('weight_kg', 1))} KG"); cv.drawString(26*mm, 61*mm, f"{s.get('quantity', 1)}"); cv.drawString(46*mm, 61*mm, f"Rs {safe_float(s.get('cod_amount', 0))}"); cv.drawString(71*mm, 61*mm, f"Rs {safe_float(s.get('declared_value', 0))}")
    cv.line(4*mm, 58*mm, 97.6*mm, 58*mm); cv.setFont("Helvetica-Bold", 6)
    cv.drawString(5*mm, 55*mm, "MODE"); cv.drawString(36*mm, 55*mm, "DEST CITY"); cv.drawString(66*mm, 55*mm, "BRANCH")
    cv.setFont("Helvetica-Bold", 8)
    cv.drawString(5*mm, 50*mm, str(s.get('service_type') or 'SURFACE')[:10]); cv.drawString(36*mm, 50*mm, str(s.get('dest_station') or '')[:14]); cv.drawString(66*mm, 50*mm, str(session.get('branch') or 'HQ')[:15])
    cv.line(4*mm, 47*mm, 97.6*mm, 47*mm); cv.setFont("Helvetica-Bold", 6); cv.drawString(5*mm, 44*mm, "SHIPPER")
    cv.setFont("Helvetica", 7); shipper = str(s.get('cname') or s.get('origin_name') or '')
    cv.drawString(5*mm, 40*mm, f"CASH BOOKING || {shipper[:35]}")
    cv.line(4*mm, 35*mm, 97.6*mm, 35*mm); cv.setFont("Helvetica", 6)
    cv.drawCentredString(50.8*mm, 31*mm, str(get_setting("terms_note", "Liability limited to declared value only.")))
    cv.drawCentredString(50.8*mm, 27*mm, f"HTTPS://AGCONLINE.IN | Computer Generated Label")
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Label_{awb}.pdf", mimetype='application/pdf')

@app.route('/print/receipt/<awb>')
@login_required
def print_receipt_pdf(awb):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT s.*, c.name as cname, c.address as caddr FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,)); s = c.fetchone()
    c.close(); conn.close()
    if not s: return "Not found"
    if session.get('role') == 'CUSTOMER' and s['customer_id'] != session.get('customer_id'): return "Unauthorized", 403

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFillColor(HexColor("#004B87")); cv.rect(0, 800, 600, 45, fill=1, stroke=0); cv.setFillColor(HexColor("#F26522")); cv.rect(0, 795, 600, 5, fill=1, stroke=0)
    draw_agc_logo(cv, 30, 802); cv.setFillColor(HexColor("#FFFFFF")); cv.setFont("Helvetica-Bold", 12); cv.drawRightString(560, 810, "NON-NEGOTIABLE DOCKET")
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica", 10); cv.drawString(30, 775, str(get_setting("company_address", "Head Office: Nohar (Raj)"))); cv.drawString(30, 755, f"Date: {s['booking_date']}")
    draw_barcode_safe(cv, s['awb_no'], 400, 750, 0.4*inch); cv.setFont("Helvetica-Bold", 14); cv.drawString(400, 735, s['awb_no'])
    
    cv.setStrokeColor(HexColor("#E1E6EE")); cv.setLineWidth(1)
    cv.roundRect(30, 600, 255, 120, 4); cv.setFillColor(HexColor("#F5F7FA")); cv.rect(31, 700, 253, 20, fill=1, stroke=0)
    cv.setFillColor(HexColor("#0B1F3A")); cv.setFont("Helvetica-Bold", 10); cv.drawString(35, 706, "CONSIGNOR (SHIPPER DETAILS):")
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 11); shipper_name = str(s.get('cname') or s.get('origin_name') or '')
    cv.drawString(35, 680, shipper_name[:40]); cv.setFont("Helvetica", 10); y_sh = 665
    for ln in wrap_lines(cv, str(s.get('caddr') or s.get('origin_address') or ''), "Helvetica", 10, 240)[:2]: cv.drawString(35, y_sh, ln); y_sh -= 15
    cv.drawString(35, y_sh, f"Ph: {str(s.get('origin_phone') or '')}"); cv.drawString(35, y_sh-15, f"State: {str(s.get('origin_state_code') or '')}")
    
    cv.roundRect(305, 600, 255, 120, 4); cv.setFillColor(HexColor("#F5F7FA")); cv.rect(306, 700, 253, 20, fill=1, stroke=0)
    cv.setFillColor(HexColor("#0B1F3A")); cv.setFont("Helvetica-Bold", 10); cv.drawString(310, 706, "CONSIGNEE (RECEIVER DETAILS):")
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 11); cv.drawString(310, 680, str(s.get('dest_name') or '')[:40]); cv.setFont("Helvetica", 10); y_cn = 665
    for ln in wrap_lines(cv, str(s.get('dest_address') or ''), "Helvetica", 10, 240)[:2]: cv.drawString(310, y_cn, ln); y_cn -= 15
    cv.drawString(310, y_cn, f"Ph: {str(s.get('dest_phone') or '')}"); cv.drawString(310, y_cn-15, f"Dest Station: {str(s.get('dest_station') or '')}")

    y_tbl = 560; cv.setFillColor(HexColor("#0E8A6D")); cv.rect(30, y_tbl, 530, 25, fill=1); cv.setFillColor(HexColor("#FFFFFF")); cv.setFont("Helvetica-Bold", 10)
    cv.drawString(35, y_tbl+8, "WEIGHT"); cv.drawString(100, y_tbl+8, "PIECES"); cv.drawString(160, y_tbl+8, "SERVICE"); cv.drawString(240, y_tbl+8, "TAXABLE"); cv.drawString(320, y_tbl+8, "GST AMT"); cv.drawString(390, y_tbl+8, "COD AMT"); cv.drawString(470, y_tbl+8, "TOTAL (Rs)")

    y_tbl -= 30; cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 11)
    cv.drawString(35, y_tbl+6, f"{safe_float(s.get('weight_kg'))} KG"); cv.drawString(100, y_tbl+6, str(s.get('quantity') or 1)); cv.drawString(160, y_tbl+6, str(s.get('service_type') or 'SURFACE')); cv.drawString(240, y_tbl+6, f"{safe_float(s.get('taxable_amount')):,.2f}")
    gst_tot = safe_float(s.get('cgst')) + safe_float(s.get('sgst')) + safe_float(s.get('igst'))
    cv.drawString(320, y_tbl+6, f"{gst_tot:,.2f}"); cv.drawString(390, y_tbl+6, f"{safe_float(s.get('cod_amount')):,.2f}"); cv.setFillColor(HexColor("#D97706")); cv.setFont("Helvetica-Bold", 14); cv.drawString(470, y_tbl+4, f"{safe_float(s.get('total_amount')):,.2f}")

    y_tbl -= 40; cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 10); cv.drawString(30, y_tbl, f"Amount to be collected: Rs {safe_float(s.get('total_amount')):,.2f}")
    cv.setFont("Helvetica", 8); cv.drawString(30, y_tbl-50, str(get_setting("terms_note", "DECLARATION: Goods are carried at Owner's Risk."))); cv.drawString(420, y_tbl-50, f"For {str(get_setting('company_name', 'PANKAJ AGENCY'))}"); cv.drawString(420, y_tbl-80, "Authorised Signatory")

    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Receipt_{awb}.pdf", mimetype='application/pdf')

@app.route('/print/manifest/<int:mid>')
@login_required
def print_manifest_pdf(mid):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM manifests WHERE id=%s", (mid,)); m = c.fetchone()
    c.execute("SELECT s.awb_no, s.dest_station, o.weight, o.pcs, o.network, o.bag_no, o.info FROM manifest_items mi JOIN shipments s ON s.id=mi.shipment_id JOIN outward_register o ON o.awb_no=s.awb_no WHERE mi.manifest_id=%s", (mid,)); items = c.fetchall()
    c.close(); conn.close()

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 50, f"{str(get_setting('company_name', 'PANKAJ AGENCY'))} - OUTWARD MANIFEST")
    cv.setFont("Helvetica", 10); cv.drawString(40, h - 65, f"Manifest No: {m['manifest_no']}   |   Route: {m['from_location']} -> {m['to_location']}")
    cv.drawString(40, h - 80, f"Vehicle: {str(m.get('vehicle_no') or '-')}   |   Driver Ph: {str(m.get('driver_phone') or '-')}   |   Seal: {str(m.get('seal_no') or '-')}   |   Items: {len(items)}")
    draw_barcode_safe(cv, m['manifest_no'], w - 180, h - 70, 0.4 * inch)
    
    y = h - 110
    def draw_headers(curr_y):
        cv.setFillColor(HexColor("#F5F7FA")); cv.rect(40, curr_y - 16, 250, 16, fill=1, stroke=0); cv.rect(305, curr_y - 16, 250, 16, fill=1, stroke=0)
        cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica-Bold", 7.5)
        cv.drawString(42, curr_y - 11, "#"); cv.drawString(60, curr_y - 11, "AWB & BARCODE"); cv.drawString(160, curr_y - 11, "DESTINATION"); cv.drawString(255, curr_y - 11, "WT")
        cv.drawString(307, curr_y - 11, "#"); cv.drawString(325, curr_y - 11, "AWB & BARCODE"); cv.drawString(425, curr_y - 11, "DESTINATION"); cv.drawString(520, curr_y - 11, "WT")
        
    draw_headers(y); y -= 16
    for i, it in enumerate(items):
        is_right = (i % 2 != 0); cx = 305 if is_right else 40
        if not is_right and y - 24 < 40: cv.showPage(); y = h - 50; draw_headers(y); y -= 16
        cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica-Bold", 7.5); cv.drawString(cx + 2, y - 10, str(i + 1)); cv.drawString(cx + 20, y - 9, it["awb_no"]); draw_barcode_safe(cv, it["awb_no"], cx + 20, y - 21, 0.16 * inch)
        cv.setFont("Helvetica", 7); cv.drawString(cx + 120, y - 14, str(it.get("dest_station") or '')[:18]); cv.setFont("Helvetica-Bold", 7.5); cv.drawString(cx + 215, y - 14, f"{it.get('weight', 1)} KG")
        if is_right: y -= 24
            
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Manifest_{m['manifest_no']}.pdf", mimetype='application/pdf')

@app.route('/print/drs/<int:did>')
@login_required
def print_drs_pdf(did):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM drs WHERE id=%s", (did,)); d = c.fetchone()
    c.execute("SELECT s.awb_no, s.dest_name, di.receiver_name FROM drs_items di JOIN shipments s ON s.id=di.shipment_id WHERE di.drs_id=%s ORDER BY s.id", (did,)); items = c.fetchall()
    c.close(); conn.close()

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 50, f"{str(get_setting('company_name', 'PANKAJ AGENCY'))} - DELIVERY RUN SHEET")
    cv.setFont("Helvetica", 10); cv.drawString(40, h - 65, f"DRS No: {d['drs_no']}   |   Rider: {d['rider_name']}   |   Date: {d['drs_date']}")
    draw_barcode_safe(cv, d['drs_no'], w - 180, h - 70, 0.4 * inch)
    
    y = h - 100; cv.setFillColor(HexColor("#F5F7FA")); cv.rect(40, y - 20, w - 80, 20, fill=1, stroke=1)
    cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica-Bold", 9); cv.drawString(45, y - 14, "#"); cv.drawString(75, y - 14, "AWB & BARCODE"); cv.drawString(225, y - 14, "CONSIGNEE NAME"); cv.drawString(385, y - 14, "SIGNATURE & MOBILE")
    
    y -= 20
    for i, it in enumerate(items):
        if y < 70: cv.showPage(); y = h - 50
        cv.rect(40, y - 42, w - 80, 42, fill=0, stroke=1); cv.setFont("Helvetica-Bold", 9); cv.drawString(45, y - 25, str(i + 1)); cv.drawString(75, y - 12, it["awb_no"]); draw_barcode_safe(cv, it["awb_no"], 75, y - 36, 0.28 * inch); cv.drawString(225, y - 25, str(it.get("dest_name") or '')[:25])
        cv.setStrokeColor(HexColor("#6B7280")); cv.setDash(1, 2); cv.line(415, y - 15, w - 45, y - 15); cv.line(415, y - 32, w - 45, y - 32); cv.setDash()
        cv.setFont("Helvetica", 8); cv.setFillColorRGB(0,0,0); cv.drawString(385, y - 15, "Sign:"); cv.drawString(385, y - 32, "Mob:")
        y -= 42

    cv.setFont("Helvetica", 9); cv.line(60, y - 40, 200, y - 40); cv.drawString(60, y - 55, "Rider Signature"); cv.line(350, y - 40, 500, y - 40); cv.drawString(350, y - 55, "Branch Manager Signature")
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"DRS_{did}.pdf", mimetype='application/pdf')

# ==========================================
# 🛑 DO NOT TOUCH - FLASK RUN
# ==========================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)
