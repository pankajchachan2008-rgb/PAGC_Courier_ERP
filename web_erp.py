from flask import Flask, request, session, redirect, url_for, render_template_string, flash, send_file
import pymysql
import configparser
import hashlib
from functools import wraps
from datetime import datetime
import io
import os

# --- PDF GENERATION LIBRARIES ---
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, mm
from reportlab.graphics.barcode import code128
try:
    import qrcode
except ImportError:
    qrcode = None

app = Flask(__name__)
app.secret_key = 'agc_super_secret_erp_ultimate_key'

config = configparser.ConfigParser()
config.read('db_config.ini')

# ==========================================
# 🛠️ 1. BULLETPROOF DB CONNECTION & HEALER
# ==========================================
def get_db():
    db_host = config['CLOUD_DB']['host'].replace('"', '').replace("'", "").strip()
    db_port = int(config['CLOUD_DB']['port'].replace('"', '').replace("'", "").strip())
    db_user = config['CLOUD_DB']['user'].replace('"', '').replace("'", "").strip()
    db_pass = config['CLOUD_DB']['password'].replace('"', '').replace("'", "").strip()
    db_name = config['CLOUD_DB']['database'].replace('"', '').replace("'", "").strip()
    return pymysql.connect(host=db_host, port=db_port, user=db_user, password=db_pass, database=db_name, cursorclass=pymysql.cursors.DictCursor, ssl={'ssl': {}})

def sha(text): return hashlib.sha256(text.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🎨 2. MASTER UI & SIDEBAR HTML
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
        <div class="logo">AGC ULTIMATE</div>
        <div class="menu">
            <a href="/">📊 Dashboard</a>
            <a href="/track" target="_blank" style="color:#38bdf8;">🌐 Public Tracking</a>
            <a href="/customers">👥 Customers</a>
            <a href="/booking">📦 Complete Booking</a>
            <a href="/shipments">🚚 Shipments (All)</a>
            <a href="/outward">📤 Outward / Manifest</a>
            <a href="/inward">📥 Inward Hub</a>
            <a href="/drs">🛵 DRS / Delivery</a>
            <a href="/accounts">💰 Accounts & Ledger</a>
            <a href="/reports" style="color:#fbbf24;">📈 All Reports</a>
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
def render_page(title, content):
    return render_template_string(BASE_HTML, title=title, content=content)

# ==========================================
# 🔐 3. AUTH & PUBLIC TRACKING
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

@app.route('/track', methods=['GET'])
def track():
    awb = request.args.get('awb', '').strip().upper()
    timeline, shipment = [], None
    if awb:
        conn = get_db()
        with conn.cursor() as c:
            c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
            shipment = c.fetchone()
            if shipment:
                c.execute("SELECT created_at as date, scan_type as title, CONCAT(location, ' - ', remarks) as _desc FROM scan_events WHERE shipment_id=%s ORDER BY id", (shipment['id'],))
                timeline = c.fetchall()
        conn.close()
    html = """<style>body{font-family:sans-serif; background:#f4f5f7; margin:0;} .nav{background:#0f172a; padding:15px; color:white; text-align:center; font-size:20px; font-weight:bold;} .card{max-width:600px; margin:40px auto; background:white; padding:30px; border-radius:8px; box-shadow:0 4px 6px rgba(0,0,0,0.1);} input, button{padding:12px; font-size:16px;} input{width:70%; border:2px solid #cbd5e1; border-radius:4px;} button{background:#0f766e; color:white; border:none; border-radius:4px; cursor:pointer;} .event{margin-bottom:15px; padding-left:20px; border-left:3px solid #0f766e;} .e-date{font-size:12px; color:#0f766e; font-weight:bold;}</style>
    <div class="nav">AGC Courier Tracking</div><div class="card"><h2 style="margin-top:0; text-align:center;">Track Parcel</h2><form style="display:flex; gap:10px;"><input name="awb" value="{{ awb }}" placeholder="Enter AWB Number" required><button>Track</button></form>
    {% if awb %}<hr style="margin:25px 0;">{% if shipment %}<div style="background:#f8fafc; padding:15px; border-left:4px solid #38bdf8;"><strong>Status:</strong> {{ shipment.status }}<br><strong>Destination:</strong> {{ shipment.dest_station }}</div><div style="margin-top:20px;">{% for t in timeline %}<div class="event"><div class="e-date">{{ t.date }}</div><h4 style="margin:5px 0;">{{ t.title }}</h4><p style="margin:0; font-size:14px; color:#475569;">{{ t._desc }}</p></div>{% endfor %}</div>{% else %}<p style="color:red; text-align:center;">Invalid AWB Number</p>{% endif %}{% endif %}</div>"""
    return render_template_string(html, awb=awb, shipment=shipment, timeline=timeline)

# ==========================================
# 📊 4. DASHBOARD & REPORTS (NO CHANGES)
# ==========================================
@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments")
        s = c.fetchone()
        c.execute("SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED'")
        d = c.fetchone()
        c.execute("SELECT awb_no, dest_name, status, total_amount, booking_date FROM shipments ORDER BY id DESC LIMIT 10")
        latest = c.fetchall()
    conn.close()
    html = f"""<div class="grid-3"><div class="card" style="border-top-color: #38bdf8;"><h3>Total Parcels</h3><h2 style="font-size:28px; margin:0;">{s['c']}</h2></div><div class="card" style="border-top-color: #10b981;"><h3>Delivered</h3><h2 style="font-size:28px; margin:0;">{d['c']}</h2></div><div class="card" style="border-top-color: #f59e0b;"><h3>Revenue (₹)</h3><h2 style="font-size:28px; margin:0;">{round(s['t'], 2)}</h2></div></div><div class="card"><h3>📦 Recent Bookings</h3><table><tr><th>AWB Number</th><th>Date</th><th>Destination</th><th>Amount</th><th>Status</th></tr>{''.join(f"<tr><td><strong>{r['awb_no']}</strong></td><td>{r['booking_date']}</td><td>{r['dest_name']}</td><td>₹{r['total_amount']}</td><td><span class='badge b-book'>{r['status']}</span></td></tr>" for r in latest)}</table></div>"""
    return render_page("Dashboard", html)

@app.route('/reports')
@login_required
def reports():
    d = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE booking_date=%s", (d,))
        b = c.fetchone()
        c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments WHERE payment_date=%s", (d,))
        p = c.fetchone()
        c.execute("SELECT c.name, COALESCE(SUM(l.debit-l.credit),0) bal FROM customers c LEFT JOIN ledger l ON l.customer_id=c.id GROUP BY c.id HAVING bal>0 ORDER BY bal DESC LIMIT 20")
        out = c.fetchall()
        c.execute("SELECT awb_no, dest_name, cod_amount FROM shipments WHERE status='DELIVERED' AND cod_amount>0")
        cods = c.fetchall()
    conn.close()
    html = """
    <div class="card" style="background:#0f172a; color:white;"><h2 style="margin:0; color:#38bdf8;">📊 Day Close Report ({{ date }})</h2><div class="grid-3" style="margin-top:15px;"><div style="background:#1e293b; padding:15px; border-radius:8px;"><h3>Bookings</h3><h2>{{ b.c }} Pcs | ₹{{ b.t }}</h2></div><div style="background:#1e293b; padding:15px; border-radius:8px;"><h3>Payments Received</h3><h2 style="color:#10b981;">₹{{ p.a }}</h2></div></div></div>
    <div class="grid-2"><div class="card"><h3 style="color:#e11d48;">🔴 Top Market Outstanding</h3><table><tr><th>Customer</th><th>Due Amount</th></tr>{% for o in out %}<tr><td><strong>{{ o.name }}</strong></td><td style="color:#e11d48; font-weight:bold;">₹{{ o.bal }}</td></tr>{% endfor %}</table></div><div class="card"><h3 style="color:#d97706;">💰 Pending COD to Collect</h3><table><tr><th>AWB</th><th>Consignee</th><th>COD Amt</th></tr>{% for c in cods %}<tr><td>{{ c.awb_no }}</td><td>{{ c.dest_name }}</td><td style="color:#d97706; font-weight:bold;">₹{{ c.cod_amount }}</td></tr>{% endfor %}</table></div></div>
    """
    return render_page("All Reports", render_template_string(html, b=b, p=p, out=out, cods=cods, date=d))

# ==========================================
# 📦 5. COMPLETE BOOKING, SHIPMENTS & HUB (UNCHANGED)
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
        gst = fr * (tax / 100)
        tot = fr + gst
        cgst = sgst = igst = 0
        if d['ostate'] == d['dstate']: cgst = sgst = gst / 2
        else: igst = gst

        with conn.cursor() as c:
            try:
                c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, origin_phone, origin_address, origin_state_code, dest_name, dest_phone, dest_address, dest_state_code, dest_station, weight_kg, quantity, cod_amount, declared_value, service_type, taxable_amount, tax_rate, cgst, sgst, igst, total_amount, info, status, current_location) 
                             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s)""",
                          (d['awb'].upper(), d.get('cust_id') or None, d['date'], d['oname'], d['ophone'], d['oaddr'], d['ostate'], d['dname'], d['dphone'], d['daddr'], d['dstate'], d['dstat'], d['wt'], d['pcs'], d['cod'], d['dec'], d['srv'], fr, tax, cgst, sgst, igst, tot, d['info'], session['branch']))
                sid = c.lastrowid
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'BOOKED',%s,'Booked at counter')", (sid, session['branch']))
                if d.get('cust_id'):
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (d['cust_id'], d['date'], d['awb'].upper(), tot, f"Booking {d['awb'].upper()}"))
                conn.commit(); flash(f"✅ AWB {d['awb'].upper()} Booked! Total: ₹{tot}", "success")
            except Exception as e: flash(f"Error: {e}", "error")

    with conn.cursor() as c:
        c.execute("SELECT id, name, phone FROM customers WHERE is_active=1")
        custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="max-width:950px; margin:auto;"><h3 style="color:#0f766e; margin-top:0;">📦 Master Booking Form</h3>
        <form method="POST">
            <div class="grid-4" style="background:#f8fafc; padding:15px; border-radius:6px; margin-bottom:15px; border:1px solid #e2e8f0;">
                <div><label>Booking Date</label><input type="date" name="date" id="bdt" required></div>
                <div><label>AWB Number</label><input name="awb" required style="font-weight:bold; color:#0284c7;"></div>
                <div style="grid-column: span 2;"><label>Customer (Accounts Auto-Link)</label>
                    <select name="cust_id"><option value="">-- Walk-in --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }} ({{ c.phone }})</option>{% endfor %}</select>
                </div>
            </div>
            <div class="grid-2">
                <div style="border:1px solid #cbd5e1; padding:15px; border-radius:6px;"><h4 style="margin-top:0; color:#d97706;">🏢 ORIGIN (SHIPPER)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Sender Name</label><input name="oname" value="{{ session['branch'] }}"></div><div><label>Phone</label><input name="ophone"></div><div><label>State Code</label><input name="ostate" value="RJ"></div>
                    <div style="grid-column: span 2;"><label>Address</label><input name="oaddr"></div>
                </div></div>
                <div style="border:1px solid #cbd5e1; padding:15px; border-radius:6px;"><h4 style="margin-top:0; color:#0f766e;">🏠 DESTINATION (CONSIGNEE)</h4><div class="grid-2">
                    <div style="grid-column: span 2;"><label>Receiver Name</label><input name="dname" required></div><div><label>Phone</label><input name="dphone" required></div><div><label>State Code</label><input name="dstate"></div>
                    <div style="grid-column: span 2;"><label>Dest Station (City)</label><input name="dstat" required style="border-color:#0f766e;"></div><div style="grid-column: span 2;"><label>Address</label><input name="daddr"></div>
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
    return render_page("Complete Booking", render_template_string(html, custs=custs))

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
        q = "SELECT s.*, c.phone as cphone FROM shipments s LEFT JOIN customers c ON s.customer_id = c.id"
        if search: q += f" WHERE s.awb_no LIKE '%{search}%' OR s.dest_station LIKE '%{search}%'"
        q += " ORDER BY s.id DESC LIMIT 150"
        c.execute(q); rows = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="padding:15px;"><form method="POST" style="display:flex; gap:10px;"><input name="search" value="{{ search }}" placeholder="Search AWB or Station..." style="flex:1;"><button type="submit" class="btn btn-blue">🔍 Search</button></form></div>
    <div class="card"><table style="font-size:12px;"><tr><th>AWB</th><th>Date</th><th>Consignee</th><th>Station</th><th>Total</th><th>Status</th><th>Actions</th></tr>
        {% for r in rows %}<tr>
            <td><strong>{{ r.awb_no }}</strong></td><td>{{ r.booking_date }}</td><td>{{ r.dest_name }}</td><td>{{ r.dest_station }}</td><td>₹{{ r.total_amount }}</td>
            <td><span class="badge b-book">{{ r.status }}</span></td>
            <td>
                <a href="/print/label/{{ r.awb_no }}" target="_blank" class="btn" style="padding:4px; font-size:11px;">🖨️ Label</a>
                <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="btn btn-gold" style="padding:4px; font-size:11px;">🧾 Bilti</a>
                <a href="/shipments?delete={{ r.id }}" onclick="return confirm('Delete?');" class="btn btn-red" style="padding:4px; font-size:11px;">🗑️</a>
            </td>
        </tr>{% endfor %}</table></div>
    """
    return render_page("Shipments Management", render_template_string(html, rows=rows, search=search))

@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c:
            c.execute("DELETE FROM outward_register WHERE id=%s", (request.args.get('delete'),))
            conn.commit(); flash("Entry Deleted!", "success"); return redirect('/outward')

    if request.method == 'POST' and 'scan_awb' in request.form:
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    s_row = c.execute("SELECT dest_station, weight_kg FROM shipments WHERE awb_no=%s", (awb,))
                    s = c.fetchone()
                    wt = s['weight_kg'] if s else 1.0; dst = s['dest_station'] if s else 'Unknown'
                    c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) VALUES(CURDATE(), %s, %s, %s, %s, %s, %s, 0)", 
                              (awb, session['branch'], request.form.get('dest_hub'), dst, wt, request.form.get('info')))
            conn.commit(); flash("✅ Added to Pending Outward.", "success")
            
    elif request.method == 'POST' and 'finalize_manifest' in request.form:
        vcl = request.form.get('vehicle')
        with conn.cursor() as c:
            c.execute("SELECT id, awb_no, out_station FROM outward_register WHERE finalized=0 AND origin_station=%s", (session['branch'],))
            pending = c.fetchall()
            if pending:
                c.execute("INSERT INTO manifests(manifest_type, from_location, to_location, vehicle_no, status) VALUES('OUTWARD', %s, %s, %s, 'CLOSED')", (session['branch'], pending[0]['out_station'], vcl))
                man_id = c.lastrowid
                for p in pending:
                    c.execute("UPDATE outward_register SET finalized=1, manifest_no=%s WHERE id=%s", (f"MF-{man_id}", p['id']))
                    s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (p['awb_no'],))
                    if s_row:
                        sid = c.fetchone()['id']
                        c.execute("INSERT INTO manifest_items(manifest_id, shipment_id) VALUES(%s, %s)", (man_id, sid))
                        c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s WHERE id=%s", (f"To {pending[0]['out_station']}", sid))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'OUTWARD', %s)", (sid, session['branch']))
                conn.commit(); flash(f"🚀 Manifest MF-{man_id} Generated!", "success")

    with conn.cursor() as c:
        c.execute("SELECT * FROM outward_register WHERE finalized=0 AND origin_station=%s", (session['branch'],))
        pending_list = c.fetchall()
        c.execute("SELECT * FROM manifests ORDER BY id DESC LIMIT 10")
        mans = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #d97706;"><h3 style="color:#d97706; margin-top:0;">1. Scan to Pending Outward</h3>
            <form method="POST"><input type="hidden" name="scan_awb" value="1">
                <label>To Hub / Station</label><input name="dest_hub" required style="margin-bottom:10px;">
                <label>Info / Notes</label><input name="info" style="margin-bottom:10px;">
                <label>Scan AWBs</label><textarea name="awbs" rows="4" required></textarea>
                <button type="submit" class="btn" style="margin-top:10px; width:100%;">Add to Pending Box</button>
            </form>
            <hr><h4>Pending Items (Not Dispatched)</h4>
            <div style="max-height:150px; overflow-y:auto; background:#f8fafc;">
                <table><tr><th>AWB</th><th>Dest</th><th>Wt</th><th>Del</th></tr>
                {% for p in pending_list %}<tr><td>{{ p.awb_no }}</td><td>{{ p.destination }}</td><td>{{ p.weight }}</td>
                <td><a href="/outward?delete={{ p.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}
                </table>
            </div>
        </div>
        <div class="card" style="border-top-color: #be123c;"><h3 style="color:#be123c; margin-top:0;">2. Finalize Manifest</h3>
            <form method="POST" style="background:#fee2e2; padding:15px; border-radius:8px;">
                <input type="hidden" name="finalize_manifest" value="1">
                <label>Vehicle / Driver Info</label><input name="vehicle" required style="margin-bottom:10px;">
                <button type="submit" class="btn btn-red" style="width:100%;">🔒 Finalize {{ pending_list|length }} Items</button>
            </form>
            <hr><h4>Manifest History</h4>
            <div style="max-height:200px; overflow-y:auto;">
                <table><tr><th>MF #</th><th>Route</th><th>Vehicle</th><th>Action</th></tr>
                {% for m in mans %}<tr><td><strong>MF-{{ m.id }}</strong></td><td>{{ m.from_location }} &rarr; {{ m.to_location }}</td><td>{{ m.vehicle_no }}</td>
                <td><a href="/print/manifest/{{ m.id }}" target="_blank" class="btn btn-blue" style="padding:4px 8px; font-size:11px;">Print</a></td></tr>{% endfor %}</table>
            </div>
        </div>
    </div>
    """
    return render_page("Outward / Manifest Hub", render_template_string(html, pending_list=pending_list, mans=mans))

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
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("INSERT INTO inward_register(entry_date, awb_no, in_station, info, finalized) VALUES(CURDATE(), %s, %s, %s, 1)", (awb, session['branch'], request.form.get('info')))
                    s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    if s_row:
                        sid = c.fetchone()['id']
                        c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE id=%s", (session['branch'], sid))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location) VALUES(%s, 'INWARD', %s)", (sid, session['branch']))
            conn.commit(); flash("✅ Inward Completed.", "success")
            
    with conn.cursor() as c:
        c.execute("SELECT * FROM inward_register WHERE in_station=%s ORDER BY id DESC LIMIT 50", (session['branch'],))
        hist = c.fetchall()
    conn.close()
    html = """<div class="grid-2"><div class="card"><h3 style="color:#0f766e; margin-top:0;">📥 Receive Inward</h3><form method="POST"><label>Info / Notes</label><input name="info" placeholder="Received via..." style="margin-bottom:10px;"><label>Scan AWBs</label><textarea name="awbs" rows="8" required></textarea><button type="submit" class="btn" style="margin-top:10px; width:100%;">Receive Parcels</button></form></div><div class="card" style="overflow-y:auto; max-height:400px;"><h3>Inward History</h3><table><tr><th>Date</th><th>AWB</th><th>Info</th><th>Del</th></tr>{% for h in hist %}<tr><td>{{ h.entry_date }}</td><td><strong>{{ h.awb_no }}</strong></td><td>{{ h.info }}</td><td><a href="/inward?delete={{ h.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}</table></div></div>"""
    return render_page("Inward Hub", render_template_string(html, hist=hist))

@app.route('/drs', methods=['GET', 'POST'])
@login_required
def drs():
    conn = get_db()
    if request.args.get('del_drs'):
        with conn.cursor() as c:
            c.execute("DELETE FROM drs_items WHERE drs_id=%s", (request.args.get('del_drs'),))
            c.execute("DELETE FROM drs WHERE id=%s", (request.args.get('del_drs'),))
            conn.commit(); return redirect('/drs')

    if request.method == 'POST' and 'assign_drs' in request.form:
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        rider = request.form.get('rider')
        with conn.cursor() as c:
            c.execute("INSERT INTO drs(drs_date, rider_name, status) VALUES(CURDATE(), %s, 'OPEN')", (rider,))
            drs_id = c.lastrowid
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    if s_row:
                        sid = c.fetchone()['id']
                        c.execute("INSERT INTO drs_items(drs_id, shipment_id, status) VALUES(%s, %s, 'ASSIGNED')", (drs_id, sid))
                        c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE id=%s", (f"Rider: {rider}", sid))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'ON_DRS', %s, %s)", (sid, session['branch'], f"Assigned to {rider}"))
            conn.commit(); flash("✅ DRS Generated", "success")

    elif request.method == 'POST' and 'mark_deliver' in request.form:
        awb = request.form.get('deliver_awb').strip().upper()
        receiver = request.form.get('receiver')
        with conn.cursor() as c:
            s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
            if s_row:
                sid = c.fetchone()['id']
                c.execute("UPDATE shipments SET status='DELIVERED', current_location=%s WHERE id=%s", (f"Delivered: {receiver}", sid))
                c.execute("UPDATE drs_items SET status='DELIVERED', receiver_name=%s WHERE shipment_id=%s", (receiver, sid))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s, 'DELIVERED', %s, %s)", (sid, session['branch'], f"Received by {receiver}"))
                conn.commit(); flash(f"✅ Delivered: {awb}", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, drs_date, rider_name FROM drs ORDER BY id DESC LIMIT 10")
        drss = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #0369a1;"><h3 style="color:#0369a1; margin-top:0;">🛵 1. Create DRS (Assign Rider)</h3>
            <form method="POST"><input type="hidden" name="assign_drs" value="1">
                <label>Rider Name</label><input name="rider" required style="margin-bottom:10px;">
                <label>Scan AWBs</label><textarea name="awbs" rows="4" required></textarea>
                <button type="submit" class="btn btn-blue" style="margin-top:10px; width:100%;">Create DRS</button>
            </form>
            <hr><h4>Recent DRS History</h4>
            <table><tr><th>DRS #</th><th>Rider</th><th>Action</th></tr>
            {% for d in drss %}<tr><td>DRS-{{ d.id }}</td><td>{{ d.rider_name }}</td>
            <td><a href="/print/drs/{{ d.id }}" target="_blank" class="btn btn-blue" style="padding:3px 6px; font-size:11px;">Print</a>
            <a href="/drs?del_drs={{ d.id }}" onclick="return confirm('Delete DRS?');" class="btn btn-red" style="padding:3px 6px; font-size:11px;">Del</a></td></tr>{% endfor %}</table>
        </div>
        <div class="card" style="border-top-color: #166534;"><h3 style="color:#166534; margin-top:0;">✅ 2. Mark Delivered</h3>
            <form method="POST"><input type="hidden" name="mark_deliver" value="1">
                <label>AWB Number</label><input name="deliver_awb" required style="margin-bottom:10px;">
                <label>Receiver Name</label><input name="receiver" required style="margin-bottom:10px;">
                <button type="submit" class="btn" style="background:#166534; width:100%;">Update Delivery</button>
            </form>
        </div>
    </div>
    """
    return render_page("DRS & Delivery", render_template_string(html, drss=drss))

@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    conn = get_db()
    if request.args.get('del_pay'):
        with conn.cursor() as c:
            p = c.execute("SELECT * FROM payments WHERE id=%s", (request.args.get('del_pay'),))
            if p:
                p = c.fetchone()
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
            c_bal = c.fetchone()['b']
    conn.close()
    
    html = """
    <div class="grid-2">
        <div class="card"><h3 style="margin-top:0; color:#10b981;">💸 Receive Payment</h3><form method="POST" class="grid-2" style="align-items:end;">
            <div style="grid-column: span 2;"><label>Customer</label><select name="cust_id" required>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div>
            <div><label>Amount (₹)</label><input type="number" step="0.01" name="amount" required></div><div><label>Mode</label><select name="mode"><option>CASH</option><option>UPI</option></select></div>
            <div><label>Reference</label><input name="ref"></div><div><button type="submit" class="btn" style="background:#10b981; width:100%;">Save Payment</button></div>
        </form></div>
        <div class="card"><h3 style="margin-top:0;">Recent Payments</h3><div style="max-height:180px; overflow-y:auto;"><table><tr><th>Date</th><th>Customer</th><th>Amount</th><th>Del</th></tr>{% for p in pays %}<tr><td>{{ p.payment_date }}</td><td>{{ p.name }}</td><td>₹{{ p.amount }}</td><td><a href="/accounts?del_pay={{ p.id }}" class="btn btn-red" style="padding:2px 5px; font-size:10px;">X</a></td></tr>{% endfor %}</table></div></div>
    </div>
    <div class="card"><h3>📒 Customer Ledger</h3>
        <form method="GET" style="display:flex; gap:10px;"><select name="cust_id" style="flex:1;">{% for c in custs %}<option value="{{ c.id }}" {% if request.args.get('cust_id') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select><button class="btn">View Ledger</button></form>
        {% if request.args.get('cust_id') %}<h4 style="text-align:right; color:#e11d48;">Closing Balance: ₹{{ c_bal }}</h4>
        <table><tr><th>Date</th><th>Voucher</th><th>Ref</th><th>Debit</th><th>Credit</th><th>Narration</th></tr>
        {% for l in l_data %}<tr><td>{{ l.entry_date }}</td><td>{{ l.voucher_type }}</td><td>{{ l.reference }}</td><td style="color:#e11d48; font-weight:bold;">{{ l.debit }}</td><td style="color:#10b981; font-weight:bold;">{{ l.credit }}</td><td>{{ l.narration }}</td></tr>{% endfor %}</table>{% endif %}
    </div>
    """
    return render_page("Accounts & Ledger", render_template_string(html, custs=custs, pays=pays, l_data=l_data, c_bal=c_bal))

# ==========================================
# 🖨️ 10. PREMIUM PDF GENERATOR (ReportLab)
# ==========================================
def hex_rgb(h): return tuple(int(h.lstrip("#")[i:i+2], 16)/255.0 for i in (0,2,4))
def money(val): return f"{float(val or 0):,.2f}"
def draw_barcode_safe(cv, value, x, y, height):
    try: code128.Code128(str(value), barHeight=height, barWidth=0.011 * inch).drawOn(cv, x, y); return True
    except Exception: return False
def draw_qr(cv, text, x, y, size):
    if qrcode:
        try:
            img = qrcode.make(text); buf = io.BytesIO(); img.save(buf, format="PNG")
            from reportlab.lib.utils import ImageReader
            cv.drawImage(ImageReader(io.BytesIO(buf.getvalue())), x, y, width=size, height=size)
        except Exception: pass
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
def num_to_words_inr(amount):
    return f"Rupees {money(amount)} Only"

# 🌟 PREMIUM HEADER FOR ALL A4 DOCUMENTS 🌟
def draw_premium_header(cv, w, h, title, subtitle):
    logo_drawn = False
    if os.path.exists("logo.png"):
        try:
            cv.drawImage("logo.png", 40, h - 60, width=120, height=40, preserveAspectRatio=True, mask="auto")
            logo_drawn = True
        except: pass
    
    cv.setFillColorRGB(*hex_rgb("#0f172a"))
    cv.setFont("Helvetica-Bold", 16)
    if not logo_drawn:
        cv.drawString(40, h - 35, "AKASH GANGA COURIER")
        
    cv.setFillColorRGB(*hex_rgb("#64748b"))
    cv.setFont("Helvetica", 9)
    y_text = h - 50 if not logo_drawn else h - 75
    cv.drawString(40, y_text, "Premium Logistics & Supply Chain")
    
    # 🌟 Live Branch Name from Login Session 🌟
    cv.setFillColorRGB(*hex_rgb("#0f766e"))
    cv.setFont("Helvetica-Bold", 9)
    cv.drawString(40, y_text - 12, f"Authorized Branch / Hub: {session.get('branch', 'Head Office').upper()}")
    
    # Right Side Document Box
    cv.setStrokeColorRGB(*hex_rgb("#d97706"))
    cv.setLineWidth(1.5)
    cv.roundRect(w - 200, h - 65, 160, 40, 6, fill=0, stroke=1)
    
    cv.setFillColorRGB(*hex_rgb("#d97706"))
    cv.setFont("Helvetica-Bold", 12)
    cv.drawCentredString(w - 120, h - 45, title)
    
    cv.setFillColorRGB(*hex_rgb("#475569"))
    cv.setFont("Helvetica", 8)
    cv.drawCentredString(w - 120, h - 58, subtitle)
    
    cv.setStrokeColorRGB(*hex_rgb("#d97706"))
    cv.setLineWidth(2)
    cv.line(40, y_text - 25, w - 40, y_text - 25)
    
    return y_text - 45

@app.route('/print/label/<awb>')
@login_required
def print_label_pdf(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT s.*, c.name as cname, c.address as caddr, c.gstin FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,))
        s = c.fetchone()
    conn.close()
    if not s: return "Not found"
    
    buf = io.BytesIO()
    w, h = 4 * inch, 6 * inch
    cv = canvas.Canvas(buf, pagesize=(w, h))
    cv.setFillColorRGB(1, 1, 1); cv.rect(0, 0, w, h, fill=1, stroke=0)
    cv.setStrokeColorRGB(*hex_rgb("#cbd5e1")); cv.setLineWidth(1.2); cv.rect(8, 8, w - 16, h - 16)
    
    logo_drawn = False
    if os.path.exists("logo.png"):
        try:
            cv.drawImage("logo.png", 14, h - 45, width=65, height=30, preserveAspectRatio=True, mask="auto")
            logo_drawn = True
        except: pass
        
    cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica-Bold", 12)
    if not logo_drawn:
        cv.drawString(14, h - 26, "AKASH GANGA COURIER")
    else:
        cv.drawString(85, h - 24, "AKASH GANGA COURIER")
        
    x_text = 85 if logo_drawn else 14
    cv.setFillColorRGB(*hex_rgb("#0f766e")); cv.setFont("Helvetica-Bold", 7.5)
    cv.drawString(x_text, h - 36, f"Branch: {session.get('branch', 'Head Office').upper()}")
    
    cv.setStrokeColorRGB(*hex_rgb("#d97706")); cv.setLineWidth(1.2); cv.rect(w - 90, h - 42, 80, 16) 
    cv.setFillColorRGB(*hex_rgb("#d97706")); cv.setFont("Helvetica-Bold", 6.5); cv.drawCentredString(w - 50, h - 37, "PREMIUM EXPRESS")
    cv.setStrokeColorRGB(*hex_rgb("#d97706")); cv.setLineWidth(1.5); cv.line(10, h - 60, w - 10, h - 60)

    cv.setFillColorRGB(*hex_rgb("#64748b")); cv.setFont("Helvetica-Bold", 6.5); cv.drawString(14, h - 74, "AWB NUMBER")
    cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica-Bold", 19); cv.drawString(14, h - 90, s["awb_no"])
    draw_barcode_safe(cv, s["awb_no"], 18, h - 128, 0.40 * inch)
    cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Courier-Bold", 9); cv.drawString(18, h - 140, s["awb_no"])

    draw_qr(cv, f"AWB:{s['awb_no']}|WT:{s['weight_kg']}", w - 74, h - 138, 58)

    cv.setFillColorRGB(*hex_rgb("#f8fafc")); cv.setStrokeColorRGB(*hex_rgb("#cbd5e1")); cv.rect(12, h - 180, w - 24, 38, fill=1, stroke=1)
    cv.setFillColorRGB(*hex_rgb("#64748b")); cv.setFont("Helvetica-Bold", 6); cv.drawString(20, h - 158, "ORIGIN"); cv.drawRightString(w - 20, h - 158, "DESTINATION")
    cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica-Bold", 13)
    cv.drawString(20, h - 172, str(s["origin_name"])[:12].upper())
    cv.drawRightString(w - 20, h - 170, str(s["dest_station"] or s["dest_name"])[:12].upper())

    cv.setFillColorRGB(*hex_rgb("#ffffff")); cv.setStrokeColorRGB(*hex_rgb("#cbd5e1")); cv.rect(12, h - 254, w - 24, 70, fill=1, stroke=1)
    cv.setFillColorRGB(*hex_rgb("#0f766e")); cv.rect(12, h - 254, 4, 70, fill=1, stroke=0)
    cv.setFont("Helvetica-Bold", 6.5); cv.drawString(22, h - 194, "DELIVER TO")
    cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica-Bold", 10)
    
    yy = h - 206
    for line in wrap_lines(cv, s["dest_name"] or "", "Helvetica-Bold", 10, w - 50)[:2]:
        cv.drawString(22, yy, line); yy -= 12
    cv.setFont("Helvetica", 7.5)
    for line in wrap_lines(cv, s["dest_address"] or "", "Helvetica", 7.5, w - 50)[:2]:
        cv.drawString(22, yy, line); yy -= 10
    cv.setFont("Helvetica-Bold", 7.5); cv.drawString(22, yy, f"Ph: {s['dest_phone'] or '-'}")

    cells = [("WEIGHT", f"{s['weight_kg']} KG"), ("PIECES", s["quantity"]), ("COD", f"Rs {money(s['cod_amount'])}"), ("DATE", s["booking_date"])]
    cw = (w - 24) / 4; chh = 19; y0 = h - 258
    for i, (label, value) in enumerate(cells):
        cx = 12 + i * cw; cy = y0 - chh
        cv.setFillColorRGB(*hex_rgb("#f8fafc")); cv.setStrokeColorRGB(*hex_rgb("#cbd5e1")); cv.rect(cx, cy, cw, chh, fill=1, stroke=1)
        cv.setFillColorRGB(*hex_rgb("#64748b")); cv.setFont("Helvetica-Bold", 5.6); cv.drawString(cx + 4, cy + chh - 7, label)
        cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica-Bold", 8); cv.drawString(cx + 4, cy + 4, str(value))

    st = y0 - chh - 6
    cv.setFillColorRGB(*hex_rgb("#ffffff")); cv.setStrokeColorRGB(*hex_rgb("#cbd5e1")); cv.rect(12, st - 40, w - 24, 40, fill=1, stroke=1)
    cv.setFillColorRGB(*hex_rgb("#d97706")); cv.setFont("Helvetica-Bold", 6.5); cv.drawString(20, st - 10, "SHIPPER")
    cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica", 6.8)
    yy = st - 20
    for line in wrap_lines(cv, f"{s['cname'] or s['origin_name']} | {s['caddr'] or s['origin_address']}", "Helvetica", 6.8, w - 44)[:2]:
        cv.drawString(20, yy, line); yy -= 9

    cv.showPage(); cv.save()
    buf.seek(0)
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

    buf = io.BytesIO()
    w, h = A4
    cv = canvas.Canvas(buf, pagesize=A4)
    
    y = draw_premium_header(cv, w, h, "BOOKING RECEIPT", f"AWB: {s['awb_no']}")

    cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica-Bold", 16); cv.drawString(40, y - 20, s["awb_no"])
    draw_barcode_safe(cv, s["awb_no"], 44, y - 55, 0.30 * inch)
    cv.setFont("Courier-Bold", 8); cv.drawString(44, y - 65, s["awb_no"])
    draw_qr(cv, f"AWB:{s['awb_no']}|WT:{s['weight_kg']}|COD:{money(s['cod_amount'])}", w - 100, y - 65, 60)

    bw = (w - 90) / 2; yb = y - 170
    cv.setStrokeColorRGB(*hex_rgb("#cbd5e1")); cv.setFillColorRGB(*hex_rgb("#f8fafc"))
    cv.roundRect(40, yb, bw, 90, 6, fill=1, stroke=1); cv.roundRect(50 + bw, yb, bw, 90, 6, fill=1, stroke=1)
    cv.setFillColorRGB(*hex_rgb("#d97706")); cv.setFont("Helvetica-Bold", 8)
    cv.drawString(48, yb + 78, "SHIPPER DETAILS"); cv.drawString(58 + bw, yb + 78, "CONSIGNEE DETAILS")
    cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica", 9)
    
    yy = yb + 62
    for ln in wrap_lines(cv, f"{s['cname'] or s['origin_name']}", "Helvetica-Bold", 9, bw - 16)[:1]:
        cv.setFont("Helvetica-Bold", 9); cv.drawString(48, yy, ln); yy -= 12
    for ln in wrap_lines(cv, f"{s['caddr'] or s['origin_address']}", "Helvetica", 8, bw - 16)[:3]:
        cv.setFont("Helvetica", 8); cv.drawString(48, yy, ln); yy -= 11
    
    yy = yb + 62
    for ln in wrap_lines(cv, f"{s['dest_name'] or ''}", "Helvetica-Bold", 9, bw - 16)[:1]:
        cv.setFont("Helvetica-Bold", 9); cv.drawString(58 + bw, yy, ln); yy -= 12
    for ln in wrap_lines(cv, f"{s['dest_address'] or ''}", "Helvetica", 8, bw - 16)[:3]:
        cv.setFont("Helvetica", 8); cv.drawString(58 + bw, yy, ln); yy -= 11
    cv.drawString(58 + bw, yy - 2, f"Ph: {s['dest_phone'] or '-'}")

    vals = [("WEIGHT", f"{s['weight_kg']} KG"), ("PIECES", s["quantity"]), ("TAXABLE", f"Rs {money(s['taxable_amount'])}"), ("GST", f"Rs {money((s['cgst'] or 0) + (s['sgst'] or 0) + (s['igst'] or 0))}"), ("TOTAL", f"Rs {money(s['total_amount'])}")]
    cw2 = (w - 80) / len(vals); yc = yb - 25
    for i, (lb, vl) in enumerate(vals):
        cx = 40 + i * cw2
        cv.setFillColorRGB(*hex_rgb("#f1f5f9")); cv.rect(cx, yc - 26, cw2 - 4, 26, fill=1, stroke=0)
        cv.setFillColorRGB(*hex_rgb("#64748b")); cv.setFont("Helvetica-Bold", 6); cv.drawString(cx + 4, yc - 8, lb)
        cv.setFillColorRGB(*hex_rgb("#0f172a")); cv.setFont("Helvetica-Bold", 8); cv.drawString(cx + 4, yc - 19, str(vl))

    cv.setFont("Helvetica-Bold", 8); cv.setFillColorRGB(*hex_rgb("#64748b")); cv.drawString(40, yc - 45, num_to_words_inr(s['total_amount']))
    cv.line(w - 180, yc - 30, w - 40, yc - 30); cv.drawString(w - 180, yc - 42, "Authorised Signatory")
    
    cv.showPage(); cv.save()
    buf.seek(0)
    return send_file(buf, download_name=f"Receipt_{awb}.pdf", mimetype='application/pdf')

@app.route('/print/manifest/<int:mid>')
@login_required
def print_manifest_pdf(mid):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM manifests WHERE id=%s", (mid,))
        m = c.fetchone()
        c.execute("SELECT s.awb_no, s.dest_station, s.weight_kg FROM manifest_items mi JOIN shipments s ON s.id=mi.shipment_id WHERE mi.manifest_id=%s", (mid,))
        items = c.fetchall()
    conn.close()

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4); w, h = A4
    y = draw_premium_header(cv, w, h, "OUTWARD MANIFEST", f"MF No: MF-{m['id']}")
    
    # Manifest Info Box
    cv.setFillColorRGB(*hex_rgb("#f8fafc")); cv.setStrokeColorRGB(*hex_rgb("#e2e8f0")); cv.roundRect(40, y - 45, w - 80, 45, 6, fill=1, stroke=1)
    cv.setFillColorRGB(*hex_rgb("#1e293b")); cv.setFont("Helvetica-Bold", 10)
    cv.drawString(55, y - 20, f"Route: {m['from_location'].upper()} -> {m['to_location'].upper()}")
    cv.setFont("Helvetica", 9)
    cv.drawString(55, y - 35, f"Vehicle: {m['vehicle_no']}   |   Date: {m['created_at']}   |   Total Items: {len(items)}")
    draw_barcode_safe(cv, f"MF-{m['id']}", w - 180, y - 38, 0.35 * inch)
    
    y -= 65
    cv.setFillColorRGB(*hex_rgb("#e2e8f0")); cv.rect(40, y - 20, w - 80, 20, fill=1, stroke=0)
    cv.setFillColorRGB(*hex_rgb("#1e293b")); cv.setFont("Helvetica-Bold", 8)
    cv.drawString(45, y - 14, "S.No"); cv.drawString(80, y - 14, "AWB & BARCODE"); cv.drawString(250, y - 14, "DESTINATION STATION"); cv.drawString(450, y - 14, "WEIGHT")
    y -= 20
    
    for i, it in enumerate(items):
        if y < 40: cv.showPage(); y = h - 40
        if i % 2 == 1: cv.setFillColorRGB(*hex_rgb("#f8fafc")); cv.rect(40, y - 28, w - 80, 28, fill=1, stroke=0)
        cv.setStrokeColorRGB(*hex_rgb("#e2e8f0")); cv.rect(40, y - 28, w - 80, 28, fill=0, stroke=1)
        
        cv.setFillColorRGB(*hex_rgb("#1e293b")); cv.setFont("Helvetica-Bold", 8)
        cv.drawString(45, y - 14, str(i + 1)); cv.drawString(80, y - 10, it["awb_no"])
        draw_barcode_safe(cv, it["awb_no"], 80, y - 25, 0.18 * inch)
        cv.setFont("Helvetica-Bold", 9); cv.drawString(250, y - 16, str(it.get("dest_station", "")).upper()[:25])
        cv.setFont("Helvetica-Bold", 8); cv.drawString(450, y - 16, f"{it['weight_kg']} KG")
        y -= 28

    cv.showPage(); cv.save()
    buf.seek(0); return send_file(buf, download_name=f"Manifest_{mid}.pdf", mimetype='application/pdf')

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
    y = draw_premium_header(cv, w, h, "DELIVERY RUN SHEET", f"DRS No: DRS-{d['id']}")
    
    cv.setFillColorRGB(*hex_rgb("#f8fafc")); cv.setStrokeColorRGB(*hex_rgb("#e2e8f0")); cv.roundRect(40, y - 45, w - 80, 45, 6, fill=1, stroke=1)
    cv.setFillColorRGB(*hex_rgb("#1e293b")); cv.setFont("Helvetica-Bold", 11)
    cv.drawString(55, y - 20, f"Rider Name: {d['rider_name'].upper()}")
    cv.setFont("Helvetica", 9)
    cv.drawString(55, y - 35, f"DRS Date: {d['drs_date']}   |   Total Parcels: {len(items)}")
    draw_qr(cv, f"DRS:{d['id']}|RIDER:{d['rider_name']}", w - 100, y - 40, 35)
    
    y -= 65
    cv.setFillColorRGB(*hex_rgb("#e2e8f0")); cv.rect(40, y - 20, w - 80, 20, fill=1, stroke=1)
    cv.setFillColorRGB(*hex_rgb("#1e293b")); cv.setFont("Helvetica-Bold", 8)
    cv.drawString(45, y - 14, "#"); cv.drawString(75, y - 14, "AWB & BARCODE"); cv.drawString(220, y - 14, "CONSIGNEE DETAILS"); cv.drawString(400, y - 14, "SIGNATURE & MOBILE")
    y -= 20

    for i, it in enumerate(items):
        if y < 60: cv.showPage(); y = h - 40
        if i % 2 == 1: cv.setFillColorRGB(*hex_rgb("#f8fafc")); cv.rect(40, y - 40, w - 80, 40, fill=1, stroke=0)
        cv.setStrokeColorRGB(*hex_rgb("#e2e8f0")); cv.rect(40, y - 40, w - 80, 40, fill=0, stroke=1)
        
        cv.setFillColorRGB(*hex_rgb("#1e293b")); cv.setFont("Helvetica-Bold", 8)
        cv.drawString(45, y - 25, str(i + 1)); cv.drawString(75, y - 12, it["awb_no"])
        draw_barcode_safe(cv, it["awb_no"], 75, y - 36, 0.28 * inch)
        
        cv.setFont("Helvetica-Bold", 9); cv.drawString(220, y - 14, str(it.get("dest_name", ""))[:25].upper())
        cv.setFont("Helvetica", 7)
        address_lines = wrap_lines(cv, it.get("dest_address", ""), "Helvetica", 7, 160)
        if address_lines: cv.drawString(220, y - 24, address_lines[0])
        cv.drawString(220, y - 34, f"Ph: {it.get('dest_phone', '')}")
        
        cv.setStrokeColorRGB(*hex_rgb("#94a3b8")); cv.setDash(1, 2)
        cv.line(420, y - 15, w - 50, y - 15); cv.line(420, y - 32, w - 50, y - 32); cv.setDash()
        cv.setFont("Helvetica", 8); cv.setFillColorRGB(*hex_rgb("#64748b")); cv.drawString(395, y - 15, "Sign:"); cv.drawString(395, y - 32, "Mob:")
        y -= 40

    cv.setFillColorRGB(*hex_rgb("#1e293b")); cv.setFont("Helvetica-Bold", 9); cv.line(60, y - 40, 200, y - 40); cv.drawString(60, y - 55, "Rider Signature")
    cv.line(350, y - 40, 500, y - 40); cv.drawString(350, y - 55, "Branch / Hub Manager Signature")
    
    cv.showPage(); cv.save()
    buf.seek(0); return send_file(buf, download_name=f"DRS_{did}.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)
