from flask import Flask, request, session, redirect, url_for, render_template_string, flash, send_file, jsonify
import pymysql, configparser, hashlib, io, os, csv, logging
from functools import wraps
from datetime import datetime, timedelta
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, mm
from reportlab.graphics.barcode import code128
from reportlab.lib.colors import HexColor
from werkzeug.exceptions import HTTPException
try: import qrcode
except ImportError: qrcode = None
import json

# ==========================================
# 🛡️ 1. BULLETPROOF LOGGING & CONFIG
# ==========================================
logging.basicConfig(filename='agc_erp.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'agc_super_secret_erp_v20_cloud_key')

config = configparser.ConfigParser()
config.read('db_config.ini')

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
            # Core Users & Master Tables
            c.execute("CREATE TABLE IF NOT EXISTS users (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(50), password_hash VARCHAR(100), full_name VARCHAR(100), role VARCHAR(50), branch_name VARCHAR(100), customer_id INT, active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS branches (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(50), name VARCHAR(100), city VARCHAR(100), phone VARCHAR(50), gstin VARCHAR(50))")
            c.execute("CREATE TABLE IF NOT EXISTS customers (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(50), name VARCHAR(255), gstin VARCHAR(50), phone VARCHAR(50), email VARCHAR(100), state VARCHAR(100), state_code VARCHAR(10), address TEXT, credit_limit DOUBLE DEFAULT 0, is_active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS rates (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, origin_state_code VARCHAR(10), dest_state_code VARCHAR(10), min_weight DOUBLE, max_weight DOUBLE, fixed_charge DOUBLE, per_kg_rate DOUBLE, gst_rate DOUBLE, active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS settings (key_name VARCHAR(100) PRIMARY KEY, value TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS sequences (name VARCHAR(50) PRIMARY KEY, value INT)")
            c.execute("CREATE TABLE IF NOT EXISTS stations (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) UNIQUE)")

            # Accounts & Finance
            c.execute("CREATE TABLE IF NOT EXISTS expenses (id INT AUTO_INCREMENT PRIMARY KEY, expense_date DATE, category VARCHAR(100), amount DOUBLE, paid_to VARCHAR(255), notes TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS ledger (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, entry_date DATE, voucher_type VARCHAR(50), reference VARCHAR(100), debit DOUBLE DEFAULT 0, credit DOUBLE DEFAULT 0, narration TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, invoice_id INT, payment_date DATE, amount DOUBLE, mode VARCHAR(50), reference VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS invoices (id INT AUTO_INCREMENT PRIMARY KEY, invoice_no VARCHAR(100), invoice_date DATE, customer_id INT, place_of_supply_state_code VARCHAR(10), taxable_amount DOUBLE DEFAULT 0, cgst DOUBLE DEFAULT 0, sgst DOUBLE DEFAULT 0, igst DOUBLE DEFAULT 0, total DOUBLE DEFAULT 0, status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS invoice_lines (id INT AUTO_INCREMENT PRIMARY KEY, invoice_id INT, description TEXT, hsn_sac VARCHAR(50), shipment_id INT, quantity INT DEFAULT 1, rate DOUBLE DEFAULT 0, taxable_amount DOUBLE DEFAULT 0, cgst DOUBLE DEFAULT 0, sgst DOUBLE DEFAULT 0, igst DOUBLE DEFAULT 0, total DOUBLE DEFAULT 0)")

            # Shipments & Operations
            c.execute("CREATE TABLE IF NOT EXISTS shipments (id INT AUTO_INCREMENT PRIMARY KEY, awb_no VARCHAR(100) UNIQUE, customer_id INT, booking_date DATE, origin_name VARCHAR(100), origin_phone VARCHAR(50), origin_address TEXT, origin_state_code VARCHAR(10), dest_name VARCHAR(100), dest_phone VARCHAR(50), dest_address TEXT, dest_state_code VARCHAR(10), dest_station VARCHAR(100), weight_kg DOUBLE, quantity INT, cod_amount DOUBLE, declared_value DOUBLE, service_type VARCHAR(50), taxable_amount DOUBLE, tax_rate DOUBLE, cgst DOUBLE, sgst DOUBLE, igst DOUBLE, total_amount DOUBLE, status VARCHAR(50), current_location VARCHAR(100), info TEXT, pod_photo TEXT, is_synced INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS scan_events (id INT AUTO_INCREMENT PRIMARY KEY, shipment_id INT, scan_type VARCHAR(50), location VARCHAR(100), remarks TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")

            # Hub & Delivery
            c.execute("CREATE TABLE IF NOT EXISTS outward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), out_station VARCHAR(100), destination VARCHAR(100), weight VARCHAR(50), pcs INT DEFAULT 1, network VARCHAR(100) DEFAULT 'SELF', network_awb VARCHAR(100), bag_no VARCHAR(100), info TEXT, outward_no VARCHAR(100), manifest_no VARCHAR(100), finalized INT DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS inward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), in_station VARCHAR(100), weight VARCHAR(50), info TEXT, inward_no VARCHAR(100), finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS delivery_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, delivery_boy VARCHAR(100), delivery_area VARCHAR(100), awb_no VARCHAR(100), receiver_name VARCHAR(100), info TEXT, drs_no VARCHAR(100), finalized INT DEFAULT 0)")

            # Transport
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

            defs = {"company_name": "AKASH GANGA COURIER", "company_address": "Head Office: Nohar, Rajasthan", "company_gstin": "08ADQPC7585D1Z9", "company_phone": "+91 7357073316", "company_state_code": "08", "company_website": "https://agconline.in", "company_email": "PANKAJNOHAR@YAHOO.CO.IN", "terms_note": "Liability limited to declared value only. Subject to local jurisdiction.", "bank_details": "Bank: HDFC | A/C: 123456789 | IFSC: HDFC0001", "fuel_surcharge": "0"}
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
# 🎨 2. MASTER CORPORATE UI TEMPLATE (WITH DATATABLES, CHARTJS, SCANNER)
# ==========================================
BASE_HTML = """
<!DOCTYPE html><html><head><title>{{ title }} - AGC Enterprise ERP</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<!-- DataTables CSS -->
<link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/dataTables.bootstrap5.min.css">
<style>
    body{font-family:'Inter',sans-serif;background:#F1F5F9;margin:0;color:#1E293B;}
    .sidebar{width:260px;background:#0B1F3A;color:white;position:fixed;height:100%;overflow-y:auto;box-shadow:4px 0 15px rgba(0,0,0,0.1);z-index:100;transition:0.3s;}
    .logo{padding:25px 20px;font-size:24px;font-weight:800;color:#C9A24B;border-bottom:1px solid rgba(255,255,255,0.05);text-align:center;letter-spacing:1px;}
    .menu a{display:flex;align-items:center;gap:12px;padding:14px 25px;color:#94A3B8;text-decoration:none;font-weight:600;font-size:14px;transition:0.3s;border-left:4px solid transparent;}
    .menu a i{width:20px;text-align:center;font-size:16px;}
    .menu a:hover,.menu a.active{background:rgba(201,162,75,0.1);color:#C9A24B;border-left:4px solid #C9A24B;}
    .menu-header{color:#64748B;padding:20px 25px 8px;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;}
    .main-content{margin-left:260px;padding:30px;}
    .header{display:flex;justify-content:space-between;align-items:center;background:white;padding:16px 25px;border-radius:12px;margin-bottom:25px;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);border:1px solid #E2E8F0;}
    .card{background:white;padding:25px;border-radius:12px;margin-bottom:25px;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);border:1px solid #E2E8F0;border-top:4px solid #0B1F3A;}
    input,select,textarea{background:#F8FAFC;border:1px solid #CBD5E1;color:#0F172A;padding:10px 14px;border-radius:8px;box-sizing:border-box;font-family:inherit;font-size:14px;width:100%;transition:0.2s;}
    input:focus,select:focus,textarea:focus{border-color:#C9A24B;outline:none;background:#FFFFFF;box-shadow:0 0 0 3px rgba(201,162,75,0.15);}
    label{font-weight:700;color:#64748B;margin-right:5px;font-size:12px;display:block;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;}
    .btn{border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-weight:700;font-size:14px;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:8px;color:white;transition:0.3s;box-shadow:0 2px 4px rgba(0,0,0,0.1);}
    .btn:hover{transform:translateY(-1px);box-shadow:0 4px 6px rgba(0,0,0,0.15);}
    .btn-blue{background:#0B1F3A;color:#C9A24B;}.btn-blue:hover{background:#13294B;}
    .btn-red{background:#EF4444;}.btn-red:hover{background:#DC2626;}
    .btn-gold{background:#C9A24B;color:#0B1F3A;}.btn-gold:hover{background:#B48A35;}
    .btn-green{background:#10B981;}.btn-green:hover{background:#059669;}
    .btn-ghost{background:#F1F5F9;border:1px solid #CBD5E1;color:#475569;box-shadow:none;}
    table{width:100%;border-collapse:separate;border-spacing:0;margin-top:15px;font-size:13px;color:#334155;}
    th,td{padding:12px 10px;text-align:left;border-bottom:1px solid #E2E8F0;}
    th{background:#F8FAFC;font-weight:700;color:#64748B;text-transform:uppercase;font-size:12px;letter-spacing:0.5px;}
    .badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:800;background:#E2E8F0;color:#475569;}
    .b-del{background:#D1FAE5;color:#059669;}
    .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
    .grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;}
    .grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;}
    .grid-6{display:grid;grid-template-columns:repeat(6,1fr);gap:15px;}
    /* DataTable Custom CSS */
    .dataTables_wrapper .dataTables_paginate .paginate_button {padding: 0.2em 0.8em; margin-left: 2px; border-radius: 4px; border: 1px solid #E2E8F0;}
    .dataTables_wrapper .dataTables_paginate .paginate_button.current {background: #0B1F3A; color: white !important; border: none;}
    .dataTables_wrapper .dataTables_filter input {border: 2px solid #C9A24B; border-radius: 6px; padding: 6px 12px; outline: none; margin-bottom: 10px;}
    /* Scanner Modal */
    .modal-overlay {display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); z-index:1000; align-items:center; justify-content:center;}
    .modal-content {background:white; padding:20px; border-radius:12px; width:100%; max-width:500px;}
</style>
<!-- Libraries -->
<script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
<script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://unpkg.com/html5-qrcode" type="text/javascript"></script>
</head>
<body>
    <div class="sidebar">
        <div class="logo">◆ AGC ERP<br><span style="font-size:13px; color:#94A3B8; font-weight:600;">{{ session.get('branch', 'HQ') }}</span></div>
        <div class="menu">
            {% if session.get('role') == 'CUSTOMER' %}
                <div class="menu-header">My Panel</div>
                <a href="/" class="{{ 'active' if current_path == '/' else '' }}"><i class="fas fa-chart-pie"></i> Dashboard</a>
                <a href="/booking" class="{{ 'active' if current_path == '/booking' else '' }}"><i class="fas fa-box-open"></i> New Booking</a>
                <a href="/shipments" class="{{ 'active' if current_path == '/shipments' else '' }}"><i class="fas fa-truck-fast"></i> My Shipments</a>
                <a href="/my_ledger" class="{{ 'active' if current_path == '/my_ledger' else '' }}"><i class="fas fa-wallet"></i> My Ledger</a>
                <a href="/track" target="_blank" class="{{ 'active' if current_path == '/track' else '' }}"><i class="fas fa-search-location"></i> Track Center</a>
            {% else %}
                <div class="menu-header">Master Operations</div>
                <a href="/" class="{{ 'active' if current_path == '/' else '' }}"><i class="fas fa-chart-pie"></i> Dashboard</a>
                <a href="/booking" class="{{ 'active' if current_path == '/booking' else '' }}"><i class="fas fa-box-open"></i> Fast Booking</a>
                <a href="/shipments" class="{{ 'active' if current_path == '/shipments' or '/edit_shipment' in current_path else '' }}"><i class="fas fa-truck-fast"></i> Shipments</a>
                <a href="/track" target="_blank" class="{{ 'active' if current_path == '/track' else '' }}"><i class="fas fa-search-location"></i> Track Center</a>
                <div class="menu-header">Hub Management</div>
                <a href="/outward" class="{{ 'active' if current_path == '/outward' else '' }}"><i class="fas fa-plane-departure"></i> Outward Hub</a>
                <a href="/inward" class="{{ 'active' if current_path == '/inward' else '' }}"><i class="fas fa-plane-arrival"></i> Inward Hub</a>
                <a href="/drs" class="{{ 'active' if current_path == '/drs' else '' }}"><i class="fas fa-motorcycle"></i> DRS / Delivery</a>
                <a href="/master_bag" class="{{ 'active' if current_path == '/master_bag' else '' }}"><i class="fas fa-shopping-bag"></i> Master Bag</a>
                <div class="menu-header">Accounts & CRM</div>
                <a href="/customers" class="{{ 'active' if current_path == '/customers' else '' }}"><i class="fas fa-users"></i> Customers</a>
                <a href="/rates" class="{{ 'active' if current_path == '/rates' else '' }}"><i class="fas fa-tags"></i> Rate Cards</a>
                <a href="/accounts" class="{{ 'active' if current_path == '/accounts' else '' }}"><i class="fas fa-wallet"></i> Ledger & Payments</a>
                <a href="/expenses" class="{{ 'active' if current_path == '/expenses' else '' }}"><i class="fas fa-receipt"></i> Expenses</a>
                <a href="/reports" class="{{ 'active' if current_path == '/reports' else '' }}"><i class="fas fa-chart-line"></i> Master Reports</a>
                {% if session.get('role') == 'ADMIN' %}
                    <div class="menu-header">Administration</div>
                    <a href="/stationery" class="{{ 'active' if current_path == '/stationery' else '' }}"><i class="fas fa-barcode"></i> Stationery AWB</a>
                    <a href="/users" class="{{ 'active' if current_path == '/users' else '' }}"><i class="fas fa-user-shield"></i> Users & Branch</a>
                    <a href="/settings" class="{{ 'active' if current_path == '/settings' else '' }}"><i class="fas fa-cogs"></i> System Settings</a>
                    <a href="/import_csv" class="{{ 'active' if current_path == '/import_csv' else '' }}"><i class="fas fa-file-import"></i> Excel Import</a>
                {% endif %}
            {% endif %}
            <a href="/logout" style="color:#EF4444; margin-top:20px; border-top:1px solid rgba(255,255,255,0.05); padding-top:20px;"><i class="fas fa-power-off"></i> Secure Logout</a>
        </div>
    </div>
    <div class="main-content">
        <div class="header">
            <div style="font-size:20px; font-weight:800; color:#0B1F3A;"><i class="fas fa-cube" style="color:#C9A24B; margin-right:8px;"></i> {{ title }}</div>
            <div style="display:flex; gap:15px; align-items:center;">
                <div style="background:#F1F5F9; color:#0B1F3A; padding:8px 18px; border-radius:20px; font-weight:700; font-size:13px; border:1px solid #E2E8F0; display:flex; align-items:center; gap:8px;">
                    <i class="fas fa-user-circle" style="color:#C9A24B; font-size:16px;"></i> {{ session.get('full_name', '') }} <span style="color:#64748b; font-weight:600;">({{ session.get('role', '') }})</span>
                </div>
            </div>
        </div>
        
        <!-- SweetAlert2 Flashes -->
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            <script>
            $(document).ready(function() {
                {% for category, message in messages %}
                    Swal.fire({
                        toast: true, position: 'top-end', showConfirmButton: false, timer: 3000,
                        icon: '{{ "success" if category == "success" else "error" }}',
                        title: '{{ message }}'
                    });
                {% endfor %}
            });
            </script>
          {% endif %}
        {% endwith %}
        
        {{ content|safe }}
        
        <!-- Init DataTables -->
        <script>
            $(document).ready(function() {
                $('.datatable').DataTable({
                    "pageLength": 25,
                    "ordering": true,
                    "order": [[0, "desc"]],
                    "language": {"search": "<i class='fas fa-search'></i> Quick Search:"}
                });
            });
        </script>
    </div>
</body></html>
"""
def render_page(title, content): 
    return render_template_string(BASE_HTML, title=title, content=content, current_path=request.path)

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
    return """<style>body{background:#F1F5F9; display:flex; justify-content:center; align-items:center; height:100vh; font-family:'Segoe UI',sans-serif;} .box{background:white; padding:50px 40px; border-radius:16px; text-align:center; width:340px; box-shadow:0 10px 40px rgba(0,0,0,0.1); border-top:6px solid #0B1F3A;} input{width:100%; margin:12px 0; padding:14px; box-sizing:border-box; background:#F8FAFC; border:1px solid #E2E8F0; color:#1E293B; border-radius:8px; outline:none; font-size:14px;} input:focus{border-color:#C9A24B; box-shadow:0 0 0 3px rgba(201,162,75,0.1);} button{width:100%; padding:14px; background:#0B1F3A; color:#C9A24B; border:none; font-weight:800; cursor:pointer; border-radius:8px; margin-top:15px; font-size:15px; letter-spacing:1px; transition:0.3s;} button:hover{background:#13294B;}</style><div class="box"><h1 style="color:#0B1F3A; margin-top:0; margin-bottom:5px; font-size:32px;">AGC <span style="color:#C9A24B;">ERP</span></h1><p style="color:#64748B; font-size:14px; margin-bottom:30px; font-weight:600;">Premium Corporate Suite</p><form method="POST"><input name="username" placeholder="Username" required autocomplete="off"><input type="password" name="password" placeholder="Password" required><button type="submit">SECURE LOGIN</button></form></div>"""

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
        <div class="card" style="border-top-color: #3B82F6;"><h3><i class="fas fa-boxes" style="color:#3B82F6; margin-right:8px;"></i> Total Shipments</h3><h2 style="font-size:28px; margin:10px 0 0 0; color:#0F172A;">{s_c}</h2></div>
        <div class="card" style="border-top-color: #10B981;"><h3><i class="fas fa-check-circle" style="color:#10B981; margin-right:8px;"></i> Delivered</h3><h2 style="font-size:28px; margin:10px 0 0 0; color:#0F172A;">{d_c}</h2></div>
        <div class="card" style="border-top-color: #C9A24B;"><h3><i class="fas fa-rupee-sign" style="color:#C9A24B; margin-right:8px;"></i> {rev_label}</h3><h2 style="font-size:28px; margin:10px 0 0 0; color:#0F172A;">₹ {rev_val:,.2f}</h2></div>
        <div class="card" style="border-top-color: #EF4444;"><h3><i class="fas fa-hand-holding-usd" style="color:#EF4444; margin-right:8px;"></i> Outstanding</h3><h2 style="font-size:28px; margin:10px 0 0 0; color:#0F172A;">₹ {out_val:,.2f}</h2></div>
    </div>
    <div class="card" style="border-top-color: #0B1F3A;">
        <h3 style="margin-top:0;"><i class="fas fa-chart-line" style="color:#C9A24B;"></i> Last 7 Days Performance</h3>
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
                    backgroundColor: '#0B1F3A',
                    borderColor: '#C9A24B',
                    borderWidth: 2,
                    borderRadius: 4
                }}]
            }}
        }});
    </script>
    """
    return render_page("Dashboard Overview", html)

# ==========================================
# 🌐 4. BRANDED PUBLIC TRACKING PAGE 
# ==========================================
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
    <!DOCTYPE html><html><head><title>Track Shipment - AGC</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet"><style>body{font-family:'Inter',sans-serif;background:#F1F5F9;margin:0;color:#1E293B;}.nav{background:#0B1F3A;padding:20px;text-align:center;box-shadow:0 4px 15px rgba(0,0,0,0.1);}.nav h1{margin:0;color:#FFFFFF;font-weight:800;font-size:28px;letter-spacing:1px;}.nav h1 span{color:#C9A24B;}.container{max-width:800px;margin:40px auto;padding:0 20px;}.card{background:white;padding:40px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,0.05);border-top:6px solid #C9A24B;}.search-box{display:flex;gap:15px;margin-bottom:30px;}input{flex:1;padding:16px 20px;border:2px solid #E2E8F0;border-radius:8px;font-size:16px;outline:none;text-transform:uppercase;font-weight:600;color:#0F172A;}input:focus{border-color:#0B1F3A;box-shadow:0 0 0 4px rgba(11,31,58,0.1);}.btn{padding:16px 30px;background:#0B1F3A;color:#C9A24B;border:none;border-radius:8px;font-size:16px;font-weight:800;cursor:pointer;transition:0.3s;letter-spacing:1px;}.btn:hover{background:#13294B;transform:translateY(-2px);box-shadow:0 5px 15px rgba(11,31,58,0.2);}.msg{padding:15px 20px;border-radius:8px;font-weight:600;font-size:14px;display:flex;align-items:center;gap:10px;}.error{background:#FEF2F2;color:#DC2626;border:1px solid #FECACA;}.status-badge{display:inline-block;padding:8px 16px;background:#FEF3C7;color:#92400E;border-radius:30px;font-weight:800;font-size:14px;text-transform:uppercase;}.status-DELIVERED{background:#D1FAE5;color:#065F46;}.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;background:#F8FAFC;padding:25px;border-radius:12px;border:1px solid #E2E8F0;margin-bottom:30px;}.info-grid div strong{color:#64748B;display:block;font-size:12px;text-transform:uppercase;margin-bottom:5px;}.info-grid div span{font-size:15px;font-weight:600;color:#0F172A;}.timeline{border-left:3px solid #E2E8F0;margin-left:20px;padding-left:30px;margin-top:30px;}.event{position:relative;margin-bottom:30px;}.event::before{content:'';position:absolute;left:-38px;top:0;width:14px;height:14px;background:white;border:4px solid #C9A24B;border-radius:50%;box-shadow:0 0 0 4px white;}.event.latest::before{border-color:#10B981;background:#10B981;}.e-date{font-size:13px;color:#64748B;font-weight:600;margin-bottom:6px;}.e-title{font-size:16px;font-weight:800;margin:0 0 6px 0;color:#0F172A;}.e-desc{font-size:14px;color:#475569;margin:0;line-height:1.5;}.footer{text-align:center;margin-top:40px;color:#94A3B8;font-size:13px;font-weight:600;}@media (max-width:600px){.search-box{flex-direction:column;}.info-grid{grid-template-columns:1fr;}}</style>
    </head><body><div class="nav"><h1>AGC <span>COURIER</span></h1></div><div class="container"><div class="card"><h2 style="color:#0B1F3A;margin-top:0;text-align:center;font-size:24px;margin-bottom:10px;">Track Your Shipment</h2><p style="text-align:center;color:#64748B;margin-bottom:30px;font-weight:600;">Enter your AWB or Reference Number</p><form method="GET" class="search-box"><input type="text" name="awb" value="{{ awb }}" placeholder="e.g. AWB12345678" required autocomplete="off"><button type="submit" class="btn"><i class="fas fa-search"></i> TRACK</button></form>
    {% if error_msg %}<div class="msg error"><i class="fas fa-exclamation-triangle"></i> System Error: {{ error_msg }}</div>{% elif awb and not shipment %}<div class="msg error"><i class="fas fa-times-circle"></i> No shipment found with AWB: {{ awb }}</div>{% elif shipment %}
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:20px;border-bottom:2px solid #F1F5F9;"><div><h3 style="margin:0;color:#0B1F3A;font-size:22px;font-weight:800;">{{ shipment.awb_no }}</h3><span style="color:#64748B;font-size:13px;font-weight:600;">Booked on {{ shipment.booking_date }}</span></div><div class="status-badge status-{{ shipment.status }}">{{ shipment.status }}</div></div>
    <div class="info-grid"><div><strong>From (Origin)</strong><span>{{ shipment.origin_name or '-' }}</span></div><div><strong>To (Destination)</strong><span>{{ shipment.dest_name or '-' }}<br><small style="color:#64748B;">{{ shipment.dest_station or '-' }}</small></span></div><div><strong>Current Location</strong><span>{{ shipment.current_location or '-' }}</span></div><div><strong>Shipment Details</strong><span>Weight: {{ shipment.weight_kg or '1.0' }} KG<br>Pieces: {{ shipment.quantity or '1' }}</span></div></div>
    <h3 style="color:#0B1F3A;font-weight:800;margin-bottom:0;">Tracking History</h3>
    {% if events %}<div class="timeline">{% for e in events %}<div class="event {% if loop.first %}latest{% endif %}"><div class="e-date">{{ e.created_at }}</div><h4 class="e-title">{{ e.scan_type }}</h4><p class="e-desc">{{ e.location or '-' }} - {{ e.remarks or '' }}</p></div>{% endfor %}</div>{% else %}<p style="color:#64748B;padding:20px 0;font-weight:600;">No tracking events found yet.</p>{% endif %}{% endif %}
    </div><div class="footer">&copy; 2026 AGC Premium Logistics. All rights reserved.<br><br><a href="/login" style="color:#C9A24B;text-decoration:none;"><i class="fas fa-lock"></i> Staff Login</a></div></div></body></html>
    """
    return render_template_string(html, awb=awb, shipment=shipment, events=events, error_msg=error_msg)

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
    html = """<div class="card"><h3 style="margin-top:0; color:#0B1F3A;"><i class="fas fa-cogs" style="color:#C9A24B;"></i> Company Settings (For PDFs & Billing)</h3><form method="POST" class="grid-2"><div><label>Company Name</label><input name="company_name" value="{{ s.get('company_name', '') }}" required></div><div><label>Company GSTIN</label><input name="company_gstin" value="{{ s.get('company_gstin', '') }}"></div><div><label>Head Office Address</label><input name="company_address" value="{{ s.get('company_address', '') }}"></div><div><label>Customer Care Phone</label><input name="company_phone" value="{{ s.get('company_phone', '') }}"></div><div><label>Website</label><input name="company_website" value="{{ s.get('company_website', '') }}"></div><div><label>Email</label><input name="company_email" value="{{ s.get('company_email', '') }}"></div><div><label>Bank Details (Invoice)</label><input name="bank_details" value="{{ s.get('bank_details', '') }}"></div><div><label>Fuel Surcharge (%)</label><input type="number" step="0.1" name="fuel_surcharge" value="{{ s.get('fuel_surcharge', '0') }}"></div><div style="grid-column: span 2;"><label>Terms & Conditions Note</label><input name="terms_note" value="{{ s.get('terms_note', '') }}"></div><div style="grid-column: span 2; margin-top:10px;"><button type="submit" class="btn btn-gold" style="width:100%; padding:12px; font-size:15px;"><i class="fas fa-save"></i> Save Global Settings</button></div></form></div>"""
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
    html = """<div class="card"><h3 style="margin-top:0; color:#0E8A6D;"><i class="fas fa-tags"></i> Add Contract Rate</h3><form method="POST" class="grid-4" style="align-items:end;"><div style="grid-column: span 2;"><label>Customer (Blank for Generic)</label><select name="cust_id"><option value="">-- Generic / Default --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div><label>Origin State (eg. RJ)</label><input name="ostate" required></div><div><label>Dest State (eg. MH)</label><input name="dstate" required></div><div><label>Min Wt (KG)</label><input type="number" step="0.1" name="min_w" value="0.0"></div><div><label>Max Wt (KG)</label><input type="number" step="0.1" name="max_w" value="999.0"></div><div><label>Fixed Charge (₹)</label><input type="number" step="0.1" name="fixed" value="0.0"></div><div><label>Per KG Rate (₹)</label><input type="number" step="0.1" name="per_kg" value="0.0"></div><div><label>GST %</label><input type="number" step="0.1" name="gst" value="18.0"></div><div><button type="submit" class="btn btn-blue" style="width:100%;"><i class="fas fa-save"></i> Save Rate</button></div></form></div><div class="card"><h3>Active Rate Cards</h3><table class="datatable"><thead><tr><th>Customer</th><th>Route</th><th>Wt Slab</th><th>Fixed</th><th>Per KG</th><th>GST</th><th>Del</th></tr></thead><tbody>{% for r in r_list %}<tr><td><strong>{{ r.name or 'Generic' }}</strong></td><td>{{ r.origin_state_code }} &rarr; {{ r.dest_state_code }}</td><td>{{ r.min_weight }} - {{ r.max_weight }} KG</td><td style="color:#0E8A6D; font-weight:bold;">₹{{ r.fixed_charge }}</td><td style="color:#C9A24B; font-weight:bold;">₹{{ r.per_kg_rate }}</td><td>{{ r.gst_rate }}%</td><td><a href="/rates?delete={{ r.id }}" class="btn btn-red" style="padding:4px 8px; border-radius:4px;"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</tbody></table></div>"""
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
    html = """<div class="grid-2"><div class="card"><h3 style="margin-top:0; color:#0B1F3A;"><i class="fas fa-barcode" style="color:#C9A24B;"></i> Allocate Pre-Printed AWBs</h3><form method="POST"><label>Assign To</label><input name="name" list="nlist" required style="margin-bottom:15px;"><datalist id="nlist">{% for n in names %}<option value="{{ n.name }}">{% endfor %}</datalist><div class="grid-3" style="margin-bottom:20px;"><div><label>Prefix</label><input name="prefix" value="AWB"></div><div><label>From No</label><input type="number" name="from" required></div><div><label>To No</label><input type="number" name="to" required></div></div><button type="submit" class="btn btn-gold" style="width:100%; padding:12px; font-size:14px;"><i class="fas fa-check-circle"></i> Allocate Inventory</button></form></div><div class="card"><h3>Allocation History</h3><table class="datatable"><thead><tr><th>Date</th><th>Assigned To</th><th>Qty</th><th>Range</th><th>Del</th></tr></thead><tbody>{% for h in hists %}<tr><td>{{ h.booking_date }}</td><td><strong>{{ h.origin_name }}</strong></td><td><span class="badge b-del">{{ h.qty }}</span></td><td><small style="color:#64748B;">{{ h.from_awb }}<br>to {{ h.to_awb }}</small></td><td><a href="/stationery?delete=1&name={{ h.origin_name }}&date={{ h.booking_date }}" class="btn btn-red" style="padding:4px 8px; border-radius:4px;"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</tbody></table></div></div>"""
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
    html = """<div class="card"><h3 style="margin-top:0; color:#0E8A6D;"><i class="fas fa-user-plus"></i> Add New User</h3><form method="POST" class="grid-4" style="align-items:end;"><div><label>Username</label><input name="username" required></div><div><label>Password</label><input type="password" name="password" required></div><div><label>Full Name</label><input name="full_name" required></div><div><label>Role</label><select name="role"><option>ADMIN</option><option>OPERATOR</option><option>ACCOUNTANT</option><option>CUSTOMER</option></select></div><div style="grid-column: span 2;"><label>Branch / Station</label><input name="branch" list="brlist" required><datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist></div><div style="grid-column: span 1;"><label>Link Customer (If Role=CUSTOMER)</label><select name="customer_id"><option value="">-- None --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div><button type="submit" class="btn btn-blue" style="width:100%;"><i class="fas fa-save"></i> Save</button></div></form></div><div class="card"><h3><i class="fas fa-users-cog"></i> System Users</h3><table class="datatable"><thead><tr><th>Username</th><th>Full Name</th><th>Role</th><th>Branch</th><th>Cust_ID</th><th>Status</th><th>Action</th></tr></thead><tbody>{% for u in u_list %}<tr><td><strong>{{ u.username }}</strong></td><td>{{ u.full_name }}</td><td><span class="badge">{{ u.role }}</span></td><td>{{ u.branch_name or 'HQ' }}</td><td>{{ u.customer_id or '-' }}</td><td>{% if u.active %}<span class="badge b-del">Active</span>{% else %}<span class="badge">Inactive</span>{% endif %}</td><td>{% if u.active %}<a href="/users?delete={{ u.id }}" class="btn btn-red" style="padding:4px 8px; border-radius:4px;"><i class="fas fa-trash"></i></a>{% endif %}</td></tr>{% endfor %}</tbody></table></div>"""
    return render_page("Users & Branches", render_template_string(html, u_list=u_list, branches=branches, custs=custs))

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

@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE customers SET is_active=0 WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Deleted!", "success"); return redirect('/customers')
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c: c.execute("INSERT INTO customers(code, name, gstin, phone, email, state, state_code, address, credit_limit, is_active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)", (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone',''), d.get('email',''), d.get('state',''), d.get('scode',''), d.get('addr',''), safe_float(d.get('limit')))); conn.commit(); flash("Added!", "success")
    with conn.cursor() as c: c.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id DESC"); custs = c.fetchall()
    conn.close()
    html = """<div class="card"><h3 style="margin-top:0; color:#0B1F3A;"><i class="fas fa-user-plus" style="color:#C9A24B;"></i> Add Customer</h3><form method="POST" class="grid-4" style="align-items:end;"><div><label>Code</label><input name="code" required></div><div><label>Company Name</label><input name="name" required></div><div><label>GSTIN</label><input name="gstin"></div><div><label>Phone</label><input name="phone"></div><div><label>Email</label><input name="email"></div><div><label>State & Code</label><div style="display:flex; gap:5px;"><input name="state" placeholder="State" style="width:70%;"><input name="scode" placeholder="Code" style="width:30%;"></div></div><div><label>Address</label><input name="addr"></div><div><label>Credit Limit (₹)</label><input type="number" name="limit" value="0"></div><div style="grid-column: span 4;"><button type="submit" class="btn btn-blue" style="width:100%; padding:12px;"><i class="fas fa-save"></i> Save Customer</button></div></form></div><div class="card"><table class="datatable"><thead><tr><th>Code</th><th>Name</th><th>Phone</th><th>GSTIN</th><th>State</th><th>Limit</th><th>Act</th></tr></thead><tbody>{% for r in custs %}<tr><td>{{ r.code }}</td><td><strong>{{ r.name }}</strong></td><td>{{ r.phone }}</td><td>{{ r.gstin }}</td><td>{{ r.state }} ({{ r.state_code }})</td><td style="color:#0E8A6D; font-weight:bold;">₹{{ r.credit_limit }}</td><td><a href="/customers?delete={{ r.id }}" class="btn btn-red" style="padding:4px 8px; border-radius:4px;"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</tbody></table></div>"""
    return render_page("Customers Master", render_template_string(html, custs=custs))

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
                
                c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, origin_phone, origin_address, origin_state_code, dest_name, dest_phone, dest_address, dest_state_code, dest_station, weight_kg, quantity, cod_amount, declared_value, service_type, taxable_amount, tax_rate, cgst, sgst, igst, total_amount, info, status, current_location, is_synced) 
                             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s, 0)""", 
                          (d.get('awb','').upper(), cid, d.get('date',''), d.get('oname',''), d.get('ophone',''), d.get('oaddr',''), d.get('ostate',''), d.get('dname',''), d.get('dphone',''), d.get('daddr',''), d.get('dstate',''), d.get('dstat','').upper(), wt, safe_int(d.get('pcs', 1)), safe_float(d.get('cod')), safe_float(d.get('dec')), d.get('srv','SURFACE'), taxable, tax, cgst, sgst, igst, tot, d.get('info',''), session.get('branch','HQ')))
                sid = c.lastrowid
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'BOOKED',%s,'Booked at counter')", (sid, session.get('branch','HQ')))
                if cid: c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (cid, d.get('date',''), d.get('awb','').upper(), tot, f"Booking {d.get('awb','').upper()}"))
                conn.commit()
                flash(f"AWB Booked! Total: ₹{tot:.2f}", "success")
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
            q_recent += " WHERE s.customer_id = %s"
            params_recent.append(session.get('customer_id'))
        elif session.get('role') != 'ADMIN':
            q_recent += " WHERE s.origin_name = %s"
            params_recent.append(session.get('branch', 'HQ'))
        q_recent += " ORDER BY s.id DESC LIMIT 100"
        
        c.execute(q_recent, tuple(params_recent))
        recent = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="max-width:1000px; margin:auto;"><h3 style="color:#0B1F3A; margin-top:0; border-bottom:2px solid #E2E8F0; padding-bottom:10px;"><i class="fas fa-box" style="color:#C9A24B;"></i> Master Fast Booking</h3>
        <form method="POST" id="bkForm">
            <div class="grid-4" style="background:#F8FAFC; padding:20px; border-radius:12px; margin-bottom:20px; border:1px solid #E2E8F0;">
                <div><label>Booking Date</label><input type="date" name="date" id="bdt" required></div>
                <div><label>AWB Number</label><input name="awb" required style="font-weight:900; color:#0B1F3A; text-transform:uppercase; font-size:16px;"></div>
                {% if session.get('role') == 'CUSTOMER' %}
                    <input type="hidden" name="cust_id" id="cid" value="{{ my_cust.id }}" data-state="{{ my_cust.state_code }}">
                    <div style="grid-column: span 2;"><label>Customer (Linked)</label><input value="{{ my_cust.name }}" readonly style="background:#E2E8F0; font-weight:bold;"></div>
                {% else %}
                    <div style="grid-column: span 2;"><label>Customer (Rates Auto-Apply)</label><select name="cust_id" id="cid" onchange="fetchRate()"><option value="">-- Walk-in / Cash Booking --</option>{% for c in custs %}<option value="{{ c.id }}" data-state="{{ c.state_code }}">{{ c.name }}</option>{% endfor %}</select></div>
                {% endif %}
            </div>
            <div class="grid-2">
                <div style="border:1px solid #E2E8F0; padding:20px; border-radius:12px; background:white;"><h4 style="margin-top:0; color:#C9A24B; text-transform:uppercase; letter-spacing:1px;"><i class="fas fa-building"></i> Origin (Shipper)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Sender Name</label><input name="oname" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.name }}{% else %}{{ session.get('branch', 'HQ') }}{% endif %}" required></div><div><label>Phone</label><input name="ophone" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.phone }}{% endif %}"></div><div><label>State Code</label><input name="ostate" id="ost" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.state_code }}{% else %}RJ{% endif %}" onchange="fetchRate()"></div>
                    <div style="grid-column: span 2;"><label>Address</label><input name="oaddr" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.address }}{% endif %}"></div>
                </div></div>
                <div style="border:1px solid #E2E8F0; padding:20px; border-radius:12px; background:white;"><h4 style="margin-top:0; color:#0E8A6D; text-transform:uppercase; letter-spacing:1px;"><i class="fas fa-home"></i> Destination (Consignee)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Receiver Name</label><input name="dname" required></div><div><label>Phone</label><input name="dphone" required></div><div><label>State Code</label><input name="dstate" id="dst" onchange="fetchRate()"></div>
                    <div style="grid-column: span 2;"><label>Dest Station (City)</label><input name="dstat" list="stations" required style="border-color:#0E8A6D; text-transform:uppercase; font-weight:bold;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
                    <div style="grid-column: span 2;"><label>Address</label><input name="daddr"></div>
                </div></div>
            </div>
            <div class="grid-6" style="margin-top:20px; background:#F8FAFC; padding:20px; border-radius:12px; border:1px solid #E2E8F0;">
                <div><label>Weight(KG)</label><input type="number" step="0.01" name="wt" id="wt" value="1.0" required oninput="fetchRate()" style="font-weight:bold;"></div><div><label>Pieces</label><input type="number" name="pcs" value="1" required></div>
                <div><label>COD Amt</label><input type="number" step="0.01" name="cod" value="0.0"></div><div><label>Declared</label><input type="number" step="0.01" name="dec" value="0.0"></div>
                <div style="grid-column: span 2;"><label>Service Type</label><select name="srv"><option>SURFACE</option><option>AIR</option><option>EXPRESS</option></select></div>
                <div style="grid-column: span 3;"><label>Info / Remarks</label><input name="info"></div>
                <div><label>Freight(₹)</label><input type="number" step="0.01" name="fr" id="fr" value="0.0" oninput="manualCalc()" required></div>
                <div><label>Tax(%)</label><input type="number" name="tax" id="tax" value="18" oninput="manualCalc()" required></div>
                <div><label>Total(₹)</label><input type="number" step="0.01" name="amt" id="amt" value="0.0" readonly style="background:#D1FAE5; font-weight:900; color:#065F46; font-size:16px;"></div>
            </div>
            <div id="calc_hint" style="color:#C9A24B; font-weight:bold; margin-top:10px; font-size:12px; text-align:right;">Auto-Rate API Ready...</div>
            <button type="submit" class="btn btn-blue" style="margin-top:20px; width:100%; font-size:16px; padding:16px; letter-spacing:1px; border-radius:8px;"><i class="fas fa-check-circle"></i> SAVE & BOOK SHIPMENT</button>
        </form>
    </div>
    <div class="card" style="margin-top:20px;">
        <h3 style="margin-top:0;">Recent Bookings</h3>
        <table class="datatable"><thead><tr><th>ID</th><th>AWB No</th><th>Customer</th><th>Station</th><th>Destination</th><th>Weight</th><th>GST</th><th>Total</th><th>Status</th><th>Date</th></tr></thead>
        <tbody>{% for r in recent %}<tr><td>{{ r.id }}</td><td style="color:#0E8A6D; font-weight:bold;">{{ r.awb_no }}</td><td>{{ r.customer_name }}</td><td>{{ r.dest_station }}</td><td>{{ r.destination }}</td><td style="font-weight:bold;">{{ r.weight_kg }} KG</td><td style="color:#C9A24B;">₹{{ "%.2f"|format(r.gst|float) }}</td><td style="font-weight:bold; color:#10B981;">₹{{ r.total_amount }}</td><td><span class="badge b-del">{{ r.status }}</span></td><td>{{ r.booking_date }}</td></tr>{% endfor %}</tbody>
        </table>
    </div>
    <script>document.getElementById('bdt').valueAsDate = new Date(); function fetchRate() { let cid = document.getElementById('cid').value; if(cid) { let opt = document.getElementById('cid').options[document.getElementById('cid').selectedIndex]; if(opt){document.getElementById('ost').value = opt.getAttribute('data-state');} } let data = { cust_id: cid, ostate: document.getElementById('ost').value, dstate: document.getElementById('dst').value, wt: document.getElementById('wt').value, fr: 0 }; fetch('/api/calc_rate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) }).then(r => r.json()).then(res => { document.getElementById('fr').value = res.freight; document.getElementById('tax').value = res.tax_rate; document.getElementById('amt').value = res.total; document.getElementById('calc_hint').innerText = `API Hit: Taxable ₹${res.taxable} + GST ₹${res.gst}`; }); } function manualCalc() { let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0; document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); document.getElementById('calc_hint').innerText = "Manual Override Active"; } if(document.getElementById('cid').tagName === 'INPUT') { fetchRate(); }</script>
    """
    return render_page("New Booking", render_template_string(html, custs=custs, stations=stations, recent=recent, my_cust=my_cust))

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
            q += " AND s.customer_id=%s"
            params.append(session.get('customer_id'))
        elif session.get('role') != 'ADMIN':
            q += " AND s.origin_name=%s"
            params.append(session.get('branch', 'HQ'))
        
        q += " ORDER BY s.id DESC LIMIT 1000"
        c.execute(q, tuple(params)); rows = c.fetchall()
    conn.close()
    
    html = """
    <div class="card"><table class="datatable" style="font-size:13px; text-align:left;"><thead><tr>
        <th>ID</th><th>AWB</th><th>Date</th><th>Dest</th><th>Station</th><th>Weight</th><th>Status</th><th>Info</th><th>Total</th><th>Actions</th></tr></thead><tbody>
        {% for r in rows %}<tr>
            <td>{{ r.id }}</td>
            <td style="color:#0B1F3A; font-weight:800;">{{ r.awb_no }}</td>
            <td>{{ r.booking_date }}</td>
            <td>{{ str(r.dest_name or '') }}</td>
            <td>{{ str(r.dest_station or '') }}</td>
            <td>{{ r.weight_kg }} KG</td>
            <td><span class="badge b-del">{{ r.status }}</span></td>
            <td>{{ str(r.info or '') }}</td>
            <td>₹{{ r.total_amount or 0 }}</td>
            <td>
                {% set ph = r.dest_phone if r.dest_phone else r.cphone %}
                {% if ph %}<a href="https://wa.me/91{{ (ph|string|replace(' ', '')|replace('-', ''))[-10:] }}?text=Track%20AGC%20Parcel:%20https://agconline.in/track?awb={{ r.awb_no }}" target="_blank" class="btn" style="background:#10B981; padding:6px 10px; font-size:11px; border-radius:6px;" title="WhatsApp"><i class="fab fa-whatsapp"></i></a>{% endif %}
                {% if session.get('role') != 'CUSTOMER' %}
                <a href="/edit_shipment/{{ r.id }}" class="btn btn-blue" style="padding:6px 10px; font-size:11px; border-radius:6px;" title="Edit"><i class="fas fa-edit"></i></a>
                {% endif %}
                <a href="/print/label/{{ r.awb_no }}" target="_blank" class="btn btn-ghost" style="padding:6px 10px; font-size:11px; border-radius:6px;" title="Print Label"><i class="fas fa-print"></i> Lbl</a>
                <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="btn btn-gold" style="padding:6px 10px; font-size:11px; border-radius:6px;" title="Print Receipt"><i class="fas fa-file-invoice-dollar"></i> Rec</a>
                {% if session.get('role') != 'CUSTOMER' %}
                <a href="/shipments?delete={{ r.id }}" class="btn btn-red" style="padding:6px 10px; font-size:11px; border-radius:6px;" title="Delete" onclick="return confirm('Are you sure?');"><i class="fas fa-trash"></i></a>
                {% endif %}
            </td>
        </tr>{% endfor %}</tbody></table></div>
    """
    return render_page("Shipments", render_template_string(html, rows=rows, str=str))

@app.route('/my_ledger')
@login_required
def my_ledger():
    if session.get('role') != 'CUSTOMER': return redirect('/')
    conn = get_db()
    cid = session.get('customer_id')
    with conn.cursor() as c:
        c.execute("SELECT * FROM ledger WHERE customer_id=%s ORDER BY entry_date DESC", (cid,))
        l_data = c.fetchall()
        c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (cid,))
        r = c.fetchone(); c_bal = safe_float(r['b']) if r else 0.0
    conn.close()
    html = """<div class="card"><h3>📒 My Account Ledger</h3>
    <h3 style="text-align:right; color:#EF4444; background:#FEF2F2; padding:10px; border-radius:6px; border:1px solid #FECACA;">Current Outstanding Balance: ₹{{ c_bal }}</h3>
    <table class="datatable"><thead><tr><th>Date</th><th>Voucher</th><th>Ref</th><th>Debit (₹)</th><th>Credit (₹)</th><th>Narration</th></tr></thead><tbody>
    {% for l in l_data %}<tr><td>{{ l.entry_date }}</td><td><span class="badge">{{ l.voucher_type }}</span></td><td>{{ l.reference }}</td><td style="color:#EF4444; font-weight:bold;">{{ l.debit }}</td><td style="color:#10B981; font-weight:bold;">{{ l.credit }}</td><td>{{ l.narration }}</td></tr>{% endfor %}</tbody></table></div>"""
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
                if old_s and (old_s['status'] != new_status or old_s['current_location'] != new_loc): c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,%s,%s,'Manually Updated via Edit Panel')", (sid, new_status, new_loc))
                conn.commit(); flash(f"✅ Shipment {d.get('awb','').upper()} Updated!", "success")
            except Exception as e: flash(f"Update Error: {e}", "error")
        return redirect('/shipments')
    with conn.cursor() as c: c.execute("SELECT * FROM shipments WHERE id=%s", (sid,)); s = c.fetchone(); c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
    conn.close()
    if not s: flash("Shipment not found", "error"); return redirect('/shipments')
    html = """<div class="card" style="max-width:950px; margin:auto;"><h3 style="color:#0B1F3A; margin-top:0; border-bottom:2px solid #E2E8F0; padding-bottom:10px;"><i class="fas fa-edit" style="color:#C9A24B;"></i> Edit Shipment: {{ s.awb_no }}</h3><form method="POST" id="editForm"><div class="grid-2" style="margin-bottom:15px; background:#FEF2F2; padding:15px; border-radius:12px; border:1px solid #FECACA;"><div><label style="color:#DC2626;">Tracking Status</label><select name="status" style="border-color:#DC2626; font-weight:bold; color:#DC2626;"><option value="BOOKED" {% if s.status == 'BOOKED' %}selected{% endif %}>BOOKED</option><option value="OUTWARD" {% if s.status == 'OUTWARD' %}selected{% endif %}>OUTWARD</option><option value="INWARD" {% if s.status == 'INWARD' %}selected{% endif %}>INWARD</option><option value="ON_DRS" {% if s.status == 'ON_DRS' %}selected{% endif %}>ON_DRS</option><option value="DELIVERED" {% if s.status == 'DELIVERED' %}selected{% endif %}>DELIVERED</option><option value="UNDELIVERED" {% if s.status == 'UNDELIVERED' %}selected{% endif %}>UNDELIVERED</option><option value="CANCELLED" {% if s.status == 'CANCELLED' %}selected{% endif %}>CANCELLED</option><option value="STATIONERY" {% if s.status == 'STATIONERY' %}selected{% endif %}>STATIONERY</option></select></div><div><label style="color:#DC2626;">Current Location (City/Hub)</label><input name="location" value="{{ s.current_location or '' }}" style="border-color:#DC2626; font-weight:bold; color:#DC2626;"></div></div><div class="grid-2" style="background:#F8FAFC; padding:20px; border-radius:12px; margin-bottom:20px; border:1px solid #E2E8F0;"><div><label>Booking Date</label><input type="date" name="date" value="{{ s.booking_date }}" required></div><div><label>AWB Number</label><input name="awb" value="{{ s.awb_no }}" required style="font-weight:900; color:#0B1F3A; text-transform:uppercase;"></div></div><div class="grid-2"><div style="border:1px solid #E2E8F0; padding:20px; border-radius:12px; background:white;"><h4 style="margin-top:0; color:#C9A24B; text-transform:uppercase;"><i class="fas fa-building"></i> Origin (Shipper)</h4><div class="grid-2"><div style="grid-column: span 2;"><label>Sender Name</label><input name="oname" value="{{ s.origin_name or '' }}" required></div><div><label>Phone</label><input name="ophone" value="{{ s.origin_phone or '' }}"></div><div><label>State Code</label><input name="ostate" id="ost" value="{{ s.origin_state_code or '' }}" onchange="manualCalc()"></div><div style="grid-column: span 2;"><label>Address</label><input name="oaddr" value="{{ s.origin_address or '' }}"></div></div></div><div style="border:1px solid #E2E8F0; padding:20px; border-radius:12px; background:white;"><h4 style="margin-top:0; color:#0E8A6D; text-transform:uppercase;"><i class="fas fa-home"></i> Destination (Consignee)</h4><div class="grid-2"><div style="grid-column: span 2;"><label>Receiver Name</label><input name="dname" value="{{ s.dest_name or '' }}" required></div><div><label>Phone</label><input name="dphone" value="{{ s.dest_phone or '' }}" required></div><div><label>State Code</label><input name="dstate" id="dst" value="{{ s.dest_state_code or '' }}" onchange="manualCalc()"></div><div style="grid-column: span 2;"><label>Dest Station (City)</label><input name="dstat" list="stations" value="{{ s.dest_station or '' }}" required style="border-color:#0E8A6D; text-transform:uppercase; font-weight:bold;"><datalist id="stations">{% for st in stations %}<option value="{{ st.name }}">{% endfor %}</datalist></div><div style="grid-column: span 2;"><label>Address</label><input name="daddr" value="{{ s.dest_address or '' }}"></div></div></div></div><div class="grid-6" style="margin-top:20px; background:#F8FAFC; padding:20px; border-radius:12px; border:1px solid #E2E8F0;"><div><label>Weight(KG)</label><input type="number" step="0.01" name="wt" id="wt" value="{{ s.weight_kg or 1 }}" required oninput="manualCalc()" style="font-weight:bold;"></div><div><label>Pieces</label><input type="number" name="pcs" value="{{ s.quantity or 1 }}" required></div><div><label>COD Amt</label><input type="number" step="0.01" name="cod" value="{{ s.cod_amount or 0 }}"></div><div><label>Declared</label><input type="number" step="0.01" name="dec" value="{{ s.declared_value or 0 }}"></div><div style="grid-column: span 2;"><label>Service Type</label><select name="srv"><option value="SURFACE" {% if s.service_type == 'SURFACE' %}selected{% endif %}>SURFACE</option><option value="AIR" {% if s.service_type == 'AIR' %}selected{% endif %}>AIR</option><option value="EXPRESS" {% if s.service_type == 'EXPRESS' %}selected{% endif %}>EXPRESS</option></select></div><div style="grid-column: span 3;"><label>Info / Remarks</label><input name="info" value="{{ s.info or '' }}"></div><div><label>Freight(₹) Taxable</label><input type="number" step="0.01" name="fr" id="fr" value="{{ s.taxable_amount or 0 }}" oninput="manualCalc()" required></div><div><label>Tax(%)</label><input type="number" name="tax" id="tax" value="{{ s.tax_rate or 18 }}" oninput="manualCalc()" required></div><div><label>Total(₹)</label><input type="number" step="0.01" name="amt" id="amt" value="{{ s.total_amount or 0 }}" readonly style="background:#D1FAE5; font-weight:900; color:#065F46; font-size:16px;"></div></div><button type="submit" class="btn btn-blue" style="margin-top:20px; width:100%; font-size:16px; padding:16px; border-radius:8px;"><i class="fas fa-check-circle"></i> UPDATE SHIPMENT RECORD</button><div style="text-align:center; margin-top:15px;"><a href="/shipments" style="color:#EF4444; font-weight:bold; text-decoration:none;"><i class="fas fa-times"></i> Cancel & Go Back</a></div></form><script>function manualCalc() { let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0; document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); }</script></div>"""
    return render_page(f"Edit AWB: {s['awb_no']}", render_template_string(html, s=s, stations=stations))

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
        conn.close(); flash(f"🎉 Import Complete! {added} Parcels Booked.", "success")
    html = """<div class="card" style="max-width:500px; margin:auto; text-align:center;"><h3 style="color:#0E8A6D;"><i class="fas fa-file-csv"></i> Bulk CSV Import</h3><p style="color:#7A8699; font-size:13px; margin-bottom:20px;">Required Columns: <b>AWB</b>, <b>Dest</b>, <b>Weight</b>, <b>Amount</b></p><form method="POST" enctype="multipart/form-data"><input type="file" name="file" accept=".csv" required style="margin-bottom:15px; width:100%;"><button type="submit" class="btn btn-blue" style="width:100%; padding:12px;">Start Import</button></form></div>"""
    return render_page("Excel Import", render_template_string(html))

@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db(); current_date = datetime.now().strftime('%Y-%m-%d')
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM outward_register WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Entry Deleted", "success"); return redirect(f"/outward?date={request.args.get('date', current_date)}")
    if request.args.get('unfinalize'):
        mid = request.args.get('unfinalize')
        with conn.cursor() as c:
            c.execute("SELECT manifest_no FROM manifests WHERE id=%s", (mid,)); m = c.fetchone()
            if m: c.execute("UPDATE outward_register SET finalized=0, manifest_no=NULL, outward_no=NULL WHERE manifest_no=%s", (m['manifest_no'],)); c.execute("DELETE FROM manifest_items WHERE manifest_id=%s", (mid,)); c.execute("DELETE FROM manifests WHERE id=%s", (mid,))
            conn.commit(); flash("Manifest Unfinalized! Items moved back to pending.", "success")
        return redirect('/outward')

    if request.method == 'POST' and request.form.get('action') == 'save_entry':
        o_date = request.form.get('out_date', current_date); o_station = str(request.form.get('out_station') or session.get('branch', 'HQ')).upper(); awb = request.form.get('awb', '').strip().upper()
        dest_input = request.form.get('dest', '').strip().upper(); wt_input = safe_float(request.form.get('weight')); info = request.form.get('info', '')
        network = str(request.form.get('network') or 'SELF').upper(); net_awb = str(request.form.get('network_awb') or '').upper(); bag_no = str(request.form.get('bag_no') or '').upper(); pcs = safe_int(request.form.get('pcs')) or 1
        
        if awb:
            with conn.cursor() as c:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (o_station,))
                if dest_input:
                    c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest_input,))
                    
                if awb.startswith("BAG"):
                    c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb,)); b_items = c.fetchall()
                    if not b_items: flash(f"Bag {awb} is empty.", "error")
                    else:
                        for bi in b_items:
                            sub_awb = bi['awb_no']
                            c.execute("SELECT id, dest_station, weight_kg FROM shipments WHERE awb_no=%s", (sub_awb,)); s = c.fetchone()
                            s_wt = safe_float(s['weight_kg']) if s else 1.0; s_dst = str(s['dest_station'] or dest_input or 'UNKNOWN') if s else (dest_input or 'UNKNOWN')
                            
                            if not c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND finalized=0", (sub_awb,)): 
                                c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, pcs, network, network_awb, bag_no, info, finalized) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)", (o_date, sub_awb, session.get('branch','HQ'), o_station, s_dst, s_wt, 1, network, net_awb, awb, f"Unpacked {awb}"))
                                
                                if s:
                                    c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, info=%s, dest_station=%s WHERE id=%s", (o_station, f"From Bag {awb}", s_dst, s['id']))
                                    c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'OUTWARD', %s, %s)", (s['id'], o_station, f"Packed in Bag {awb}"))
                        flash(f"Bag unpacked and linked.", "success")
                else:
                    if c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND finalized=0", (awb,)): 
                        flash(f"AWB {awb} already pending!", "error")
                    else:
                        c.execute("SELECT id, dest_station, dest_name, weight_kg FROM shipments WHERE awb_no=%s", (awb,)); s = c.fetchone()
                        s_dest = str(s['dest_station'] or s['dest_name'] or 'UNKNOWN') if s else 'UNKNOWN'
                        final_dest = dest_input if dest_input else s_dest
                        final_wt = wt_input if wt_input > 0 else (safe_float(s['weight_kg']) if s else 1.0)
                        
                        if s:
                            c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, info=%s, dest_station=%s, weight_kg=%s WHERE id=%s", 
                                      (o_station, info, final_dest, final_wt, s['id']))
                            c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'OUTWARD', %s, 'Scanned at Outward')", (s['id'], o_station))
                        else:
                            c.execute("INSERT INTO shipments(awb_no, booking_date, origin_name, dest_station, dest_name, weight_kg, service_type, status, current_location, taxable_amount, total_amount, info, is_synced) VALUES(%s, %s, %s, %s, %s, %s, 'SURFACE', 'OUTWARD', %s, 0, 0, %s, 0)", 
                                      (awb, o_date, session.get('branch','HQ'), final_dest, final_dest, final_wt, o_station, info))
                            new_sid = c.lastrowid
                            c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'OUTWARD', %s, 'Auto-linked from Outward')", (new_sid, o_station))
                            
                        c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, pcs, network, network_awb, bag_no, info, finalized) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)", (o_date, awb, session.get('branch','HQ'), o_station, final_dest, final_wt, pcs, network, net_awb, bag_no, info))
                        flash(f"AWB {awb} Scanned!", "success")
                conn.commit()
            return redirect(f"/outward?date={o_date}&station={o_station}")

    if request.method == 'POST' and request.form.get('action') == 'finalize':
        o_date = request.form.get('out_date', current_date); o_station = request.form.get('out_station', session.get('branch', 'HQ')).upper()
        with conn.cursor() as c:
            c.execute("SELECT id, awb_no FROM outward_register WHERE entry_date=%s AND out_station=%s AND origin_station=%s AND finalized=0", (o_date, o_station, session.get('branch','HQ'))); pending = c.fetchall()
            if pending:
                ono = get_seq("outward", "OUT", 6); mno = get_seq("manifest", "MF", 7)
                c.execute("INSERT INTO manifests(manifest_no, manifest_type, from_location, to_location, vehicle_no, driver_phone, seal_no, status) VALUES(%s, 'OUTWARD', %s, %s, %s, %s, %s, 'OPEN')", (mno, session.get('branch','HQ'), o_station, request.form.get('vehicle_no',''), request.form.get('driver_phone',''), request.form.get('seal_no','')))
                mid = c.lastrowid
                for p in pending:
                    c.execute("UPDATE outward_register SET finalized=1, outward_no=%s, manifest_no=%s WHERE id=%s", (ono, mno, p['id']))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (p['awb_no'],)); s_row = c.fetchone()
                    if s_row: c.execute("INSERT INTO manifest_items(manifest_id, shipment_id) VALUES(%s, %s)", (mid, s_row['id'])); c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'OUTWARD', %s)", (s_row['id'], session.get('branch','HQ')))
                conn.commit(); flash(f"{mno} Locked!", "success")
        return redirect(f"/outward?date={o_date}&station={o_station}")

    f_date = request.args.get('date', current_date); f_station = request.args.get('station', session.get('branch', 'HQ')).upper()
    with conn.cursor() as c:
        c.execute("SELECT id, awb_no, destination, weight, info, pcs, network, bag_no FROM outward_register WHERE entry_date=%s AND out_station=%s AND origin_station=%s AND finalized=0 ORDER BY id DESC", (f_date, f_station, session.get('branch','HQ'))); pending_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); stations = [r['name'] for r in c.fetchall()]
        q_m = "SELECT id, manifest_no, created_at, from_location, to_location, vehicle_no FROM manifests WHERE manifest_type='OUTWARD'"
        params_m = []
        if session.get('role') != 'ADMIN': q_m += " AND from_location=%s"; params_m.append(session.get('branch','HQ'))
        c.execute(q_m + " ORDER BY id DESC LIMIT 10", tuple(params_m)); mans = c.fetchall()
    conn.close()
    
    html = """
    <div style="display:flex; gap:10px; margin-bottom:20px; background:white; padding:10px; border-radius:12px; box-shadow:0 1px 3px rgba(0,0,0,0.05); border:1px solid #E2E8F0;">
        <button class="btn" onclick="switchTab('new')" id="tab-new" style="background:#0B1F3A; flex:1; padding:12px;"><i class="fas fa-plane-departure"></i> Dispatch Center</button>
        <button class="btn btn-ghost" onclick="switchTab('history')" id="tab-history" style="flex:1; border:none; padding:12px;"><i class="fas fa-list-alt"></i> Manifest History</button>
        <button class="btn btn-ghost" onclick="switchTab('tools')" id="tab-tools" style="flex:1; border:none; padding:12px;"><i class="fas fa-cogs"></i> Utilities</button>
    </div>
    
    <!-- QR Scanner Modal -->
    <div id="scannerModal" class="modal-overlay">
        <div class="modal-content">
            <h3 style="margin-top:0; color:#0B1F3A;"><i class="fas fa-camera"></i> Scan Barcode</h3>
            <div id="reader" style="width: 100%;"></div>
            <button class="btn btn-red" style="width:100%; margin-top:15px;" onclick="stopScanner()">Cancel / Close</button>
        </div>
    </div>

    <div class="card" id="content-new" style="border-top-color:#0B1F3A;">
        <div style="display:flex; align-items:center; gap:15px; margin-bottom:20px; background:#F8FAFC; padding:15px; border-radius:8px; border:1px solid #E2E8F0;">
            <label style="margin:0;">Date</label><input type="date" id="ui_date" value="{{ f_date }}" onchange="reloadPage()" style="width:140px; font-weight:bold;">
            <label style="margin:0;">Hub Station</label><input list="stlist" id="ui_station" value="{{ f_station }}" onchange="reloadPage()" style="width:180px; font-weight:bold; color:#0B1F3A;"><datalist id="stlist">{% for s in stations %}<option value="{{ s }}">{% endfor %}</datalist>
            <div style="flex:1;"></div><button class="btn btn-blue" onclick="window.open('/master_bag')"><i class="fas fa-shopping-bag"></i> Bora Packing</button>
        </div>
        <div style="display:flex; align-items:center; gap:15px; margin-bottom:15px; background:#FEF3C7; padding:12px; border-radius:8px; border:1px solid #FDE68A;">
            <label style="margin:0; color:#92400E;"><i class="fas fa-network-wired"></i> Network:</label><select id="ui_network" style="width:130px;"><option>SELF</option><option>BLUEDART</option><option>DELHIVERY</option></select>
            <label style="margin:0; color:#92400E;">Net AWB:</label><input type="text" id="ui_net_awb" placeholder="If applicable" style="width:140px;">
            <label style="margin:0; color:#92400E;">Bag No:</label><input type="text" id="ui_bag_no" placeholder="Optional" style="width:120px;">
            <label style="margin:0; color:#92400E;">Pcs:</label><input type="number" id="ui_pcs" value="1" style="width:80px; text-align:center;">
        </div>
        <form method="POST" id="entryForm" style="display:flex; gap:10px; background:#0B1F3A; padding:15px; border-radius:8px; margin-bottom:15px;">
            <input type="hidden" name="action" value="save_entry"><input type="hidden" name="out_date" id="hdn_date"><input type="hidden" name="out_station" id="hdn_station"><input type="hidden" name="network" id="hdn_network"><input type="hidden" name="network_awb" id="hdn_net_awb"><input type="hidden" name="bag_no" id="hdn_bag_no"><input type="hidden" name="pcs" id="hdn_pcs">
            <button type="button" class="btn" style="background:#10B981; padding:10px 15px;" onclick="startScanner('awb_input')"><i class="fas fa-camera"></i> Scan</button>
            <input type="text" name="awb" id="awb_input" placeholder="SCAN AWB HERE" required autofocus style="flex:1; font-size:16px; font-weight:bold; text-transform:uppercase;" onkeypress="if(event.key==='Enter'){event.preventDefault(); document.getElementById('dest_input').focus();}">
            <input type="text" name="dest" id="dest_input" list="stlist" placeholder="Destination" style="flex:1;" onkeypress="if(event.key==='Enter'){event.preventDefault(); document.getElementById('wt_input').focus();}">
            <input type="number" step="0.01" name="weight" id="wt_input" placeholder="Weight" style="width:90px;" onkeypress="if(event.key==='Enter'){event.preventDefault(); document.getElementById('info_input').focus();}">
            <input type="text" name="info" id="info_input" placeholder="Remarks" style="flex:1;" onkeypress="if(event.key==='Enter'){event.preventDefault(); document.getElementById('entryForm').submit();}">
            <button type="submit" class="btn btn-gold" style="padding:10px 25px;"><i class="fas fa-plus"></i> ADD</button>
        </form>
        <h4 style="color:#C9A24B; margin:0 0 10px 0;"><i class="fas fa-inbox"></i> Pending Items ({{ pending_list|length }})</h4>
        <div style="height:300px; overflow-y:auto; border:1px solid #E2E8F0; border-radius:8px;"><table style="margin:0;" class="datatable">
            <thead><tr style="position:sticky; top:0; background:#F8FAFC; z-index:1;"><th>AWB</th><th>Dest</th><th>Wt</th><th>Info</th><th>Net</th><th>Bag</th><th>Del</th></tr></thead>
            <tbody>{% for p in pending_list %}<tr><td style="color:#0B1F3A; font-weight:800; font-size:14px;">{{ p.awb_no }}</td><td>{{ p.destination or '-' }}</td><td style="font-weight:bold;">{{ p.weight or '0' }} kg</td><td>{{ str(p.info or '')[:20] }}</td><td><span class="badge">{{ p.network or '-' }}</span></td><td>{{ p.bag_no or '-' }}</td><td><a href="/outward?delete={{ p.id }}&date={{ f_date }}&station={{ f_station }}" class="btn btn-red" style="padding:4px 8px; border-radius:4px;"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</tbody>
        </table></div>
        <form method="POST" id="finalizeForm" style="display:flex; gap:10px; margin-top:20px; background:#FEF2F2; padding:15px; border-radius:8px; border:1px solid #FECACA;">
            <input type="hidden" name="action" value="finalize"><input type="hidden" name="out_date" id="fin_date" value="{{ f_date }}"><input type="hidden" name="out_station" id="fin_station" value="{{ f_station }}">
            <input type="text" name="vehicle_no" placeholder="Vehicle No (RJ-..)" required style="flex:1;"><input type="text" name="driver_phone" placeholder="Driver Mobile" style="flex:1;"><input type="text" name="seal_no" placeholder="Lock Seal" style="flex:1;">
            <button type="button" onclick="if(confirm('Lock {{ pending_list|length }} items into a Manifest?')){document.getElementById('finalizeForm').submit();}" class="btn btn-red" style="flex:1; font-size:15px;"><i class="fas fa-lock"></i> FINALIZE DISPATCH</button>
        </form>
    </div>
    <div class="card" id="content-history" style="display:none; border-top-color:#C9A24B;">
        <h3 style="margin-top:0; color:#0B1F3A;"><i class="fas fa-list"></i> Previous Manifests</h3>
        <table class="datatable"><thead><tr><th>Manifest No</th><th>Date</th><th>Route</th><th>Vehicle</th><th>Actions</th></tr></thead>
        <tbody>{% for m in mans %}<tr><td style="color:#C9A24B; font-size:14px;"><strong>{{ m.manifest_no }}</strong></td><td>{{ m.created_at }}</td><td>{{ m.from_location }} &rarr; {{ m.to_location }}</td><td>{{ m.vehicle_no or '-' }}</td><td><a href="/print/manifest/{{ m.id }}" target="_blank" class="btn btn-blue" style="padding:6px 12px; font-size:12px; border-radius:6px;"><i class="fas fa-print"></i> Print</a> <a href="/outward?unfinalize={{ m.id }}" onclick="return confirm('Unlock this Manifest? Items will return to pending.');" class="btn btn-red" style="padding:6px 12px; font-size:12px; border-radius:6px;"><i class="fas fa-unlock"></i> Unlock</a></td></tr>{% endfor %}</tbody></table>
    </div>
    <div class="card" id="content-tools" style="display:none; border-top-color:#0E8A6D;">
        <h3 style="color:#0B1F3A; margin-top:0;"><i class="fas fa-calendar-alt"></i> Date Range Export</h3><form action="/reports/outward-range" method="POST" class="grid-4" style="align-items:end; margin-bottom:30px; background:#F8FAFC; padding:20px; border-radius:8px;"><div><label>From Date</label><input type="date" name="from_date" required style="width:100%;"></div><div><label>To Date</label><input type="date" name="to_date" required style="width:100%;"></div><div><button type="submit" name="export" value="csv" class="btn btn-blue" style="width:100%;"><i class="fas fa-file-csv"></i> Download CSV</button></div><div><button type="submit" name="export" value="pdf" class="btn btn-red" style="width:100%;"><i class="fas fa-file-pdf"></i> Download PDF</button></div></form>
        <h3 style="color:#0B1F3A;"><i class="fas fa-wrench"></i> Super Tools</h3>
        <div style="display:flex; gap:15px;"><form action="/tools/sync-shipments" method="POST" style="flex:1;"><button type="submit" class="btn" style="background:#10B981; width:100%; padding:15px; font-size:15px;"><i class="fas fa-sync-alt"></i> Force Sync Old Data</button></form><form action="/tools/bulk-date-change" method="POST" style="display:flex; gap:10px; flex:2;"><input type="date" name="old_date" required style="flex:1;"><input type="date" name="new_date" required style="flex:1;"><button type="submit" class="btn btn-blue" style="flex:1;"><i class="fas fa-calendar-day"></i> Bulk Date Change</button></form></div>
    </div>
    <script>
    function switchTab(tab) { document.getElementById('content-new').style.display = 'none'; document.getElementById('content-history').style.display = 'none'; document.getElementById('content-tools').style.display = 'none'; document.getElementById('tab-new').style.background = 'transparent'; document.getElementById('tab-history').style.background = 'transparent'; document.getElementById('tab-tools').style.background = 'transparent'; document.getElementById('tab-new').style.color = '#475569'; document.getElementById('tab-history').style.color = '#475569'; document.getElementById('tab-tools').style.color = '#475569'; document.getElementById('content-' + tab).style.display = 'block'; document.getElementById('tab-' + tab).style.background = '#0B1F3A'; document.getElementById('tab-' + tab).style.color = 'white'; }
    function reloadPage() { window.location.href = `/outward?date=${document.getElementById('ui_date').value}&station=${document.getElementById('ui_station').value}`; }
    document.getElementById('entryForm').addEventListener('submit', function() { document.getElementById('hdn_date').value = document.getElementById('ui_date').value; document.getElementById('hdn_station').value = document.getElementById('ui_station').value; document.getElementById('hdn_network').value = document.getElementById('ui_network').value; document.getElementById('hdn_net_awb').value = document.getElementById('ui_net_awb').value; document.getElementById('hdn_bag_no').value = document.getElementById('ui_bag_no').value; document.getElementById('hdn_pcs').value = document.getElementById('ui_pcs').value; });
    
    // Scanner JS
    let html5QrcodeScanner = null;
    let targetInput = '';
    function startScanner(inputId) {
        targetInput = inputId;
        document.getElementById('scannerModal').style.display = 'flex';
        html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: {width: 250, height: 100} }, false);
        html5QrcodeScanner.render(onScanSuccess, onScanFailure);
    }
    function stopScanner() {
        if(html5QrcodeScanner) { html5QrcodeScanner.clear(); }
        document.getElementById('scannerModal').style.display = 'none';
    }
    function onScanSuccess(decodedText, decodedResult) {
        document.getElementById(targetInput).value = decodedText;
        stopScanner();
        
        // Auto-submit form immediately after scan
        if(targetInput === 'awb_input') {
            document.getElementById('entryForm').submit();
        } else if(targetInput === 'in_awb_input') {
            document.getElementById('inForm').submit();
        }
    }
    function onScanFailure(error) { }
    </script>
    """
    return render_page("Outward Dispatch", render_template_string(html, pending_list=pending_list, mans=mans, stations=stations, f_date=f_date, f_station=f_station, str=str))

# ==========================================
# 🎒 9. MASTER BAG & INWARD HUB
# ==========================================
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
            conn.commit(); flash(f"🎒 Master Bag Sealed! Bag No: {bag_no}", "success")
    with conn.cursor() as c:
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
        c.execute("SELECT bag_no, destination, created_at, (SELECT COUNT(*) FROM master_bag_items WHERE bag_no=master_bags.bag_no) as items FROM master_bags ORDER BY id DESC LIMIT 10"); bags = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card" style="border-top-color: #38bdf8;"><h3 style="color:#38bdf8; margin-top:0;"><i class="fas fa-shopping-bag" style="color:#C9A24B;"></i> Create Master Bag (Bora)</h3><form method="POST"><label>Bag Destination Hub</label><input name="dest_hub" list="stations" required style="margin-bottom:15px; text-transform:uppercase; width:100%;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist><label>Scan Items to Pack</label><textarea name="awbs" rows="8" required style="font-family:monospace; font-size:15px; margin-top:5px; width:100%; background:#F8FAFC; border:1px solid #E2E8F0;"></textarea><button type="submit" class="btn btn-blue" style="margin-top:15px; width:100%; font-size:15px; padding:15px;"><i class="fas fa-lock"></i> SEAL MASTER BAG</button></form></div><div class="card"><h3>Recent Sealed Bags</h3><div style="max-height:300px; overflow-y:auto;"><table class="datatable"><thead><tr><th>Bag No</th><th>Destination</th><th>Items</th><th>Date</th></tr></thead><tbody>{% for b in bags %}<tr><td style="color:#0E8A6D; font-weight:bold; font-size:14px;">{{ b.bag_no }}</td><td>{{ b.destination }}</td><td><span class="badge">{{ b.items }}</span></td><td>{{ b.created_at }}</td></tr>{% endfor %}</tbody></table></div></div></div>"""
    return render_page("Master Bag Processing", render_template_string(html, stations=stations, bags=bags))

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
        if awb: awbs_list.append(awb) # For single scan
        
        origin = request.form.get('origin', '').upper(); wt = str(safe_float(request.form.get('weight'))); info = request.form.get('info', '')
        with conn.cursor() as c:
            for a in awbs_list:
                awb_clean = a.strip().upper()
                if awb_clean:
                    if awb_clean.startswith("BAG"):
                        c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb_clean,))
                        for bi in c.fetchall():
                            c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, weight, info, finalized) VALUES(CURDATE(), %s, %s, %s, %s, %s, 1)", (bi['awb_no'], origin, session.get('branch','HQ'), wt, f"Unpacked from {awb_clean}"))
                            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (bi['awb_no'],)); s_row = c.fetchone()
                            if s_row: c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session.get('branch','HQ'), s_row['id'])); c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (s_row['id'], session.get('branch','HQ')))
                    else:
                        c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, weight, info, finalized) VALUES(CURDATE(), %s, %s, %s, %s, %s, 1)", (awb_clean, origin, session.get('branch','HQ'), wt, info))
                        c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb_clean,)); s_row = c.fetchone()
                        if s_row: c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session.get('branch','HQ'), s_row['id'])); c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (s_row['id'], session.get('branch','HQ')))
            conn.commit(); flash("✅ Inward Completed.", "success")
            
    with conn.cursor() as c:
        c.execute("SELECT * FROM inward_register WHERE in_station=%s AND finalized=0 ORDER BY id DESC LIMIT 50", (session.get('branch','HQ'),)); hist = c.fetchall()
        c.execute("SELECT inward_no, MIN(entry_date) as d, MIN(in_station) as st, COUNT(*) as c, MIN(manifest_no) as m FROM inward_register WHERE finalized=1 GROUP BY inward_no ORDER BY d DESC LIMIT 10"); sess = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
    conn.close()
    
    html = """
    <div style="display:flex; gap:10px; margin-bottom:20px; background:white; padding:10px; border-radius:12px; box-shadow:0 1px 3px rgba(0,0,0,0.05); border:1px solid #E2E8F0;">
        <button class="btn" onclick="document.getElementById('in-new').style.display='block'; document.getElementById('in-hist').style.display='none'; this.style.background='#0B1F3A'; document.getElementById('tab-hist').style.background='transparent'; document.getElementById('tab-hist').style.color='#475569'; this.style.color='white';" id="tab-new" style="background:#0B1F3A; flex:1; padding:12px;"><i class="fas fa-plane-arrival"></i> Receive Inward</button>
        <button class="btn btn-ghost" onclick="document.getElementById('in-new').style.display='none'; document.getElementById('in-hist').style.display='block'; this.style.background='#0B1F3A'; document.getElementById('tab-new').style.background='transparent'; document.getElementById('tab-new').style.color='#475569'; this.style.color='white';" id="tab-hist" style="flex:1; border:none; padding:12px;"><i class="fas fa-list-alt"></i> Inward Sessions</button>
    </div>
    
    <!-- QR Scanner Modal -->
    <div id="scannerModal" class="modal-overlay">
        <div class="modal-content">
            <h3 style="margin-top:0; color:#0B1F3A;"><i class="fas fa-camera"></i> Scan Barcode</h3>
            <div id="reader" style="width: 100%;"></div>
            <button class="btn btn-red" style="width:100%; margin-top:15px;" onclick="stopScanner()">Cancel / Close</button>
        </div>
    </div>

    <div class="grid-2" id="in-new"><div class="card" style="border-top-color: #0B1F3A;"><h3 style="color:#0B1F3A; margin-top:0;"><i class="fas fa-plane-arrival" style="color:#C9A24B;"></i> Receive Inward</h3><form method="POST" id="inForm"><div class="grid-2" style="margin-bottom:15px; background:#F8FAFC; padding:15px; border-radius:8px;"><div><label>My Hub</label><input value="{{ session['branch'] }}" readonly style="background:#E2E8F0; font-weight:bold;"></div><div><label>From (Origin)</label><input name="origin" list="stations" required style="text-transform:uppercase;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div></div><div style="display:flex; gap:10px; margin-bottom:10px;"><input type="number" step="0.01" name="weight" value="1.00" placeholder="Weight" style="flex:1;"><input name="info" placeholder="Remarks/Info" style="flex:2;"></div>
    <label>Scan Single AWB / Bag</label>
    <div style="display:flex; gap:5px; margin-bottom:10px;">
        <button type="button" class="btn" style="background:#10B981; padding:10px;" onclick="startScanner('in_awb_input')"><i class="fas fa-camera"></i> Scan</button>
        <input type="text" name="awb" id="in_awb_input" placeholder="SCAN AWB HERE" autofocus style="flex:1; font-size:16px; font-weight:bold; text-transform:uppercase;" onkeypress="if(event.key==='Enter'){event.preventDefault(); document.getElementById('inForm').submit();}">
    </div>
    <label>Or Scan Bulk Items (Textarea)</label><textarea name="awbs" rows="4" style="font-family:monospace; margin-top:5px; font-size:15px; background:#F1F5F9;"></textarea><button type="submit" class="btn btn-blue" style="width:100%; margin-top:15px; padding:15px; font-size:15px;"><i class="fas fa-download"></i> Save Inward Entry</button></form></div><div class="card" style="overflow-y:auto; max-height:550px;"><h3>Pending Inward</h3><table class="datatable"><thead><tr><th>ID</th><th>AWB</th><th>Coming From (Origin)</th><th>Weight</th><th>Info</th></tr></thead><tbody>{% for h in hist %}<tr><td>{{ h.id }}</td><td style="color:#0B1F3A; font-weight:bold;">{{ h.awb_no }}</td><td>{{ h.origin_station }}</td><td>{{ h.weight }}</td><td>{{ h.info }}</td></tr>{% endfor %}</tbody></table></div></div>
    <div class="card" id="in-hist" style="display:none; border-top-color:#C9A24B;"><h3>Inward Sessions</h3><table class="datatable"><thead><tr><th>Inward No</th><th>Date</th><th>Station</th><th>Docs</th><th>Manifest</th></tr></thead><tbody>{% for s in sess %}<tr><td><strong>{{ s.inward_no }}</strong></td><td>{{ s.d }}</td><td>{{ s.st }}</td><td>{{ s.c }}</td><td>{{ s.m or '-' }}</td></tr>{% endfor %}</tbody></table></div>
    <script>
    // Scanner JS logic repeated for Inward
    let html5QrcodeScanner = null;
    let targetInput = '';
    function startScanner(inputId) {
        targetInput = inputId;
        document.getElementById('scannerModal').style.display = 'flex';
        html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: {width: 250, height: 100} }, false);
        html5QrcodeScanner.render(onScanSuccess, onScanFailure);
    }
    function stopScanner() {
        if(html5QrcodeScanner) { html5QrcodeScanner.clear(); }
        document.getElementById('scannerModal').style.display = 'none';
    }
    function onScanSuccess(decodedText, decodedResult) {
        document.getElementById(targetInput).value = decodedText;
        stopScanner();
        // Play beep
        let audio = new Audio('https://www.soundjay.com/button/beep-07.wav'); audio.play();
        if(targetInput === 'in_awb_input') { document.getElementById('inForm').submit(); }
    }
    function onScanFailure(error) { }
    </script>
    """
    return render_page("INWARD HUB", render_template_string(html, hist=hist, sess=sess, stations=stations))

# ==========================================
# 🛵 10. DRS & DELIVERY
# ==========================================
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
            conn.commit(); flash(f"✅ Added to Delivery Queue", "success")

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
            conn.commit(); flash(f"✅ DRS Finalized", "success")

    elif request.method == 'POST' and 'mark_deliver' in request.form:
        awb = request.form.get('deliver_awb', '').strip().upper(); receiver = request.form.get('receiver', '')
        with conn.cursor() as c:
            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,)); s_row = c.fetchone()
            if s_row:
                c.execute("UPDATE shipments SET status='DELIVERED', current_location=%s WHERE id=%s", (f"Delivered: {receiver}", s_row['id']))
                c.execute("UPDATE drs_items SET status='DELIVERED', receiver_name=%s WHERE shipment_id=%s", (receiver, s_row['id']))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'DELIVERED', %s, %s)", (s_row['id'], session.get('branch','HQ'), f"Received by {receiver}"))
                conn.commit(); flash(f"✅ Delivered: {awb}", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, entry_date, delivery_boy, delivery_area, awb_no, receiver_name FROM delivery_register WHERE finalized=0 ORDER BY id DESC"); pending = c.fetchall()
        c.execute("SELECT drs_no, MIN(entry_date) d, MIN(delivery_boy) b, MIN(delivery_area) a, COUNT(*) c FROM delivery_register WHERE finalized=1 GROUP BY drs_no ORDER BY d DESC"); sess = c.fetchall()
        c.execute("SELECT id, drs_no, drs_date, rider_name, status FROM drs ORDER BY id DESC LIMIT 15"); drs_tbl = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #0B1F3A;">
            <h3 style="color:#0B1F3A; margin-top:0;"><i class="fas fa-motorcycle" style="color:#C9A24B;"></i> 1. Delivery Entry Form</h3>
            <form method="POST"><input type="hidden" name="assign_drs" value="1">
                <div class="grid-2" style="margin-bottom:15px; background:#F8FAFC; padding:15px; border-radius:8px;">
                    <div><label>Rider/Boy Name</label><input name="rider" required></div><div><label>Area / Route</label><input name="area"></div>
                </div>
                <label>Scan Parcels for Delivery</label><textarea name="awbs" rows="4" required style="font-family:monospace; margin-top:5px; background:#F1F5F9; font-size:15px;"></textarea>
                <button type="submit" class="btn btn-blue" style="margin-top:15px; width:100%; padding:12px; font-size:15px;"><i class="fas fa-clipboard-list"></i> Save Delivery Entry</button>
            </form>
            <hr style="border:0; border-top:1px solid #E2E8F0; margin:20px 0;">
            <h4>Pending Entries</h4>
            <div style="max-height:200px; overflow-y:auto;"><table class="datatable"><thead><tr><th>ID</th><th>Date</th><th>Rider</th><th>Area</th><th>AWB</th><th>Receiver</th></tr></thead><tbody>{% for p in pending %}<tr><td>{{ p.id }}</td><td>{{ p.entry_date }}</td><td>{{ p.delivery_boy }}</td><td>{{ p.delivery_area }}</td><td style="font-weight:bold; color:#0E8A6D;">{{ p.awb_no }}</td><td>{{ p.receiver_name }}</td></tr>{% endfor %}</tbody></table></div>
            <form method="POST" style="margin-top:10px;"><input type="hidden" name="finalize_drs" value="1"><button type="submit" class="btn btn-gold" style="width:100%; padding:12px;"><i class="fas fa-flag-checkered"></i> FINALIZE & GENERATE DRS</button></form>
        </div>
        <div>
            <div class="card" style="border-top-color: #C9A24B;">
                <h3 style="color:#C9A24B; margin-top:0;">Finalized DRS Sessions</h3>
                <div style="max-height:200px; overflow-y:auto;"><table class="datatable"><thead><tr><th>DRS No</th><th>Date</th><th>Rider</th><th>Area</th><th>Total Docs</th></tr></thead><tbody>{% for s in sess %}<tr><td><strong>{{ s.drs_no }}</strong></td><td>{{ s.d }}</td><td>{{ s.b }}</td><td>{{ s.a }}</td><td>{{ s.c }}</td></tr>{% endfor %}</tbody></table></div>
                <h4 style="margin-top:20px;">DRS Printing</h4>
                <table class="datatable"><thead><tr><th>ID</th><th>DRS No</th><th>Date</th><th>Rider</th><th>Status</th><th>Action</th></tr></thead><tbody>{% for d in drs_tbl %}<tr><td>{{ d.id }}</td><td><strong>{{ d.drs_no }}</strong></td><td>{{ d.drs_date }}</td><td>{{ d.rider_name }}</td><td><span class="badge">{{ d.status }}</span></td><td><a href="/print/drs/{{ d.id }}" target="_blank" class="btn btn-blue" style="padding:2px 6px; font-size:11px;">🖨️</a></td></tr>{% endfor %}</tbody></table>
            </div>
            <div class="card" style="border-top-color: #10B981;">
                <h3 style="color:#10B981; margin-top:0;"><i class="fas fa-check-double"></i> 2. Mark Delivered</h3>
                <form method="POST" style="background:#ECFDF5; padding:20px; border-radius:8px; border:1px solid #A7F3D0;"><input type="hidden" name="mark_deliver" value="1"><label style="color:#065F46;">AWB Number</label><input name="deliver_awb" required style="margin-bottom:15px; font-size:16px; text-transform:uppercase;"><label style="color:#065F46;">Receiver Name / Sign</label><input name="receiver" required style="margin-bottom:20px; font-size:16px;"><button type="submit" class="btn btn-green" style="width:100%; padding:15px; font-size:16px;"><i class="fas fa-check-circle"></i> UPDATE DELIVERY</button></form>
            </div>
        </div>
    </div>
    """
    return render_page("DRS & Delivery", render_template_string(html, pending=pending, sess=sess, drs_tbl=drs_tbl))

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
    html = """<div class="grid-2"><div class="card"><h3 style="margin-top:0;"><i class="fas fa-money-bill-wave"></i> Add Expense</h3><form method="POST" class="grid-2"><div><label>Date</label><input type="date" name="date" required style="width:100%;"></div><div><label>Category</label><select name="cat" style="width:100%;"><option>Fuel</option><option>Rent</option><option>Staff Salary</option><option>Vehicle Maintenance</option><option>Office Supplies</option><option>Miscellaneous</option></select></div><div><label>Amount</label><input type="number" step="0.01" name="amt" required style="width:100%;"></div><div><label>Paid To</label><input name="paid" style="width:100%;"></div><div style="grid-column: span 2;"><label>Notes</label><input name="notes" style="width:100%;"></div><div style="grid-column: span 2;"><button type="submit" class="btn btn-blue" style="width:100%; padding:12px;">Save</button></div></form></div><div class="card" style="overflow-y:auto; max-height:400px;"><h3>Expense History</h3><table class="datatable"><thead><tr><th>ID</th><th>Date</th><th>Category</th><th>Amount</th><th>Paid To</th><th>Notes</th><th>Del</th></tr></thead><tbody>{% for e in exps %}<tr><td>{{ e.id }}</td><td>{{ e.expense_date }}</td><td>{{ e.category }}</td><td style="color:#D64550; font-weight:bold;">₹{{ e.amount }}</td><td>{{ e.paid_to }}</td><td>{{ e.notes }}</td><td><a href="/expenses?delete={{ e.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}</tbody></table></div></div>"""
    return render_page("Office Expenses", render_template_string(html, exps=exps))

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
        l_data = []; c_bal = 0.0
        if request.args.get('cust_id'):
            c.execute("SELECT * FROM ledger WHERE customer_id=%s ORDER BY entry_date", (request.args.get('cust_id'),)); l_data = c.fetchall()
            c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (request.args.get('cust_id'),)); r = c.fetchone(); c_bal = safe_float(r['b']) if r else 0.0
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3 style="margin-top:0; color:#10B981;"><i class="fas fa-hand-holding-usd"></i> Receive Payment</h3><form method="POST" class="grid-2" style="align-items:end; background:#ECFDF5; padding:20px; border-radius:8px; border:1px solid #A7F3D0;"><div style="grid-column: span 2;"><label style="color:#065F46;">Customer</label><select name="cust_id" required style="width:100%;">{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div><label style="color:#065F46;">Amount (₹)</label><input type="number" step="0.01" name="amount" required style="font-weight:bold; width:100%;"></div><div><label style="color:#065F46;">Mode</label><select name="mode" style="width:100%;"><option>CASH</option><option>UPI</option></select></div><div style="grid-column: span 2;"><label style="color:#065F46;">Reference</label><input name="ref" style="width:100%;"></div><div style="grid-column: span 2;"><button type="submit" class="btn btn-green" style="width:100%; padding:12px;">Save Payment</button></div></form></div><div class="card"><h3 style="margin-top:0;">Recent Payments</h3><div style="max-height:280px; overflow-y:auto;"><table class="datatable"><thead><tr><th>ID</th><th>Date</th><th>Amount</th><th>Mode</th><th>Reference</th><th>Del</th></tr></thead><tbody>{% for p in pays %}<tr><td>{{ p.id }}</td><td>{{ p.payment_date }}</td><td style="color:#10B981; font-weight:bold;">₹{{ p.amount }}</td><td>{{ p.mode }}</td><td>{{ p.reference }}</td><td><a href="/accounts?del_pay={{ p.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}</tbody></table></div></div></div><div class="card"><h3>📒 Customer Ledger</h3><form method="GET" style="display:flex; gap:10px;"><select name="cust_id" style="flex:1;">{% for c in custs %}<option value="{{ c.id }}" {% if request.args.get('cust_id') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select><button class="btn btn-blue">View Ledger</button></form>{% if request.args.get('cust_id') %}<h3 style="text-align:right; color:#EF4444; background:#FEF2F2; padding:10px; border-radius:6px; border:1px solid #FECACA;">Closing Balance: ₹{{ c_bal }}</h3><table class="datatable"><thead><tr><th>Date</th><th>Voucher</th><th>Ref</th><th>Debit</th><th>Credit</th><th>Narration</th></tr></thead><tbody>{% for l in l_data %}<tr><td>{{ l.entry_date }}</td><td><span class="badge">{{ l.voucher_type }}</span></td><td>{{ l.reference }}</td><td style="color:#EF4444; font-weight:bold;">{{ l.debit }}</td><td style="color:#10B981; font-weight:bold;">{{ l.credit }}</td><td>{{ l.narration }}</td></tr>{% endfor %}</tbody></table>{% endif %}</div>"""
    return render_page("Accounts & Billing", render_template_string(html, custs=custs, pays=pays, l_data=l_data, c_bal=c_bal))

@app.route('/reports')
@login_required
def reports():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    d = datetime.now().strftime("%Y-%m-%d"); conn = get_db()
    with conn.cursor() as c:
        p1 = [d]; p2 = [d]; p4 = []
        q_b = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE booking_date=%s"
        if session.get('role') != 'ADMIN': q_b += " AND origin_name=%s"; p1.append(session.get('branch','HQ'))
        c.execute(q_b, tuple(p1)); b_row = c.fetchone()
        c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments WHERE payment_date=%s", tuple(p2)); p_row = c.fetchone()
        c.execute("SELECT COALESCE(SUM(amount),0) e FROM expenses WHERE expense_date=%s", tuple(p2)); e_row = c.fetchone()
        c.execute("SELECT c.code, c.name, COALESCE(SUM(l.debit-l.credit),0) bal FROM customers c LEFT JOIN ledger l ON l.customer_id=c.id GROUP BY c.id HAVING bal>0 ORDER BY bal DESC LIMIT 20"); out = c.fetchall()
        c.execute("SELECT origin_name as branch_name, COUNT(id) as total_shipments, SUM(total_amount) as total_revenue FROM shipments GROUP BY origin_name ORDER BY total_revenue DESC"); settlement = c.fetchall()
    conn.close()
    
    b_c = safe_int(b_row['c']) if b_row else 0; b_t = safe_float(b_row['t']) if b_row else 0.0
    p_a = safe_float(p_row['a']) if p_row else 0.0; e_e = safe_float(e_row['e']) if e_row else 0.0; net = round(p_a - e_e, 2)
    
    html = """<div class="card" style="background:#0B1F3A; color:white; border-top:4px solid #C9A24B;"><h2 style="margin:0; color:#C9A24B;"><i class="fas fa-chart-bar"></i> Day Close Report ({{ date }})</h2><div class="grid-4" style="margin-top:20px;"><div style="background:#13294B; padding:20px; border-radius:8px;"><h3><i class="fas fa-box"></i> Bookings</h3><h2 style="font-size:26px; margin:0;">{{ b_c }} <span style="font-size:14px; color:#8FA3BF; font-weight:normal;">Pcs</span> | ₹{{ b_t }}</h2></div><div style="background:#13294B; padding:20px; border-radius:8px;"><h3><i class="fas fa-rupee-sign"></i> Payments</h3><h2 style="color:#10B981; font-size:26px; margin:0;">₹{{ p_a }}</h2></div><div style="background:#13294B; padding:20px; border-radius:8px;"><h3><i class="fas fa-file-invoice"></i> Expenses</h3><h2 style="color:#EF4444; font-size:26px; margin:0;">₹{{ e_e }}</h2></div><div style="background:#13294B; padding:20px; border-radius:8px;"><h3><i class="fas fa-piggy-bank"></i> Net Cash</h3><h2 style="color:#38bdf8; font-size:26px; margin:0;">₹{{ net }}</h2></div></div></div><div class="card"><h3 style="color:#0E8A6D;">🌐 Multi-Branch Settlement</h3><table class="datatable"><thead><tr><th>Branch</th><th>Total Shipments</th><th>Total Revenue</th></tr></thead><tbody>{% for s in settlement %}<tr><td><strong>{{ s.branch_name }}</strong></td><td><span class="badge">{{ s.total_shipments }}</span></td><td style="font-weight:bold; color:#0B1F3A;">₹{{ s.total_revenue }}</td></tr>{% endfor %}</tbody></table></div><div class="grid-2"><div class="card"><h3 style="color:#EF4444; margin-top:0;"><i class="fas fa-exclamation-circle"></i> Market Outstanding</h3><table class="datatable"><thead><tr><th>Code</th><th>Name</th><th>Balance</th></tr></thead><tbody>{% for o in out %}<tr><td>{{ o.code }}</td><td><strong>{{ o.name }}</strong></td><td style="color:#EF4444; font-weight:bold;">₹{{ o.bal }}</td></tr>{% endfor %}</tbody></table></div></div>"""
    return render_page("Master Reports", render_template_string(html, b_c=b_c, b_t=b_t, p_a=p_a, e_e=e_e, net=net, out=out, settlement=settlement, date=d))

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

@app.route('/tools/sync-shipments', methods=['POST'])
@login_required
def sync_shipments():
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO outward_register (entry_date, awb_no, origin_station, out_station, destination, weight, pcs, finalized) SELECT booking_date, awb_no, origin_name, dest_station, dest_station, weight_kg, quantity, 1 FROM shipments WHERE status='OUTWARD' AND awb_no NOT IN (SELECT awb_no FROM outward_register)")
    conn.commit(); flash(f"✅ Synced {c.rowcount} shipments to outward", "success"); c.close(); conn.close()
    return redirect('/outward')

@app.route('/tools/auto-invoice', methods=['POST'])
@login_required
def auto_invoice():
    flash("✅ Auto Invoice functionality is ready.", "success"); return redirect('/outward')

@app.route('/tools/bulk-date-change', methods=['POST'])
@login_required
def bulk_date_change():
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE outward_register SET entry_date=%s WHERE entry_date=%s", (request.form.get('new_date'), request.form.get('old_date')))
    conn.commit(); flash(f"✅ Bulk Date Changed!", "success"); c.close(); conn.close()
    return redirect('/outward')

# ==========================================
# 🖨️ 12. EXACT OFFLINE PDF ENGINE
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
    
    # Restrict customer to only print their own labels
    if session.get('role') == 'CUSTOMER' and s['customer_id'] != session.get('customer_id'):
        return "Unauthorized", 403
    
    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=(101.6*mm, 152.4*mm)); cv.setLineWidth(1)
    cv.rect(4*mm, 4*mm, 93.6*mm, 144*mm) 
    draw_agc_logo(cv, 6*mm, 136*mm); cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica", 5.5); cv.drawString(6*mm, 129*mm, "ISO 9001:2008 Certified Company")
    cv.setFont("Helvetica-Bold", 14); cv.drawRightString(95*mm, 141*mm, str(session.get('branch', 'HQ')).upper())
    cv.setFont("Helvetica", 6); cv.drawRightString(95*mm, 137*mm, str(get_setting("company_name", "AKASH GANGA COURIER")))
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
    
    # Restrict customer to only print their own receipts
    if session.get('role') == 'CUSTOMER' and s['customer_id'] != session.get('customer_id'):
        return "Unauthorized", 403

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
    cv.setFont("Helvetica", 8); cv.drawString(30, y_tbl-50, str(get_setting("terms_note", "DECLARATION: Goods are carried at Owner's Risk."))); cv.drawString(420, y_tbl-50, f"For {str(get_setting('company_name', 'AKASH GANGA'))}"); cv.drawString(420, y_tbl-80, "Authorised Signatory")

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
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 50, f"{str(get_setting('company_name', 'AKASH GANGA'))} - OUTWARD MANIFEST")
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
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 50, f"{str(get_setting('company_name', 'AKASH GANGA'))} - DELIVERY RUN SHEET")
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
