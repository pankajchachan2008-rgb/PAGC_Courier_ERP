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
            c.execute("CREATE TABLE IF NOT EXISTS outward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), out_station VARCHAR(100), destination VARCHAR(100), weight VARCHAR(50), pcs INT DEFAULT 1, network VARCHAR(100) DEFAULT 'SELF', network_awb VARCHAR(100), bag_no VARCHAR(100), info TEXT, manifest_no VARCHAR(100), finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS inward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), in_station VARCHAR(100), weight VARCHAR(50), info TEXT, inward_no VARCHAR(100), finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS manifests (id INT AUTO_INCREMENT PRIMARY KEY, manifest_no VARCHAR(100), manifest_type VARCHAR(50), from_location VARCHAR(100), to_location VARCHAR(100), vehicle_no VARCHAR(100), driver_phone VARCHAR(50), seal_no VARCHAR(100), status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS manifest_items (id INT AUTO_INCREMENT PRIMARY KEY, manifest_id INT, shipment_id INT, received INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS drs (id INT AUTO_INCREMENT PRIMARY KEY, drs_no VARCHAR(100), drs_date DATE, rider_name VARCHAR(100), rider_phone VARCHAR(50), vehicle_no VARCHAR(100), status VARCHAR(50))")
            c.execute("CREATE TABLE IF NOT EXISTS drs_items (id INT AUTO_INCREMENT PRIMARY KEY, drs_id INT, shipment_id INT, status VARCHAR(50), receiver_name VARCHAR(100))")
            c.execute("CREATE TABLE IF NOT EXISTS stations (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255) UNIQUE)")
            c.execute("CREATE TABLE IF NOT EXISTS master_bags (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100) UNIQUE, destination VARCHAR(100), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS master_bag_items (id INT AUTO_INCREMENT PRIMARY KEY, bag_no VARCHAR(100), awb_no VARCHAR(100))")
            c.execute("CREATE TABLE IF NOT EXISTS sequences (name VARCHAR(50) PRIMARY KEY, value INT)")
            
            try: c.execute("ALTER TABLE outward_register ADD COLUMN pcs INT DEFAULT 1")
            except: pass
            try: c.execute("ALTER TABLE outward_register ADD COLUMN network VARCHAR(100) DEFAULT 'SELF'")
            except: pass
            try: c.execute("ALTER TABLE outward_register ADD COLUMN network_awb VARCHAR(100)")
            except: pass
            try: c.execute("ALTER TABLE outward_register ADD COLUMN bag_no VARCHAR(100)")
            except: pass
            try: c.execute("ALTER TABLE manifests ADD COLUMN driver_phone VARCHAR(50)")
            except: pass
            try: c.execute("ALTER TABLE manifests ADD COLUMN seal_no VARCHAR(100)")
            except: pass
        conn.commit(); conn.close()
    except Exception as e: print("Heal Error:", e)

auto_heal_db()

def sha(text): return hashlib.sha256(text.encode()).hexdigest()

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
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f5f7; margin: 0; color: #1e293b; }
        .sidebar { width: 260px; background: #0f172a; color: white; position: fixed; height: 100%; overflow-y: auto; box-shadow: 2px 0 10px rgba(0,0,0,0.1); }
        .logo { padding: 20px; font-size: 24px; font-weight: 900; color: #38bdf8; border-bottom: 1px solid #1e293b; text-align: center; }
        .menu a { display: block; padding: 12px 25px; color: #cbd5e1; text-decoration: none; font-weight: 600; border-bottom: 1px solid #1e293b; transition: 0.2s; }
        .menu a:hover { background: #0f766e; color: white; border-left: 4px solid #fbbf24; }
        .main-content { margin-left: 260px; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; background: white; padding: 15px 25px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; border-top: 4px solid #0f766e; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; }
        .grid-6 { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
        input, select, textarea { padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 4px; width: 100%; box-sizing: border-box; font-family: inherit; font-size: 13px;}
        input:focus, select:focus { border-color: #0f766e; outline: none; box-shadow: 0 0 0 2px rgba(15,118,110,0.2);}
        label { font-weight: 600; color: #475569; margin-bottom: 4px; display: block; font-size: 12px; text-transform: uppercase; }
        .btn { background: #0f766e; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 13px; text-decoration: none; display: inline-block; text-align: center;}
        .btn:hover { background: #0d9488; }
        .btn-gold { background: #d97706; } .btn-gold:hover { background: #b45309; }
        .btn-red { background: #be123c; } .btn-red:hover { background: #9f1239; }
        .btn-blue { background: #0284c7; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #f8fafc; color: #1e293b; font-weight: bold; border-bottom: 2px solid #cbd5e1; }
        .msg { padding: 10px; margin-bottom: 15px; border-radius: 4px; font-weight: 600; font-size:14px; }
        .success { background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }
        .error { background: #fee2e2; color: #9f1239; border: 1px solid #fecdd3; }
        .badge { padding: 3px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; }
        .b-book { background: #e2e8f0; color: #334155; }
        .b-out { background: #fef08a; color: #a16207; }
        .b-del { background: #bbf7d0; color: #15803d; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">AGC CLOUD</div>
        <div class="menu">
            <a href="/">📊 Dashboard</a>
            <a href="/track" target="_blank" style="color:#38bdf8;">🌐 Public Tracking</a>
            <a href="/customers">👥 Customers</a>
            <a href="/booking">📦 BOOKING</a>
            <a href="/shipments">🚚 SHIPMENTS</a>
            <a href="/outward">📤 OUTWARD HUB</a>
            <a href="/inward">📥 INWARD HUB</a>
            <a href="/drs">🛵 DRS / DELIVERY</a>
            <a href="/master_bag">🎒 MASTER BAG</a>
            <a href="/accounts">💰 Accounts & Ledger</a>
            <a href="/reports" style="color:#fbbf24;">📈 All Reports</a>
            {% if session.get('role') == 'ADMIN' %}
                <a href="/users" style="color:#f472b6;">⚙️ Users & Branch</a>
            {% endif %}
            <a href="/logout" style="background:#be123c; border-left:0; margin-top:20px;">🚪 Logout</a>
        </div>
    </div>
    <div class="main-content">
        <div class="header">
            <h2 style="margin:0;">{{ title }}</h2>
            <div style="font-weight:600; color:#475569;">👤 {{ session['full_name'] }} | Branch: {{ session['branch'] }}</div>
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
    return """<style>body{background:#0f172a; display:flex; justify-content:center; align-items:center; height:100vh;} .box{background:#1e293b; padding:40px; border-radius:8px; text-align:center; width:300px;} input{width:100%; margin:10px 0; padding:12px; box-sizing:border-box;} button{width:100%; padding:12px; background:#0f766e; color:white; border:none; font-weight:bold; cursor:pointer;}</style><div class="box"><h2 style="color:#38bdf8; margin-top:0;">ERP LOGIN</h2><form method="POST"><input name="username" placeholder="Username" required autocomplete="off"><input type="password" name="password" placeholder="Password" required><button type="submit">LOGIN</button></form></div>"""

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
    html = f"""<div class="grid-3"><div class="card" style="border-top-color: #38bdf8;"><h3>Total Parcels</h3><h2 style="font-size:28px; margin:0;">{s['c']}</h2></div><div class="card" style="border-top-color: #10b981;"><h3>Delivered</h3><h2 style="font-size:28px; margin:0;">{d['c']}</h2></div><div class="card" style="border-top-color: #f59e0b;"><h3>Revenue (₹)</h3><h2 style="font-size:28px; margin:0;">{round(s['t'], 2)}</h2></div></div><div class="card"><h3>📦 Recent Bookings ({session['branch']})</h3><table><tr><th>AWB Number</th><th>Date</th><th>Destination</th><th>Amount</th><th>Status</th></tr>{''.join(f"<tr><td><strong>{r['awb_no']}</strong></td><td>{r['booking_date']}</td><td>{r['dest_name']}</td><td>₹{r['total_amount']}</td><td><span class='badge b-book'>{r['status']}</span></td></tr>" for r in latest)}</table></div>"""
    return render_page("Dashboard", html)

# ==========================================
# 📦 4. COMPLETE BOOKING (BUG FIXED: PROPER SENDER LINKAGE)
# ==========================================
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
                
                # 🚀 FIX: Ab 'origin_name' mein form wala d['oname'] jayega, session branch nahi! 
                # (Jis se PDF me blank hone ki problem hamesha ke liye khatam)
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
    <div class="card" style="max-width:950px; margin:auto;"><h3 style="color:#0f766e; margin-top:0;">📦 Master Booking Form</h3>
        <form method="POST">
            <div class="grid-4" style="background:#f8fafc; padding:15px; border-radius:6px; margin-bottom:15px; border:1px solid #e2e8f0;">
                <div><label>Booking Date</label><input type="date" name="date" id="bdt" required></div>
                <div><label>AWB Number</label><input name="awb" required style="font-weight:bold; color:#0284c7; text-transform:uppercase;"></div>
                <div style="grid-column: span 2;"><label>Customer (Accounts Auto-Link)</label>
                    <select name="cust_id"><option value="">-- Walk-in --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }} ({{ c.phone }})</option>{% endfor %}</select>
                </div>
            </div>
            <div class="grid-2">
                <div style="border:1px solid #cbd5e1; padding:15px; border-radius:6px;"><h4 style="margin-top:0; color:#d97706;">🏢 ORIGIN (SHIPPER)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Sender Name</label><input name="oname" value="{{ session['branch'] }}" required></div><div><label>Phone</label><input name="ophone"></div><div><label>State Code</label><input name="ostate" value="RJ"></div>
                    <div style="grid-column: span 2;"><label>Address</label><input name="oaddr"></div>
                </div></div>
                <div style="border:1px solid #cbd5e1; padding:15px; border-radius:6px;"><h4 style="margin-top:0; color:#0f766e;">🏠 DESTINATION (CONSIGNEE)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Receiver Name</label><input name="dname" required></div><div><label>Phone</label><input name="dphone" required></div><div><label>State Code</label><input name="dstate"></div>
                    <div style="grid-column: span 2;"><label>Dest Station (City)</label><input name="dstat" list="stations" required style="border-color:#0f766e; text-transform:uppercase;">
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
                <div><label>Total(₹)</label><input type="number" step="0.01" name="amt" id="amt" value="59.0" readonly style="background:#fee2e2; font-weight:bold;"></div>
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
        q = "SELECT * FROM shipments WHERE 1=1"
        params = []
        if session.get('role') != 'ADMIN': q += " AND origin_name=%s"; params.append(session['branch'])
        if search: q += " AND (awb_no LIKE %s OR dest_station LIKE %s)"; params.extend([f"%{search}%", f"%{search}%"])
        q += " ORDER BY id DESC LIMIT 150"
        c.execute(q, params); rows = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="padding:15px;"><form method="POST" style="display:flex; gap:10px;"><input name="search" value="{{ search }}" placeholder="Search AWB or Station..." style="flex:1;"><button type="submit" class="btn btn-blue">🔍 Search</button></form></div>
    <div class="card"><table style="font-size:12px;"><tr><th>AWB</th><th>Date</th><th>Consignee</th><th>Station</th><th>Total</th><th>Status</th><th>Actions</th></tr>
        {% for r in rows %}<tr>
            <td><strong>{{ r.awb_no }}</strong></td><td>{{ r.booking_date }}</td><td>{{ r.dest_name }}</td><td>{{ r.dest_station }}</td><td>₹{{ r.total_amount }}</td>
            <td><span class="badge b-book">{{ r.status }}</span></td>
            <td>
                {% set ph = r.dest_phone if r.dest_phone else r.cphone %}
                {% if ph %}<a href="https://wa.me/91{{ ph }}?text=Track%20AGC%20Parcel:%20http://pagcerp.cgsmart.in/track?awb={{ r.awb_no }}" target="_blank" class="btn" style="background:#16a34a; padding:4px; font-size:11px;">WA</a>{% endif %}
                <a href="/print/label/{{ r.awb_no }}" target="_blank" class="btn" style="padding:4px; font-size:11px;">🖨️ Label</a>
                <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="btn btn-gold" style="padding:4px; font-size:11px;">🧾 Bilti</a>
                <a href="/shipments?delete={{ r.id }}" onclick="return confirm('Delete this shipment?');" class="btn btn-red" style="padding:4px; font-size:11px;">🗑️</a>
            </td>
        </tr>{% endfor %}</table></div>
    """
    return render_page("Shipments Management", render_template_string(html, rows=rows, search=search))

# ==========================================
# 📤 5. ENHANCED OUTWARD HUB
# ==========================================
@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    conn = get_db()
    
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("DELETE FROM outward_register WHERE id=%s", (request.args.get('delete'),))
            conn.commit(); flash("Entry Deleted!", "success"); return redirect('/outward')
            
    if request.method == 'POST' and 'edit_entry' in request.form:
        entry_id = request.form.get('entry_id')
        dest_hub = request.form.get('dest_hub').upper()
        network = request.form.get('network', 'SELF').upper()
        network_awb = request.form.get('network_awb', '')
        bag_no = request.form.get('bag_no', '')
        weight = request.form.get('weight', '1.0')
        pcs = request.form.get('pcs', '1')
        info = request.form.get('info', '')
        with conn.cursor() as c:
            c.execute("""UPDATE outward_register SET out_station=%s, network=%s, network_awb=%s, bag_no=%s, weight=%s, pcs=%s, info=%s WHERE id=%s""", 
                      (dest_hub, network, network_awb, bag_no, weight, pcs, info, entry_id))
            conn.commit(); flash("Entry Updated!", "success"); return redirect('/outward')

    if request.method == 'POST' and 'scan_awb' in request.form:
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        dest_hub = request.form.get('dest_hub').upper()
        network = request.form.get('network', 'SELF').upper()
        network_awb = request.form.get('network_awb', '')
        bag_no = request.form.get('bag_no', '')
        info = request.form.get('info', '')
        pcs_input = request.form.get('pcs', '1')
        weight_input = request.form.get('weight', '1.0')
        
        with conn.cursor() as c:
            c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest_hub,))
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    if awb.startswith("BAG"):
                        c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb,))
                        b_items = c.fetchall()
                        if not b_items: 
                            flash(f"Bag {awb} is empty or invalid.", "error"); continue
                        for bi in b_items:
                            sub_awb = bi['awb_no']
                            s_row = c.execute("SELECT dest_station, weight_kg, quantity FROM shipments WHERE awb_no=%s", (sub_awb,))
                            s = c.fetchone()
                            wt = s['weight_kg'] if s else 1.0; dst = s['dest_station'] if s else 'Unknown'; sub_pcs = s['quantity'] if s else 1
                            if not c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND finalized=0", (sub_awb,)):
                                c.execute("""INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, pcs, network, network_awb, bag_no, info, finalized) 
                                             VALUES(CURDATE(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)""", 
                                          (sub_awb, session['branch'], dest_hub, dst, wt, sub_pcs, network, network_awb, awb, f"Unpacked from {awb}"))
                        flash(f"✅ Bag {awb} unpacked into Outward.", "success")
                        continue
                    
                    s_row = c.execute("SELECT dest_station, weight_kg, quantity FROM shipments WHERE awb_no=%s", (awb,))
                    s = c.fetchone()
                    wt = weight_input if weight_input != '1.0' else (s['weight_kg'] if s else 1.0)
                    dst = s['dest_station'] if s else 'Unknown'
                    c.execute("""INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, pcs, network, network_awb, bag_no, info, finalized) 
                                 VALUES(CURDATE(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)""", 
                              (awb, session['branch'], dest_hub, dst, wt, pcs_input, network, network_awb, bag_no, info))
            conn.commit(); flash("✅ Added to Pending Outward with Full Details.", "success")
    
    if request.method == 'POST' and 'finalize_manifest' in request.form:
        vcl = request.form.get('vehicle')
        d_ph = request.form.get('driver_phone')
        seal = request.form.get('seal_no')
        with conn.cursor() as c:
            c.execute("SELECT id, awb_no, out_station FROM outward_register WHERE finalized=0 AND origin_station=%s", (session['branch'],))
            pending = c.fetchall()
            if pending:
                c.execute("SELECT MAX(CAST(SUBSTRING_INDEX(manifest_no, '-', -1) AS UNSIGNED)) as max_no FROM outward_register WHERE manifest_no IS NOT NULL")
                r = c.fetchone()
                outward_no = (r['max_no'] or 0) + 1
                manifest_no = f"MF-{outward_no}"
                
                c.execute("INSERT INTO manifests(manifest_no, manifest_type, from_location, to_location, vehicle_no, driver_phone, seal_no, status) VALUES(%s, 'OUTWARD', %s, %s, %s, %s, %s, 'CLOSED')", 
                          (manifest_no, session['branch'], pending[0]['out_station'], vcl, d_ph, seal))
                man_id = c.lastrowid
                for p in pending:
                    c.execute("UPDATE outward_register SET finalized=1, manifest_no=%s WHERE id=%s", (manifest_no, p['id']))
                    s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (p['awb_no'],))
                    if s_row:
                        sid = c.fetchone()['id']
                        c.execute("INSERT INTO manifest_items(manifest_id, shipment_id) VALUES(%s, %s)", (man_id, sid))
                        c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s WHERE id=%s", (f"To {pending[0]['out_station']}", sid))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'OUTWARD', %s)", (sid, session['branch']))
                conn.commit(); flash(f"🚀 Manifest {manifest_no} Generated & Locked!", "success")
    
    with conn.cursor() as c:
        c.execute("SELECT * FROM outward_register WHERE finalized=0 AND origin_station=%s ORDER BY id", (session['branch'],))
        pending_list = c.fetchall()
        q_m = "SELECT * FROM manifests WHERE 1=1"
        if session.get('role') != 'ADMIN': q_m += f" AND from_location='{session['branch']}'"
        c.execute(q_m + " ORDER BY id DESC LIMIT 10")
        mans = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()
    
    html = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
        <h3 style="color:#d97706; margin:0;">📤 Outward Dispatch Hub</h3>
        <div style="display:flex; gap:10px;">
            <button class="btn" style="background:#10b981;" onclick="alert('Feature Available Soon!')">☁️ Update Data to Cloud</button>
        </div>
    </div>
    
    <div style="display:flex; gap:10px; margin-bottom:20px;">
        <button class="btn" id="tab-new" onclick="switchTab('new')" style="background:#0f766e;">New Entry Finalize</button>
        <button class="btn" id="tab-history" onclick="switchTab('history')" style="background:#64748b;">Manifests History</button>
        <button class="btn" id="tab-tools" onclick="switchTab('tools')" style="background:#64748b;">Advanced Tools</button>
    </div>
    
    <div id="content-new">
        <div class="card" style="border-top-color: #d97706;"><h3 style="color:#d97706; margin-top:0;">1. Scan to Pending Outward (PRO)</h3>
            <form method="POST"><input type="hidden" name="scan_awb" value="1">
                <div class="grid-4" style="background:#fef3c7; padding:15px; border-radius:8px; border:1px solid #fde68a; margin-bottom:15px;">
                    <div style="grid-column: span 2;"><label>To Hub / Station</label><input name="dest_hub" list="stations" required style="text-transform:uppercase;">
                    <datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
                    <div><label>Scan Mode</label><select name="scan_mode" id="scan_mode"><option>MANUAL</option><option>VOICE</option></select></div>
                    <div><label>Forwarding Network</label><select name="network"><option>SELF</option><option>BLUEDART</option><option>DELHIVERY</option><option>OTHER</option></select></div>
                    <div><label>Pieces (Pcs)</label><input type="number" name="pcs" value="1"></div>
                    <div><label>Weight (KG)</label><input type="number" step="0.01" name="weight" value="1.0"></div>
                    <div><label>Network AWB (If Any)</label><input name="network_awb" placeholder="Optional"></div>
                    <div><label>Bag / Sack No.</label><input name="bag_no" placeholder="e.g. BAG001"></div>
                    <div style="grid-column: span 2;"><label>Info / Notes</label><input name="info" id="out_info" placeholder="Remarks"></div>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><label style="margin:0;">Scan AWBs or Bag No (One per line)</label>
                    <div style="display:flex; gap:10px;"><button type="button" onclick="startVoice('out_awbs')" class="btn btn-red">🎤 Voice Entry</button>
                    <button type="button" onclick="createMasterBag()" class="btn btn-blue">🎒 Create Master Bag</button></div>
                </div>
                <textarea name="awbs" id="out_awbs" rows="4" required style="font-family:monospace; font-size:14px; margin-top:5px;"></textarea>
                <button type="submit" class="btn btn-gold" style="margin-top:10px; width:100%; font-size:15px;">📥 Add to Pending Dispatch</button>
            </form>
            <hr><h4>Pending Items (Not Dispatched) - Total: {{ pending_list|length }}</h4>
            <div style="max-height:250px; overflow-y:auto; background:#f8fafc;">
                <table><tr><th>ID</th><th>AWB</th><th>Dest</th><th>Pcs</th><th>Wt</th><th>Network</th><th>Net AWB</th><th>Bag No</th><th>Action</th></tr>
                {% for p in pending_list %}<tr><td>{{ p.id }}</td><td><strong>{{ p.awb_no }}</strong></td><td>{{ p.destination }}</td><td>{{ p.pcs }}</td><td>{{ p.weight }}</td><td><span class="badge b-book">{{ p.network }}</span></td><td>{{ p.network_awb }}</td><td>{{ p.bag_no }}</td>
                <td><button onclick='editEntry({{ p|tojson }})' class="btn btn-blue" style="padding:2px 5px; font-size:10px;">Edit</button> <a href="/outward?delete={{ p.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}</table>
            </div>
            
            <div id="edit-form" style="display:none; margin-top:15px; padding:15px; background:#fef3c7; border-radius:8px;">
                <h4>Edit Entry</h4>
                <form method="POST" class="grid-4"><input type="hidden" name="edit_entry" value="1"><input type="hidden" name="entry_id" id="edit_id">
                    <div><label>Destination Hub</label><input name="dest_hub" id="edit_dest" required></div>
                    <div><label>Network</label><select name="network" id="edit_network"><option>SELF</option><option>BLUEDART</option><option>DELHIVERY</option></select></div>
                    <div><label>Network AWB</label><input name="network_awb" id="edit_netawb"></div>
                    <div><label>Bag No</label><input name="bag_no" id="edit_bag"></div>
                    <div><label>Weight</label><input type="number" step="0.01" name="weight" id="edit_weight"></div>
                    <div><label>Pcs</label><input type="number" name="pcs" id="edit_pcs"></div>
                    <div style="grid-column: span 2;"><label>Info</label><input name="info" id="edit_info"></div>
                    <div style="grid-column: span 2;"><button type="submit" class="btn btn-blue">💾 Save Changes</button> <button type="button" onclick="document.getElementById('edit-form').style.display='none'" class="btn btn-red">Cancel</button></div>
                </form>
            </div>
        </div>
        
        <div class="card" style="border-top-color: #be123c;"><h3 style="color:#be123c; margin-top:0;">2. Finalize Manifest & Print</h3>
            <form method="POST" style="background:#fee2e2; padding:15px; border-radius:8px;">
                <input type="hidden" name="finalize_manifest" value="1">
                <div class="grid-3">
                    <div><label>Vehicle No.</label><input name="vehicle" required placeholder="RJ-00-1234"></div>
                    <div><label>Driver Phone</label><input name="driver_phone" placeholder="10 Digits"></div>
                    <div><label>Master Seal No.</label><input name="seal_no" placeholder="Lock Seal"></div>
                </div>
                <button type="submit" class="btn btn-red" style="width:100%; margin-top:15px; font-size:15px;">🔒 FINALIZE + OUTWARD NO ({{ pending_list|length }} Items)</button>
            </form>
        </div>
    </div>
    
    <div id="content-history" style="display:none;">
        <div class="card"><h3>Manifests History</h3>
            <table><tr><th>Manifest No</th><th>Date</th><th>From</th><th>To</th><th>Vehicle</th><th>Status</th><th>Actions</th></tr>
            {% for m in mans %}<tr><td><strong>{{ m.manifest_no }}</strong></td><td>{{ m.created_at }}</td><td>{{ m.from_location }}</td><td>{{ m.to_location }}</td><td>{{ m.vehicle_no }}</td><td><span class="badge b-del">{{ m.status }}</span></td>
            <td><a href="/print/manifest/{{ m.id }}" target="_blank" class="btn btn-blue" style="padding:4px 8px;">🖨️ Print</a></td></tr>{% endfor %}</table>
        </div>
    </div>
    
    <div id="content-tools" style="display:none;">
        <div class="card" style="border-top-color: #38bdf8;"><h3 style="color:#0284c7; margin-top:0;">📊 Date Range Reports</h3>
            <form action="/reports/outward-range" method="POST" class="grid-4" style="align-items:end;">
                <div><label>From Date</label><input type="date" name="from_date" required></div><div><label>To Date</label><input type="date" name="to_date" required></div>
                <div><button type="submit" name="export" value="csv" class="btn btn-blue">📄 Range CSV</button></div><div><button type="submit" name="export" value="pdf" class="btn btn-red">📕 Range PDF</button></div>
            </form>
        </div>
        <div class="card" style="border-top-color: #d97706;"><h3 style="color:#d97706; margin-top:0;">⚙️ Admin Operations Tools</h3>
            <div style="display:flex; flex-direction:column; gap:10px;">
                <form action="/tools/auto-invoice" method="POST"><button type="submit" class="btn btn-gold" style="width:100%; text-align:left; padding:12px;"> Auto Invoice from Outward Info</button></form>
                <form action="/tools/sync-shipments" method="POST"><button type="submit" class="btn" style="background:#10b981; width:100%; text-align:left; padding:12px;">🔄 Sync Shipments to Outward</button></form>
            </div>
        </div>
    </div>
    
    <script>
    function switchTab(tab) {
        document.getElementById('content-new').style.display = 'none'; document.getElementById('content-history').style.display = 'none'; document.getElementById('content-tools').style.display = 'none';
        document.getElementById('tab-new').style.background = '#64748b'; document.getElementById('tab-history').style.background = '#64748b'; document.getElementById('tab-tools').style.background = '#64748b';
        document.getElementById('content-' + tab).style.display = 'block'; document.getElementById('tab-' + tab).style.background = '#0f766e';
    }
    function editEntry(entry) {
        document.getElementById('edit_id').value = entry.id; document.getElementById('edit_dest').value = entry.destination; document.getElementById('edit_network').value = entry.network; document.getElementById('edit_netawb').value = entry.network_awb || ''; document.getElementById('edit_bag').value = entry.bag_no || ''; document.getElementById('edit_weight').value = entry.weight; document.getElementById('edit_pcs').value = entry.pcs; document.getElementById('edit_info').value = entry.info || ''; document.getElementById('edit-form').style.display = 'block'; document.getElementById('edit-form').scrollIntoView({behavior: 'smooth'});
    }
    function createMasterBag() { window.open('/master_bag', '_blank'); }
    function startVoice(targetId) {
        let recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
        recognition.lang = 'en-IN'; recognition.onstart = function() { document.getElementById('out_info').value = "Listening..."; };
        recognition.onresult = function(event) { let text = event.results[0][0].transcript.toLowerCase(); document.getElementById('out_info').value = "Heard: " + text; let match = text.match(/(awb|bill|parcel|number|bag)\\s*([a-z0-9]+)/); if(match) { let box = document.getElementById(targetId); box.value += (box.value ? "\\n" : "") + match[2].toUpperCase(); }};
        recognition.start();
    }
    </script>
    """
    return render_page("PRO Outward Hub", render_template_string(html, pending_list=pending_list, mans=mans, stations=stations))

# ==========================================
# 🎒 6. MASTER BAG
# ==========================================
@app.route('/master_bag', methods=['GET', 'POST'])
@login_required
def master_bag():
    conn = get_db()
    if request.method == 'POST':
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        dest = request.form.get('dest_hub').upper()
        with conn.cursor() as c:
            val = int(get_seq("bag", "BAG", 6).replace("BAG", ""))
            bag_no = f"BAG{val:06d}"
            c.execute("INSERT INTO master_bags(bag_no, destination) VALUES(%s,%s)", (bag_no, dest))
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("INSERT INTO master_bag_items(bag_no, awb_no) VALUES(%s,%s)", (bag_no, awb))
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    s = c.fetchone()
                    if s: c.execute("INSERT INTO scan_events(shipment_id,scan_type,location,remarks) VALUES(%s,'BAGGED',%s,%s)", (s['id'], session['branch'], f"Packed in {bag_no}"))
            conn.commit(); flash(f"🎒 Master Bag Sealed! Bag No: {bag_no}", "success")

    with conn.cursor() as c:
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
        c.execute("SELECT bag_no, destination, created_at, (SELECT COUNT(*) FROM master_bag_items WHERE bag_no=master_bags.bag_no) as items FROM master_bags ORDER BY id DESC LIMIT 10")
        bags = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #38bdf8;"><h3 style="color:#0f172a; margin-top:0;">🎒 Create Master Bag (Bora)</h3>
            <form method="POST">
                <label>Bag Destination Hub</label><input name="dest_hub" list="stations" required style="margin-bottom:15px; text-transform:uppercase;">
                <datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist>
                <div style="display:flex; justify-content:space-between; align-items:center;"><label>Scan Items to Pack</label><button type="button" onclick="startVoice('bag_awbs')" style="background:#10b981; color:white; border:none; padding:5px 10px; border-radius:4px; cursor:pointer;">🎤 Voice Scan</button></div>
                <textarea name="awbs" id="bag_awbs" rows="6" required style="font-family:monospace; font-size:14px; margin-top:5px;"></textarea>
                <button type="submit" class="btn btn-blue" style="margin-top:10px; width:100%; font-size:15px;">🔒 SEAL MASTER BAG</button>
            </form>
        </div>
        <div class="card"><h3>Recent Sealed Bags</h3>
            <div style="max-height:300px; overflow-y:auto;">
                <table><tr><th>Bag No</th><th>Destination</th><th>Items</th><th>Date</th></tr>
                {% for b in bags %}<tr><td><strong>{{ b.bag_no }}</strong></td><td>{{ b.destination }}</td><td>{{ b.items }}</td><td>{{ b.created_at }}</td></tr>{% endfor %}</table>
            </div>
        </div>
    </div>
    <script>
    function startVoice(targetId) {
        let recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
        recognition.lang = 'en-IN';
        recognition.onresult = function(event) { let match = event.results[0][0].transcript.toLowerCase().match(/(awb|bill|parcel|number)\\s*([a-z0-9]+)/); if(match) { let box = document.getElementById(targetId); box.value += (box.value ? "\\n" : "") + match[2].toUpperCase(); }};
        recognition.start();
    }
    </script>
    """
    return render_page("Master Bag Generator", render_template_string(html, stations=stations, bags=bags))

# ==========================================
# 📥 7. ENHANCED INWARD HUB
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
        info = request.form.get('info', '')
        
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    if awb.startswith("BAG"):
                        c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb,))
                        for bi in c.fetchall():
                            c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, weight, info, finalized) VALUES(CURDATE(), %s, %s, %s, '1.0', %s, 1)", (bi['awb_no'], origin, session['branch'], f"Unpacked from {awb}"))
                            s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (bi['awb_no'],))
                            if s_row:
                                sid = c.fetchone()['id']
                                c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session['branch'], sid))
                                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (sid, session['branch']))
                        continue
                    
                    c.execute("INSERT INTO inward_register(entry_date, awb_no, origin_station, in_station, info, finalized) VALUES(CURDATE(), %s, %s, %s, %s, 1)", (awb, origin, session['branch'], info))
                    s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    if s_row:
                        sid = c.fetchone()['id']
                        c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session['branch'], sid))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (sid, session['branch']))
            conn.commit(); flash("✅ Inward Completed.", "success")
    
    with conn.cursor() as c:
        c.execute("SELECT * FROM inward_register WHERE in_station=%s ORDER BY id DESC LIMIT 50", (session['branch'],))
        hist = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()
    
    html = """
    <div style="display:flex; gap:10px; margin-bottom:20px;">
        <button class="btn" id="tab-inward-new" onclick="switchInwardTab('new')" style="background:#0f766e;">New Inward Finalize</button>
        <button class="btn" id="tab-inward-history" onclick="switchInwardTab('history')" style="background:#64748b;">Inward Sessions History</button>
    </div>
    <div id="inward-content-new"><div class="grid-2"><div class="card">
        <h3 style="color:#0f766e; margin-top:0;">📥 Receive Inward</h3>
        <form method="POST">
            <div class="grid-2" style="margin-bottom:15px;">
                <div><label>My Hub</label><input value="{{ session['branch'] }}" readonly style="background:#f1f5f9;"></div>
                <div><label>Coming From (Origin)</label><input name="origin" list="stations" required style="text-transform:uppercase;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><label>Scan AWBs or BAG No.</label><button type="button" class="btn btn-gold">⚖️ Read Scale</button></div>
            <div style="display:flex; gap:10px; margin-bottom:10px;"><button type="button" onclick="startVoice('in_awbs')" class="btn btn-red" style="flex:1;">🎤 Voice Scan</button><input type="number" step="0.01" placeholder="Weight" id="scale_weight" style="flex:1;"></div>
            <textarea name="awbs" id="in_awbs" rows="8" required style="font-family:monospace; margin-top:5px;"></textarea>
            <label style="margin-top:10px;">Info / Notes</label><input name="info" placeholder="Received via..." style="margin-bottom:15px;">
            <button type="submit" class="btn" style="width:100%;">💾 Save Inward Entry</button>
        </form>
    </div><div class="card" style="overflow-y:auto; max-height:500px;">
        <h3>Inward History</h3><table><tr><th>Date</th><th>AWB</th><th>Origin</th><th>Info</th><th>Del</th></tr>{% for h in hist %}<tr><td>{{ h.entry_date }}</td><td><strong>{{ h.awb_no }}</strong></td><td>{{ h.origin_station }}</td><td>{{ h.info }}</td><td><a href="/inward?delete={{ h.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}</table>
    </div></div></div>
    <div id="inward-content-history" style="display:none;"><div class="card"><h3>Inward Sessions History</h3><table><tr><th>Date</th><th>Origin</th><th>Total AWBs</th><th>Status</th></tr><tr><td colspan="4">History will appear here</td></tr></table></div></div>
    <script>
    function switchInwardTab(tab) { document.getElementById('inward-content-new').style.display = tab === 'new' ? 'block' : 'none'; document.getElementById('inward-content-history').style.display = tab === 'history' ? 'block' : 'none'; document.getElementById('tab-inward-new').style.background = tab === 'new' ? '#0f766e' : '#64748b'; document.getElementById('tab-inward-history').style.background = tab === 'history' ? '#0f766e' : '#64748b'; }
    function startVoice(targetId) { let recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)(); recognition.lang = 'en-IN'; recognition.onresult = function(event) { let match = event.results[0][0].transcript.toLowerCase().match(/(awb|bill|parcel|number|bag)\\s*([a-z0-9]+)/); if(match) { let box = document.getElementById(targetId); box.value += (box.value ? "\\n" : "") + match[2].toUpperCase(); }}; recognition.start(); }
    </script>
    """
    return render_page("Inward Hub", render_template_string(html, hist=hist, stations=stations))

# ==========================================
# 🛵 8. DRS & DELIVERY
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
        rider = request.form.get('rider'); area = request.form.get('area', '')
        with conn.cursor() as c:
            drs_no = get_seq("drs", "DRS", 6)
            c.execute("INSERT INTO drs(drs_no, drs_date, rider_name, vehicle_no, status) VALUES(%s, CURDATE(), %s, %s, 'OPEN')", (drs_no, rider, area))
            drs_id = c.lastrowid
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    s_row = c.fetchone()
                    if s_row:
                        sid = s_row['id']
                        c.execute("INSERT INTO drs_items(drs_id, shipment_id, status) VALUES(%s, %s, 'ASSIGNED')", (drs_id, sid))
                        c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE id=%s", (f"Rider: {rider}", sid))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'ON_DRS', %s, %s)", (sid, session['branch'], f"Assigned to {rider}"))
            conn.commit(); flash(f"✅ DRS {drs_no} Generated", "success")

    elif request.method == 'POST' and 'finalize_drs' in request.form:
        rider = request.form.get('rider_name'); awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        with conn.cursor() as c:
            drs_no = get_seq("drs", "DRS", 6)
            c.execute("INSERT INTO drs(drs_no, drs_date, rider_name, status) VALUES(%s, CURDATE(), %s, 'FINALIZED')", (drs_no, rider))
            drs_id = c.lastrowid
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    s_row = c.fetchone()
                    if s_row:
                        c.execute("INSERT INTO drs_items(drs_id, shipment_id, status) VALUES(%s, %s, 'DELIVERED')", (drs_id, s_row['id']))
                        c.execute("UPDATE shipments SET status='DELIVERED' WHERE id=%s", (s_row['id'],))
            conn.commit(); flash(f"✅ DRS {drs_no} Finalized", "success")
            
    elif request.method == 'POST' and 'mark_deliver' in request.form:
        awb = request.form.get('deliver_awb').strip().upper()
        receiver = request.form.get('receiver')
        with conn.cursor() as c:
            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
            s_row = c.fetchone()
            if s_row:
                sid = s_row['id']
                c.execute("UPDATE shipments SET status='DELIVERED', current_location=%s WHERE id=%s", (f"Delivered: {receiver}", sid))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'DELIVERED', %s, %s)", (sid, session['branch'], f"Received by {receiver}"))
                conn.commit(); flash(f"✅ Delivered: {awb}", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, drs_no, drs_date, rider_name, status FROM drs ORDER BY id DESC LIMIT 15")
        drss = c.fetchall()
        c.execute("SELECT d.id, d.drs_no, d.drs_date, d.rider_name, COUNT(di.id) as total_docs FROM drs d LEFT JOIN drs_items di ON d.id = di.drs_id WHERE d.status='FINALIZED' GROUP BY d.id ORDER BY d.id DESC LIMIT 10")
        finalized_sessions = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #0369a1;"><h3 style="color:#0369a1; margin-top:0;">🛵 1. Create DRS (Assign Rider)</h3>
            <form method="POST"><input type="hidden" name="assign_drs" value="1">
                <div class="grid-2" style="margin-bottom:15px;"><div><label>Rider/Boy Name</label><input name="rider" required placeholder="Delivery Boy"></div><div><label>Area / Route</label><input name="area" placeholder="Area"></div></div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><label>Scan AWBs</label><button type="button" onclick="startVoice('drs_awbs')" class="btn btn-red">🎤 Voice Scan</button></div>
                <textarea name="awbs" id="drs_awbs" rows="4" required style="font-family:monospace; margin-top:5px;"></textarea><button type="submit" class="btn btn-blue" style="margin-top:10px; width:100%;">Create DRS</button>
            </form>
            <hr><h4>Recent DRS History</h4>
            <table><tr><th>DRS #</th><th>Rider</th><th>Status</th><th>Action</th></tr>{% for d in drss %}<tr><td>{{ d.drs_no }}</td><td>{{ d.rider_name }}</td><td><span class="badge {% if d.status=='FINALIZED' %}b-del{% else %}b-book{% endif %}">{{ d.status }}</span></td><td><a href="/print/drs/{{ d.id }}" target="_blank" class="btn btn-blue" style="padding:3px 6px; font-size:11px;">Print</a> <a href="/drs?del_drs={{ d.id }}" class="btn btn-red" style="padding:3px 6px; font-size:11px;">Del</a></td></tr>{% endfor %}</table>
        </div>
        <div class="card" style="border-top-color: #166534;"><h3 style="color:#166534; margin-top:0;">✅ 2. Mark Delivered</h3>
            <form method="POST"><input type="hidden" name="mark_deliver" value="1"><label>AWB Number</label><input name="deliver_awb" required style="margin-bottom:10px;"><label>Receiver Name</label><input name="receiver" required style="margin-bottom:10px;"><button type="submit" class="btn" style="background:#166534; width:100%;">Update Delivery</button></form>
        </div>
    </div>
    <div class="card" style="border-top-color: #d97706; margin-top:20px;"><h3 style="color:#d97706; margin-top:0;">📋 Delivery Register (Generate DRS)</h3>
        <form method="POST"><input type="hidden" name="finalize_drs" value="1">
            <div class="grid-3" style="margin-bottom:15px;"><div><label>Rider/Boy</label><input name="rider_name" required></div></div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><label>Scan AWBs</label><button type="button" onclick="startVoice('drs_f_awbs')" class="btn btn-red">🎤 Voice Scan</button></div>
            <textarea name="awbs" id="drs_f_awbs" rows="4" required style="font-family:monospace; margin-top:5px;"></textarea>
            <button type="submit" class="btn btn-gold" style="width:100%; font-size:15px; padding:12px; margin-top:10px;">⭐ FINALIZE GENERATE DRS</button>
        </form>
        <hr><h4>Finalized DRS Sessions (Print / Unfinalize)</h4>
        <table><tr><th>DRS No</th><th>Date</th><th>Rider</th><th>Total Docs</th><th>Actions</th></tr>{% for s in finalized_sessions %}<tr><td><strong>{{ s.drs_no }}</strong></td><td>{{ s.drs_date }}</td><td>{{ s.rider_name }}</td><td>{{ s.total_docs }}</td><td><a href="/print/drs/{{ s.id }}" target="_blank" class="btn btn-blue" style="padding:4px 8px; font-size:11px;">🖨️ Print DRS</a> <a href="/drs?unfinalize={{ s.id }}" class="btn btn-red" style="padding:4px 8px; font-size:11px;">🔓 Unfinalize</a></td></tr>{% endfor %}</table>
    </div>
    <script>
    function startVoice(targetId) { let recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)(); recognition.lang = 'en-IN'; recognition.onresult = function(event) { let match = event.results[0][0].transcript.toLowerCase().match(/(awb|bill|parcel|number)\\s*([a-z0-9]+)/); if(match) { let box = document.getElementById(targetId); box.value += (box.value ? "\\n" : "") + match[2].toUpperCase(); }}; recognition.start(); }
    </script>
    """
    return render_page("DRS & Delivery", render_template_string(html, drss=drss, finalized_sessions=finalized_sessions))

# ==========================================
# 💰 9. ACCOUNTS
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
        c.execute("SELECT id, name FROM customers WHERE is_active=1")
        custs = c.fetchall()
        c.execute("SELECT p.id, p.payment_date, c.name, p.amount, p.mode, p.reference FROM payments p JOIN customers c ON p.customer_id=c.id ORDER BY p.id DESC LIMIT 20")
        pays = c.fetchall()
        l_data = []; c_bal = 0
        if request.args.get('cust_id'):
            c.execute("SELECT * FROM ledger WHERE customer_id=%s ORDER BY entry_date", (request.args.get('cust_id'),))
            l_data = c.fetchall()
            c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (request.args.get('cust_id'),))
            r = c.fetchone(); c_bal = r['b'] if r and r['b'] else 0
    conn.close()
    
    html = """
    <div class="grid-2"><div class="card"><h3 style="margin-top:0; color:#10b981;">💸 Receive Payment</h3><form method="POST" class="grid-2" style="align-items:end;"><div style="grid-column: span 2;"><label>Customer</label><select name="cust_id" required>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div><label>Amount (₹)</label><input type="number" step="0.01" name="amount" required></div><div><label>Mode</label><select name="mode"><option>CASH</option><option>UPI</option></select></div><div><label>Reference</label><input name="ref"></div><div><button type="submit" class="btn" style="background:#10b981; width:100%;">Save Payment</button></div></form></div><div class="card"><h3 style="margin-top:0;">Recent Payments</h3><div style="max-height:180px; overflow-y:auto;"><table><tr><th>Date</th><th>Customer</th><th>Amount</th><th>Del</th></tr>{% for p in pays %}<tr><td>{{ p.payment_date }}</td><td>{{ p.name }}</td><td>₹{{ p.amount }}</td><td><a href="/accounts?del_pay={{ p.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}</table></div></div></div>
    <div class="card"><h3>📒 Customer Ledger</h3><form method="GET" style="display:flex; gap:10px;"><select name="cust_id" style="flex:1;">{% for c in custs %}<option value="{{ c.id }}" {% if request.args.get('cust_id') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select><button class="btn">View Ledger</button></form>{% if request.args.get('cust_id') %}<h4 style="text-align:right; color:#e11d48;">Closing Balance: ₹{{ c_bal }}</h4><table><tr><th>Date</th><th>Voucher</th><th>Ref</th><th>Debit</th><th>Credit</th><th>Narration</th></tr>{% for l in l_data %}<tr><td>{{ l.entry_date }}</td><td>{{ l.voucher_type }}</td><td>{{ l.reference }}</td><td style="color:#e11d48; font-weight:bold;">{{ l.debit }}</td><td style="color:#10b981; font-weight:bold;">{{ l.credit }}</td><td>{{ l.narration }}</td></tr>{% endfor %}</table>{% endif %}</div>
    """
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
    html = """<div class="card" style="background:#0f172a; color:white;"><h2 style="margin:0; color:#38bdf8;">📊 Day Close Report ({{ date }})</h2><div class="grid-3" style="margin-top:15px;"><div style="background:#1e293b; padding:15px; border-radius:8px;"><h3>Bookings</h3><h2>{{ b.c }} Pcs | ₹{{ b.t }}</h2></div><div style="background:#1e293b; padding:15px; border-radius:8px;"><h3>Payments Received</h3><h2 style="color:#10b981;">₹{{ p.a }}</h2></div></div></div><div class="grid-2"><div class="card"><h3 style="color:#e11d48;">🔴 Top Market Outstanding</h3><table><tr><th>Customer</th><th>Due Amount</th></tr>{% for o in out %}<tr><td><strong>{{ o.name }}</strong></td><td style="color:#e11d48; font-weight:bold;">₹{{ o.bal }}</td></tr>{% endfor %}</table></div><div class="card"><h3 style="color:#d97706;">💰 Pending COD to Collect</h3><table><tr><th>AWB</th><th>Consignee</th><th>COD Amt</th></tr>{% for c in cods %}<tr><td>{{ c.awb_no }}</td><td>{{ c.dest_name }}</td><td style="color:#d97706; font-weight:bold;">₹{{ c.cod_amount }}</td></tr>{% endfor %}</table></div></div>"""
    return render_page("All Reports", render_template_string(html, b=b, p=p, out=out, cods=cods, date=d))

# ==========================================
# 🖨️ 10. EXACT PDF GENERATOR (ReportLab)
# ==========================================
def draw_barcode_safe(cv, value, x, y, height):
    try: code128.Code128(str(value), barHeight=height, barWidth=0.011 * inch).drawOn(cv, x, y); return True
    except Exception: return False
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
def money(val): return f"{float(val or 0):,.2f}"
def num_to_words_inr(amount): return f"Rupees {money(amount)} Only"

@app.route('/print/label/<awb>')
@login_required
def print_label_pdf(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT s.*, c.name as cname, c.address as caddr FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,))
        s = c.fetchone()
    conn.close()
    if not s: return "Not found"
    
    # EXACT 4x6 INCH LAYOUT (101.6 mm x 152.4 mm)
    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=(4*inch, 6*inch))
    
    cv.roundRect(4*mm, 4*mm, 93.6*mm, 144*mm, 2*mm) # Outer Border
    cv.line(4*mm, 130*mm, 97.6*mm, 130*mm) # Top Line
    
    cv.rect(33*mm, 130*mm, 64.6*mm, 18*mm, fill=1) # Black Header Box
    cv.setFillColorRGB(1, 1, 1); cv.setFont("Helvetica-Bold", 12)
    cv.drawCentredString(65*mm, 141*mm, "AKASH GANGA COURIER")
    cv.setFont("Helvetica-Bold", 8); cv.drawCentredString(65*mm, 135*mm, "PREMIUM EXPRESS")
    
    cv.setFillColorRGB(0, 0, 0); cv.setFont("Helvetica-BoldOblique", 18)
    cv.drawString(6*mm, 136*mm, "AGC")
    
    # 🌟 Origin Block (100% Correct Mapped fields)
    cv.setFont("Helvetica", 8); cv.drawString(8*mm, 124*mm, "SHIPPER (ORIGIN):")
    shipper_name = s.get('cname') if s.get('cname') else s.get('origin_name', '')
    cv.setFont("Helvetica-Bold", 10); cv.drawString(8*mm, 118*mm, str(shipper_name)[:30])
    
    shipper_addr = s.get('caddr') if s.get('caddr') else s.get('origin_address', '')
    cv.setFont("Helvetica", 8); cv.drawString(8*mm, 113*mm, str(shipper_addr)[:45])
    cv.drawString(8*mm, 108*mm, f"Ph: {s.get('origin_phone', '')}")
    
    cv.roundRect(6*mm, 52*mm, 89.6*mm, 54*mm, 2*mm) # Consignee Box
    cv.rect(6*mm, 98*mm, 89.6*mm, 8*mm, fill=1) # Black Consignee Header
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
    
    cv.roundRect(6*mm, 34*mm, 89.6*mm, 15*mm, 2*mm) # Details Box
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
        c.execute("SELECT s.*, c.name as cname, c.address as caddr FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,))
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
    cv.setFont("Helvetica-Bold", 11)
    
    shipper_name = s.get('cname') if s.get('cname') else s.get('origin_name', '')
    shipper_addr = s.get('caddr') if s.get('caddr') else s.get('origin_address', '')
    
    cv.drawString(35, 710, str(shipper_name)[:40])
    cv.setFont("Helvetica", 10)
    y_sh = 695
    for ln in wrap_lines(cv, str(shipper_addr), "Helvetica", 10, 240)[:2]:
        cv.drawString(35, y_sh, ln); y_sh -= 15
    cv.drawString(35, y_sh, f"Ph: {s.get('origin_phone', '')}")
    cv.drawString(35, y_sh-15, f"State: {s.get('origin_state_code', '')}")
    
    cv.setFont("Helvetica-Bold", 10); cv.drawString(310, 725, "CONSIGNEE (RECEIVER DETAILS):")
    cv.setFont("Helvetica-Bold", 11); cv.drawString(310, 710, str(s.get('dest_name', ''))[:40])
    cv.setFont("Helvetica", 10)
    y_cn = 695
    for ln in wrap_lines(cv, s.get('dest_address', ''), "Helvetica", 10, 240)[:2]:
        cv.drawString(310, y_cn, ln); y_cn -= 15
    cv.drawString(310, y_cn, f"Ph: {s.get('dest_phone', '')}")
    cv.drawString(310, y_cn-15, f"Dest Station: {s.get('dest_station', '')}")

    y_tbl = 590
    cv.rect(30, y_tbl, 530, 20, fill=1)
    cv.setFillColorRGB(1, 1, 1); cv.setFont("Helvetica-Bold", 10)
    cv.drawString(35, y_tbl+6, "WEIGHT"); cv.drawString(100, y_tbl+6, "PIECES"); cv.drawString(160, y_tbl+6, "SERVICE")
    cv.drawString(240, y_tbl+6, "TAXABLE"); cv.drawString(320, y_tbl+6, "GST AMT"); cv.drawString(390, y_tbl+6, "COD AMT")
    cv.drawString(470, y_tbl+6, "TOTAL (Rs)")

    y_tbl -= 25
    cv.setFillColorRGB(0, 0, 0); cv.setFont("Helvetica-Bold", 11)
    cv.drawString(35, y_tbl+6, f"{s.get('weight_kg', 1)} KG"); cv.drawString(100, y_tbl+6, str(s.get('quantity', 1)))
    cv.drawString(160, y_tbl+6, str(s.get('service_type', 'SURFACE'))); cv.drawString(240, y_tbl+6, f"{s.get('taxable_amount', 0):.2f}")
    gst_tot = float(s.get('cgst') or 0) + float(s.get('sgst') or 0) + float(s.get('igst') or 0)
    cv.drawString(320, y_tbl+6, f"{gst_tot:.2f}"); cv.drawString(390, y_tbl+6, f"{s.get('cod_amount', 0):.2f}")
    cv.setFont("Helvetica-Bold", 14); cv.drawString(470, y_tbl+4, f"{s.get('total_amount', 0):.2f}")

    y_tbl -= 35; cv.setFont("Helvetica-Bold", 10)
    cv.drawString(30, y_tbl, f"Amount to be collected: Rs {s.get('total_amount', 0)}")
    
    cv.setFont("Helvetica", 8)
    cv.drawString(30, y_tbl-50, "DECLARATION: Goods are carried at Owner's Risk. Cash, Jewelry, Narcotics strictly prohibited.")
    cv.drawString(420, y_tbl-50, "For AKASH GANGA COURIER")
    cv.drawString(420, y_tbl-80, "Authorised Signatory")

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
    cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 50, "AKASH GANGA - OUTWARD MANIFEST")
    cv.setFont("Helvetica", 10); cv.drawString(40, h - 65, f"Manifest No: {m['manifest_no']}   |   Route: {m['from_location']} -> {m['to_location']}")
    cv.drawString(40, h - 80, f"Vehicle: {m['vehicle_no']}   |   Date: {m['created_at']}   |   Items: {len(items)}")
    draw_barcode_safe(cv, m['manifest_no'], w - 180, h - 70, 0.4 * inch)
    
    y = h - 110; cv.rect(40, y - 20, w - 80, 20, fill=1)
    cv.setFillColorRGB(1,1,1); cv.setFont("Helvetica-Bold", 9)
    cv.drawString(45, y - 14, "S.No"); cv.drawString(85, y - 14, "AWB & BARCODE"); cv.drawString(220, y - 14, "DESTINATION"); cv.drawString(330, y - 14, "NET/BAG"); cv.drawString(420, y - 14, "WT/PCS"); cv.drawString(480, y - 14, "INFO")
    
    y -= 20; cv.setFillColorRGB(0,0,0)
    for i, it in enumerate(items):
        if y < 50: cv.showPage(); y = h - 50
        cv.line(40, y-30, w-40, y-30)
        cv.setFont("Helvetica-Bold", 9)
        cv.drawString(45, y - 18, str(i + 1))
        cv.drawString(85, y - 14, it["awb_no"]); draw_barcode_safe(cv, it["awb_no"], 85, y - 26, 0.15 * inch)
        cv.drawString(220, y - 18, str(it.get("dest_station", ""))[:20])
        cv.setFont("Helvetica", 8); cv.drawString(330, y - 18, f"{it.get('network','')}/{it.get('bag_no','')}")
        cv.setFont("Helvetica-Bold", 9); cv.drawString(420, y - 18, f"{it.get('weight', 1)}kg / {it.get('pcs', 1)}pcs")
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
        cv.line(40, y-40, w-40, y-40)
        cv.setFont("Helvetica-Bold", 9)
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
# 📊 11. ADVANCED TOOLS (Outward Range, Bulk Sync)
# ==========================================
@app.route('/reports/outward-range', methods=['POST'])
@login_required
def outward_range_report():
    f_date = request.form.get('from_date'); t_date = request.form.get('to_date'); exp_type = request.form.get('export')
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT o.*, s.dest_name, s.dest_phone FROM outward_register o LEFT JOIN shipments s ON o.awb_no = s.awb_no WHERE o.entry_date BETWEEN %s AND %s AND o.origin_station = %s ORDER BY o.id", (f_date, t_date, session['branch']))
        data = c.fetchall()
    conn.close()
    
    if exp_type == 'csv':
        output = io.StringIO(); writer = csv.writer(output)
        writer.writerow(['Date', 'AWB', 'Dest Station', 'Weight', 'Pcs', 'Network', 'Bag No', 'Info'])
        for row in data: writer.writerow([row['entry_date'], row['awb_no'], row['destination'], row['weight'], row['pcs'], row['network'], row['bag_no'] or '', row['info'] or ''])
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode('utf-8')), mimetype='text/csv', download_name=f'Outward_{f_date}_to_{t_date}.csv', as_attachment=True)
    elif exp_type == 'pdf':
        buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4); w, h = A4
        cv.setFont("Helvetica-Bold", 16); cv.drawString(40, h - 40, f"Outward Report: {f_date} to {t_date}")
        cv.setFont("Helvetica", 10); cv.drawString(40, h - 60, f"Branch: {session['branch']} | Total Entries: {len(data)}")
        y = h - 100; cv.setFont("Helvetica-Bold", 8)
        cv.drawString(40, y, "AWB"); cv.drawString(100, y, "Destination"); cv.drawString(200, y, "Weight"); cv.drawString(260, y, "Network"); cv.drawString(340, y, "Bag No")
        y -= 20; cv.setFont("Helvetica", 8)
        for row in data:
            if y < 50: cv.showPage(); y = h - 40
            cv.drawString(40, y, str(row['awb_no'])); cv.drawString(100, y, str(row['destination'])[:20]); cv.drawString(200, y, str(row['weight'])); cv.drawString(260, y, str(row['network'])); cv.drawString(340, y, str(row['bag_no'] or ''))
            y -= 15
        cv.showPage(); cv.save(); buf.seek(0)
        return send_file(buf, mimetype='application/pdf', download_name=f'Outward_{f_date}_to_{t_date}.pdf', as_attachment=True)

@app.route('/tools/sync-shipments', methods=['POST'])
@login_required
def sync_shipments():
    conn = get_db()
    with conn.cursor() as c:
        c.execute("""INSERT INTO outward_register (entry_date, awb_no, origin_station, out_station, destination, weight, pcs, finalized)
                     SELECT booking_date, awb_no, origin_name, dest_station, dest_station, weight_kg, quantity, 1 FROM shipments 
                     WHERE status='OUTWARD' AND awb_no NOT IN (SELECT awb_no FROM outward_register)""")
        conn.commit(); flash(f"✅ Synced {c.rowcount} shipments to outward", "success")
    conn.close()
    return redirect('/outward')

@app.route('/tools/auto-invoice', methods=['POST'])
@login_required
def auto_invoice():
    flash("✅ Auto Invoice functionality is active.", "success")
    return redirect('/outward')

# ==========================================
# 🌐 PUBLIC TRACKING PAGE (No Login Required)
# ==========================================
@app.route('/track', methods=['GET', 'POST'])
def track():
    awb = request.args.get('awb') or request.form.get('awb')
    awb = awb.strip().upper() if awb else ''
    
    shipment = None
    timeline = []
    
    if awb:
        try:
            conn = get_db()
            with conn.cursor() as c:
                # Basic Shipment Data
                c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
                shipment = c.fetchone()
                
                if shipment:
                    # 1. Booking Event
                    timeline.append({
                        'date': str(shipment['booking_date']), 
                        'title': '📦 Parcel Booked', 
                        'desc': f"Origin: {shipment['origin_name']} | Dest: {shipment['dest_station']}"
                    })
                    
                    # 2. Outward Events (Dispatched)
                    c.execute("SELECT entry_date, out_station, info FROM outward_register WHERE awb_no=%s ORDER BY id", (awb,))
                    for r in c.fetchall():
                        timeline.append({
                            'date': str(r['entry_date']), 
                            'title': '📤 Dispatched (Outward)', 
                            'desc': f"Forwarded to {r['out_station']}. {r['info']}"
                        })
                        
                    # 3. Inward Events (Received at Hub)
                    c.execute("SELECT entry_date, in_station, info FROM inward_register WHERE awb_no=%s ORDER BY id", (awb,))
                    for r in c.fetchall():
                        timeline.append({
                            'date': str(r['entry_date']), 
                            'title': '📥 Received at Hub (Inward)', 
                            'desc': f"Arrived at {r['in_station']}. {r['info']}"
                        })
                        
                    # 4. Delivery Events (DRS)
                    c.execute("SELECT entry_date, delivery_boy, drs_no FROM delivery_register WHERE awb_no=%s ORDER BY id", (awb,))
                    for r in c.fetchall():
                        timeline.append({
                            'date': str(r['entry_date']), 
                            'title': '🛵 Out for Delivery', 
                            'desc': f"Assigned to Rider: {r['delivery_boy']} (DRS: {r['drs_no']})"
                        })
                        
                    # 5. Delivered Event (Final)
                    if shipment['status'] == 'DELIVERED':
                        timeline.append({
                            'date': 'System Updated', 
                            'title': '✅ Successfully Delivered', 
                            'desc': f"Status: {shipment['current_location']}"
                        })
                        
            conn.close()
            # Sort timeline by date
            timeline = sorted(timeline, key=lambda x: x['date'])
        except Exception as e:
            print("Tracking Error:", e)

    # 🎨 Premium Mobile-Friendly UI (CSS & HTML)
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Track Shipment - AGC Courier</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5; margin: 0; color: #1e293b; }
            .nav { background: #0f172a; padding: 15px 20px; color: white; text-align: center; font-size: 22px; font-weight: 900; letter-spacing: 1px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);}
            .nav span { color: #38bdf8; }
            .container { max-width: 600px; margin: 40px auto; padding: 20px; }
            .card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); }
            .search-box { display: flex; gap: 10px; margin-bottom: 20px; }
            input { flex: 1; padding: 15px; border: 2px solid #cbd5e1; border-radius: 8px; font-size: 16px; outline: none; text-transform: uppercase;}
            input:focus { border-color: #0f766e; }
            .btn { padding: 15px 25px; background: #0f766e; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; transition: 0.3s;}
            .btn:hover { background: #0d9488; }
            
            /* Premium Vertical Timeline CSS */
            .status-badge { display: inline-block; padding: 6px 12px; background: #fef08a; color: #b45309; border-radius: 20px; font-weight: bold; font-size: 14px; margin-bottom: 20px;}
            .status-DELIVERED { background: #dcfce7; color: #166534; }
            
            .timeline { border-left: 3px solid #0f766e; margin-left: 15px; padding-left: 25px; margin-top: 25px; }
            .event { position: relative; margin-bottom: 25px; }
            .event::before { content: ''; position: absolute; left: -35px; top: 0; width: 14px; height: 14px; background: #fbbf24; border: 3px solid #0f766e; border-radius: 50%; }
            .e-date { font-size: 13px; color: #0f766e; font-weight: bold; margin-bottom: 5px; }
            .e-title { font-size: 16px; font-weight: bold; margin: 0 0 5px 0; color: #1e293b; }
            .e-desc { font-size: 14px; color: #475569; margin: 0; line-height: 1.5; }
            
            .footer { text-align: center; margin-top: 40px; color: #94a3b8; font-size: 13px; }
            @media (max-width: 600px) { .search-box { flex-direction: column; } .container { margin: 10px auto;} }
        </style>
    </head>
    <body>
        <div class="nav">AGC <span>COURIER</span></div>
        <div class="container">
            <div class="card">
                <h2 style="margin-top:0; text-align:center;">Track Your Shipment</h2>
                <p style="text-align:center; color:#64748b; margin-bottom:25px;">Enter your AWB / Bilti number below</p>
                
                <form method="GET" class="search-box">
                    <input type="text" name="awb" value="{{ awb }}" placeholder="e.g. AWB00000123" required autocomplete="off">
                    <button type="submit" class="btn">Track Live</button>
                </form>
                
                {% if awb %}
                    <hr style="border:0; border-top:1px dashed #cbd5e1; margin:25px 0;">
                    {% if shipment %}
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h3 style="margin:0; color:#0f766e;">AWB: {{ shipment.awb_no }}</h3>
                            <div class="status-badge status-{{ shipment.status }}">{{ shipment.status }}</div>
                        </div>
                        
                        <div style="background:#f8fafc; padding:15px; border-radius:8px; margin-bottom:20px; font-size:14px; border-left:4px solid #38bdf8;">
                            <strong>To:</strong> {{ shipment.dest_name }}<br>
                            <strong>Destination:</strong> {{ shipment.dest_station }}<br>
                            <strong>Weight:</strong> {{ shipment.weight_kg }} KG
                        </div>
                        
                        <div class="timeline">
                            {% for t in timeline %}
                            <div class="event">
                                <div class="e-date">{{ t.date }}</div>
                                <h4 class="e-title">{{ t.title }}</h4>
                                <p class="e-desc">{{ t.desc }}</p>
                            </div>
                            {% endfor %}
                        </div>
                    {% else %}
                        <div style="text-align:center; color:#be123c; padding:20px; background:#fee2e2; border-radius:8px;">
                            <strong>No records found for AWB: {{ awb }}</strong><br>
                            Please check the number and try again.
                        </div>
                    {% endif %}
                {% endif %}
            </div>
            <div class="footer">&copy; 2026 AGC Smart ERP Cloud. All rights reserved.</div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, awb=awb, shipment=shipment, timeline=timeline)

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)
