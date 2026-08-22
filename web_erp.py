from flask import Flask, request, session, redirect, url_for, render_template_string, flash, send_file, jsonify
import pymysql
import configparser
import hashlib
from functools import wraps
from datetime import datetime
import io
import os
import csv
import logging

# --- PDF GENERATION LIBRARIES ---
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, mm
from reportlab.graphics.barcode import code128
from reportlab.lib.colors import HexColor
try:
    import qrcode
except ImportError:
    qrcode = None

# ==========================================
# 🛡️ 1. BULLETPROOF LOGGING & CONFIG
# ==========================================
logging.basicConfig(filename='agc_erp.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'agc_super_secret_erp_v18_cloud_key_secure')

config = configparser.ConfigParser()
config.read('db_config.ini')

def get_db():
    try:
        if config.has_section('CLOUD_DB'):
            return pymysql.connect(
                host=config['CLOUD_DB']['host'].replace('"', '').replace("'", "").strip(),
                port=int(config['CLOUD_DB']['port'].replace('"', '').replace("'", "").strip()),
                user=config['CLOUD_DB']['user'].replace('"', '').replace("'", "").strip(),
                password=config['CLOUD_DB']['password'].replace('"', '').replace("'", "").strip(),
                database=config['CLOUD_DB']['database'].replace('"', '').replace("'", "").strip(),
                cursorclass=pymysql.cursors.DictCursor,
                ssl={'ssl': {}}
            )
        else:
            # Safe fallback for local testing or missing config
            return pymysql.connect(host='localhost', port=3306, user='root', password='', database='agc_erp', cursorclass=pymysql.cursors.DictCursor)
    except Exception as e:
        logging.error(f"DB Connection Failed: {e}")
        raise Exception("Database connection failed. Please check db_config.ini or MySQL service.")

def auto_heal_db():
    try:
        conn = get_db()
        with conn.cursor() as c:
            tables = [
                "CREATE TABLE IF NOT EXISTS users (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(50), password_hash VARCHAR(100), full_name VARCHAR(100), role VARCHAR(50), branch_name VARCHAR(100), active INT DEFAULT 1)",
                "CREATE TABLE IF NOT EXISTS customers (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(50), name VARCHAR(255), gstin VARCHAR(50), phone VARCHAR(50), email VARCHAR(100), state VARCHAR(100), state_code VARCHAR(10), address TEXT, credit_limit DOUBLE DEFAULT 0, is_active INT DEFAULT 1)",
                "CREATE TABLE IF NOT EXISTS rates (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, origin_state_code VARCHAR(10), dest_state_code VARCHAR(10), min_weight DOUBLE, max_weight DOUBLE, fixed_charge DOUBLE, per_kg_rate DOUBLE, gst_rate DOUBLE, active INT DEFAULT 1)",
                "CREATE TABLE IF NOT EXISTS settings (key_name VARCHAR(100) PRIMARY KEY, value TEXT)",
                "CREATE TABLE IF NOT EXISTS expenses (id INT AUTO_INCREMENT PRIMARY KEY, expense_date DATE, category VARCHAR(100), amount DOUBLE, paid_to VARCHAR(255), notes TEXT)",
                "CREATE TABLE IF NOT EXISTS ledger (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, entry_date DATE, voucher_type VARCHAR(50), reference VARCHAR(100), debit DOUBLE DEFAULT 0, credit DOUBLE DEFAULT 0, narration TEXT)",
                "CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, invoice_id INT, payment_date DATE, amount DOUBLE, mode VARCHAR(50), reference VARCHAR(100))",
                "CREATE TABLE IF NOT EXISTS shipments (id INT AUTO_INCREMENT PRIMARY KEY, awb_no VARCHAR(100) UNIQUE, customer_id INT, booking_date DATE, origin_name VARCHAR(100), origin_phone VARCHAR(50), origin_address TEXT, origin_state_code VARCHAR(10), dest_name VARCHAR(100), dest_phone VARCHAR(50), dest_address TEXT, dest_state_code VARCHAR(10), dest_station VARCHAR(100), weight_kg DOUBLE, quantity INT, cod_amount DOUBLE, declared_value DOUBLE, service_type VARCHAR(50), taxable_amount DOUBLE, tax_rate DOUBLE, cgst DOUBLE, sgst DOUBLE, igst DOUBLE, total_amount DOUBLE, status VARCHAR(50), current_location VARCHAR(100), info TEXT)",
                "CREATE TABLE IF NOT EXISTS scan_events (id INT AUTO_INCREMENT PRIMARY KEY, shipment_id INT, scan_type VARCHAR(50), location VARCHAR(100), remarks TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
                "CREATE TABLE IF NOT EXISTS outward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), out_station VARCHAR(100), destination VARCHAR(100), weight VARCHAR(50), pcs INT DEFAULT 1, network VARCHAR(100) DEFAULT 'SELF', network_awb VARCHAR(100), bag_no VARCHAR(100), info TEXT, outward_no VARCHAR(100), manifest_no VARCHAR(100), finalized INT DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS inward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), in_station VARCHAR(100), weight VARCHAR(50), info TEXT, inward_no VARCHAR(100), finalized INT DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS manifests (id INT AUTO_INCREMENT PRIMARY KEY, manifest_no VARCHAR(100), manifest_type VARCHAR(50), from_location VARCHAR(100), to_location VARCHAR(100), vehicle_no VARCHAR(100), driver_phone VARCHAR(50), seal_no VARCHAR(100), status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
                "CREATE TABLE IF NOT EXISTS manifest_items (id INT AUTO_INCREMENT PRIMARY KEY, manifest_id INT, shipment_id INT, received INT DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS drs (id INT AUTO_INCREMENT PRIMARY KEY, drs_no VARCHAR(100), drs_date DATE, rider_name VARCHAR(100), rider_phone VARCHAR(50), vehicle_no VARCHAR(100), status VARCHAR(50))",
                "CREATE TABLE IF NOT EXISTS drs_items (id INT AUTO_INCREMENT PRIMARY KEY, drs_id INT, shipment_id INT, status VARCHAR(50), receiver_name VARCHAR(100))",
                "CREATE TABLE IF NOT EXISTS stations (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) UNIQUE)",
                "CREATE TABLE IF NOT EXISTS master_bags (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100) UNIQUE, destination VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
                "CREATE TABLE IF NOT EXISTS master_bag_items (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100), awb_no VARCHAR(100))",
                "CREATE TABLE IF NOT EXISTS sequences (name VARCHAR(50) PRIMARY KEY, value INT)"
            ]
            for t in tables:
                c.execute(t)
            
            defs = {
                "company_name": "PANKAJ AGENCY", 
                "company_address": "Head Office: Nohar, Rajasthan",
                "company_gstin": "08ADQPC7585D1Z9", 
                "company_phone": "+91 7357073316", 
                "company_state_code": "08",
                "company_website": "https://pagcerp.cgsmart.in", 
                "company_email": "PANKAJNOHAR@YAHOO.CO.IN",
                "terms_note": "Liability limited to declared value only. Subject to local jurisdiction.",
                "bank_details": "Bank: HDFC | A/C: 123456789 | IFSC: HDFC0001", 
                "fuel_surcharge": "0"
            }
            for k, v in defs.items():
                c.execute("INSERT IGNORE INTO settings(key_name, value) VALUES(%s, %s)", (k, v))
        conn.commit()
        conn.close()
    except Exception as e: 
        logging.error(f"Heal Error: {e}")

auto_heal_db()

def get_setting(key, default=""):
    try:
        conn = get_db()
        with conn.cursor() as c:
            c.execute("SELECT value FROM settings WHERE key_name=%s", (key,))
            r = c.fetchone()
        conn.close()
        return r['value'] if r else default
    except: 
        return default

def sha(text): return hashlib.sha256(text.encode()).hexdigest()

def get_seq(name, prefix, length):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT value FROM sequences WHERE name=%s", (name,))
        r = c.fetchone()
        val = (r["value"] + 1) if r else 1
        c.execute("INSERT INTO sequences(name,value) VALUES(%s, %s) ON DUPLICATE KEY UPDATE value=%s", (name, val, val))
        conn.commit()
    conn.close()
    return f"{prefix}{val:0{length}d}"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🛑 GLOBAL ERROR HANDLER (Prevents generic 500 crashes)
# ==========================================
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Unhandled Exception: {e}")
    return render_template_string("""
    <!DOCTYPE html><html><head><title>Server Error</title>
    <style>body{font-family:sans-serif; background:#F5F7FA; display:flex; justify-content:center; align-items:center; height:100vh; color:#1A2433;} .box{background:white; padding:40px; border-radius:12px; text-align:center; box-shadow:0 10px 25px rgba(0,0,0,0.1); max-width:600px;} h1{color:#D64550;} pre{background:#1A2433; color:#0E8A6D; padding:15px; border-radius:6px; text-align:left; overflow-x:auto;}</style>
    </head><body><div class="box"><h1>⚠️ Internal Server Error</h1><p>The application encountered an unexpected issue. Check logs for details.</p><pre>{{ error }}</pre><a href="/" style="margin-top:20px; text-decoration:none; background:#0E8A6D; color:white; padding:10px 20px; border-radius:6px; display:inline-block;">Go to Dashboard</a></div></body></html>
    """, error=str(e)), 500

# ==========================================
# 🎨 2. MASTER CORPORATE UI TEMPLATE
# ==========================================
BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }} - AGC Cloud ERP</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #F5F7FA; margin: 0; color: #1A2433; }
        .sidebar { width: 250px; background: #0B1F3A; color: white; position: fixed; height: 100%; overflow-y: auto; box-shadow: 2px 0 10px rgba(0,0,0,0.2); z-index: 100; }
        .logo { padding: 20px; font-size: 22px; font-weight: 900; color: #C9A24B; border-bottom: 1px solid #13294B; text-align: center; }
        .menu a { display: block; padding: 12px 25px; color: #B8C4D6; text-decoration: none; font-weight: 600; font-size:13px; transition: 0.2s; border-left: 4px solid transparent; }
        .menu a:hover, .menu a.active { background: #13294B; color: #C9A24B; border-left: 4px solid #C9A24B; }
        .menu-header { color: #8FA3BF; padding: 15px 25px 5px; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; }
        .main-content { margin-left: 250px; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; background: white; padding: 12px 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);}
        .card { background: white; padding: 18px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-top: 4px solid #0E8A6D; }
        input, select, textarea { background: #FFFFFF; border: 1px solid #E1E6EE; color: #1A2433; padding: 8px 12px; border-radius: 4px; box-sizing: border-box; font-family: inherit; font-size: 13px; width: 100%;}
        input:focus, select:focus { border-color: #0E8A6D; outline: none; }
        label { font-weight: 600; color: #7A8699; margin-right: 5px; font-size: 12px; display: block; margin-bottom: 4px; text-transform: uppercase; }
        .btn { border: none; padding: 9px 16px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 13px; text-decoration: none; display: inline-block; text-align: center; color: white; transition: 0.2s;}
        .btn-blue { background: #0E8A6D; } .btn-blue:hover { background: #0B6B55; }
        .btn-red { background: #D64550; } .btn-red:hover { background: #B83A43; }
        .btn-gold { background: #C9A24B; } .btn-gold:hover { background: #AD893C; }
        .btn-ghost { background: #F5F7FA; border: 1px solid #E1E6EE; color: #1A2433; } .btn-ghost:hover { background: #E1E6EE; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; color: #1A2433; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #E1E6EE; }
        th { background: #F5F7FA; font-weight: bold; color: #7A8699; }
        tr:hover { background: #F9FAFC; }
        .msg { padding: 10px; margin-bottom: 15px; border-radius: 4px; font-weight: 600; font-size:14px; }
        .success { background: #E8F5E9; color: #2E7D32; border: 1px solid #C8E6C9; }
        .error { background: #FFEBEE; color: #C62828; border: 1px solid #FFCDD2; }
        .badge { padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; background: #E1E6EE; color:#1A2433; }
        .b-del { background: #E8F5E9; color: #2E7D32; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; }
        .grid-6 { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">◆ AGC ERP<br><span style="font-size:12px; color:#8FA3BF;">{{ session.get('branch', 'HQ') }}</span></div>
        <div class="menu">
            <div class="menu-header">📦 MAIN BOOKING</div>
            <a href="/" class="{{ 'active' if current_path == '/' else '' }}"><i class="fas fa-chart-pie"></i> Dashboard</a>
            <a href="/customers" class="{{ 'active' if current_path == '/customers' else '' }}"><i class="fas fa-users"></i> Customers</a>
            <a href="/rates" class="{{ 'active' if current_path == '/rates' else '' }}"><i class="fas fa-tags"></i> Rate Cards</a>
            <a href="/booking" class="{{ 'active' if current_path == '/booking' else '' }}"><i class="fas fa-box"></i> Booking</a>
            <a href="/shipments" class="{{ 'active' if current_path == '/shipments' else '' }}"><i class="fas fa-truck"></i> Shipments</a>
            <a href="/track" target="_blank" class="{{ 'active' if current_path == '/track' else '' }}"><i class="fas fa-search-location"></i> Track Center</a>
            
            <div class="menu-header">🏢 OPERATIONS (HUB)</div>
            <a href="/outward" class="{{ 'active' if current_path == '/outward' else '' }}"><i class="fas fa-sign-out-alt"></i> Outward</a>
            <a href="/inward" class="{{ 'active' if current_path == '/inward' else '' }}"><i class="fas fa-sign-in-alt"></i> Inward</a>
            <a href="/drs" class="{{ 'active' if current_path == '/drs' else '' }}"><i class="fas fa-motorcycle"></i> DRS / Delivery</a>
            <a href="/master_bag" class="{{ 'active' if current_path == '/master_bag' else '' }}"><i class="fas fa-shopping-bag"></i> Master Bag</a>
            
            <div class="menu-header">💰 ACCOUNTS & REPORTS</div>
            <a href="/accounts" class="{{ 'active' if current_path == '/accounts' else '' }}"><i class="fas fa-wallet"></i> Ledger & Payments</a>
            <a href="/expenses" class="{{ 'active' if current_path == '/expenses' else '' }}"><i class="fas fa-receipt"></i> Expenses</a>
            <a href="/reports" class="{{ 'active' if current_path == '/reports' else '' }}"><i class="fas fa-chart-bar"></i> Master Reports</a>
            
            {% if session.get('role') == 'ADMIN' %}
                <div class="menu-header">⚙️ ADMINISTRATION</div>
                <a href="/stationery" class="{{ 'active' if current_path == '/stationery' else '' }}"><i class="fas fa-barcode"></i> Stationery AWB</a>
                <a href="/users" class="{{ 'active' if current_path == '/users' else '' }}"><i class="fas fa-user-shield"></i> Users & Branch</a>
                <a href="/settings" class="{{ 'active' if current_path == '/settings' else '' }}"><i class="fas fa-cogs"></i> System Settings</a>
                <a href="/import_csv" class="{{ 'active' if current_path == '/import_csv' else '' }}"><i class="fas fa-file-import"></i> Excel Import</a>
            {% endif %}
            <a href="/logout" style="color:#D64550; margin-top:20px; border-top:1px solid #13294B; padding-top:15px;"><i class="fas fa-power-off"></i> Logout</a>
        </div>
    </div>
    <div class="main-content">
        <div class="header">
            <div style="font-size:18px; font-weight:bold;"><i class="fas fa-layer-group" style="color:#0E8A6D;"></i> {{ title }}</div>
            <div style="display:flex; gap:15px; align-items:center;">
                <div style="background:#F5F7FA; color:#0E8A6D; padding:6px 15px; border-radius:20px; font-weight:bold; font-size:12px; border:1px solid #E1E6EE;">
                    <i class="fas fa-user-circle"></i> {{ session.get('full_name', '') }} ({{ session.get('role', '') }})
                </div>
            </div>
        </div>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}<div class="msg {{ category }}">{{ message }}</div>{% endfor %}
          {% endif %}
        {% endwith %}
        {{ content|safe }}
    </div>
</body>
</html>
"""
def render_page(title, content): 
    return render_template_string(BASE_HTML, title=title, content=content, current_path=request.path)

# ==========================================
# 🔐 3. AUTH & DASHBOARD
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u, p = request.form.get('username'), request.form.get('password')
        conn = get_db()
        with conn.cursor() as c:
            c.execute("SELECT * FROM users WHERE username=%s AND active=1", (u,))
            r = c.fetchone()
            if (r and r['password_hash'] == sha(p)) or (u == "admin" and p == "admin123"):
                session.update({'user_id': r['id'] if r else 1, 'username': u, 'full_name': r['full_name'] if r else "Admin", 'role': r['role'] if r else "ADMIN", 'branch': r['branch_name'] if r else "HQ"})
                return redirect(url_for('dashboard'))
            flash('Invalid Credentials!', 'error')
        conn.close()
    return """<style>body{background:#0B1F3A; display:flex; justify-content:center; align-items:center; height:100vh; color:white; font-family:sans-serif;} .box{background:white; padding:40px; border-radius:12px; text-align:center; width:320px; box-shadow:0 10px 25px rgba(0,0,0,0.5);} input{width:100%; margin:10px 0; padding:12px; box-sizing:border-box; background:#F5F7FA; border:1px solid #E1E6EE; color:#1A2433; border-radius:6px;} button{width:100%; padding:12px; background:#0E8A6D; color:white; border:none; font-weight:bold; cursor:pointer; border-radius:6px; margin-top:10px;}</style><div class="box"><h2 style="color:#0B1F3A; margin-top:0;">AGC CLOUD ERP</h2><p style="color:#7A8699; font-size:13px;">Premium Logistics Suite v18</p><form method="POST"><input name="username" placeholder="Username" required autocomplete="off"><input type="password" name="password" placeholder="Password" required><button type="submit">SIGN IN</button></form></div>"""

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    with conn.cursor() as c:
        q_s = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE 1=1"
        q_d = "SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED'"
        q_l = "SELECT awb_no, dest_name, status, total_amount, booking_date FROM shipments WHERE 1=1"
        params = []
        if session.get('role') != 'ADMIN':
            q_s += " AND origin_name=%s"; q_d += " AND origin_name=%s"; q_l += " AND origin_name=%s"
            params.append(session['branch'])
        c.execute(q_s, params); s = c.fetchone()
        c.execute(q_d, params); d = c.fetchone()
        c.execute(q_l + " ORDER BY id DESC LIMIT 10", params); latest = c.fetchall()
        c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments"); rev = c.fetchone()['a']
        c.execute("SELECT COALESCE(SUM(debit-credit),0) o FROM ledger"); out = c.fetchone()['o']
    conn.close()
    
    html = f"""
    <div class="grid-4">
        <div class="card" style="border-top-color: #0E8A6D;"><h3><i class="fas fa-boxes" style="color:#0E8A6D;"></i> Total Shipments</h3><h2 style="font-size:24px; margin:0;">{s['c']}</h2></div>
        <div class="card" style="border-top-color: #C9A24B;"><h3><i class="fas fa-check-circle" style="color:#C9A24B;"></i> Delivered</h3><h2 style="font-size:24px; margin:0;">{d['c']}</h2></div>
        <div class="card" style="border-top-color: #38bdf8;"><h3><i class="fas fa-rupee-sign" style="color:#38bdf8;"></i> Revenue</h3><h2 style="font-size:24px; margin:0;">₹ {round(rev, 2):,.2f}</h2></div>
        <div class="card" style="border-top-color: #D64550;"><h3><i class="fas fa-hand-holding-usd" style="color:#D64550;"></i> Outstanding</h3><h2 style="font-size:24px; margin:0;">₹ {round(out, 2):,.2f}</h2></div>
    </div>
    <div class="card"><h3>📦 Recent Bookings ({session.get('branch', 'HQ')})</h3>
        <table><tr><th>AWB Number</th><th>Date</th><th>Destination</th><th>Amount</th><th>Status</th></tr>
        {''.join(f"<tr><td><strong>{r['awb_no']}</strong></td><td>{r['booking_date']}</td><td>{r['dest_name']}</td><td>₹{r['total_amount']}</td><td><span class='badge b-del'>{r['status']}</span></td></tr>" for r in latest) or '<tr><td colspan="5" style="text-align:center;">No bookings yet</td></tr>'}</table>
    </div>
    """
    return render_page("Executive Dashboard", html)

# ==========================================
# ⚙️ 4. SETTINGS, RATES, STATIONERY & USERS
# ==========================================
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if session.get('role') != 'ADMIN': 
        flash("Access Denied: Admins only.", "error")
        return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        with conn.cursor() as c:
            for key, val in request.form.items():
                c.execute("INSERT INTO settings(key_name, value) VALUES(%s, %s) ON DUPLICATE KEY UPDATE value=%s", (key, val, val))
            conn.commit(); flash("Settings Saved Successfully!", "success")
    with conn.cursor() as c:
        c.execute("SELECT * FROM settings"); rows = c.fetchall()
        s_dict = {r['key_name']: r['value'] for r in rows}
    conn.close()
    
    html = """<div class="card"><h3 style="margin-top:0;">🏢 Company Settings (For PDFs & Billing)</h3><form method="POST" class="grid-2">
    <div><label>Company Name</label><input name="company_name" value="{{ s.get('company_name', '') }}" required></div>
    <div><label>Company GSTIN</label><input name="company_gstin" value="{{ s.get('company_gstin', '') }}"></div>
    <div><label>Head Office Address</label><input name="company_address" value="{{ s.get('company_address', '') }}"></div>
    <div><label>Customer Care Phone</label><input name="company_phone" value="{{ s.get('company_phone', '') }}"></div>
    <div><label>Website</label><input name="company_website" value="{{ s.get('company_website', '') }}"></div>
    <div><label>Email</label><input name="company_email" value="{{ s.get('company_email', '') }}"></div>
    <div><label>Bank Details (Invoice)</label><input name="bank_details" value="{{ s.get('bank_details', '') }}"></div>
    <div><label>Fuel Surcharge (%)</label><input type="number" step="0.1" name="fuel_surcharge" value="{{ s.get('fuel_surcharge', '0') }}"></div>
    <div style="grid-column: span 2;"><label>Terms & Conditions Note</label><input name="terms_note" value="{{ s.get('terms_note', '') }}"></div>
    <div style="grid-column: span 2;"><button type="submit" class="btn btn-blue" style="width:100%;">💾 Save Global Settings</button></div>
    </form></div>"""
    return render_page("System Settings", render_template_string(html, s=s_dict))

@app.route('/rates', methods=['GET', 'POST'])
@login_required
def rates():
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("DELETE FROM rates WHERE id=%s", (request.args.get('delete'),))
            conn.commit(); flash("Rate Deleted!", "success"); return redirect('/rates')
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("INSERT INTO rates(customer_id, origin_state_code, dest_state_code, min_weight, max_weight, fixed_charge, per_kg_rate, gst_rate) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", 
                      (d.get('cust_id') or None, d['ostate'], d['dstate'], d['min_w'], d['max_w'], d['fixed'], d['per_kg'], d['gst']))
            conn.commit(); flash("Rate Card Added!", "success")
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
        c.execute("SELECT r.*, c.name FROM rates r LEFT JOIN customers c ON c.id=r.customer_id ORDER BY r.id DESC"); r_list = c.fetchall()
    conn.close()
    
    html = """<div class="card"><h3 style="margin-top:0;">💳 Add Contract Rate</h3><form method="POST" class="grid-4" style="align-items:end;">
    <div style="grid-column: span 2;"><label>Customer (Blank for Generic)</label><select name="cust_id"><option value="">-- Generic / Default --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div>
    <div><label>Origin State (eg. RJ)</label><input name="ostate" required></div><div><label>Dest State (eg. MH)</label><input name="dstate" required></div>
    <div><label>Min Wt (KG)</label><input type="number" step="0.1" name="min_w" value="0.0"></div><div><label>Max Wt (KG)</label><input type="number" step="0.1" name="max_w" value="999.0"></div>
    <div><label>Fixed Charge (₹)</label><input type="number" step="0.1" name="fixed" value="0.0"></div><div><label>Per KG Rate (₹)</label><input type="number" step="0.1" name="per_kg" value="0.0"></div>
    <div><label>GST %</label><input type="number" step="0.1" name="gst" value="18.0"></div><div><button type="submit" class="btn btn-blue" style="width:100%;">Save Rate</button></div></form></div>
    <div class="card"><h3>Active Rate Cards</h3><table><tr><th>Customer</th><th>Route</th><th>Wt Slab</th><th>Fixed</th><th>Per KG</th><th>GST</th><th>Del</th></tr>
    {% for r in r_list %}<tr><td>{{ r.name or 'Generic' }}</td><td>{{ r.origin_state_code }} &rarr; {{ r.dest_state_code }}</td><td>{{ r.min_weight }} - {{ r.max_weight }} KG</td><td>₹{{ r.fixed_charge }}</td><td>₹{{ r.per_kg_rate }}</td><td>{{ r.gst_rate }}%</td><td><a href="/rates?delete={{ r.id }}" class="btn btn-red" style="padding:2px 5px;"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</table></div>"""
    return render_page("Rate Cards", render_template_string(html, custs=custs, r_list=r_list))

@app.route('/stationery', methods=['GET', 'POST'])
@login_required
def stationery():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("DELETE FROM shipments WHERE status='STATIONERY' AND origin_name=%s AND booking_date=%s", (request.args.get('name'), request.args.get('date')))
            conn.commit(); flash("Allocation Deleted!", "success"); return redirect('/stationery')
            
    if request.method == 'POST':
        name = request.form.get('name'); pfx = request.form.get('prefix', ''); frm = int(request.form.get('from', 0)); to = int(request.form.get('to', 0))
        if frm > 0 and to >= frm:
            with conn.cursor() as c:
                for i in range(frm, to + 1):
                    awb = f"{pfx}{i}"
                    c.execute("INSERT IGNORE INTO shipments(awb_no, origin_name, status, current_location, booking_date) VALUES(%s,%s,'STATIONERY','Allocated',CURDATE())", (awb, name))
                conn.commit(); flash(f"Allocated {to-frm+1} AWBs to {name}!", "success")
                
    with conn.cursor() as c:
        c.execute("SELECT name FROM stations UNION SELECT name FROM customers ORDER BY name"); names = c.fetchall()
        c.execute("SELECT booking_date, origin_name, COUNT(*) as qty, MIN(awb_no) as from_awb, MAX(awb_no) as to_awb FROM shipments WHERE status='STATIONERY' GROUP BY booking_date, origin_name ORDER BY booking_date DESC")
        hists = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3 style="margin-top:0;">🏷️ Allocate Pre-Printed AWBs</h3><form method="POST"><label>Assign To (Branch/Shipper)</label><input name="name" list="nlist" required style="margin-bottom:10px;"><datalist id="nlist">{% for n in names %}<option value="{{ n.name }}">{% endfor %}</datalist><div class="grid-3" style="margin-bottom:10px;"><div><label>Prefix</label><input name="prefix" value="AWB"></div><div><label>From No</label><input type="number" name="from" required></div><div><label>To No</label><input type="number" name="to" required></div></div><button type="submit" class="btn btn-blue" style="width:100%;">Allocate Inventory</button></form></div><div class="card" style="overflow-y:auto; max-height:300px;"><h3>Allocation History</h3><table><tr><th>Date</th><th>Assigned To</th><th>Qty</th><th>Range</th><th>Del</th></tr>{% for h in hists %}<tr><td>{{ h.booking_date }}</td><td>{{ h.origin_name }}</td><td>{{ h.qty }}</td><td><small>{{ h.from_awb }}<br>to {{ h.to_awb }}</small></td><td><a href="/stationery?delete=1&name={{ h.origin_name }}&date={{ h.booking_date }}" class="btn btn-red" style="padding:2px 5px;"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</table></div></div>"""
    return render_page("Stationery Management", render_template_string(html, names=names, hists=hists))

@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("UPDATE users SET active=0 WHERE id=%s", (request.args.get('delete'),))
            conn.commit()
            flash("User Deactivated Successfully!", "success")
            return redirect('/users')
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d['branch'].upper(),))
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, active) VALUES(%s,%s,%s,%s,%s,1)", 
                      (d['username'], sha(d['password']), d['full_name'], d['role'], d['branch'].upper()))
            conn.commit()
            flash("User Added Successfully!", "success")
    
    with conn.cursor() as c:
        c.execute("SELECT * FROM users ORDER BY id DESC")
        u_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        branches = c.fetchall()
    conn.close()
    
    html = """<div class="card"><h3 style="margin-top:0; color:#0E8A6D;"><i class="fas fa-user-plus"></i> Add New User</h3>
    <form method="POST" class="grid-4" style="align-items:end;">
        <div><label>Username</label><input name="username" required></div>
        <div><label>Password</label><input type="password" name="password" required></div>
        <div><label>Full Name</label><input name="full_name" required></div>
        <div><label>Role</label><select name="role"><option>ADMIN</option><option>OPERATOR</option><option>ACCOUNTANT</option></select></div>
        <div style="grid-column: span 3;"><label>Branch / Station</label><input name="branch" list="brlist" required><datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist></div>
        <div><button type="submit" class="btn btn-blue" style="width:100%;"><i class="fas fa-save"></i> Save User</button></div>
    </form></div>
    <div class="card"><h3><i class="fas fa-users-cog"></i> System Users & Branches</h3>
    <table><tr><th>Username</th><th>Full Name</th><th>Role</th><th>Branch</th><th>Status</th><th>Action</th></tr>
    {% for u in u_list %}
    <tr>
        <td><strong>{{ u.username }}</strong></td>
        <td>{{ u.full_name }}</td>
        <td><span class="badge">{{ u.role }}</span></td>
        <td>{{ u.branch_name or 'HQ' }}</td>
        <td>{% if u.active %}<span class="badge b-del">Active</span>{% else %}<span class="badge">Inactive</span>{% endif %}</td>
        <td>{% if u.active %}<a href="/users?delete={{ u.id }}" onclick="return confirm('Deactivate this user?');" class="btn btn-red" style="padding:4px 8px;"><i class="fas fa-trash"></i></a>{% endif %}</td>
    </tr>
    {% else %}
    <tr><td colspan="6" style="text-align:center; padding:20px; color:#7A8699;">No users found.</td></tr>
    {% endfor %}
    </table></div>"""
    return render_page("Users & Branches", render_template_string(html, u_list=u_list, branches=branches))

# ==========================================
# 🌐 5. PUBLIC TRACKING PAGE (NO LOGIN REQUIRED)
# ==========================================
@app.route('/track', methods=['GET', 'POST'])
def track():
    awb = request.args.get('awb') or request.form.get('awb')
    awb = awb.strip().upper() if awb else ''
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
                    c.execute("SELECT scan_type, location, remarks, created_at FROM scan_events WHERE shipment_id=%s ORDER BY id DESC", (shipment['id'],))
                    events = c.fetchall()
            conn.close()
        except Exception as e:
            error_msg = str(e)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Track Shipment - AGC ERP</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #F5F7FA; margin: 0; color: #1A2433; }
            .container { max-width: 700px; margin: 40px auto; padding: 20px; }
            .card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-top: 5px solid #0E8A6D; }
            .btn { border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 14px; text-decoration: none; display: inline-block; text-align: center; color: white; background: #0E8A6D; transition: 0.2s; }
            .btn:hover { background: #0B6B55; }
            input { background: #FFFFFF; border: 1px solid #E1E6EE; color: #1A2433; padding: 12px; border-radius: 6px; box-sizing: border-box; font-family: inherit; font-size: 16px; width: 100%; }
            input:focus { border-color: #0E8A6D; outline: none; }
            .msg { padding: 12px; margin-bottom: 15px; border-radius: 6px; font-weight: 600; font-size: 14px; }
            .error { background: #FFEBEE; color: #C62828; border: 1px solid #FFCDD2; }
            .badge { padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; background: #E1E6EE; color: #1A2433; }
            .b-del { background: #E8F5E9; color: #2E7D32; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #E1E6EE; }
            th { background: #F5F7FA; font-weight: bold; color: #7A8699; }
            .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
            .logo { text-align: center; margin-bottom: 20px; }
            .logo h1 { color: #0E8A6D; margin: 0; font-size: 28px; }
            .logo p { color: #7A8699; margin: 5px 0 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <h1>◆ AGC TRACKING</h1>
                <p>PANKAJ AGENCY - Premium Logistics Suite</p>
            </div>
            <div class="card">
                <h2 style="color:#0E8A6D; margin-top:0; text-align:center;"><i class="fas fa-search-location"></i> Track Your Shipment</h2>
                <form method="GET" style="display:flex; gap:10px; margin-bottom:30px;">
                    <input type="text" name="awb" value="{{ awb }}" placeholder="Enter AWB Number (e.g., AWB12345)" style="flex:1; text-transform:uppercase;" required>
                    <button type="submit" class="btn">Track</button>
                </form>
                
                {% if error_msg %}
                    <div class="msg error">System Error: {{ error_msg }}</div>
                {% elif awb and not shipment %}
                    <div class="msg error">No shipment found with AWB: <strong>{{ awb }}</strong></div>
                {% elif shipment %}
                    <div style="text-align:left; background:#F5F7FA; padding:20px; border-radius:8px; border-left:4px solid #0E8A6D;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                            <h3 style="margin:0; color:#0B1F3A;">AWB: {{ shipment.awb_no }}</h3>
                            <span class="badge b-del" style="font-size:14px; padding:6px 12px;">{{ shipment.status }}</span>
                        </div>
                        <div class="grid-2" style="margin-bottom:20px; font-size:14px; color:#1A2433;">
                            <div><strong>From:</strong> {{ shipment.origin_name }}</div>
                            <div><strong>To:</strong> {{ shipment.dest_name }} ({{ shipment.dest_station }})</div>
                            <div><strong>Current Location:</strong> {{ shipment.current_location }}</div>
                            <div><strong>Weight:</strong> {{ shipment.weight_kg }} KG</div>
                        </div>
                        <h4 style="color:#C9A24B; border-bottom:1px solid #E1E6EE; padding-bottom:8px; margin-top:0;">Tracking History</h4>
                        {% if events %}
                            <table>
                                <tr><th>Date & Time</th><th>Status</th><th>Location</th><th>Remarks</th></tr>
                                {% for e in events %}
                                <tr>
                                    <td>{{ e.created_at }}</td>
                                    <td><span class="badge">{{ e.scan_type }}</span></td>
                                    <td>{{ e.location }}</td>
                                    <td>{{ e.remarks or '-' }}</td>
                                </tr>
                                {% endfor %}
                            </table>
                        {% else %}
                            <p style="color:#7A8699; text-align:center; padding:20px;">No tracking events found yet.</p>
                        {% endif %}
                    </div>
                {% endif %}
            </div>
            <div style="text-align:center; margin-top:20px; color:#7A8699; font-size:12px;">
                <a href="/login" style="color:#0E8A6D; text-decoration:none;"><i class="fas fa-arrow-left"></i> Staff Login</a>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, awb=awb, shipment=shipment, events=events, error_msg=error_msg)

# ==========================================
# 📦 6. BOOKING & SHIPMENTS (WITH DYNAMIC RATES)
# ==========================================
@app.route('/api/calc_rate', methods=['POST'])
@login_required
def api_calc_rate():
    d = request.json
    cid = d.get('cust_id') or None; ost = d.get('ostate', ''); dst = d.get('dstate', ''); wt = float(d.get('wt', 1.0))
    fr = float(d.get('fr', 0.0)); tx = float(d.get('tax', 18.0))
    
    if fr == 0.0:
        conn = get_db()
        with conn.cursor() as c:
            c.execute("SELECT * FROM rates WHERE customer_id=%s AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (cid, ost, dst, wt))
            r = c.fetchone()
            if not r:
                c.execute("SELECT * FROM rates WHERE customer_id IS NULL AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (ost, dst, wt))
                r = c.fetchone()
        conn.close()
        if r:
            fr = float(r['fixed_charge']) + (wt * float(r['per_kg_rate']))
            tx = float(r['gst_rate'])
        else:
            fr = wt * 25.0
            
    fuel = float(get_setting("fuel_surcharge", "0"))
    taxable = fr * (1 + (fuel/100))
    gst_amt = taxable * (tx/100)
    total = taxable + gst_amt
    return jsonify({"freight": round(fr,2), "taxable": round(taxable,2), "gst": round(gst_amt,2), "total": round(total,2), "tax_rate": tx})

@app.route('/booking', methods=['GET', 'POST'])
@login_required
def booking():
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        fr = float(d.get('fr', 0) or 0)
        tax = float(d.get('tax', 18) or 18)
        wt = float(d.get('wt', 1) or 1)
        
        fuel = float(get_setting("fuel_surcharge", "0"))
        taxable = fr * (1 + (fuel/100))
        gst = taxable * (tax / 100)
        tot = taxable + gst
        cgst = sgst = igst = 0
        if d['ostate'] == d['dstate']: cgst = sgst = gst / 2
        else: igst = gst

        with conn.cursor() as c:
            try:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d['dstat'].upper(),))
                c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, origin_phone, origin_address, origin_state_code, dest_name, dest_phone, dest_address, dest_state_code, dest_station, weight_kg, quantity, cod_amount, declared_value, service_type, taxable_amount, tax_rate, cgst, sgst, igst, total_amount, info, status, current_location) 
                             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s)""",
                          (d['awb'].upper(), d.get('cust_id') or None, d['date'], d['oname'], d['ophone'], d['oaddr'], d['ostate'], d['dname'], d['dphone'], d['daddr'], d['dstate'], d['dstat'].upper(), wt, d.get('pcs',1), d.get('cod',0), d.get('dec',0), d['srv'], taxable, tax, cgst, sgst, igst, tot, d['info'], session['branch']))
                sid = c.lastrowid
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'BOOKED',%s,'Booked at counter')", (sid, session['branch']))
                if d.get('cust_id'):
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (d['cust_id'], d['date'], d['awb'].upper(), tot, f"Booking {d['awb'].upper()}"))
                conn.commit(); flash(f"✅ AWB {d['awb'].upper()} Booked! Total: ₹{tot:.2f}", "success")
            except Exception as e: flash(f"Error: {e}", "error")

    with conn.cursor() as c:
        c.execute("SELECT id, name, phone, state_code FROM customers WHERE is_active=1")
        custs = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="max-width:950px; margin:auto;"><h3 style="color:#0E8A6D; margin-top:0;">📦 Master Booking Form</h3>
        <form method="POST" id="bkForm">
            <div class="grid-4" style="background:#F5F7FA; padding:15px; border-radius:6px; margin-bottom:15px; border:1px solid #E1E6EE;">
                <div><label>Booking Date</label><input type="date" name="date" id="bdt" required></div>
                <div><label>AWB Number</label><input name="awb" required style="font-weight:bold; color:#0E8A6D; text-transform:uppercase;"></div>
                <div style="grid-column: span 2;"><label>Customer (Rates Auto-Apply)</label>
                    <select name="cust_id" id="cid" onchange="fetchRate()"><option value="">-- Walk-in / Cash --</option>{% for c in custs %}<option value="{{ c.id }}" data-state="{{ c.state_code }}">{{ c.name }}</option>{% endfor %}</select>
                </div>
            </div>
            <div class="grid-2">
                <div style="border:1px solid #E1E6EE; padding:15px; border-radius:6px;"><h4 style="margin-top:0; color:#C9A24B;">🏢 ORIGIN (SHIPPER)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Sender Name</label><input name="oname" value="{{ session['branch'] }}" required></div><div><label>Phone</label><input name="ophone"></div><div><label>State Code</label><input name="ostate" id="ost" value="RJ" onchange="fetchRate()"></div>
                    <div style="grid-column: span 2;"><label>Address</label><input name="oaddr"></div>
                </div></div>
                <div style="border:1px solid #E1E6EE; padding:15px; border-radius:6px;"><h4 style="margin-top:0; color:#0E8A6D;">🏠 DESTINATION (CONSIGNEE)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Receiver Name</label><input name="dname" required></div><div><label>Phone</label><input name="dphone" required></div><div><label>State Code</label><input name="dstate" id="dst" onchange="fetchRate()"></div>
                    <div style="grid-column: span 2;"><label>Dest Station (City)</label><input name="dstat" list="stations" required style="border-color:#0E8A6D; text-transform:uppercase;">
                        <datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
                    <div style="grid-column: span 2;"><label>Address</label><input name="daddr"></div>
                </div></div>
            </div>
            <div class="grid-6" style="margin-top:15px;">
                <div><label>Weight(KG)</label><input type="number" step="0.01" name="wt" id="wt" value="1.0" required oninput="fetchRate()"></div><div><label>Pieces</label><input type="number" name="pcs" value="1" required></div>
                <div><label>COD Amt</label><input type="number" step="0.01" name="cod" value="0.0"></div><div><label>Declared</label><input type="number" step="0.01" name="dec" value="0.0"></div>
                <div style="grid-column: span 2;"><label>Service Type</label><select name="srv"><option>SURFACE</option><option>AIR</option><option>EXPRESS</option></select></div>
                <div style="grid-column: span 3;"><label>Info / Remarks</label><input name="info"></div>
                <div><label>Freight(₹)</label><input type="number" step="0.01" name="fr" id="fr" value="0.0" oninput="manualCalc()" required></div>
                <div><label>Tax(%)</label><input type="number" name="tax" id="tax" value="18" oninput="manualCalc()" required></div>
                <div><label>Total(₹)</label><input type="number" step="0.01" name="amt" id="amt" value="0.0" readonly style="background:#E8F5E9; font-weight:bold; color:#2E7D32;"></div>
            </div>
            <div id="calc_hint" style="color:#C9A24B; font-weight:bold; margin-top:10px; font-size:12px;">Auto-Rate API Ready...</div>
            <button type="submit" class="btn btn-gold" style="margin-top:10px; width:100%; font-size:16px; padding:12px;"><i class="fas fa-save"></i> SAVE SHIPMENT</button>
        </form>
        <script>
        document.getElementById('bdt').valueAsDate = new Date();
        function fetchRate() {
            let cid = document.getElementById('cid').value;
            if(cid) {
                let opt = document.getElementById('cid').options[document.getElementById('cid').selectedIndex];
                document.getElementById('ost').value = opt.getAttribute('data-state');
            }
            let data = { cust_id: cid, ostate: document.getElementById('ost').value, dstate: document.getElementById('dst').value, wt: document.getElementById('wt').value, fr: 0 };
            fetch('/api/calc_rate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) })
            .then(r => r.json()).then(res => {
                document.getElementById('fr').value = res.freight; document.getElementById('tax').value = res.tax_rate; document.getElementById('amt').value = res.total;
                document.getElementById('calc_hint').innerText = `API Hit: Taxable ₹${res.taxable} + GST ₹${res.gst} (Surcharge applied if any)`;
            });
        }
        function manualCalc() {
            let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0;
            document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2);
            document.getElementById('calc_hint').innerText = "Manual Override Active";
        }
        </script>
    </div>
    """
    return render_page("New Booking", render_template_string(html, custs=custs, stations=stations))

@app.route('/shipments', methods=['GET', 'POST'])
@login_required
def shipments():
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("DELETE FROM scan_events WHERE shipment_id=%s", (request.args.get('delete'),))
            c.execute("DELETE FROM shipments WHERE id=%s", (request.args.get('delete'),))
            conn.commit(); flash("Shipment Deleted!", "success"); return redirect('/shipments')

    search = request.form.get('search', '').strip() if request.method == 'POST' else ''
    with conn.cursor() as c:
        q = "SELECT s.*, c.phone as cphone, c.name as cname FROM shipments s LEFT JOIN customers c ON s.customer_id = c.id WHERE 1=1"
        params = []
        if session.get('role') != 'ADMIN': q += " AND s.origin_name=%s"; params.append(session['branch'])
        if search: q += " AND (s.awb_no LIKE %s OR s.dest_station LIKE %s OR s.dest_name LIKE %s)"; params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        q += " ORDER BY s.id DESC LIMIT 300"
        c.execute(q, params); rows = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="padding:15px;"><form method="POST" style="display:flex; gap:10px;"><input name="search" value="{{ search }}" placeholder="Search AWB or Station..." style="flex:1;"><button type="submit" class="btn btn-blue">🔍 Search</button></form></div>
    <div class="card"><table style="font-size:12px;"><tr><th>AWB</th><th>Date</th><th>Shipper</th><th>Consignee</th><th>Station</th><th>Total</th><th>Status</th><th>Actions</th></tr>
        {% for r in rows %}<tr>
            <td style="color:#0E8A6D;"><strong>{{ r.awb_no }}</strong></td><td>{{ r.booking_date }}</td><td>{{ r.cname or r.origin_name }}</td><td>{{ r.dest_name }}</td><td>{{ r.dest_station }}</td><td>₹{{ r.total_amount }}</td>
            <td><span class="badge">{{ r.status }}</span></td>
            <td>
                {% set ph = r.dest_phone if r.dest_phone else r.cphone %}
                {% if ph %}<a href="https://wa.me/91{{ ph|replace(' ', '')|replace('-', '')[-10:] }}?text=Track%20AGC%20Parcel:%20https://pagcerp.cgsmart.in/track?awb={{ r.awb_no }}" target="_blank" class="btn" style="background:#12B76A; padding:4px; font-size:11px;"><i class="fab fa-whatsapp"></i></a>{% endif %}
                <a href="/print/label/{{ r.awb_no }}" target="_blank" class="btn btn-ghost" style="padding:4px; font-size:11px;">🖨️ Lbl</a>
                <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="btn btn-gold" style="padding:4px; font-size:11px;">🧾 Rec</a>
                <a href="/shipments?delete={{ r.id }}" onclick="return confirm('Delete this shipment?');" class="btn btn-red" style="padding:4px; font-size:11px;"><i class="fas fa-trash"></i></a>
            </td>
        </tr>{% endfor %}</table></div>
    """
    return render_page("Shipments Management", render_template_string(html, rows=rows, search=search))

# ==========================================
# 📤 7. OUTWARD HUB & EXCEL IMPORT
# ==========================================
@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    conn = get_db()
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("DELETE FROM outward_register WHERE id=%s", (request.args.get('delete'),))
            conn.commit(); return redirect(f"/outward?date={request.args.get('date', current_date)}")
            
    if request.args.get('unfinalize'):
        mid = request.args.get('unfinalize')
        with conn.cursor() as c:
            c.execute("SELECT manifest_no FROM manifests WHERE id=%s", (mid,))
            m = c.fetchone()
            if m:
                c.execute("UPDATE outward_register SET finalized=0, manifest_no=NULL, outward_no=NULL WHERE manifest_no=%s", (m['manifest_no'],))
                c.execute("DELETE FROM manifest_items WHERE manifest_id=%s", (mid,))
                c.execute("DELETE FROM manifests WHERE id=%s", (mid,))
            conn.commit(); flash("✅ Manifest Unfinalized! Items moved back to pending.", "success")
        return redirect('/outward')

    if request.method == 'POST' and request.form.get('action') == 'save_entry':
        o_date = request.form.get('out_date', current_date)
        o_station = request.form.get('out_station', session.get('branch', 'NOHAR')).upper()
        awb = request.form.get('awb', '').strip().upper()
        dest_input = request.form.get('dest', '').strip().upper()
        wt_input = float(request.form.get('weight', '0') or 0)
        info = request.form.get('info', '')
        network = request.form.get('network', 'SELF').upper()
        net_awb = request.form.get('network_awb', '').upper()
        bag_no = request.form.get('bag_no', '').upper()
        pcs = int(request.form.get('pcs', '1') or 1)
        
        if awb:
            with conn.cursor() as c:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (o_station,))
                
                if awb.startswith("BAG"):
                    c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb,))
                    b_items = c.fetchall()
                    if not b_items: flash(f"Bag {awb} is empty or invalid.", "error")
                    else:
                        for bi in b_items:
                            sub_awb = bi['awb_no']
                            c.execute("SELECT dest_station, weight_kg, quantity FROM shipments WHERE awb_no=%s", (sub_awb,))
                            s = c.fetchone()
                            s_wt = s['weight_kg'] if s and s['weight_kg'] else 1.0; s_dst = s['dest_station'] if s and s['dest_station'] else 'UNKNOWN'
                            s_pcs = s['quantity'] if s and s['quantity'] else 1
                            if not c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND finalized=0", (sub_awb,)):
                                c.execute("""INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, pcs, network, network_awb, bag_no, info, finalized) 
                                             VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)""", 
                                          (o_date, sub_awb, session['branch'], o_station, s_dst, s_wt, s_pcs, network, net_awb, awb, f"Unpacked from {awb}"))
                        flash(f"✅ Bag {awb} unpacked into Outward.", "success")
                else:
                    if c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND finalized=0", (awb,)):
                        flash(f"AWB {awb} is already in pending list!", "error")
                    else:
                        c.execute("SELECT id, dest_station, dest_name, weight_kg FROM shipments WHERE awb_no=%s", (awb,))
                        s = c.fetchone()
                        
                        final_dest = dest_input if dest_input else (s['dest_station'] if s and s['dest_station'] else (s['dest_name'] if s and s['dest_name'] else 'UNKNOWN'))
                        final_wt = wt_input if wt_input > 0 else (s['weight_kg'] if s and s['weight_kg'] else 1.0)
                        
                        if final_dest and final_dest != 'UNKNOWN': c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (final_dest,))
                        if s: c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s WHERE awb_no=%s", (o_station, awb))
                        c.execute("""INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, pcs, network, network_awb, bag_no, info, finalized) 
                                     VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)""", 
                                  (o_date, awb, session['branch'], o_station, final_dest, final_wt, pcs, network, net_awb, bag_no, info))
                conn.commit()
            return redirect(f"/outward?date={o_date}&station={o_station}")

    if request.method == 'POST' and request.form.get('action') == 'finalize':
        o_date = request.form.get('out_date', current_date)
        o_station = request.form.get('out_station', session.get('branch', 'NOHAR')).upper()
        vcl = request.form.get('vehicle_no', '')
        d_ph = request.form.get('driver_phone', '')
        seal = request.form.get('seal_no', '')
        with conn.cursor() as c:
            c.execute("SELECT id, awb_no FROM outward_register WHERE entry_date=%s AND out_station=%s AND origin_station=%s AND finalized=0", (o_date, o_station, session['branch']))
            pending = c.fetchall()
            if pending:
                ono = get_seq("outward", "OUT", 6); mno = get_seq("manifest", "MF", 7)
                c.execute("INSERT INTO manifests(manifest_no, manifest_type, from_location, to_location, vehicle_no, driver_phone, seal_no, status) VALUES(%s, 'OUTWARD', %s, %s, %s, %s, %s, 'OPEN')", 
                          (mno, session['branch'], o_station, vcl, d_ph, seal))
                mid = c.lastrowid
                for p in pending:
                    c.execute("UPDATE outward_register SET finalized=1, outward_no=%s, manifest_no=%s WHERE id=%s", (ono, mno, p['id']))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (p['awb_no'],))
                    s_row = c.fetchone()
                    if s_row:
                        c.execute("INSERT INTO manifest_items(manifest_id, shipment_id) VALUES(%s, %s)", (mid, s_row['id']))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'OUTWARD', %s)", (s_row['id'], session['branch']))
                conn.commit(); flash(f"✅ {ono} | {mno} Generated Successfully!", "success")
            else:
                flash("No pending entries to finalize.", "error")
        return redirect(f"/outward?date={o_date}&station={o_station}")

    f_date = request.args.get('date', current_date)
    f_station = request.args.get('station', session.get('branch', 'NOHAR')).upper()

    with conn.cursor() as c:
        c.execute("SELECT id, awb_no, destination, weight, info, pcs, network, bag_no FROM outward_register WHERE entry_date=%s AND out_station=%s AND origin_station=%s AND finalized=0 ORDER BY id DESC", (f_date, f_station, session['branch']))
        pending_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = [r['name'] for r in c.fetchall()]
        
        q_m = "SELECT manifest_no, created_at, from_location, to_location, vehicle_no, driver_phone, seal_no, status, id FROM manifests WHERE manifest_type='OUTWARD'"
        params_m = []
        if session.get('role') != 'ADMIN': 
            q_m += " AND from_location=%s"
            params_m.append(session['branch'])
        c.execute(q_m + " ORDER BY id DESC LIMIT 10", params_m)
        mans = c.fetchall()
    conn.close()
    
    html = """
    <div style="display:flex; gap:5px; margin-bottom:15px; border-bottom: 1px solid #334155;">
        <button class="btn" onclick="switchTab('new')" id="tab-new" style="background:#0E8A6D; border-radius:8px 8px 0 0; padding:10px 20px;"><i class="fas fa-box-open"></i> New Entry Finalize</button>
        <button class="btn btn-ghost" onclick="switchTab('history')" id="tab-history" style="border:none; border-radius:8px 8px 0 0; padding:10px 20px;"><i class="fas fa-list-alt"></i> Manifests History</button>
    </div>

    <div class="card" id="content-new" style="padding:10px 15px;">
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:15px; padding-bottom:15px; border-bottom:1px solid #334155;">
            <label style="margin:0;">Date</label><input type="date" id="ui_date" value="{{ f_date }}" onchange="reloadPage()" style="width:130px;">
            <label style="margin:0; margin-left:10px;">Station</label><input list="station_list" id="ui_station" value="{{ f_station }}" onchange="reloadPage()" style="width:180px; text-transform:uppercase;">
            <div style="flex:1;"></div>
            <button class="btn btn-blue" onclick="window.open('/master_bag', '_blank')">🎒 Create Master Bag</button>
        </div>

        <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; background:#0F172A; padding:5px;">
            <label style="margin:0; color:#cbd5e1;">Network:</label>
            <select id="ui_network" style="width:130px;"><option>SELF</option><option>BLUEDART</option><option>DELHIVERY</option></select>
            <label style="margin:0; color:#cbd5e1; margin-left:10px;">Net AWB:</label>
            <input type="text" id="ui_net_awb" placeholder="Optional" style="width:120px;">
            <label style="margin:0; color:#cbd5e1; margin-left:10px;">Bag No:</label>
            <input type="text" id="ui_bag_no" placeholder="Bag No" style="width:120px; text-transform:uppercase;">
            <label style="margin:0; color:#cbd5e1; margin-left:10px;">Pcs:</label>
            <input type="number" id="ui_pcs" value="1" style="width:80px;">
        </div>

        <form method="POST" id="entryForm" style="display:flex; align-items:center; gap:10px; background:#1E293B; border:1px solid #475569; padding:5px 10px; border-radius:6px; margin-bottom:10px;">
            <input type="hidden" name="action" value="save_entry">
            <input type="hidden" name="out_date" id="hdn_date">
            <input type="hidden" name="out_station" id="hdn_station">
            <input type="hidden" name="network" id="hdn_network">
            <input type="hidden" name="network_awb" id="hdn_net_awb">
            <input type="hidden" name="bag_no" id="hdn_bag_no">
            <input type="hidden" name="pcs" id="hdn_pcs">
            
            <label style="margin:0; color:white;">AWB</label>
            <input type="text" name="awb" id="awb_input" placeholder="Scan/type AWB then Enter..." required autofocus style="flex:2;" onkeypress="checkEnter(event)">
            <label style="margin:0; margin-left:5px; color:white;">Dest</label><input type="text" name="dest" id="dest_input" list="station_list" placeholder="Dest Station" style="flex:1.5; text-transform:uppercase;" onkeypress="checkEnter(event)">
            <label style="margin:0; margin-left:5px; color:white;">Weight</label><input type="number" step="0.01" name="weight" id="wt_input" placeholder="0.00" style="width:80px;" onkeypress="checkEnter(event)">
            <label style="margin:0; margin-left:5px; color:white;">Info</label><input type="text" name="info" id="info_input" style="flex:2;" onkeypress="checkEnter(event)">
            <datalist id="station_list">{% for s in stations %}<option value="{{ s }}">{% endfor %}</datalist>
        </form>
        <button onclick="document.getElementById('entryForm').submit();" class="btn" style="background:#0284C7; width:100%; font-size:15px; padding:10px; margin-bottom:15px;">+ Save Entry</button>

        <h4 style="color:#D97706; margin-top:0; margin-bottom:5px;">Total Pending Entries: {{ pending_list|length }}</h4>
        <div style="height:300px; overflow-y:auto; border:1px solid #334155; border-radius:4px; background:#0F172A; margin-bottom:10px;">
            <table style="margin:0; width:100%;">
                <tr style="position:sticky; top:0; background:#1E293B; z-index:1;">
                    <th>ID</th><th>AWB</th><th>Dest</th><th>Pcs</th><th>Weight</th><th>Network</th><th>Bag</th><th>Info</th>
                </tr>
                {% for p in pending_list %}
                <tr onclick="selectRow(this, {{ p.id }})" style="cursor:pointer;" class="tbl-row">
                    <td>{{ p.id }}</td>
                    <td style="color:#38BDF8; font-weight:bold;">{{ p.awb_no }}</td>
                    <td>{{ p.destination }}</td>
                    <td>{{ p.pcs }}</td>
                    <td>{{ p.weight }}</td>
                    <td><span class="badge">{{ p.network }}</span></td>
                    <td>{{ p.bag_no }}</td>
                    <td>{{ p.info }}</td>
                </tr>
                {% else %}
                <tr><td colspan="8" style="text-align:center; color:#64748b; padding:30px;">No pending entries. Scan AWB to begin.</td></tr>
                {% endfor %}
            </table>
        </div>

        <form method="POST" id="finalizeForm" style="display:flex; gap:10px; margin-bottom:10px;">
            <input type="hidden" name="action" value="finalize">
            <input type="hidden" name="out_date" id="fin_date" value="{{ f_date }}">
            <input type="hidden" name="out_station" id="fin_station" value="{{ f_station }}">
            <input type="text" name="vehicle_no" placeholder="Vehicle No. (RJ-00-0000)" required style="flex:1;">
            <input type="text" name="driver_phone" placeholder="Driver Phone" style="flex:1;">
            <input type="text" name="seal_no" placeholder="Seal No" style="flex:1;">
            <button type="button" onclick="confirmFinalize()" class="btn btn-gold" style="flex:1; font-size:15px; letter-spacing:1px;"><i class="fas fa-flag-checkered"></i> FINALIZE + OUTWARD NO</button>
        </form>
    </div>

    <div class="card" id="content-history" style="display:none; padding:10px 15px;">
        <h3 style="margin-top:0;">Manifests History</h3>
        <table style="width:100%;">
            <tr><th>Manifest No</th><th>Date</th><th>Route</th><th>Vehicle</th><th>Actions</th></tr>
            {% for m in mans %}
            <tr>
                <td style="color:#38bdf8;"><strong>{{ m.manifest_no }}</strong></td><td>{{ m.created_at }}</td><td>{{ m.from_location }} &rarr; {{ m.to_location }}</td>
                <td>{{ m.vehicle_no or '-' }}<br><small>Ph: {{ m.driver_phone or '-' }} | Seal: {{ m.seal_no or '-' }}</small></td>
                <td>
                    <a href="/print/manifest/{{ m.id }}" target="_blank" class="btn btn-blue" style="padding:4px 8px; font-size:11px;">🖨️ Print</a>
                    <a href="/outward?unfinalize={{ m.id }}" onclick="return confirm('Is Manifest ko Unfinalize karein? Item wapas Pending box mein aayenge.');" class="btn btn-red" style="padding:4px 8px; font-size:11px;">🔓 Unfinalize</a>
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>

    <script>
    let selectedId = null;
    function switchTab(tab) {
        document.getElementById('content-new').style.display = 'none'; document.getElementById('content-history').style.display = 'none';
        document.getElementById('tab-new').style.background = 'transparent'; document.getElementById('tab-history').style.background = 'transparent';
        document.getElementById('content-' + tab).style.display = 'block'; document.getElementById('tab-' + tab).style.background = '#0E8A6D';
    }
    function reloadPage() {
        let d = document.getElementById('ui_date').value; let s = document.getElementById('ui_station').value;
        window.location.href = `/outward?date=${d}&station=${s}`;
    }
    function checkEnter(e) {
        if(e.key === 'Enter') {
            e.preventDefault();
            let src = e.target.id;
            if(src === 'awb_input') document.getElementById('dest_input').focus();
            else if(src === 'dest_input') document.getElementById('wt_input').focus();
            else if(src === 'wt_input') document.getElementById('info_input').focus();
            else if(src === 'info_input') document.getElementById('entryForm').submit();
        }
    }
    function selectRow(tr, id) {
        document.querySelectorAll('.tbl-row').forEach(r => r.style.background = 'transparent');
        tr.style.background = 'rgba(56,189,248,0.2)'; selectedId = id;
    }
    function confirmFinalize() {
        let count = {{ pending_list|length }};
        if(count === 0) { alert("No pending entries to finalize!"); return; }
        if(confirm(`Are you sure you want to finalize ${count} items and generate Manifest?`)) { document.getElementById('finalizeForm').submit(); }
    }
    document.getElementById('entryForm').addEventListener('submit', function() {
        document.getElementById('hdn_date').value = document.getElementById('ui_date').value;
        document.getElementById('hdn_station').value = document.getElementById('ui_station').value;
        document.getElementById('hdn_network').value = document.getElementById('ui_network').value;
        document.getElementById('hdn_net_awb').value = document.getElementById('ui_net_awb').value;
        document.getElementById('hdn_bag_no').value = document.getElementById('ui_bag_no').value;
        document.getElementById('hdn_pcs').value = document.getElementById('ui_pcs').value;
    });
    </script>
    """
    return render_page("OUTWARD HUB", render_template_string(html, pending_list=pending_list, mans=mans, stations=stations, f_date=f_date, f_station=f_station))

@app.route('/import_csv', methods=['GET', 'POST'])
@login_required
def import_csv():
    if session.get('role') != 'ADMIN': return redirect('/')
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'): flash("Invalid CSV file", "error"); return redirect('/import_csv')
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        reader = csv.DictReader(stream)
        headers = {k.strip().lower(): k for k in reader.fieldnames if k}
        conn = get_db(); added = 0
        with conn.cursor() as c:
            for row in reader:
                awb = row.get(headers.get("awb", "AWB")) or row.get("AWB")
                if not awb: continue
                awb = str(awb).strip().upper()
                c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                if c.fetchone(): continue
                
                dest = row.get(headers.get("dest", "Dest")) or row.get("Dest Station", "UNKNOWN")
                wt = row.get(headers.get("weight", "Weight")) or "1"
                tot = row.get(headers.get("amount", "Amount")) or "0"
                d = datetime.now().strftime("%Y-%m-%d")
                
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest.upper(),))
                c.execute("""INSERT INTO shipments(awb_no, dest_name, dest_station, weight_kg, total_amount, booking_date, status, current_location, service_type, origin_name) VALUES(%s, %s, %s, %s, %s, %s, 'BOOKED', 'Origin', 'SURFACE', %s)""", 
                          (awb, dest, dest.upper(), float(wt), float(tot), d, session['branch']))
                added += 1
            conn.commit()
        conn.close(); flash(f"🎉 Import Complete! {added} Parcels Booked.", "success")
    html = """<div class="card" style="max-width:500px; margin:auto; text-align:center;"><h3 style="color:#0E8A6D;"><i class="fas fa-file-csv"></i> Bulk CSV Import</h3><p style="color:#7A8699; font-size:13px; margin-bottom:20px;">Required Columns: <b>AWB</b>, <b>Dest</b>, <b>Weight</b>, <b>Amount</b></p><form method="POST" enctype="multipart/form-data"><input type="file" name="file" accept=".csv" required style="margin-bottom:15px; width:100%;"><button type="submit" class="btn btn-blue" style="width:100%; padding:12px;">Start Import</button></form></div>"""
    return render_page("Excel Import", render_template_string(html))

# ==========================================
# 🖨️ 8. EXACT OFFLINE PDF ENGINE (LABEL / MANIFEST REPLICA)
# ==========================================
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
    cv.saveState()
    cv.setFont("Helvetica-BoldOblique", 24); cv.setFillColor(HexColor("#004B87"))
    cv.drawString(x, y + 4*mm, "AGC")
    cv.setFont("Helvetica-Bold", 14); cv.setFillColor(HexColor("#000000"))
    cv.drawString(x, y - 4*mm, "Akash")
    cv.setFillColor(HexColor("#F26522")); cv.drawString(x + 13*mm, y - 4*mm, "Ganga")
    cv.setFont("Helvetica", 6); cv.setFillColor(HexColor("#004B87"))
    cv.drawString(x, y - 8*mm, "Integrity at work")
    cv.restoreState()

@app.route('/print/label/<awb>')
@login_required
def print_label_pdf(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT s.*, c.name as cname, c.address as caddr FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,))
        s = c.fetchone()
    conn.close()
    if not s: return "Not found"
    
    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=(101.6*mm, 152.4*mm))
    cv.setLineWidth(1)
    cv.rect(4*mm, 4*mm, 93.6*mm, 144*mm) 
    
    draw_agc_logo(cv, 6*mm, 136*mm)
    cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica", 5.5)
    cv.drawString(6*mm, 129*mm, "ISO 9001:2008 Certified Company")
    
    cv.setFont("Helvetica-Bold", 14); cv.drawRightString(95*mm, 141*mm, session.get('branch', 'HQ').upper())
    cv.setFont("Helvetica", 6); cv.drawRightString(95*mm, 137*mm, get_setting("company_name", "PANKAJ AGENCY"))
    cv.setFont("Helvetica-Bold", 8); cv.setFillColor(HexColor("#D97706"))
    cv.drawRightString(95*mm, 132*mm, "PREMIUM EXPRESS")
    cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica", 6)
    cv.drawRightString(95*mm, 128*mm, f"GSTIN: {get_setting('company_gstin', '')} | Ph: {get_setting('company_phone', '')}")
    
    cv.line(4*mm, 126*mm, 97.6*mm, 126*mm)
    
    cv.setFont("Helvetica-Bold", 7); cv.drawString(6*mm, 122*mm, "AWB NUMBER")
    cv.setFont("Helvetica-Bold", 16); cv.drawString(6*mm, 115*mm, s['awb_no'])
    cv.setFont("Helvetica", 7); cv.drawString(6*mm, 110*mm, s['awb_no'])
    
    draw_barcode_safe(cv, s['awb_no'], 45*mm, 111*mm, 12*mm)
    
    cv.line(4*mm, 106*mm, 97.6*mm, 106*mm)
    cv.line(35*mm, 106*mm, 35*mm, 94*mm); cv.line(65*mm, 106*mm, 65*mm, 94*mm)
    
    cv.setFont("Helvetica-Bold", 6); cv.drawString(6*mm, 103*mm, "ORIGIN")
    cv.setFont("Helvetica-Bold", 9); cv.drawString(6*mm, 97*mm, str(s.get('origin_name',''))[:15].upper())
    
    cv.setFont("Helvetica-Bold", 6); cv.drawString(36*mm, 103*mm, "SERVICE")
    cv.setFont("Helvetica-Bold", 9); cv.drawString(36*mm, 97*mm, str(s.get('service_type','SURFACE'))[:12].upper())
    
    cv.setFont("Helvetica-Bold", 6); cv.drawString(66*mm, 103*mm, "DESTINATION")
    cv.setFont("Helvetica-Bold", 9); cv.drawString(66*mm, 97*mm, str(s.get('dest_station', s.get('dest_name', '')))[:14].upper())
    
    cv.line(4*mm, 94*mm, 97.6*mm, 94*mm)
    cv.setFont("Helvetica-Bold", 6); cv.drawString(6*mm, 91*mm, "DELIVER TO")
    cv.setFont("Helvetica-Bold", 11); cv.drawString(6*mm, 85*mm, str(s.get('dest_name',''))[:40].upper())
    cv.setFont("Helvetica", 8)
    addr_lines = wrap_lines(cv, s.get('dest_address', ''), "Helvetica", 8, 90*mm)
    y_addr = 81
    for ln in addr_lines[:2]: cv.drawString(6*mm, y_addr*mm, ln); y_addr -= 4
    cv.setFont("Helvetica-Bold", 8); cv.drawString(6*mm, y_addr*mm, f"Ph: {s.get('dest_phone', '')}")
    
    cv.line(4*mm, 69*mm, 97.6*mm, 69*mm)
    cv.setFont("Helvetica-Bold", 6)
    cv.drawString(6*mm, 66*mm, "WEIGHT"); cv.drawString(26*mm, 66*mm, "PIECES"); cv.drawString(46*mm, 66*mm, "COD"); cv.drawString(71*mm, 66*mm, "DECLARED")
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(6*mm, 61*mm, f"{s.get('weight_kg', 1)} KG"); cv.drawString(26*mm, 61*mm, f"{s.get('quantity', 1)}"); cv.drawString(46*mm, 61*mm, f"Rs {s.get('cod_amount', 0)}"); cv.drawString(71*mm, 61*mm, f"Rs {s.get('declared_value', 0)}")
    
    cv.line(4*mm, 58*mm, 97.6*mm, 58*mm)
    cv.setFont("Helvetica-Bold", 6)
    cv.drawString(6*mm, 55*mm, "MODE"); cv.drawString(36*mm, 55*mm, "DEST CITY"); cv.drawString(66*mm, 55*mm, "BRANCH")
    cv.setFont("Helvetica-Bold", 8)
    cv.drawString(6*mm, 50*mm, str(s.get('service_type', 'SURFACE'))); cv.drawString(36*mm, 50*mm, str(s.get('dest_station', ''))[:14]); cv.drawString(66*mm, 50*mm, session.get('branch', 'Head Office')[:15])
    
    cv.line(4*mm, 47*mm, 97.6*mm, 47*mm)
    cv.setFont("Helvetica-Bold", 6); cv.drawString(6*mm, 44*mm, "SHIPPER")
    cv.setFont("Helvetica", 7); shipper = s.get('cname') if s.get('cname') else s.get('origin_name', '')
    cv.drawString(6*mm, 40*mm, f"{shipper[:35]}")
    
    cv.line(4*mm, 35*mm, 97.6*mm, 35*mm)
    cv.setFont("Helvetica", 6)
    cv.drawCentredString(50.8*mm, 31*mm, get_setting("terms_note", "Liability limited to declared value only. Subject to local jurisdiction."))
    cv.drawCentredString(50.8*mm, 27*mm, f"{get_setting('company_website', 'https://pagcerp.cgsmart.in')} | Computer Generated Label")
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Label_{awb}.pdf", mimetype='application/pdf')

@app.route('/print/receipt/<awb>')
@login_required
def print_receipt_pdf(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT s.*, c.name as cname, c.address as caddr FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,))
        s = c.fetchone()
    conn.close()
    if not s: return "Not found"

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFillColor(HexColor("#0B1F3A")); cv.rect(0, 800, 600, 45, fill=1, stroke=0)
    cv.setFillColor(HexColor("#D97706")); cv.rect(0, 795, 600, 5, fill=1, stroke=0)
    
    draw_agc_logo(cv, 30, 802)
    cv.setFillColor(HexColor("#FFFFFF")); cv.setFont("Helvetica-Bold", 12); cv.drawRightString(560, 810, "NON-NEGOTIABLE DOCKET")
    
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica", 10)
    cv.drawString(30, 775, get_setting("company_address", "Head Office: Nohar (Raj) - 335523"))
    cv.drawString(30, 755, f"Date: {s['booking_date']}")
    draw_barcode_safe(cv, s['awb_no'], 400, 750, 0.4*inch)
    cv.setFont("Helvetica-Bold", 14); cv.drawString(400, 735, s['awb_no'])
    
    cv.setStrokeColor(HexColor("#E1E6EE")); cv.setLineWidth(1)
    cv.roundRect(30, 600, 255, 120, 4); cv.setFillColor(HexColor("#F5F7FA")); cv.rect(31, 700, 253, 20, fill=1, stroke=0)
    cv.setFillColor(HexColor("#0B1F3A")); cv.setFont("Helvetica-Bold", 10); cv.drawString(35, 706, "CONSIGNOR (SHIPPER DETAILS):")
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 11)
    shipper_name = s.get('cname') if s.get('cname') else s.get('origin_name', '')
    cv.drawString(35, 680, str(shipper_name)[:40]); cv.setFont("Helvetica", 10); y_sh = 665
    for ln in wrap_lines(cv, str(s.get('origin_address', '')), "Helvetica", 10, 240)[:2]:
        cv.drawString(35, y_sh, ln); y_sh -= 15
    cv.drawString(35, y_sh, f"Ph: {s.get('origin_phone', '')}"); cv.drawString(35, y_sh-15, f"State: {s.get('origin_state_code', '')}")
    
    cv.roundRect(305, 600, 255, 120, 4); cv.setFillColor(HexColor("#F5F7FA")); cv.rect(306, 700, 253, 20, fill=1, stroke=0)
    cv.setFillColor(HexColor("#0B1F3A")); cv.setFont("Helvetica-Bold", 10); cv.drawString(310, 706, "CONSIGNEE (RECEIVER DETAILS):")
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 11); cv.drawString(310, 680, str(s.get('dest_name', ''))[:40])
    cv.setFont("Helvetica", 10); y_cn = 665
    for ln in wrap_lines(cv, s.get('dest_address', ''), "Helvetica", 10, 240)[:2]:
        cv.drawString(310, y_cn, ln); y_cn -= 15
    cv.drawString(310, y_cn, f"Ph: {s.get('dest_phone', '')}"); cv.drawString(310, y_cn-15, f"Dest Station: {s.get('dest_station', '')}")

    y_tbl = 560; cv.setFillColor(HexColor("#0E8A6D")); cv.rect(30, y_tbl, 530, 25, fill=1)
    cv.setFillColor(HexColor("#FFFFFF")); cv.setFont("Helvetica-Bold", 10)
    cv.drawString(35, y_tbl+8, "WEIGHT"); cv.drawString(100, y_tbl+8, "PIECES"); cv.drawString(160, y_tbl+8, "SERVICE")
    cv.drawString(240, y_tbl+8, "TAXABLE"); cv.drawString(320, y_tbl+8, "GST AMT"); cv.drawString(390, y_tbl+8, "COD AMT"); cv.drawString(470, y_tbl+8, "TOTAL (Rs)")

    y_tbl -= 30; cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 11)
    cv.drawString(35, y_tbl+6, f"{s.get('weight_kg', 1)} KG"); cv.drawString(100, y_tbl+6, str(s.get('quantity', 1)))
    cv.drawString(160, y_tbl+6, str(s.get('service_type', 'SURFACE'))); cv.drawString(240, y_tbl+6, f"{s.get('taxable_amount', 0):.2f}")
    gst_tot = float(s.get('cgst') or 0) + float(s.get('sgst') or 0) + float(s.get('igst') or 0)
    cv.drawString(320, y_tbl+6, f"{gst_tot:.2f}"); cv.drawString(390, y_tbl+6, f"{s.get('cod_amount', 0):.2f}")
    cv.setFillColor(HexColor("#D97706")); cv.setFont("Helvetica-Bold", 14); cv.drawString(470, y_tbl+4, f"{s.get('total_amount', 0):.2f}")

    y_tbl -= 40; cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 10)
    cv.drawString(30, y_tbl, f"Amount to be collected: Rs {s.get('total_amount', 0)}")
    cv.setFont("Helvetica", 8); cv.drawString(30, y_tbl-50, get_setting("terms_note", "DECLARATION: Goods are carried at Owner's Risk. Cash, Jewelry, Narcotics strictly prohibited."))
    cv.drawString(420, y_tbl-50, f"For {get_setting('company_name', 'PANKAJ AGENCY')}"); cv.drawString(420, y_tbl-80, "Authorised Signatory")

    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Receipt_{awb}.pdf", mimetype='application/pdf')

@app.route('/print/manifest/<int:mid>')
@login_required
def print_manifest_pdf(mid):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM manifests WHERE id=%s", (mid,))
        m = c.fetchone()
        c.execute("SELECT s.awb_no, s.dest_station, o.weight, o.pcs, o.network, o.network_awb, o.bag_no, o.info FROM manifest_items mi JOIN shipments s ON s.id=mi.shipment_id JOIN outward_register o ON o.awb_no=s.awb_no WHERE mi.manifest_id=%s", (mid,))
        items = c.fetchall()
    conn.close()

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 50, f"{get_setting('company_name', 'AKASH GANGA')} - OUTWARD MANIFEST")
    cv.setFont("Helvetica", 10); cv.drawString(40, h - 65, f"Manifest No: {m['manifest_no']}   |   Route: {m['from_location']} -> {m['to_location']}")
    cv.drawString(40, h - 80, f"Vehicle: {m.get('vehicle_no', 'N/A')}   |   Driver Ph: {m.get('driver_phone','')}   |   Seal: {m.get('seal_no','')}   |   Items: {len(items)}")
    draw_barcode_safe(cv, m['manifest_no'], w - 180, h - 70, 0.4 * inch)
    
    y = h - 110
    def draw_headers(curr_y):
        cv.setFillColorRGB(0.96, 0.97, 0.98); cv.rect(40, curr_y - 16, 250, 16, fill=1, stroke=0); cv.rect(305, curr_y - 16, 250, 16, fill=1, stroke=0)
        cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica-Bold", 7.5)
        cv.drawString(42, curr_y - 11, "#"); cv.drawString(60, curr_y - 11, "AWB & BARCODE"); cv.drawString(160, curr_y - 11, "DESTINATION"); cv.drawString(255, curr_y - 11, "WT")
        cv.drawString(307, curr_y - 11, "#"); cv.drawString(325, curr_y - 11, "AWB & BARCODE"); cv.drawString(425, curr_y - 11, "DESTINATION"); cv.drawString(520, curr_y - 11, "WT")
        
    draw_headers(y); y -= 16
    
    for i, it in enumerate(items):
        is_right = (i % 2 != 0); cx = 305 if is_right else 40
        if not is_right and y - 24 < 40:
            cv.showPage(); y = h - 50; draw_headers(y); y -= 16
        
        cv.setFillColorRGB(0,0,0); cv.setFont("Helvetica-Bold", 7.5)
        cv.drawString(cx + 2, y - 10, str(i + 1))
        cv.drawString(cx + 20, y - 9, it["awb_no"]); draw_barcode_safe(cv, it["awb_no"], cx + 20, y - 21, 0.16 * inch)
        cv.setFont("Helvetica", 7); cv.drawString(cx + 120, y - 14, str(it.get("dest_station", ""))[:18])
        cv.setFont("Helvetica-Bold", 7.5); cv.drawString(cx + 215, y - 14, f"{it.get('weight', 1)} KG")
        if is_right: y -= 24
            
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Manifest_{m['manifest_no']}.pdf", mimetype='application/pdf')

# ==========================================
# 🛑 DO NOT TOUCH - FLASK RUN
# ==========================================
if __name__ == '__main__':
    # For production, use: gunicorn -w 4 -b 0.0.0.0:5000 app:app
    app.run(host='0.0.0.0', debug=True, port=5000)
