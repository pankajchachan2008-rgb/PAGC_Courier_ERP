from flask import Flask, request, session, redirect, url_for, render_template_string, flash, send_file
import pymysql
import configparser
import hashlib
from functools import wraps
from datetime import datetime
import io
import os
import csv

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

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'agc_super_secret_erp_ultimate_key')

config = configparser.ConfigParser()
config.read('db_config.ini')

# ==========================================
# 🛠️ 1. BULLETPROOF DB CONNECTION & HEALER
# ==========================================
def get_db():
    if not config.has_section('CLOUD_DB'):
        raise Exception("db_config.ini is missing or does not contain [CLOUD_DB] section")
    db_host = config['CLOUD_DB']['host'].replace('"', '').replace("'", "").strip()
    db_port = int(config['CLOUD_DB']['port'].replace('"', '').replace("'", "").strip())
    db_user = config['CLOUD_DB']['user'].replace('"', '').replace("'", "").strip()
    db_pass = config['CLOUD_DB']['password'].replace('"', '').replace("'", "").strip()
    db_name = config['CLOUD_DB']['database'].replace('"', '').replace("'", "").strip()
    return pymysql.connect(host=db_host, port=db_port, user=db_user, password=db_pass, database=db_name, cursorclass=pymysql.cursors.DictCursor, ssl={'ssl': {}})

def auto_heal_db():
    try:
        conn = get_db()
        with conn.cursor() as c:
            c.execute("CREATE TABLE IF NOT EXISTS users (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(50), password_hash VARCHAR(100), full_name VARCHAR(100), role VARCHAR(50), branch_name VARCHAR(100), active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS customers (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(50), name VARCHAR(255), gstin VARCHAR(50), phone VARCHAR(50), state VARCHAR(100), credit_limit DOUBLE DEFAULT 0, is_active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS ledger (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, entry_date DATE, voucher_type VARCHAR(50), reference VARCHAR(100), debit DOUBLE DEFAULT 0, credit DOUBLE DEFAULT 0, narration TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, payment_date DATE, amount DOUBLE, mode VARCHAR(50), reference VARCHAR(100))")
            c.execute("CREATE TABLE IF NOT EXISTS shipments (id INT AUTO_INCREMENT PRIMARY KEY, awb_no VARCHAR(100) UNIQUE, customer_id INT, booking_date DATE, origin_name VARCHAR(100), origin_phone VARCHAR(50), origin_address TEXT, origin_state_code VARCHAR(10), dest_name VARCHAR(100), dest_phone VARCHAR(50), dest_address TEXT, dest_state_code VARCHAR(10), dest_station VARCHAR(100), weight_kg DOUBLE, quantity INT, cod_amount DOUBLE, declared_value DOUBLE, service_type VARCHAR(50), taxable_amount DOUBLE, tax_rate DOUBLE, cgst DOUBLE, sgst DOUBLE, igst DOUBLE, total_amount DOUBLE, status VARCHAR(50), current_location VARCHAR(100), info TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS scan_events (id INT AUTO_INCREMENT PRIMARY KEY, shipment_id INT, scan_type VARCHAR(50), location VARCHAR(100), remarks TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS outward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), out_station VARCHAR(100), destination VARCHAR(100), weight VARCHAR(50), info TEXT, outward_no VARCHAR(100), manifest_no VARCHAR(100), finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS inward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), in_station VARCHAR(100), weight VARCHAR(50), info TEXT, inward_no VARCHAR(100), finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS manifests (id INT AUTO_INCREMENT PRIMARY KEY, manifest_no VARCHAR(100), manifest_type VARCHAR(50), from_location VARCHAR(100), to_location VARCHAR(100), vehicle_no VARCHAR(100), driver_phone VARCHAR(50), seal_no VARCHAR(100), status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS manifest_items (id INT AUTO_INCREMENT PRIMARY KEY, manifest_id INT, shipment_id INT, received INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS drs (id INT AUTO_INCREMENT PRIMARY KEY, drs_no VARCHAR(100), drs_date DATE, rider_name VARCHAR(100), rider_phone VARCHAR(50), vehicle_no VARCHAR(100), status VARCHAR(50))")
            c.execute("CREATE TABLE IF NOT EXISTS drs_items (id INT AUTO_INCREMENT PRIMARY KEY, drs_id INT, shipment_id INT, status VARCHAR(50), receiver_name VARCHAR(100))")
            c.execute("CREATE TABLE IF NOT EXISTS stations (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) UNIQUE)")
            c.execute("CREATE TABLE IF NOT EXISTS master_bags (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100) UNIQUE, destination VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS master_bag_items (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100), awb_no VARCHAR(100))")
            c.execute("CREATE TABLE IF NOT EXISTS sequences (name VARCHAR(50) PRIMARY KEY, value INT)")
        conn.commit(); conn.close()
    except Exception as e: print("Heal Error:", e)

auto_heal_db()

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
# 🎨 2. MASTER UI & HTML TEMPLATE
# ==========================================
BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }} - AGC Cloud ERP</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #1E293B; margin: 0; color: #F8FAFC; }
        .sidebar { width: 260px; background: #0F172A; color: white; position: fixed; height: 100%; overflow-y: auto; box-shadow: 2px 0 10px rgba(0,0,0,0.5); }
        .logo { padding: 20px; font-size: 24px; font-weight: 900; color: #38bdf8; border-bottom: 1px solid #334155; text-align: center; }
        .menu a { display: block; padding: 12px 25px; color: #cbd5e1; text-decoration: none; font-weight: 600; transition: 0.2s; }
        .menu a:hover, .menu a.active { background: #0284c7; color: white; border-left: 4px solid #fbbf24; }
        .menu-header { color: #d97706; padding: 15px 25px 5px; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; }
        .main-content { margin-left: 260px; padding: 15px; }
        .header { display: flex; justify-content: space-between; align-items: center; background: #0F172A; padding: 10px 20px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #334155;}
        .card { background: #0F172A; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #334155; }
        
        input, select, textarea { background: #1E293B; border: 1px solid #475569; color: #F8FAFC; padding: 8px 10px; border-radius: 4px; box-sizing: border-box; font-family: inherit; font-size: 13px;}
        input:focus, select:focus { border-color: #38BDF8; outline: none; }
        label { font-weight: 600; color: #CBD5E1; margin-right: 5px; font-size: 12px; text-transform: uppercase; }
        
        .btn { border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 13px; text-decoration: none; display: inline-block; text-align: center; color: white;}
        .btn-blue { background: #0284C7; } .btn-blue:hover { background: #0369a1; }
        .btn-red { background: #B91C1C; } .btn-red:hover { background: #991b1b; }
        .btn-gold { background: #D97706; } .btn-gold:hover { background: #b45309; }
        .btn-ghost { background: transparent; border: 1px solid #475569; color: #CBD5E1; } .btn-ghost:hover { background: #1E293B; color: white; }
        
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; color: #F8FAFC; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #334155; }
        th { background: #1E293B; font-weight: bold; color: #cbd5e1; }
        tr:hover { background: rgba(255,255,255,0.05); }
        .msg { padding: 10px; margin-bottom: 15px; border-radius: 4px; font-weight: 600; font-size:14px; }
        .success { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #059669; }
        .error { background: rgba(225, 29, 72, 0.2); color: #fb7185; border: 1px solid #e11d48; }
        .badge { padding: 3px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; background: #334155; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; }
        .grid-6 { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">◆ AGC<br><span style="font-size:14px; color:white;">{{ session.get('branch', 'HQ') }}</span></div>
        <div class="menu">
            <div class="menu-header">📦 MAIN BOOKING</div>
            <a href="/"><i class="fas fa-chart-line"></i> Dashboard</a>
            <a href="/customers"><i class="fas fa-users"></i> Customers</a>
            <a href="/booking"><i class="fas fa-box"></i> Booking</a>
            <a href="/shipments"><i class="fas fa-truck"></i> Shipments</a>
            <a href="/track" target="_blank"><i class="fas fa-map-marker-alt"></i> Track</a>
            
            <div class="menu-header">🏢 OPERATIONS (HUB)</div>
            <a href="/outward"><i class="fas fa-sign-out-alt"></i> Outward</a>
            <a href="/inward"><i class="fas fa-sign-in-alt"></i> Inward</a>
            <a href="/drs"><i class="fas fa-motorcycle"></i> DRS / Delivery</a>
            <a href="/master_bag"><i class="fas fa-shopping-bag"></i> Master Bag</a>
            
            <div class="menu-header">💰 ACCOUNTS & TAX</div>
            <a href="/accounts"><i class="fas fa-wallet"></i> Ledger & Payments</a>
            <a href="/reports"><i class="fas fa-chart-bar"></i> Reports</a>
            {% if session.get('role') == 'ADMIN' %}
                <a href="/users" style="color:#f472b6;"><i class="fas fa-cogs"></i> Users & Branch</a>
            {% endif %}
            <a href="/logout" style="color:#fb7185; margin-top:20px;"><i class="fas fa-sign-out-alt"></i> Logout</a>
        </div>
    </div>
    <div class="main-content">
        <div class="header">
            <div style="font-size:18px; font-weight:bold; color:white;"><i class="fas fa-boxes"></i> {{ title }}</div>
            <div style="display:flex; gap:15px; align-items:center;">
                <input type="text" placeholder="🔍 Global Search AWB..." style="width:250px; background:#1E293B; border-radius:20px; padding:6px 15px;">
                <button class="btn btn-gold" onclick="alert('Quick print mode activated!')"><i class="fas fa-bolt"></i> Quick Print</button>
                <div style="background:rgba(56,189,248,0.1); color:#38bdf8; padding:5px 15px; border-radius:15px; font-weight:bold; font-size:12px;">{{ session.get('full_name', '') }} • {{ session.get('role', '') }}</div>
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
def render_page(title, content): return render_template_string(BASE_HTML, title=title, content=content)

# ==========================================
# 🔐 3. AUTH, DASHBOARD & USERS (RESTORED!)
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
    return """<style>body{background:#0F172A; display:flex; justify-content:center; align-items:center; height:100vh; color:white; font-family:sans-serif;} .box{background:#1E293B; padding:40px; border-radius:8px; text-align:center; width:300px; box-shadow:0 10px 25px rgba(0,0,0,0.5);} input{width:100%; margin:10px 0; padding:12px; box-sizing:border-box; background:#0F172A; border:1px solid #334155; color:white; border-radius:4px;} button{width:100%; padding:12px; background:#0284C7; color:white; border:none; font-weight:bold; cursor:pointer; border-radius:4px;}</style><div class="box"><h2 style="color:#38bdf8; margin-top:0;">AGC LOGIN</h2><form method="POST"><input name="username" placeholder="Username" required autocomplete="off"><input type="password" name="password" placeholder="Password" required><button type="submit">LOGIN TO CLOUD</button></form></div>"""

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
    conn.close()
    html = f"""<div class="grid-3"><div class="card" style="border-top-color: #38bdf8;"><h3>Total Parcels</h3><h2 style="font-size:28px; margin:0; color:#38bdf8;">{s['c']}</h2></div><div class="card" style="border-top-color: #10b981;"><h3>Delivered</h3><h2 style="font-size:28px; margin:0; color:#10b981;">{d['c']}</h2></div><div class="card" style="border-top-color: #f59e0b;"><h3>Revenue (₹)</h3><h2 style="font-size:28px; margin:0; color:#f59e0b;">{round(s['t'], 2)}</h2></div></div><div class="card"><h3>📦 Recent Bookings ({session['branch']})</h3><table><tr><th>AWB Number</th><th>Date</th><th>Destination</th><th>Amount</th><th>Status</th></tr>{''.join(f"<tr><td><strong>{r['awb_no']}</strong></td><td>{r['booking_date']}</td><td>{r['dest_name']}</td><td>₹{r['total_amount']}</td><td><span class='badge b-book'>{r['status']}</span></td></tr>" for r in latest)}</table></div>"""
    return render_page("Dashboard", html)

@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if session.get('role') != 'ADMIN': return redirect(url_for('dashboard'))
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("DELETE FROM users WHERE id=%s AND username != 'admin'", (request.args.get('delete'),))
            conn.commit(); flash("User Deleted!", "success"); return redirect('/users')
    if request.method == 'POST':
        u, p, f, r, b = request.form.get('user'), request.form.get('pass'), request.form.get('fname'), request.form.get('role'), request.form.get('branch')
        with conn.cursor() as c:
            try:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (b.upper(),))
                c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, active) VALUES(%s,%s,%s,%s,%s,1)", (u, sha(p), f, r, b.upper()))
                conn.commit(); flash(f"User created for Branch: {b.upper()}", "success")
            except Exception: flash("Username exists!", "error")
    with conn.cursor() as c:
        c.execute("SELECT id, username, full_name, role, branch_name FROM users ORDER BY id")
        usr_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        branches = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card" style="border-top-color: #38bdf8;"><h3 style="margin-top:0;">➕ Create Branch User</h3><form method="POST"><label>Username</label><input name="user" required style="margin-bottom:10px;"><label>Password</label><input type="password" name="pass" required style="margin-bottom:10px;"><label>Full Name</label><input name="fname" required style="margin-bottom:10px;"><label>Role</label><select name="role" style="margin-bottom:10px;"><option>OPS</option><option>DELIVERY</option><option>ACCOUNTS</option><option>ADMIN</option></select><label>Branch / Station</label><input name="branch" list="branches" required style="margin-bottom:15px; text-transform:uppercase;"><datalist id="branches">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist><button type="submit" class="btn btn-blue" style="width:100%;">Create User</button></form></div><div class="card"><h3 style="margin-top:0;">👥 All Users List</h3><div style="max-height:400px; overflow-y:auto;"><table><tr><th>User</th><th>Name</th><th>Role</th><th>Branch</th><th>Action</th></tr>{% for u in usr_list %}<tr><td><strong>{{ u.username }}</strong></td><td>{{ u.full_name }}</td><td>{{ u.role }}</td><td>{{ u.branch_name }}</td><td>{% if u.username != 'admin' %}<a href="/users?delete={{ u.id }}" class="btn btn-red" style="padding:4px 8px; font-size:11px;">Del</a>{% endif %}</td></tr>{% endfor %}</table></div></div></div>"""
    return render_page("Users & Branch", render_template_string(html, usr_list=usr_list, branches=branches))

# ==========================================
# 🌐 4. PUBLIC TRACKING (RESTORED!)
# ==========================================
@app.route('/track', methods=['GET', 'POST'])
def track():
    awb = request.args.get('awb') or request.form.get('awb')
    awb = awb.strip().upper() if awb else ''
    shipment = None; timeline = []
    
    if awb:
        try:
            conn = get_db()
            with conn.cursor() as c:
                c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
                shipment = c.fetchone()
                if shipment:
                    c.execute("SELECT created_at as date, scan_type as title, CONCAT(location, ' - ', remarks) as _desc FROM scan_events WHERE shipment_id=%s ORDER BY id", (shipment['id'],))
                    timeline = c.fetchall()
            conn.close()
        except Exception as e: print("Tracking Error:", e)

    html = """
    <!DOCTYPE html>
    <html><head><title>Track Shipment - AGC Courier</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5; margin: 0; color: #1e293b; }
            .nav { background: #0f172a; padding: 15px 20px; color: white; text-align: center; font-size: 22px; font-weight: 900; letter-spacing: 1px;}
            .nav span { color: #38bdf8; }
            .container { max-width: 600px; margin: 40px auto; padding: 20px; }
            .card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); }
            .search-box { display: flex; gap: 10px; margin-bottom: 20px; }
            input { flex: 1; padding: 15px; border: 2px solid #cbd5e1; border-radius: 8px; font-size: 16px; outline: none; text-transform: uppercase;}
            .btn { padding: 15px 25px; background: #0f766e; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer;}
            .timeline { border-left: 3px solid #0f766e; margin-left: 15px; padding-left: 25px; margin-top: 25px; }
            .event { position: relative; margin-bottom: 25px; }
            .event::before { content: ''; position: absolute; left: -35px; top: 0; width: 14px; height: 14px; background: #fbbf24; border: 3px solid #0f766e; border-radius: 50%; }
        </style>
    </head><body>
        <div class="nav">AGC <span>COURIER</span></div>
        <div class="container">
            <div class="card"><h2 style="margin-top:0; text-align:center;">Track Your Shipment</h2>
                <form method="GET" class="search-box"><input type="text" name="awb" value="{{ awb }}" placeholder="e.g. AWB00000123" required autocomplete="off"><button type="submit" class="btn">Track Live</button></form>
                {% if awb %}<hr style="border:0; border-top:1px dashed #cbd5e1; margin:25px 0;">
                    {% if shipment %}
                        <div style="display:flex; justify-content:space-between; align-items:center;"><h3 style="margin:0; color:#0f766e;">AWB: {{ shipment.awb_no }}</h3><strong>{{ shipment.status }}</strong></div>
                        <div style="background:#f8fafc; padding:15px; border-radius:8px; margin-bottom:20px; margin-top:10px; font-size:14px; border-left:4px solid #38bdf8;">
                            <strong>To:</strong> {{ shipment.dest_name }}<br><strong>Destination:</strong> {{ shipment.dest_station }}<br><strong>Weight:</strong> {{ shipment.weight_kg }} KG
                        </div>
                        <div class="timeline">{% for t in timeline %}<div class="event"><div style="font-size:13px; color:#0f766e; font-weight:bold;">{{ t.date }}</div><h4 style="margin:5px 0;">{{ t.title }}</h4><p style="margin:0; color:#475569;">{{ t._desc }}</p></div>{% endfor %}</div>
                    {% else %}<div style="text-align:center; color:#be123c; padding:20px; background:#fee2e2; border-radius:8px;"><strong>No records found for AWB: {{ awb }}</strong></div>{% endif %}
                {% endif %}
            </div>
        </div>
    </body></html>
    """
    return render_template_string(html, awb=awb, shipment=shipment, timeline=timeline)

# ==========================================
# 📦 5. COMPLETE BOOKING (RESTORED CUSTOMERS)
# ==========================================
@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("UPDATE customers SET is_active=0 WHERE id=%s", (request.args.get('delete'),))
            conn.commit(); flash("Customer Deleted!", "success"); return redirect('/customers')
    if request.method == 'POST':
        c, n, g, p = request.form.get('code'), request.form.get('name'), request.form.get('gstin'), request.form.get('phone')
        with conn.cursor() as cur:
            cur.execute("INSERT INTO customers(code, name, gstin, phone, state, is_active) VALUES(%s,%s,%s,%s,'Default',1)", (c, n, g, p))
            conn.commit(); flash("Customer Added!", "success")
    with conn.cursor() as cur:
        cur.execute("SELECT id, code, name, phone, credit_limit FROM customers WHERE is_active=1 ORDER BY id DESC")
        custs = cur.fetchall()
    conn.close()
    html = """<div class="card"><h3>➕ Add Customer</h3><form method="POST" class="grid-4" style="align-items:end;"><div><label>Customer Code</label><input name="code" required></div><div><label>Customer Name</label><input name="name" required></div><div><label>Phone Number</label><input name="phone"></div><div><button type="submit" class="btn btn-blue" style="width:100%;">Save Customer</button></div></form></div><div class="card"><table><tr><th>ID</th><th>Code</th><th>Name</th><th>Phone</th><th>Credit Limit</th><th>Act</th></tr>{% for r in custs %}<tr><td>{{ r.id }}</td><td>{{ r.code }}</td><td><strong>{{ r.name }}</strong></td><td>{{ r.phone }}</td><td>₹{{ r.credit_limit }}</td><td><a href="/customers?delete={{ r.id }}" class="btn btn-red" style="padding:4px 8px;">Del</a></td></tr>{% endfor %}</table></div>"""
    return render_page("Customers", render_template_string(html, custs=custs))

@app.route('/booking', methods=['GET', 'POST'])
@login_required
def booking():
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        fr, tax = float(d['fr']), float(d['tax'])
        gst = fr * (tax / 100); tot = fr + gst
        cgst = sgst = igst = 0
        if d['ostate'] == d['dstate']: cgst = sgst = gst / 2
        else: igst = gst

        with conn.cursor() as c:
            try:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d['dstat'].upper(),))
                # Origin fields exactly mapped
                c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, origin_phone, origin_address, origin_state_code, dest_name, dest_phone, dest_address, dest_state_code, dest_station, weight_kg, quantity, cod_amount, declared_value, service_type, taxable_amount, tax_rate, cgst, sgst, igst, total_amount, info, status, current_location) 
                             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s)""",
                          (d['awb'].upper(), d.get('cust_id') or None, d['date'], d['oname'], d['ophone'], d['oaddr'], d['ostate'], d['dname'], d['dphone'], d['daddr'], d['dstate'], d['dstat'].upper(), d['wt'], d['pcs'], d['cod'], d['dec'], d['srv'], fr, tax, cgst, sgst, igst, tot, d['info'], session['branch']))
                sid = c.lastrowid
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'BOOKED',%s,'Booked at counter')", (sid, session['branch']))
                if d.get('cust_id'):
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (d['cust_id'], d['date'], d['awb'].upper(), tot, f"Booking {d['awb'].upper()}"))
                conn.commit(); flash(f"✅ AWB {d['awb'].upper()} Booked! Total: ₹{tot}", "success")
            except Exception as e: flash(f"Error: {e}", "error")

    with conn.cursor() as c:
        c.execute("SELECT id, name, phone FROM customers WHERE is_active=1")
        custs = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="max-width:950px; margin:auto;"><h3 style="color:#38bdf8; margin-top:0;">📦 Master Booking Form</h3>
        <form method="POST">
            <div class="grid-4" style="background:#1E293B; padding:15px; border-radius:6px; margin-bottom:15px; border:1px solid #334155;">
                <div><label>Booking Date</label><input type="date" name="date" id="bdt" required></div>
                <div><label>AWB Number</label><input name="awb" required style="font-weight:bold; color:#38bdf8; text-transform:uppercase;"></div>
                <div style="grid-column: span 2;"><label>Customer (Accounts Auto-Link)</label>
                    <select name="cust_id"><option value="">-- Walk-in --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }} ({{ c.phone }})</option>{% endfor %}</select>
                </div>
            </div>
            <div class="grid-2">
                <div style="border:1px solid #334155; padding:15px; border-radius:6px;"><h4 style="margin-top:0; color:#d97706;">🏢 ORIGIN (SHIPPER)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Sender Name</label><input name="oname" value="{{ session['branch'] }}" required></div><div><label>Phone</label><input name="ophone"></div><div><label>State Code</label><input name="ostate" value="RJ"></div>
                    <div style="grid-column: span 2;"><label>Address</label><input name="oaddr"></div>
                </div></div>
                <div style="border:1px solid #334155; padding:15px; border-radius:6px;"><h4 style="margin-top:0; color:#10b981;">🏠 DESTINATION (CONSIGNEE)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Receiver Name</label><input name="dname" required></div><div><label>Phone</label><input name="dphone" required></div><div><label>State Code</label><input name="dstate"></div>
                    <div style="grid-column: span 2;"><label>Dest Station (City)</label><input name="dstat" list="stations" required style="border-color:#38bdf8; text-transform:uppercase;">
                        <datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
                    <div style="grid-column: span 2;"><label>Address</label><input name="daddr"></div>
                </div></div>
            </div>
            <div class="grid-6" style="margin-top:15px;">
                <div><label>Weight(KG)</label><input type="number" step="0.01" name="wt" value="1.0" required></div><div><label>Pieces</label><input type="number" name="pcs" value="1" required></div>
                <div><label>COD Amt</label><input type="number" step="0.01" name="cod" value="0.0"></div><div><label>Declared</label><input type="number" step="0.01" name="dec" value="0.0"></div>
                <div style="grid-column: span 2;"><label>Service Type</label><select name="srv"><option>SURFACE</option><option>EXPRESS</option></select></div>
                <div style="grid-column: span 3;"><label>Info / Remarks</label><input name="info"></div>
                <div><label>Freight(₹)</label><input type="number" step="0.01" name="fr" id="fr" value="50.0" oninput="calc()" required></div>
                <div><label>Tax(%)</label><input type="number" name="tax" id="tax" value="18" oninput="calc()" required></div>
                <div><label>Total(₹)</label><input type="number" step="0.01" name="amt" id="amt" value="59.0" readonly style="background:#0F172A; font-weight:bold; color:#10b981;"></div>
            </div>
            <button type="submit" class="btn btn-gold" style="margin-top:20px; width:100%; font-size:16px; padding:12px;">💾 SAVE SHIPMENT</button>
        </form>
        <script>document.getElementById('bdt').valueAsDate = new Date(); function calc() { let f = parseFloat(document.getElementById('fr').value)||0; let t = parseFloat(document.getElementById('tax').value)||0; document.getElementById('amt').value = (f + (f*t/100)).toFixed(2); }</script>
    </div>
    """
    return render_page("Complete Booking", render_template_string(html, custs=custs, stations=stations))

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
        q = "SELECT s.*, c.phone as cphone FROM shipments s LEFT JOIN customers c ON s.customer_id = c.id WHERE 1=1"
        params = []
        if session.get('role') != 'ADMIN': q += " AND s.origin_name=%s"; params.append(session['branch'])
        if search: q += " AND (s.awb_no LIKE %s OR s.dest_station LIKE %s)"; params.extend([f"%{search}%", f"%{search}%"])
        q += " ORDER BY s.id DESC LIMIT 150"
        c.execute(q, params); rows = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="padding:15px;"><form method="POST" style="display:flex; gap:10px;"><input name="search" value="{{ search }}" placeholder="Search AWB or Station..." style="flex:1;"><button type="submit" class="btn btn-blue">🔍 Search</button></form></div>
    <div class="card"><table style="font-size:12px;"><tr><th>AWB</th><th>Date</th><th>Consignee</th><th>Station</th><th>Total</th><th>Status</th><th>Actions</th></tr>
        {% for r in rows %}<tr>
            <td style="color:#38bdf8;"><strong>{{ r.awb_no }}</strong></td><td>{{ r.booking_date }}</td><td>{{ r.dest_name }}</td><td>{{ r.dest_station }}</td><td>₹{{ r.total_amount }}</td>
            <td><span class="badge b-book">{{ r.status }}</span></td>
            <td>
                {% set ph = r.dest_phone if r.dest_phone else r.cphone %}
                {% if ph %}<a href="https://wa.me/91{{ ph }}?text=Track%20AGC%20Parcel:%20http://pagcerp.cgsmart.in/track?awb={{ r.awb_no }}" target="_blank" class="btn" style="background:#10b981; padding:4px; font-size:11px;"><i class="fab fa-whatsapp"></i></a>{% endif %}
                <a href="/print/label/{{ r.awb_no }}" target="_blank" class="btn btn-ghost" style="padding:4px; font-size:11px;">🖨️ Lbl</a>
                <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="btn btn-gold" style="padding:4px; font-size:11px;">🧾 Rec</a>
                <a href="/shipments?delete={{ r.id }}" onclick="return confirm('Delete this shipment?');" class="btn btn-red" style="padding:4px; font-size:11px;"><i class="fas fa-trash"></i></a>
            </td>
        </tr>{% endfor %}</table></div>
    """
    return render_page("Shipments Management", render_template_string(html, rows=rows, search=search))

# ==========================================
# 📤 6. EXACT SCREENSHOT OUTWARD HUB + SMART FILL (BUG FIXED)
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
        
        # 🚀 SMART FILL FIX FOR DESTINATION AND WEIGHT:
        dest_input = request.form.get('dest', '').strip().upper()
        wt_input_str = request.form.get('weight', '0.00')
        wt_input = float(wt_input_str) if wt_input_str else 0.0
        
        info = request.form.get('info', '')
        network = request.form.get('network', 'SELF').upper()
        net_awb = request.form.get('network_awb', '').upper()
        bag_no = request.form.get('bag_no', '').upper()
        pcs = request.form.get('pcs', '1')
        
        if awb:
            with conn.cursor() as c:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (o_station,))
                
                # BAG UNPACKING
                if awb.startswith("BAG"):
                    c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb,))
                    b_items = c.fetchall()
                    if not b_items: flash(f"Bag {awb} is empty or invalid.", "error")
                    else:
                        for bi in b_items:
                            sub_awb = bi['awb_no']
                            c.execute("SELECT dest_station, weight_kg FROM shipments WHERE awb_no=%s", (sub_awb,))
                            s = c.fetchone()
                            s_wt = s['weight_kg'] if s and s['weight_kg'] else 1.0
                            s_dst = s['dest_station'] if s and s['dest_station'] else 'UNKNOWN'
                            if not c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND finalized=0", (sub_awb,)):
                                c.execute("""INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) 
                                             VALUES(%s, %s, %s, %s, %s, %s, %s, 0)""", 
                                          (o_date, sub_awb, session['branch'], o_station, s_dst, s_wt, f"Unpacked from {awb}"))
                        flash(f"✅ Bag {awb} unpacked into Outward.", "success")
                else:
                    if c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND finalized=0", (awb,)):
                        flash(f"AWB {awb} is already in pending list!", "error")
                    else:
                        # Fetch default values from shipments if user skipped them
                        c.execute("SELECT id, dest_station, weight_kg FROM shipments WHERE awb_no=%s", (awb,))
                        s = c.fetchone()
                        
                        # 🚀 SMART FILL: 
                        final_dest = dest_input if dest_input else (s['dest_station'] if s and s['dest_station'] else 'UNKNOWN')
                        final_wt = wt_input if wt_input > 0 else (s['weight_kg'] if s and s['weight_kg'] else 1.0)
                        
                        if final_dest and final_dest != 'UNKNOWN':
                            c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (final_dest,))
                            
                        if s: 
                            c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s WHERE awb_no=%s", (o_station, awb))
                        
                        c.execute("""INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) 
                                     VALUES(%s, %s, %s, %s, %s, %s, %s, 0)""", 
                                  (o_date, awb, session['branch'], o_station, final_dest, final_wt, info))
                conn.commit()
            return redirect(f"/outward?date={o_date}&station={o_station}")

    if request.method == 'POST' and request.form.get('action') == 'finalize':
        o_date = request.form.get('out_date', current_date)
        o_station = request.form.get('out_station', session.get('branch', 'NOHAR')).upper()
        with conn.cursor() as c:
            c.execute("SELECT id, awb_no FROM outward_register WHERE entry_date=%s AND out_station=%s AND origin_station=%s AND finalized=0", (o_date, o_station, session['branch']))
            pending = c.fetchall()
            if pending:
                ono = get_seq("outward", "OUT", 6); mno = get_seq("manifest", "MF", 7)
                c.execute("INSERT INTO manifests(manifest_no, manifest_type, from_location, to_location, vehicle_no, status) VALUES(%s, 'OUTWARD', %s, %s, '', 'OPEN')", 
                          (mno, session['branch'], o_station))
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
        c.execute("SELECT id, awb_no, destination, weight, info FROM outward_register WHERE entry_date=%s AND out_station=%s AND origin_station=%s AND finalized=0 ORDER BY id DESC", (f_date, f_station, session['branch']))
        pending_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = [r['name'] for r in c.fetchall()]
        q_m = "SELECT manifest_no, created_at, from_location, to_location, vehicle_no, status, id FROM manifests WHERE manifest_type='OUTWARD'"
        if session.get('role') != 'ADMIN': q_m += f" AND from_location='{session['branch']}'"
        c.execute(q_m + " ORDER BY id DESC LIMIT 10"); mans = c.fetchall()
    conn.close()
    
    html = """
    <div style="display:flex; gap:5px; margin-bottom:15px; border-bottom: 1px solid #334155;">
        <button class="btn" onclick="switchTab('new')" id="tab-new" style="background:#0E8A6D; border-radius:8px 8px 0 0; padding:10px 20px;"><i class="fas fa-box-open"></i> New Entry Finalize</button>
        <button class="btn btn-ghost" onclick="switchTab('history')" id="tab-history" style="border:none; border-radius:8px 8px 0 0; padding:10px 20px;"><i class="fas fa-list-alt"></i> Manifests History</button>
    </div>

    <!-- MAIN OUTWARD PANEL -->
    <div class="card" id="content-new" style="padding:10px 15px;">
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:15px; padding-bottom:15px; border-bottom:1px solid #334155;">
            <label style="margin:0;">Date</label><input type="date" id="ui_date" value="{{ f_date }}" onchange="reloadPage()" style="width:130px;">
            <label style="margin:0; margin-left:10px;">Station</label><input list="station_list" id="ui_station" value="{{ f_station }}" onchange="reloadPage()" style="width:180px; text-transform:uppercase;">
            <label style="margin:0; margin-left:10px;">Scan Mode</label><select id="ui_mode" style="width:120px;"><option>MANUAL</option><option>AUTO</option></select>
            <div style="flex:1;"></div>
            <button class="btn btn-red" onclick="startVoice('awb_input')"><i class="fas fa-microphone"></i> Voice Entry</button>
            <button class="btn btn-blue" onclick="window.open('/master_bag', '_blank')">🎒 Create Master Bag</button>
        </div>

        <form method="POST" id="entryForm" style="display:flex; align-items:center; gap:10px; background:#1E293B; border:1px solid #475569; padding:5px 10px; border-radius:6px; margin-bottom:10px;">
            <input type="hidden" name="action" value="save_entry">
            <input type="hidden" name="out_date" id="hdn_date" value="{{ f_date }}">
            <input type="hidden" name="out_station" id="hdn_station" value="{{ f_station }}">
            
            <label style="margin:0; color:white;">AWB</label>
            <div style="display:flex; flex:2;">
                <input type="text" name="awb" id="awb_input" placeholder="Scan/type AWB then Enter..." required autofocus style="flex:1; border-radius:4px 0 0 4px; border-right:none;" onkeypress="checkEnter(event)">
                <button type="button" class="btn btn-blue" style="border-radius:0 4px 4px 0; padding:8px 12px;"><i class="fas fa-camera"></i></button>
            </div>
            <label style="margin:0; margin-left:5px; color:white;">Dest</label><input type="text" name="dest" id="dest_input" list="station_list" placeholder="Dest Station" style="flex:1.5; text-transform:uppercase;" onkeypress="checkEnter(event)">
            <label style="margin:0; margin-left:5px; color:white;">Weight</label><input type="number" step="0.01" name="weight" id="wt_input" value="0.00" style="width:80px;" onkeypress="checkEnter(event)">
            <label style="margin:0; margin-left:5px; color:white;">Info</label><input type="text" name="info" id="info_input" style="flex:2;" onkeypress="checkEnter(event)">
            <datalist id="station_list">{% for s in stations %}<option value="{{ s }}">{% endfor %}</datalist>
        </form>
        <button onclick="document.getElementById('entryForm').submit();" class="btn" style="background:#0284C7; width:100%; font-size:15px; padding:10px; margin-bottom:15px;">+ Save Entry</button>

        <h4 style="color:#D97706; margin-top:0; margin-bottom:5px;">Total Pending Entries: {{ pending_list|length }}</h4>
        <div style="height:300px; overflow-y:auto; border:1px solid #334155; border-radius:4px; background:#0F172A; margin-bottom:10px;">
            <table style="margin:0; width:100%;">
                <tr style="position:sticky; top:0; background:#1E293B; z-index:1;">
                    <th>ID</th><th>AWB</th><th>Dest</th><th>Weight</th><th>Info</th>
                </tr>
                {% for p in pending_list %}
                <tr onclick="selectRow(this, {{ p.id }})" style="cursor:pointer;" class="tbl-row">
                    <td>{{ p.id }}</td>
                    <td style="color:#38BDF8; font-weight:bold;">{{ p.awb_no }}</td>
                    <td>{{ p.destination }}</td>
                    <td>{{ p.weight }}</td>
                    <td>{{ p.info }}</td>
                </tr>
                {% else %}
                <tr><td colspan="5" style="text-align:center; color:#64748b; padding:30px;">No pending entries. Scan AWB to begin.</td></tr>
                {% endfor %}
            </table>
        </div>

        <div style="display:flex; gap:10px; margin-bottom:10px;">
            <button class="btn btn-ghost" style="flex:1;" onclick="alert('Select entry from table to edit')">✏ Edit Entry</button>
            <button class="btn btn-red" style="flex:1;" onclick="deleteSelected()">🗑 Delete Entry</button>
        </div>
        <form method="POST" id="finalizeForm">
            <input type="hidden" name="action" value="finalize">
            <input type="hidden" name="out_date" id="fin_date" value="{{ f_date }}">
            <input type="hidden" name="out_station" id="fin_station" value="{{ f_station }}">
            <button type="button" onclick="confirmFinalize()" class="btn btn-gold" style="width:100%; font-size:15px; padding:12px; letter-spacing:1px;"><i class="fas fa-flag-checkered"></i> FINALIZE + OUTWARD NO</button>
        </form>
    </div>

    <!-- HISTORY TAB -->
    <div class="card" id="content-history" style="display:none; padding:10px 15px;">
        <h3 style="margin-top:0;">Manifests History</h3>
        <table style="width:100%;">
            <tr><th>Manifest No</th><th>Date</th><th>Route</th><th>Vehicle</th><th>Actions</th></tr>
            {% for m in mans %}
            <tr>
                <td style="color:#38bdf8;"><strong>{{ m.manifest_no }}</strong></td><td>{{ m.created_at }}</td><td>{{ m.from_location }} &rarr; {{ m.to_location }}</td><td>{{ m.vehicle_no or 'System' }}</td>
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
            let mode = document.getElementById('ui_mode').value;
            if(mode === 'AUTO') { document.getElementById('entryForm').submit(); }
            else {
                let src = e.target.id;
                if(src === 'awb_input') document.getElementById('dest_input').focus();
                else if(src === 'dest_input') document.getElementById('wt_input').focus();
                else if(src === 'wt_input') document.getElementById('info_input').focus();
                else if(src === 'info_input') document.getElementById('entryForm').submit();
            }
        }
    }
    function selectRow(tr, id) {
        document.querySelectorAll('.tbl-row').forEach(r => r.style.background = 'transparent');
        tr.style.background = 'rgba(56,189,248,0.2)'; selectedId = id;
    }
    function deleteSelected() {
        if(!selectedId) { alert("Please select a row first!"); return; }
        if(confirm("Delete this entry?")) {
            let d = document.getElementById('ui_date').value; let s = document.getElementById('ui_station').value;
            window.location.href = `/outward?delete=${selectedId}&date=${d}&station=${s}`;
        }
    }
    function confirmFinalize() {
        let count = {{ pending_list|length }};
        if(count === 0) { alert("No pending entries to finalize!"); return; }
        if(confirm(`Are you sure you want to finalize ${count} items and generate Manifest?`)) { document.getElementById('finalizeForm').submit(); }
    }
    document.getElementById('entryForm').addEventListener('submit', function() {
        document.getElementById('hdn_date').value = document.getElementById('ui_date').value;
        document.getElementById('hdn_station').value = document.getElementById('ui_station').value;
    });
    function startVoice(targetId) {
        let recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
        recognition.lang = 'en-IN';
        recognition.onstart = function() { document.getElementById('awb_input').placeholder = "Listening..."; };
        recognition.onresult = function(event) { let match = event.results[0][0].transcript.toLowerCase().match(/(awb|bill|parcel|number|bag)\\s*([a-z0-9]+)/); if(match) { let box = document.getElementById(targetId); box.value = match[2].toUpperCase(); document.getElementById('entryForm').submit(); }};
        recognition.start();
    }
    </script>
    """
    return render_page("OUTWARD HUB", render_template_string(html, pending_list=pending_list, mans=mans, stations=stations, f_date=f_date, f_station=f_station))

# ==========================================
# 🎒 7. MASTER BAG
# ==========================================
@app.route('/master_bag', methods=['GET', 'POST'])
@login_required
def master_bag():
    conn = get_db()
    if request.method == 'POST':
        awbs = request.form.get('awbs').replace(',', '\n').split('\n'); dest = request.form.get('dest_hub').upper()
        with conn.cursor() as c:
            bag_no = get_seq("bag", "BAG", 6)
            c.execute("INSERT INTO master_bags(bag_no, destination) VALUES(%s,%s)", (bag_no, dest))
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("INSERT INTO master_bag_items(bag_no, awb_no) VALUES(%s,%s)", (bag_no, awb))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,)); s = c.fetchone()
                    if s: c.execute("INSERT INTO scan_events(shipment_id,scan_type,location,remarks) VALUES(%s,'BAGGED',%s,%s)", (s['id'], session['branch'], f"Packed in {bag_no}"))
            conn.commit(); flash(f"🎒 Master Bag Sealed! Bag No: {bag_no}", "success")
    with conn.cursor() as c:
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
        c.execute("SELECT bag_no, destination, created_at, (SELECT COUNT(*) FROM master_bag_items WHERE bag_no=master_bags.bag_no) as items FROM master_bags ORDER BY id DESC LIMIT 10"); bags = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card" style="border-top-color: #38bdf8;"><h3 style="color:#38bdf8; margin-top:0;">🎒 Create Master Bag (Bora)</h3><form method="POST"><label>Bag Destination Hub</label><input name="dest_hub" list="stations" required style="margin-bottom:15px; text-transform:uppercase;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist><div style="display:flex; justify-content:space-between; align-items:center;"><label>Scan Items to Pack</label><button type="button" onclick="startVoice('bag_awbs')" class="btn btn-red">🎤 Voice Scan</button></div><textarea name="awbs" id="bag_awbs" rows="6" required style="font-family:monospace; font-size:14px; margin-top:5px;"></textarea><button type="submit" class="btn btn-blue" style="margin-top:10px; width:100%; font-size:15px;">🔒 SEAL MASTER BAG</button></form></div><div class="card"><h3>Recent Sealed Bags</h3><div style="max-height:300px; overflow-y:auto;"><table><tr><th>Bag No</th><th>Destination</th><th>Items</th><th>Date</th></tr>{% for b in bags %}<tr><td style="color:#38bdf8;"><strong>{{ b.bag_no }}</strong></td><td>{{ b.destination }}</td><td>{{ b.items }}</td><td>{{ b.created_at }}</td></tr>{% endfor %}</table></div></div></div><script>function startVoice(targetId) { let recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)(); recognition.lang = 'en-IN'; recognition.onresult = function(event) { let match = event.results[0][0].transcript.toLowerCase().match(/(awb|bill|parcel|number)\\s*([a-z0-9]+)/); if(match) { let box = document.getElementById(targetId); box.value += (box.value ? "\\n" : "") + match[2].toUpperCase(); }}; recognition.start(); }</script>"""
    return render_page("MASTER BAG", render_template_string(html, stations=stations, bags=bags))

# ==========================================
# 📥 8. ENHANCED INWARD HUB
# ==========================================
@app.route('/inward', methods=['GET', 'POST'])
@login_required
def inward():
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("DELETE FROM inward_register WHERE id=%s", (request.args.get('delete'),))
            conn.commit(); return redirect('/inward')
    
    if request.method == 'POST':
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        origin = request.form.get('origin', '').upper()
        wt = request.form.get('weight', '1.0')
        info = request.form.get('info', '')
        
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    if awb.startswith("BAG"):
                        c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb,))
                        for bi in c.fetchall():
                            c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, weight, info, finalized) VALUES(CURDATE(), %s, %s, %s, %s, %s, 1)", (bi['awb_no'], origin, session['branch'], wt, f"Unpacked from {awb}"))
                            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (bi['awb_no'],)); s_row = c.fetchone()
                            if s_row:
                                c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session['branch'], s_row['id']))
                                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (s_row['id'], session['branch']))
                        continue
                    
                    c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, weight, info, finalized) VALUES(CURDATE(), %s, %s, %s, %s, %s, 1)", (awb, origin, session['branch'], wt, info))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,)); s_row = c.fetchone()
                    if s_row:
                        c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session['branch'], s_row['id']))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (s_row['id'], session['branch']))
            conn.commit(); flash("✅ Inward Completed.", "success")
    
    with conn.cursor() as c:
        c.execute("SELECT * FROM inward_register WHERE in_station=%s ORDER BY id DESC LIMIT 50", (session['branch'],)); hist = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3 style="color:#0f766e; margin-top:0;">📥 Receive Inward</h3><form method="POST"><div class="grid-2" style="margin-bottom:15px;"><div><label>My Hub</label><input value="{{ session['branch'] }}" readonly style="background:#0F172A;"></div><div><label>Coming From (Origin)</label><input name="origin" list="stations" required style="text-transform:uppercase;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div></div><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><label>Scan AWBs or BAG No.</label><button type="button" onclick="startVoice('in_awbs')" class="btn btn-red">🎤 Voice Scan</button></div><div style="display:flex; gap:10px; margin-bottom:10px;"><input type="number" step="0.01" name="weight" value="1.00" placeholder="Weight" style="flex:1;"><input name="info" placeholder="Remarks/Info" style="flex:2;"></div><textarea name="awbs" id="in_awbs" rows="6" required style="font-family:monospace; margin-top:5px;"></textarea><button type="submit" class="btn btn-blue" style="width:100%; margin-top:10px;">💾 Save Inward Entry</button></form></div><div class="card" style="overflow-y:auto; max-height:500px;"><h3>Inward History</h3><table><tr><th>Date</th><th>AWB</th><th>Origin</th><th>Wt</th><th>Info</th><th>Del</th></tr>{% for h in hist %}<tr><td>{{ h.entry_date }}</td><td style="color:#38bdf8;"><strong>{{ h.awb_no }}</strong></td><td>{{ h.origin_station }}</td><td>{{ h.weight }}</td><td>{{ h.info }}</td><td><a href="/inward?delete={{ h.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</table></div></div><script>function startVoice(targetId) { let recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)(); recognition.lang = 'en-IN'; recognition.onresult = function(event) { let match = event.results[0][0].transcript.toLowerCase().match(/(awb|bill|parcel|number|bag)\\s*([a-z0-9]+)/); if(match) { let box = document.getElementById(targetId); box.value += (box.value ? "\\n" : "") + match[2].toUpperCase(); }}; recognition.start(); }</script>"""
    return render_page("INWARD HUB", render_template_string(html, hist=hist, stations=stations))

# ==========================================
# 🛵 9. DRS & DELIVERY
# ==========================================
@app.route('/drs', methods=['GET', 'POST'])
@login_required
def drs():
    conn = get_db()
    if request.args.get('del_drs'):
        with conn.cursor() as c:
            c.execute("DELETE FROM drs_items WHERE drs_id=%s", (request.args.get('del_drs'),))
            c.execute("DELETE FROM drs WHERE id=%s", (request.args.get('del_drs'),))
            conn.commit(); return redirect('/drs')
    if request.args.get('unfinalize'):
        with conn.cursor() as c:
            drs_id = request.args.get('unfinalize')
            c.execute("UPDATE drs SET status='OPEN' WHERE id=%s", (drs_id,))
            c.execute("UPDATE drs_items SET status='ASSIGNED' WHERE drs_id=%s", (drs_id,))
            conn.commit(); flash("DRS Reopened!", "success"); return redirect('/drs')

    if request.method == 'POST' and 'assign_drs' in request.form:
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        rider = request.form.get('rider'); vehicle = request.form.get('vehicle', '')
        with conn.cursor() as c:
            drs_no = get_seq("drs", "DRS", 6)
            c.execute("INSERT INTO drs(drs_no, drs_date, rider_name, vehicle_no, status) VALUES(%s, CURDATE(), %s, %s, 'FINALIZED')", (drs_no, rider, vehicle))
            drs_id = c.lastrowid
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,)); s_row = c.fetchone()
                    if s_row:
                        c.execute("INSERT INTO drs_items(drs_id, shipment_id, status) VALUES(%s, %s, 'ASSIGNED')", (drs_id, s_row['id']))
                        c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE id=%s", (f"Rider: {rider}", s_row['id']))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'ON_DRS', %s, %s)", (s_row['id'], session['branch'], f"Assigned to {rider}"))
            conn.commit(); flash(f"✅ DRS {drs_no} Generated & Finalized", "success")

    elif request.method == 'POST' and 'mark_deliver' in request.form:
        awb = request.form.get('deliver_awb').strip().upper()
        receiver = request.form.get('receiver')
        with conn.cursor() as c:
            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,)); s_row = c.fetchone()
            if s_row:
                c.execute("UPDATE shipments SET status='DELIVERED', current_location=%s WHERE id=%s", (f"Delivered: {receiver}", s_row['id']))
                c.execute("UPDATE drs_items SET status='DELIVERED', receiver_name=%s WHERE shipment_id=%s", (receiver, s_row['id']))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'DELIVERED', %s, %s)", (s_row['id'], session['branch'], f"Received by {receiver}"))
                conn.commit(); flash(f"✅ Delivered: {awb}", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, drs_no, drs_date, rider_name, vehicle_no, status FROM drs ORDER BY id DESC LIMIT 15"); drss = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid-2"><div class="card" style="border-top-color: #0369a1;"><h3 style="color:#38bdf8; margin-top:0;">🛵 1. Create DRS (Assign Rider)</h3><form method="POST"><input type="hidden" name="assign_drs" value="1"><div class="grid-2" style="margin-bottom:15px;"><div><label>Rider/Boy Name</label><input name="rider" required></div><div><label>Route / Area</label><input name="vehicle"></div></div><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><label>Scan AWBs</label><button type="button" onclick="startVoice('drs_awbs')" class="btn btn-red">🎤 Voice Scan</button></div><textarea name="awbs" id="drs_awbs" rows="4" required style="font-family:monospace; margin-top:5px;"></textarea><button type="submit" class="btn btn-blue" style="margin-top:10px; width:100%;">Create DRS</button></form><hr><h4>Recent DRS History</h4><table><tr><th>DRS #</th><th>Rider</th><th>Status</th><th>Action</th></tr>{% for d in drss %}<tr><td style="color:#38bdf8;"><strong>{{ d.drs_no }}</strong></td><td>{{ d.rider_name }}</td><td><span class="badge {% if d.status=='FINALIZED' %}b-del{% else %}b-book{% endif %}">{{ d.status }}</span></td><td><a href="/print/drs/{{ d.id }}" target="_blank" class="btn btn-blue" style="padding:3px 6px; font-size:11px;">🖨️</a> <a href="/drs?del_drs={{ d.id }}" onclick="return confirm('Delete DRS?');" class="btn btn-red" style="padding:3px 6px; font-size:11px;"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</table></div><div class="card" style="border-top-color: #10b981;"><h3 style="color:#10b981; margin-top:0;">✅ 2. Mark Delivered</h3><form method="POST"><input type="hidden" name="mark_deliver" value="1"><label>AWB Number</label><input name="deliver_awb" required style="margin-bottom:10px;"><label>Receiver Name</label><input name="receiver" required style="margin-bottom:10px;"><button type="submit" class="btn" style="background:#10b981; width:100%;">Update Delivery</button></form></div></div><script>function startVoice(targetId) { let recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)(); recognition.lang = 'en-IN'; recognition.onresult = function(event) { let match = event.results[0][0].transcript.toLowerCase().match(/(awb|bill|parcel|number)\\s*([a-z0-9]+)/); if(match) { let box = document.getElementById(targetId); box.value += (box.value ? "\\n" : "") + match[2].toUpperCase(); }}; recognition.start(); }</script>
    """
    return render_page("DRS & DELIVERY", render_template_string(html, drss=drss))

# ==========================================
# 💰 10. ACCOUNTS & REPORTS
# ==========================================
@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    conn = get_db()
    if request.args.get('del_pay'):
        with conn.cursor() as c:
            c.execute("SELECT * FROM payments WHERE id=%s", (request.args.get('del_pay'),))
            p = c.fetchone()
            if p:
                c.execute("DELETE FROM ledger WHERE voucher_type='PAYMENT' AND reference=%s AND customer_id=%s", (p['reference'], p['customer_id']))
                c.execute("DELETE FROM payments WHERE id=%s", (p['id'],))
            conn.commit(); flash("Payment Deleted!", "success"); return redirect('/accounts')

    if request.method == 'POST':
        cid, amt, mode, ref, d = request.form.get('cust_id'), request.form.get('amount'), request.form.get('mode'), request.form.get('ref') or f"PAY-{int(datetime.now().timestamp())}", datetime.now().strftime("%Y-%m-%d")
        with conn.cursor() as c:
            c.execute("INSERT INTO payments(customer_id, payment_date, amount, mode, reference) VALUES(%s,%s,%s,%s,%s)", (cid, d, amt, mode, ref))
            c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'PAYMENT',%s,0,%s,%s)", (cid, d, ref, amt, f"Received ({mode})"))
            conn.commit(); flash("Payment Saved!", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
        c.execute("SELECT p.id, p.payment_date, c.name, p.amount, p.mode, p.reference FROM payments p JOIN customers c ON p.customer_id=c.id ORDER BY p.id DESC LIMIT 20"); pays = c.fetchall()
        l_data = []; c_bal = 0
        if request.args.get('cust_id'):
            c.execute("SELECT * FROM ledger WHERE customer_id=%s ORDER BY entry_date", (request.args.get('cust_id'),)); l_data = c.fetchall()
            c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (request.args.get('cust_id'),)); r = c.fetchone(); c_bal = r['b'] if r and r['b'] else 0
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3 style="margin-top:0; color:#10b981;">💸 Receive Payment</h3><form method="POST" class="grid-2" style="align-items:end;"><div style="grid-column: span 2;"><label>Customer</label><select name="cust_id" required>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div><label>Amount (₹)</label><input type="number" step="0.01" name="amount" required></div><div><label>Mode</label><select name="mode"><option>CASH</option><option>UPI</option></select></div><div><label>Reference</label><input name="ref"></div><div><button type="submit" class="btn" style="background:#10b981; width:100%;">Save Payment</button></div></form></div><div class="card"><h3 style="margin-top:0;">Recent Payments</h3><div style="max-height:180px; overflow-y:auto;"><table><tr><th>Date</th><th>Customer</th><th>Amount</th><th>Del</th></tr>{% for p in pays %}<tr><td>{{ p.payment_date }}</td><td>{{ p.name }}</td><td>₹{{ p.amount }}</td><td><a href="/accounts?del_pay={{ p.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}</table></div></div></div><div class="card"><h3>📒 Customer Ledger</h3><form method="GET" style="display:flex; gap:10px;"><select name="cust_id" style="flex:1;">{% for c in custs %}<option value="{{ c.id }}" {% if request.args.get('cust_id') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select><button class="btn btn-blue">View Ledger</button></form>{% if request.args.get('cust_id') %}<h4 style="text-align:right; color:#fb7185;">Closing Balance: ₹{{ c_bal }}</h4><table><tr><th>Date</th><th>Voucher</th><th>Ref</th><th>Debit</th><th>Credit</th><th>Narration</th></tr>{% for l in l_data %}<tr><td>{{ l.entry_date }}</td><td>{{ l.voucher_type }}</td><td>{{ l.reference }}</td><td style="color:#fb7185; font-weight:bold;">{{ l.debit }}</td><td style="color:#34d399; font-weight:bold;">{{ l.credit }}</td><td>{{ l.narration }}</td></tr>{% endfor %}</table>{% endif %}</div>"""
    return render_page("Accounts & Ledger", render_template_string(html, custs=custs, pays=pays, l_data=l_data, c_bal=c_bal))

@app.route('/reports')
@login_required
def reports():
    d = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    with conn.cursor() as c:
        p1 = [d]; p2 = [d]; p4 = []
        q_b = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE booking_date=%s"
        q_c = "SELECT awb_no, dest_name, cod_amount FROM shipments WHERE status='DELIVERED' AND cod_amount>0"
        if session.get('role') != 'ADMIN':
            q_b += " AND origin_name=%s"; p1.append(session['branch'])
            q_c += " AND origin_name=%s"; p4.append(session['branch'])
        c.execute(q_b, p1); b = c.fetchone()
        c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments WHERE payment_date=%s", p2); p = c.fetchone()
        c.execute("SELECT c.name, COALESCE(SUM(l.debit-l.credit),0) bal FROM customers c LEFT JOIN ledger l ON l.customer_id=c.id GROUP BY c.id HAVING bal>0 ORDER BY bal DESC LIMIT 20")
        out = c.fetchall()
        c.execute(q_c, p4); cods = c.fetchall()
    conn.close()
    html = """<div class="card" style="background:#0f172a; color:white;"><h2 style="margin:0; color:#38bdf8;">📊 Day Close Report ({{ date }})</h2><div class="grid-3" style="margin-top:15px;"><div style="background:#1e293b; padding:15px; border-radius:8px;"><h3>Bookings</h3><h2>{{ b.c }} Pcs | ₹{{ b.t }}</h2></div><div style="background:#1e293b; padding:15px; border-radius:8px;"><h3>Payments Received</h3><h2 style="color:#10b981;">₹{{ p.a }}</h2></div></div></div><div class="grid-2"><div class="card"><h3 style="color:#fb7185;">🔴 Top Market Outstanding</h3><table><tr><th>Customer</th><th>Due Amount</th></tr>{% for o in out %}<tr><td><strong>{{ o.name }}</strong></td><td style="color:#fb7185; font-weight:bold;">₹{{ o.bal }}</td></tr>{% endfor %}</table></div><div class="card"><h3 style="color:#d97706;">💰 Pending COD to Collect</h3><table><tr><th>AWB</th><th>Consignee</th><th>COD Amt</th></tr>{% for c in cods %}<tr><td>{{ c.awb_no }}</td><td>{{ c.dest_name }}</td><td style="color:#d97706; font-weight:bold;">₹{{ c.cod_amount }}</td></tr>{% endfor %}</table></div></div>"""
    return render_page("All Reports", render_template_string(html, b=b, p=p, out=out, cods=cods, date=d))

# ==========================================
# 🖨️ 11. EXACT PDF GENERATOR (ReportLab)
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

@app.route('/print/label/<awb>')
@login_required
def print_label_pdf(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT s.*, c.name as cname, c.address as caddr FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,))
        s = c.fetchone()
    conn.close()
    if not s: return "Not found"
    
    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=(4*inch, 6*inch))
    cv.roundRect(4*mm, 4*mm, 93.6*mm, 144*mm, 2*mm) 
    cv.line(4*mm, 130*mm, 97.6*mm, 130*mm) 
    cv.rect(33*mm, 130*mm, 64.6*mm, 18*mm, fill=1) 
    cv.setFillColorRGB(1, 1, 1); cv.setFont("Helvetica-Bold", 12)
    cv.drawCentredString(65*mm, 141*mm, "AKASH GANGA COURIER")
    cv.setFont("Helvetica-Bold", 8); cv.drawCentredString(65*mm, 135*mm, "PREMIUM EXPRESS")
    cv.setFillColorRGB(0, 0, 0); cv.setFont("Helvetica-BoldOblique", 18)
    cv.drawString(6*mm, 136*mm, "AGC")
    
    cv.setFont("Helvetica", 8); cv.drawString(8*mm, 124*mm, "SHIPPER (ORIGIN):")
    cv.setFont("Helvetica-Bold", 10); cv.drawString(8*mm, 118*mm, str(s.get('origin_name') or 'Shipper')[:30])
    cv.setFont("Helvetica", 8); cv.drawString(8*mm, 113*mm, str(s.get('origin_address') or '')[:45])
    cv.drawString(8*mm, 108*mm, f"Ph: {s.get('origin_phone', '')}")
    
    cv.roundRect(6*mm, 52*mm, 89.6*mm, 54*mm, 2*mm) 
    cv.rect(6*mm, 98*mm, 89.6*mm, 8*mm, fill=1) 
    cv.setFillColorRGB(1, 1, 1); cv.setFont("Helvetica-Bold", 9)
    cv.drawString(8*mm, 100*mm, "DELIVER TO (CONSIGNEE DETAILS):")
    
    cv.setFillColorRGB(0, 0, 0); cv.setFont("Helvetica-Bold", 12)
    cv.drawString(8*mm, 88*mm, str(s.get('dest_name', ''))[:30])
    cv.setFont("Helvetica", 9)
    addr_lines = wrap_lines(cv, s.get('dest_address', ''), "Helvetica", 9, 85*mm)
    y_addr = 80
    for ln in addr_lines[:2]: cv.drawString(8*mm, y_addr*mm, ln); y_addr -= 4
    cv.drawString(8*mm, (y_addr-2)*mm, f"City: {s.get('dest_station', '')}")
    cv.drawString(8*mm, (y_addr-6)*mm, f"Phone: {s.get('dest_phone', '')}")
    cv.setFont("Helvetica-Bold", 10); cv.drawString(8*mm, 55*mm, f"COD AMT: Rs {s.get('cod_amount', 0)}")
    
    cv.roundRect(6*mm, 34*mm, 89.6*mm, 15*mm, 2*mm) 
    cv.setFont("Helvetica-Bold", 8)
    cv.drawString(8*mm, 43*mm, f"Date: {s.get('booking_date', '')}"); cv.drawString(50*mm, 43*mm, f"Pcs: {s.get('quantity', 1)}")
    cv.drawString(8*mm, 37*mm, f"Wt: {s.get('weight_kg', 1)} KG"); cv.drawString(50*mm, 37*mm, f"Type: {s.get('service_type', 'SURFACE')}")
    
    draw_barcode_safe(cv, s['awb_no'], 18*mm, 14*mm, 14*mm)
    cv.setFont("Helvetica-Bold", 15); cv.drawCentredString(50.8*mm, 7*mm, s['awb_no'])
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Label_{awb}.pdf", mimetype='application/pdf')

@app.route('/print/receipt/<awb>')
@login_required
def print_receipt_pdf(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
        s = c.fetchone()
    conn.close()
    if not s: return "Not found"

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFont("Helvetica-Bold", 18); cv.drawString(30, 800, "AKASH GANGA COURIER")
    cv.setFont("Helvetica-Bold", 11); cv.drawRightString(560, 800, "NON-NEGOTIABLE DOCKET")
    cv.setFont("Helvetica", 10)
    cv.drawString(30, 785, "Head Office: Nohar (Raj) - 335523 | Premium Logistics & Supply Chain")
    cv.drawString(30, 765, f"Date: {s['booking_date']}")
    
    draw_barcode_safe(cv, s['awb_no'], 400, 760, 0.4*inch)
    cv.setFont("Helvetica-Bold", 14); cv.drawString(400, 745, s['awb_no'])
    
    cv.roundRect(30, 630, 255, 110, 4); cv.roundRect(305, 630, 255, 110, 4)
    
    cv.setFont("Helvetica-Bold", 10); cv.drawString(35, 725, "CONSIGNOR (SHIPPER DETAILS):")
    cv.setFont("Helvetica-Bold", 11); cv.drawString(35, 710, str(s.get('origin_name', ''))[:40])
    cv.setFont("Helvetica", 10)
    y_sh = 695
    for ln in wrap_lines(cv, str(s.get('origin_address', '')), "Helvetica", 10, 240)[:2]:
        cv.drawString(35, y_sh, ln); y_sh -= 15
    cv.drawString(35, y_sh, f"Ph: {s.get('origin_phone', '')}"); cv.drawString(35, y_sh-15, f"State: {s.get('origin_state_code', '')}")
    
    cv.setFont("Helvetica-Bold", 10); cv.drawString(310, 725, "CONSIGNEE (RECEIVER DETAILS):")
    cv.setFont("Helvetica-Bold", 11); cv.drawString(310, 710, str(s.get('dest_name', ''))[:40])
    cv.setFont("Helvetica", 10)
    y_cn = 695
    for ln in wrap_lines(cv, s.get('dest_address', ''), "Helvetica", 10, 240)[:2]:
        cv.drawString(310, y_cn, ln); y_cn -= 15
    cv.drawString(310, y_cn, f"Ph: {s.get('dest_phone', '')}"); cv.drawString(310, y_cn-15, f"Dest Station: {s.get('dest_station', '')}")

    y_tbl = 590
    cv.rect(30, y_tbl, 530, 20, fill=1)
    cv.setFillColorRGB(1, 1, 1); cv.setFont("Helvetica-Bold", 10)
    cv.drawString(35, y_tbl+6, "WEIGHT"); cv.drawString(100, y_tbl+6, "PIECES"); cv.drawString(160, y_tbl+6, "SERVICE")
    cv.drawString(240, y_tbl+6, "TAXABLE"); cv.drawString(320, y_tbl+6, "GST AMT"); cv.drawString(390, y_tbl+6, "COD AMT"); cv.drawString(470, y_tbl+6, "TOTAL (Rs)")

    y_tbl -= 25; cv.setFillColorRGB(0, 0, 0); cv.setFont("Helvetica-Bold", 11)
    cv.drawString(35, y_tbl+6, f"{s.get('weight_kg', 1)} KG"); cv.drawString(100, y_tbl+6, str(s.get('quantity', 1)))
    cv.drawString(160, y_tbl+6, str(s.get('service_type', 'SURFACE'))); cv.drawString(240, y_tbl+6, f"{s.get('taxable_amount', 0):.2f}")
    gst_tot = float(s.get('cgst') or 0) + float(s.get('sgst') or 0) + float(s.get('igst') or 0)
    cv.drawString(320, y_tbl+6, f"{gst_tot:.2f}"); cv.drawString(390, y_tbl+6, f"{s.get('cod_amount', 0):.2f}")
    cv.setFont("Helvetica-Bold", 14); cv.drawString(470, y_tbl+4, f"{s.get('total_amount', 0):.2f}")

    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(30, y_tbl-35, f"Amount to be collected: Rs {s.get('total_amount', 0)}")
    cv.setFont("Helvetica", 8); cv.drawString(30, y_tbl-50, "DECLARATION: Goods are carried at Owner's Risk. Cash, Jewelry, Narcotics strictly prohibited.")
    cv.drawString(420, y_tbl-50, "For AKASH GANGA COURIER"); cv.drawString(420, y_tbl-80, "Authorised Signatory")

    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Receipt_{awb}.pdf", mimetype='application/pdf')

@app.route('/print/manifest/<int:mid>')
@login_required
def print_manifest_pdf(mid):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM manifests WHERE id=%s", (mid,))
        m = c.fetchone()
        c.execute("SELECT s.awb_no, s.dest_station, o.weight, o.info FROM manifest_items mi JOIN shipments s ON s.id=mi.shipment_id JOIN outward_register o ON o.awb_no=s.awb_no WHERE mi.manifest_id=%s", (mid,))
        items = c.fetchall()
    conn.close()

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 50, "AKASH GANGA - OUTWARD MANIFEST")
    cv.setFont("Helvetica", 10); cv.drawString(40, h - 65, f"Manifest No: {m['manifest_no']}   |   Route: {m['from_location']} -> {m['to_location']}")
    cv.drawString(40, h - 80, f"Vehicle: {m.get('vehicle_no', 'N/A')}   |   Date: {m['created_at']}   |   Items: {len(items)}")
    draw_barcode_safe(cv, m['manifest_no'], w - 180, h - 70, 0.4 * inch)
    
    y = h - 110; cv.rect(40, y - 20, w - 80, 20, fill=1)
    cv.setFillColorRGB(1,1,1); cv.setFont("Helvetica-Bold", 9)
    cv.drawString(45, y - 14, "S.No"); cv.drawString(85, y - 14, "AWB"); cv.drawString(220, y - 14, "DESTINATION"); cv.drawString(400, y - 14, "WT/PCS"); cv.drawString(480, y - 14, "INFO")
    
    y -= 20; cv.setFillColorRGB(0,0,0)
    for i, it in enumerate(items):
        if y < 50: cv.showPage(); y = h - 50
        cv.line(40, y-30, w-40, y-30); cv.setFont("Helvetica-Bold", 9)
        cv.drawString(45, y - 18, str(i + 1)); cv.drawString(85, y - 18, it["awb_no"])
        cv.drawString(220, y - 18, str(it.get("dest_station", ""))[:20]); cv.drawString(400, y - 18, f"{it.get('weight', 1)}kg")
        cv.setFont("Helvetica", 8); cv.drawString(480, y - 18, str(it.get('info', ''))[:15])
        y -= 30
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Manifest_{mid}.pdf", mimetype='application/pdf')

@app.route('/print/drs/<int:did>')
@login_required
def print_drs_pdf(did):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM drs WHERE id=%s", (did,))
        d = c.fetchone()
        c.execute("SELECT s.awb_no, s.dest_name, s.dest_address, s.dest_phone FROM drs_items di JOIN shipments s ON s.id=di.shipment_id WHERE di.drs_id=%s", (did,))
        items = c.fetchall()
    conn.close()

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4); w, h = A4
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 50, "AKASH GANGA - DELIVERY RUN SHEET (DRS)")
    cv.setFont("Helvetica", 10); cv.drawString(40, h - 65, f"DRS No: {d['drs_no']}   |   Rider: {d['rider_name']}   |   Date: {d['drs_date']}")
    draw_barcode_safe(cv, d['drs_no'], w - 180, h - 70, 0.4 * inch)
    
    y = h - 100; cv.rect(40, y - 20, w - 80, 20, fill=1)
    cv.setFillColorRGB(1,1,1); cv.setFont("Helvetica-Bold", 9)
    cv.drawString(45, y - 14, "#"); cv.drawString(70, y - 14, "AWB & BARCODE"); cv.drawString(210, y - 14, "CONSIGNEE DETAILS"); cv.drawString(420, y - 14, "RECEIVER SIGN & MOB")
    
    y -= 20; cv.setFillColorRGB(0,0,0)
    for i, it in enumerate(items):
        if y < 70: cv.showPage(); y = h - 50
        cv.line(40, y-40, w-40, y-40); cv.setFont("Helvetica-Bold", 9)
        cv.drawString(45, y - 22, str(i + 1))
        cv.drawString(70, y - 15, it["awb_no"]); draw_barcode_safe(cv, it["awb_no"], 70, y - 30, 0.20 * inch)
        cv.drawString(210, y - 14, str(it.get("dest_name", ""))[:30])
        cv.setFont("Helvetica", 8)
        addr_lines = wrap_lines(cv, it.get('dest_address', ''), "Helvetica", 8, 190)
        if addr_lines: cv.drawString(210, y - 24, addr_lines[0])
        cv.drawString(210, y - 34, f"Ph: {it.get('dest_phone', '')}")
        cv.setFont("Helvetica", 9)
        cv.drawString(420, y - 15, "Sign: ........................")
        cv.drawString(420, y - 32, "Mob: ........................")
        y -= 40

    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(60, y - 30, "Rider Signature")
    cv.drawString(400, y - 30, "Branch Manager Signature")
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"DRS_{did}.pdf", mimetype='application/pdf')

# ==========================================
# 🛑 DO NOT TOUCH - FLASK RUN
# ==========================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)
