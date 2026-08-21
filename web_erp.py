from flask import Flask, request, session, redirect, url_for, render_template_string, flash
import pymysql
import configparser
import hashlib
from functools import wraps

app = Flask(__name__)
# Session secure rakhne ke liye secret key (ise change mat karna)
app.secret_key = 'agc_super_secret_erp_key'

# Config file se Cloud Database ki details
config = configparser.ConfigParser()
config.read('db_config.ini')

def get_db():
    return pymysql.connect(
        host=config['CLOUD_DB']['host'], port=int(config['CLOUD_DB']['port']),
        user=config['CLOUD_DB']['user'], password=config['CLOUD_DB']['password'],
        database=config['CLOUD_DB']['database'], cursorclass=pymysql.cursors.DictCursor
    )

def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()

# 🛡️ PROTECTOR: Yeh check karega ki user logged in hai ya nahi
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🎨 HTML DESIGNS (UI)
# ==========================================
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>AGC Web ERP - Login</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body { font-family: 'Segoe UI', sans-serif; background: #0F172A; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
    .login-box { background: #1E293B; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); width: 100%; max-width: 350px; text-align: center; }
    h2 { color: #38BDF8; margin-bottom: 30px; }
    input { width: 90%; padding: 12px; margin: 10px 0; border: 1px solid #334155; border-radius: 6px; background: #0F172A; color: white; outline: none; }
    input:focus { border-color: #38BDF8; }
    button { width: 98%; padding: 12px; background: #0E8A6D; color: white; border: none; border-radius: 6px; font-weight: bold; font-size: 16px; cursor: pointer; margin-top: 20px; }
    button:hover { background: #12B76A; }
    .error { color: #E4405F; font-size: 14px; margin-bottom: 10px; }
</style>
</head>
<body>
    <div class="login-box">
        <h2>◆ AGC Web ERP</h2>
        {% with messages = get_flashed_messages() %}
          {% if messages %}<div class="error">{{ messages[0] }}</div>{% endif %}
        {% endwith %}
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required autocomplete="off">
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Secure Login</button>
        </form>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head><title>Dashboard - AGC Web ERP</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body { font-family: 'Segoe UI', sans-serif; background: #f4f5f7; margin: 0; }
    .navbar { background: #2B1B63; padding: 15px 30px; color: white; display: flex; justify-content: space-between; align-items: center; }
    .navbar a { color: #FF9F1C; text-decoration: none; font-weight: bold; background: rgba(255,255,255,0.1); padding: 8px 15px; border-radius: 6px; margin-right: 10px; }
    .navbar a:hover { background: rgba(255,255,255,0.2); }
    .container { padding: 30px; max-width: 1200px; margin: auto; }
    .stats { display: flex; gap: 20px; margin-bottom: 30px; flex-wrap: wrap; }
    .card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); flex: 1; min-width: 250px; border-left: 5px solid #0E8A6D; }
    .card h3 { margin: 0; color: #718096; font-size: 14px; }
    .card h2 { margin: 10px 0 0; color: #2D3748; font-size: 28px; }
    .table-responsive { overflow-x: auto; background: white; box-shadow: 0 2px 10px rgba(0,0,0,0.05); border-radius: 10px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 15px; text-align: left; border-bottom: 1px solid #EDF2F7; }
    th { background: #2B1B63; color: white; }
    
    @media (max-width: 768px) {
        .navbar { flex-direction: column; gap: 15px; text-align: center; }
    }
</style>
</head>
<body>
    <div class="navbar">
        <div style="font-size: 20px; font-weight: bold;">◆ AGC Smart ERP (Online)</div>
        <div>
            <a href="/">📊 Dashboard</a>
            <a href="/booking">📦 New Booking</a>
            <span style="margin: 0 15px; color: #CBD5E1;">|</span>
            <span style="margin-right: 20px;">👤 {{ session['full_name'] }} ({{ session['role'] }})</span>
            <a href="/logout" style="background: #E4405F; color: white;">Logout</a>
        </div>
    </div>
    
    <div class="container">
        <div class="stats">
            <div class="card"><h3>Total Shipments (Cloud)</h3><h2>{{ total_ship }}</h2></div>
            <div class="card" style="border-color: #FF9F1C;"><h3>Total Revenue</h3><h2>₹{{ total_rev }}</h2></div>
            <div class="card" style="border-color: #E4405F;"><h3>Pending Deliveries</h3><h2>{{ pending_del }}</h2></div>
        </div>

        <h3 style="color: #2D3748;">📦 Latest Bookings</h3>
        <div class="table-responsive">
            <table>
                <tr><th>AWB Number</th><th>Date</th><th>Destination</th><th>Status</th><th>Total (₹)</th></tr>
                {% for s in shipments %}
                <tr>
                    <td><strong>{{ s.awb_no }}</strong></td>
                    <td>{{ s.booking_date }}</td>
                    <td>{{ s.dest_name }}</td>
                    <td><span style="background: #E2E8F0; padding: 5px 10px; border-radius: 12px; font-size: 12px; font-weight:bold;">{{ s.status }}</span></td>
                    <td>{{ s.total_amount }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
</body>
</html>
"""

BOOKING_HTML = """
<!DOCTYPE html>
<html>
<head><title>New Booking - AGC Web</title><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body { font-family: 'Segoe UI', sans-serif; background: #f4f5f7; margin: 0; }
    .navbar { background: #2B1B63; padding: 15px 30px; color: white; display: flex; justify-content: space-between; align-items: center; }
    .navbar a { color: #FF9F1C; text-decoration: none; font-weight: bold; background: rgba(255,255,255,0.1); padding: 8px 15px; border-radius: 6px; margin-right: 10px; }
    .navbar a:hover { background: rgba(255,255,255,0.2); }
    .container { padding: 30px; max-width: 800px; margin: auto; }
    .card { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); border-top: 5px solid #FF9F1C; }
    h2 { color: #2B1B63; margin-top: 0; }
    .form-group { display: flex; flex-direction: column; margin-bottom: 15px; }
    label { font-weight: bold; color: #4A5568; margin-bottom: 5px; }
    input, select { padding: 10px; border: 1px solid #CBD5E0; border-radius: 6px; font-size: 15px; outline: none; }
    input:focus { border-color: #0E8A6D; }
    .btn-submit { background: #0E8A6D; color: white; padding: 12px 20px; border: none; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer; width: 100%; margin-top: 10px; }
    .btn-submit:hover { background: #12B76A; }
    .msg { padding: 15px; border-radius: 6px; font-weight: bold; margin-bottom: 20px; text-align: center; }
    .success { background: #C6F6D5; color: #22543D; }
    .error { background: #FED7D7; color: #822727; }
    .flex-row { display: flex; gap: 15px; }
    .flex-1 { flex: 1; }
    
    @media (max-width: 600px) {
        .flex-row { flex-direction: column; gap: 0; }
        .navbar { flex-direction: column; gap: 15px; text-align: center; }
    }
</style>
</head>
<body>
    <div class="navbar">
        <div style="font-size: 20px; font-weight: bold;">◆ AGC Smart ERP</div>
        <div>
            <a href="/">📊 Dashboard</a>
            <a href="/booking">📦 New Booking</a>
            <span style="margin: 0 15px; color: #CBD5E1;">|</span>
            <span style="margin-right: 20px;">👤 {{ session['full_name'] }}</span>
            <a href="/logout" style="background: #E4405F; color: white;">Logout</a>
        </div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>📦 Book New Parcel</h2>
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="msg {{ category }}">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            <form method="POST">
                <div class="flex-row">
                    <div class="form-group flex-1">
                        <label>AWB Number</label>
                        <input type="text" name="awb_no" placeholder="e.g. AWB12345" required autocomplete="off">
                    </div>
                    <div class="form-group flex-1">
                        <label>Booking Date</label>
                        <input type="date" name="booking_date" id="bdate" required>
                    </div>
                </div>
                
                <div class="form-group">
                    <label>Receiver (Dest) Name</label>
                    <input type="text" name="dest_name" placeholder="Consignee Name" required>
                </div>
                
                <div class="form-group">
                    <label>Destination City/Station</label>
                    <input type="text" name="dest_station" placeholder="e.g. Jaipur" required>
                </div>
                
                <div class="flex-row">
                    <div class="form-group flex-1">
                        <label>Weight (KG)</label>
                        <input type="number" step="0.01" name="weight" value="1.0" required>
                    </div>
                    <div class="form-group flex-1">
                        <label>Total Amount (₹)</label>
                        <input type="number" step="0.01" name="total_amount" value="0.0" required>
                    </div>
                </div>
                
                <button type="submit" class="btn-submit">🚀 Book Parcel Now</button>
            </form>
        </div>
    </div>
    
    <!-- Aaj ki date automatically set karne ke liye -->
    <script>document.getElementById('bdate').valueAsDate = new Date();</script>
</body>
</html>
"""

# ==========================================
# 🚦 ROUTES (Application Logic)
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username')
        pwd = request.form.get('password')
        
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username=%s AND active=1", (user,))
                r = cursor.fetchone()
                
                # Password Check (Hash ya Admin Bypass)
                ok = False
                if r and r['password_hash'] == sha(pwd):
                    ok = True
                elif user == "admin" and pwd == "admin123":
                    ok = True
                    r = {"id": 1, "username": "admin", "full_name": "Main Admin", "role": "ADMIN", "branch_name": "HQ"}

                if ok:
                    session['user_id'] = r['id']
                    session['username'] = r['username']
                    session['full_name'] = r['full_name']
                    session['role'] = r['role']
                    session['branch'] = r['branch_name']
                    return redirect(url_for('dashboard'))
                else:
                    flash('Invalid Username or Password!')
                    
        except Exception as e:
            flash(f"Database Error: {e}")
            
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    try:
        conn = get_db()
        with conn.cursor() as cursor:
            # 1. Dashboard Stats
            cursor.execute("SELECT COUNT(*) as c, SUM(total_amount) as t FROM shipments")
            stats = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) as c FROM shipments WHERE status != 'DELIVERED'")
            pending = cursor.fetchone()
            
            # 2. Latest Shipments Table
            cursor.execute("SELECT awb_no, booking_date, dest_name, status, total_amount FROM shipments ORDER BY id DESC LIMIT 15")
            latest = cursor.fetchall()
            
        conn.close()
        return render_template_string(
            DASHBOARD_HTML, 
            total_ship=stats['c'] or 0, 
            total_rev=round(stats['t'] or 0, 2),
            pending_del=pending['c'] or 0,
            shipments=latest
        )
    except Exception as e:
        return f"Error loading dashboard: {e}"

@app.route('/booking', methods=['GET', 'POST'])
@login_required
def booking():
    if request.method == 'POST':
        awb = request.form.get('awb_no').strip().upper() # Hamesha Capital me save karega
        b_date = request.form.get('booking_date')
        d_name = request.form.get('dest_name').strip()
        d_station = request.form.get('dest_station').strip()
        weight = request.form.get('weight')
        amount = request.form.get('total_amount')
        
        # User ki branch nikal lo (taaki pata chale parcel kahan se book hua)
        origin = session.get('branch', 'System')
        
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                # Pehle check karo AWB pehle se toh nahi hai
                cursor.execute("SELECT id FROM shipments WHERE awb_no = %s", (awb,))
                if cursor.fetchone():
                    flash(f"Error: AWB {awb} pehle se exist karta hai!", "error")
                else:
                    # Cloud DB mein Insert karo
                    sql = """INSERT INTO shipments 
                             (awb_no, booking_date, origin_name, dest_name, dest_station, weight_kg, total_amount, status, current_location, service_type) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s, 'BOOKED', 'Origin', 'SURFACE')"""
                    cursor.execute(sql, (awb, b_date, origin, d_name, d_station, weight, amount))
                    conn.commit()
                    flash(f"✅ Success! Parcel {awb} successfully Cloud par book ho gaya!", "success")
            conn.close()
        except Exception as e:
            flash(f"Database Error: {e}", "error")
            
    return render_template_string(BOOKING_HTML)

if __name__ == '__main__':
    # '0.0.0.0' allow karta hai ki aap apne phone browser mein bhi IP daal kar isey check kar sakein!
    app.run(host='0.0.0.0', debug=True, port=5000)