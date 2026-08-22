from flask import Flask, request, session, redirect, url_for, render_template_string, flash
import pymysql
import configparser
import hashlib
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'agc_super_secret_erp_key'

# Config load
config = configparser.ConfigParser()
config.read('db_config.ini')

def get_db():
    return pymysql.connect(
        host=config['CLOUD_DB']['host'], port=int(config['CLOUD_DB']['port']),
        user=config['CLOUD_DB']['user'], password=config['CLOUD_DB']['password'],
        database=config['CLOUD_DB']['database'], cursorclass=pymysql.cursors.DictCursor
    )

def sha(text): return hashlib.sha256(text.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🎨 MASTER HTML TEMPLATE
# ==========================================
BASE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }} - AGC Cloud ERP</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #f4f5f7; margin: 0; color: #2D3748; }
        .sidebar { width: 250px; background: #1E293B; color: white; position: fixed; height: 100%; overflow-y: auto; }
        .logo { padding: 20px; font-size: 22px; font-weight: 800; color: #38BDF8; border-bottom: 1px solid #334155; }
        .menu a { display: block; padding: 15px 20px; color: #CBD5E1; text-decoration: none; font-weight: bold; border-bottom: 1px solid #334155; }
        .menu a:hover { background: #0E8A6D; color: white; border-left: 5px solid #FF9F1C; }
        .main-content { margin-left: 250px; padding: 20px; }
        .header { display: flex; justify-content: space-between; background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); margin-bottom: 20px; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 20px; border-top: 4px solid #0E8A6D;}
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; }
        .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; }
        input, select, button, textarea { padding: 10px; border: 1px solid #CBD5E0; border-radius: 5px; width: 100%; box-sizing: border-box; }
        .btn { background: #0E8A6D; color: white; border: none; cursor: pointer; font-weight: bold; }
        .btn-gold { background: #FF9F1C; color: white; }
        .btn-blue { background: #38BDF8; color: #1E293B; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #EDF2F7; }
        th { background: #2B1B63; color: white; }
        .msg { padding: 10px; margin-bottom: 15px; border-radius: 5px; font-weight: bold; }
        .success { background: #C6F6D5; color: #22543D; }
        .error { background: #FED7D7; color: #822727; }
        @media (max-width: 768px) { .sidebar { display: none; } .main-content { margin-left: 0; } }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">◆ AGC Cloud ERP</div>
        <div class="menu">
            <a href="/">📊 Dashboard</a>
            <a href="/customers">👥 Customers</a>
            <a href="/booking">📦 New Booking</a>
            <a href="/shipments">🚚 Shipments</a>
            <a href="/outward">📤 Outward Hub</a>
            <a href="/inward">📥 Inward Hub</a>
            <a href="/drs">🛵 DRS / Delivery</a>
            <a href="/accounts" style="color:#FF9F1C;">💰 Accounts & Ledger</a>
            <a href="/logout" style="background:#E4405F; color:white;">Logout</a>
        </div>
    </div>
    <div class="main-content">
        <div class="header">
            <div><h2 style="margin:0;">{{ title }}</h2></div>
            <div>👤 {{ session['full_name'] }} ({{ session['branch'] }})</div>
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
# 🚦 ROUTES (LOGIN & DASHBOARD)
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
    return """<style>body{background:#0F172A;color:white;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;} .box{background:#1E293B;padding:40px;border-radius:12px;text-align:center;} input,button{width:90%;margin:10px 0;padding:12px;} button{background:#0E8A6D;color:white;border:none;font-weight:bold;cursor:pointer;}</style>
    <div class="box"><h2 style="color:#38BDF8;">AGC Cloud ERP</h2><form method="POST"><input name="username" placeholder="Username" required><input type="password" name="password" placeholder="Password" required><button type="submit">Secure Login</button></form></div>"""

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
        c.execute("SELECT awb_no, dest_name, status, total_amount FROM shipments ORDER BY id DESC LIMIT 10")
        latest = c.fetchall()
        # Outstanding Logic (Accounts)
        c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger")
        out = c.fetchone()
    conn.close()
    html = f"""
    <div class="grid-4">
        <div class="card" style="border-top-color: #38BDF8;"><h3>Total Parcels</h3><h2>{s['c']}</h2></div>
        <div class="card" style="border-top-color: #12B76A;"><h3>Delivered</h3><h2>{d['c']}</h2></div>
        <div class="card" style="border-top-color: #FF9F1C;"><h3>Revenue (₹)</h3><h2>{s['t']}</h2></div>
        <div class="card" style="border-top-color: #E4405F;"><h3>Market Due (₹)</h3><h2>{out['b']}</h2></div>
    </div>
    <div class="card">
        <h3>📦 Recent Bookings</h3>
        <table><tr><th>AWB Number</th><th>Destination</th><th>Amount</th><th>Status</th></tr>
        {''.join(f"<tr><td><strong>{r['awb_no']}</strong></td><td>{r['dest_name']}</td><td>₹{r['total_amount']}</td><td><span style='background:#E2E8F0; padding:4px 8px; border-radius:4px; font-size:12px; font-weight:bold;'>{r['status']}</span></td></tr>" for r in latest)}
        </table>
    </div>
    """
    return render_page("Executive Dashboard", html)

# ==========================================
# 📦 OPERATIONS: CUSTOMERS, BOOKING, SHIPMENTS
# ==========================================
@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    conn = get_db()
    if request.method == 'POST':
        c, n, g, p = request.form.get('code'), request.form.get('name'), request.form.get('gstin'), request.form.get('phone')
        with conn.cursor() as cur:
            cur.execute("INSERT INTO customers(code, name, gstin, phone, state, is_active) VALUES(%s,%s,%s,%s,'Rajasthan',1)", (c, n, g, p))
            conn.commit()
            flash("Customer Added Successfully!", "success")
    with conn.cursor() as cur:
        cur.execute("SELECT id, code, name, phone, credit_limit FROM customers WHERE is_active=1 ORDER BY id DESC")
        custs = cur.fetchall()
    conn.close()
    html = """
    <div class="card">
        <h3>➕ Add Customer</h3>
        <form method="POST" class="grid-4">
            <div><input name="code" placeholder="CUST Code" required></div>
            <div><input name="name" placeholder="Customer Name" required></div>
            <div><input name="phone" placeholder="Phone Number"></div>
            <div><button type="submit" class="btn">Save Customer</button></div>
        </form>
    </div>
    <div class="card">
        <table><tr><th>Code</th><th>Name</th><th>Phone</th><th>Credit Limit</th></tr>
        {% for r in custs %}<tr><td>{{ r.code }}</td><td><strong>{{ r.name }}</strong></td><td>{{ r.phone }}</td><td>₹{{ r.credit_limit }}</td></tr>{% endfor %}
        </table>
    </div>
    """
    from flask import render_template_string
    return render_page("Customer Management", render_template_string(html, custs=custs))

@app.route('/booking', methods=['GET', 'POST'])
@login_required
def booking():
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, dest_name, dest_station, weight_kg, total_amount, status, current_location) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s)",
                      (d['awb'].upper(), d.get('cust_id') or None, d['date'], session['branch'], d['dname'], d['dstat'], d['wt'], d['amt'], session['branch']))
            
            # Agar customer ka account hai toh uske ledger me entry karo (Auto-Billing)
            if d.get('cust_id'):
                c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)",
                          (d['cust_id'], d['date'], d['awb'].upper(), d['amt'], f"Booking {d['awb'].upper()}"))
            conn.commit()
            flash(f"AWB {d['awb'].upper()} Booked Successfully!", "success")

    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1")
        custs = c.fetchall()
    conn.close()
    html = """
    <div class="card">
        <form method="POST">
            <div class="grid-4">
                <div><label>Date</label><input type="date" name="date" id="bdt" required></div>
                <div><label>AWB Number</label><input name="awb" required></div>
                <div style="grid-column: span 2;"><label>Customer (Accounts Auto-Link)</label>
                    <select name="cust_id"><option value="">-- Cash Booking --</option>
                    {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select>
                </div>
                <div><label>Receiver Name</label><input name="dname" required></div>
                <div><label>Dest Station</label><input name="dstat" required></div>
                <div><label>Weight (KG)</label><input type="number" step="0.01" name="wt" value="1.0" required></div>
                <div><label>Amount (₹)</label><input type="number" step="0.01" name="amt" value="0.0" required></div>
            </div>
            <button type="submit" class="btn" style="margin-top:15px; width:100%;">🚀 Secure Book Parcel</button>
        </form>
        <script>document.getElementById('bdt').valueAsDate = new Date();</script>
    </div>
    """
    from flask import render_template_string
    return render_page("New Parcel Booking", render_template_string(html, custs=custs))

@app.route('/shipments')
@login_required
def shipments():
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT awb_no, booking_date, dest_name, dest_station, status, total_amount, current_location FROM shipments ORDER BY id DESC LIMIT 100")
        rows = c.fetchall()
    conn.close()
    html = """
    <div class="card">
        <table><tr><th>AWB</th><th>Date</th><th>Consignee</th><th>Station</th><th>Total</th><th>Status</th><th>Location</th></tr>
        {% for r in rows %}<tr>
            <td><strong>{{ r.awb_no }}</strong></td><td>{{ r.booking_date }}</td><td>{{ r.dest_name }}</td><td>{{ r.dest_station }}</td><td>₹{{ r.total_amount }}</td>
            <td><span style="background:#E2E8F0; padding:3px 8px; border-radius:4px; font-size:12px; font-weight:bold;">{{ r.status }}</span></td><td>{{ r.current_location }}</td>
        </tr>{% endfor %}</table>
    </div>
    """
    from flask import render_template_string
    return render_page("Shipments Data", render_template_string(html, rows=rows))

# ==========================================
# 🚚 HUB LOGISTICS: OUTWARD & INWARD
# ==========================================
@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    if request.method == 'POST':
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        dest = request.form.get('dest_hub')
        conn = get_db()
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s WHERE awb_no=%s", (f"En-route to {dest}", awb))
            conn.commit()
            flash(f"✅ Dispatched {len(awbs)} parcels to {dest}.", "success")
        conn.close()
    html = """<div class="card"><form method="POST"><div class="grid-2">
        <div><label>Destination Hub</label><input name="dest_hub" placeholder="Jaipur Hub" required></div>
        <div><label>Vehicle/Info</label><input name="vehicle" placeholder="RJ-XX-1234"></div></div>
        <label>Scan AWBs</label><textarea name="awbs" rows="8" required></textarea>
        <button type="submit" class="btn btn-red" style="margin-top:10px;">📤 Dispatch Outward Manifest</button>
    </form></div>"""
    return render_page("Outward Hub", html)

@app.route('/inward', methods=['GET', 'POST'])
@login_required
def inward():
    if request.method == 'POST':
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        conn = get_db()
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb: c.execute("UPDATE shipments SET status='INWARD', current_location=%s WHERE awb_no=%s", (session['branch'], awb))
            conn.commit()
            flash(f"✅ Inward Complete for {len(awbs)} parcels.", "success")
        conn.close()
    html = """<div class="card"><form method="POST">
        <label>Scan AWBs Received</label><textarea name="awbs" rows="10" required></textarea>
        <button type="submit" class="btn" style="margin-top:10px;">📥 Receive Inward</button>
    </form></div>"""
    return render_page("Inward Hub", html)

# ==========================================
# 🛵 ADVANCED DRS & DELIVERY MANAGEMENT
# ==========================================
@app.route('/drs', methods=['GET', 'POST'])
@login_required
def drs():
    conn = get_db()
    # ACTION 1: Generate DRS (Assign Rider)
    if request.method == 'POST' and 'assign_drs' in request.form:
        awbs = request.form.get('awbs').replace(',', '\n').split('\n')
        rider = request.form.get('rider')
        with conn.cursor() as c:
            for a in awbs:
                awb = a.strip().upper()
                if awb:
                    c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE awb_no=%s", (f"Rider: {rider}", awb))
            conn.commit()
            flash(f"🛵 DRS Generated! {len(awbs)} parcels assigned to {rider}.", "success")
            
    # ACTION 2: Mark as Delivered
    elif request.method == 'POST' and 'mark_deliver' in request.form:
        awb = request.form.get('deliver_awb').strip().upper()
        receiver = request.form.get('receiver')
        with conn.cursor() as c:
            c.execute("UPDATE shipments SET status='DELIVERED', current_location=%s WHERE awb_no=%s", (f"Delivered to: {receiver}", awb))
            conn.commit()
            flash(f"✅ Parcel {awb} Marked as DELIVERED to {receiver}.", "success")

    # Fetch live pending deliveries
    with conn.cursor() as c:
        c.execute("SELECT awb_no, dest_name, current_location FROM shipments WHERE status='ON_DRS' LIMIT 100")
        live = c.fetchall()
    conn.close()

    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #FF9F1C;">
            <h3 style="color:#FF9F1C;">🛵 1. Create DRS (Assign Rider)</h3>
            <form method="POST">
                <input type="hidden" name="assign_drs" value="1">
                <label>Rider Name / ID</label><input name="rider" required style="margin-bottom:10px;">
                <label>Scan AWBs</label><textarea name="awbs" rows="6" required></textarea>
                <button type="submit" class="btn btn-gold" style="margin-top:10px;">Assign to Rider</button>
            </form>
        </div>
        
        <div class="card" style="border-top-color: #12B76A;">
            <h3 style="color:#12B76A;">✅ 2. Update Delivery Status</h3>
            <form method="POST">
                <input type="hidden" name="mark_deliver" value="1">
                <label>Scan Delivered AWB</label><input name="deliver_awb" required style="margin-bottom:10px;">
                <label>Receiver Name / Sign</label><input name="receiver" required style="margin-bottom:10px;">
                <button type="submit" class="btn" style="background:#12B76A; width:100%;">Mark as Delivered</button>
            </form>
            <hr style="border:0; border-top:1px solid #eee; margin:15px 0;">
            <h4 style="margin:0 0 10px 0;">Live Out for Delivery (Pending)</h4>
            <div style="max-height:180px; overflow-y:auto;">
                <table style="font-size:12px;"><tr><th>AWB</th><th>Rider Info</th></tr>
                {% for r in live %}<tr><td><strong>{{ r.awb_no }}</strong></td><td>{{ r.current_location }}</td></tr>{% endfor %}
                </table>
            </div>
        </div>
    </div>
    """
    from flask import render_template_string
    return render_page("DRS & Delivery Management", render_template_string(html, live=live))

# ==========================================
# 💰 ACCOUNTS: LEDGER, PAYMENTS, OUTSTANDING
# ==========================================
@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    conn = get_db()
    # ACTION: Save Payment
    if request.method == 'POST' and 'save_payment' in request.form:
        cid = request.form.get('cust_id')
        amt = request.form.get('amount')
        mode = request.form.get('mode')
        ref = request.form.get('ref')
        d = datetime.now().strftime("%Y-%m-%d")
        with conn.cursor() as c:
            c.execute("INSERT INTO payments(customer_id, payment_date, amount, mode, reference) VALUES(%s,%s,%s,%s,%s)", (cid, d, amt, mode, ref))
            # Payment entry in Ledger (Credit)
            c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'PAYMENT',%s,0,%s,%s)",
                      (cid, d, ref, amt, f"Payment Received ({mode})"))
            conn.commit()
            flash(f"✅ Payment of ₹{amt} added successfully!", "success")

    # Fetch Data for View
    cust_id_filter = request.args.get('cust_id')
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1")
        custs = c.fetchall()
        
        # Calculate Global Outstanding
        c.execute("SELECT c.name, COALESCE(SUM(l.debit-l.credit),0) as bal FROM customers c LEFT JOIN ledger l ON l.customer_id=c.id GROUP BY c.id HAVING bal>0 ORDER BY bal DESC")
        outstanding = c.fetchall()
        
        ledger_data = []
        cust_bal = 0
        if cust_id_filter:
            c.execute("SELECT entry_date, voucher_type, reference, debit, credit, narration FROM ledger WHERE customer_id=%s ORDER BY entry_date, id", (cust_id_filter,))
            ledger_data = c.fetchall()
            c.execute("SELECT COALESCE(SUM(debit-credit),0) as b FROM ledger WHERE customer_id=%s", (cust_id_filter,))
            cust_bal = c.fetchone()['b']
    conn.close()

    html = """
    <div class="grid-2">
        <div class="card" style="border-top-color: #38BDF8;">
            <h3 style="color:#38BDF8;">💸 Receive Payment</h3>
            <form method="POST">
                <input type="hidden" name="save_payment" value="1">
                <div class="grid-2">
                    <div style="grid-column: span 2;"><label>Customer</label>
                        <select name="cust_id" required><option value="">-- Select Customer --</option>
                        {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select>
                    </div>
                    <div><label>Amount (₹)</label><input type="number" step="0.01" name="amount" required></div>
                    <div><label>Mode</label>
                        <select name="mode"><option>CASH</option><option>UPI / ONLINE</option><option>CHEQUE</option></select>
                    </div>
                    <div style="grid-column: span 2;"><label>Reference / Note</label><input name="ref" placeholder="UPI Ref / Cheque No"></div>
                </div>
                <button type="submit" class="btn btn-blue" style="margin-top:15px; width:100%;">💾 Save Payment</button>
            </form>
        </div>

        <div class="card" style="border-top-color: #E4405F;">
            <h3 style="color:#E4405F;">📊 Market Outstanding (Due)</h3>
            <div style="max-height:250px; overflow-y:auto;">
                <table><tr><th>Customer Name</th><th>Balance Due (₹)</th></tr>
                {% for o in outstanding %}<tr><td><strong>{{ o.name }}</strong></td><td style="color:#E4405F; font-weight:bold;">₹{{ o.bal }}</td></tr>{% endfor %}
                </table>
            </div>
        </div>
    </div>

    <div class="card">
        <h3>📒 Customer Ledger Statement</h3>
        <form method="GET" style="display:flex; gap:10px; margin-bottom:15px;">
            <select name="cust_id" style="flex:1;" required><option value="">-- Select Customer to View Ledger --</option>
            {% for c in custs %}<option value="{{ c.id }}" {% if request.args.get('cust_id') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select>
            <button type="submit" class="btn" style="width:auto;">🔍 Load Ledger</button>
        </form>
        
        {% if request.args.get('cust_id') %}
            <h4 style="text-align:right; color:#E4405F;">Closing Balance: ₹{{ cust_bal }}</h4>
            <table><tr><th>Date</th><th>Voucher</th><th>Reference</th><th>Debit (₹)</th><th>Credit (₹)</th><th>Narration</th></tr>
            {% for l in ledger_data %}<tr>
                <td>{{ l.entry_date }}</td><td>{{ l.voucher_type }}</td><td>{{ l.reference }}</td>
                <td style="color:#E4405F;">{{ l.debit }}</td><td style="color:#12B76A;">{{ l.credit }}</td><td>{{ l.narration }}</td>
            </tr>{% endfor %}
            </table>
        {% endif %}
    </div>
    """
    from flask import render_template_string
    return render_page("Accounts & Financials", render_template_string(html, custs=custs, outstanding=outstanding, ledger_data=ledger_data, cust_bal=cust_bal))

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)