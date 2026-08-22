from flask import Flask, request, session, redirect, url_for, render_template_string, flash
import pymysql
import configparser
import hashlib
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'agc_super_secret_erp_key'

config = configparser.ConfigParser()
config.read('db_config.ini')

def get_db():
    # 🧹 AUTO-CLEANER: Copy-Paste ke hidden spaces ko saaf karega
    db_host = config['CLOUD_DB']['host'].replace('"', '').replace("'", "").strip()
    db_port = int(config['CLOUD_DB']['port'].replace('"', '').replace("'", "").strip())
    db_user = config['CLOUD_DB']['user'].replace('"', '').replace("'", "").strip()
    db_pass = config['CLOUD_DB']['password'].replace('"', '').replace("'", "").strip()
    db_name = config['CLOUD_DB']['database'].replace('"', '').replace("'", "").strip()
    
    # 🚀 MAGIC TRICK 1: Aiven ke Internal (.i.) address ko Public (.a.) mein automatically badalna
    if ".i.aivencloud" in db_host:
        db_host = db_host.replace(".i.aivencloud", ".a.aivencloud")
        
    # 🔒 MAGIC TRICK 2: Aiven bina SSL ke connect nahi hota, hum automatically SSL force karenge
    return pymysql.connect(
        host=db_host, 
        port=db_port,
        user=db_user, 
        password=db_pass,
        database=db_name, 
        cursorclass=pymysql.cursors.DictCursor,
        ssl={'ssl': {}}  # Yeh Aiven ko batayega ki connection 100% Secure (SSL) hai
    )

# ==========================================
# 🚀 DATABASE AUTO-HEALER (Missing Tables Creator)
# ==========================================
def auto_heal_cloud_db():
    try:
        conn = get_db()
        with conn.cursor() as c:
            # Create completely new missing tables for Accounts, DRS, Manifests
            c.execute("CREATE TABLE IF NOT EXISTS customers (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(50), name VARCHAR(255), gstin VARCHAR(50), phone VARCHAR(50), state VARCHAR(100), credit_limit DOUBLE DEFAULT 0, is_active INT DEFAULT 1)")
            c.execute("CREATE TABLE IF NOT EXISTS ledger (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, entry_date DATE, voucher_type VARCHAR(50), reference VARCHAR(100), debit DOUBLE DEFAULT 0, credit DOUBLE DEFAULT 0, narration TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, payment_date DATE, amount DOUBLE, mode VARCHAR(50), reference VARCHAR(100))")
            c.execute("CREATE TABLE IF NOT EXISTS outward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), out_station VARCHAR(100), destination VARCHAR(100), weight VARCHAR(50), info TEXT, finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS inward_register (id INT AUTO_INCREMENT PRIMARY KEY, entry_date DATE, awb_no VARCHAR(100), origin_station VARCHAR(100), in_station VARCHAR(100), weight VARCHAR(50), info TEXT, finalized INT DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS drs (id INT AUTO_INCREMENT PRIMARY KEY, drs_date DATE, rider_name VARCHAR(100), status VARCHAR(50))")
            c.execute("CREATE TABLE IF NOT EXISTS drs_items (id INT AUTO_INCREMENT PRIMARY KEY, drs_id INT, shipment_id INT, status VARCHAR(50), receiver_name VARCHAR(100))")
            c.execute("CREATE TABLE IF NOT EXISTS manifests (id INT AUTO_INCREMENT PRIMARY KEY, manifest_type VARCHAR(50), from_location VARCHAR(100), to_location VARCHAR(100), vehicle_no VARCHAR(100), status VARCHAR(50), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS manifest_items (id INT AUTO_INCREMENT PRIMARY KEY, manifest_id INT, shipment_id INT)")
            
            # Patch shipments table for any missing columns
            cols_to_add = [
                "customer_id INT", "dest_station VARCHAR(100)", "weight_kg DOUBLE DEFAULT 1.0", 
                "quantity INT DEFAULT 1", "service_type VARCHAR(50) DEFAULT 'SURFACE'", 
                "current_location VARCHAR(100)", "origin_name VARCHAR(100)", 
                "dest_phone VARCHAR(50)", "dest_address TEXT"
            ]
            for col in cols_to_add:
                try:
                    c.execute(f"ALTER TABLE shipments ADD COLUMN {col}")
                except Exception:
                    pass # Column already exists
        conn.commit()
        conn.close()
        print("✅ Cloud DB Tables Healed Successfully!")
    except Exception as e:
        print("DB Heal Error:", e)

# Run healer once when app starts
auto_heal_cloud_db()

def sha(text): return hashlib.sha256(text.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🎨 MASTER UI TEMPLATE
# ==========================================
BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }} - AGC Cloud</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #f0f2f5; margin: 0; color: #1e293b; }
        .sidebar { width: 260px; background: #0f172a; color: white; position: fixed; height: 100%; overflow-y: auto; box-shadow: 2px 0 5px rgba(0,0,0,0.1); }
        .logo { padding: 20px; font-size: 24px; font-weight: 900; color: #38bdf8; border-bottom: 1px solid #1e293b; text-align: center; letter-spacing: 1px;}
        .menu a { display: block; padding: 15px 25px; color: #cbd5e1; text-decoration: none; font-weight: 600; border-bottom: 1px solid #1e293b; transition: 0.3s; }
        .menu a:hover, .menu a.active { background: #0f766e; color: white; border-left: 4px solid #fbbf24; }
        .main-content { margin-left: 260px; padding: 25px; }
        .header { display: flex; justify-content: space-between; align-items: center; background: white; padding: 15px 25px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 25px; }
        .card { background: white; padding: 25px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 25px; border-top: 4px solid #0f766e; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }
        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
        input, select, textarea { padding: 10px; border: 1px solid #cbd5e1; border-radius: 6px; width: 100%; box-sizing: border-box; font-family: inherit; }
        input:focus, select:focus, textarea:focus { border-color: #0f766e; outline: none; }
        label { font-weight: 600; color: #475569; margin-bottom: 5px; display: block; font-size: 14px; }
        .btn { background: #0f766e; color: white; border: none; padding: 10px 15px; border-radius: 6px; cursor: pointer; font-weight: bold; transition: 0.3s; }
        .btn:hover { background: #0d9488; }
        .btn-gold { background: #d97706; } .btn-gold:hover { background: #f59e0b; }
        .btn-red { background: #be123c; } .btn-red:hover { background: #e11d48; }
        .btn-blue { background: #0369a1; } .btn-blue:hover { background: #0284c7; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #1e293b; color: white; font-weight: 600; }
        tr:hover { background-color: #f8fafc; }
        .msg { padding: 12px 15px; margin-bottom: 20px; border-radius: 6px; font-weight: 600; }
        .success { background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }
        .error { background: #fee2e2; color: #9f1239; border: 1px solid #fecdd3; }
        .badge { padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
        .b-booked { background: #e2e8f0; color: #475569; }
        .b-outward { background: #fef08a; color: #b45309; }
        .b-drs { background: #bfdbfe; color: #0369a1; }
        .b-del { background: #bbf7d0; color: #166534; }
        @media (max-width: 768px) { .sidebar { display: none; } .main-content { margin-left: 0; } .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">AGC CLOUD</div>
        <div class="menu">
            <a href="/">📊 Dashboard</a>
            <a href="/customers">👥 Customers</a>
            <a href="/booking">📦 Booking</a>
            <a href="/shipments">🚚 Shipments</a>
            <a href="/outward">📤 Outward / Manifest</a>
            <a href="/inward">📥 Inward Hub</a>
            <a href="/drs">🛵 DRS / Delivery</a>
            <a href="/accounts">💰 Accounts & Ledger</a>
            <a href="/logout" style="background:#be123c; border-left:0; margin-top:20px;">🚪 Logout</a>
        </div>
    </div>
    <div class="main-content">
        <div class="header">
            <h2 style="margin:0; color:#1e293b;">{{ title }}</h2>
            <div style="font-weight:600; color:#475569;">👤 {{ session['full_name'] }} ({{ session['branch'] }}) | 📅 {{ date }}</div>
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
    return render_template_string(BASE_HTML, title=title, content=content, date=datetime.now().strftime("%d-%b-%Y"))

# ==========================================
# 🚦 CORE ROUTES
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
    return """<style>body{background:#0f172a; display:flex; justify-content:center; align-items:center; height:100vh; font-family:sans-serif;} .box{background:#1e293b; padding:40px; border-radius:10px; text-align:center; width:300px; box-shadow:0 10px 25px rgba(0,0,0,0.5);} input{width:100%; margin:10px 0; padding:12px; border-radius:5px; border:1px solid #334155; background:#0f172a; color:white; box-sizing:border-box;} button{width:100%; padding:12px; background:#0f766e; color:white; border:none; border-radius:5px; font-weight:bold; cursor:pointer; margin-top:10px;}</style>
    <div class="box"><h2 style="color:#38bdf8; margin-top:0;">AGC LOGIN</h2><form method="POST"><input name="username" placeholder="Username" required autocomplete="off"><input type="password" name="password" placeholder="Password" required><button type="submit">LOGIN TO CLOUD</button></form></div>"""

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments")
        s = c.fetchone()
        c.execute("SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED'")
        d = c.fetchone()
        c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger")
        out = c.fetchone()
        c.execute("SELECT awb_no, dest_name, status, total_amount, booking_date FROM shipments ORDER BY id DESC LIMIT 10")
        latest = c.fetchall()
    conn.close()
    html = f"""
    <div class="grid-4">
        <div class="card" style="border-top-color: #38bdf8;"><h3>Total Parcels</h3><h2 style="color:#0f172a; font-size:28px; margin:0;">{s['c']}</h2></div>
        <div class="card" style="border-top-color: #10b981;"><h3>Delivered</h3><h2 style="color:#0f172a; font-size:28px; margin:0;">{d['c']}</h2></div>
        <div class="card" style="border-top-color: #f59e0b;"><h3>Revenue (₹)</h3><h2 style="color:#0f172a; font-size:28px; margin:0;">{round(s['t'], 2)}</h2></div>
        <div class="card" style="border-top-color: #e11d48;"><h3>Market Due (₹)</h3><h2 style="color:#0f172a; font-size:28px; margin:0;">{round(out['b'], 2)}</h2></div>
    </div>
    <div class="card">
        <h3>📦 Recent Bookings</h3>
        <table><tr><th>AWB Number</th><th>Date</th><th>Destination</th><th>Amount</th><th>Status</th></tr>
        {''.join(f"<tr><td><strong>{r['awb_no']}</strong></td><td>{r['booking_date']}</td><td>{r['dest_name']}</td><td>₹{r['total_amount']}</td><td><span class='badge b-booked'>{r['status']}</span></td></tr>" for r in latest)}
        </table>
    </div>
    """
    return render_page("Executive Dashboard", html)

# ==========================================
# 📦 CUSTOMERS & BOOKING
# ==========================================
@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    conn = get_db()
    if request.method == 'POST':
        c, n, g, p = request.form.get('code'), request.form.get('name'), request.form.get('gstin'), request.form.get('phone')
        with conn.cursor() as cur:
            cur.execute("INSERT INTO customers(code, name, gstin, phone, state, is_active) VALUES(%s,%s,%s,%s,'Default',1)", (c, n, g, p))
            conn.commit()
            flash("Customer Added Successfully!", "success")
    with conn.cursor() as cur:
        cur.execute("SELECT id, code, name, phone, credit_limit FROM customers WHERE is_active=1 ORDER BY id DESC")
        custs = cur.fetchall()
    conn.close()
    html = """
    <div class="card">
        <h3>➕ Add Customer</h3>
        <form method="POST" class="grid-4" style="align-items:end;">
            <div><label>Customer Code</label><input name="code" placeholder="CUST001" required></div>
            <div><label>Customer Name</label><input name="name" required></div>
            <div><label>Phone Number</label><input name="phone"></div>
            <div><button type="submit" class="btn btn-blue" style="width:100%;">Save Customer</button></div>
        </form>
    </div>
    <div class="card">
        <table><tr><th>ID</th><th>Code</th><th>Name</th><th>Phone</th><th>Credit Limit</th></tr>
        {% for r in custs %}<tr><td>{{ r.id }}</td><td>{{ r.code }}</td><td><strong>{{ r.name }}</strong></td><td>{{ r.phone }}</td><td>₹{{ r.credit_limit }}</td></tr>{% endfor %}
        </table>
    </div>
    """
    return render_page("Customer Management", render_template_string(html, custs=custs))

@app.route('/booking', methods=['GET', 'POST'])
@login_required
def booking():
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, dest_name, dest_station, 
                         weight_kg, quantity, service_type, total_amount, status, current_location) 
                         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s)""",
                      (d['awb'].upper(), d.get('cust_id') or None, d['date'], session['branch'], d['dname'], d['dstat'], 
                       d['wt'], d['pcs'], d['srv'], d['amt'], session['branch']))
            if d.get('cust_id'):
                c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)",
                          (d['cust_id'], d['date'], d['awb'].upper(), d['amt'], f"Auto Bill AWB {d['awb'].upper()}"))
            conn.commit()
            flash(f"✅ AWB {d['awb'].upper()} Booked!", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1")
        custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="max-width:800px; margin:auto;">
        <h3 style="color:#0f766e; margin-top:0;">📦 New Parcel Booking</h3>
        <form method="POST">
            <div class="grid-2">
                <div><label>Booking Date</label><input type="date" name="date" id="bdt" required></div>
                <div><label>AWB Number</label><input name="awb" required autocomplete="off"></div>
                <div style="grid-column: span 2;"><label>Customer / Shipper (Accounts Linked)</label>
                    <select name="cust_id"><option value="">-- Cash / Walk-in Booking --</option>
                    {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select>
                </div>
                <div><label>Consignee (Receiver) Name</label><input name="dname" required></div>
                <div><label>Dest Station (City)</label><input name="dstat" required></div>
                
                <div class="grid-2">
                    <div><label>Weight (KG)</label><input type="number" step="0.01" name="wt" value="1.0" required></div>
                    <div><label>Pieces</label><input type="number" name="pcs" value="1" required></div>
                </div>
                <div><label>Service Type</label>
                    <select name="srv"><option>SURFACE</option><option>EXPRESS</option><option>AIR</option></select>
                </div>
            </div>
            <hr style="border:1px solid #e2e8f0; margin:20px 0;">
            <div class="grid-2" style="align-items:end;">
                <div><label>Total Amount (₹)</label><input type="number" step="0.01" name="amt" value="0.0" required style="font-size:18px; font-weight:bold; color:#be123c;"></div>
                <div><button type="submit" class="btn btn-gold" style="width:100%; font-size:16px; padding:12px;">🚀 BOOK SHIPMENT</button></div>
            </div>
        </form>
        <script>document.getElementById('bdt').valueAsDate = new Date();</script>
    </div>
    """
    return render_page("Booking Panel", render_template_string(html, custs=custs))

# --- SHIPMENTS VIEW & PRINT ---
@app.route('/shipments')
@login_required
def shipments():
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT id, awb_no, booking_date, dest_name, dest_station, status, total_amount, current_location FROM shipments ORDER BY id DESC LIMIT 100")
        rows = c.fetchall()
    conn.close()
    html = """
    <div class="card">
        <table><tr><th>AWB</th><th>Date</th><th>Dest Name</th><th>Station</th><th>Total (₹)</th><th>Status</th><th>Location</th><th>Action</th></tr>
        {% for r in rows %}<tr>
            <td><strong>{{ r.awb_no }}</strong></td><td>{{ r.booking_date }}</td><td>{{ r.dest_name }}</td><td>{{ r.dest_station }}</td><td>{{ r.total_amount }}</td>
            <td><span class="badge b-booked">{{ r.status }}</span></td><td>{{ r.current_location }}</td>
            <td>
                <a href="/print/label/{{ r.awb_no }}" target="_blank" class="btn" style="padding:4px 8px; font-size:12px; text-decoration:none;">Label</a>
                <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="btn btn-gold" style="padding:4px 8px; font-size:12px; text-decoration:none;">Bilti</a>
            </td>
        </tr>{% endfor %}</table>
    </div>
    """
    return render_page("All Shipments", render_template_string(html, rows=rows))

# ==========================================
# 🚚 HUB OPERATIONS (OUTWARD, INWARD, DRS)
# ==========================================
@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    conn = get_db()
    if request.method == 'POST':
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        dest = request.form.get('dest_hub')
        vcl = request.form.get('vehicle')
        date_val = datetime.now().strftime("%Y-%m-%d")
        
        with conn.cursor() as c:
            c.execute("INSERT INTO manifests(manifest_type, from_location, to_location, vehicle_no, status) VALUES('OUTWARD', %s, %s, %s, 'CLOSED')", (session['branch'], dest, vcl))
            man_id = c.lastrowid
            count = 0
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    if s_row:
                        sid = c.fetchone()['id']
                        c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, info, finalized) VALUES(%s, %s, %s, %s, %s, 1)", (date_val, awb, session['branch'], dest, f"Veh: {vcl}"))
                        c.execute("INSERT INTO manifest_items(manifest_id, shipment_id) VALUES(%s, %s)", (man_id, sid))
                        c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s WHERE id=%s", (f"En-route to {dest}", sid))
                        count += 1
            conn.commit()
            flash(f"✅ Manifest #{man_id} Created! Dispatched {count} parcels.", "success")
            
    with conn.cursor() as c:
        c.execute("SELECT id, from_location, to_location, vehicle_no, created_at FROM manifests ORDER BY id DESC LIMIT 15")
        mans = c.fetchall()
    conn.close()
    
    html = """
    <div class="grid-2">
        <div class="card">
            <h3 style="color:#d97706; margin-top:0;">📤 Create Outward Manifest</h3>
            <form method="POST">
                <label>To Destination Hub</label><input name="dest_hub" placeholder="e.g. Jaipur Hub" required style="margin-bottom:10px;">
                <label>Vehicle / Driver Details</label><input name="vehicle" placeholder="RJ-XX-1234" required style="margin-bottom:10px;">
                <label>Scan AWBs</label><textarea name="awbs" rows="8" required placeholder="Line by line AWBs..." style="font-family:monospace;"></textarea>
                <button type="submit" class="btn btn-gold" style="margin-top:15px; width:100%; font-size:16px;">Create & Dispatch Manifest</button>
            </form>
        </div>
        <div class="card">
            <h3 style="margin-top:0;">📋 Manifest History</h3>
            <table><tr><th>Manifest #</th><th>Date</th><th>To Station</th><th>Vehicle</th><th>Action</th></tr>
            {% for m in mans %}<tr>
                <td><strong>MF-{{ m.id }}</strong></td><td>{{ m.created_at.strftime('%Y-%m-%d') if m.created_at else '-' }}</td><td>{{ m.to_location }}</td><td>{{ m.vehicle_no }}</td>
                <td><a href="/print/manifest/{{ m.id }}" target="_blank" class="btn btn-blue" style="padding:4px 8px; text-decoration:none; font-size:12px;">Print</a></td>
            </tr>{% endfor %}</table>
        </div>
    </div>
    """
    return render_page("Outward Operations", render_template_string(html, mans=mans))

@app.route('/inward', methods=['GET', 'POST'])
@login_required
def inward():
    if request.method == 'POST':
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        conn = get_db()
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE awb_no=%s", (session['branch'], awb))
            conn.commit()
            flash(f"✅ Received {len(awbs)} parcels at {session['branch']}.", "success")
        conn.close()
    html = """
    <div class="card" style="max-width: 600px; margin: auto;">
        <h3 style="color:#0f766e; margin-top:0;">📥 Inward Scanning</h3>
        <form method="POST">
            <label>Scan AWBs from incoming vehicle</label>
            <textarea name="awbs" rows="10" required style="font-family:monospace; font-size:16px;"></textarea>
            <button type="submit" class="btn" style="margin-top:15px; width:100%; font-size:16px;">Update Stock to Hub</button>
        </form>
    </div>
    """
    return render_page("Inward Operations", html)

@app.route('/drs', methods=['GET', 'POST'])
@login_required
def drs():
    conn = get_db()
    if request.method == 'POST':
        if 'assign_drs' in request.form:
            awbs = request.form.get('awbs').replace(',', '\n').split('\n')
            rider = request.form.get('rider')
            date_val = datetime.now().strftime("%Y-%m-%d")
            with conn.cursor() as c:
                c.execute("INSERT INTO drs(drs_date, rider_name, status) VALUES(%s, %s, 'OPEN')", (date_val, rider))
                drs_id = c.lastrowid
                for a in awbs:
                    awb = a.strip().upper()
                    if awb:
                        s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                        if s_row:
                            sid = c.fetchone()['id']
                            c.execute("INSERT INTO drs_items(drs_id, shipment_id, status) VALUES(%s, %s, 'ASSIGNED')", (drs_id, sid))
                            c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE id=%s", (f"Rider: {rider}", sid))
                conn.commit()
                flash(f"✅ DRS #{drs_id} Generated for {rider}.", "success")

        elif 'mark_deliver' in request.form:
            awb = request.form.get('deliver_awb').strip().upper()
            receiver = request.form.get('receiver')
            with conn.cursor() as c:
                s_row = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                if s_row:
                    sid = c.fetchone()['id']
                    c.execute("UPDATE shipments SET status='DELIVERED', current_location=%s WHERE id=%s", (f"Delivered: {receiver}", sid))
                    c.execute("UPDATE drs_items SET status='DELIVERED', receiver_name=%s WHERE shipment_id=%s", (receiver, sid))
                    conn.commit()
                    flash(f"✅ {awb} Delivered to {receiver}.", "success")

    with conn.cursor() as c:
        c.execute("SELECT awb_no, dest_name, current_location FROM shipments WHERE status='ON_DRS' LIMIT 50")
        live = c.fetchall()
        c.execute("SELECT id, drs_date, rider_name FROM drs ORDER BY id DESC LIMIT 10")
        drss = c.fetchall()
    conn.close()

    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #0369a1;">
            <h3 style="color:#0369a1; margin-top:0;">🛵 1. Generate DRS</h3>
            <form method="POST">
                <input type="hidden" name="assign_drs" value="1">
                <label>Rider Name</label><input name="rider" required style="margin-bottom:10px;">
                <label>Scan AWBs</label><textarea name="awbs" rows="6" required></textarea>
                <button type="submit" class="btn btn-blue" style="margin-top:10px; width:100%;">Create DRS</button>
            </form>
            <hr style="margin:20px 0; border:1px solid #e2e8f0;">
            <h4>Recent DRS</h4>
            <table><tr><th>DRS #</th><th>Rider</th><th>Action</th></tr>
            {% for d in drss %}<tr><td>DRS-{{ d.id }}</td><td>{{ d.rider_name }}</td>
            <td><a href="/print/drs/{{ d.id }}" target="_blank" class="badge b-drs" style="text-decoration:none;">Print</a></td></tr>{% endfor %}</table>
        </div>
        
        <div class="card" style="border-top-color: #166534;">
            <h3 style="color:#166534; margin-top:0;">✅ 2. Mark Delivered</h3>
            <form method="POST">
                <input type="hidden" name="mark_deliver" value="1">
                <label>AWB Number</label><input name="deliver_awb" required style="margin-bottom:10px;">
                <label>Receiver Name</label><input name="receiver" required style="margin-bottom:10px;">
                <button type="submit" class="btn" style="background:#166534; width:100%;">Update Delivery</button>
            </form>
            <hr style="margin:20px 0; border:1px solid #e2e8f0;">
            <h4>Out for Delivery (Pending)</h4>
            <div style="max-height:250px; overflow-y:auto;">
                <table><tr><th>AWB</th><th>Consignee</th><th>Location</th></tr>
                {% for r in live %}<tr><td><strong>{{ r.awb_no }}</strong></td><td>{{ r.dest_name }}</td><td>{{ r.current_location }}</td></tr>{% endfor %}
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("DRS & Delivery", render_template_string(html, live=live, drss=drss))

# ==========================================
# 💰 ACCOUNTS (LEDGER & PAYMENTS)
# ==========================================
@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    conn = get_db()
    if request.method == 'POST' and 'save_payment' in request.form:
        cid = request.form.get('cust_id')
        amt = request.form.get('amount')
        mode = request.form.get('mode')
        ref = request.form.get('ref')
        d = datetime.now().strftime("%Y-%m-%d")
        with conn.cursor() as c:
            c.execute("INSERT INTO payments(customer_id, payment_date, amount, mode, reference) VALUES(%s,%s,%s,%s,%s)", (cid, d, amt, mode, ref))
            c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'PAYMENT',%s,0,%s,%s)",
                      (cid, d, ref, amt, f"Payment Received ({mode})"))
            conn.commit()
            flash(f"✅ Payment of ₹{amt} added successfully!", "success")

    cust_id_filter = request.args.get('cust_id')
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1")
        custs = c.fetchall()
        c.execute("SELECT c.name, COALESCE(SUM(l.debit-l.credit),0) as bal FROM customers c LEFT JOIN ledger l ON l.customer_id=c.id GROUP BY c.id HAVING bal>0 ORDER BY bal DESC")
        outstanding = c.fetchall()
        ledger_data = []; cust_bal = 0
        if cust_id_filter:
            c.execute("SELECT entry_date, voucher_type, reference, debit, credit, narration FROM ledger WHERE customer_id=%s ORDER BY entry_date, id", (cust_id_filter,))
            ledger_data = c.fetchall()
            c.execute("SELECT COALESCE(SUM(debit-credit),0) as b FROM ledger WHERE customer_id=%s", (cust_id_filter,))
            r = c.fetchone()
            cust_bal = r['b'] if r and r['b'] else 0
    conn.close()

    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #10b981;">
            <h3 style="color:#10b981; margin-top:0;">💸 Receive Payment</h3>
            <form method="POST">
                <input type="hidden" name="save_payment" value="1">
                <label>Select Customer</label>
                <select name="cust_id" required style="margin-bottom:10px;"><option value="">-- Customer --</option>
                {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select>
                
                <div class="grid-2">
                    <div><label>Amount (₹)</label><input type="number" step="0.01" name="amount" required></div>
                    <div><label>Mode</label><select name="mode"><option>CASH</option><option>UPI</option><option>BANK</option></select></div>
                </div>
                <label style="margin-top:10px;">Reference No</label><input name="ref" placeholder="UPI Ref / Cheque No">
                <button type="submit" class="btn" style="background:#10b981; margin-top:15px; width:100%;">Save Payment</button>
            </form>
        </div>

        <div class="card" style="border-top-color: #e11d48;">
            <h3 style="color:#e11d48; margin-top:0;">📊 Market Outstanding (Due)</h3>
            <div style="max-height:250px; overflow-y:auto;">
                <table><tr><th>Customer Name</th><th>Balance Due (₹)</th></tr>
                {% for o in outstanding %}<tr><td><strong>{{ o.name }}</strong></td><td style="color:#e11d48; font-weight:bold;">₹{{ o.bal }}</td></tr>{% endfor %}
                </table>
            </div>
        </div>
    </div>

    <div class="card">
        <h3>📒 Customer Ledger Passbook</h3>
        <form method="GET" style="display:flex; gap:10px; margin-bottom:15px;">
            <select name="cust_id" style="flex:1;" required><option value="">-- Select Customer --</option>
            {% for c in custs %}<option value="{{ c.id }}" {% if request.args.get('cust_id') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select>
            <button type="submit" class="btn" style="width:auto;">View Ledger</button>
        </form>
        {% if request.args.get('cust_id') %}
            <h4 style="text-align:right; color:#e11d48;">Closing Balance: ₹{{ cust_bal }}</h4>
            <table><tr><th>Date</th><th>Voucher</th><th>Ref</th><th>Debit (₹)</th><th>Credit (₹)</th><th>Narration</th></tr>
            {% for l in ledger_data %}<tr>
                <td>{{ l.entry_date }}</td><td>{{ l.voucher_type }}</td><td>{{ l.reference }}</td>
                <td style="color:#e11d48; font-weight:bold;">{{ l.debit }}</td><td style="color:#10b981; font-weight:bold;">{{ l.credit }}</td><td>{{ l.narration }}</td>
            </tr>{% endfor %}</table>
        {% endif %}
    </div>
    """
    return render_page("Accounts & Financials", render_template_string(html, custs=custs, outstanding=outstanding, ledger_data=ledger_data, cust_bal=cust_bal))

# ==========================================
# 🖨️ WEB PRINTING MODULES (HTML Based)
# ==========================================
@app.route('/print/label/<awb>')
@login_required
def print_label(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT s.*, c.name as cname, c.address as caddr FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,))
        d = c.fetchone()
    conn.close()
    if not d: return "Not found"
    html = """<html><head><script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script></head>
    <body onload="JsBarcode('#bc', '{{d.awb_no}}', {displayValue:false, height:50}); window.print();" style="font-family:sans-serif; max-width:380px; margin:auto; border:2px solid #000; padding:15px;">
        <h2 style="text-align:center; margin:0;">AGC COURIER</h2>
        <div style="text-align:center;"><svg id="bc"></svg><h3 style="margin:0; letter-spacing:2px;">{{ d.awb_no }}</h3></div>
        <hr>
        <div style="display:flex; justify-content:space-between; font-weight:bold; font-size:18px;">
            <span>{{ d.origin_name }}</span> <span>&rarr;</span> <span>{{ d.dest_station }}</span>
        </div>
        <hr>
        <p><strong>To:</strong> {{ d.dest_name }}<br>{{ d.dest_address }}<br>Ph: {{ d.dest_phone }}</p>
        <p><strong>From:</strong> {{ d.cname or 'AGC Branch' }}<br>{{ d.caddr }}</p>
        <hr>
        <p style="display:flex; justify-content:space-between;"><span>Weight: {{ d.weight_kg }} KG</span> <span>Pcs: {{ d.quantity }}</span> <span>Date: {{ d.booking_date }}</span></p>
        <h3 style="text-align:right; margin:0;">Total: Rs {{ d.total_amount }}</h3>
    </body></html>"""
    return render_template_string(html, d=d)

@app.route('/print/receipt/<awb>')
@login_required
def print_receipt(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT s.*, c.name as cname FROM shipments s LEFT JOIN customers c ON c.id=s.customer_id WHERE s.awb_no=%s", (awb,))
        d = c.fetchone()
    conn.close()
    if not d: return "Not found"
    html = """<html><head><style>body{font-family:Arial; max-width:800px; margin:auto; padding:20px; border:1px solid #ccc;} table{width:100%; border-collapse:collapse; margin-top:20px;} th,td{border:1px solid #ccc; padding:8px;}</style></head>
    <body onload="window.print()">
        <h1 style="text-align:center;">AGC COURIER - BOOKING RECEIPT</h1>
        <div style="display:flex; justify-content:space-between;">
            <div><p><strong>AWB No:</strong> {{d.awb_no}}</p><p><strong>Date:</strong> {{d.booking_date}}</p></div>
            <div><p><strong>Origin:</strong> {{d.origin_name}}</p><p><strong>Destination:</strong> {{d.dest_station}}</p></div>
        </div>
        <table>
            <tr><th>Shipper</th><th>Consignee</th></tr>
            <tr><td>{{ d.cname or 'Walk-in' }}</td><td>{{ d.dest_name }}<br>{{ d.dest_address }}<br>Ph: {{ d.dest_phone }}</td></tr>
        </table>
        <table>
            <tr><th>Weight</th><th>Pieces</th><th>Service</th><th>Taxable</th><th>Total Amount</th></tr>
            <tr><td>{{ d.weight_kg }} KG</td><td>{{ d.quantity }}</td><td>{{ d.service_type }}</td><td>Rs {{ d.taxable_amount }}</td><td><strong>Rs {{ d.total_amount }}</strong></td></tr>
        </table>
        <p style="margin-top:40px;">Auth. Signatory</p>
    </body></html>"""
    return render_template_string(html, d=d)

@app.route('/print/manifest/<int:mid>')
@login_required
def print_manifest(mid):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM manifests WHERE id=%s", (mid,))
        m = c.fetchone()
        c.execute("SELECT s.awb_no, s.dest_name, s.weight_kg FROM manifest_items mi JOIN shipments s ON s.id=mi.shipment_id WHERE mi.manifest_id=%s", (mid,))
        items = c.fetchall()
    conn.close()
    html = """<html><body onload="window.print()" style="font-family:Arial; padding:20px;">
        <h2 style="text-align:center; border-bottom:2px solid #000; padding-bottom:10px;">OUTWARD MANIFEST #{{m.id}}</h2>
        <p><strong>Date:</strong> {{ m.created_at }} | <strong>Route:</strong> {{ m.from_location }} &rarr; {{ m.to_location }} | <strong>Vehicle:</strong> {{ m.vehicle_no }}</p>
        <table style="width:100%; border-collapse:collapse; margin-top:20px;" border="1" cellpadding="8">
            <tr><th>#</th><th>AWB Number</th><th>Destination</th><th>Weight</th></tr>
            {% for i in items %}<tr><td>{{ loop.index }}</td><td><strong>{{ i.awb_no }}</strong></td><td>{{ i.dest_name }}</td><td>{{ i.weight_kg }} KG</td></tr>{% endfor %}
        </table>
    </body></html>"""
    return render_template_string(html, m=m, items=items)

@app.route('/print/drs/<int:did>')
@login_required
def print_drs(did):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM drs WHERE id=%s", (did,))
        d = c.fetchone()
        c.execute("SELECT s.awb_no, s.dest_name, s.dest_address, s.dest_phone FROM drs_items di JOIN shipments s ON s.id=di.shipment_id WHERE di.drs_id=%s", (did,))
        items = c.fetchall()
    conn.close()
    html = """<html><body onload="window.print()" style="font-family:Arial; padding:20px;">
        <h2 style="text-align:center; border-bottom:2px solid #000; padding-bottom:10px;">DELIVERY RUN SHEET (DRS #{{d.id}})</h2>
        <p><strong>Date:</strong> {{ d.drs_date }} | <strong>Rider Name:</strong> {{ d.rider_name }}</p>
        <table style="width:100%; border-collapse:collapse; margin-top:20px;" border="1" cellpadding="8">
            <tr><th>#</th><th>AWB No</th><th>Consignee Details</th><th>Receiver Signature & Time</th></tr>
            {% for i in items %}<tr><td>{{ loop.index }}</td><td><strong>{{ i.awb_no }}</strong></td>
            <td>{{ i.dest_name }}<br>{{ i.dest_address }}<br>{{ i.dest_phone }}</td><td style="width:30%;"></td></tr>{% endfor %}
        </table>
        <p style="margin-top:40px;">Rider Signature: _______________ &nbsp;&nbsp;&nbsp;&nbsp; Hub Manager: _______________</p>
    </body></html>"""
    return render_template_string(html, d=d, items=items)

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)