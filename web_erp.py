# ============================================================
# AGC ENTERPRISE ERP - COMPLETE MASTER CODE
# File: web_erp.py
# Version: 5.1 Enterprise Edition (Logo & Bug Fixes)
# ============================================================
from flask import Flask, request, session, redirect, url_for, render_template_string, flash, send_file, jsonify, abort
import pymysql, configparser, hashlib, io, os, csv, logging, json, datetime, threading, requests, secrets, hmac, re
from functools import wraps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.graphics.barcode import code128
from reportlab.lib.utils import ImageReader
try: import qrcode
except ImportError: qrcode = None

from markupsafe import escape
from werkzeug.security import generate_password_hash, check_password_hash

# ==========================================
# 🛡️ LOGGING & CONFIG
# ==========================================
logging.basicConfig(filename='agc_erp.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    # Development fallback: sessions are invalidated on every restart.
    # Production deployments must set a persistent SECRET_KEY.
    SECRET_KEY = secrets.token_hex(32)
    logging.warning("SECRET_KEY is not configured; using an ephemeral development key.")
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', 'false').lower() == 'true',
)
config = configparser.ConfigParser()
config.read('db_config.ini')

# ==========================================
# 🔧 HELPER FUNCTIONS & AUTO HEAL DB
# ==========================================
def safe_float(val):
    try: return float(val) if val else 0.0
    except: return 0.0

def safe_int(val):
    try: return int(val) if val else 0
    except: return 0

def csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token

app.jinja_env.globals['csrf_token'] = csrf_token

@app.before_request
def validate_csrf():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
        
    # 🚀 API FIX: Desktop app ki naye API routes ko CSRF check se azaad karein
    if request.endpoint in ('login', 'track', 'sync_download', 'sync_smart', 'force_upload'):
        return
        
    # Standard web pages par protection active rahegi
    supplied = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    expected = session.get('_csrf_token')
    if not supplied or not expected or not hmac.compare_digest(supplied, expected):
        abort(400, description='Invalid or missing CSRF token.')

from dbutils.pooled_db import PooledDB
import pymysql

# ==========================================
# 🚀 DATABASE CONNECTION POOLING (HIGH PERFORMANCE)
# ==========================================
db_pool = None

def init_db_pool():
    global db_pool
    try:
        if config.has_section('CLOUD_DB'):
            db_pool = PooledDB(
                creator=pymysql,
                maxconnections=30,  # Max 30 concurrent connections allowed
                mincached=2,        # Hamesha 2 connections ready rahenge
                maxcached=10,
                blocking=True,      # Agar limit cross hui, toh wait karega (crash nahi hoga)
                host=config['CLOUD_DB']['host'].strip().strip('"').strip("'"),
                port=int(config['CLOUD_DB']['port'].strip().strip('"').strip("'")),
                user=config['CLOUD_DB']['user'].strip().strip('"').strip("'"),
                password=config['CLOUD_DB']['password'].strip().strip('"').strip("'"),
                database=config['CLOUD_DB']['database'].strip().strip('"').strip("'"),
                cursorclass=pymysql.cursors.DictCursor,
                ssl={'ssl': {}},
                ping=1  # Hamesha ping karke check karega ki connection zinda hai ya nahi
            )
        else:
            db_pool = PooledDB(
                creator=pymysql, maxconnections=20, blocking=True, ping=1,
                host='localhost', port=3306, user='root', password='', 
                database='agc_erp', cursorclass=pymysql.cursors.DictCursor
            )
    except Exception as e:
        logging.error(f"Pool Init Error: {e}")
        raise

# Server start hote hi pool initialize kar do
init_db_pool()

def get_db():
    """Ab naya connection banne ki jagah, ye sidha Pool se fast connection dega"""
    return db_pool.connection()

def auto_heal_db():
    try:
        conn = get_db()
        with conn.cursor() as c:
            c.execute("CREATE TABLE IF NOT EXISTS users (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(50), password_hash VARCHAR(100), full_name VARCHAR(100), role VARCHAR(50), branch_name VARCHAR(100), customer_id INT, phone VARCHAR(50), active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS customers (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(50), name VARCHAR(255), gstin VARCHAR(50), phone VARCHAR(50), email VARCHAR(100), state VARCHAR(100), state_code VARCHAR(10), address TEXT, credit_limit DOUBLE DEFAULT 0, is_active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS rates (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, origin_state_code VARCHAR(10), dest_state_code VARCHAR(10), min_weight DOUBLE, max_weight DOUBLE, fixed_charge DOUBLE, per_kg_rate DOUBLE, gst_rate DOUBLE, active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS settings (key_name VARCHAR(100) PRIMARY KEY, value TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS sequences (name VARCHAR(50) PRIMARY KEY, value INT)")
            c.execute("CREATE TABLE IF NOT EXISTS stations (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) UNIQUE)")
            c.execute("CREATE TABLE IF NOT EXISTS expenses (id INT AUTO_INCREMENT PRIMARY KEY, expense_date DATE, category VARCHAR(100), amount DOUBLE, paid_to VARCHAR(255), mode VARCHAR(50), notes TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS ledger (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, entry_date DATE, voucher_type VARCHAR(50), reference VARCHAR(100), debit DOUBLE DEFAULT 0, credit DOUBLE DEFAULT 0, narration TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, invoice_id INT, payment_date DATE, amount DOUBLE, mode VARCHAR(50), reference VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS invoices (id INT AUTO_INCREMENT PRIMARY KEY, invoice_no VARCHAR(100), invoice_date DATE, customer_id INT, taxable_amount DOUBLE DEFAULT 0, cgst DOUBLE DEFAULT 0, sgst DOUBLE DEFAULT 0, igst DOUBLE DEFAULT 0, total DOUBLE DEFAULT 0, status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS invoice_lines (id INT AUTO_INCREMENT PRIMARY KEY, invoice_id INT, description TEXT, shipment_id INT, taxable_amount DOUBLE DEFAULT 0, cgst DOUBLE DEFAULT 0, sgst DOUBLE DEFAULT 0, igst DOUBLE DEFAULT 0, total DOUBLE DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS shipments (id INT AUTO_INCREMENT PRIMARY KEY, awb_no VARCHAR(100) UNIQUE, customer_id INT, booking_date DATE, origin_name VARCHAR(100), origin_phone VARCHAR(50), origin_address TEXT, origin_state_code VARCHAR(10), dest_name VARCHAR(100), dest_phone VARCHAR(50), dest_address TEXT, dest_state_code VARCHAR(10), dest_station VARCHAR(100), weight_kg DOUBLE, quantity INT, cod_amount DOUBLE, declared_value DOUBLE, service_type VARCHAR(50), taxable_amount DOUBLE, tax_rate DOUBLE, cgst DOUBLE, sgst DOUBLE, igst DOUBLE, total_amount DOUBLE, status VARCHAR(50), current_location VARCHAR(100), info TEXT, pod_photo TEXT, is_synced INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS scan_events (id INT AUTO_INCREMENT PRIMARY KEY, shipment_id INT, scan_type VARCHAR(50), location VARCHAR(100), remarks TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS outward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), out_station VARCHAR(100), destination VARCHAR(100), weight VARCHAR(50), network VARCHAR(100) DEFAULT 'SELF', network_awb VARCHAR(100), info TEXT, outward_no VARCHAR(100), manifest_no VARCHAR(100), finalized INT DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS inward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), in_station VARCHAR(100), weight VARCHAR(50), info TEXT, finalized INT DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS manifests (id INT AUTO_INCREMENT PRIMARY KEY, manifest_no VARCHAR(100), manifest_type VARCHAR(50), from_location VARCHAR(100), to_location VARCHAR(100), vehicle_no VARCHAR(100), status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS manifest_items (id INT AUTO_INCREMENT PRIMARY KEY, manifest_id INT, shipment_id INT, received INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS drs (id INT AUTO_INCREMENT PRIMARY KEY, drs_no VARCHAR(100), drs_date DATE, rider_name VARCHAR(100), rider_phone VARCHAR(50), vehicle_no VARCHAR(100), status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            
            # Auto-patch existing cloud database
            try: c.execute("ALTER TABLE drs ADD COLUMN rider_phone VARCHAR(50) AFTER rider_name")
            except: pass

            c.execute("CREATE TABLE IF NOT EXISTS drs_items (id INT AUTO_INCREMENT PRIMARY KEY, drs_id INT, shipment_id INT, status VARCHAR(50), receiver_name VARCHAR(100), remarks TEXT, pod_photo TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS master_bags (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100) UNIQUE, destination VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS master_bag_items (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100), awb_no VARCHAR(100))")
            
            # ✅ FIX: Missing delivery_register table added for DRS
            c.execute("CREATE TABLE IF NOT EXISTS delivery_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, delivery_boy VARCHAR(100), delivery_area VARCHAR(100), awb_no VARCHAR(100), receiver_name VARCHAR(100), info TEXT, finalized INT DEFAULT 0, drs_no VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")

            # 🚀 SYNC FIX: Add missing 'updated_at' to cloud shipments table for Smart Sync
            try: c.execute("ALTER TABLE shipments ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
            except: pass

            # 🚀 OUTWARD SYNC FIX: Ensure Cloud has the same outward columns as Desktop to prevent Force Upload crash
            try: c.execute("ALTER TABLE outward_register ADD COLUMN pcs INT DEFAULT 1")
            except: pass
            try: c.execute("ALTER TABLE outward_register ADD COLUMN bag_no VARCHAR(100)")
            except: pass
            
            try: c.execute("ALTER TABLE settings CHANGE `key` key_name VARCHAR(100)")
            except: pass
            
            # ✅ FIX: Trailing spaces removed from keys
            defs = {
                "company_name": "PANKAJ AGENCY COURIER",
                "company_address": "Nohar, Rajasthan",
                "company_gstin": "08ADQPC7585D1Z9",
                "company_phone": "+91 7357073316",
                "company_state_code": "08",
                "company_email": "PANKAJNOHAR@YAHOO.CO.IN",
                "bank_details": "SBI Bank | A/C: 31069139910 | IFSC: SBIN011303",
                "terms_note": "Liability limited to declared value.",
                "fuel_surcharge": "0"
            }
            for k, v in defs.items(): 
                c.execute("INSERT IGNORE INTO settings(key_name, value) VALUES(%s, %s)", (k, v))
        
        conn.commit()
        conn.close()
    except Exception as e: 
        logging.error(f"Heal Error: {e}")

def get_setting(key, default=""):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key_name=%s", (key,))
        r = c.fetchone(); conn.close()
        return r['value'] if r else default
    except: return default

def get_seq(name, prefix, length):
    conn = get_db(); c = conn.cursor()
    try:
        # Atomic increment prevents duplicate document numbers under concurrent requests.
        c.execute(
            "INSERT INTO sequences(name,value) VALUES(%s, LAST_INSERT_ID(1)) "
            "ON DUPLICATE KEY UPDATE value=LAST_INSERT_ID(value+1)",
            (name,)
        )
        c.execute("SELECT LAST_INSERT_ID() AS value")
        val = c.fetchone()["value"]
        conn.commit()
    finally:
        c.close()
        conn.close()
    return f"{prefix}{val:0{length}d}"

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ✅ FIX: Logo Serve Route
@app.route('/logo.png')
def serve_logo():
    if os.path.exists('logo.png'):
        return send_file('logo.png', mimetype='image/png')
    return "Logo not found", 404

# ==========================================
# 🎨 ENTERPRISE THEME (MODERN SAAS UI)
# ==========================================
AGCS_BASE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} | AGC ERP</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
    <style>
        body{font-family:'Inter',system-ui,sans-serif;background:#f1f5f9}
        .sidebar-link{transition:.2s}.sidebar-link:hover,.sidebar-link.active{background:#1e293b;color:#38bdf8;border-left:3px solid #38bdf8}
        .card{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.05);border:1px solid #e2e8f0}
        .btn-primary{background:#2563eb;color:#fff;padding:8px 16px;border-radius:6px;font-weight:500;border:none;cursor:pointer;display:inline-block;text-decoration:none;font-size:14px}
        .btn-primary:hover{background:#1d4ed8}
        .btn-danger{background:#ef4444;color:#fff;padding:8px 16px;border-radius:6px;font-weight:500;border:none;cursor:pointer;font-size:14px}
        .btn-success{background:#16a34a;color:#fff;padding:8px 16px;border-radius:6px;font-weight:500;border:none;cursor:pointer;font-size:14px}
        .btn-warning{background:#f59e0b;color:#fff;padding:8px 16px;border-radius:6px;font-weight:500;border:none;cursor:pointer;font-size:14px}
        .input-modern{width:100%;padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:14px;box-sizing:border-box;background:#fff}
        .input-modern:focus{outline:none;border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.1)}
        .label-modern{font-size:12px;font-weight:600;color:#475569;margin-bottom:4px;display:block}
        .datatable{width:100%;border-collapse:collapse;font-size:13px;background:#fff}
        .datatable th{background:#f8fafc;color:#475569;font-weight:600;text-align:left;padding:10px 12px;border-bottom:2px solid #e2e8f0}
        .datatable td{padding:10px 12px;border-bottom:1px solid #f1f5f9;color:#334155}
        .datatable tr:hover{background:#f8fafc}
        .tab-btn{padding:10px 20px;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:6px 6px 0 0;cursor:pointer;font-weight:500;color:#475569;font-size:13px}
        .tab-btn.active{background:#2563eb;color:#fff;border-color:#2563eb}
        .tab-content{display:none}.tab-content.active{display:block}
        .modal{display:none;position:fixed;z-index:1000;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,.6);overflow-y:auto}
        .modal-content{background:#fff;margin:5% auto;padding:24px;border:1px solid #e2e8f0;width:600px;max-width:90%;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.3)}
    </style>
</head>
<body class="bg-slate-100 text-slate-800">
<aside class="fixed top-0 left-0 z-40 w-64 h-screen bg-slate-900 text-slate-300 overflow-y-auto">
    <div class="p-5 border-b border-slate-800 flex items-center gap-3">
        <!-- ✅ LOGO INTEGRATION -->
        <div class="w-10 h-10 bg-white rounded-lg flex items-center justify-center text-blue-600 font-bold text-xl overflow-hidden p-1 shadow-sm">
            <img src="/logo.png" onerror="this.style.display='none'; this.parentElement.innerText='A'" class="w-full h-full object-contain">
        </div>
        <div> <h1 class="text-white font-bold text-lg leading-tight">AGC ERP</h1> <p class="text-xs text-slate-500">Enterprise Courier</p> </div>
    </div>
    <nav class="p-4 space-y-1 text-sm">
        <a href="/" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-chart-line w-5"></i> Dashboard </a>
        {% if session.get('role') == 'CUSTOMER' %}
        <a href="/booking" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-plus-circle w-5"></i> New Booking </a>
        <a href="/customer_bulk" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-file-excel w-5"></i> Bulk Upload </a>
        <a href="/pickup" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-truck-pickup w-5"></i> Request Pickup </a>
        <a href="/address_book" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-address-book w-5"></i> Address Book </a>
        <a href="/developer_api" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-code w-5"></i> API & Integration </a>
        <a href="/shipments" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-box w-5"></i> My Shipments </a>
        <a href="/my_ledger" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-wallet w-5"></i> My Ledger </a>
        <a href="/wallet" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-rupee-sign w-5"></i> My Wallet </a>
        {% else %}
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-4 mb-2 px-3">Master Entries</div>
        <a href="/customers" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-building w-5"></i> Franchisee Master </a>
        <a href="/cargo_master" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-handshake w-5"></i> Cargo Party </a>
        <a href="/credit_party" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-credit-card w-5"></i> Credit Party </a>
        <a href="/location_master" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-map-marker-alt w-5"></i> Locations </a>
        <a href="/rates" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-tags w-5"></i> Rate Master </a>
        <a href="/stationery" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-barcode w-5"></i> Shipper/Barcode </a>
        <a href="/delivery_boy" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-motorcycle w-5"></i> Delivery Boys </a>
        <a href="/users" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-users-cog w-5"></i> User Setup </a>
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-4 mb-2 px-3">Transactions</div>
        <a href="/booking" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-file-invoice w-5"></i> Counter Booking </a>
        <a href="/inward" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-sign-in-alt w-5"></i> Cargo Inward </a>
        <a href="/outward" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-sign-out-alt w-5"></i> Outward Hub </a>
        <a href="/manage_pickups" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-people-carry w-5"></i> Pickup Requests </a>
        <a href="/master_bag" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-shopping-bag w-5"></i> Master Bag </a>
        <a href="/drs" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-clipboard-list w-5"></i> D.R.S. Entry </a>
        <a href="/invoices" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-file-contract w-5"></i> Account Bill </a>
        <a href="/accounts" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-book w-5"></i> Cash/Bank Book </a>
        <a href="/expenses" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-receipt w-5"></i> Journal Voucher </a>
        <a href="/party_ledger" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-balance-scale w-5"></i> Party Ledger </a>
        <a href="/manage_wallets" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-wallet w-5"></i> Manage Wallets </a>
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-4 mb-2 px-3">Reports</div>
        <a href="/reports" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-chart-bar w-5"></i> Reports Hub </a>
        <a href="/shipments" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-list w-5"></i> Delivery Status </a>
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-4 mb-2 px-3">Utilities</div>
        <a href="/import_csv" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-file-csv w-5"></i> CSV Import </a>
        <a href="/settings" class="sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg"> <i class="fas fa-cog w-5"></i> Settings </a>
        {% endif %}
    </nav>
</aside>
<div class="ml-64 min-h-screen flex flex-col">
    <header class="bg-white shadow-sm h-16 flex items-center justify-between px-6 sticky top-0 z-30 border-b border-slate-200">
        <h2 class="text-lg font-semibold text-slate-800">{{ title }}</h2>
        <div class="flex items-center gap-6">
            <form action="/track_doc" method="POST" target="_blank" class="flex items-center bg-slate-100 rounded-lg px-3 py-2">
                <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
                <i class="fas fa-search text-slate-400 mr-2"></i>
                <input type="text" name="awb" placeholder="Track AWB/DRS/Invoice..." class="bg-transparent outline-none text-sm w-56">
                <input type="hidden" name="doc_type" value="c_note">
            </form>
            <div class="flex items-center gap-3 pl-6 border-l border-slate-200">
                <div class="text-right"> <p class="text-sm font-semibold text-slate-800">{{ session.get('full_name','Admin') }}</p> <p class="text-xs text-slate-500">{{ session.get('role') }} | {{ session.get('branch','HQ') }}</p> </div>
                <a href="/logout" class="w-9 h-9 bg-red-50 text-red-500 rounded-full flex items-center justify-center hover:bg-red-100"> <i class="fas fa-sign-out-alt"></i> </a>
            </div>
        </div>
    </header>
    <main class="p-6 flex-1">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %} <div class="mb-4 space-y-2">{% for category, message in messages %} <div class="p-4 rounded-lg border {{ 'bg-green-50 border-green-200 text-green-800' if category == 'success' else 'bg-red-50 border-red-200 text-red-800' }}">{{ message }}</div>{% endfor %}</div>{% endif %}
        {% endwith %}
        {{ content | safe }}
    </main>
    <footer class="bg-white border-t border-slate-200 py-4 px-6 text-center text-xs text-slate-500"> &copy; 2026 AGC Pankaj Agency Enterprise ERP </footer>
</div>
<script>
$(document).ready(function(){if($('.datatable').length){$('.datatable').DataTable({ "pageLength":50, "order":[]});}});
</script>
</body>
</html>
"""
def render_page(title, content):
    # Individual module templates are rendered as strings. Add the token here so
    # every generated POST form is protected without duplicating it in every form.
    token_input = '<input type="hidden" name="_csrf_token" value="' + csrf_token() + '">'
    protected_content = re.sub(r'<form(\s[^>]*)?>', lambda m: '<form' + (m.group(1) or '') + '>' + token_input, content)
    return render_template_string(AGCS_BASE_HTML, title=title, content=protected_content)

# ==========================================
# 🛠️ DIRECT DATABASE FIX ROUTE (RUN ONCE)
# ==========================================
@app.route('/fix_db')
def fix_db():
    conn = get_db()
    messages = []
    try:
        with conn.cursor() as c:
            # 1. Fix Shipments Table
            try:
                c.execute("ALTER TABLE shipments ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
                messages.append("✅ shipments table: 'updated_at' successfully added!")
            except Exception as e:
                messages.append(f"⚠️ shipments issue: {str(e)}")
                
            # 2. Fix Outward Register Table (pcs)
            try:
                c.execute("ALTER TABLE outward_register ADD COLUMN pcs INT DEFAULT 1")
                messages.append("✅ outward_register table: 'pcs' successfully added!")
            except Exception as e:
                messages.append(f"⚠️ outward_register issue (pcs): {str(e)}")

            # 3. Fix Outward Register Table (bag_no)
            try:
                c.execute("ALTER TABLE outward_register ADD COLUMN bag_no VARCHAR(100)")
                messages.append("✅ outward_register table: 'bag_no' successfully added!")
            except Exception as e:
                messages.append(f"⚠️ outward_register issue (bag_no): {str(e)}")

        conn.commit()
    except Exception as e:
        messages.append(f"❌ Connection Error: {str(e)}")
    finally:
        conn.close()
        
    html = "<body style='font-family: Arial; padding: 40px; line-height: 1.6;'>"
    html += "<h2>Cloud Database Diagnostic & Fix Tool</h2><ul>"
    for m in messages:
        html += f"<li>{m}</li>"
    html += "</ul><h3>🔥 Done! Ab aap apne Desktop app se Sync ya 'Master Force Upload' try karein!</h3></body>"
    
    return html

# ==========================================
# 🔐 LOGIN / LOGOUT
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '')
        p = request.form.get('password', '')
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s AND active=1", (u,))
        r = c.fetchone()
        
        if r:
            is_valid = False
            # Check 1: Old SHA256 Logic (Auto-upgrade to new secure hash if matched)
            if r['password_hash'] == hashlib.sha256(p.encode()).hexdigest():
                is_valid = True
                # Automatically secure the password for future logins
                from werkzeug.security import generate_password_hash
                new_secure_hash = generate_password_hash(p)
                c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_secure_hash, r['id']))
                conn.commit()
            # Check 2: New Secure PBKDF2 Hash Logic
            else:
                from werkzeug.security import check_password_hash
                if check_password_hash(r['password_hash'], p):
                    is_valid = True

            if is_valid:
                session.clear()
                user_id = r.get('id', 1)
                session.update({
                    'user_id': user_id, 'username': u,
                    'full_name': r.get('full_name', 'Admin') if r else 'Admin',
                    'role': r.get('role', 'ADMIN') if r else 'ADMIN',
                    'branch': str(r.get('branch_name', 'HQ')) if r else 'HQ',
                    'customer_id': r.get('customer_id') if r else None
                })
                conn.close()
                return redirect(url_for('dashboard'))
                
        flash('Invalid Credentials!', 'error')
        conn.close()
    
    login_html = """<!DOCTYPE html>
<html>
<head><title>Login | AGC ERP</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-900 flex items-center justify-center min-h-screen">
    <div class="bg-white p-8 rounded-2xl shadow-2xl w-96">
        <div class="text-center mb-6">
            <div class="w-20 h-20 bg-white rounded-2xl flex items-center justify-center text-blue-600 text-2xl font-bold mx-auto mb-3 overflow-hidden p-2 shadow-md">
                <img src="/logo.png" onerror="this.style.display='none'; this.parentElement.innerText='A'" class="w-full h-full object-contain">
            </div>
            <h1 class="text-2xl font-bold text-slate-800">AGC Enterprise</h1>
            <p class="text-slate-500 text-sm">Login Portal</p>
        </div>
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}<div class="mb-4 p-3 bg-red-50 text-red-600 text-sm rounded-lg border border-red-200">{% for category, message in messages %}{{ message }}{% endfor %}</div>{% endif %}
        {% endwith %}
        <form method="POST" class="space-y-4">
            <div><label class="block text-sm font-medium text-slate-700 mb-1">Username</label><input type="text" name="username" required class="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"></div>
            <div><label class="block text-sm font-medium text-slate-700 mb-1">Password</label><input type="password" name="password" required class="w-full px-4 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"></div>
            <button type="submit" class="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700">Sign In</button>
        </form>
    </div>
</body>
</html>"""
    return render_template_string(login_html)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# 📊 DASHBOARD
# ==========================================
@app.route('/')
@login_required
def dashboard():
    conn = get_db(); c = conn.cursor(); params = []
    if session.get('role') == 'CUSTOMER':
        cid = session.get('customer_id')
        q_s = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE customer_id=%s"
        q_d = "SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED' AND customer_id=%s"
        params.append(cid)
        c.execute("SELECT COALESCE(SUM(debit-credit),0) o FROM ledger WHERE customer_id=%s", (cid,)); out = c.fetchone()
        rev = {'a': 0.0}
        c.execute("SELECT booking_date as dt, COUNT(id) as cnt FROM shipments WHERE customer_id=%s GROUP BY booking_date ORDER BY dt DESC LIMIT 7", (cid,))
        chart_data = c.fetchall()
    else:
        q_s = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE 1=1"
        q_d = "SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED'"
        c.execute("SELECT booking_date as dt, COUNT(id) as cnt FROM shipments GROUP BY booking_date ORDER BY dt DESC LIMIT 7")
        chart_data = c.fetchall()
        c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments "); rev = c.fetchone()
        c.execute("SELECT COALESCE(SUM(debit-credit),0) o FROM ledger "); out = c.fetchone()
    
    c.execute(q_s, tuple(params)); s = c.fetchone()
    c.execute(q_d, tuple(params)); d = c.fetchone()
    c.close(); conn.close()
    
    chart_labels = json.dumps([str(r['dt']) for r in chart_data][::-1])
    chart_values = json.dumps([r['cnt'] for r in chart_data][::-1])
    rev_val = safe_float(s['t']) if session.get('role')=='CUSTOMER' else safe_float(rev['a'] if rev else 0)
    rev_label = "Total Billing" if session.get('role')=='CUSTOMER' else "Revenue"
    
    html = f"""
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
        <div class="card p-6"> <div class="flex items-center justify-between"> <div> <p class="text-sm text-slate-500 font-medium">Total Shipments</p> <h3 class="text-2xl font-bold text-slate-800 mt-1">{safe_int(s['c'])}</h3> </div> <div class="w-12 h-12 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-xl"> <i class="fas fa-box"></i> </div> </div> </div>
        <div class="card p-6"> <div class="flex items-center justify-between"> <div> <p class="text-sm text-slate-500 font-medium">Delivered</p> <h3 class="text-2xl font-bold text-green-600 mt-1">{safe_int(d['c'])}</h3> </div> <div class="w-12 h-12 bg-green-100 text-green-600 rounded-full flex items-center justify-center text-xl"> <i class="fas fa-check-circle"></i> </div> </div> </div>
        <div class="card p-6"> <div class="flex items-center justify-between"> <div> <p class="text-sm text-slate-500 font-medium">{rev_label}</p> <h3 class="text-2xl font-bold text-slate-800 mt-1">₹ {rev_val:,.2f}</h3> </div> <div class="w-12 h-12 bg-purple-100 text-purple-600 rounded-full flex items-center justify-center text-xl"> <i class="fas fa-coins"></i> </div> </div> </div>
        <div class="card p-6"> <div class="flex items-center justify-between"> <div> <p class="text-sm text-slate-500 font-medium">Outstanding</p> <h3 class="text-2xl font-bold text-red-600 mt-1">₹ {safe_float(out['o']) if out else 0:,.2f}</h3> </div> <div class="w-12 h-12 bg-red-100 text-red-600 rounded-full flex items-center justify-center text-xl"> <i class="fas fa-exclamation-triangle"></i> </div> </div> </div>
    </div>
    <div class="card p-6"> <h3 class="text-lg font-bold text-slate-800 mb-4">Last 7 Days Performance</h3> <script src="https://cdn.jsdelivr.net/npm/chart.js"></script> <canvas id="dashChart" height="80"></canvas> </div>
    <script>new Chart(document.getElementById('dashChart').getContext('2d'),{{type:'bar',data:{{labels:{chart_labels},datasets:[{{label:'Parcels',data:{chart_values},backgroundColor:'#3b82f6',borderRadius:6}}]}},options:{{responsive:true,plugins:{{legend:{{display:false}}}}}}}});</script>
    """
    return render_page("Dashboard", html)

# ==========================================
# 🌍 NETWORK TRACKING
# ==========================================
def fetch_network_tracking(network_name, network_awb):
    events = []
    try:
        events.append({'scan_type': 'NETWORK DISPATCH', 'location': f'Forwarded to {network_name}', 'f_date': datetime.datetime.now().strftime('%d-%b-%Y %I:%M %p'), 'remarks': f"Partner AWB: {network_awb}"})
    except Exception as e: logging.error(f"Network API: {e}")
    return events

@app.route('/track', methods=['GET', 'POST'])
def track():
    awb = (request.args.get('awb') or request.form.get('awb') or '').strip().upper()
    events = []; shipment = None; error_msg = None
    if awb:
        try:
            conn = get_db()
            with conn.cursor() as c:
                c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
                shipment = c.fetchone()
                if shipment:
                    c.execute("SELECT scan_type, location, remarks, DATE_FORMAT(created_at, '%%d-%%b-%%Y %%h:%%i %%p') as f_date FROM scan_events WHERE shipment_id=%s ORDER BY id DESC", (shipment['id'],))
                    events = list(c.fetchall())
                    c.execute("SELECT network, network_awb FROM outward_register WHERE awb_no=%s AND network != 'SELF' ORDER BY id DESC LIMIT 1", (awb,))
                    od = c.fetchone()
                    if od and od['network_awb']: events = fetch_network_tracking(od['network'], od['network_awb']) + events

                    # 🚀 THE FIX: Clean up "None" values for a professional Display
                    # 1. Fix Origin (If empty, fetch from Outward Register)
                    if not shipment.get('origin_name') or str(shipment['origin_name']).lower() == 'none':
                        c.execute("SELECT origin_station FROM outward_register WHERE awb_no=%s ORDER BY id ASC LIMIT 1", (awb,))
                        orig_row = c.fetchone()
                        shipment['origin_name'] = orig_row['origin_station'] if orig_row else 'Hub / Branch'
                    
                    # 2. Fix Destination (Use Dest Station if Dest Name is empty)
                    if not shipment.get('dest_name') or str(shipment['dest_name']).lower() == 'none':
                        shipment['dest_name'] = shipment.get('dest_station') or 'Not Specified'
                        
                    # 3. Clean Date Format (Remove 00:00:00)
                    if shipment.get('booking_date'):
                        shipment['booking_date'] = str(shipment['booking_date']).split(' ')[0]

        except Exception as e: 
            error_msg = str(e)
        finally:
            if 'conn' in locals():
                try: conn.close()
                except: pass
            
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Track Shipment | AGC ERP</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Inter', sans-serif; background-color: #f8fafc; }
            .glass-card { background: #ffffff; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03); }
            .timeline-dot { box-shadow: 0 0 0 4px #ffffff; }
        </style>
    </head>
    <body class="text-slate-800 antialiased min-h-screen flex flex-col">
        
        <!-- Top Navbar -->
        <nav class="bg-slate-900 text-white shadow-md">
            <div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex items-center justify-between h-16">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 bg-white rounded-lg flex items-center justify-center text-blue-600 font-bold text-xl overflow-hidden p-1">
                            <img src="/logo.png" onerror="this.style.display='none'; this.parentElement.innerText='AGC'" class="w-full h-full object-contain">
                        </div>
                        <span class="font-bold text-xl tracking-tight">AGC Logistics</span>
                    </div>
                </div>
            </div>
        </nav>

        <!-- Main Content -->
        <main class="flex-1 max-w-5xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-10 md:py-14">
            
            <!-- Search Section -->
            <div class="text-center mb-12">
                <h1 class="text-3xl md:text-4xl font-extrabold text-slate-900 mb-3 tracking-tight">Track Your Shipment</h1>
                <p class="text-slate-500 mb-8 font-medium">Enter your AWB or Reference Number to get real-time status.</p>
                
                <form method="GET" action="/track" class="max-w-2xl mx-auto flex shadow-xl rounded-xl overflow-hidden bg-white border border-slate-200 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500 transition-all">
                    <div class="flex items-center pl-5 text-slate-400"><i class="fas fa-search text-lg"></i></div>
                    <input type="text" name="awb" value="{{ awb }}" placeholder="Enter AWB Number..." class="flex-1 px-4 py-4 md:py-5 outline-none text-slate-700 font-bold uppercase text-lg" required>
                    <button type="submit" class="bg-blue-600 hover:bg-blue-700 text-white px-8 md:px-10 py-4 md:py-5 font-bold transition-colors text-lg">TRACK</button>
                </form>
            </div>

            {% if error_msg %}
            <div class="max-w-2xl mx-auto bg-red-50 border-l-4 border-red-500 p-4 rounded-r-lg shadow-sm mb-8">
                <div class="flex items-center">
                    <i class="fas fa-exclamation-circle text-red-500 text-xl mr-3"></i>
                    <p class="text-red-700 font-medium">{{ error_msg }}</p>
                </div>
            </div>
            {% elif awb and not shipment %}
            <div class="max-w-2xl mx-auto bg-amber-50 border-l-4 border-amber-500 p-8 rounded-r-lg shadow-sm mb-8 text-center">
                <i class="fas fa-box-open text-amber-400 text-5xl mb-4"></i>
                <h3 class="text-amber-800 font-bold text-xl">No Shipment Found!</h3>
                <p class="text-amber-700 mt-2 font-medium">Please check your AWB number and try again. It might take some time to update.</p>
            </div>
            {% elif shipment %}
            
            <!-- Dynamic Progress Bar Logic -->
            {% set status = shipment.status %}
            {% set progress = 10 %}
            {% set bar_color = 'bg-blue-500' %}
            
            {% if status == 'OUTWARD' or status == 'INWARD' %}{% set progress = 50 %}{% endif %}
            {% if status == 'ON_DRS' %}{% set progress = 80 %}{% endif %}
            {% if status == 'DELIVERED' %}{% set progress = 100 %}{% set bar_color = 'bg-green-500' %}{% endif %}
            {% if status == 'CANCELLED' %}{% set progress = 100 %}{% set bar_color = 'bg-red-500' %}{% endif %}
            {% if status == 'UNDELIVERED' %}{% set progress = 80 %}{% set bar_color = 'bg-orange-500' %}{% endif %}

            <div class="glass-card rounded-2xl p-6 md:p-8 mb-8">
                <!-- Header Info -->
                <div class="flex flex-col md:flex-row md:items-center justify-between border-b border-slate-100 pb-6 mb-8">
                    <div>
                        <p class="text-slate-400 text-xs font-bold uppercase tracking-wider mb-1">AWB Number</p>
                        <h2 class="text-3xl font-black text-slate-800 tracking-tight">
                            {{ shipment.awb_no }}
                        </h2>
                    </div>
                    <div class="mt-4 md:mt-0 text-left md:text-right">
                        <p class="text-slate-400 text-xs font-bold uppercase tracking-wider mb-1">Current Status</p>
                        <span class="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold uppercase tracking-wider border
                            {% if status == 'DELIVERED' %}bg-green-50 text-green-700 border-green-200
                            {% elif status == 'CANCELLED' %}bg-red-50 text-red-700 border-red-200
                            {% elif status == 'ON_DRS' %}bg-blue-50 text-blue-700 border-blue-200
                            {% elif status == 'UNDELIVERED' %}bg-orange-50 text-orange-700 border-orange-200
                            {% else %}bg-indigo-50 text-indigo-700 border-indigo-200{% endif %} shadow-sm">
                            {% if status == 'DELIVERED' %}<i class="fas fa-check-circle"></i>
                            {% elif status == 'CANCELLED' %}<i class="fas fa-times-circle"></i>
                            {% elif status == 'ON_DRS' %}<i class="fas fa-motorcycle"></i>
                            {% else %}<i class="fas fa-truck-fast"></i>{% endif %}
                            {{ status|replace('_', ' ') }}
                        </span>
                    </div>
                </div>

                <!-- Visual Progress Bar -->
                <div class="mb-10 px-2">
                    <div class="w-full bg-slate-100 rounded-full h-3 mb-4 relative overflow-hidden shadow-inner">
                        <div class="{{ bar_color }} h-3 rounded-full transition-all duration-1000 ease-out" style="width: {{ progress }}%"></div>
                    </div>
                    <div class="flex justify-between text-[11px] md:text-xs font-bold text-slate-400 uppercase tracking-wider">
                        <span class="{% if progress >= 10 %}text-slate-800{% endif %}">Booked</span>
                        <span class="{% if progress >= 50 %}text-slate-800{% endif %} text-center">In Transit</span>
                        <span class="{% if progress >= 80 %}text-slate-800{% endif %} text-center">Out for Delivery</span>
                        <span class="{% if progress == 100 %}text-slate-800{% endif %} text-right">Delivered</span>
                    </div>
                </div>

                <!-- Quick Details Grid -->
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 bg-slate-50 p-6 rounded-xl border border-slate-200 shadow-inner">
                    <div>
                        <div class="flex items-center gap-2 text-slate-500 mb-2">
                            <i class="fas fa-plane-departure text-slate-400"></i>
                            <span class="text-xs font-bold uppercase tracking-wider">Origin</span>
                        </div>
                        <p class="font-bold text-slate-800 truncate" title="{{ shipment.origin_name }}">{{ shipment.origin_name }}</p>
                    </div>
                    <div>
                        <div class="flex items-center gap-2 text-slate-500 mb-2">
                            <i class="fas fa-location-dot text-slate-400"></i>
                            <span class="text-xs font-bold uppercase tracking-wider">Destination</span>
                        </div>
                        <p class="font-bold text-slate-800 truncate" title="{{ shipment.dest_name }}">{{ shipment.dest_name }}</p>
                    </div>
                    <div>
                        <div class="flex items-center gap-2 text-slate-500 mb-2">
                            <i class="fas fa-calendar-alt text-slate-400"></i>
                            <span class="text-xs font-bold uppercase tracking-wider">Booked On</span>
                        </div>
                        <p class="font-bold text-slate-800">{{ shipment.booking_date }}</p>
                    </div>
                    <div>
                        <div class="flex items-center gap-2 text-slate-500 mb-2">
                            <i class="fas fa-weight-scale text-slate-400"></i>
                            <span class="text-xs font-bold uppercase tracking-wider">Weight / Pcs</span>
                        </div>
                        <p class="font-bold text-slate-800">{{ shipment.weight_kg }} KG <span class="text-slate-500 font-semibold ml-1">({{ shipment.quantity }} Pcs)</span></p>
                    </div>
                </div>
            </div>

            <!-- Vertical Timeline Section -->
            <div class="glass-card rounded-2xl p-6 md:p-8">
                <h3 class="text-xl font-extrabold text-slate-800 mb-8 flex items-center gap-3 border-b border-slate-100 pb-4">
                    <i class="fas fa-history text-blue-600"></i> Detailed Tracking History
                </h3>
                
                {% if not events %}
                <div class="text-center py-8">
                    <i class="fas fa-hourglass-empty text-5xl text-slate-200 mb-4"></i>
                    <p class="text-slate-500 font-medium text-lg">Tracking history is being updated.</p>
                </div>
                {% else %}
                <div class="relative border-l-2 border-slate-200 ml-4 md:ml-6 pb-4">
                    {% for e in events %}
                    
                    <!-- Dynamic Icon & Color Logic -->
                    {% set icon_color = 'bg-slate-400' %}
                    {% set icon_class = 'fa-circle' %}
                    
                    {% if e.scan_type == 'BOOKED' %}{% set icon_color = 'bg-blue-500' %}{% set icon_class = 'fa-box' %}{% endif %}
                    {% if e.scan_type == 'OUTWARD' %}{% set icon_color = 'bg-indigo-500' %}{% set icon_class = 'fa-truck-fast' %}{% endif %}
                    {% if e.scan_type == 'INWARD' %}{% set icon_color = 'bg-teal-500' %}{% set icon_class = 'fa-building' %}{% endif %}
                    {% if e.scan_type == 'NETWORK DISPATCH' %}{% set icon_color = 'bg-purple-500' %}{% set icon_class = 'fa-network-wired' %}{% endif %}
                    {% if e.scan_type == 'ON_DRS' %}{% set icon_color = 'bg-amber-500' %}{% set icon_class = 'fa-motorcycle' %}{% endif %}
                    {% if e.scan_type == 'DELIVERED' %}{% set icon_color = 'bg-green-500' %}{% set icon_class = 'fa-check' %}{% endif %}
                    {% if e.scan_type == 'UNDELIVERED' %}{% set icon_color = 'bg-orange-500' %}{% set icon_class = 'fa-exclamation' %}{% endif %}
                    {% if e.scan_type == 'CANCELLED' %}{% set icon_color = 'bg-red-500' %}{% set icon_class = 'fa-times' %}{% endif %}

                    <div class="mb-8 ml-8 md:ml-10 relative">
                        <!-- Timeline Dot -->
                        <span class="timeline-dot absolute -left-12 md:-left-14 flex items-center justify-center w-8 h-8 rounded-full {{ icon_color }} text-white text-xs shadow-md">
                            <i class="fas {{ icon_class }}"></i>
                        </span>
                        
                        <!-- Content Card -->
                        <div class="bg-white border border-slate-100 rounded-xl p-4 md:p-5 shadow-sm hover:shadow-md transition-shadow">
                            <div class="flex flex-col md:flex-row md:justify-between md:items-center gap-2 mb-3">
                                <h4 class="text-base font-bold text-slate-800 uppercase tracking-wide">{{ e.scan_type|replace('_', ' ') }}</h4>
                                <span class="text-xs font-bold text-slate-500 flex items-center gap-2 bg-slate-100 px-3 py-1 rounded-full">
                                    <i class="far fa-clock"></i> {{ e.f_date }}
                                </span>
                            </div>
                            <p class="text-slate-700 font-semibold flex items-center gap-2 mb-2">
                                <i class="fas fa-map-marker-alt text-slate-400"></i> {{ e.location }}
                            </p>
                            {% if e.remarks %}
                            <p class="text-sm text-slate-600 mt-2 bg-slate-50 p-3 rounded-lg border border-slate-100 font-medium">
                                <i class="fas fa-info-circle text-blue-400 mr-2"></i> {{ e.remarks }}
                            </p>
                            {% endif %}
                        </div>
                    </div>
                    {% endfor %}
                </div>
                {% endif %}
            </div>
            {% endif %}
            
        </main>
        
        <!-- Footer -->
        <footer class="bg-slate-900 text-slate-400 py-6 text-center text-sm mt-auto border-t border-slate-800">
            <p class="font-medium">&copy; 2026 AGC Enterprise Logistics. All rights reserved.</p>
        </footer>
    </body>
    </html>
    """
    return render_template_string(html, awb=awb, shipment=shipment, events=events, error_msg=error_msg)

@app.route('/track_doc', methods=['POST'])
@login_required
def track_doc():
    doc_no = request.form.get('awb', '').strip().upper()
    doc_type = request.form.get('doc_type', '')
    err = "<html><body style='font-family:Inter;padding:40px;background:#fee2e2;color:#991b1b;text-align:center;'><h2>Error!</h2><p>{}</p><button onclick='window.close()' style='margin-top:10px;padding:10px 20px;background:#ef4444;color:white;border:none;border-radius:8px;'>Close</button></body></html>"
    if not doc_no: return err.format("Enter Document Number.")
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as c:
            if doc_type in ['c_note', 'pkg_slip']: return redirect(url_for('track', awb=doc_no))
            elif doc_type == 'drs':
                c.execute("SELECT * FROM drs WHERE drs_no=%s", (doc_no,))
                drs = c.fetchone()
                if drs:
                    c.execute("SELECT s.awb_no, di.receiver_name, s.dest_address, di.status FROM drs_items di JOIN shipments s ON s.id=di.shipment_id WHERE di.drs_id=%s", (drs['id'],))
                    items = c.fetchall()
                    rows_html = ""
                    
                    for i in items: 
                        # 🛡️ SECURITY FIX: Escape raw DB inputs to prevent HTML/JS execution
                        safe_awb = escape(i['awb_no'] or '')
                        safe_rec = escape(i['receiver_name'] or '')
                        safe_addr = escape(i['dest_address'] or '')
                        safe_status = escape(i['status'] or '')
                        rows_html += f"<tr><td>{safe_awb}</td><td>{safe_rec}</td><td>{safe_addr}</td><td>{safe_status}</td></tr>"
                    
                    # 🛡️ SECURITY FIX: Escape the DRS and Rider names as well
                    safe_drs_no = escape(drs['drs_no'] or '')
                    safe_rider = escape(drs['rider_name'] or '')
                    
                    return f"<html><body style='font-family:Inter;padding:20px;'><h2>DRS: {safe_drs_no} | Rider: {safe_rider}</h2><table border='1' cellpadding='8' style='border-collapse:collapse;width:100%;'><tr style='background:#2563eb;color:white;'><th>AWB</th><th>Receiver</th><th>Address</th><th>Status</th></tr>{rows_html}</table></body></html>"
                return err.format("DRS not found.")
            elif doc_type == 'invoice':
                c.execute("SELECT id FROM invoices WHERE invoice_no=%s", (doc_no,))
                inv = c.fetchone()
                if inv: return redirect(f"/print/invoice/{inv['id']}")
                return err.format("Invoice not found.")
    except Exception as e: 
        # Escape the error string to prevent injection via exception messages
        return err.format(escape(str(e)))
    finally: 
        if conn:
            try: conn.close()
            except: pass
    return err.format("Invalid type.")

# ==========================================
# 📱 PWA MANIFEST
# ==========================================
@app.route('/manifest.json')
def manifest():
    return jsonify({ "name": "AGC ERP", "short_name": "AGC", "start_url": "/", "display": "standalone", "background_color": "#0f172a", "theme_color": "#2563eb"})

#⚠ PART 1 ENDS HERE. PART 2 (Master Entries) agle message me aayega.

# ==========================================
# MASTER ENTRIES (Customers, Locations, Rates, Users, Settings)
# ==========================================
@app.route('/customers', methods=['GET', 'POST'])
@app.route('/cargo_master', methods=['GET', 'POST'])
@app.route('/credit_party', methods=['GET', 'POST'])
@login_required
def customers():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    page_type = 'cargo' if 'cargo' in request.path else ('credit' if 'credit' in request.path else 'franchisee')
    page_title = {'cargo': 'Cargo Party A/c Master', 'credit': 'Credit Party A/c Master', 'franchisee': 'Franchisee Master Setup'}[page_type]
    
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("UPDATE customers SET is_active=0 WHERE id=%s", (request.args.get('delete'),))
        conn.commit()
        flash("Record Deactivated Successfully!", "success")
        return redirect(request.path)
    if request.args.get('restore'):
        with conn.cursor() as c:
            c.execute("UPDATE customers SET is_active=1 WHERE id=%s", (request.args.get('restore'),))
        conn.commit()
        flash("Record Restored!", "success")
        return redirect(request.path)
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("""INSERT INTO customers(code, name, gstin, phone, email, state, state_code, address, credit_limit, is_active)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone',''),
                 d.get('email',''), d.get('state',''), d.get('scode',''), d.get('address',''),
                 safe_float(d.get('limit'))))
        conn.commit()
        flash(f"New Record Added in {page_title}!", "success")
        return redirect(request.path)
    
    with conn.cursor() as c:
        c.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id DESC")
        custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top:4px solid #2563eb;">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold text-slate-800">New Entry: {{ page_title }}</h3>
            <span class="px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-bold">Total Active: {{ custs|length }}</span>
        </div>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-2">
            <div><label class="label-modern">Party Code *</label><input type="text" name="code" class="input-modern" required></div>
            <div><label class="label-modern">Full Name *</label><input type="text" name="name" class="input-modern" required></div>
            <div><label class="label-modern">Phone</label><input type="text" name="phone" class="input-modern"></div>
            <div><label class="label-modern">Email</label><input type="email" name="email" class="input-modern"></div>
            <div><label class="label-modern">Address</label><input type="text" name="address" class="input-modern"></div>
            <div><label class="label-modern">State</label><input type="text" name="state" class="input-modern uppercase"></div>
            <div><label class="label-modern">State Code</label><input type="text" name="scode" class="input-modern uppercase" maxlength="2"></div>
            <div><label class="label-modern">GSTIN</label><input type="text" name="gstin" class="input-modern uppercase"></div>
            <div><label class="label-modern">Credit Limit (Rs)</label><input type="number" step="0.01" name="limit" class="input-modern" value="0.00"></div>
            <div class="flex items-end"><button type="submit" class="btn-primary w-full"><i class="fas fa-save"></i> Save Record</button></div>
        </form>
    </div>
    <div class="card">
        <h3 class="text-lg font-bold text-slate-800 mb-4">Registered Accounts</h3>
        <div class="table-responsive">
        <table class="datatable">
            <thead><tr><th>Code</th><th>Name</th><th>Phone</th><th>GSTIN</th><th>State</th><th>Credit Limit</th><th style="width:280px;">Actions</th></tr></thead>
            <tbody>
            {% for r in custs %}
            <tr>
                <td><span class="px-2 py-1 bg-slate-100 rounded font-bold">{{ r.code }}</span></td>
                <td class="font-semibold text-blue-600">{{ r.name }}</td>
                <td>{{ r.phone or '-' }}</td>
                <td>{{ r.gstin or '-' }}</td>
                <td>{{ r.state or '-' }} {% if r.state_code %}({{ r.state_code }}){% endif %}</td>
                <td class="text-red-600 font-bold">Rs {{ r.credit_limit }}</td>
                <td>
                    <a href="/edit_customer/{{ r.id }}" class="btn-primary" style="padding:4px 10px; font-size:11px;"><i class="fas fa-edit"></i> Edit</a>
                    <a href="/print/statement/{{ r.id }}" target="_blank" class="btn-warning" style="padding:4px 10px; font-size:11px;"><i class="fas fa-file-pdf"></i></a>
                    <a href="?delete={{ r.id }}" class="btn-danger" style="padding:4px 10px; font-size:11px;" onclick="return confirm('Delete this record?');"><i class="fas fa-trash"></i></a>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
    </div>
    """
    return render_page(
        page_title,
        render_template_string(
            html,
            custs=custs,
            page_title=page_title
        )
    )

# ==========================================
# ✏️ 2.2 EDIT CUSTOMER (DEDICATED EDIT PAGE) — FIXED SYNTAX
# ==========================================
@app.route('/edit_customer/<int:cid>', methods=['GET', 'POST'])
@login_required
def edit_customer(cid):
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM customers WHERE id=%s", (cid,))
        cust = c.fetchone()
        if not cust: 
            flash("Record Not Found!", "error")
            return redirect('/customers')
        if request.method == 'POST':
            d = request.form
            c.execute("""UPDATE customers SET code=%s, name=%s, gstin=%s, phone=%s, email=%s,
                state=%s, state_code=%s, address=%s, credit_limit=%s WHERE id=%s""",
                (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone',''),
                 d.get('email',''), d.get('state',''), d.get('scode',''), d.get('address',''),
                 safe_float(d.get('limit')), cid))
            conn.commit()
            flash("Record Updated Successfully!", "success")
            return redirect('/customers')
    conn.close()
    
    html = """
    <div class="card" style="max-width:800px; margin:0 auto; border-top:4px solid #f59e0b;">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold text-slate-800">Edit: <span class="text-blue-600">{{ cust.name }}</span></h3>
            <span class="px-3 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-bold">EDIT MODE</span>
        </div>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div><label class="label-modern">Party Code *</label><input type="text" name="code" value="{{ cust.code }}" class="input-modern" required></div>
            <div><label class="label-modern">Full Name *</label><input type="text" name="name" value="{{ cust.name }}" class="input-modern" required></div>
            <div><label class="label-modern">Phone</label><input type="text" name="phone" value="{{ cust.phone }}" class="input-modern"></div>
            <div><label class="label-modern">Email</label><input type="email" name="email" value="{{ cust.email }}" class="input-modern"></div>
            <div class="md:col-span-2"><label class="label-modern">Address</label><input type="text" name="address" value="{{ cust.address }}" class="input-modern"></div>
            <div><label class="label-modern">State</label><input type="text" name="state" value="{{ cust.state }}" class="input-modern uppercase"></div>
            <div><label class="label-modern">State Code</label><input type="text" name="scode" value="{{ cust.state_code }}" class="input-modern uppercase" maxlength="2"></div>
            <div><label class="label-modern">GSTIN</label><input type="text" name="gstin" value="{{ cust.gstin }}" class="input-modern uppercase"></div>
            <div><label class="label-modern">Credit Limit (Rs)</label><input type="number" step="0.01" name="limit" value="{{ cust.credit_limit }}" class="input-modern"></div>
            <div class="md:col-span-2 flex gap-3 mt-4">
                <button type="submit" class="btn-success flex-1"><i class="fas fa-save"></i> Update Record</button>
                <a href="/customers" class="btn-danger flex-1" style="text-align:center;">Cancel</a>
            </div>
        </form>
    </div>
    """
    return render_page(
        f"Edit: {cust['name']}",
        render_template_string(html, cust=cust)
    )

# ==========================================
# 📍 2.3 LOCATION MASTER (ADD + EDIT + DELETE)
# ==========================================
@app.route('/location_master', methods=['GET', 'POST'])
@login_required
def location_master():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    
    # 🗑️ DELETE
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM stations WHERE id=%s", (request.args.get('delete'),))
        conn.commit(); flash("Location Deleted!", "success"); return redirect('/location_master')
    
    # ➕ ADD
    if request.method == 'POST':
        name = request.form.get('name', '').strip().upper()
        if name:
            with conn.cursor() as c: c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (name,))
            conn.commit(); flash(f"✅ Location '{name}' Added!", "success")
    
    with conn.cursor() as c: c.execute("SELECT id, name FROM stations ORDER BY id DESC LIMIT 500"); stations_list = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card" style="border-top:4px solid #16a34a;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">➕ Add New Location</h3>
            <form method="POST" class="space-y-3">
                <div><label class="label-modern">Station / City Name *</label><input type="text" name="name" class="input-modern uppercase" required></div>
                <button type="submit" class="btn-success w-full"><i class="fas fa-plus"></i> Add Station</button>
            </form>
        </div>
        <div class="card lg:col-span-2">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📍 System Locations ({{ stations_list|length }})</h3>
            <div class="table-responsive" style="max-height:450px; overflow-y:auto;">
            <table class="datatable">
                <thead><tr><th>ID</th><th>Station Name</th><th style="width:180px;">Actions</th></tr></thead>
                <tbody>
                {% for r in s_list %}
                <tr>
                    <td>{{ r.id }}</td>
                    <td class="font-bold text-blue-600">{{ r.name }}</td>
                    <td>
                        <a href="/edit_location/{{ r.id }}" class="btn-primary" style="padding:4px 10px; font-size:11px;"><i class="fas fa-edit"></i> Edit</a>
                        <a href="/location_master?delete={{ r.id }}" class="btn-danger" style="padding:4px 10px; font-size:11px;" onclick="return confirm('Delete?');"><i class="fas fa-trash"></i></a>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
            </div>
        </div>
    </div>
    """
    return render_page("Location Master", render_template_string(html, s_list=stations_list))

# ✏️ EDIT LOCATION — FIXED SYNTAX
@app.route('/edit_location/<int:lid>', methods=['GET', 'POST'])
@login_required
def edit_location(lid):
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM stations WHERE id=%s", (lid,))
        loc = c.fetchone()
        if not loc: flash("Not found!", "error"); return redirect('/location_master')
        
        if request.method == 'POST':
            name = request.form.get('name','').strip().upper()
            c.execute("UPDATE stations SET name=%s WHERE id=%s", (name, lid))
            conn.commit(); flash("✅ Location Updated!", "success")
            return redirect('/location_master')
    conn.close()
    
    html = """
    <div class="card" style="max-width:500px; margin:0 auto; border-top:4px solid #f59e0b;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">✏️ Edit Location #{{ loc.id }}</h3>
        <form method="POST" class="space-y-3">
            <div><label class="label-modern">Station Name *</label><input type="text" name="name" value="{{ loc.name }}" class="input-modern uppercase" required></div>
            <div class="flex gap-3 mt-4">
                <button type="submit" class="btn-success flex-1"><i class="fas fa-save"></i> Update</button>
                <a href="/location_master" class="btn-danger flex-1" style="text-align:center;">Cancel</a>
            </div>
        </form>
    </div>
    """
    return render_page(f"Edit Location: {loc['name']}", render_template_string(html, loc=loc))

# ==========================================
# 💰 2.4 RATE MASTER (ADD + EDIT + DELETE)
# ==========================================
@app.route('/rates', methods=['GET', 'POST'])
@login_required
def rates():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    
    # 🗑️ DELETE
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM rates WHERE id=%s", (request.args.get('delete'),))
        conn.commit(); flash("Rate Deleted!", "success"); return redirect('/rates')
    
    # ➕ ADD
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("""INSERT INTO rates(customer_id, origin_state_code, dest_state_code, min_weight, max_weight, fixed_charge, per_kg_rate, gst_rate, active)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (safe_int(d.get('cust_id')) if d.get('cust_id') else None, d.get('ostate','').upper(), d.get('dstate','').upper(),
                 safe_float(d.get('min_wt')), safe_float(d.get('max_wt')), safe_float(d.get('fixed')),
                 safe_float(d.get('per_kg')), safe_float(d.get('gst'))))
        conn.commit(); flash("✅ Rate Chart Added!", "success")
    
    with conn.cursor() as c:
        c.execute("SELECT r.*, c.name as cname FROM rates r LEFT JOIN customers c ON r.customer_id=c.id ORDER BY r.id DESC"); rates_list = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top:4px solid #f59e0b;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">💰 Add New Rate Contract</h3>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div><label class="label-modern">Customer (Blank=Default)</label><select name="cust_id" class="input-modern"><option value="">-- DEFAULT RATE --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div>
            <div><label class="label-modern">Origin State *</label><input type="text" name="ostate" class="input-modern uppercase" required placeholder="RJ"></div>
            <div><label class="label-modern">Dest State *</label><input type="text" name="dstate" class="input-modern uppercase" required placeholder="HR"></div>
            <div><label class="label-modern">Min Weight</label><input type="number" step="0.01" name="min_wt" value="0.1" class="input-modern"></div>
            <div><label class="label-modern">Max Weight</label><input type="number" step="0.01" name="max_wt" value="50" class="input-modern"></div>
            <div><label class="label-modern">Fixed Charge (₹)</label><input type="number" step="0.01" name="fixed" value="50" class="input-modern"></div>
            <div><label class="label-modern">Per KG Rate (₹)</label><input type="number" step="0.01" name="per_kg" value="20" class="input-modern"></div>
            <div><label class="label-modern">GST %</label><input type="number" step="0.01" name="gst" value="18" class="input-modern"></div>
            <div class="flex items-end"><button type="submit" class="btn-warning w-full"><i class="fas fa-save"></i> Save Rate</button></div>
        </form>
    </div>
    <div class="card">
        <h3 class="text-lg font-bold text-slate-800 mb-4">📋 Rate Contracts Register</h3>
        <div class="table-responsive">
        <table class="datatable">
            <thead><tr><th>Customer</th><th>Route</th><th>Weight Range</th><th>Charges</th><th>GST</th><th style="width:180px;">Actions</th></tr></thead>
            <tbody>
            {% for r in rates_list %}
            <tr>
                <td class="font-bold">{% if r.cname %}<span class="text-blue-600">{{ r.cname }}</span>{% else %}<span class="px-2 py-1 bg-amber-100 text-amber-700 rounded-full text-xs">DEFAULT</span>{% endif %}</td>
                <td class="font-bold">{{ r.origin_state_code }} ➔ {{ r.dest_state_code }}</td>
                <td>{{ r.min_weight }} - {{ r.max_weight }} KG</td>
                <td class="text-red-600 font-bold">₹{{ r.fixed_charge }} + ₹{{ r.per_kg_rate }}/KG</td>
                <td>{{ r.gst_rate }}%</td>
                <td>
                    <a href="/edit_rate/{{ r.id }}" class="btn-primary" style="padding:4px 10px; font-size:11px;"><i class="fas fa-edit"></i> Edit</a>
                    <a href="/rates?delete={{ r.id }}" class="btn-danger" style="padding:4px 10px; font-size:11px;" onclick="return confirm('Delete this rate?');"><i class="fas fa-trash"></i></a>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
    </div>
    """
    return render_page("Rate Master", render_template_string(html, custs=custs, rates_list=rates_list))

# ✏️ EDIT RATE — FIXED SYNTAX
@app.route('/edit_rate/<int:rid>', methods=['GET', 'POST'])
@login_required
def edit_rate(rid):
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT r.*, c.name as cname FROM rates r LEFT JOIN customers c ON r.customer_id=c.id WHERE r.id=%s", (rid,))
        rate = c.fetchone()
        if not rate: flash("Rate not found!", "error"); return redirect('/rates')
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
        
        if request.method == 'POST':
            d = request.form
            c.execute("""UPDATE rates SET customer_id=%s, origin_state_code=%s, dest_state_code=%s, min_weight=%s,
                max_weight=%s, fixed_charge=%s, per_kg_rate=%s, gst_rate=%s WHERE id=%s""",
                (safe_int(d.get('cust_id')) if d.get('cust_id') else None, d.get('ostate','').upper(), d.get('dstate','').upper(),
                 safe_float(d.get('min_wt')), safe_float(d.get('max_wt')), safe_float(d.get('fixed')),
                 safe_float(d.get('per_kg')), safe_float(d.get('gst')), rid))
            conn.commit(); flash("✅ Rate Updated Successfully!", "success")
            return redirect('/rates')
    conn.close()
    
    html = """
    <div class="card" style="max-width:700px; margin:0 auto; border-top:4px solid #f59e0b;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">✏️ Edit Rate: <span class="text-blue-600">{{ rate.origin_state_code }} ➔ {{ rate.dest_state_code }}</span></h3>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div class="md:col-span-2"><label class="label-modern">Customer (Blank=Default)</label>
                <select name="cust_id" class="input-modern">
                    <option value="">-- DEFAULT RATE --</option>
                    {% for c in custs %}<option value="{{ c.id }}" {% if rate.customer_id == c.id %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
                </select>
            </div>
            <div><label class="label-modern">Origin State *</label><input type="text" name="ostate" value="{{ rate.origin_state_code }}" class="input-modern uppercase" required></div>
            <div><label class="label-modern">Dest State *</label><input type="text" name="dstate" value="{{ rate.dest_state_code }}" class="input-modern uppercase" required></div>
            <div><label class="label-modern">Min Weight</label><input type="number" step="0.01" name="min_wt" value="{{ rate.min_weight }}" class="input-modern"></div>
            <div><label class="label-modern">Max Weight</label><input type="number" step="0.01" name="max_wt" value="{{ rate.max_weight }}" class="input-modern"></div>
            <div><label class="label-modern">Fixed Charge (₹)</label><input type="number" step="0.01" name="fixed" value="{{ rate.fixed_charge }}" class="input-modern"></div>
            <div><label class="label-modern">Per KG Rate (₹)</label><input type="number" step="0.01" name="per_kg" value="{{ rate.per_kg_rate }}" class="input-modern"></div>
            <div><label class="label-modern">GST %</label><input type="number" step="0.01" name="gst" value="{{ rate.gst_rate }}" class="input-modern"></div>
            <div class="md:col-span-2 flex gap-3 mt-4">
                <button type="submit" class="btn-success flex-1"><i class="fas fa-save"></i> Update Rate</button>
                <a href="/rates" class="btn-danger flex-1" style="text-align:center;">Cancel</a>
            </div>
        </form>
    </div>
    """
    return render_page(f"Edit Rate #{rid}", render_template_string(html, rate=rate, custs=custs))

# ==========================================
# 📦 2.5 STATIONERY / SHIPPER ISSUE (ISSUE + RELEASE)
# ==========================================
@app.route('/stationery', methods=['GET', 'POST'])
@login_required
def stationery():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    
    # 🔄 RELEASE (Undo Issue)
    if request.args.get('delete'):
        awb_del = request.args.get('delete')
        with conn.cursor() as c:
            c.execute("UPDATE shipments SET status='BOOKED', info='' WHERE awb_no=%s AND status='STATIONERY'", (awb_del,))
        conn.commit(); flash(f"✅ AWB {awb_del} Released!", "success"); return redirect('/stationery')
    
    # ➕ ISSUE
    if request.method == 'POST':
        awb = request.form.get('awb','').strip().upper()
        issue_to = request.form.get('issue_to','')
        pcs = safe_int(request.form.get('pcs', 1))
        with conn.cursor() as c:
            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,)); s = c.fetchone()
            if s:
                c.execute("UPDATE shipments SET status='STATIONERY', info=%s WHERE id=%s", (f"Issued {pcs} pcs to {issue_to}", s['id']))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'STATIONERY',%s,%s)", (s['id'], session.get('branch','HQ'), f"Issued {pcs} pcs to {issue_to}"))
                conn.commit(); flash(f"✅ Stationery Issued for {awb}!", "success")
            else: flash("❌ AWB not found in system!", "error")
    
    with conn.cursor() as c:
        c.execute("SELECT awb_no, booking_date, origin_name, status, info FROM shipments WHERE status='STATIONERY' ORDER BY id DESC LIMIT 500"); hist = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card" style="border-top:4px solid #2563eb;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📦 Issue Stationery</h3>
            <form method="POST" class="space-y-3">
                <div><label class="label-modern">AWB No *</label><input type="text" name="awb" class="input-modern uppercase font-bold text-red-600" required></div>
                <div><label class="label-modern">Issue To *</label><select name="issue_to" class="input-modern" required>{% for c in custs %}<option>{{ c.name }}</option>{% endfor %}</select></div>
                <div><label class="label-modern">Pieces</label><input type="number" name="pcs" value="1" min="1" class="input-modern"></div>
                <button type="submit" class="btn-primary w-full"><i class="fas fa-check"></i> Assign AWB</button>
            </form>
        </div>
        <div class="card lg:col-span-2">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📋 Stationery Register ({{ hist|length }})</h3>
            <div class="table-responsive" style="max-height:450px; overflow-y:auto;">
            <table class="datatable">
                <thead><tr><th>AWB</th><th>Date</th><th>Issued To</th><th>Remarks</th><th style="width:100px;">Actions</th></tr></thead>
                <tbody>
                {% for h in hist %}
                <tr>
                    <td class="font-bold text-blue-600">{{ h.awb_no }}</td>
                    <td>{{ h.booking_date }}</td>
                    <td class="font-bold">{{ h.origin_name }}</td>
                    <td>{{ h.info }}</td>
                    <td><a href="/stationery?delete={{ h.awb_no }}" class="btn-warning" style="padding:3px 8px; font-size:11px;" onclick="return confirm('Release this AWB?');"><i class="fas fa-undo"></i></a></td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
            </div>
        </div>
    </div>
    """
    return render_page("Shipper/Barcode Issue", render_template_string(html, custs=custs, hist=hist))

# ==========================================
# 🛵 2.6 DELIVERY BOY MASTER (ADD + EDIT + DELETE)
# ==========================================
@app.route('/delivery_boy', methods=['GET', 'POST'])
@login_required
def delivery_boy():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    
    # 🗑️ DELETE
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE users SET active=0 WHERE id=%s AND role='DELIVERY'", (request.args.get('delete'),))
        conn.commit(); flash("Delivery Boy Removed!", "success"); return redirect('/delivery_boy')
    
    # ➕ ADD
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            fake_hash = hashlib.sha256("boy123".encode()).hexdigest()
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, phone, active) VALUES(%s,%s,%s,'DELIVERY',%s,%s,1)",
                      (d.get('code',''), fake_hash, d.get('name',''), session.get('branch','HQ'), d.get('phone','')))
        conn.commit(); flash("✅ Delivery Boy Added! (Default Pass: boy123)", "success")
    
    with conn.cursor() as c: c.execute("SELECT * FROM users WHERE role='DELIVERY' ORDER BY id DESC"); boys = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card" style="border-top:4px solid #f59e0b;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">🛵 Add Delivery Boy</h3>
            <form method="POST" class="space-y-3">
                <div><label class="label-modern">Employee Code *</label><input type="text" name="code" class="input-modern" required></div>
                <div><label class="label-modern">Full Name *</label><input type="text" name="name" class="input-modern" required></div>
                <div><label class="label-modern">Phone</label><input type="text" name="phone" class="input-modern"></div>
                <button type="submit" class="btn-warning w-full"><i class="fas fa-plus"></i> Add Rider</button>
            </form>
            <div class="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
                💡 Default Password: <b>boy123</b>
            </div>
        </div>
        <div class="card lg:col-span-2">
            <h3 class="text-lg font-bold text-slate-800 mb-4">Riders List ({{ boys|length }})</h3>
            <table class="datatable">
                <thead><tr><th>Code</th><th>Name</th><th>Phone</th><th>Branch</th><th>Status</th><th style="width:180px;">Actions</th></tr></thead>
                <tbody>
                {% for b in boys %}
                <tr>
                    <td class="font-bold">{{ b.username }}</td>
                    <td class="font-bold text-blue-600">{{ b.full_name }}</td>
                    <td>{{ b.phone or '-' }}</td>
                    <td>{{ b.branch_name }}</td>
                    <td>{% if b.active %}<span class="px-2 py-1 bg-green-100 text-green-700 rounded-full text-xs font-bold">Active</span>{% else %}<span class="px-2 py-1 bg-red-100 text-red-700 rounded-full text-xs font-bold">Disabled</span>{% endif %}</td>
                    <td>
                        <a href="/edit_delivery_boy/{{ b.id }}" class="btn-primary" style="padding:4px 10px; font-size:11px;"><i class="fas fa-edit"></i> Edit</a>
                        {% if b.active %}<a href="/delivery_boy?delete={{ b.id }}" class="btn-danger" style="padding:4px 10px; font-size:11px;" onclick="return confirm('Remove this rider?');"><i class="fas fa-trash"></i></a>{% endif %}
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Delivery Boy Master", render_template_string(html, boys=boys))

# ✏️ EDIT DELIVERY BOY — FIXED SYNTAX
@app.route('/edit_delivery_boy/<int:bid>', methods=['GET', 'POST'])
@login_required
def edit_delivery_boy(bid):
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM users WHERE id=%s AND role='DELIVERY'", (bid,))
        boy = c.fetchone()
        if not boy: flash("Rider not found!", "error"); return redirect('/delivery_boy')
        
        if request.method == 'POST':
            d = request.form
            c.execute("UPDATE users SET username=%s, full_name=%s, phone=%s WHERE id=%s",
                      (d.get('code',''), d.get('name',''), d.get('phone',''), bid))
            conn.commit(); flash("✅ Rider Updated!", "success")
            return redirect('/delivery_boy')
    conn.close()
    
    html = """
    <div class="card" style="max-width:500px; margin:0 auto; border-top:4px solid #f59e0b;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">✏️ Edit Rider: <span class="text-blue-600">{{ boy.full_name }}</span></h3>
        <form method="POST" class="space-y-3">
            <div><label class="label-modern">Employee Code *</label><input type="text" name="code" value="{{ boy.username }}" class="input-modern" required></div>
            <div><label class="label-modern">Full Name *</label><input type="text" name="name" value="{{ boy.full_name }}" class="input-modern" required></div>
            <div><label class="label-modern">Phone</label><input type="text" name="phone" value="{{ boy.phone }}" class="input-modern"></div>
            <div class="flex gap-3 mt-4">
                <button type="submit" class="btn-success flex-1"><i class="fas fa-save"></i> Update</button>
                <a href="/delivery_boy" class="btn-danger flex-1" style="text-align:center;">Cancel</a>
            </div>
        </form>
    </div>
    """
    return render_page(f"Edit Rider: {boy['full_name']}", render_template_string(html, boy=boy))

# ==========================================
# 👥 2.7 USER MANAGEMENT (ADD + EDIT + DEACTIVATE/ACTIVATE)
# ==========================================
@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    
    # 🗑️ DEACTIVATE
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE users SET active=0 WHERE id=%s", (request.args.get('delete'),))
        conn.commit(); flash("User Deactivated!", "success"); return redirect('/users')
    
    # 🔄 ACTIVATE
    if request.args.get('activate'):
        with conn.cursor() as c: c.execute("UPDATE users SET active=1 WHERE id=%s", (request.args.get('activate'),))
        conn.commit(); flash("User Activated!", "success"); return redirect('/users')
    
    # ➕ ADD
    if request.method == 'POST':
        d = request.form
        b = str(d.get('branch', '')).upper()
        cid = safe_int(d.get('customer_id')) if d.get('customer_id') else None
        with conn.cursor() as c:
            c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (b,))
            
            # 🛡️ SECURITY FIX: Generate Secure PBKDF2 Hash
            from werkzeug.security import generate_password_hash
            secure_hash = generate_password_hash(d.get('password',''))
            
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, customer_id, active) VALUES(%s,%s,%s,%s,%s,%s,1)",
                      (d.get('username',''), secure_hash, d.get('full_name',''), d.get('role',''), b, cid))
        conn.commit(); flash("✅ User Created Successfully!", "success")
    
    with conn.cursor() as c:
        c.execute("SELECT u.*, c.name as cname FROM users u LEFT JOIN customers c ON u.customer_id=c.id ORDER BY u.id DESC"); u_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); branches = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top:4px solid #2563eb;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">👥 Create ERP User</h3>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div><label class="label-modern">Username *</label><input type="text" name="username" class="input-modern" required></div>
            <div><label class="label-modern">Password *</label><input type="password" name="password" class="input-modern" required></div>
            <div><label class="label-modern">Full Name *</label><input type="text" name="full_name" class="input-modern" required></div>
            <div><label class="label-modern">Role</label><select name="role" class="input-modern"><option>OPERATOR</option><option>ADMIN</option><option>ACCOUNTS</option><option>CUSTOMER</option><option>DELIVERY</option></select></div>
            <div><label class="label-modern">Branch *</label><input type="text" name="branch" list="brlist" class="input-modern uppercase" required><datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist></div>
            <div><label class="label-modern">Link Customer (B2B)</label><select name="customer_id" class="input-modern"><option value="">-- None --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div>
            <div class="md:col-span-3"><button type="submit" class="btn-primary"><i class="fas fa-user-check"></i> Create User</button></div>
        </form>
    </div>
    <div class="card">
        <h3 class="text-lg font-bold text-slate-800 mb-4">System Users ({{ u_list|length }})</h3>
        <div class="table-responsive">
        <table class="datatable">
            <thead><tr><th>Login ID</th><th>Full Name</th><th>Role</th><th>Branch</th><th>Linked Customer</th><th>Status</th><th style="width:220px;">Actions</th></tr></thead>
            <tbody>
            {% for u in u_list %}
            <tr>
                <td class="font-bold">{{ u.username }}</td>
                <td>{{ u.full_name }}</td>
                <td><span class="px-2 py-1 bg-purple-100 text-purple-700 rounded-full text-xs font-bold">{{ u.role }}</span></td>
                <td>{{ u.branch_name }}</td>
                <td>{{ u.cname or '-' }}</td>
                <td>{% if u.active %}<span class="px-2 py-1 bg-green-100 text-green-700 rounded-full text-xs font-bold">Active</span>{% else %}<span class="px-2 py-1 bg-red-100 text-red-700 rounded-full text-xs font-bold">Disabled</span>{% endif %}</td>
                <td>
                    <a href="/edit_user/{{ u.id }}" class="btn-primary" style="padding:4px 10px; font-size:11px;"><i class="fas fa-edit"></i> Edit</a>
                    {% if u.active %}
                    <a href="/users?delete={{ u.id }}" class="btn-danger" style="padding:4px 10px; font-size:11px;" onclick="return confirm('Disable user?');"><i class="fas fa-ban"></i></a>
                    {% else %}
                    <a href="/users?activate={{ u.id }}" class="btn-success" style="padding:4px 10px; font-size:11px;" onclick="return confirm('Activate user?');"><i class="fas fa-check"></i></a>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
    </div>
    """
    return render_page("User Management", render_template_string(html, u_list=u_list, branches=branches, custs=custs))

# ✏️ EDIT USER (Dedicated Edit Page with Password Reset) — FIXED SYNTAX
@app.route('/edit_user/<int:uid>', methods=['GET', 'POST'])
@login_required
def edit_user(uid):
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT u.*, c.name as cname FROM users u LEFT JOIN customers c ON u.customer_id=c.id WHERE u.id=%s", (uid,))
        user = c.fetchone()
        if not user: flash("User not found!", "error"); return redirect('/users')
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); branches = c.fetchall()
        
        if request.method == 'POST':
            d = request.form
            b = str(d.get('branch', '')).upper()
            cid = safe_int(d.get('customer_id')) if d.get('customer_id') else None
            c.execute("UPDATE users SET username=%s, full_name=%s, role=%s, branch_name=%s, customer_id=%s WHERE id=%s",
                      (d.get('username',''), d.get('full_name',''), d.get('role',''), b, cid, uid))
            
            # 🔑 🛡️ SECURITY FIX: Password Reset with Secure PBKDF2 Hash
            if d.get('new_pass', '').strip():
                from werkzeug.security import generate_password_hash
                secure_hash = generate_password_hash(d.get('new_pass', '').strip())
                c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (secure_hash, uid))
                flash("✅ User Updated + Password Reset!", "success")
            else:
                flash("✅ User Updated Successfully!", "success")
            conn.commit()
            return redirect('/users')
    conn.close()
    
    html = """
    <div class="card" style="max-width:700px; margin:0 auto; border-top:4px solid #f59e0b;">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold text-slate-800">✏️ Edit User: <span class="text-blue-600">{{ user.username }}</span></h3>
            <span class="px-3 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-bold">EDIT MODE</span>
        </div>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div><label class="label-modern">Username *</label><input type="text" name="username" value="{{ user.username }}" class="input-modern" required></div>
            <div><label class="label-modern">Full Name *</label><input type="text" name="full_name" value="{{ user.full_name }}" class="input-modern" required></div>
            <div><label class="label-modern">Role</label>
                <select name="role" class="input-modern">
                    <option {% if user.role=='OPERATOR' %}selected{% endif %}>OPERATOR</option>
                    <option {% if user.role=='ADMIN' %}selected{% endif %}>ADMIN</option>
                    <option {% if user.role=='ACCOUNTS' %}selected{% endif %}>ACCOUNTS</option>
                    <option {% if user.role=='CUSTOMER' %}selected{% endif %}>CUSTOMER</option>
                    <option {% if user.role=='DELIVERY' %}selected{% endif %}>DELIVERY</option>
                </select>
            </div>
            <div><label class="label-modern">Branch *</label><input type="text" name="branch" value="{{ user.branch_name }}" list="brlist" class="input-modern uppercase" required><datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist></div>
            <div class="md:col-span-2"><label class="label-modern">Link Customer (B2B Only)</label>
                <select name="customer_id" class="input-modern">
                    <option value="">-- None --</option>
                    {% for c in custs %}<option value="{{ c.id }}" {% if user.customer_id == c.id %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
                </select>
            </div>
            <div class="md:col-span-2 p-4 bg-red-50 border border-red-200 rounded-lg">
                <label class="label-modern text-red-600">🔑 Reset Password (Optional - blank rakhe agar change nahi karna)</label>
                <input type="password" name="new_pass" class="input-modern" placeholder="Enter new password...">
            </div>
            <div class="md:col-span-2 flex gap-3 mt-4">
                <button type="submit" class="btn-success flex-1"><i class="fas fa-save"></i> Update User</button>
                <a href="/users" class="btn-danger flex-1" style="text-align:center;">Cancel</a>
            </div>
        </form>
    </div>
    """
    return render_page(f"Edit User: {user['username']}", render_template_string(html, user=user, custs=custs, branches=branches))

# ==========================================
# ⚙️ 2.8 SETTINGS (Company + Password) — SECURED
# ==========================================
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    conn = get_db()
    if request.method == 'POST':
        # 🔑 PASSWORD CHANGE (UPGRADED TO BANK-LEVEL SECURITY)
        if 'old_pass' in request.form:
            old_p = request.form.get('old_pass', '')
            new_p = request.form.get('new_pass', '')
            with conn.cursor() as c:
                c.execute("SELECT password_hash FROM users WHERE id=%s", (session['user_id'],))
                u = c.fetchone()
                
                is_valid_old = False
                if u:
                    from werkzeug.security import check_password_hash, generate_password_hash
                    import hashlib
                    
                    # Check 1: Old SHA256 logic (taaki purane accounts block na ho)
                    if u['password_hash'] == hashlib.sha256(old_p.encode()).hexdigest():
                        is_valid_old = True
                    # Check 2: New PBKDF2 Secure Hash
                    elif check_password_hash(u['password_hash'], old_p):
                        is_valid_old = True

                if is_valid_old:
                    # Naya password hamesha SECURE hash me save hoga
                    secure_hash = generate_password_hash(new_p)
                    c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (secure_hash, session['user_id']))
                    conn.commit()
                    flash("✅ Password Changed Successfully!", "success")
                else: 
                    flash("❌ Old Password Incorrect!", "error")
                    
        # 🏢 COMPANY SETTINGS (Admin only)
        else:
            if session.get('role') != 'ADMIN': 
                flash("#⚠ Only Admins can change system settings.", "error")
            else:
                with conn.cursor() as c:
                    for key in ['company_name','company_address','company_gstin','company_phone','company_state_code','company_email','bank_details','terms_note','fuel_surcharge']:
                        c.execute("UPDATE settings SET value=%s WHERE key_name=%s", (request.form.get(key, ''), key))
                    conn.commit(); flash("✅ Settings Updated!", "success")
    
    with conn.cursor() as c:
        c.execute("SELECT key_name, value FROM settings")
        settings_data = {r['key_name'].strip(): r['value'] for r in c.fetchall()}  
    conn.close()
    
    html = """
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {% if session.get('role') == 'ADMIN' %}
        <div class="card" style="border-top:4px solid #2563eb;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">🏢 Company & Billing Settings</h3>
            <form method="POST" class="space-y-3">
                <div class="grid grid-cols-2 gap-3">
                    <div><label class="label-modern">Company Name</label><input name="company_name" value="{{ s.company_name }}" class="input-modern"></div>
                    <div><label class="label-modern">GSTIN</label><input name="company_gstin" value="{{ s.company_gstin }}" class="input-modern"></div>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div><label class="label-modern">Phone</label><input name="company_phone" value="{{ s.company_phone }}" class="input-modern"></div>
                    <div><label class="label-modern">Email</label><input name="company_email" value="{{ s.company_email }}" class="input-modern"></div>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div><label class="label-modern">State Code</label><input name="company_state_code" value="{{ s.company_state_code }}" class="input-modern"></div>
                    <div><label class="label-modern">Fuel Surcharge %</label><input type="number" step="0.01" name="fuel_surcharge" value="{{ s.fuel_surcharge }}" class="input-modern"></div>
                </div>
                <div><label class="label-modern">Address</label><textarea name="company_address" class="input-modern" rows="2">{{ s.company_address }}</textarea></div>
                <div><label class="label-modern">Bank Details</label><textarea name="bank_details" class="input-modern" rows="2">{{ s.bank_details }}</textarea></div>
                <div><label class="label-modern">Terms & Conditions</label><textarea name="terms_note" class="input-modern" rows="2">{{ s.terms_note }}</textarea></div>
                <button type="submit" class="btn-primary w-full"><i class="fas fa-save"></i> Update Settings</button>
            </form>
        </div>
        {% endif %}
        <div class="card" style="border-top:4px solid #ef4444;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">🔑 Change My Password</h3>
            <form method="POST" class="space-y-3">
                <div><label class="label-modern">Current Password</label><input type="password" name="old_pass" class="input-modern" required></div>
                <div><label class="label-modern">New Password</label><input type="password" name="new_pass" class="input-modern" required></div>
                <button type="submit" class="btn-danger w-full"><i class="fas fa-lock"></i> Change Password</button>
            </form>
        </div>
    </div>
    """
    return render_page("System Settings", render_template_string(html, s=settings_data))

#⚠ PART 2 ENDS HERE. PART 3 (Transactions) agle message me aayega.

# ============================================================
# 📦 PART 3: TRANSACTIONS MODULE (FULL CRUD)
# ============================================================

# ==========================================
#🔌 3.1 AUTO-RATE CALCULATION API
# ==========================================
@app.route('/api/calc_rate', methods=['POST'])
@login_required
def api_calc_rate():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify({"success": False, "error": "Request body must be valid JSON."}), 400
    cid = safe_int(d.get('cust_id')) if d.get('cust_id') else None
    ost = d.get('ostate', '')
    dst = d.get('dstate', '')
    wt = safe_float(d.get('wt'))
    fr = safe_float(d.get('fr'))
    tx = safe_float(d.get('tax'))
    
    if fr == 0.0:
        conn = get_db(); c = conn.cursor()
        # Customer-specific rate
        c.execute("""SELECT * FROM rates WHERE active=1 AND customer_id=%s AND origin_state_code=%s AND dest_state_code=%s 
            AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1""", (cid, ost, dst, wt))
        r = c.fetchone()
        if not r:
            # Default rate
            c.execute("""SELECT * FROM rates WHERE active=1 AND customer_id IS NULL AND origin_state_code=%s AND dest_state_code=%s 
                AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1""", (ost, dst, wt))
            r = c.fetchone()
        c.close(); conn.close()
        if r:
            fr = safe_float(r['fixed_charge']) + (wt * safe_float(r['per_kg_rate']))
            tx = safe_float(r['gst_rate'])
        else:
            fr = wt * 25.0  # Default fallback
    
    fuel = safe_float(get_setting("fuel_surcharge", "0"))
    taxable = fr * (1 + (fuel/100))
    gst_amt = taxable * (tx/100)
    total = taxable + gst_amt
    return jsonify({"freight": round(fr,2), "taxable": round(taxable,2), "gst": round(gst_amt,2), "total": round(total,2), "tax_rate": tx})

@app.route('/api/get_awb_info/<awb>', methods=['GET'])
@login_required
def api_get_awb_info(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT dest_station, dest_name, weight_kg FROM shipments WHERE awb_no=%s", (awb.upper(),))
        s = c.fetchone()
    conn.close()
    if s: return jsonify({"success": True, "dest_station": s['dest_station'], "dest_name": s['dest_name'], "weight": s['weight_kg']})
    return jsonify({"success": False})

# ==========================================
# 📤 3.2 COUNTER BOOKING (ADD + AUTO-RATE)
# ==========================================
@app.route('/booking', methods=['GET', 'POST'])
@login_required
def booking():
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        fr = safe_float(d.get('fr')); tax = safe_float(d.get('tax', 18)); wt = safe_float(d.get('wt', 1))
        fuel = safe_float(get_setting("fuel_surcharge", "0"))
        taxable = fr * (1 + (fuel/100)); gst = taxable * (tax / 100); tot = taxable + gst
        cgst = sgst = igst = 0
        if str(d.get('ostate','')).strip().upper() == str(d.get('dstate','')).strip().upper():
            cgst = sgst = gst / 2
        else:
            igst = gst
        
        with conn.cursor() as c:
            try:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d.get('dstat','').upper(),))
                cid = session.get('customer_id') if session.get('role') == 'CUSTOMER' else (safe_int(d.get('cust_id')) if d.get('cust_id') else None)
                awb = d.get('awb','').upper()
                c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, origin_phone, origin_address, origin_state_code, 
                    dest_name, dest_phone, dest_address, dest_state_code, dest_station, weight_kg, quantity, cod_amount, declared_value, 
                    service_type, taxable_amount, tax_rate, cgst, sgst, igst, total_amount, info, status, current_location, is_synced)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s, 0)""",
                    (awb, cid, d.get('date',''), d.get('oname',''), d.get('ophone',''), d.get('oaddr',''), d.get('ostate',''),
                     d.get('dname',''), d.get('dphone',''), d.get('daddr',''), d.get('dstate',''), d.get('dstat','').upper(),
                     wt, safe_int(d.get('pcs', 1)), safe_float(d.get('cod')), safe_float(d.get('dec')), d.get('srv','SURFACE'),
                     taxable, tax, cgst, sgst, igst, tot, d.get('info',''), session.get('branch','HQ')))
                sid = c.lastrowid
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'BOOKED',%s,'Booked at counter')", (sid, session.get('branch','HQ')))
                if cid:
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (cid, d.get('date',''), awb, tot, f"Booking {awb}"))
                conn.commit()
                flash(f"✅ AWB {awb} Booked! Total: ₹{tot:,.2f}", "success")
            except Exception as e:
                flash(f"❌ Booking Error: {e}", "error")
        return redirect('/booking')
    
    with conn.cursor() as c:
        c.execute("SELECT id, name, phone, state_code FROM customers WHERE is_active=1"); custs = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
        my_cust = None
        addr_book = [] # 🚀 NAYA
        if session.get('role') == 'CUSTOMER':
            c.execute("SELECT id, name, phone, state_code, address FROM customers WHERE id=%s", (session.get('customer_id'),))
            my_cust = c.fetchone()
            # 🚀 NAYA: Fetch Address Book
            try:
                c.execute("SELECT * FROM address_book WHERE customer_id=%s", (session.get('customer_id'),))
                addr_book = c.fetchall()
            except: pass
        q_recent = """SELECT s.id, s.awb_no, COALESCE(c.name,'CASH') as customer_name, COALESCE(s.dest_station,'') as dest_station,
            s.weight_kg, s.total_amount, s.status, s.booking_date FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id"""
        params_recent = []
        if session.get('role') == 'CUSTOMER':
            q_recent += " WHERE s.customer_id = %s"; params_recent.append(session.get('customer_id'))
        elif session.get('role') != 'ADMIN':
            q_recent += " WHERE s.origin_name = %s"; params_recent.append(session.get('branch', 'HQ'))
        q_recent += " ORDER BY s.id DESC LIMIT 50"
        c.execute(q_recent, tuple(params_recent)); recent = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top:4px solid #2563eb;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">📦 Counter Booking Entry</h3>
        <form method="POST" id="bkForm" class="space-y-4">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div><label class="label-modern">Booking Date *</label><input type="date" name="date" id="bdt" required class="input-modern"></div>
                <div><label class="label-modern">AWB / C.Note No *</label><input name="awb" required class="input-modern font-bold text-red-600 uppercase"></div>
                <div><label class="label-modern">Customer A/c</label>
                    {% if session.get('role') == 'CUSTOMER' %}
                    <input type="hidden" name="cust_id" id="cid" value="{{ my_cust.id }}" data-state="{{ my_cust.state_code }}">
                    <input value="{{ my_cust.name }}" readonly class="input-modern bg-slate-100 font-bold">
                    {% else %}
                    <select name="cust_id" id="cid" onchange="fetchRate()" class="input-modern"><option value="">-- Cash Booking --</option>{% for c in custs %}<option value="{{ c.id }}" data-state="{{ c.state_code }}">{{ c.name }}</option>{% endfor %}</select>
                    {% endif %}
                </div>
                <div><label class="label-modern">Service</label><select name="srv" class="input-modern"><option>SURFACE</option><option>AIR</option></select></div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="border border-amber-200 rounded-lg p-4 bg-amber-50">
                    <h4 class="font-bold text-amber-700 mb-3 text-sm">📤 CONSIGNOR (Sender)</h4>
                    <div class="space-y-2">
                        <input name="oname" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.name }}{% else %}{{ session.get('branch', 'HQ') }}{% endif %}" class="input-modern" placeholder="Name" required>
                        <input name="ophone" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.phone }}{% endif %}" class="input-modern" placeholder="Phone">
                        <input name="ostate" id="ost" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.state_code }}{% else %}RJ{% endif %}" onchange="fetchRate()" class="input-modern" placeholder="State Code">
                        <input name="oaddr" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.address }}{% endif %}" class="input-modern" placeholder="Address">
                    </div>
                </div>
                <div class="border border-blue-200 rounded-lg p-4 bg-blue-50">
                    <div class="flex justify-between items-center mb-3">
                        <h4 class="font-bold text-blue-700 text-sm">📥 CONSIGNEE (Receiver)</h4>
                        {% if session.get('role') == 'CUSTOMER' and addr_book %}
                        <select id="addr_selector" onchange="fillAddress()" class="text-xs border p-1 rounded outline-none border-blue-300">
                            <option value="">-- Auto-Fill from Address Book --</option>
                            {% for a in addr_book %}
                            <option value="{{ a.name }}|{{ a.phone }}|{{ a.station }}|{{ a.state_code }}|{{ a.address }}">{{ a.name }} ({{ a.station }})</option>
                            {% endfor %}
                        </select>
                        {% endif %}
                    </div>
                    <div class="space-y-2">
                        <input name="dname" id="dname" class="input-modern" placeholder="Name" required>
                        <input name="dphone" id="dphone" class="input-modern" placeholder="Phone" required>
                        <input name="dstat" id="dstat" list="stations" class="input-modern uppercase font-bold" placeholder="Destination Station" required><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist>
                        <input name="dstate" id="dst" onchange="fetchRate()" class="input-modern" placeholder="State Code">
                        <input name="daddr" id="daddr" class="input-modern" placeholder="Address">
                    </div>
                </div>
            </div>
            <div class="border border-green-200 rounded-lg p-4 bg-green-50">
                <h4 class="font-bold text-green-700 mb-3 text-sm">💰 CHARGE DETAILS</h4>
                <div class="grid grid-cols-2 md:grid-cols-6 gap-3 items-end">
                    <div><label class="label-modern">Weight (KG)</label><input type="number" step="0.01" name="wt" id="wt" value="1.0" required oninput="fetchRate()" class="input-modern font-bold"></div>
                    <div><label class="label-modern">Pieces</label><input type="number" name="pcs" value="1" required class="input-modern"></div>
                    <div><label class="label-modern">COD Amt</label><input type="number" step="0.01" name="cod" value="0" class="input-modern"></div>
                    <div><label class="label-modern">Freight (₹)</label><input type="number" step="0.01" name="fr" id="fr" value="0.0" oninput="manualCalc()" required class="input-modern text-right"></div>
                    <div><label class="label-modern">Tax %</label><input type="number" name="tax" id="tax" value="18" oninput="manualCalc()" required class="input-modern text-right"></div>
                    <div><label class="label-modern">Grand Total (₹)</label><input type="number" step="0.01" name="amt" id="amt" value="0.0" readonly class="input-modern font-bold text-red-600 text-right bg-red-50"></div>
                </div>
                <div id="calc_hint" class="text-xs text-amber-600 font-bold mt-2 text-right">⚡ Auto-Rate API Ready</div>
            </div>
            <div class="flex gap-3 justify-end">
                <button type="button" class="btn-danger" onclick="document.getElementById('bkForm').reset()"><i class="fas fa-undo"></i> Reset</button>
                <button type="submit" class="btn-primary"><i class="fas fa-save"></i> BOOK PARCEL</button>
            </div>
        </form>
    </div>
    <div class="card mt-4">
        <h3 class="text-lg font-bold text-slate-800 mb-4">📋 Recent Bookings</h3>
        <table class="datatable">
            <thead><tr><th>AWB</th><th>Party</th><th>Station</th><th>Weight</th><th>Amount</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
            {% for r in recent %}
            <tr>
                <td class="font-bold text-red-600">{{ r.awb_no }}</td>
                <td>{{ r.customer_name }}</td>
                <td>{{ r.dest_station }}</td>
                <td>{{ r.weight_kg }} KG</td>
                <td class="font-bold">₹{{ r.total_amount }}</td>
                <td><span class="px-2 py-1 rounded-full text-xs font-bold {% if r.status=='BOOKED' %}bg-blue-100 text-blue-700{% else %}bg-slate-100 text-slate-700{% endif %}">{{ r.status }}</span></td>
                <td>
                    <a href="/edit_shipment/{{ r.id }}" class="btn-primary" style="padding:4px 8px; font-size:11px;"><i class="fas fa-edit"></i></a>
                    <a href="/print/label/{{ r.awb_no }}" target="_blank" class="btn-warning" style="padding:4px 8px; font-size:11px;"><i class="fas fa-tag"></i> Label</a>
                    <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="btn-success" style="padding:4px 8px; font-size:11px;"><i class="fas fa-receipt"></i> Receipt</a>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    <script>
    document.getElementById('bdt').valueAsDate = new Date();
    
    function fillAddress() {
        let val = document.getElementById('addr_selector').value;
        if(!val) return;
        let parts = val.split('|');
        document.getElementById('dname').value = parts[0] || '';
        document.getElementById('dphone').value = parts[1] || '';
        document.getElementById('dstat').value = parts[2] || '';
        document.getElementById('dst').value = parts[3] || '';
        document.getElementById('daddr').value = parts[4] || '';
        fetchRate();
    }
    
    function fetchRate() {
        let cid = document.getElementById('cid').value;
        if(cid && document.getElementById('cid').tagName === 'SELECT') {
            let opt = document.getElementById('cid').options[document.getElementById('cid').selectedIndex];
            if(opt) document.getElementById('ost').value = opt.getAttribute('data-state');
        }
        let data = { cust_id: cid, ostate: document.getElementById('ost').value, dstate: document.getElementById('dst').value, wt: document.getElementById('wt').value, fr: 0 };
        fetch('/api/calc_rate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) })
        .then(r => r.json()).then(res => { 
            document.getElementById('fr').value = res.freight;
            document.getElementById('tax').value = res.tax_rate;
            document.getElementById('amt').value = res.total;
            document.getElementById('calc_hint').innerHTML = `✅ Taxable: ₹${res.taxable} | GST: ₹${res.gst}`;
        });
    }
    function manualCalc() {
        let fr = parseFloat(document.getElementById('fr').value)||0;
        let tx = parseFloat(document.getElementById('tax').value)||0;
        document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2);
        document.getElementById('calc_hint').innerHTML = "✏️ Manual Override Applied";
    }
    if(document.getElementById('cid').tagName === 'INPUT') fetchRate();
    </script>
    """
    return render_page("Counter Booking", render_template_string(html, custs=custs, stations=stations, recent=recent, my_cust=my_cust, addr_book=addr_book))

# ==========================================
# ✏️ 3.3 EDIT SHIPMENT (FULL UPDATE + STATUS)
# ==========================================
@app.route('/edit_shipment/<int:sid>', methods=['GET', 'POST'])
@login_required
def edit_shipment(sid):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM shipments WHERE id=%s", (sid,))
        s = c.fetchone()
        if not s: flash("Shipment not found!", "error"); return redirect('/shipments')
        
        # Customer can only edit their own BOOKED shipments
        if session.get('role') == 'CUSTOMER':
            if s['customer_id'] != session.get('customer_id'):
                flash("Unauthorized access!", "error"); return redirect('/shipments')
            if s['status'] != 'BOOKED':
                flash("Cannot edit dispatched shipment!", "error"); return redirect('/shipments')
        
        if request.method == 'POST':
            d = request.form
            fr = safe_float(d.get('fr')); tax = safe_float(d.get('tax', 18)); wt = safe_float(d.get('wt', 1))
            fuel = safe_float(get_setting("fuel_surcharge", "0"))
            taxable = fr * (1 + (fuel/100)); gst = taxable * (tax / 100); tot = taxable + gst
            cgst = sgst = igst = 0
            if str(d.get('ostate','')).strip().upper() == str(d.get('dstate','')).strip().upper():
                cgst = sgst = gst / 2
            else:
                igst = gst
            try:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d.get('dstat','').upper(),))
                new_status = d.get('status', 'BOOKED') if session.get('role') != 'CUSTOMER' else 'BOOKED'
                new_loc = d.get('location', '') if session.get('role') != 'CUSTOMER' else s['current_location']
                c.execute("""UPDATE shipments SET awb_no=%s, booking_date=%s, origin_name=%s, origin_phone=%s, origin_address=%s, 
                    origin_state_code=%s, dest_name=%s, dest_phone=%s, dest_address=%s, dest_state_code=%s, dest_station=%s, 
                    weight_kg=%s, quantity=%s, cod_amount=%s, declared_value=%s, service_type=%s, taxable_amount=%s, tax_rate=%s, 
                    cgst=%s, sgst=%s, igst=%s, total_amount=%s, info=%s, status=%s, current_location=%s WHERE id=%s""",
                    (d.get('awb','').upper(), d.get('date',''), d.get('oname',''), d.get('ophone',''), d.get('oaddr',''),
                     d.get('ostate',''), d.get('dname',''), d.get('dphone',''), d.get('daddr',''), d.get('dstate',''),
                     d.get('dstat','').upper(), wt, safe_int(d.get('pcs', 1)), safe_float(d.get('cod')), safe_float(d.get('dec')),
                     d.get('srv','SURFACE'), taxable, tax, cgst, sgst, igst, tot, d.get('info',''), new_status, new_loc, sid))
                # Log status change
                if s['status'] != new_status or s['current_location'] != new_loc:
                    c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,%s,%s,'Updated via Edit Panel')", (sid, new_status, new_loc))
                conn.commit()
                flash(f"✅ AWB {d.get('awb','').upper()} Updated Successfully!", "success")
                return redirect('/shipments')
            except Exception as e:
                flash(f"❌ Update Error: {e}", "error")
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="max-width:900px; margin:0 auto; border-top:4px solid #f59e0b;">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold text-slate-800">✏️ Edit AWB: <span class="text-red-600">{{ s.awb_no }}</span></h3>
            <span class="px-3 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-bold">EDIT MODE</span>
        </div>
        <form method="POST" class="space-y-4">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div><label class="label-modern">Date</label><input type="date" name="date" value="{{ s.booking_date }}" required class="input-modern"></div>
                <div><label class="label-modern">AWB No</label><input name="awb" value="{{ s.awb_no }}" required class="input-modern font-bold text-red-600 uppercase"></div>
                {% if session.get('role') != 'CUSTOMER' %}
                <div><label class="label-modern">Status</label>
                    <select name="status" class="input-modern font-bold">
                        <option {% if s.status == 'BOOKED' %}selected{% endif %}>BOOKED</option>
                        <option {% if s.status == 'OUTWARD' %}selected{% endif %}>OUTWARD</option>
                        <option {% if s.status == 'INWARD' %}selected{% endif %}>INWARD</option>
                        <option {% if s.status == 'ON_DRS' %}selected{% endif %}>ON_DRS</option>
                        <option {% if s.status == 'DELIVERED' %}selected{% endif %}>DELIVERED</option>
                    </select>
                </div>
                <div><label class="label-modern">Location</label><input name="location" value="{{ s.current_location or '' }}" class="input-modern"></div>
                {% endif %}
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="border border-amber-200 rounded-lg p-4 bg-amber-50">
                    <h4 class="font-bold text-amber-700 mb-3 text-sm">📤 CONSIGNOR</h4>
                    <div class="space-y-2">
                        <input name="oname" value="{{ s.origin_name or '' }}" class="input-modern" required>
                        <input name="ophone" value="{{ s.origin_phone or '' }}" class="input-modern">
                        <input name="ostate" id="ost" value="{{ s.origin_state_code or '' }}" onchange="manualCalc()" class="input-modern">
                        <input name="oaddr" value="{{ s.origin_address or '' }}" class="input-modern">
                    </div>
                </div>
                <div class="border border-blue-200 rounded-lg p-4 bg-blue-50">
                    <h4 class="font-bold text-blue-700 mb-3 text-sm">📥 CONSIGNEE</h4>
                    <div class="space-y-2">
                        <input name="dname" value="{{ s.dest_name or '' }}" class="input-modern" required>
                        <input name="dphone" value="{{ s.dest_phone or '' }}" class="input-modern">
                        <input name="dstat" list="stations" value="{{ s.dest_station or '' }}" class="input-modern uppercase font-bold" required>
                        <datalist id="stations">{% for st in stations %}<option value="{{ st.name }}">{% endfor %}</datalist>
                        <input name="dstate" id="dst" value="{{ s.dest_state_code or '' }}" onchange="manualCalc()" class="input-modern">
                        <input name="daddr" value="{{ s.dest_address or '' }}" class="input-modern">
                    </div>
                </div>
            </div>
            <div class="border border-green-200 rounded-lg p-4 bg-green-50">
                <h4 class="font-bold text-green-700 mb-3 text-sm">💰 CHARGES</h4>
                <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
                    <div><label class="label-modern">Weight</label><input type="number" step="0.01" name="wt" id="wt" value="{{ s.weight_kg or 1 }}" oninput="manualCalc()" required class="input-modern font-bold"></div>
                    <div><label class="label-modern">Pieces</label><input type="number" name="pcs" value="{{ s.quantity or 1 }}" required class="input-modern"></div>
                    <div><label class="label-modern">Freight</label><input type="number" step="0.01" name="fr" id="fr" value="{{ s.taxable_amount or 0 }}" oninput="manualCalc()" required class="input-modern text-right"></div>
                    <div><label class="label-modern">Tax %</label><input type="number" name="tax" id="tax" value="{{ s.tax_rate or 18 }}" oninput="manualCalc()" class="input-modern text-right"></div>
                    <div><label class="label-modern">Total</label><input type="number" step="0.01" name="amt" id="amt" value="{{ s.total_amount or 0 }}" readonly class="input-modern font-bold text-red-600 text-right"></div>
                </div>
            </div>
            <div class="flex gap-3 justify-end">
                <a href="/shipments" class="btn-danger" style="text-align:center;"><i class="fas fa-times"></i> Cancel</a>
                <button type="submit" class="btn-success"><i class="fas fa-save"></i> UPDATE SHIPMENT</button>
            </div>
        </form>
    </div>
    <script>function manualCalc() { let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0; document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); }</script>
    """
    return render_page(f"Edit AWB: {s['awb_no']}", render_template_string(html, s=s, stations=stations))

# ==========================================
# 📋 3.4 SHIPMENTS REGISTER (LIST + DELETE)
# ==========================================
@app.route('/shipments', methods=['GET', 'POST'])
@login_required
def shipments():
    conn = get_db()
    # 🗑️ DELETE
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("SELECT customer_id, status FROM shipments WHERE id=%s", (request.args.get('delete'),))
            ship = c.fetchone()
            if ship:
                if session.get('role') == 'CUSTOMER' and (ship['customer_id'] != session.get('customer_id') or ship['status'] != 'BOOKED'):
                    flash("Cannot delete this shipment!", "error")
                else:
                    c.execute("DELETE FROM scan_events WHERE shipment_id=%s", (request.args.get('delete'),))
                    c.execute("DELETE FROM shipments WHERE id=%s", (request.args.get('delete'),))
                    conn.commit()
                    flash("Shipment Deleted!", "success")
        return redirect('/shipments')
    
    with conn.cursor() as c:
        q = """SELECT s.id, s.awb_no, s.booking_date, s.dest_name, s.dest_station, s.weight_kg, s.status, s.total_amount
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
        <h3 class="text-lg font-bold text-slate-800 mb-4">{% if session.get('role') == 'CUSTOMER' %}📦 My Shipments{% else %}📦 Delivery Status Register{% endif %}</h3>
        <table class="datatable">
            <thead><tr><th>AWB</th><th>Date</th><th>Destination</th><th>Station</th><th>Weight</th><th>Status</th><th>Total</th><th>Actions</th></tr></thead>
            <tbody>
            {% for r in rows %}
            <tr>
                <td class="font-bold text-red-600">{{ r.awb_no }}</td>
                <td>{{ r.booking_date }}</td>
                <td>{{ r.dest_name or '-' }}</td>
                <td>{{ r.dest_station or '-' }}</td>
                <td>{{ r.weight_kg }} KG</td>
                <td><span class="px-2 py-1 rounded-full text-xs font-bold {% if r.status=='DELIVERED' %}bg-green-100 text-green-700{% elif r.status=='OUTWARD' %}bg-purple-100 text-purple-700{% elif r.status=='INWARD' %}bg-amber-100 text-amber-700{% elif r.status=='ON_DRS' %}bg-blue-100 text-blue-700{% else %}bg-slate-100 text-slate-700{% endif %}">{{ r.status }}</span></td>
                <td class="font-bold">₹{{ r.total_amount or 0 }}</td>
                <td>
                    {% if session.get('role') != 'CUSTOMER' or r.status == 'BOOKED' %}
                    <a href="/edit_shipment/{{ r.id }}" class="btn-primary" style="padding:3px 8px; font-size:11px;"><i class="fas fa-edit"></i></a>
                    {% endif %}
                    <a href="/track?awb={{ r.awb_no }}" target="_blank" class="btn-success" style="padding:3px 8px; font-size:11px;"><i class="fas fa-map-marker-alt"></i></a>
                    <a href="/print/label/{{ r.awb_no }}" target="_blank" class="btn-warning" style="padding:3px 8px; font-size:11px;"><i class="fas fa-tag"></i></a>
                    <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="btn-primary" style="padding:3px 8px; font-size:11px;"><i class="fas fa-receipt"></i></a>
                    {% if session.get('role') != 'CUSTOMER' or r.status == 'BOOKED' %}
                    <a href="/shipments?delete={{ r.id }}" class="btn-danger" style="padding:3px 8px; font-size:11px;" onclick="return confirm('Delete?');"><i class="fas fa-trash"></i></a>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page("Shipments Register", render_template_string(html, rows=rows))

# ==========================================
# 📥 3.5 CARGO INWARD (ADD + DELETE)
# ==========================================
@app.route('/inward', methods=['GET', 'POST'])
@login_required
def inward():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    st = session.get('branch', 'HQ')
    date_today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            if action == 'add':
                awb = request.form.get('awb', '').strip().upper()
                orig = request.form.get('orig', '').strip().upper()
                wt = safe_float(request.form.get('wt', 1.0))
                info = request.form.get('info', '')
                c.execute("SELECT id FROM inward_register WHERE awb_no=%s AND entry_date=%s AND in_station=%s", (awb, date_today, st))
                if c.fetchone():
                    flash(f"AWB {awb} already inwarded today!", "error")
                else:
                    c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (orig,))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    s = c.fetchone()
                    if s:
                        c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (st, s['id']))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'INWARD', %s, 'Web Inward Entry')", (s['id'], st))
                    c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, weight, info, finalized) VALUES(%s, %s, %s, %s, %s, %s, 0)", (date_today, awb, orig, st, wt, info))
                    conn.commit()
                    flash(f"✅ AWB {awb} Inward Saved!", "success")
            elif action == 'delete':
                c.execute("DELETE FROM inward_register WHERE id=%s", (request.form.get('del_id'),))
                conn.commit()
                flash("Entry removed from inward pending!", "success")
        return redirect('/inward')
    
    with conn.cursor() as c:
        c.execute("SELECT * FROM inward_register WHERE in_station=%s AND finalized=0 ORDER BY id DESC", (st,))
        pending = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top:4px solid #f59e0b;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">📥 Cargo Packet Inward</h3>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <input type="hidden" name="action" value="add">
            <div><label class="label-modern text-red-600">AWB No *</label><input type="text" name="awb" required autofocus class="input-modern font-bold text-red-600 uppercase" autocomplete="off"></div>
            <div><label class="label-modern">Coming From *</label><input type="text" name="orig" list="st_list" required class="input-modern uppercase" autocomplete="off"><datalist id="st_list">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
            <div><label class="label-modern">Weight (KG)</label><input type="number" step="0.01" name="wt" value="1.0" required class="input-modern font-bold"></div>
            <div><label class="label-modern">Remarks</label><input type="text" name="info" class="input-modern"></div>
            <div><button type="submit" class="btn-warning w-full"><i class="fas fa-download"></i> Save Inward</button></div>
        </form>
    </div>
    <div class="card mt-4">
        <h3 class="text-lg font-bold text-slate-800 mb-4">Pending Inwards ({{ pending|length }})</h3>
        <table class="datatable">
            <thead><tr><th>ID</th><th>AWB</th><th>Coming From</th><th>Weight</th><th>Remarks</th><th>Action</th></tr></thead>
            <tbody>
            {% for p in pending %}
            <tr>
                <td>{{ p.id }}</td>
                <td class="font-bold text-red-600">{{ p.awb_no }}</td>
                <td class="font-bold text-blue-600">{{ p.origin_station }}</td>
                <td>{{ p.weight }} KG</td>
                <td>{{ p.info }}</td>
                <td>
                    <form method="POST" style="display:inline;" onsubmit="return confirm('Delete this entry?');">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="del_id" value="{{ p.id }}">
                        <button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-trash"></i></button>
                    </form>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page("Packet Inward", render_template_string(html, pending=pending, stations=stations))

# ==========================================
# 📤 3.6 OUTWARD HUB (FULL: Voice, Camera, Bag, Edit, Delete, Finalize)
# ==========================================
@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    st = session.get('branch', 'HQ')
    date_today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            # ADD ENTRY / UNPACK BAG
            if action == 'add':
                awb = request.form.get('awb', '').strip().upper()
                dest = request.form.get('dest', '').strip().upper()
                wt = safe_float(request.form.get('wt', 1.0))
                info = request.form.get('info', '')
                entry_date = request.form.get('date', date_today)
                if awb:
                    if dest: c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest,))
                    # BAG Unpack Logic
                    if awb.startswith("BAG"):
                        c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb,))
                        items = c.fetchall()
                        if not items:
                            flash(f"Bag {awb} empty or invalid!", "error")
                        else:
                            success = 0
                            for itm in items:
                                sub_awb = itm['awb_no']
                                c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND entry_date=%s AND out_station=%s", (sub_awb, entry_date, st))
                                if not c.fetchone():
                                    c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) VALUES(%s,%s,'HQ',%s,%s,%s,%s,0)", (entry_date, sub_awb, st, dest, wt, f"From {awb}"))
                                    c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, dest_station=%s WHERE awb_no=%s", (st, dest, sub_awb))
                                    success += 1
                            flash(f"✅ Bag {awb} unpacked! {success} items added.", "success")
                    else:
                        c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND entry_date=%s AND out_station=%s", (awb, entry_date, st))
                        if c.fetchone():
                            flash(f"AWB {awb} already scanned!", "error")
                        else:
                            c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) VALUES(%s,%s,'HQ',%s,%s,%s,%s,0)", (entry_date, awb, st, dest, wt, info))
                            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                            s = c.fetchone()
                            if s:
                                c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, dest_station=%s, weight_kg=%s WHERE awb_no=%s", (st, dest, wt, awb))
                                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'OUTWARD', %s, 'Web Outward Entry')", (s['id'], st))
                            else:
                                # 🛠️ FIX: Force dest_name to be a blank string instead of NULL so 'None' stops showing up
                                c.execute("INSERT INTO shipments(awb_no, booking_date, dest_name, dest_station, weight_kg, service_type, status, current_location, info) VALUES(%s, %s, '', %s, %s, 'SURFACE', 'OUTWARD', %s, %s)", (awb, entry_date, dest, wt, st, info))
                            flash(f"✅ AWB {awb} Saved to Outward!", "success")
            # EDIT PENDING
            elif action == 'edit_pending':
                oid = request.form.get('edit_id')
                awb = request.form.get('awb', '').strip().upper()
                dest = request.form.get('dest', '').strip().upper()
                wt = safe_float(request.form.get('wt', 1.0))
                info = request.form.get('info', '')
                c.execute("SELECT awb_no FROM outward_register WHERE id=%s", (oid,))
                old = c.fetchone()
                if old:
                    c.execute("UPDATE outward_register SET awb_no=%s, destination=%s, weight=%s, info=%s WHERE id=%s", (awb, dest, wt, info, oid))
                    c.execute("UPDATE shipments SET awb_no=%s, dest_station=%s, weight_kg=%s, info=%s WHERE awb_no=%s", (awb, dest, wt, info, old['awb_no']))
                    flash("Entry updated & synced!", "success")
            # DELETE
            elif action == 'delete':
                c.execute("DELETE FROM outward_register WHERE id=%s", (request.form.get('del_id'),))
                flash("Entry deleted!", "success")
            # FINALIZE
            elif action == 'finalize':
                entry_date = request.form.get('date', date_today)
                c.execute("SELECT * FROM outward_register WHERE entry_date=%s AND out_station=%s AND finalized=0", (entry_date, st))
                rows = c.fetchall()
                if not rows:
                    flash("No pending entries to finalize!", "error")
                else:
                    ono = get_seq("outward", "OUT", 6)
                    mno = get_seq("manifest", "MF", 7)
                    c.execute("INSERT INTO manifests(manifest_no, manifest_type, from_location, to_location, vehicle_no, status) VALUES(%s, 'OUTWARD', %s, %s, '', 'OPEN')", (mno, 'HQ', st))
                    mid = c.lastrowid
                    for r in rows:
                        c.execute("UPDATE outward_register SET finalized=1, outward_no=%s, manifest_no=%s WHERE id=%s", (ono, mno, r['id']))
                        c.execute("SELECT id FROM shipments WHERE awb_no=%s", (r['awb_no'],))
                        s = c.fetchone()
                        if s:
                            c.execute("INSERT INTO manifest_items(manifest_id, shipment_id, received) VALUES(%s, %s, 0)", (mid, s['id']))
                            c.execute("UPDATE shipments SET status='OUTWARD' WHERE id=%s", (s['id'],))
                    flash(f"✅ Finalized! Outward: {ono} | Manifest: {mno}", "success")
            # UNFINALIZE
            elif action == 'unfinalize':
                ono = request.form.get('outward_no')
                c.execute("UPDATE outward_register SET finalized=0, outward_no=NULL, manifest_no=NULL WHERE outward_no=%s", (ono,))
                flash(f"Session {ono} unfinalized!", "success")
            # CREATE MASTER BAG
            elif action == 'create_bag':
                dest = request.form.get('bag_dest', '').strip().upper()
                awb_list = request.form.get('bag_awbs', '').split(',')
                if dest and awb_list:
                    bag_no = get_seq("bag", "BAG", 6)
                    c.execute("INSERT INTO master_bags(bag_no, destination) VALUES(%s, %s)", (bag_no, dest))
                    for a in awb_list:
                        a = a.strip().upper()
                        if a: c.execute("INSERT INTO master_bag_items(bag_no, awb_no) VALUES(%s, %s)", (bag_no, a))
                    flash(f"🎒 Master Bag Created: {bag_no} with {len(awb_list)} items!", "success")
        conn.commit()
        return redirect('/outward')
    
    with conn.cursor() as c:
        c.execute("SELECT * FROM outward_register WHERE out_station=%s AND finalized=0 ORDER BY id DESC", (st,))
        pending = c.fetchall()
        c.execute("SELECT outward_no, MIN(entry_date) as d, COUNT(*) as c, MIN(manifest_no) as m FROM outward_register WHERE finalized=1 AND out_station=%s GROUP BY outward_no ORDER BY d DESC", (st,))
        sessions_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top:4px solid #2563eb;">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold text-slate-800">📤 Outward Hub Entry</h3>
            <div class="flex gap-2">
                <button type="button" class="btn-danger" onclick="startVoice()"><i class="fas fa-microphone"></i> Voice</button>
                <button type="button" class="btn-primary" onclick="document.getElementById('camModal').style.display='block'"><i class="fas fa-camera"></i> Camera</button>
                <button type="button" class="btn-warning" onclick="document.getElementById('bagModal').style.display='block'"><i class="fas fa-shopping-bag"></i> Master Bag</button>
            </div>
        </div>
        <form method="POST" id="addForm" class="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
            <input type="hidden" name="action" value="add">
            <div><label class="label-modern">Date</label><input type="date" name="date" id="date_input" value="{{ date_today }}" required class="input-modern"></div>
            <div><label class="label-modern">Scan Mode</label><select name="scan_mode" id="scan_mode" class="input-modern font-bold"><option value="MANUAL">MANUAL</option><option value="AUTO">AUTO</option></select></div>
            <div><label class="label-modern text-red-600">AWB / BAG *</label><input type="text" name="awb" id="awb_input" required autofocus class="input-modern font-bold text-red-600 uppercase" autocomplete="off"></div>
            <div><label class="label-modern">Destination *</label><input type="text" name="dest" id="dest_input" list="st_list" required class="input-modern uppercase" autocomplete="off"><datalist id="st_list">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
            <div><label class="label-modern">Weight</label><input type="number" step="0.01" name="wt" id="wt_input" value="1.0" class="input-modern"></div>
            <div><button type="submit" class="btn-primary w-full"><i class="fas fa-plus"></i> SAVE</button></div>
        </form>
    </div>
    <div class="card mt-4">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold text-slate-800">Pending Unfinalized ({{ pending|length }})</h3>
            <form method="POST" onsubmit="return confirm('Finalize all entries?');">
                <input type="hidden" name="action" value="finalize">
                <input type="hidden" name="date" id="fin_date_input" value="{{ date_today }}">
                <button type="submit" class="btn-success"><i class="fas fa-check-double"></i> FINALIZE & MANIFEST</button>
            </form>
        </div>
        <div class="table-responsive" style="max-height:300px; overflow-y:auto;">
        <table class="datatable" id="pendingTable">
            <thead class="sticky top-0"><tr><th>ID</th><th>AWB</th><th>Dest</th><th>Weight</th><th>Info</th><th>Action</th></tr></thead>
            <tbody>
            {% for p in pending %}
            <tr onclick="selectRow(this, '{{ p.id }}', '{{ p.awb_no }}', '{{ p.destination }}', '{{ p.weight }}', '{{ p.info }}')" class="cursor-pointer hover:bg-amber-50">
                <td>{{ p.id }}</td>
                <td class="font-bold text-red-600">{{ p.awb_no }}</td>
                <td class="font-bold text-blue-600">{{ p.destination }}</td>
                <td>{{ p.weight }}</td>
                <td>{{ p.info }}</td>
                <td><form method="POST" style="display:inline;" onsubmit="return confirm('Delete?');"><input type="hidden" name="action" value="delete"><input type="hidden" name="del_id" value="{{ p.id }}"><button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-trash"></i></button></form></td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
        <div class="flex gap-3 mt-3">
            <button type="button" class="btn-primary flex-1" onclick="openEditModal()"><i class="fas fa-edit"></i> EDIT SELECTED</button>
        </div>
    </div>
    <div class="card mt-4">
        <h3 class="text-lg font-bold text-slate-800 mb-4">Manifests History</h3>
        <table class="datatable">
            <thead><tr><th>Outward No</th><th>Date</th><th>Docs</th><th>Manifest</th><th>Action</th></tr></thead>
            <tbody>
            {% for s in sessions_list %}
            <tr>
                <td class="font-bold text-green-600">{{ s.outward_no }}</td>
                <td>{{ s.d }}</td>
                <td>{{ s.c }}</td>
                <td>{{ s.m }}</td>
                <td><form method="POST" style="display:inline;" onsubmit="return confirm('Unfinalize?');"><input type="hidden" name="action" value="unfinalize"><input type="hidden" name="outward_no" value="{{ s.outward_no }}"><button type="submit" class="btn-warning" style="padding:3px 8px; font-size:11px;"><i class="fas fa-undo"></i></button></form></td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    <!-- MODAL: MASTER BAG -->
    <div id="bagModal" class="modal">
        <div class="modal-content">
            <h3 class="text-lg font-bold text-slate-800 mb-4">🎒 Create Master Bag</h3>
            <form method="POST">
                <input type="hidden" name="action" value="create_bag">
                <div class="space-y-3">
                    <div><label class="label-modern">Bag Destination</label><input type="text" name="bag_dest" list="st_list" class="input-modern uppercase" required></div>
                    <div><label class="label-modern">Scan AWBs (Comma separated)</label><textarea name="bag_awbs" class="input-modern" rows="5" required></textarea></div>
                </div>
                <div class="flex gap-3 mt-4">
                    <button type="button" class="btn-danger flex-1" onclick="document.getElementById('bagModal').style.display='none'">Cancel</button>
                    <button type="submit" class="btn-warning flex-1"><i class="fas fa-lock"></i> Seal Bag</button>
                </div>
            </form>
        </div>
    </div>
    <!-- MODAL: EDIT -->
    <div id="editModal" class="modal">
        <div class="modal-content">
            <h3 class="text-lg font-bold text-slate-800 mb-4">✏️ Edit Pending Entry</h3>
            <form method="POST">
                <input type="hidden" name="action" value="edit_pending">
                <input type="hidden" name="edit_id" id="edit_id_input">
                <div class="space-y-3">
                    <div><label class="label-modern">AWB</label><input type="text" name="awb" id="edit_awb" class="input-modern uppercase" required></div>
                    <div><label class="label-modern">Dest</label><input type="text" name="dest" id="edit_dest" class="input-modern uppercase" required></div>
                    <div><label class="label-modern">Weight</label><input type="text" name="wt" id="edit_wt" class="input-modern" required></div>
                    <div><label class="label-modern">Info</label><input type="text" name="info" id="edit_info" class="input-modern"></div>
                </div>
                <div class="flex gap-3 mt-4">
                    <button type="button" class="btn-danger flex-1" onclick="document.getElementById('editModal').style.display='none'">Cancel</button>
                    <button type="submit" class="btn-primary flex-1"><i class="fas fa-save"></i> Save</button>
                </div>
            </form>
        </div>
    </div>
    <!-- MODAL: CAMERA -->
    <div id="camModal" class="modal">
        <div class="modal-content" style="width:450px; text-align:center;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📷 Webcam Scanner</h3>
            <div id="reader" style="width:100%; height:300px; background:#000; border-radius:8px; margin-bottom:10px;"></div>
            <button class="btn-danger" onclick="closeCamera()">Close Camera</button>
        </div>
    </div>
    <script src="https://unpkg.com/html5-qrcode"></script>
    <script>
    let selectedRowId = null, selAwb = "", selDest = "", selWt = "", selInfo = "";
    function selectRow(tr, id, awb, dest, wt, info) {
        let rows = document.getElementById("pendingTable").getElementsByTagName("tr");
        for (let i = 0; i < rows.length; i++) rows[i].classList.remove("bg-amber-100");
        tr.classList.add("bg-amber-100");
        selectedRowId = id; selAwb = awb; selDest = dest; selWt = wt; selInfo = info;
    }
    function openEditModal() {
        if(!selectedRowId) { alert("Select an entry first!"); return; }
        document.getElementById('edit_id_input').value = selectedRowId;
        document.getElementById('edit_awb').value = selAwb;
        document.getElementById('edit_dest').value = selDest;
        document.getElementById('edit_wt').value = selWt;
        document.getElementById('edit_info').value = selInfo;
        document.getElementById('editModal').style.display = 'block';
    }
    document.getElementById('awb_input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            if(document.getElementById('scan_mode').value === 'AUTO') document.getElementById('addForm').submit();
            else document.getElementById('dest_input').focus();
        }
    });
    function startVoice() {
        if (!('webkitSpeechRecognition' in window)) { alert("Voice requires Chrome!"); return; }
        const recognition = new webkitSpeechRecognition();
        recognition.lang = 'en-IN'; recognition.start();
        document.getElementById('awb_input').placeholder = "🎙️ Listening...";
        recognition.onresult = function(event) {
            const text = event.results[0][0].transcript.toLowerCase();
            const awbMatch = text.match(/(?:awb|parcel|number)\\s*([a-z0-9]+)/);
            const destMatch = text.match(/(?:destination|to)\\s*([a-z]+)/);
            if(awbMatch) document.getElementById('awb_input').value = awbMatch[1].toUpperCase();
            if(destMatch) document.getElementById('dest_input').value = destMatch[1].toUpperCase();
            if(awbMatch) document.getElementById('addForm').submit();
        };
    }
    let html5QrcodeScanner;
    function openCamera() {
        document.getElementById('camModal').style.display = 'block';
        html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: 250 });
        html5QrcodeScanner.render(function(decodedText) {
            document.getElementById('awb_input').value = decodedText;
            closeCamera();
            if(document.getElementById('scan_mode').value === 'AUTO') document.getElementById('addForm').submit();
            else document.getElementById('dest_input').focus();
        });
    }
    function closeCamera() {
        document.getElementById('camModal').style.display = 'none';
        if (html5QrcodeScanner) html5QrcodeScanner.clear();
    }
    </script>
    """
    return render_page("Outward Hub", render_template_string(html, pending=pending, sessions_list=sessions_list, stations=stations, date_today=date_today))

# ==========================================
# 💰 3.7 LEDGER (FIXED: Admin + Customer Access)
# ==========================================
# ==========================================
# 💰 3.7 MY LEDGER (CUSTOMER PANEL) - FIXED
# ==========================================
@app.route('/my_ledger', methods=['GET'])
@login_required
def my_ledger():
    # 1. Agar Admin/Accounts login hai, toh seedha Party Ledger pe bhejo
    if session.get('role') != 'CUSTOMER':
        return redirect('/party_ledger')
        
    conn = get_db()
    cid = session.get('customer_id')
    
    # 2. ERROR HANDLING: Agar Admin ne User ko Customer Profile se link nahi kiya hai
    if not cid:
        return render_page("My Ledger", """
        <div class='card p-12 text-center mt-6'>
            <i class='fas fa-exclamation-triangle text-5xl text-red-500 mb-4'></i>
            <h3 class='text-xl font-bold text-red-600'>Account Not Linked</h3>
            <p class='text-slate-600 mt-2 font-medium'>Aapka user account kisi B2B Customer Profile se juda hua nahi hai.</p>
            <p class='text-slate-500 text-sm mt-1'>Kripya Admin se kahin ki "User Setup" me jakar aapki profile ko 'Link Customer' se update karein.</p>
        </div>
        """)

    # 3. DATE FILTERS (Default: 1st of the month to Today)
    f_date = request.args.get('from_date', datetime.datetime.now().replace(day=1).strftime('%Y-%m-%d'))
    t_date = request.args.get('to_date', datetime.datetime.now().strftime('%Y-%m-%d'))
    
    l_data = []; c_bal = 0.0; customer_name = ""
    
    with conn.cursor() as c:
        # Get Customer Name
        c.execute("SELECT name FROM customers WHERE id=%s", (cid,))
        cst = c.fetchone()
        if cst: customer_name = cst['name']
        
        # Fetch Date-Filtered Ledger Data
        c.execute("""SELECT entry_date, voucher_type, reference, debit, credit, narration 
            FROM ledger WHERE customer_id=%s AND entry_date BETWEEN %s AND %s 
            ORDER BY entry_date ASC, id ASC""", (cid, f_date, t_date))
        l_data = c.fetchall()
        
        # Get Net Outstanding Total (Overall)
        c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (cid,))
        r = c.fetchone()
        c_bal = safe_float(r['b']) if r else 0.0
    conn.close()
    
    html = """
    <div class="card" style="background:#f8fafc;">
        <form method="GET" class="flex flex-wrap gap-3 items-end p-5">
            <div><label class="label-modern">📅 From Date</label><input type="date" name="from_date" value="{{ f_date }}" class="input-modern" required></div>
            <div><label class="label-modern">📅 To Date</label><input type="date" name="to_date" value="{{ t_date }}" class="input-modern" required></div>
            <button type="submit" class="btn-primary"><i class="fas fa-search"></i> Load Statement</button>
            <button type="button" class="btn-warning" onclick="window.print()"><i class="fas fa-print"></i> Print</button>
        </form>
    </div>
    
    <div class="card mt-6">
        <div class="flex justify-between items-center mb-4 p-5 border-b border-slate-200">
            <h3 class="text-lg font-bold text-slate-800">📒 Account Statement: <span class="text-blue-600">{{ customer_name }}</span></h3>
            <div class="px-4 py-2 rounded-lg font-bold text-lg {% if c_bal > 0 %}bg-red-50 text-red-700 border border-red-200{% else %}bg-green-50 text-green-700 border border-green-200{% endif %}">
                Net Outstanding: ₹ {{ "{:,.2f}".format(c_bal) }}
            </div>
        </div>
        <div class="table-responsive px-5 pb-5">
            <table class="datatable">
                <thead><tr><th>Date</th><th>Voucher Type</th><th>Reference</th><th>Narration</th><th>Debit (Bill ₹)</th><th>Credit (Paid ₹)</th></tr></thead>
                <tbody>
                {% for l in l_data %}
                <tr>
                    <td>{{ l.entry_date }}</td>
                    <td><span class="px-2 py-1 rounded-full text-xs font-bold {% if l.voucher_type == 'INVOICE' %}bg-purple-100 text-purple-700{% else %}bg-green-100 text-green-700{% endif %}">{{ l.voucher_type }}</span></td>
                    <td class="font-bold">{{ l.reference }}</td>
                    <td>{{ l.narration }}</td>
                    <td class="text-red-600 font-bold">{% if l.debit > 0 %}₹ {{ l.debit }}{% else %}-{% endif %}</td>
                    <td class="text-green-600 font-bold">{% if l.credit > 0 %}₹ {{ l.credit }}{% else %}-{% endif %}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("My Ledger", render_template_string(html, l_data=l_data, c_bal=c_bal, f_date=f_date, t_date=t_date, customer_name=customer_name))

# ==========================================
# 🚀 3.8 B2B CUSTOMER BULK BOOKING (CSV)
# ==========================================
@app.route('/customer_bulk', methods=['GET', 'POST'])
@login_required
def customer_bulk():
    if session.get('role') != 'CUSTOMER': return redirect('/')
    conn = get_db()
    cid = session.get('customer_id')
    
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            flash("Invalid file! Please upload a .csv file.", "error")
            return redirect('/customer_bulk')
        
        try:
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            reader = csv.DictReader(stream)
            headers = {k.strip().lower(): k for k in reader.fieldnames if k}
            
            added = 0
            total_billing = 0.0
            
            with conn.cursor() as c:
                # Get Customer Detail for Origin Info
                c.execute("SELECT name, phone, address, state_code FROM customers WHERE id=%s", (cid,))
                cust = c.fetchone()
                
                for row in reader:
                    # CSV Column Mapping
                    dest_name = row.get(headers.get("consignee name", "consignee name")) or row.get("Consignee Name", "")
                    dest_phone = row.get(headers.get("phone", "phone")) or row.get("Phone", "")
                    dest_address = row.get(headers.get("address", "address")) or row.get("Address", "")
                    dest_station = row.get(headers.get("destination", "destination")) or row.get("Destination", "")
                    dest_state_code = row.get(headers.get("state code", "state code")) or row.get("State Code", "")
                    wt = safe_float(row.get(headers.get("weight", "weight")) or "1")
                    pcs = safe_int(row.get(headers.get("pieces", "pieces")) or "1")
                    cod = safe_float(row.get(headers.get("cod amount", "cod amount")) or "0")
                    
                    if not dest_name or not dest_station: continue
                    
                    # 🧮 Auto-Calculate Rates (Customer Specific or Default)
                    c.execute("SELECT * FROM rates WHERE active=1 AND customer_id=%s AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (cid, cust['state_code'], dest_state_code, wt))
                    rate_row = c.fetchone()
                    if not rate_row:
                        c.execute("SELECT * FROM rates WHERE active=1 AND customer_id IS NULL AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (cust['state_code'], dest_state_code, wt))
                        rate_row = c.fetchone()
                    
                    fr = 0.0; tx = 18.0
                    if rate_row:
                        fr = safe_float(rate_row['fixed_charge']) + (wt * safe_float(rate_row['per_kg_rate']))
                        tx = safe_float(rate_row['gst_rate'])
                    else:
                        fr = wt * 25.0 # Fallback default freight
                        
                    fuel = safe_float(get_setting("fuel_surcharge", "0"))
                    taxable = fr * (1 + (fuel/100))
                    gst = taxable * (tx/100)
                    tot = taxable + gst
                    
                    cgst = sgst = igst = 0
                    if cust['state_code'].strip().upper() == str(dest_state_code).strip().upper(): cgst = sgst = gst / 2
                    else: igst = gst
                        
                    # Auto-Generate AWB
                    awb = get_seq("awb", "AWB", 8)
                    
                    d = datetime.datetime.now().strftime("%Y-%m-%d")
                    c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest_station.upper(),))
                    
                    c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, origin_phone, origin_address, origin_state_code, dest_name, dest_phone, dest_address, dest_state_code, dest_station, weight_kg, quantity, cod_amount, service_type, status, current_location, taxable_amount, tax_rate, cgst, sgst, igst, total_amount, is_synced) 
                                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'SURFACE','BOOKED','Origin',%s,%s,%s,%s,%s,%s, 0)""", 
                              (awb, cid, d, cust['name'], cust['phone'], cust['address'], cust['state_code'], dest_name, dest_phone, dest_address, dest_state_code, dest_station.upper(), wt, pcs, cod, taxable, tx, cgst, sgst, igst, tot))
                    
                    sid = c.lastrowid
                    c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'BOOKED','Origin','B2B Bulk CSV Booking') ", (sid,))
                    added += 1
                    total_billing += tot
            
            # Master Ledger Entry (Ek sath poori list ka bill ban jayega)
            if total_billing > 0:
                with conn.cursor() as c:
                    d = datetime.datetime.now().strftime("%Y-%m-%d")
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (cid, d, f"BULK-{added}AWB", total_billing, f"Bulk Booking {added} parcels"))
            
            conn.commit()
            flash(f"🎉 Bulk Booking Complete! {added} Parcels Booked. Total Billed: ₹{total_billing:,.2f}", "success")
        except Exception as e:
            flash(f"Error: {e}", "error")
        finally:
            conn.close()
        return redirect('/customer_bulk')
        
    html = """
    <div class="card" style="border-top:4px solid #8b5cf6;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">🚀 B2B Bulk Booking (CSV Upload)</h3>
        <div style="background:#f5f3ff; padding:15px; border-radius:8px; border:1px dashed #8b5cf6; margin-bottom:20px; font-size:13px; color:#4c1d95;">
            <b>File Structure Required (Comma Separated CSV):</b><br><br>
            • <b>Consignee Name</b> (Receiver's Name)<br>
            • <b>Phone</b> (Receiver's Phone)<br>
            • <b>Address</b> (Full Address)<br>
            • <b>Destination</b> (City/Station Name)<br>
            • <b>State Code</b> (e.g., 08 for RJ, 27 for MH)<br>
            • <b>Weight</b> (in KG)<br>
            • <b>Pieces</b> (Total Boxes)<br>
            • <b>COD Amount</b> (Put 0 if prepaid)<br><br>
            <i>💡 Note: The system will automatically generate AWB numbers, calculate accurate freight based on your contract, and update your ledger.</i>
        </div>
        <form method="POST" enctype="multipart/form-data" class="space-y-4">
            <div>
                <label class="label-modern">Upload CSV File *</label>
                <input type="file" name="file" accept=".csv" required class="input-modern" style="padding:12px;">
            </div>
            <button type="submit" style="background:#8b5cf6; color:white; padding:10px 20px; border-radius:6px; font-weight:bold; width:100%;"><i class="fas fa-upload"></i> Process Bulk Upload</button>
        </form>
    </div>
    """
    return render_page("Bulk Booking", render_template_string(html))

#⚠ PART 3 ENDS HERE. PART 4 (DRS, Master Bag, Accounts, Expenses, Invoices) agle message me aayega.

# ============================================================
# 📦 PART 4: DRS, FINANCE & BILLING MODULE (FULL CRUD)
# ============================================================

# ==========================================
# 🛵 4.1 D.R.S. (DELIVERY RUN SHEET) — FULL CRUD
# ==========================================
@app.route('/drs', methods=['GET', 'POST'])
@login_required
def drs():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    date_today = datetime.datetime.now().strftime('%Y-%m-%d')
    st = session.get('branch', 'HQ')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            # ➕ ADD TO DRS QUEUE
            if action == 'add':
                awb = request.form.get('awb', '').strip().upper()
                boy = request.form.get('boy', '').strip()
                area = request.form.get('area', '').strip()
                rec = request.form.get('rec', '').strip()
                info = request.form.get('info', '')
                c.execute("SELECT id FROM delivery_register WHERE awb_no=%s AND finalized=0", (awb,))
                if c.fetchone():
                    flash(f"AWB {awb} already pending for delivery!", "error")
                else:
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    s = c.fetchone()
                    if s:
                        if s.get('status') in ('DELIVERED', 'CANCELLED'):
                            flash(f"AWB {awb} cannot be assigned in its current status.", "error")
                            conn.rollback()
                            return redirect('/drs')
                        c.execute("INSERT INTO delivery_register(entry_date, delivery_boy, delivery_area, awb_no, receiver_name, info, finalized) VALUES(%s, %s, %s, %s, %s, %s, 0)",
                            (date_today, boy, area, awb, rec, info))
                        c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE id=%s", (area, s['id']))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'ON_DRS', %s, %s)", (s['id'], area, f"Assigned to {boy}"))
                        flash(f"✅ {awb} added to delivery queue for {boy}.", "success")
                    else:
                        flash(f"AWB {awb} does not exist in shipments.", "error")
            
            # 🗑️ DELETE FROM QUEUE
            elif action == 'delete':
                did = request.form.get('del_id')
                c.execute("SELECT awb_no FROM delivery_register WHERE id=%s", (did,))
                dr = c.fetchone()
                if dr:
                    c.execute("UPDATE shipments SET status='INWARD', current_location='Hub' WHERE awb_no=%s AND status='ON_DRS'", (dr['awb_no'],))
                c.execute("DELETE FROM delivery_register WHERE id=%s", (did,))
                flash("Entry removed from pending delivery.", "success")
            
            # 🏁 FINALIZE & GENERATE DRS
            elif action == 'finalize':
                c.execute("SELECT DISTINCT delivery_boy, delivery_area FROM delivery_register WHERE finalized=0")
                groups = c.fetchall()
                if not groups:
                    flash("No pending entries to finalize.", "error")
                else:
                    generated = []
                    for grp in groups:
                        boy = grp['delivery_boy']; area = grp['delivery_area']
                        c.execute("SELECT * FROM delivery_register WHERE finalized=0 AND delivery_boy=%s AND delivery_area=%s", (boy, area))
                        rows = c.fetchall()
                        if rows:
                            drs_no = get_seq("drs", "DRS", 6)
                            # ✅ FIX: rider_phone column removed (not in table)
                            c.execute("INSERT INTO drs(drs_no, drs_date, rider_name, vehicle_no, status) VALUES(%s, %s, %s, %s, 'OPEN')", (drs_no, date_today, boy, area))
                            drs_id = c.lastrowid
                            for r in rows:
                                c.execute("UPDATE delivery_register SET finalized=1, drs_no=%s WHERE id=%s", (drs_no, r['id']))
                                c.execute("SELECT id FROM shipments WHERE awb_no=%s", (r['awb_no'],))
                                s = c.fetchone()
                                if s:
                                    c.execute("INSERT INTO drs_items(drs_id, shipment_id, status, receiver_name) VALUES(%s, %s, 'ASSIGNED', %s)", (drs_id, s['id'], r['receiver_name']))
                            generated.append(f"{drs_no} ({boy})")
                    flash(f"✅ DRS Generated: {', '.join(generated)}", "success")
            
            # 🔄 UNFINALIZE DRS
            elif action == 'unfinalize':
                dno = request.form.get('drs_no')
                c.execute("SELECT id FROM drs WHERE drs_no=%s", (dno,))
                drs_row = c.fetchone()
                if drs_row:
                    did = drs_row['id']
                    c.execute("SELECT shipment_id FROM drs_items WHERE drs_id=%s", (did,))
                    s_items = c.fetchall()
                    for s_item in s_items:
                        c.execute("UPDATE shipments SET status='INWARD', current_location='Hub' WHERE id=%s AND status IN ('ON_DRS','DELIVERED')", (s_item['shipment_id'],))
                    c.execute("DELETE FROM drs_items WHERE drs_id=%s", (did,))
                    c.execute("DELETE FROM drs WHERE id=%s", (did,))
                    c.execute("UPDATE delivery_register SET finalized=0, drs_no=NULL WHERE drs_no=%s", (dno,))
                    flash(f"DRS {dno} unfinalized & moved back to pending.", "success")
            
            # ✅ DELIVER SINGLE ITEM
            elif action == 'deliver':
                item_id = request.form.get('item_id')
                receiver = request.form.get('receiver', '')
                remarks = request.form.get('remarks', '')
                c.execute("UPDATE drs_items SET status='DELIVERED', receiver_name=%s, remarks=%s WHERE id=%s", (receiver, remarks, item_id))
                c.execute("SELECT shipment_id, drs_id FROM drs_items WHERE id=%s", (item_id,))
                itm = c.fetchone()
                if itm:
                    c.execute("UPDATE shipments SET status='DELIVERED' WHERE id=%s", (itm['shipment_id'],))
                    c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'DELIVERED', %s, %s)", (itm['shipment_id'], st, f"Receiver: {receiver}"))
                    c.execute("SELECT COUNT(*) as cnt FROM drs_items WHERE drs_id=%s AND status != 'DELIVERED'", (itm['drs_id'],))
                    remaining = c.fetchone()
                    if remaining['cnt'] == 0:
                        c.execute("UPDATE drs SET status='COMPLETED' WHERE id=%s", (itm['drs_id'],))
                    flash("✅ Delivered successfully!", "success")
        conn.commit()
        return redirect('/drs')
    
    # Fetch data
    with conn.cursor() as c:
        c.execute("SELECT * FROM delivery_register WHERE finalized=0 ORDER BY id DESC")
        pending = c.fetchall()
        c.execute("SELECT drs_no, MIN(entry_date) as d, MIN(delivery_boy) as b, MIN(delivery_area) as a, COUNT(*) as cnt FROM delivery_register WHERE finalized=1 GROUP BY drs_no ORDER BY d DESC, drs_no DESC LIMIT 200")
        sessions_list = c.fetchall()
        c.execute("SELECT full_name FROM users WHERE role='DELIVERY' AND active=1")
        boys = c.fetchall()
        c.execute("SELECT d.*, (SELECT COUNT(*) FROM drs_items WHERE drs_id=d.id) as total_items, (SELECT COUNT(*) FROM drs_items WHERE drs_id=d.id AND status='DELIVERED') as delivered FROM drs d ORDER BY d.id DESC LIMIT 50")
        active_drs = c.fetchall()
    conn.close()
    
    html = """
    <div class="flex gap-2 mb-4">
        <button class="tab-btn active" onclick="openTab(event, 'tab1')">🛵 Create DRS</button>
        <button class="tab-btn" onclick="openTab(event, 'tab2')">📋 DRS History</button>
        <button class="tab-btn" onclick="openTab(event, 'tab3')">✅ Delivery Scan</button>
    </div>
    
    <!-- TAB 1: CREATE DRS -->
    <div id="tab1" class="tab-content active">
        <div class="card" style="border-top:4px solid #f59e0b;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">🛵 Scan Parcels For Delivery</h3>
            <form method="POST" class="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
                <input type="hidden" name="action" value="add">
                <div><label class="label-modern">Delivery Boy *</label>
                    <input type="text" name="boy" list="boy_list" required class="input-modern uppercase">
                    <datalist id="boy_list">{% for b in boys %}<option value="{{ b.full_name }}">{% endfor %}</datalist>
                </div>
                <div><label class="label-modern">Route / Area</label><input type="text" name="area" class="input-modern"></div>
                <div><label class="label-modern text-red-600">AWB No *</label><input type="text" name="awb" required autofocus class="input-modern font-bold text-red-600 uppercase"></div>
                <div><label class="label-modern">Receiver Name</label><input type="text" name="rec" class="input-modern"></div>
                <div><button type="submit" class="btn-warning w-full"><i class="fas fa-plus"></i> Add Entry</button></div>
            </form>
        </div>
        <div class="card mt-4">
            <div class="flex justify-between items-center mb-3">
                <h3 class="text-lg font-bold text-slate-800">Pending DRS Queue ({{ pending|length }})</h3>
                <form method="POST" onsubmit="return confirm('Generate DRS sheets for all riders?');">
                    <input type="hidden" name="action" value="finalize">
                    <button type="submit" class="btn-success"><i class="fas fa-check-double"></i> FINALIZE & GENERATE DRS</button>
                </form>
            </div>
            <table class="datatable">
                <thead><tr><th>Rider</th><th>Area</th><th>AWB No</th><th>Receiver</th><th>Info</th><th>Action</th></tr></thead>
                <tbody>
                {% for p in pending %}
                <tr>
                    <td class="font-bold">{{ p.delivery_boy }}</td>
                    <td>{{ p.delivery_area }}</td>
                    <td class="font-bold text-red-600">{{ p.awb_no }}</td>
                    <td>{{ p.receiver_name }}</td>
                    <td>{{ p.info }}</td>
                    <td>
                        <form method="POST" style="display:inline;" onsubmit="return confirm('Remove?');">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="del_id" value="{{ p.id }}">
                            <button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-trash"></i></button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- TAB 2: DRS HISTORY -->
    <div id="tab2" class="tab-content">
        <div class="card">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📋 Finalized DRS History</h3>
            <table class="datatable">
                <thead><tr><th>DRS No</th><th>Date</th><th>Rider</th><th>Area</th><th>Parcels</th><th>Actions</th></tr></thead>
                <tbody>
                {% for s in sessions_list %}
                <tr>
                    <td class="font-bold text-green-600">{{ s.drs_no }}</td>
                    <td>{{ s.d }}</td>
                    <td class="font-bold">{{ s.b }}</td>
                    <td>{{ s.a }}</td>
                    <td class="font-bold text-blue-600">{{ s.cnt }} Docs</td>
                    <td>
                        <form method="POST" style="display:inline;" onsubmit="return confirm('#⚠ Unfinalize this DRS? Parcels will go back to pending.');">
                            <input type="hidden" name="action" value="unfinalize">
                            <input type="hidden" name="drs_no" value="{{ s.drs_no }}">
                            <button type="submit" class="btn-warning" style="padding:3px 8px; font-size:11px;"><i class="fas fa-undo"></i></button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <!-- TAB 3: DELIVERY SCAN -->
    <div id="tab3" class="tab-content">
        <div class="card">
            <h3 class="text-lg font-bold text-slate-800 mb-4">✅ Active DRS — Delivery Scan</h3>
            <div class="space-y-4">
            {% for d in active_drs %}
                <div class="border border-slate-200 rounded-lg p-4 bg-slate-50">
                    <div class="flex justify-between items-center mb-3">
                        <div>
                            <span class="font-bold text-blue-600 text-lg">{{ d.drs_no }}</span>
                            <span class="ml-3 text-sm text-slate-500">Rider: {{ d.rider_name }}</span>
                            <span class="ml-3 px-2 py-1 rounded-full text-xs font-bold {% if d.status == 'COMPLETED' %}bg-green-100 text-green-700{% else %}bg-amber-100 text-amber-700{% endif %}">{{ d.status }}</span>
                        </div>
                        <span class="text-sm font-bold">{{ d.delivered }}/{{ d.total_items }} Delivered</span>
                    </div>
                </div>
            {% endfor %}
            {% if not active_drs %}
                <div class="text-center py-8 text-slate-400"><i class="fas fa-inbox text-4xl mb-3"></i><p>No active DRS. Create one first.</p></div>
            {% endif %}
            </div>
        </div>
    </div>
    
    <script>
    function openTab(evt, tabName) {
        document.querySelectorAll('.tab-content').forEach(t => t.style.display = 'none');
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.getElementById(tabName).style.display = 'block';
        evt.currentTarget.classList.add('active');
    }
    </script>
    """
    return render_page("D.R.S. Management", render_template_string(html, pending=pending, sessions_list=sessions_list, boys=boys, active_drs=active_drs))

# ==========================================
# 🎒 4.2 MASTER BAG / MANIFEST GENERATOR
# ==========================================
@app.route('/master_bag', methods=['GET', 'POST'])
@login_required
def master_bag():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            # ➕ CREATE BAG
            if action == 'create':
                dest = request.form.get('dest', '').strip().upper()
                awbs = request.form.get('awbs', '').replace('\n', ',').split(',')
                if dest and awbs:
                    bag_no = get_seq("bag", "BAG", 6)
                    c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest,))
                    c.execute("INSERT INTO master_bags(bag_no, destination) VALUES(%s, %s)", (bag_no, dest))
                    count = 0
                    for a in awbs:
                        a = a.strip().upper()
                        if a:
                            c.execute("INSERT INTO master_bag_items(bag_no, awb_no) VALUES(%s, %s)", (bag_no, a))
                            count += 1
                    flash(f"🎒 Master Bag {bag_no} created with {count} items → {dest}", "success")
            
            # 🗑️ DELETE BAG
            elif action == 'delete':
                bag = request.form.get('bag_no')
                c.execute("DELETE FROM master_bag_items WHERE bag_no=%s", (bag,))
                c.execute("DELETE FROM master_bags WHERE bag_no=%s", (bag,))
                flash(f"Bag {bag} deleted!", "success")
        conn.commit()
        return redirect('/master_bag')
    
    with conn.cursor() as c:
        c.execute("SELECT mb.*, COUNT(mbi.awb_no) as item_count FROM master_bags mb LEFT JOIN master_bag_items mbi ON mb.bag_no=mbi.bag_no GROUP BY mb.bag_no ORDER BY mb.id DESC LIMIT 100")
        bags = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card" style="border-top:4px solid #2563eb;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">🎒 Create Master Bag</h3>
            <form method="POST" class="space-y-3">
                <input type="hidden" name="action" value="create">
                <div><label class="label-modern">Bag Destination *</label>
                    <input type="text" name="dest" list="st_list" class="input-modern uppercase font-bold" required>
                    <datalist id="st_list">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist>
                </div>
                <div><label class="label-modern">Scan AWBs (comma or new line separated)</label>
                    <textarea name="awbs" class="input-modern" rows="6" placeholder="Scan AWBs here..." required></textarea>
                </div>
                <button type="submit" class="btn-primary w-full"><i class="fas fa-lock"></i> Seal Bag</button>
            </form>
            <div class="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-700">
                💡 <b>Tip:</b> Outward Entry me BAG number scan karke poora bag ek saath outward kar sakte ho.
            </div>
        </div>
        <div class="card lg:col-span-2">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📋 Bag Register ({{ bags|length }})</h3>
            <table class="datatable">
                <thead><tr><th>Bag No</th><th>Destination</th><th>Items</th><th>Created</th><th>Action</th></tr></thead>
                <tbody>
                {% for b in bags %}
                <tr>
                    <td class="font-bold text-blue-600">{{ b.bag_no }}</td>
                    <td class="font-bold">{{ b.destination }}</td>
                    <td><span class="px-2 py-1 bg-purple-100 text-purple-700 rounded-full text-xs font-bold">{{ b.item_count }}</span></td>
                    <td>{{ b.created_at }}</td>
                    <td>
                        <form method="POST" style="display:inline;" onsubmit="return confirm('Delete bag {{ b.bag_no }}?');">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="bag_no" value="{{ b.bag_no }}">
                            <button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-trash"></i></button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Outward Manifest Generator", render_template_string(html, bags=bags, stations=stations))

# ==========================================
# 💰 4.3 ACCOUNTS — CASH BOOK / BANK BOOK
# ==========================================
@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    if session.get('role') not in ['ADMIN', 'ACCOUNTS']: return redirect('/')
    conn = get_db()
    date_today = datetime.datetime.now().strftime('%Y-%m-%d')
    book_type = request.args.get('book', 'CASH')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            # ➕ ADD PAYMENT/RECEIPT
            if action == 'add':
                cid = request.form.get('cust_id')
                amt = safe_float(request.form.get('amount'))
                mode = request.form.get('mode', 'CASH')
                ref = request.form.get('reference', '')
                p_date = request.form.get('date', date_today)
                if amt > 0:
                    c.execute("INSERT INTO payments(customer_id, payment_date, amount, mode, reference) VALUES(%s, %s, %s, %s, %s)", (cid if cid else None, p_date, amt, mode, ref))
                    if cid:
                        c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s, %s, 'PAYMENT', %s, 0, %s, %s)", (cid, p_date, ref, amt, f"{mode} Received"))
                    flash(f"✅ Payment of ₹{amt:,.2f} via {mode} recorded!", "success")
                else:
                    flash("Amount must be greater than zero.", "error")
            
            # 🗑️ DELETE PAYMENT (with ledger rollback)
            elif action == 'delete':
                pid = request.form.get('del_id')
                c.execute("SELECT * FROM payments WHERE id=%s", (pid,))
                p = c.fetchone()
                if p:
                    if p['customer_id']:
                        c.execute("DELETE FROM ledger WHERE voucher_type='PAYMENT' AND customer_id=%s AND credit=%s LIMIT 1", (p['customer_id'], p['amount']))
                    c.execute("DELETE FROM payments WHERE id=%s", (pid,))
                    flash("Payment deleted & Ledger reversed.", "success")
        conn.commit()
        return redirect(f'/accounts?book={book_type}')
    
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name")
        custs = c.fetchall()
        c.execute("SELECT p.*, c.name as cust_name FROM payments p LEFT JOIN customers c ON p.customer_id=c.id ORDER BY p.id DESC LIMIT 300")
        pay_list = c.fetchall()
    conn.close()
    
    total_cash = sum(safe_float(p['amount']) for p in pay_list if p['mode'] == 'CASH')
    total_bank = sum(safe_float(p['amount']) for p in pay_list if p['mode'] != 'CASH')
    
    html = """
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div class="card p-4 text-center" style="border-left:4px solid #16a34a;">
            <p class="text-sm text-slate-500 font-medium">Total Cash Received</p>
            <h3 class="text-2xl font-bold text-green-600">₹ {{ "{:,.2f}".format(total_cash) }}</h3>
        </div>
        <div class="card p-4 text-center" style="border-left:4px solid #2563eb;">
            <p class="text-sm text-slate-500 font-medium">Total Bank/UPI Received</p>
            <h3 class="text-2xl font-bold text-blue-600">₹ {{ "{:,.2f}".format(total_bank) }}</h3>
        </div>
        <div class="card p-4 text-center" style="border-left:4px solid #f59e0b;">
            <p class="text-sm text-slate-500 font-medium">Total Transactions</p>
            <h3 class="text-2xl font-bold text-amber-600">{{ pay_list|length }}</h3>
        </div>
    </div>
    <div class="card" style="border-top:4px solid #16a34a;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">💰 Record New Payment / Receipt</h3>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
            <input type="hidden" name="action" value="add">
            <div><label class="label-modern">Customer A/c</label>
                <select name="cust_id" class="input-modern">
                    <option value="">-- Cash / Misc --</option>
                    {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
                </select>
            </div>
            <div><label class="label-modern">Amount (₹) *</label><input type="number" step="0.01" name="amount" required class="input-modern font-bold text-green-600"></div>
            <div><label class="label-modern">Mode *</label>
                <select name="mode" class="input-modern font-bold">
                    <option value="CASH">CASH</option>
                    <option value="BANK">BANK TRANSFER</option>
                    <option value="UPI">UPI / GPay</option>
                    <option value="CHEQUE">CHEQUE</option>
                </select>
            </div>
            <div><label class="label-modern">Reference / UTR</label><input type="text" name="reference" class="input-modern" placeholder="Optional"></div>
            <div><label class="label-modern">Date</label><input type="date" name="date" value="{{ date_today }}" required class="input-modern"></div>
            <div><button type="submit" class="btn-success w-full"><i class="fas fa-save"></i> Save</button></div>
        </form>
    </div>
    <div class="card mt-4">
        <h3 class="text-lg font-bold text-slate-800 mb-4">📋 Payment Register</h3>
        <table class="datatable">
            <thead><tr><th>Txn ID</th><th>Date</th><th>Customer</th><th>Amount</th><th>Mode</th><th>Reference</th><th>Action</th></tr></thead>
            <tbody>
            {% for p in pay_list %}
            <tr>
                <td>TXN-{{ p.id }}</td>
                <td>{{ p.payment_date }}</td>
                <td class="font-bold text-blue-600">{{ p.cust_name or 'CASH / MISC' }}</td>
                <td class="font-bold text-green-600">₹ {{ p.amount }}</td>
                <td><span class="px-2 py-1 rounded-full text-xs font-bold {% if p.mode == 'CASH' %}bg-green-100 text-green-700{% else %}bg-blue-100 text-blue-700{% endif %}">{{ p.mode }}</span></td>
                <td>{{ p.reference or '-' }}</td>
                <td>
                    <form method="POST" style="display:inline;" onsubmit="return confirm('#⚠ Delete payment & reverse ledger?');">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="del_id" value="{{ p.id }}">
                        <button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-trash"></i></button>
                    </form>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page("Cash / Bank Book", render_template_string(html, custs=custs, pay_list=pay_list, date_today=date_today, total_cash=total_cash, total_bank=total_bank))

# ==========================================
# 💸 4.4 EXPENSES — JOURNAL VOUCHER
# ==========================================
@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    if session.get('role') not in ['ADMIN', 'ACCOUNTS']: return redirect('/')
    conn = get_db()
    date_today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            if action == 'add':
                cat = request.form.get('category', 'Miscellaneous')
                amt = safe_float(request.form.get('amount'))
                paid_to = request.form.get('paid_to', '')
                notes = request.form.get('notes', '')
                e_date = request.form.get('date', date_today)
                if amt > 0:
                    c.execute("INSERT INTO expenses(expense_date, category, amount, paid_to, notes) VALUES(%s, %s, %s, %s, %s)", (e_date, cat, amt, paid_to, notes))
                    flash(f"✅ Expense of ₹{amt:,.2f} recorded.", "success")
                else:
                    flash("Amount must be greater than zero.", "error")
            elif action == 'delete':
                eid = request.form.get('del_id')
                c.execute("DELETE FROM expenses WHERE id=%s", (eid,))
                flash("Expense entry deleted.", "success")
        conn.commit()
        return redirect('/expenses')
    
    with conn.cursor() as c:
        c.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT 300")
        exp_list = c.fetchall()
    conn.close()
    
    total_exp = sum(safe_float(e['amount']) for e in exp_list)
    
    html = """
    <div class="card" style="border-top:4px solid #ef4444;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">💸 Add Office / Hub Expense</h3>
        <form method="POST" class="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
            <input type="hidden" name="action" value="add">
            <div><label class="label-modern">Category *</label>
                <select name="category" class="input-modern font-bold">
                    <option>Fuel & Transport</option>
                    <option>Office Rent</option>
                    <option>Staff Salary & Wages</option>
                    <option>Vehicle Maintenance</option>
                    <option>Loading / Unloading</option>
                    <option>Stationery & Printing</option>
                    <option>Electricity & Internet</option>
                    <option>Miscellaneous</option>
                </select>
            </div>
            <div><label class="label-modern">Amount (₹) *</label><input type="number" step="0.01" name="amount" required class="input-modern font-bold text-red-600"></div>
            <div><label class="label-modern">Paid To *</label><input type="text" name="paid_to" class="input-modern" required></div>
            <div><label class="label-modern">Notes</label><input type="text" name="notes" class="input-modern"></div>
            <div><label class="label-modern">Date</label><input type="date" name="date" value="{{ date_today }}" required class="input-modern"></div>
            <div><button type="submit" class="btn-danger w-full"><i class="fas fa-save"></i> Save</button></div>
        </form>
    </div>
    <div class="card mt-4">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold text-slate-800">📋 Expense Register</h3>
            <span class="px-4 py-2 bg-red-50 text-red-700 rounded-lg font-bold text-lg">Total: ₹ {{ "{:,.2f}".format(total_exp) }}</span>
        </div>
        <table class="datatable">
            <thead><tr><th>ID</th><th>Date</th><th>Category</th><th>Paid To</th><th>Amount</th><th>Notes</th><th>Action</th></tr></thead>
            <tbody>
            {% for e in exp_list %}
            <tr>
                <td>EXP-{{ e.id }}</td>
                <td>{{ e.expense_date }}</td>
                <td><span class="px-2 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-bold">{{ e.category }}</span></td>
                <td class="font-bold">{{ e.paid_to }}</td>
                <td class="font-bold text-red-600">₹ {{ e.amount }}</td>
                <td>{{ e.notes }}</td>
                <td>
                    <form method="POST" style="display:inline;" onsubmit="return confirm('Delete expense?');">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="del_id" value="{{ e.id }}">
                        <button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-trash"></i></button>
                    </form>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    """
    return render_page("Journal Voucher Entry", render_template_string(html, exp_list=exp_list, total_exp=total_exp, date_today=date_today))

# ==========================================
# 🧾 4.5 INVOICES — FULL BILLING ENGINE WITH PAYMENT SYNC
# ==========================================
@app.route('/invoices', methods=['GET', 'POST'])
@login_required
def invoices():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    date_today = datetime.datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            # ⚡ AUTO-GENERATE INVOICE
            if action == 'generate':
                cid = request.form.get('cust_id')
                if not cid:
                    flash("Select a customer first!", "error")
                else:
                    c.execute("""SELECT * FROM shipments WHERE customer_id=%s AND total_amount > 0 AND status != 'CANCELLED'
                        AND id NOT IN (SELECT shipment_id FROM invoice_lines WHERE shipment_id IS NOT NULL)""", (cid,))
                    rows = c.fetchall()
                    if not rows:
                        flash("No pending uninvoiced shipments for this customer.", "error")
                    else:
                        tt = sum(safe_float(r.get("taxable_amount")) for r in rows)
                        cg = sum(safe_float(r.get("cgst")) for r in rows)
                        sg = sum(safe_float(r.get("sgst")) for r in rows)
                        ig = sum(safe_float(r.get("igst")) for r in rows)
                        tot = sum(safe_float(r.get("total_amount")) for r in rows)
                        inv_no = get_seq("invoice", "INV/", 5)
                        c.execute("INSERT INTO invoices(invoice_no, invoice_date, customer_id, taxable_amount, cgst, sgst, igst, total, status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'UNPAID')", (inv_no, date_today, cid, tt, cg, sg, ig, tot))
                        iid = c.lastrowid
                        for r in rows:
                            c.execute("INSERT INTO invoice_lines(invoice_id, description, shipment_id, taxable_amount, cgst, sgst, igst, total) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (iid, f"AWB {r['awb_no']}", r['id'], safe_float(r['taxable_amount']), safe_float(r['cgst']), safe_float(r['sgst']), safe_float(r['igst']), safe_float(r['total_amount'])))
                        c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (cid, date_today, inv_no, tot, f"Auto Invoice: {inv_no}"))
                        flash(f"✅ Invoice {inv_no} Generated! Total: ₹{tot:,.2f}", "success")
            
            # 💰 RECORD PAYMENT AGAINST INVOICE
            elif action == 'record_payment':
                inv_id = request.form.get('inv_id')
                amt = safe_float(request.form.get('pay_amount'))
                mode = request.form.get('pay_mode', 'CASH')
                ref = request.form.get('pay_ref', '')
                if amt > 0 and inv_id:
                    c.execute("SELECT * FROM invoices WHERE id=%s", (inv_id,))
                    inv = c.fetchone()
                    if inv:
                        c.execute("INSERT INTO payments(customer_id, invoice_id, payment_date, amount, mode, reference) VALUES(%s,%s,%s,%s,%s,%s)", (inv['customer_id'], inv_id, date_today, amt, mode, ref))
                        c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'PAYMENT',%s,0,%s,%s)", (inv['customer_id'], date_today, inv['invoice_no'], amt, f"{mode} Payment against {inv['invoice_no']}"))
                        c.execute("SELECT COALESCE(SUM(amount),0) as paid FROM payments WHERE invoice_id=%s", (inv_id,))
                        paid_total = c.fetchone()['paid']
                        if paid_total >= safe_float(inv['total']):
                            c.execute("UPDATE invoices SET status='PAID' WHERE id=%s", (inv_id,))
                            flash(f"✅ Invoice {inv['invoice_no']} fully PAID! ₹{amt:,.2f} received.", "success")
                        else:
                            c.execute("UPDATE invoices SET status='PARTLY_PAID' WHERE id=%s", (inv_id,))
                            flash(f"✅ Partial payment ₹{amt:,.2f} recorded. Remaining: ₹{safe_float(inv['total']) - paid_total:,.2f}", "success")
            
            # ✏️ UPDATE STATUS
            elif action == 'edit_status':
                iid = request.form.get('inv_id')
                new_status = request.form.get('status')
                c.execute("UPDATE invoices SET status=%s WHERE id=%s", (new_status, iid))
                flash(f"Invoice status updated to {new_status}.", "success")
            
            # 🗑️ DELETE INVOICE & ROLLBACK
            elif action == 'delete':
                iid = request.form.get('del_id')
                c.execute("SELECT invoice_no, customer_id, total FROM invoices WHERE id=%s", (iid,))
                inv = c.fetchone()
                if inv:
                    c.execute("DELETE FROM ledger WHERE voucher_type='INVOICE' AND reference=%s", (inv['invoice_no'],))
                    c.execute("DELETE FROM payments WHERE invoice_id=%s", (iid,))
                    c.execute("DELETE FROM invoice_lines WHERE invoice_id=%s", (iid,))
                    c.execute("DELETE FROM invoices WHERE id=%s", (iid,))
                    flash(f"🗑️ Invoice {inv['invoice_no']} deleted & Ledger reversed.", "success")
        conn.commit()
        return redirect('/invoices')
    
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name")
        custs = c.fetchall()
        c.execute("""SELECT i.*, c.name as cust_name,
            COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id=i.id), 0) as paid_amount
            FROM invoices i LEFT JOIN customers c ON i.customer_id=c.id ORDER BY i.id DESC LIMIT 300""")
        inv_list = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top:4px solid #f59e0b;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">⚡ Auto-Invoice Generation</h3>
        <form method="POST" class="flex gap-4 items-end" onsubmit="return confirm('Generate Invoice?');">
            <input type="hidden" name="action" value="generate">
            <div class="flex-1"><label class="label-modern">Select Customer *</label>
                <select name="cust_id" class="input-modern" required>
                    <option value="">-- Choose Customer --</option>
                    {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
                </select>
            </div>
            <button type="submit" class="btn-warning"><i class="fas fa-bolt"></i> GENERATE INVOICE</button>
        </form>
    </div>
    <div class="card mt-4">
        <h3 class="text-lg font-bold text-slate-800 mb-4">📋 Invoice Register</h3>
        <table class="datatable">
            <thead><tr><th>Inv No</th><th>Date</th><th>Customer</th><th>Taxable</th><th>GST</th><th>Total</th><th>Paid</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
            {% for i in inv_list %}
            <tr>
                <td class="font-bold text-red-600">{{ i.invoice_no }}</td>
                <td>{{ i.invoice_date }}</td>
                <td class="font-bold text-blue-600">{{ i.cust_name }}</td>
                <td>₹{{ i.taxable_amount }}</td>
                <td>₹{{ i.cgst + i.sgst + i.igst }}</td>
                <td class="font-bold">₹{{ i.total }}</td>
                <td class="text-green-600 font-bold">₹{{ i.paid_amount }}</td>
                <td><span class="px-2 py-1 rounded-full text-xs font-bold {% if i.status=='PAID' %}bg-green-100 text-green-700{% elif i.status=='PARTLY_PAID' %}bg-amber-100 text-amber-700{% else %}bg-red-100 text-red-700{% endif %}">{{ i.status }}</span></td>
                <td style="white-space:nowrap;">
                    <a href="/print/invoice/{{ i.id }}" target="_blank" class="btn-primary" style="padding:3px 8px; font-size:11px;"><i class="fas fa-print"></i></a>
                    {% if i.status != 'PAID' %}
                    <button onclick="openPayModal('{{ i.id }}', '{{ i.invoice_no }}', '{{ i.total - i.paid_amount }}')" class="btn-success" style="padding:3px 8px; font-size:11px;"><i class="fas fa-rupee-sign"></i></button>
                    {% endif %}
                    <form method="POST" style="display:inline;" onsubmit="return confirm('#⚠ Delete invoice & reverse ledger?');">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="del_id" value="{{ i.id }}">
                        <button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-trash"></i></button>
                    </form>
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    
    <!-- MODAL: RECORD PAYMENT -->
    <div id="payModal" class="modal">
        <div class="modal-content">
            <h3 class="text-lg font-bold text-slate-800 mb-4">💰 Record Payment</h3>
            <p class="text-sm text-slate-500 mb-3">Invoice: <b id="pay_inv_no"></b> | Remaining: <b id="pay_remaining" class="text-red-600"></b></p>
            <form method="POST" class="space-y-3">
                <input type="hidden" name="action" value="record_payment">
                <input type="hidden" name="inv_id" id="pay_inv_id">
                <div><label class="label-modern">Payment Amount (₹) *</label><input type="number" step="0.01" name="pay_amount" id="pay_amount" class="input-modern font-bold" required></div>
                <div><label class="label-modern">Payment Mode</label>
                    <select name="pay_mode" class="input-modern">
                        <option value="CASH">CASH</option>
                        <option value="BANK">BANK TRANSFER</option>
                        <option value="UPI">UPI / GPay</option>
                        <option value="CHEQUE">CHEQUE</option>
                    </select>
                </div>
                <div><label class="label-modern">Reference / UTR</label><input type="text" name="pay_ref" class="input-modern" placeholder="Optional"></div>
                <div class="flex gap-3 mt-4">
                    <button type="button" class="btn-danger flex-1" onclick="document.getElementById('payModal').style.display='none'">Cancel</button>
                    <button type="submit" class="btn-success flex-1"><i class="fas fa-check"></i> Record Payment</button>
                </div>
            </form>
        </div>
    </div>
    <script>
    function openPayModal(id, invNo, remaining) {
        document.getElementById('pay_inv_id').value = id;
        document.getElementById('pay_inv_no').innerText = invNo;
        document.getElementById('pay_remaining').innerText = '₹' + parseFloat(remaining).toLocaleString('en-IN');
        document.getElementById('pay_amount').value = remaining;
        document.getElementById('payModal').style.display = 'block';
    }
    </script>
    """
    return render_page("Account Bill Section", render_template_string(html, custs=custs, inv_list=inv_list, date_today=date_today))

# ==========================================
# 📒 4.6 PARTY LEDGER (ADMIN ACCESS — FIXED)
# ==========================================
@app.route('/party_ledger', methods=['GET'])
@login_required
def party_ledger():
    if session.get('role') == 'CUSTOMER':
        return redirect('/my_ledger')
    conn = get_db()
    cid = request.args.get('cust_id')
    f_date = request.args.get('from_date', datetime.datetime.now().replace(day=1).strftime('%Y-%m-%d'))
    t_date = request.args.get('to_date', datetime.datetime.now().strftime('%Y-%m-%d'))
    l_data = []; c_bal = 0.0; customer_name = ""
    
    if cid:
        with conn.cursor() as c:
            c.execute("SELECT name FROM customers WHERE id=%s", (cid,))
            cst = c.fetchone()
            if cst: customer_name = cst['name']
            c.execute("""SELECT entry_date, voucher_type, reference, debit, credit, narration
                FROM ledger WHERE customer_id=%s AND entry_date BETWEEN %s AND %s
                ORDER BY entry_date ASC, id ASC""", (cid, f_date, t_date))
            l_data = c.fetchall()
            c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (cid,))
            r = c.fetchone()
            c_bal = safe_float(r['b']) if r else 0.0
    
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name")
        custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="background:#f8fafc;">
        <form method="GET" class="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <div class="md:col-span-2"><label class="label-modern">Select Customer *</label>
                <select name="cust_id" class="input-modern" required onchange="this.form.submit()">
                    <option value="">-- Type to Search --</option>
                    {% for c in custs %}<option value="{{ c.id }}" {% if c.id|string == cid %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
                </select>
            </div>
            <div><label class="label-modern">From Date</label><input type="date" name="from_date" value="{{ f_date }}" class="input-modern"></div>
            <div><label class="label-modern">To Date</label><input type="date" name="to_date" value="{{ t_date }}" class="input-modern"></div>
            <div class="flex gap-2">
                <button type="submit" class="btn-primary"><i class="fas fa-search"></i> Load</button>
                {% if cid %}<button type="button" class="btn-warning" onclick="window.print()"><i class="fas fa-print"></i></button>{% endif %}
            </div>
        </form>
    </div>
    {% if cid %}
    <div class="card mt-4">
        <div class="flex justify-between items-center mb-4">
            <h3 class="text-lg font-bold text-slate-800">📒 Statement: <span class="text-blue-600">{{ customer_name }}</span></h3>
            <div class="px-4 py-2 rounded-lg font-bold text-lg {% if c_bal > 0 %}bg-red-50 text-red-700{% else %}bg-green-50 text-green-700{% endif %}">
                Net Outstanding: ₹ {{ "{:,.2f}".format(c_bal) }}
            </div>
        </div>
        <table class="datatable">
            <thead><tr><th>Date</th><th>Voucher</th><th>Reference</th><th>Narration</th><th>Debit (₹)</th><th>Credit (₹)</th></tr></thead>
            <tbody>
            {% for l in l_data %}
            <tr>
                <td>{{ l.entry_date }}</td>
                <td><span class="px-2 py-1 rounded-full text-xs font-bold {% if l.voucher_type == 'INVOICE' %}bg-purple-100 text-purple-700{% else %}bg-green-100 text-green-700{% endif %}">{{ l.voucher_type }}</span></td>
                <td class="font-bold">{{ l.reference }}</td>
                <td>{{ l.narration }}</td>
                <td class="text-red-600 font-bold">{% if l.debit > 0 %}₹{{ l.debit }}{% else %}-{% endif %}</td>
                <td class="text-green-600 font-bold">{% if l.credit > 0 %}₹{{ l.credit }}{% else %}-{% endif %}</td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
    </div>
    {% else %}
    <div class="card mt-4 text-center py-12 text-slate-400">
        <i class="fas fa-user-circle text-5xl mb-4"></i>
        <h4 class="text-lg font-semibold">Select a customer to view their Ledger Statement.</h4>
    </div>
    {% endif %}
    """
    return render_page("Party Account Ledger", render_template_string(html, custs=custs, cid=cid, l_data=l_data, c_bal=c_bal, f_date=f_date, t_date=t_date, customer_name=customer_name))

# ==========================================
# 📊 4.7 REPORTS HUB (Central Reports Page)
# ==========================================
@app.route('/reports')
@login_required
def reports():
    html = """
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/cash_billing_register'">
            <i class="fas fa-money-bill-wave text-3xl text-green-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Cash Billing Register</h4>
            <p class="text-sm text-slate-500">All cash bookings with date filter</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/credit_billing'">
            <i class="fas fa-handshake text-3xl text-blue-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Credit Billing Register</h4>
            <p class="text-sm text-slate-500">Corporate customer billing data</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/outward_register'">
            <i class="fas fa-truck-loading text-3xl text-purple-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Outward Register</h4>
            <p class="text-sm text-slate-500">All outward entries with manifest</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/cargo_inward'">
            <i class="fas fa-boxes text-3xl text-amber-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Inward Register</h4>
            <p class="text-sm text-slate-500">All inward cargo entries</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/invoice_data'">
            <i class="fas fa-file-invoice text-3xl text-indigo-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Invoice Data</h4>
            <p class="text-sm text-slate-500">All generated invoices</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/bill_pending'">
            <i class="fas fa-exclamation-triangle text-3xl text-red-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Bill Pending</h4>
            <p class="text-sm text-slate-500">Unpaid invoices list</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/drs_status'">
            <i class="fas fa-motorcycle text-3xl text-teal-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">DRS Status</h4>
            <p class="text-sm text-slate-500">Delivery run sheet tracking</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/manifest_register'">
            <i class="fas fa-clipboard-list text-3xl text-cyan-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Manifest Register</h4>
            <p class="text-sm text-slate-500">All manifests with route info</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/main_reports/inward_outward_pending'">
            <i class="fas fa-clock text-3xl text-orange-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Inward-Outward Pending</h4>
            <p class="text-sm text-slate-500">Parcels stuck in transit</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/audit_reports/daily_collection'">
            <i class="fas fa-coins text-3xl text-yellow-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Daily Collection</h4>
            <p class="text-sm text-slate-500">Payment collection report</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/module/audit_reports/counter_booking'">
            <i class="fas fa-file-invoice-dollar text-3xl text-lime-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Counter Booking Analysis</h4>
            <p class="text-sm text-slate-500">Booking volume analysis</p>
        </div>
        <div class="card p-5 hover:shadow-lg transition cursor-pointer" onclick="location.href='/party_ledger'">
            <i class="fas fa-balance-scale text-3xl text-pink-500 mb-3"></i>
            <h4 class="font-bold text-slate-800">Party Ledger</h4>
            <p class="text-sm text-slate-500">Customer account statement</p>
        </div>
    </div>
    """
    return render_page("Reports Hub", render_template_string(html))

# ==========================================
# 🖨️ PRINT LABEL PDF (BULLETPROOF & CRASH-FREE)
# ==========================================
@app.route('/print/label/<awb>')
@login_required
def print_label(awb):
    try:
        conn = get_db()
        with conn.cursor() as c:
            c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
            s = c.fetchone()
            if not s: return "Shipment not found", 404
            
            cust = {}
            if s.get('customer_id'):
                c.execute("SELECT * FROM customers WHERE id=%s", (s['customer_id'],))
                cust = c.fetchone() or {}
            
            c.execute("SELECT origin_station, out_station FROM outward_register WHERE awb_no=%s ORDER BY id DESC LIMIT 1", (awb,))
            outward = c.fetchone() or {}
            
            # 🚀 THE BUG FIX: Smart Column Detector for Settings Table
            c.execute("SELECT * FROM settings")
            settings = {}
            for r in c.fetchall():
                k = r.get('key') if 'key' in r else r.get('name')
                if k:
                    settings[k] = r.get('value')
                    
        conn.close()
    except Exception as e:
        return f"Database Error: {str(e)}", 500

    try:
        import io
        from flask import send_file
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import inch
        from reportlab.graphics.barcode import code128

        def hex_rgb(h):
            h = h.lstrip("#")
            return tuple(int(h[i:i+2], 16)/255.0 for i in (0, 2, 4))
            
        def fit_text(cv, text, font, size, max_width):
            text = str(text or "")
            if cv.stringWidth(text, font, size) <= max_width: return text
            while text and cv.stringWidth(text + "...", font, size) > max_width: text = text[:-1]
            return text + "..."

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

        # 🚀 SAFE VARIABLE EXTRACTION (Prevents NoneType Crash)
        _org = outward.get('origin_station') or "NOHAR"
        _dst = outward.get('out_station') or s.get('dest_station') or s.get('dest_name') or "-"
        
        stype = s.get("service_type") or "SURFACE"
        if stype in ["BOOKED", "OUTWARD", "INWARD", "ON_DRS", "DELIVERED"]: 
            stype = "SURFACE"

        buf = io.BytesIO()
        w, h = 4 * inch, 6 * inch
        cv = canvas.Canvas(buf, pagesize=(w, h))
        
        # Background & Borders
        cv.setFillColorRGB(1, 1, 1); cv.rect(0, 0, w, h, fill=1, stroke=0)
        cv.setStrokeColorRGB(*hex_rgb("#E3E6EA")); cv.setLineWidth(1.2); cv.rect(8, 8, w - 16, h - 16)
        
        # Header Box
        x = 14
        max_w = w - 115
        cv.setFillColorRGB(*hex_rgb("#23272F")); cv.setFont("Helvetica-Bold", 11)
        cv.drawString(x, h - 26, fit_text(cv, settings.get("company_name") or "AGC Courier", "Helvetica-Bold", 11, max_w))
        cv.setFillColorRGB(*hex_rgb("#6B7280")); cv.setFont("Helvetica", 6.2)
        cv.drawString(x, h - 38, fit_text(cv, settings.get("company_address") or "", "Helvetica", 6.2, max_w))
        cv.drawString(x, h - 50, fit_text(cv, f"GSTIN: {settings.get('company_gstin') or ''} | Ph: {settings.get('company_phone') or ''}", "Helvetica", 6.2, max_w))
        
        # Premium Express Box
        cv.setStrokeColorRGB(*hex_rgb("#B08A47")); cv.setLineWidth(1.2); cv.rect(w - 90, h - 42, 80, 16)
        cv.setFillColorRGB(*hex_rgb("#B08A47")); cv.setFont("Helvetica-Bold", 6.5)
        cv.drawCentredString(w - 50, h - 37, "PREMIUM EXPRESS")
        cv.setStrokeColorRGB(*hex_rgb("#B08A47")); cv.setLineWidth(1.5); cv.line(10, h - 62, w - 10, h - 62)
        
        # AWB & Barcode
        safe_awb = str(s.get("awb_no") or "")
        cv.setFillColorRGB(*hex_rgb("#6B7280")); cv.setFont("Helvetica-Bold", 6.5); cv.drawString(14, h - 74, "AWB NUMBER")
        cv.setFillColorRGB(*hex_rgb("#23272F")); cv.setFont("Helvetica-Bold", 19); cv.drawString(14, h - 90, safe_awb)
        try:
            code128.Code128(safe_awb, barHeight=0.40*inch, barWidth=0.011*inch).drawOn(cv, 18, h - 128)
        except: pass
        cv.setFillColorRGB(*hex_rgb("#23272F")); cv.setFont("Courier-Bold", 9); cv.drawString(18, h - 140, safe_awb)
        
        # Origin / Service / Destination Box
        cv.setFillColorRGB(*hex_rgb("#F7F8FA")); cv.setStrokeColorRGB(*hex_rgb("#E3E6EA"))
        cv.rect(12, h - 180, w - 24, 38, fill=1, stroke=1)
        cv.setFillColorRGB(*hex_rgb("#6B7280")); cv.setFont("Helvetica-Bold", 6)
        cv.drawString(20, h - 158, "ORIGIN"); cv.drawCentredString(w / 2, h - 158, "SERVICE"); cv.drawRightString(w - 20, h - 158, "DESTINATION")
        
        cv.setFillColorRGB(*hex_rgb("#23272F")); cv.setFont("Helvetica-Bold", 11)
        cv.drawString(20, h - 172, fit_text(cv, str(_org).upper(), "Helvetica-Bold", 11, 75))
        cv.drawRightString(w - 20, h - 170, fit_text(cv, str(_dst).upper(), "Helvetica-Bold", 11, 75))
        
        cv.setStrokeColorRGB(*hex_rgb("#0E8A6D")); cv.setLineWidth(1.2); cv.rect(w / 2 - 40, h - 174, 80, 16)
        cv.setFillColorRGB(*hex_rgb("#0E8A6D")); cv.setFont("Helvetica-Bold", 7.5); cv.drawCentredString(w / 2, h - 169, str(stype))
        
        # Consignee Details
        cv.setFillColorRGB(1, 1, 1); cv.setStrokeColorRGB(*hex_rgb("#E3E6EA")); cv.rect(12, h - 254, w - 24, 70, fill=1, stroke=1)
        cv.setFillColorRGB(*hex_rgb("#0E8A6D")); cv.rect(12, h - 254, 4, 70, fill=1, stroke=0)
        cv.setFont("Helvetica-Bold", 6.5); cv.drawString(22, h - 194, "DELIVER TO")
        cv.setFillColorRGB(*hex_rgb("#23272F")); cv.setFont("Helvetica-Bold", 10)
        
        yy = h - 206
        for line in wrap_lines(cv, s.get("dest_name") or "", "Helvetica-Bold", 10, w - 50)[:2]:
            cv.drawString(22, yy, line); yy -= 12
        cv.setFont("Helvetica", 7.5)
        for line in wrap_lines(cv, s.get("dest_address") or "", "Helvetica", 7.5, w - 50)[:2]:
            cv.drawString(22, yy, line); yy -= 10
        cv.setFont("Helvetica-Bold", 7.5); cv.drawString(22, yy, f"Ph: {s.get('dest_phone') or '-'}")
        
        # Metrics Grid
        cells = [
            ("WEIGHT", f"{s.get('weight_kg') or '0'} KG"), 
            ("PIECES", str(s.get("quantity") or "1")), 
            ("COD", f"Rs {s.get('cod_amount') or 0}"),
            ("DECLARED", f"Rs {s.get('declared_value') or 0}"), 
            ("DATE", str(s.get("booking_date") or "")[:10]), 
            ("MODE", str(stype)),
            ("DEST CITY", str(_dst)[:14]), 
            ("BRANCH", str(settings.get("branch_name") or "HQ"))
        ]
        
        cw = (w - 24) / 4; chh = 19; y0 = h - 258
        for i, (label, value) in enumerate(cells):
            col, row = i % 4, i // 4
            cx = 12 + col * cw; cy = y0 - (row + 1) * chh
            cv.setFillColorRGB(*hex_rgb("#F7F8FA" if row % 2 == 0 else "#FFFFFF")); cv.setStrokeColorRGB(*hex_rgb("#E3E6EA"))
            cv.rect(cx, cy, cw, chh, fill=1, stroke=1)
            cv.setFillColorRGB(*hex_rgb("#6B7280")); cv.setFont("Helvetica-Bold", 5.6); cv.drawString(cx + 4, cy + chh - 7, label)
            cv.setFillColorRGB(*hex_rgb("#23272F")); cv.setFont("Helvetica-Bold", 8); cv.drawString(cx + 4, cy + 4, str(value))
            
        # Shipper Footer
        st = y0 - 2 * chh - 6
        cv.setFillColorRGB(1, 1, 1); cv.setStrokeColorRGB(*hex_rgb("#E3E6EA")); cv.rect(12, st - 40, w - 24, 40, fill=1, stroke=1)
        cv.setFillColorRGB(*hex_rgb("#B08A47")); cv.setFont("Helvetica-Bold", 6.5); cv.drawString(20, st - 10, "SHIPPER")
        cv.setFillColorRGB(*hex_rgb("#23272F")); cv.setFont("Helvetica", 6.8)
        yy = st - 20
        
        # Safe Shipper Formatting
        shipper_name = cust.get('name') or s.get('origin_name') or ""
        shipper_addr = cust.get('address') or ""
        if str(shipper_addr).lower() == 'none': shipper_addr = ''
        shipper_gst = cust.get('gstin') or "-"
        
        shipper_info = str(shipper_name)
        if shipper_addr: 
            shipper_info += f" | {shipper_addr}"
        shipper_info += f" | GSTIN: {shipper_gst}"
        
        for line in wrap_lines(cv, shipper_info, "Helvetica", 6.8, w - 44)[:2]:
            cv.drawString(20, yy, line); yy -= 9
            
        cv.setFillColorRGB(*hex_rgb("#F7F8FA")); cv.rect(10, 10, w - 20, 28, fill=1, stroke=0)
        cv.setFillColorRGB(*hex_rgb("#6B7280")); cv.setFont("Helvetica", 5.8)
        cv.drawCentredString(w / 2, 26, fit_text(cv, settings.get("terms_note") or "", "Helvetica", 5.8, w - 40))
        cv.drawCentredString(w / 2, 17, "Computer Generated Label | AGC ERP")
        
        cv.showPage(); cv.save()
        buf.seek(0)
        return send_file(buf, as_attachment=False, download_name=f"Label_{awb}.pdf", mimetype='application/pdf')
        
    except Exception as e:
        return f"PDF Generator Error: {str(e)}", 500

# ==========================================
# 🧾 5.2 BOOKING RECEIPT PDF PRINT (A5 LANDSCAPE DESIGN)
# ==========================================
@app.route('/print/receipt/<awb>')
@login_required
def print_receipt(awb):
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT s.*, c.name as cust_name, c.address as cust_address, c.gstin as cust_gstin
        FROM shipments s LEFT JOIN customers c ON s.customer_id=c.id
        WHERE s.awb_no=%s""", (awb.upper(),))
    s = c.fetchone()
    c.close(); conn.close()
    if not s: return "Shipment Not Found", 404

    buf = io.BytesIO()
    w, h = 595, 421 # A5 Landscape equivalent
    cv = canvas.Canvas(buf, pagesize=(w, h))

    # Header
    x = 30
    logo_path = 'logo.png'
    if os.path.exists(logo_path):
        try:
            cv.drawImage(ImageReader(logo_path), x, h - 60, width=90, height=45, preserveAspectRatio=True, mask='auto')
            x = 130
        except: pass

    cv.setFillColor(HexColor("#23272F")); cv.setFont("Helvetica-Bold", 13)
    cv.drawString(x, h - 35, str(get_setting('company_name', 'AGC COURIER')))
    cv.setFillColor(HexColor("#6B7280")); cv.setFont("Helvetica", 6.5)
    cv.drawString(x, h - 46, str(get_setting('company_address', ''))[:80])
    cv.drawString(x, h - 55, f"GSTIN: {get_setting('company_gstin', '')} | Ph: {get_setting('company_phone', '')}")

    # Title Box
    cv.setStrokeColor(HexColor("#B08A47")); cv.setLineWidth(1.5)
    cv.roundRect(w - 175, h - 52, 145, 30, 8, fill=0, stroke=1)
    cv.setFillColor(HexColor("#B08A47")); cv.setFont("Helvetica-Bold", 11)
    cv.drawCentredString(w - 102, h - 41, "COURIER SLIP / RECEIPT")
    cv.setFillColor(HexColor("#6B7280")); cv.setFont("Helvetica", 7)
    cv.drawRightString(w - 30, h - 62, f"Date: {s['booking_date']}")
    
    cv.setStrokeColor(HexColor("#B08A47")); cv.setLineWidth(1.5); cv.line(20, h - 70, w - 20, h - 70)

    # AWB Info
    cv.setFillColor(HexColor("#23272F")); cv.setFont("Helvetica-Bold", 16)
    cv.drawString(30, h - 90, s["awb_no"])
    try:
        barcode = code128.Code128(str(s['awb_no']), barHeight=21.6, barWidth=0.8)
        barcode.drawOn(cv, 34, h - 125)
    except: pass
    cv.setFont("Courier-Bold", 8); cv.drawString(34, h - 135, s["awb_no"])

    try:
        if qrcode:
            qr_img = qrcode.make(f"AWB:{s['awb_no']}|WT:{s['weight_kg']}|COD:{s['cod_amount'] or 0}")
            qr_buf = io.BytesIO()
            qr_img.save(qr_buf, format='PNG')
            qr_buf.seek(0)
            cv.drawImage(ImageReader(qr_buf), w - 95, h - 135, width=60, height=60)
    except: pass

    # Shipper / Consignee boxes
    bw = (w - 70) / 2
    yb = h - 235
    cv.setStrokeColor(HexColor("#E3E6EA")); cv.setFillColor(HexColor("#F7F8FA"))
    cv.roundRect(30, yb, bw, 90, 6, fill=1, stroke=1)
    cv.roundRect(40 + bw, yb, bw, 90, 6, fill=1, stroke=1)
    
    cv.setFillColor(HexColor("#B08A47")); cv.setFont("Helvetica-Bold", 7)
    cv.drawString(38, yb + 80, "SHIPPER"); cv.drawString(48 + bw, yb + 80, "CONSIGNEE")
    cv.setFillColor(HexColor("#23272F")); cv.setFont("Helvetica", 7.5)
    
    # Shipper Details
    cname = str(s["cust_name"] or s["origin_name"] or "")
    caddr = str(s["cust_address"] or s["origin_address"] or "")
    cv.drawString(38, yb + 68, cname[:35])
    cv.drawString(38, yb + 59, caddr[:40])
    cv.drawString(38, yb + 50, caddr[40:80])
    cv.drawString(38, yb + 39, f"GSTIN: {s['cust_gstin'] or '-'}")

    # Consignee Details
    dname = str(s["dest_name"] or "")
    daddr = str(s["dest_address"] or "")
    cv.drawString(48 + bw, yb + 68, dname[:35])
    cv.drawString(48 + bw, yb + 59, daddr[:40])
    cv.drawString(48 + bw, yb + 50, daddr[40:80])
    cv.drawString(48 + bw, yb + 39, f"Ph: {s['dest_phone'] or '-'} | State: {s['dest_state_code'] or '-'}")

    # Summary Grid
    stype = str(s.get("service_type") or "SURFACE")
    gst_total = safe_float(s['cgst']) + safe_float(s['sgst']) + safe_float(s['igst'])
    vals = [
        ("WEIGHT", f"{s['weight_kg']} KG"), ("PIECES", s["quantity"]), ("SERVICE", stype),
        ("COD", f"Rs {s['cod_amount'] or 0}"), ("TAXABLE", f"{s['taxable_amount'] or 0}"),
        ("GST", f"{gst_total:.2f}"), ("TOTAL", f"Rs {s['total_amount'] or 0}")
    ]
    
    cw2 = (w - 60) / len(vals)
    yc = yb - 18
    for i, (lb, vl) in enumerate(vals):
        cx = 30 + i * cw2
        cv.setFillColor(HexColor("#EEF1F4")); cv.rect(cx, yc - 26, cw2 - 4, 26, fill=1, stroke=0)
        cv.setFillColor(HexColor("#6B7280")); cv.setFont("Helvetica-Bold", 5.5); cv.drawString(cx + 4, yc - 8, lb)
        cv.setFillColor(HexColor("#23272F")); cv.setFont("Helvetica-Bold", 8); cv.drawString(cx + 4, yc - 19, str(vl))

    cv.setFont("Helvetica", 6.5); cv.setFillColor(HexColor("#6B7280"))
    cv.drawString(30, yc - 38, f"Grand Total: Rs {s['total_amount']}")
    
    cv.line(w - 170, yc - 30, w - 30, yc - 30)
    cv.drawString(w - 170, yc - 40, "For " + str(get_setting('company_name', 'AGC')))
    
    cv.setFont("Helvetica", 6)
    cv.drawString(30, 20, str(get_setting('terms_note', 'Liability limited to declared value.'))[:100])
    cv.drawRightString(w - 30, 20, str(get_setting('company_website', '')))
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Receipt_{s['awb_no']}.pdf", mimetype='application/pdf')

# ==========================================
# 📊 5.3 ACCOUNT STATEMENT PDF PRINT (WITH LOGO)
# ==========================================
@app.route('/print/statement/<int:cid>')
@login_required
def print_statement(cid):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM customers WHERE id=%s", (cid,))
    cust = c.fetchone()
    if not cust: return "Customer Not Found", 404
    c.execute("""SELECT entry_date, voucher_type, reference, debit, credit, narration 
        FROM ledger WHERE customer_id=%s ORDER BY entry_date ASC, id ASC""", (cid,))
    l_data = c.fetchall()
    c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (cid,))
    r = c.fetchone()
    c_bal = safe_float(r['b']) if r else 0.0
    c.close(); conn.close()
    
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    
    # Header
    cv.setFillColor(HexColor("#116B7A"))
    cv.rect(0, 780, 600, 60, fill=1, stroke=0)
    
    # ✅ LOGO INTEGRATION
    logo_path = 'logo.png'
    if os.path.exists(logo_path):
        try:
            cv.drawImage(ImageReader(logo_path), 20, 788, width=45, height=45, mask='auto')
        except Exception as e:
            logging.error(f"Logo draw error: {e}")
    
    cv.setFillColor(HexColor("#FFFFFF"))
    cv.setFont("Helvetica-Bold", 16)
    cv.drawCentredString(300, 815, str(get_setting('company_name', 'AGC COURIER')))
    cv.setFont("Helvetica", 9)
    cv.drawCentredString(300, 795, f"{get_setting('company_address', '')} | GSTIN: {get_setting('company_gstin', '')}")
    
    # Title
    cv.setFillColor(HexColor("#D67A00"))
    cv.setFont("Helvetica-Bold", 14)
    cv.drawCentredString(300, 755, "CUSTOMER ACCOUNT STATEMENT")
    
    # Customer Info
    y = 730
    cv.setFillColor(HexColor("#000000"))
    cv.setFont("Helvetica-Bold", 11)
    cv.drawString(40, y, f"Customer: {cust['name']}")
    cv.setFont("Helvetica", 10)
    cv.drawString(40, y-18, f"A/c Code: {cust['code']} | Phone: {cust['phone'] or 'N/A'} | GSTIN: {cust['gstin'] or 'N/A'}")
    cv.drawString(40, y-33, f"Address: {cust['address'] or 'N/A'}")
    
    # Balance Box
    cv.setFillColor(HexColor("#FEE2E2") if c_bal > 0 else HexColor("#D1FAE5"))
    cv.rect(400, y-40, 160, 45, fill=1, stroke=1)
    cv.setFillColor(HexColor("#DC2626") if c_bal > 0 else HexColor("#059669"))
    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(410, y-15, "NET OUTSTANDING")
    cv.setFont("Helvetica-Bold", 14)
    cv.drawString(410, y-32, f"Rs {c_bal:,.2f}")
    
    # Table Header
    y -= 70
    cv.setFillColor(HexColor("#116B7A"))
    cv.rect(40, y-5, 520, 25, fill=1, stroke=0)
    cv.setFillColor(HexColor("#FFFFFF"))
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(45, y+3, "Date")
    cv.drawString(100, y+3, "Voucher")
    cv.drawString(170, y+3, "Reference")
    cv.drawString(280, y+3, "Narration")
    cv.drawString(390, y+3, "Debit")
    cv.drawString(460, y+3, "Credit")
    cv.drawString(520, y+3, "Balance")
    
    # Table Rows
    running_balance = 0.0
    y -= 25
    cv.setFont("Helvetica", 8)
    for l in l_data:
        if y < 60:
            cv.showPage()
            y = 780
            cv.setFont("Helvetica", 8)
        running_balance += safe_float(l['debit']) - safe_float(l['credit'])
        cv.setFillColor(HexColor("#000000"))
        cv.drawString(45, y, str(l['entry_date']))
        cv.drawString(100, y, l['voucher_type'][:8])
        cv.drawString(170, y, str(l['reference'])[:12])
        cv.drawString(280, y, str(l['narration'])[:18])
        if safe_float(l['debit']) > 0:
            cv.setFillColor(HexColor("#DC2626"))
            cv.drawString(390, y, f"{safe_float(l['debit']):,.2f}")
        if safe_float(l['credit']) > 0:
            cv.setFillColor(HexColor("#059669"))
            cv.drawString(460, y, f"{safe_float(l['credit']):,.2f}")
        cv.setFillColor(HexColor("#000000"))
        cv.drawString(520, y, f"{running_balance:,.2f}")
        cv.setStrokeColor(HexColor("#E2E8F0"))
        cv.line(40, y-5, 560, y-5)
        y -= 18
    
    # Footer
    cv.setFillColor(HexColor("#64748B"))
    cv.setFont("Helvetica", 8)
    cv.drawCentredString(300, 30, f"Generated on {datetime.datetime.now().strftime('%d-%b-%Y %H:%M')}")
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Statement_{cust['code']}.pdf", mimetype='application/pdf')

# ==========================================
# 🧾 5.4 TAX INVOICE PDF PRINT (WITH LOGO)
# ==========================================
@app.route('/print/invoice/<int:inv_id>')
@login_required
def print_invoice_pdf(inv_id):
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT i.*, c.name as cname, c.gstin as cgstin, c.address as caddr, c.state_code as cstate
        FROM invoices i JOIN customers c ON i.customer_id=c.id WHERE i.id=%s""", (inv_id,))
    inv = c.fetchone()
    c.execute("""SELECT il.*, s.awb_no FROM invoice_lines il
        LEFT JOIN shipments s ON il.shipment_id=s.id WHERE il.invoice_id=%s""", (inv_id,))
    lines = c.fetchall()
    c.close(); conn.close()
    if not inv: return "Invoice Not Found", 404
    
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    
    # Header
    cv.setFillColor(HexColor("#0F172A"))
    cv.rect(0, 780, 600, 62, fill=1, stroke=0)
    
    # ✅ LOGO INTEGRATION
    logo_path = 'logo.png'
    if os.path.exists(logo_path):
        try:
            # ✅ LOGO ASPECT RATIO FIX
            cv.drawImage(ImageReader(logo_path), 20, 788, width=45, height=45, preserveAspectRatio=True, mask='auto')
        except Exception as e:
            logging.error(f"Logo draw error: {e}")
    
    cv.setFillColor(HexColor("#FFFFFF"))
    cv.setFont("Helvetica-Bold", 18)
    cv.drawCentredString(300, 820, str(get_setting('company_name', 'AGC ERP')))
    cv.setFont("Helvetica", 9)
    cv.drawCentredString(300, 800, f"{get_setting('company_address', '')}")
    cv.drawCentredString(300, 788, f"GSTIN: {get_setting('company_gstin', '')} | Ph: {get_setting('company_phone', '')}")
    
    # Title
    cv.setFillColor(HexColor("#2563EB"))
    cv.setFont("Helvetica-Bold", 16)
    cv.drawCentredString(300, 760, "TAX INVOICE")
    
    # Invoice Meta
    cv.setFillColor(HexColor("#000000"))
    cv.setFont("Helvetica", 10)
    cv.drawString(40, 740, f"Invoice No: {inv['invoice_no']}")
    cv.drawRightString(560, 740, f"Date: {inv['invoice_date']}")
    
    # Bill To Box
    cv.setStrokeColor(HexColor("#CBD5E1"))
    cv.rect(40, 680, 520, 50)
    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(50, 718, "BILL TO:")
    cv.setFont("Helvetica", 10)
    cv.drawString(50, 705, f"{inv['cname']}")
    cv.drawString(50, 692, f"{inv['caddr'] or ''}")
    cv.drawString(350, 718, f"GSTIN: {inv['cgstin'] or 'N/A'}")
    cv.drawString(350, 705, f"State Code: {inv['cstate'] or 'N/A'}")
    
    # Table Header
    y = 660
    cv.setFillColor(HexColor("#F1F5F9"))
    cv.rect(40, y, 520, 22, fill=1, stroke=0)
    cv.setFillColor(HexColor("#000000"))
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(45, y+7, "AWB No")
    cv.drawString(110, y+7, "Description")
    cv.drawString(270, y+7, "Taxable")
    cv.drawString(340, y+7, "CGST")
    cv.drawString(395, y+7, "SGST")
    cv.drawString(450, y+7, "IGST")
    cv.drawString(505, y+7, "Total")
    
    # Table Rows
    y -= 20
    cv.setFont("Helvetica", 9)
    for l in lines:
        if y < 200:
            cv.showPage()
            y = 780
            cv.setFont("Helvetica", 9)
        cv.drawString(45, y, str(l['awb_no'] or '-'))
        cv.drawString(110, y, str(l['description'])[:28])
        cv.drawString(270, y, f"{safe_float(l['taxable_amount']):,.2f}")
        cv.drawString(340, y, f"{safe_float(l['cgst']):,.2f}")
        cv.drawString(395, y, f"{safe_float(l['sgst']):,.2f}")
        cv.drawString(450, y, f"{safe_float(l['igst']):,.2f}")
        cv.setFont("Helvetica-Bold", 9)
        cv.drawString(505, y, f"{safe_float(l['total']):,.2f}")
        cv.setFont("Helvetica", 9)
        cv.setStrokeColor(HexColor("#E2E8F0"))
        cv.line(40, y-5, 560, y-5)
        y -= 18
    
    # Totals Section
    y -= 20
    cv.line(280, y+10, 560, y+10)
    cv.setFont("Helvetica", 10)
    cv.drawString(300, y, "Total Taxable:")
    cv.drawRightString(550, y, f"Rs {safe_float(inv['taxable_amount']):,.2f}")
    y -= 18
    cv.drawString(300, y, "CGST:")
    cv.drawRightString(550, y, f"Rs {safe_float(inv['cgst']):,.2f}")
    y -= 18
    cv.drawString(300, y, "SGST:")
    cv.drawRightString(550, y, f"Rs {safe_float(inv['sgst']):,.2f}")
    y -= 18
    cv.drawString(300, y, "IGST:")
    cv.drawRightString(550, y, f"Rs {safe_float(inv['igst']):,.2f}")
    
    # Grand Total Box
    y -= 30
    cv.setFillColor(HexColor("#2563EB"))
    cv.rect(280, y-5, 280, 30, fill=1, stroke=0)
    cv.setFillColor(HexColor("#FFFFFF"))
    cv.setFont("Helvetica-Bold", 13)
    cv.drawString(290, y+5, "GRAND TOTAL:")
    cv.drawRightString(550, y+5, f"Rs {safe_float(inv['total']):,.2f}")
    
    # Bank Details & Terms
    cv.setFillColor(HexColor("#000000"))
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(40, 130, "BANK DETAILS:")
    cv.setFont("Helvetica", 9)
    cv.drawString(40, 115, str(get_setting('bank_details', '')))
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(40, 95, "TERMS & CONDITIONS:")
    cv.setFont("Helvetica", 8)
    cv.drawString(40, 80, str(get_setting('terms_note', ''))[:90])
    
    # Signature
    cv.setFont("Helvetica", 10)
    cv.drawString(430, 80, f"For {get_setting('company_name', 'AGC')}")
    cv.line(430, 75, 560, 75)
    cv.setFont("Helvetica", 8)
    cv.drawString(450, 60, "Authorised Signatory")
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Invoice_{inv['invoice_no'].replace('/', '_')}.pdf", mimetype='application/pdf')

# ==========================================
# 📥 5.5 BULK CSV IMPORT
# ==========================================
@app.route('/import_csv', methods=['GET', 'POST'])
@login_required
def import_csv():
    if session.get('role') not in ['ADMIN', 'ACCOUNTS']: return redirect('/')
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            flash("Invalid file! Please upload a .csv file.", "error")
            return redirect('/import_csv')
        try:
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            reader = csv.DictReader(stream)
            headers = {k.strip().lower(): k for k in reader.fieldnames if k}
            conn = get_db(); added = 0; skipped = 0
            with conn.cursor() as c:
                for row in reader:
                    awb = row.get(headers.get("awb", "AWB")) or row.get("AWB")
                    if not awb: continue
                    awb = str(awb).strip().upper()
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    if c.fetchone():
                        skipped += 1
                        continue
                    dest = row.get(headers.get("dest", "Dest")) or row.get("Dest Station", "UNKNOWN")
                    wt = row.get(headers.get("weight", "Weight")) or "1"
                    tot = row.get(headers.get("amount", "Amount")) or "0"
                    d = datetime.datetime.now().strftime("%Y-%m-%d")
                    c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest.upper(),))
                    c.execute("""INSERT INTO shipments(awb_no, dest_name, dest_station, weight_kg, total_amount, 
                        booking_date, status, current_location, service_type, origin_name)
                        VALUES(%s, %s, %s, %s, %s, %s, 'BOOKED', 'Origin', 'SURFACE', %s)""",
                        (awb, dest, dest.upper(), safe_float(wt), safe_float(tot), d, session.get('branch','HQ')))
                    added += 1
            conn.commit(); conn.close()
            flash(f"🎉 Import Complete! {added} New Parcels Booked. {skipped} Duplicates Skipped.", "success")
        except Exception as e:
            flash(f"Import Error: {e}", "error")
        return redirect('/import_csv')
    
    html = """
    <div class="card" style="max-width:600px; margin:0 auto; border-top:4px solid #16a34a;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">📥 Bulk CSV Import (Fast Booking)</h3>
        <div style="background:#f0fdf4; padding:15px; border-radius:8px; border:1px dashed #16a34a; margin-bottom:20px; font-size:13px;">
            <b>Required Column Headers in CSV:</b><br><br>
            • <b>AWB</b> - Consignment Number<br>
            • <b>Dest</b> - Destination Station<br>
            • <b>Weight</b> - Weight in KG<br>
            • <b>Amount</b> - Total Amount<br><br>
            <i style="color:#64748b;">💡 Tip: Save your Excel file as 'CSV (Comma delimited)' before uploading.</i>
        </div>
        <form method="POST" enctype="multipart/form-data" class="space-y-4">
            <div>
                <label class="label-modern">Select CSV File</label>
                <input type="file" name="file" accept=".csv" required class="input-modern" style="padding:12px;">
            </div>
            <button type="submit" class="btn-success w-full"><i class="fas fa-upload"></i> Start Import</button>
        </form>
    </div>
    """
    return render_page("Excel Import", render_template_string(html))

# ==========================================
# 📊 5.6 SMART DYNAMIC REPORTS ENGINE (60+ REPORTS) - FIXED
# ==========================================
@app.route('/module/<category>/<action>', methods=['GET', 'POST'])
@login_required
def dynamic_module(category, action):
    # ✅ FIX: Replaced empty string with underscore
    title_category = category.replace('_', ' ').upper()
    title_action = action.replace('_', ' ').upper()
    page_title = f"{title_action} [{title_category}]"
    f_date = request.args.get('from_date', datetime.datetime.now().strftime('%Y-%m-%d'))
    t_date = request.args.get('to_date', datetime.datetime.now().strftime('%Y-%m-%d'))
    data_found = False; table_headers = []; table_rows = []
    conn = get_db()
    
    with conn.cursor() as c:
        # ✅ FIX: SQL Injection fix - Using parameterized queries
        q_map = {
            'cash_billing_register': ("SELECT id, awb_no, booking_date, dest_name, weight_kg, total_amount FROM shipments WHERE customer_id IS NULL AND booking_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "AWB", "Date", "Dest", "Weight", "Total", "Actions"]),
            'credit_billing': ("SELECT s.id, s.awb_no, s.booking_date, c.name as customer, s.total_amount FROM shipments s JOIN customers c ON s.customer_id=c.id WHERE s.customer_id IS NOT NULL AND s.booking_date BETWEEN %s AND %s ORDER BY s.id DESC LIMIT 500", ["ID", "AWB", "Date", "Customer", "Amount", "Actions"]),
            'invoice_data': ("SELECT id, invoice_no, invoice_date, total, status FROM invoices WHERE invoice_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Invoice No", "Date", "Total", "Status", "Actions"]),
            'bill_pending': ("SELECT id, invoice_no, invoice_date, total, status FROM invoices WHERE status='UNPAID' AND invoice_date BETWEEN %s AND %s", ["ID", "Invoice No", "Date", "Amount", "Status", "Actions"]),
            'drs_status': ("SELECT id, drs_no, drs_date, rider_name, status FROM drs WHERE drs_date BETWEEN %s AND %s ORDER BY id DESC", ["ID", "DRS No", "Date", "Rider", "Status", "Actions"]),
            'cargo_inward': ("SELECT id, entry_date, awb_no, origin_station, in_station, weight FROM inward_register WHERE entry_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Date", "AWB", "Origin", "In-Station", "Weight", "Actions"]),
            'outward_register': ("SELECT id, entry_date, awb_no, out_station, destination, weight FROM outward_register WHERE entry_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Date", "AWB", "Out-Station", "Dest", "Weight", "Actions"]),
            'manifest_register': ("SELECT id, manifest_no, manifest_type, from_location, to_location, status, DATE(created_at) as created FROM manifests WHERE DATE(created_at) BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Manifest No", "Type", "Origin", "Dest", "Status", "Date", "Actions"]),
            'daily_collection': ("SELECT id, payment_date, mode, amount FROM payments WHERE payment_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Date", "Mode", "Amount", "Actions"]),
            'counter_booking': ("SELECT id, awb_no, booking_date, dest_name, total_amount FROM shipments WHERE booking_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "AWB", "Date", "Dest", "Amount", "Actions"]),
            'inward_outward_pending': ("SELECT id, awb_no, booking_date, status, current_location FROM shipments WHERE status IN ('BOOKED', 'OUTWARD', 'INWARD') AND booking_date BETWEEN %s AND %s LIMIT 500", ["ID", "AWB", "Date", "Status", "Location", "Actions"]),
            'cash_book': ("SELECT id, payment_date, mode, amount, reference FROM payments WHERE mode='CASH' AND payment_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Date", "Mode", "Amount", "Ref", "Actions"]),
            'bank_book': ("SELECT id, payment_date, mode, amount, reference FROM payments WHERE mode != 'CASH' AND payment_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Date", "Mode", "Amount", "Ref", "Actions"]),
            'journal_voucher': ("SELECT id, expense_date, category, amount, paid_to FROM expenses WHERE expense_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Date", "Category", "Amount", "Paid To", "Actions"]),
            'drs_register': ("SELECT id, drs_no, drs_date, rider_name, vehicle_no FROM drs WHERE drs_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "DRS No", "Date", "Rider", "Vehicle", "Actions"]),
            'pod_register': ("SELECT di.id, d.drs_no, s.awb_no, di.receiver_name, di.status FROM drs_items di JOIN drs d ON di.drs_id=d.id JOIN shipments s ON di.shipment_id=s.id WHERE d.drs_date BETWEEN %s AND %s ORDER BY di.id DESC LIMIT 500", ["ID", "DRS", "AWB", "Receiver", "Status", "Actions"]),
            'service_tax_ledger': ("SELECT id, entry_date, voucher_type, reference, debit, credit FROM ledger WHERE entry_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "Date", "Type", "Ref", "Debit", "Credit", "Actions"]),
            'charts': ("SELECT booking_date, COUNT(*) as cnt, SUM(total_amount) as amt FROM shipments WHERE booking_date BETWEEN %s AND %s GROUP BY booking_date ORDER BY booking_date", ["Date", "Count", "Amount", "Actions"]),
            'bulk_print': ("SELECT id, awb_no, booking_date, dest_station FROM shipments WHERE booking_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 500", ["ID", "AWB", "Date", "Dest", "Actions"]),
            'data_manager': ("SELECT id, awb_no, booking_date, status FROM shipments WHERE booking_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 200", ["ID", "AWB", "Date", "Status", "Actions"]),
            'franchisee_summary': ("SELECT id, name, code, credit_limit FROM customers WHERE is_active=1 ORDER BY name LIMIT 500", ["ID", "Name", "Code", "Limit", "Actions"]),
            'duplicate_cnote': ("SELECT awb_no, COUNT(*) as cnt FROM outward_register GROUP BY awb_no HAVING cnt > 1 LIMIT 500", ["AWB", "Count", "Actions"]),
        }
        
        # Fallback Query
        query_data = q_map.get(action, (
            "SELECT id, awb_no, booking_date, dest_name, status FROM shipments WHERE booking_date BETWEEN %s AND %s ORDER BY id DESC LIMIT 200",
            ["ID", "AWB", "Date", "Dest", "Status", "Actions"]
        ))
        
        try:
            # ✅ FIX: Parameterized query execution
            if '%s' in query_data[0]:
                c.execute(query_data[0], (f_date, t_date))
            else:
                c.execute(query_data[0])
            rows = c.fetchall()
            if rows:
                data_found = True
                table_headers = query_data[1]
                for r in rows:
                    row_vals = [str(v) if v is not None else '-' for v in r.values()]
                    act_html = ""
                    if 'awb_no' in r:
                        act_html = f"""<div style="display:flex; gap:3px;">
                            <a href="/edit_shipment/{r['id']}" class="btn-primary" style="padding:2px 6px; font-size:10px;">✏️</a>
                            <a href="/print/label/{r['awb_no']}" target="_blank" class="btn-warning" style="padding:2px 6px; font-size:10px;">🏷️</a>
                            <a href="/print/receipt/{r['awb_no']}" target="_blank" class="btn-success" style="padding:2px 6px; font-size:10px;">🧾</a>
                        </div>"""
                    elif 'invoice_no' in r:
                        act_html = f"""<div style="display:flex; gap:3px;">
                            <a href="/print/invoice/{r['id']}" target="_blank" class="btn-primary" style="padding:2px 6px; font-size:10px;">🖨️ Print</a>
                        </div>"""
                    elif 'drs_no' in r:
                        act_html = f'<a href="/drs" class="btn-primary" style="padding:2px 6px; font-size:10px;">👁️ View</a>'
                    else:
                        act_html = f'<button class="btn-primary" style="padding:2px 6px; font-size:10px;">👁️ View</button>'
                    row_vals.append(act_html)
                    table_rows.append(row_vals)
        except Exception as e:
            logging.error(f"Report Mapping Error: {e}")
            flash(f"Report Error: {e}", "error")
    conn.close()
    
    html = """
    <div class="card" style="background:#f8fafc; border-left:4px solid #2563eb;">
        <form method="GET" class="flex flex-wrap gap-3 items-end">
            <div><label class="label-modern">📅 From Date</label><input type="date" name="from_date" value="{{ f_date }}" class="input-modern" style="width:160px;"></div>
            <div><label class="label-modern">📅 To Date</label><input type="date" name="to_date" value="{{ t_date }}" class="input-modern" style="width:160px;"></div>
            <button type="submit" class="btn-primary"><i class="fas fa-filter"></i> Apply Filter</button>
            <button type="button" class="btn-warning" onclick="window.print()"><i class="fas fa-print"></i> Print Report</button>
            <button type="button" class="btn-success" onclick="exportCSV()"><i class="fas fa-file-csv"></i> Export CSV</button>
        </form>
    </div>
    <div class="card mt-4">
        <div class="flex justify-between items-center mb-3">
            <h3 class="text-lg font-bold text-slate-800">{{ title }}</h3>
            <span class="px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-bold">{{ rows|length }} Records</span>
        </div>
        {% if has_data %}
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr>{% for h in headers %}<th>{{ h }}</th>{% endfor %}</tr></thead>
                <tbody>{% for row in rows %}<tr>{% for cell in row %}<td>{{ cell | safe }}</td>{% endfor %}</tr>{% endfor %}</tbody>
            </table>
        </div>
        {% else %}
        <div class="text-center py-12">
            <i class="fas fa-folder-open text-5xl text-slate-300 mb-4"></i>
            <h4 class="text-lg font-semibold text-slate-600">No Data Found</h4>
            <p class="text-sm text-slate-400">Try changing the date range.</p>
        </div>
        {% endif %}
    </div>
    <script>
    function exportCSV() {
        let table = document.querySelector('.datatable');
        if(!table) { alert('No data to export!'); return; }
        let csv = [];
        let rows = table.querySelectorAll('tr');
        for(let row of rows) {
            let cols = row.querySelectorAll('td, th');
            let rowData = [];
            for(let col of cols) {
                let text = col.innerText.replace(/"/g, '""');
                rowData.push('"' + text + '"');
            }
            csv.push(rowData.join(','));
        }
        let csvContent = csv.join('\\n');
        let blob = new Blob([csvContent], {type: 'text/csv'});
        let url = window.URL.createObjectURL(blob);
        let a = document.createElement('a');
        a.href = url;
        a.download = '{{ title }}.csv';
        a.click();
        window.URL.revokeObjectURL(url);
    }
    </script>
    """
    return render_page(page_title, render_template_string(html, title=page_title, has_data=data_found, headers=table_headers, rows=table_rows, f_date=f_date, t_date=t_date))

# ==========================================
# 🔄 5.8 UNIVERSAL SYNC API FOR DESKTOP
# ==========================================
@app.route('/api/sync/download', methods=['GET', 'POST'])
@login_required
def sync_download():
    """
    Desktop App ko poora latest data (all tables & all columns)
    JSON format me securely bhejne ke liye.
    """
    # 🛡️ SECURITY FIX: Strictly block unauthorized roles (like CUSTOMER or DELIVERY) from downloading the database
    if session.get('role') not in ['ADMIN', 'OPS', 'ACCOUNTS']:
        return jsonify({"success": False, "error": "Unauthorized Access. Data sync is restricted to authorized personnel."}), 403

    conn = get_db()
    response_data = {}
    tables_to_sync = [
        'users', 'customers', 'rates', 'stations', 'expenses',
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
                    clean_rows = []
                    for row in rows:
                        clean_row = {}
                        for key, value in row.items():
                            # Security: Never transmit password hashes, even to the desktop app
                            if tbl == 'users' and key == 'password_hash':
                                continue
                            if isinstance(value, (datetime.date, datetime.datetime)):
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

@app.route('/api/sync/smart', methods=['POST'])
def sync_smart():
    """Receives local unsynced shipments, merges them securely, and returns cloud updates."""
    # 🛡️ SECURITY: Verify the desktop app using a secret token, not a database password.
    client_token = request.headers.get('X-Sync-Token')
    server_token = os.environ.get('SYNC_API_KEY', 'agc-super-secret-sync-key-2026')
    if client_token != server_token:
        return jsonify({"success": False, "error": "Unauthorized Sync API Access"}), 403

    payload = request.get_json()
    local_shipments = payload.get('shipments', [])
    
    conn = get_db()
    try:
        with conn.cursor() as c:
            cols = ["customer_id","booking_date","origin_name","origin_phone","origin_address","origin_state_code",
                    "dest_name","dest_phone","dest_address","dest_state_code","dest_station","weight_kg","quantity",
                    "cod_amount","declared_value","service_type","taxable_amount","tax_rate","cgst","sgst","igst",
                    "total_amount","status","current_location","info","updated_at"]
            
            RANK = {"STATIONERY":0,"BOOKED":1,"OUTWARD":2,"INWARD":3,"ON_DRS":4,"DELIVERED":5,"UNDELIVERED":5,"CANCELLED":6}

            def is_empty(v, col):
                return v is None or str(v).strip() == ""

            def merge_logic(pri, fb):
                m = {}
                pri_newer = True
                if pri.get('updated_at') and fb.get('updated_at'):
                    if str(fb['updated_at']) > str(pri['updated_at']):
                        pri_newer = False
                
                primary = pri if pri_newer else fb
                fallback = fb if pri_newer else pri

                for col in cols:
                    if col == "status": continue
                    m[col] = primary.get(col) if not is_empty(primary.get(col), col) else fallback.get(col)
                
                ra = RANK.get(str(pri.get("status") or "").upper(), 1)
                rb = RANK.get(str(fb.get("status") or "").upper(), 1)
                m["status"] = pri.get("status") if ra >= rb else fb.get("status")
                return m

            # 1. Merge Incoming Desktop Data to Cloud
            for lrow in local_shipments:
                c.execute("SELECT * FROM shipments WHERE awb_no=%s", (lrow['awb_no'],))
                crow = c.fetchone()
                if crow:
                    merged = merge_logic(lrow, crow)
                    sets = ", ".join([f"`{col}`=%s" for col in cols])
                    vals = [merged.get(col) for col in cols]
                    c.execute(f"UPDATE shipments SET {sets} WHERE awb_no=%s", tuple(vals + [lrow['awb_no']]))
                else:
                    placeholders = ", ".join(["%s"] * len(cols))
                    vals = [lrow.get(col) for col in cols]
                    c.execute(f"INSERT INTO shipments (awb_no, {', '.join(['`'+col+'`' for col in cols])}) VALUES (%s, {placeholders})", tuple([lrow['awb_no']] + vals))

            # 2. Fetch Latest Cloud Data to send back to Desktop
            c.execute(f"SELECT awb_no, {', '.join(['`'+col+'`' for col in cols])} FROM shipments ORDER BY id DESC LIMIT 500")
            cloud_latest = c.fetchall()
            
            # Serialize dates for JSON
            for r in cloud_latest:
                for k, v in r.items():
                    if isinstance(v, (datetime.date, datetime.datetime)): r[k] = str(v)

        conn.commit()
        return jsonify({"success": True, "cloud_shipments": cloud_latest})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        conn.close()

@app.route('/api/sync/force_upload', methods=['POST'])
def force_upload():
    """Receives master table dumps from desktop and rebuilds cloud dynamically."""
    client_token = request.headers.get('X-Sync-Token')
    server_token = os.environ.get('SYNC_API_KEY', 'agc-super-secret-sync-key-2026')
    if client_token != server_token: return jsonify({"success": False, "error": "Unauthorized"}), 403

    tables = request.get_json().get('tables', {})
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SET FOREIGN_KEY_CHECKS=0;")
            
            # 🚀 AUTO-HEAL: Koshish karenge ki missing columns add ho jayein
            try: c.execute("ALTER TABLE shipments ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
            except: pass
            try: c.execute("ALTER TABLE drs_items ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
            except: pass
            
            for tbl, rows in tables.items():
                # 🛡️ BULLETPROOF: Pehle check karega ki Cloud me actually kaunse columns hain
                try:
                    c.execute(f"SHOW COLUMNS FROM `{tbl}`")
                    valid_cols = [r['Field'] for r in c.fetchall()]
                except Exception:
                    continue # Agar table cloud me nahi hai toh skip karega
                    
                c.execute(f"TRUNCATE TABLE `{tbl}`")
                if rows:
                    raw_cols = list(rows[0].keys())
                    
                    # Sirf wahi columns insert karega jo Cloud me available hain (Crash-Proof Logic)
                    mapped_cols = []
                    for col in raw_cols:
                        if col == 'key' and 'key_name' in valid_cols:
                            mapped_cols.append(('key', 'key_name')) # Key mapping fix
                        elif col in valid_cols:
                            mapped_cols.append((col, col))
                            
                    if not mapped_cols:
                        continue
                        
                    cols_str = ", ".join([f"`{cloud_col}`" for local_col, cloud_col in mapped_cols])
                    placeholders = ", ".join(["%s"] * len(mapped_cols))
                    insert_query = f"INSERT INTO `{tbl}` ({cols_str}) VALUES ({placeholders})"
                    
                    bulk_data = []
                    for r in rows:
                        row_vals = [r.get(local_col) for local_col, cloud_col in mapped_cols]
                        bulk_data.append(tuple(row_vals))
                        
                    c.executemany(insert_query, bulk_data)
                    
            c.execute("SET FOREIGN_KEY_CHECKS=1;")
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        conn.close()

# ==========================================
# 🚚 3.9 PICKUP REQUEST SYSTEM (B2B & ADMIN)
# ==========================================
@app.route('/pickup', methods=['GET', 'POST'])
@login_required
def pickup():
    if session.get('role') != 'CUSTOMER': return redirect('/')
    conn = get_db()
    cid = session.get('customer_id')
    
    # Auto-Heal: Table create karega agar nahi hai toh
    with conn.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS pickup_requests (
            id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, request_date DATE, 
            ready_time VARCHAR(50), total_boxes INT, approx_weight DOUBLE, pickup_address TEXT, 
            status VARCHAR(50) DEFAULT 'PENDING', assigned_rider VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        
    if request.method == 'POST':
        d = request.form
        req_date = d.get('request_date')
        ready_time = d.get('ready_time')
        boxes = safe_int(d.get('boxes'))
        weight = safe_float(d.get('weight'))
        address = d.get('address')
        
        with conn.cursor() as c:
            c.execute("INSERT INTO pickup_requests (customer_id, request_date, ready_time, total_boxes, approx_weight, pickup_address) VALUES (%s, %s, %s, %s, %s, %s)", 
                      (cid, req_date, ready_time, boxes, weight, address))
        conn.commit()
        flash("✅ Pickup Request submitted successfully! Our team will assign a rider shortly.", "success")
        return redirect('/pickup')
        
    with conn.cursor() as c:
        c.execute("SELECT * FROM pickup_requests WHERE customer_id=%s ORDER BY id DESC LIMIT 50", (cid,))
        requests_list = c.fetchall()
        c.execute("SELECT address FROM customers WHERE id=%s", (cid,))
        cust_row = c.fetchone()
        cust_addr = cust_row['address'] if cust_row else ""
    conn.close()
    
    html = """
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card" style="border-top:4px solid #f59e0b;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">🚚 Schedule a Pickup</h3>
            <form method="POST" class="space-y-4">
                <div><label class="label-modern">Pickup Date *</label><input type="date" name="request_date" required class="input-modern"></div>
                <div><label class="label-modern">Parcels Ready By (Time) *</label><input type="time" name="ready_time" required class="input-modern"></div>
                <div class="grid grid-cols-2 gap-3">
                    <div><label class="label-modern">Total Boxes *</label><input type="number" name="boxes" value="1" min="1" required class="input-modern"></div>
                    <div><label class="label-modern">Approx Wt (KG) *</label><input type="number" step="0.1" name="weight" value="1.0" required class="input-modern"></div>
                </div>
                <div><label class="label-modern">Pickup Address *</label><textarea name="address" rows="3" required class="input-modern">{{ cust_addr }}</textarea></div>
                <button type="submit" class="btn-warning w-full"><i class="fas fa-truck"></i> Request Pickup Now</button>
            </form>
        </div>
        <div class="card lg:col-span-2">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📋 My Pickup History</h3>
            <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Req ID</th><th>Date & Time</th><th>Boxes / Wt</th><th>Address</th><th>Status</th><th>Rider Info</th></tr></thead>
                <tbody>
                {% for r in reqs %}
                <tr>
                    <td class="font-bold text-blue-600">PKP-{{ r.id }}</td>
                    <td>{{ r.request_date }} <br><span class="text-xs text-slate-500">{{ r.ready_time }}</span></td>
                    <td class="font-bold">{{ r.total_boxes }} Pcs <br><span class="text-xs text-slate-500">{{ r.approx_weight }} KG</span></td>
                    <td class="text-xs">{{ r.pickup_address }}</td>
                    <td>
                        <span class="px-2 py-1 rounded-full text-xs font-bold 
                        {% if r.status == 'PENDING' %}bg-amber-100 text-amber-700
                        {% elif r.status == 'ASSIGNED' %}bg-blue-100 text-blue-700
                        {% elif r.status == 'COMPLETED' %}bg-green-100 text-green-700
                        {% else %}bg-red-100 text-red-700{% endif %}">
                        {{ r.status }}
                        </span>
                    </td>
                    <td>{{ r.assigned_rider or 'Pending Assignment' }}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
            </div>
        </div>
    </div>
    <script>document.querySelector('input[type="date"]').valueAsDate = new Date();</script>
    """
    return render_page("Request Pickup", render_template_string(html, reqs=requests_list, cust_addr=cust_addr))

@app.route('/manage_pickups', methods=['GET', 'POST'])
@login_required
def manage_pickups():
    if session.get('role') not in ['ADMIN', 'OPS']: return redirect('/')
    conn = get_db()
    
    # Auto-Heal: Table Check
    with conn.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS pickup_requests (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, request_date DATE, ready_time VARCHAR(50), total_boxes INT, approx_weight DOUBLE, pickup_address TEXT, status VARCHAR(50) DEFAULT 'PENDING', assigned_rider VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    
    if request.method == 'POST':
        action = request.form.get('action')
        req_id = request.form.get('req_id')
        
        with conn.cursor() as c:
            if action == 'assign':
                rider = request.form.get('rider')
                c.execute("UPDATE pickup_requests SET assigned_rider=%s, status='ASSIGNED' WHERE id=%s", (rider, req_id))
                flash(f"✅ Rider '{rider}' assigned to pickup #{req_id}", "success")
            elif action == 'complete':
                c.execute("UPDATE pickup_requests SET status='COMPLETED' WHERE id=%s", (req_id,))
                flash(f"✅ Pickup #{req_id} marked as completed.", "success")
            elif action == 'cancel':
                c.execute("UPDATE pickup_requests SET status='CANCELLED' WHERE id=%s", (req_id,))
                flash(f"❌ Pickup #{req_id} cancelled.", "success")
        conn.commit()
        return redirect('/manage_pickups')
        
    with conn.cursor() as c:
        c.execute("""SELECT p.*, c.name as cust_name, c.phone as cust_phone 
                     FROM pickup_requests p JOIN customers c ON p.customer_id = c.id 
                     ORDER BY p.id DESC LIMIT 200""")
        requests_list = c.fetchall()
        c.execute("SELECT full_name FROM users WHERE role='DELIVERY' AND active=1")
        riders = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top:4px solid #2563eb;">
        <h3 class="text-lg font-bold text-slate-800 mb-4">🚛 Master Pickup Management Hub</h3>
        <div class="table-responsive">
        <table class="datatable">
            <thead><tr><th>Req ID</th><th>Customer Info</th><th>Date / Time</th><th>Boxes / Wt</th><th>Address</th><th>Status & Rider</th><th>Actions</th></tr></thead>
            <tbody>
            {% for r in reqs %}
            <tr>
                <td class="font-bold text-blue-600">PKP-{{ r.id }}</td>
                <td><span class="font-bold text-slate-800">{{ r.cust_name }}</span><br><span class="text-xs text-slate-500">{{ r.cust_phone }}</span></td>
                <td>{{ r.request_date }}<br><span class="text-xs text-red-500 font-bold">Ready By: {{ r.ready_time }}</span></td>
                <td class="font-bold">{{ r.total_boxes }} Pcs <br><span class="text-xs text-slate-500">{{ r.approx_weight }} KG</span></td>
                <td class="text-xs">{{ r.pickup_address }}</td>
                <td>
                    <span class="px-2 py-1 rounded-full text-xs font-bold 
                    {% if r.status == 'PENDING' %}bg-amber-100 text-amber-700
                    {% elif r.status == 'ASSIGNED' %}bg-blue-100 text-blue-700
                    {% elif r.status == 'COMPLETED' %}bg-green-100 text-green-700
                    {% else %}bg-red-100 text-red-700{% endif %}">
                    {{ r.status }}
                    </span><br>
                    <span class="text-xs font-bold mt-1 block">{{ r.assigned_rider }}</span>
                </td>
                <td style="white-space:nowrap;">
                    {% if r.status == 'PENDING' or r.status == 'ASSIGNED' %}
                    <form method="POST" style="display:inline-block;" class="mb-1">
                        <input type="hidden" name="req_id" value="{{ r.id }}">
                        <input type="hidden" name="action" value="assign">
                        <select name="rider" required style="width:100px; padding:2px; font-size:11px; border:1px solid #ccc;">
                            <option value="">-- Assign Rider --</option>
                            {% for rider in riders %}<option value="{{ rider.full_name }}">{{ rider.full_name }}</option>{% endfor %}
                        </select>
                        <button type="submit" class="btn-primary" style="padding:2px 6px; font-size:11px;">Go</button>
                    </form><br>
                    {% endif %}
                    
                    {% if r.status != 'COMPLETED' and r.status != 'CANCELLED' %}
                    <form method="POST" style="display:inline-block;" onsubmit="return confirm('Mark this pickup as successfully completed?');">
                        <input type="hidden" name="req_id" value="{{ r.id }}">
                        <input type="hidden" name="action" value="complete">
                        <button type="submit" class="btn-success" style="padding:3px 8px; font-size:11px;"><i class="fas fa-check"></i> Done</button>
                    </form>
                    <form method="POST" style="display:inline-block;" onsubmit="return confirm('Are you sure you want to cancel this request?');">
                        <input type="hidden" name="req_id" value="{{ r.id }}">
                        <input type="hidden" name="action" value="cancel">
                        <button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-times"></i></button>
                    </form>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
    </div>
    """
    return render_page("Manage Pickups", render_template_string(html, reqs=requests_list, riders=riders))

# ==========================================
# 📘 3.10 ADDRESS BOOK (SAVED RECEIVERS)
# ==========================================
@app.route('/address_book', methods=['GET', 'POST'])
@login_required
def address_book():
    if session.get('role') != 'CUSTOMER': return redirect('/')
    conn = get_db()
    cid = session.get('customer_id')
    
    # Auto-Heal: Create Table
    with conn.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS address_book (
            id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, name VARCHAR(100), 
            phone VARCHAR(50), address TEXT, station VARCHAR(100), state_code VARCHAR(10), 
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
            
    if request.method == 'POST':
        action = request.form.get('action')
        with conn.cursor() as c:
            if action == 'add':
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (request.form.get('station').upper(),))
                c.execute("INSERT INTO address_book (customer_id, name, phone, address, station, state_code) VALUES (%s,%s,%s,%s,%s,%s)",
                          (cid, request.form.get('name'), request.form.get('phone'), request.form.get('address'), request.form.get('station').upper(), request.form.get('state_code')))
                flash("✅ Address saved to your Address Book!", "success")
            elif action == 'delete':
                c.execute("DELETE FROM address_book WHERE id=%s AND customer_id=%s", (request.form.get('del_id'), cid))
                flash("Address deleted.", "success")
        conn.commit()
        return redirect('/address_book')
        
    with conn.cursor() as c:
        c.execute("SELECT * FROM address_book WHERE customer_id=%s ORDER BY name ASC", (cid,))
        addresses = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card" style="border-top:4px solid #10b981;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📘 Add New Receiver</h3>
            <form method="POST" class="space-y-3">
                <input type="hidden" name="action" value="add">
                <div><label class="label-modern">Receiver Name *</label><input type="text" name="name" required class="input-modern"></div>
                <div><label class="label-modern">Phone</label><input type="text" name="phone" class="input-modern"></div>
                <div><label class="label-modern">Dest Station *</label><input type="text" name="station" list="st_list" class="input-modern uppercase font-bold" required><datalist id="st_list">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
                <div><label class="label-modern">State Code</label><input type="text" name="state_code" class="input-modern" maxlength="2"></div>
                <div><label class="label-modern">Full Address</label><textarea name="address" rows="3" class="input-modern"></textarea></div>
                <button type="submit" class="btn-success w-full"><i class="fas fa-save"></i> Save Address</button>
            </form>
        </div>
        <div class="card lg:col-span-2">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📋 Saved Addresses ({{ addrs|length }})</h3>
            <table class="datatable">
                <thead><tr><th>Name / Phone</th><th>Destination</th><th>Address</th><th>Action</th></tr></thead>
                <tbody>
                {% for a in addrs %}
                <tr>
                    <td><span class="font-bold text-blue-600">{{ a.name }}</span><br><span class="text-xs text-slate-500">{{ a.phone }}</span></td>
                    <td class="font-bold">{{ a.station }} <br><span class="text-xs text-slate-500 font-normal">State: {{ a.state_code }}</span></td>
                    <td class="text-xs">{{ a.address }}</td>
                    <td>
                        <form method="POST" style="display:inline;" onsubmit="return confirm('Delete this address?');">
                            <input type="hidden" name="action" value="delete"><input type="hidden" name="del_id" value="{{ a.id }}">
                            <button type="submit" class="btn-danger" style="padding:3px 8px; font-size:11px;"><i class="fas fa-trash"></i></button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Address Book", render_template_string(html, addrs=addresses, stations=stations))

# ==========================================
# 💳 3.12 B2B PREPAID WALLET SYSTEM (SAAS FEATURE)
# ==========================================
@app.route('/wallet', methods=['GET', 'POST'])
@login_required
def wallet():
    if session.get('role') != 'CUSTOMER': return redirect('/')
    conn = get_db()
    cid = session.get('customer_id')

    # Auto-Heal: Create Wallet Table
    with conn.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, txn_date DATETIME DEFAULT CURRENT_TIMESTAMP, 
            txn_type VARCHAR(20), amount DOUBLE, description TEXT, status VARCHAR(20) DEFAULT 'APPROVED', reference VARCHAR(100))""")

    if request.method == 'POST':
        amt = safe_float(request.form.get('amount'))
        ref = request.form.get('reference', '')
        if amt > 0:
            with conn.cursor() as c:
                c.execute("INSERT INTO wallet_transactions (customer_id, txn_type, amount, description, status, reference) VALUES (%s, 'CREDIT', %s, 'Wallet Recharge Request', 'PENDING', %s)", (cid, amt, ref))
            conn.commit()
            flash("✅ Recharge request submitted! Balance will reflect once approved by Admin.", "success")
        else:
            flash("❌ Invalid amount.", "error")
        return redirect('/wallet')

    with conn.cursor() as c:
        # Calculate Current Wallet Balance
        c.execute("SELECT COALESCE(SUM(CASE WHEN txn_type='CREDIT' AND status='APPROVED' THEN amount ELSE 0 END),0) - COALESCE(SUM(CASE WHEN txn_type='DEBIT' AND status='APPROVED' THEN amount ELSE 0 END),0) as bal FROM wallet_transactions WHERE customer_id=%s", (cid,))
        bal_row = c.fetchone()
        wallet_balance = safe_float(bal_row['bal']) if bal_row else 0.0

        c.execute("SELECT * FROM wallet_transactions WHERE customer_id=%s ORDER BY id DESC LIMIT 100", (cid,))
        txns = c.fetchall()
    conn.close()

    html = """
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card lg:col-span-1" style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: none;">
            <div class="p-6 text-white text-center">
                <p class="text-slate-400 text-sm font-semibold uppercase tracking-wider mb-2">Available Balance</p>
                <h2 class="text-4xl font-bold text-white mb-6">₹ {{ "{:,.2f}".format(wallet_balance) }}</h2>
                <button onclick="document.getElementById('rechargeForm').style.display='block'" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 rounded-lg transition shadow-lg"><i class="fas fa-bolt"></i> Recharge Wallet</button>
            </div>
            
            <div id="rechargeForm" class="p-6 bg-white rounded-b-lg" style="display:none;">
                <h4 class="font-bold text-slate-800 mb-3 text-sm border-b pb-2">Request Recharge</h4>
                <form method="POST" class="space-y-3">
                    <div><label class="label-modern">Amount (₹) *</label><input type="number" step="0.01" name="amount" required class="input-modern font-bold text-green-600"></div>
                    <div><label class="label-modern">Payment Reference / UTR *</label><input type="text" name="reference" required placeholder="UPI / Bank Txn ID" class="input-modern"></div>
                    <div class="flex gap-2">
                        <button type="button" onclick="document.getElementById('rechargeForm').style.display='none'" class="btn-danger flex-1">Cancel</button>
                        <button type="submit" class="btn-success flex-1">Submit</button>
                    </div>
                </form>
            </div>
        </div>
        
        <div class="card lg:col-span-2">
            <h3 class="text-lg font-bold text-slate-800 mb-4">💳 Wallet Transaction History</h3>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>Txn ID</th><th>Date</th><th>Description</th><th>Ref/UTR</th><th>Amount</th><th>Status</th></tr></thead>
                    <tbody>
                    {% for t in txns %}
                    <tr>
                        <td class="font-bold text-slate-500">WTX-{{ t.id }}</td>
                        <td class="text-xs">{{ t.txn_date }}</td>
                        <td>{{ t.description }}</td>
                        <td class="text-xs font-mono">{{ t.reference or '-' }}</td>
                        <td class="font-bold {% if t.txn_type == 'CREDIT' %}text-green-600{% else %}text-red-600{% endif %}">
                            {% if t.txn_type == 'CREDIT' %}+{% else %}-{% endif %} ₹{{ t.amount }}
                        </td>
                        <td>
                            <span class="px-2 py-1 rounded-full text-xs font-bold 
                            {% if t.status == 'APPROVED' %}bg-green-100 text-green-700
                            {% elif t.status == 'PENDING' %}bg-amber-100 text-amber-700
                            {% else %}bg-red-100 text-red-700{% endif %}">
                            {{ t.status }}
                            </span>
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("My Wallet", render_template_string(html, wallet_balance=wallet_balance, txns=txns))

@app.route('/manage_wallets', methods=['GET', 'POST'])
@login_required
def manage_wallets():
    if session.get('role') not in ['ADMIN', 'ACCOUNTS']: return redirect('/')
    conn = get_db()
    
    # Auto-Heal Check
    with conn.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, txn_date DATETIME DEFAULT CURRENT_TIMESTAMP, 
            txn_type VARCHAR(20), amount DOUBLE, description TEXT, status VARCHAR(20) DEFAULT 'APPROVED', reference VARCHAR(100))""")

    if request.method == 'POST':
        action = request.form.get('action')
        with conn.cursor() as c:
            if action == 'approve':
                tid = request.form.get('txn_id')
                c.execute("UPDATE wallet_transactions SET status='APPROVED' WHERE id=%s", (tid,))
                
                # Payment Register aur Ledger me entry add karein taaki Accounting match ho
                c.execute("SELECT * FROM wallet_transactions WHERE id=%s", (tid,))
                txn = c.fetchone()
                if txn:
                    d = datetime.datetime.now().strftime("%Y-%m-%d")
                    c.execute("INSERT INTO payments(customer_id, payment_date, amount, mode, reference) VALUES(%s,%s,%s,'BANK',%s)", (txn['customer_id'], d, txn['amount'], f"Wallet Recharge: {txn['reference']}"))
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'PAYMENT',%s,0,%s,%s)", (txn['customer_id'], d, f"WTX-{tid}", txn['amount'], "Wallet Recharge Approved"))
                flash(f"✅ Recharge Request #{tid} Approved!", "success")
                
            elif action == 'reject':
                tid = request.form.get('txn_id')
                c.execute("UPDATE wallet_transactions SET status='REJECTED' WHERE id=%s", (tid,))
                flash(f"❌ Recharge Request #{tid} Rejected.", "error")
                
            elif action == 'manual_adjust':
                cid = request.form.get('cust_id')
                ttype = request.form.get('txn_type')
                amt = safe_float(request.form.get('amount'))
                desc = request.form.get('desc', 'Manual Admin Adjustment')
                if amt > 0:
                    c.execute("INSERT INTO wallet_transactions (customer_id, txn_type, amount, description, status) VALUES (%s, %s, %s, %s, 'APPROVED')", (cid, ttype, amt, desc))
                    flash(f"✅ Manual {ttype} of ₹{amt} added successfully.", "success")
        conn.commit()
        return redirect('/manage_wallets')

    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name")
        custs = c.fetchall()
        c.execute("""SELECT w.*, c.name as cust_name FROM wallet_transactions w 
                     JOIN customers c ON w.customer_id = c.id 
                     ORDER BY w.id DESC LIMIT 200""")
        txns = c.fetchall()
    conn.close()

    html = """
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="card" style="border-top:4px solid #10b981;">
            <h3 class="text-lg font-bold text-slate-800 mb-4">⚙️ Manual Adjustment</h3>
            <form method="POST" class="space-y-3">
                <input type="hidden" name="action" value="manual_adjust">
                <div><label class="label-modern">Customer A/c *</label>
                    <select name="cust_id" class="input-modern" required>
                        <option value="">-- Select Customer --</option>
                        {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
                    </select>
                </div>
                <div class="grid grid-cols-2 gap-2">
                    <div><label class="label-modern">Type *</label>
                        <select name="txn_type" class="input-modern font-bold">
                            <option value="CREDIT">Add Funds (+)</option>
                            <option value="DEBIT">Deduct Funds (-)</option>
                        </select>
                    </div>
                    <div><label class="label-modern">Amount (₹) *</label><input type="number" step="0.01" name="amount" required class="input-modern font-bold text-slate-800"></div>
                </div>
                <div><label class="label-modern">Description / Reason *</label><input type="text" name="desc" required class="input-modern"></div>
                <button type="submit" class="btn-success w-full"><i class="fas fa-check-circle"></i> Apply Adjustment</button>
            </form>
        </div>
        
        <div class="card lg:col-span-2">
            <h3 class="text-lg font-bold text-slate-800 mb-4">🏦 Master Wallet Register & Requests</h3>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>Txn ID</th><th>Customer</th><th>Amount</th><th>Ref/Desc</th><th>Status</th><th>Actions</th></tr></thead>
                    <tbody>
                    {% for t in txns %}
                    <tr>
                        <td class="font-bold text-slate-500">WTX-{{ t.id }}</td>
                        <td class="font-bold text-blue-600">{{ t.cust_name }}</td>
                        <td class="font-bold {% if t.txn_type == 'CREDIT' %}text-green-600{% else %}text-red-600{% endif %}">
                            {% if t.txn_type == 'CREDIT' %}+{% else %}-{% endif %} ₹{{ t.amount }}
                        </td>
                        <td class="text-xs">{{ t.reference or t.description }}</td>
                        <td>
                            <span class="px-2 py-1 rounded-full text-xs font-bold 
                            {% if t.status == 'APPROVED' %}bg-green-100 text-green-700
                            {% elif t.status == 'PENDING' %}bg-amber-100 text-amber-700
                            {% else %}bg-red-100 text-red-700{% endif %}">
                            {{ t.status }}
                            </span>
                        </td>
                        <td>
                            {% if t.status == 'PENDING' %}
                            <form method="POST" style="display:inline;" onsubmit="return confirm('Approve this recharge?');"><input type="hidden" name="action" value="approve"><input type="hidden" name="txn_id" value="{{ t.id }}"><button type="submit" class="btn-success" style="padding:2px 8px; font-size:11px;"><i class="fas fa-check"></i></button></form>
                            <form method="POST" style="display:inline;" onsubmit="return confirm('Reject this recharge?');"><input type="hidden" name="action" value="reject"><input type="hidden" name="txn_id" value="{{ t.id }}"><button type="submit" class="btn-danger" style="padding:2px 8px; font-size:11px;"><i class="fas fa-times"></i></button></form>
                            {% else %}
                            <span class="text-xs text-slate-400">Processed</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Manage Wallets", render_template_string(html, custs=custs, txns=txns))

# ==========================================
# SERVER LAUNCHER
# ==========================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("DEBUG", "False").lower() == "true"
    print(f"""
============================================================
   AGC ENTERPRISE ERP v5.1 - SERVER STARTED!           
   Local:  http://localhost:{port}                       
   Login:  admin / admin123                            
   Logo:  Place 'logo.png' in same folder             
   Production me DEBUG=False rakhein!                  
============================================================
""")
    app.run(host='0.0.0.0', debug=debug_mode, port=port)
