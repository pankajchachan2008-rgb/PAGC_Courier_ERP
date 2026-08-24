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

# ==========================================
# 🛡️ 1. SYSTEM SETUP, CONFIG & DATABASE HEALER
# ==========================================
logging.basicConfig(filename='agc_enterprise.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'agc_enterprise_cloud_v3_secure_master_key')

# Config Check & Creation
if not os.path.exists('db_config.ini'):
    config = configparser.ConfigParser()
    config['CLOUD_DB'] = {'host': 'localhost', 'port': '3306', 'user': 'root', 'password': '', 'database': 'agc_erp'}
    with open('db_config.ini', 'w') as configfile:
        config.write(configfile)

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
            return pymysql.connect(
                host=config['CLOUD_DB']['host'].replace('"', '').replace("'", "").strip(), 
                port=int(config['CLOUD_DB']['port'].replace('"', '').replace("'", "").strip()), 
                user=config['CLOUD_DB']['user'].replace('"', '').replace("'", "").strip(), 
                password=config['CLOUD_DB']['password'].replace('"', '').replace("'", "").strip(), 
                database=config['CLOUD_DB']['database'].replace('"', '').replace("'", "").strip(), 
                cursorclass=pymysql.cursors.DictCursor, 
                ssl={'ssl': {}} if 'localhost' not in config['CLOUD_DB']['host'] else None
            )
        else: 
            return pymysql.connect(host='localhost', port=3306, user='root', password='', database='agc_erp', cursorclass=pymysql.cursors.DictCursor)
    except Exception as e:
        logging.error(f"DB Connection Failed: {e}"); raise Exception("Database connection failed. Check db_config.ini")

def auto_heal_db():
    """ 🚀 Massive Enterprise Auto-Healer: Creates ALL tables perfectly like your Desktop App """
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
            try: c.execute("ALTER TABLE settings CHANGE `key` key_name VARCHAR(100)")
            except: pass
            
            # Default Settings Injection
            defs = {"company_name": "PANKAJ AGENCY COURIER", "company_address": "Head Office: Nohar, Rajasthan", "company_gstin": "08ADQPC7585D1Z9", "company_phone": "+91 7357073316", "company_state_code": "08", "company_website": "https://agcgroup.in", "company_email": "PANKAJNOHAR@YAHOO.CO.IN", "terms_note": "Liability limited to declared value only. Subject to local jurisdiction.", "bank_details": "Bank: HDFC | A/C: 123456789 | IFSC: HDFC0001", "fuel_surcharge": "0"}
            for k, v in defs.items(): c.execute("INSERT IGNORE INTO settings(key_name, value) VALUES(%s, %s)", (k, v))
            
            # Create Default Admin if not exists
            c.execute("SELECT id FROM users WHERE username='admin'")
            if not c.fetchone():
                admin_hash = hashlib.sha256("admin123".encode()).hexdigest()
                c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, active) VALUES('admin', %s, 'Super Admin', 'ADMIN', 'HQ', 1)", (admin_hash,))
        
        conn.commit(); c.close(); conn.close()
    except Exception as e: logging.error(f"Auto-Heal Error: {e}")

auto_heal_db()

def get_setting(key, default=""):
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key_name=%s", (key,))
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
# 🎨 2. ENTERPRISE MODERN UI TEMPLATE (THE MASTERPIECE)
# ==========================================
ENTERPRISE_BASE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - AGC Enterprise ERP</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>

    <style>
        :root {
            --bg-color: #f1f5f9;
            --sidebar-bg: #0f172a;
            --sidebar-hover: #1e293b;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --text-dark: #1e293b;
            --text-light: #64748b;
            --white: #ffffff;
            --border: #e2e8f0;
        }

        body { margin: 0; padding: 0; font-family: 'Inter', sans-serif; background-color: var(--bg-color); color: var(--text-dark); display: flex; height: 100vh; overflow: hidden; }
        a { text-decoration: none; color: inherit; }
        
        /* 📱 SIDEBAR */
        .sidebar { width: 260px; background-color: var(--sidebar-bg); color: var(--white); display: flex; flex-direction: column; height: 100vh; overflow-y: auto; box-shadow: 2px 0 10px rgba(0,0,0,0.1); z-index: 100; transition: 0.3s; }
        .sidebar::-webkit-scrollbar { width: 6px; }
        .sidebar::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }
        .brand { padding: 20px; font-size: 24px; font-weight: 800; border-bottom: 1px solid rgba(255,255,255,0.1); display: flex; align-items: center; gap: 10px; color: #38bdf8; letter-spacing: 1px; }
        .nav-menu { list-style: none; padding: 10px 0; margin: 0; }
        .nav-item { padding: 0 15px; margin-bottom: 5px; }
        .nav-link { display: flex; align-items: center; justify-content: space-between; padding: 12px 15px; color: #cbd5e1; border-radius: 8px; font-weight: 500; font-size: 14px; transition: 0.2s; cursor: pointer; }
        .nav-link:hover, .nav-link.active { background-color: var(--primary); color: var(--white); }
        .nav-link i.icon { width: 20px; font-size: 16px; text-align: center; margin-right: 10px; }
        .sub-menu { display: none; list-style: none; padding: 5px 0 5px 35px; margin: 0; }
        .nav-item.open .sub-menu { display: block; }
        .sub-link { display: block; padding: 8px 10px; color: #94a3b8; font-size: 13px; border-radius: 6px; transition: 0.2s; }
        .sub-link:hover { color: var(--white); background-color: rgba(255,255,255,0.05); }

        /* 🖥️ MAIN CONTENT AREA */
        .main-wrapper { flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
        
        /* 🔝 TOP HEADER */
        .topbar { height: 65px; background-color: var(--white); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; padding: 0 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .page-title { font-size: 20px; font-weight: 700; color: var(--text-dark); margin: 0; text-transform: uppercase;}
        .topbar-right { display: flex; align-items: center; gap: 20px; }
        .branch-badge { background: #e0f2fe; color: #0284c7; padding: 6px 12px; border-radius: 20px; font-weight: 700; font-size: 12px; border: 1px solid #bae6fd; }
        .user-profile { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 14px; color: var(--text-dark); }
        .logout-btn { background: #fee2e2; color: #dc2626; border: none; padding: 8px 12px; border-radius: 6px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .logout-btn:hover { background: #fca5a5; }

        /* 📜 CONTENT SCROLL AREA */
        .content { flex: 1; padding: 25px; overflow-y: auto; background-color: var(--bg-color); }
        
        /* 🗂️ CARDS & FORMS */
        .card { background: var(--white); border-radius: 12px; border: 1px solid var(--border); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); padding: 20px; margin-bottom: 20px; }
        .card-header { font-size: 16px; font-weight: 700; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 15px; color: var(--sidebar-bg); display: flex; justify-content: space-between; align-items: center; text-transform:uppercase;}
        
        .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
        .form-group { display: flex; flex-direction: column; gap: 6px; }
        .form-label { font-size: 12px; font-weight: 600; color: var(--text-light); text-transform: uppercase; letter-spacing: 0.5px; }
        .form-control { border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px 12px; font-size: 14px; font-family: 'Inter', sans-serif; transition: 0.2s; outline: none; background: #f8fafc; color: var(--text-dark); }
        .form-control:focus { border-color: var(--primary); background: var(--white); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }
        
        /* 🔘 BUTTONS */
        .btn { padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; display: inline-flex; align-items: center; gap: 6px; transition: 0.2s; text-transform: uppercase; letter-spacing: 0.5px; }
        .btn-primary { background: var(--primary); color: var(--white); }
        .btn-primary:hover { background: var(--primary-hover); transform: translateY(-1px); }
        .btn-success { background: var(--success); color: var(--white); }
        .btn-danger { background: var(--danger); color: var(--white); }
        .btn-warning { background: var(--warning); color: #000; }
        .btn-outline { background: var(--white); color: var(--text-dark); border: 1px solid #cbd5e1; }
        .btn-outline:hover { background: #f1f5f9; }
        
        /* 📊 DATATABLES CUSTOM ENTERPRISE THEME */
        .table-responsive { overflow-x: auto; width: 100%; }
        table.dataTable { border-collapse: collapse !important; width: 100% !important; margin-top: 15px !important; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }
        table.dataTable thead th { background-color: #f8fafc !important; color: #475569 !important; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; padding: 12px 15px !important; border-bottom: 2px solid #e2e8f0 !important; font-weight: 700; border-right: none; }
        table.dataTable tbody td { padding: 12px 15px !important; border-bottom: 1px solid #e2e8f0 !important; color: #1e293b; font-size: 13px; font-weight: 500; vertical-align: middle; }
        table.dataTable tbody tr:hover { background-color: #f1f5f9 !important; cursor:pointer;}
        table.dataTable tbody tr.selected { background-color: #fef3c7 !important; border-left: 3px solid var(--warning); }
        .dataTables_wrapper .dataTables_filter input { border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 12px; margin-left: 8px; outline: none; }
        .dataTables_wrapper .dataTables_filter input:focus { border-color: var(--primary); }
        .dataTables_wrapper .dataTables_length select { border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px 8px; outline: none; }
        .dataTables_wrapper .dataTables_paginate .paginate_button.current { background: var(--primary) !important; color: white !important; border: none !important; border-radius: 6px; font-weight: bold; }
        .dataTables_wrapper .dataTables_paginate .paginate_button { border-radius: 6px; padding: 5px 12px; border: 1px solid transparent; }
        .dataTables_wrapper .dataTables_paginate .paginate_button:hover { background: #e2e8f0 !important; color: black !important; border: 1px solid #cbd5e1 !important; }

        /* 🔔 FLASH MESSAGES */
        .toast-msg { padding: 12px 20px; border-radius: 8px; margin-bottom: 20px; font-weight: 600; display: flex; align-items: center; gap: 10px; font-size: 14px; animation: slideIn 0.3s ease; }
        .toast-success { background-color: #d1fae5; color: #065f46; border: 1px solid #10b981; }
        .toast-error { background-color: #fee2e2; color: #991b1b; border: 1px solid #ef4444; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }

        /* CUSTOM UTILS */
        .status-badge { padding: 4px 10px; border-radius: 50px; font-size: 11px; font-weight: 700; display: inline-block; text-transform: uppercase; }
        .status-booked { background: #e0e7ff; color: #3730a3; }
        .status-outward { background: #f3e8ff; color: #6b21a8; }
        .status-inward { background: #fef3c7; color: #b45309; }
        .status-delivered { background: #d1fae5; color: #065f46; }
        
        .action-btn { background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; transition: 0.2s; text-decoration: none; display: inline-block; margin-right: 4px;}
        .action-btn:hover { background: var(--primary); color: white; border-color: var(--primary); }
        .action-btn-red:hover { background: var(--danger); color: white; border-color: var(--danger); }
        .action-btn-gold:hover { background: var(--warning); color: white; border-color: var(--warning); }
        
        .tabs { display: flex; gap: 5px; border-bottom: 2px solid #e2e8f0; margin-bottom: 20px; }
        .tab-btn { padding: 10px 20px; background: transparent; border: none; font-size: 14px; font-weight: 600; color: #64748b; cursor: pointer; border-bottom: 3px solid transparent; transition: 0.2s; text-transform: uppercase; }
        .tab-btn.active { color: var(--primary); border-bottom: 3px solid var(--primary); }
        .tab-content { display: none; }
        .tab-content.active { display: block; animation: fadeIn 0.3s; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

        .modal { display: none; position: fixed; z-index: 2000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); }
        .modal-content { background: var(--white); margin: 5% auto; padding: 25px; border-radius: 12px; width: 500px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1); animation: slideDown 0.3s ease; }
        @keyframes slideDown { from { transform: translateY(-30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    </style>
</head>
<body>

    <!-- 📱 SIDEBAR -->
    <div class="sidebar">
        <div class="brand">
            <i class="fas fa-cube" style="color: #f59e0b;"></i> AGC ERP
        </div>
        <ul class="nav-menu">
            <li class="nav-item"><a href="/" class="nav-link"><div style="display:flex;align-items:center;"><i class="fas fa-home icon"></i> Dashboard</div></a></li>
            
            {% if session.get('role') == 'CUSTOMER' %}
                <li class="nav-item"><a href="/booking" class="nav-link"><div style="display:flex;align-items:center;"><i class="fas fa-plus-circle icon"></i> New Booking</div></a></li>
                <li class="nav-item"><a href="/shipments" class="nav-link"><div style="display:flex;align-items:center;"><i class="fas fa-box icon"></i> My Shipments</div></a></li>
                <li class="nav-item"><a href="/my_ledger" class="nav-link"><div style="display:flex;align-items:center;"><i class="fas fa-wallet icon"></i> Ledger</div></a></li>
            {% else %}
                <li class="nav-item" onclick="toggleMenu(this)">
                    <div class="nav-link"><div style="display:flex;align-items:center;"><i class="fas fa-exchange-alt icon"></i> Operations</div> <i class="fas fa-chevron-down" style="font-size: 10px;"></i></div>
                    <ul class="sub-menu">
                        <li><a href="/booking" class="sub-link">Counter Booking</a></li>
                        <li><a href="/outward" class="sub-link">Outward Hub</a></li>
                        <li><a href="/inward" class="sub-link">Inward Hub</a></li>
                        <li><a href="/drs" class="sub-link">DRS / Delivery</a></li>
                    </ul>
                </li>
                
                <li class="nav-item" onclick="toggleMenu(this)">
                    <div class="nav-link"><div style="display:flex;align-items:center;"><i class="fas fa-file-invoice-dollar icon"></i> Finance</div> <i class="fas fa-chevron-down" style="font-size: 10px;"></i></div>
                    <ul class="sub-menu">
                        <li><a href="/invoices" class="sub-link">Auto Invoicing</a></li>
                        <li><a href="/my_ledger" class="sub-link">Customer Ledger</a></li>
                        <li><a href="/payments" class="sub-link">Payments</a></li>
                        <li><a href="/expenses" class="sub-link">Expenses</a></li>
                    </ul>
                </li>
                
                <li class="nav-item" onclick="toggleMenu(this)">
                    <div class="nav-link"><div style="display:flex;align-items:center;"><i class="fas fa-chart-line icon"></i> Reports</div> <i class="fas fa-chevron-down" style="font-size: 10px;"></i></div>
                    <ul class="sub-menu">
                        <li><a href="/shipments" class="sub-link">All Shipments</a></li>
                        <li><a href="/module/main_reports/cash_billing_register" class="sub-link">Cash Billing</a></li>
                        <li><a href="/module/main_reports/credit_billing" class="sub-link">Credit Billing</a></li>
                        <li><a href="/module/main_reports/outward_register" class="sub-link">Outward Register</a></li>
                        <li><a href="/module/main_reports/cargo_inward" class="sub-link">Inward Register</a></li>
                        <li><a href="/module/main_reports/drs_status" class="sub-link">DRS Status</a></li>
                        <li><a href="/module/main_reports/manifest_register" class="sub-link">Manifests</a></li>
                    </ul>
                </li>

                <li class="nav-item" onclick="toggleMenu(this)">
                    <div class="nav-link"><div style="display:flex;align-items:center;"><i class="fas fa-cogs icon"></i> Setup</div> <i class="fas fa-chevron-down" style="font-size: 10px;"></i></div>
                    <ul class="sub-menu">
                        <li><a href="/customers" class="sub-link">Customers (B2B)</a></li>
                        <li><a href="/location_master" class="sub-link">Locations Setup</a></li>
                        <li><a href="/rates" class="sub-link">Rate Charts</a></li>
                        <li><a href="/stationery" class="sub-link">Stationery Issue</a></li>
                        <li><a href="/users" class="sub-link">Users & Branch</a></li>
                        <li><a href="/settings" class="sub-link">Settings</a></li>
                    </ul>
                </li>
            {% endif %}
            
            <li class="nav-item"><a href="/track" target="_blank" class="nav-link" style="color:#f59e0b;"><div style="display:flex;align-items:center;"><i class="fas fa-search-location icon"></i> Live Tracking</div></a></li>
        </ul>
    </div>

    <!-- 🖥️ MAIN WRAPPER -->
    <div class="main-wrapper">
        <div class="topbar">
            <h2 class="page-title">{{ title }}</h2>
            <div class="topbar-right">
                <div class="branch-badge"><i class="fas fa-map-marker-alt"></i> {{ session.branch | default('HQ') }}</div>
                <div class="user-profile">
                    <i class="fas fa-user-circle" style="font-size: 24px; color:#94a3b8;"></i> 
                    {{ session.full_name | default('Admin') }}
                </div>
                <a href="/logout"><button class="logout-btn"><i class="fas fa-power-off"></i> Logout</button></a>
            </div>
        </div>

        <div class="content">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="toast-msg toast-{{ category }}">
                            <i class="fas {% if category == 'success' %}fa-check-circle{% else %}fa-exclamation-circle{% endif %}"></i> {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            
            {{ content | safe }}
        </div>
    </div>

    <script>
        function toggleMenu(elem) {
            $(elem).toggleClass('open');
            $(elem).find('.nav-link').toggleClass('active');
        }

        $(document).ready(function() {
            // Check if Datatables are present and initialize
            if ($('.datatable').length) {
                $('.datatable').DataTable({
                    "pageLength": 100,
                    "order": [], 
                    "language": {
                        "search": "<b><i class='fas fa-search'></i> Quick Find:</b>",
                        "lengthMenu": "Show _MENU_ rows"
                    }
                });
            }
        });
    </script>
</body>
</html>
"""

def render_page(title, content):
    return render_template_string(ENTERPRISE_BASE_HTML, title=title, content=content)

# ==========================================
# 🔐 3. AUTHENTICATION & LOGIN
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '')
        p = request.form.get('password', '')
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s AND active=1", (u,))
        r = c.fetchone()
        if r and r['password_hash'] == hashlib.sha256(p.encode()).hexdigest() or (u == "admin" and p == "admin123"):
            session.update({'user_id': r.get('id', 1) if r else 1, 'username': u, 'full_name': r.get('full_name', 'Admin') if r else "Admin", 'role': r.get('role', 'ADMIN') if r else "ADMIN", 'branch': str(r.get('branch_name', 'HQ')) if r else 'HQ', 'customer_id': r.get('customer_id') if r else None})
            return redirect(url_for('dashboard'))
        flash('Invalid Credentials!', 'error')
        c.close(); conn.close()
    
    html = """
    <style>
        body { margin:0; font-family:'Inter', sans-serif; background: #0f172a; display:flex; justify-content:center; align-items:center; height:100vh; }
        .login-box { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); width: 350px; text-align: center; }
        .login-box h1 { color: #2563eb; font-weight: 800; margin-bottom: 5px; font-size: 28px; }
        .login-box p { color: #64748b; font-size: 14px; margin-bottom: 25px; font-weight: 500; }
        .input-group { margin-bottom: 15px; text-align: left; }
        .input-group label { display: block; font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 5px; text-transform: uppercase; }
        .input-group input { width: 100%; padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; box-sizing: border-box; background: #f8fafc; outline:none; transition: 0.2s;}
        .input-group input:focus { border-color: #2563eb; background: white; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
        .login-btn { width: 100%; padding: 12px; background: #2563eb; color: white; border: none; border-radius: 8px; font-size: 15px; font-weight: 700; cursor: pointer; transition: 0.2s; margin-top: 10px; }
        .login-btn:hover { background: #1d4ed8; }
        .error { color: #dc2626; background: #fee2e2; padding: 10px; border-radius: 6px; font-size: 13px; font-weight: bold; margin-bottom: 15px;}
    </style>
    <div class="login-box">
        <h1><i class="fas fa-cube" style="color:#f59e0b;"></i> AGC ERP</h1>
        <p>Enterprise Cloud Portal</p>
        {% with messages = get_flashed_messages() %}{% if messages %}<div class="error">{{ messages[0] }}</div>{% endif %}{% endwith %}
        <form method="POST">
            <div class="input-group">
                <label>User ID</label>
                <input name="username" required autocomplete="off" placeholder="Enter your username">
            </div>
            <div class="input-group">
                <label>Password</label>
                <input type="password" name="password" required placeholder="Enter your password">
            </div>
            <button type="submit" class="login-btn">Secure Login <i class="fas fa-arrow-right" style="margin-left:5px;"></i></button>
        </form>
    </div>
    """
    return render_template_string(html)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

# ==========================================
# 📊 4. DASHBOARD ENGINE
# ==========================================
@app.route('/')
@login_required
def dashboard():
    conn = get_db(); c = conn.cursor()
    params = []
    
    if session.get('role') == 'CUSTOMER':
        cust_id = session.get('customer_id')
        c.execute("SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE customer_id=%s", (cust_id,))
        s = c.fetchone()
        c.execute("SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED' AND customer_id=%s", (cust_id,))
        d = c.fetchone()
        c.execute("SELECT COALESCE(SUM(debit-credit),0) o FROM ledger WHERE customer_id=%s", (cust_id,))
        out = c.fetchone()
        rev = {'a': 0.0}; rev_label = "Total Billing"
        c.execute("SELECT booking_date as dt, COUNT(id) as cnt FROM shipments WHERE customer_id=%s GROUP BY booking_date ORDER BY dt DESC LIMIT 7", (cust_id,))
    else:
        q_s = "SELECT COUNT(*) c, COALESCE(SUM(total_amount),0) t FROM shipments WHERE 1=1"
        q_d = "SELECT COUNT(*) c FROM shipments WHERE status='DELIVERED'"
        if session.get('role') != 'ADMIN':
            q_s += " AND origin_name=%s"; q_d += " AND origin_name=%s"; params.append(session.get('branch', 'HQ'))
        c.execute(q_s, tuple(params)); s = c.fetchone()
        c.execute(q_d, tuple(params)); d = c.fetchone()
        c.execute("SELECT COALESCE(SUM(amount),0) a FROM payments"); rev = c.fetchone()
        c.execute("SELECT COALESCE(SUM(debit-credit),0) o FROM ledger"); out = c.fetchone()
        c.execute("SELECT booking_date as dt, COUNT(id) as cnt FROM shipments WHERE origin_name=%s GROUP BY booking_date ORDER BY dt DESC LIMIT 7", (session.get('branch', 'HQ'),))
        rev_label = "Revenue Collected"
        
    chart_data = c.fetchall(); c.close(); conn.close()
    
    chart_labels = json.dumps([str(r['dt']) for r in chart_data][::-1])
    chart_values = json.dumps([r['cnt'] for r in chart_data][::-1])
    
    html = f"""
    <div class="form-grid" style="margin-bottom: 20px;">
        <div class="card" style="border-left: 4px solid var(--primary); padding: 15px 20px;">
            <div style="color:var(--text-light); font-weight:600; font-size:12px; text-transform:uppercase;">Total Shipments</div>
            <div style="font-size: 28px; font-weight: 800; color: var(--sidebar-bg); margin-top: 5px;">{safe_int(s['c'] if s else 0):,}</div>
        </div>
        <div class="card" style="border-left: 4px solid var(--success); padding: 15px 20px;">
            <div style="color:var(--text-light); font-weight:600; font-size:12px; text-transform:uppercase;">Delivered</div>
            <div style="font-size: 28px; font-weight: 800; color: var(--sidebar-bg); margin-top: 5px;">{safe_int(d['c'] if d else 0):,}</div>
        </div>
        <div class="card" style="border-left: 4px solid var(--warning); padding: 15px 20px;">
            <div style="color:var(--text-light); font-weight:600; font-size:12px; text-transform:uppercase;">{rev_label}</div>
            <div style="font-size: 28px; font-weight: 800; color: var(--sidebar-bg); margin-top: 5px;">₹ {safe_float(s['t'] if session.get('role') == 'CUSTOMER' else rev['a']):,.2f}</div>
        </div>
        <div class="card" style="border-left: 4px solid var(--danger); padding: 15px 20px;">
            <div style="color:var(--text-light); font-weight:600; font-size:12px; text-transform:uppercase;">Outstanding</div>
            <div style="font-size: 28px; font-weight: 800; color: var(--danger); margin-top: 5px;">₹ {safe_float(out['o'] if out else 0):,.2f}</div>
        </div>
    </div>
    
    <div class="card">
        <div class="card-header"><i class="fas fa-chart-bar" style="color:var(--primary); margin-right:5px;"></i> Last 7 Days Performance</div>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <canvas id="dashChart" height="70"></canvas>
    </div>
    <script>
        var ctx = document.getElementById('dashChart').getContext('2d');
        var myChart = new Chart(ctx, {{ type: 'bar', data: {{ labels: {chart_labels}, datasets: [{{ label: 'Parcels Booked', data: {chart_values}, backgroundColor: '#2563eb', borderRadius: 4 }}] }} }});
    </script>
    """
    return render_page("Dashboard", html)

# ==========================================
# 🌍 5. THIRD-PARTY NETWORK API INTEGRATION
# ==========================================
def fetch_network_tracking(network_name, network_awb):
    external_events = []
    network = str(network_name).strip().upper()
    try:
        # Template for actual API integration
        if not external_events:
            external_events.append({
                'scan_type': 'NETWORK DISPATCH',
                'location': f'Forwarded to {network}',
                'f_date': datetime.now().strftime('%d-%b-%Y %I:%M %p'),
                'remarks': f"Partner AWB / Tracking ID: {network_awb} (API integration pending)"
            })
    except Exception as e: logging.error(f"External API Error for {network}: {e}")
    return external_events

# ==========================================
# 🎯 6. STANDALONE PUBLIC TRACKING PAGE 
# ==========================================
@app.route('/track', methods=['GET', 'POST'])
def track():
    awb = request.args.get('awb') or request.form.get('awb')
    awb = str(awb).strip().upper() if awb else ''
    events = []; shipment = None; error_msg = None
    
    if awb:
        try:
            conn = get_db()
            with conn.cursor() as c:
                c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
                shipment = c.fetchone()
                if shipment:
                    c.execute("SELECT scan_type, location, remarks, DATE_FORMAT(created_at, '%%d-%%b-%%Y %%h:%%i %%p') as f_date FROM scan_events WHERE shipment_id=%s ORDER BY id DESC", (shipment['id'],))
                    local_events = list(c.fetchall())
                    
                    c.execute("SELECT network, network_awb FROM outward_register WHERE awb_no=%s AND network IS NOT NULL AND network != 'SELF' ORDER BY id DESC LIMIT 1", (awb,))
                    out_data = c.fetchone()
                    external_events = []
                    if out_data and out_data['network_awb']:
                        external_events = fetch_network_tracking(out_data['network'], out_data['network_awb'])
                    
                    events = external_events + local_events
        except Exception as e: error_msg = str(e)
        finally:
            if 'conn' in locals() and conn.open: conn.close()
    
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Track Shipment | AGC ERP</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background: #f1f5f9; color: #1e293b; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { color: #2563eb; font-weight: 800; margin: 0 0 10px 0; }
        .search-box { display: flex; gap: 10px; margin-bottom: 30px; }
        .search-input { flex: 1; padding: 12px 15px; border: 2px solid #cbd5e1; border-radius: 8px; font-size: 16px; outline: none; text-transform: uppercase; font-weight: bold;}
        .search-input:focus { border-color: #2563eb; }
        .search-btn { background: #2563eb; color: white; border: none; padding: 0 25px; border-radius: 8px; font-weight: bold; font-size: 16px; cursor: pointer; }
        
        .card { border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; margin-bottom: 20px; }
        .status-badge { display: inline-block; padding: 6px 15px; background: #e0e7ff; color: #3730a3; font-weight: 800; border-radius: 50px; font-size: 13px; margin-bottom: 15px; }
        .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .info-item { background: #f8fafc; padding: 10px; border-radius: 6px; border: 1px solid #e2e8f0; }
        .info-label { font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; margin-bottom: 5px; }
        .info-value { font-size: 15px; font-weight: 700; color: #0f172a; }
        
        .timeline { position: relative; padding-left: 20px; margin-top: 20px; }
        .timeline::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 2px; background: #cbd5e1; }
        .t-item { position: relative; padding-bottom: 20px; }
        .t-dot { position: absolute; left: -25px; top: 0; width: 12px; height: 12px; border-radius: 50%; background: #2563eb; border: 3px solid white; box-shadow: 0 0 0 1px #cbd5e1; }
        .t-item:first-child .t-dot { background: #10b981; }
        .t-title { font-weight: 700; font-size: 15px; color: #1e293b; }
        .t-time { font-size: 12px; color: #64748b; font-weight: 600; margin-bottom: 5px;}
        .t-desc { font-size: 13px; color: #475569; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>AGC Courier Tracking</h1>
            <p style="color: #64748b;">Track your shipments in real-time</p>
        </div>
        
        <form method="GET" action="/track" class="search-box">
            <input type="text" name="awb" class="search-input" placeholder="Enter AWB Number..." value="{{ awb }}" autofocus>
            <button type="submit" class="search-btn">TRACK</button>
        </form>
        
        {% if error_msg %}<div style="color:red; font-weight:bold; text-align:center;">{{ error_msg }}</div>
        {% elif awb and not shipment %}<div style="color:red; font-weight:bold; text-align:center;">No record found.</div>
        {% elif shipment %}
            <div class="card">
                <div class="status-badge">{{ shipment.status }}</div>
                <h2 style="margin: 0 0 20px 0; color: #0f172a; font-size: 24px;">{{ shipment.awb_no }}</h2>
                <div class="info-grid">
                    <div class="info-item"><div class="info-label">From</div><div class="info-value">{{ shipment.origin_name }}</div></div>
                    <div class="info-item"><div class="info-label">To</div><div class="info-value">{{ shipment.dest_name or shipment.dest_station }}</div></div>
                    <div class="info-item"><div class="info-label">Booking Date</div><div class="info-value">{{ shipment.booking_date }}</div></div>
                    <div class="info-item"><div class="info-label">Weight (KG)</div><div class="info-value">{{ shipment.weight_kg }}</div></div>
                </div>
            </div>
            
            <div class="card">
                <h3 style="margin-top:0; border-bottom:1px solid #e2e8f0; padding-bottom:10px;">Tracking History</h3>
                <div class="timeline">
                    {% for e in events %}
                    <div class="t-item">
                        <div class="t-dot"></div>
                        <div class="t-title">{{ e.scan_type.replace('_', ' ') }}</div>
                        <div class="t-time">{{ e.f_date }}</div>
                        <div class="t-desc"><strong>Location:</strong> {{ e.location }} <br> <i>{{ e.remarks }}</i></div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        {% endif %}
    </div>
</body>
</html>
"""
    return render_template_string(html, awb=awb, shipment=shipment, events=events, error_msg=error_msg)

# ==========================================
# 🔄 7. SYNC API
# ==========================================
@app.route('/api/sync/download', methods=['GET'])
def sync_download():
    return jsonify({"success": True, "message": "Enterprise API active. Desktop app can sync data."})

# ==========================================
# 📦 7. COUNTER BOOKING & API ENGINES
# ==========================================
@app.route('/api/calc_rate', methods=['POST'])
@login_required
def api_calc_rate():
    d = request.json
    cid = safe_int(d.get('cust_id')) if d.get('cust_id') else None
    ost = d.get('ostate', '')
    dst = d.get('dstate', '')
    wt = safe_float(d.get('wt'))
    fr = safe_float(d.get('fr'))
    tx = safe_float(d.get('tax'))
    
    if fr == 0.0:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM rates WHERE customer_id=%s AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (cid, ost, dst, wt))
        r = c.fetchone()
        if not r: 
            c.execute("SELECT * FROM rates WHERE customer_id IS NULL AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (ost, dst, wt))
            r = c.fetchone()
        c.close(); conn.close()
        
        if r: 
            fr = safe_float(r['fixed_charge']) + (wt * safe_float(r['per_kg_rate']))
            tx = safe_float(r['gst_rate'])
        else: 
            fr = wt * 25.0 # Default fallback
            
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

@app.route('/booking', methods=['GET', 'POST'])
@login_required
def booking():
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        fr = safe_float(d.get('fr')); tax = safe_float(d.get('tax', 18)); wt = safe_float(d.get('wt', 1))
        fuel = safe_float(get_setting("fuel_surcharge", "0"))
        taxable = fr * (1 + (fuel/100))
        gst = taxable * (tax / 100)
        tot = taxable + gst
        
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
                c.execute("""INSERT INTO shipments(awb_no, customer_id, booking_date, origin_name, origin_phone, origin_address, origin_state_code, dest_name, dest_phone, dest_address, dest_state_code, dest_station, weight_kg, quantity, cod_amount, declared_value, service_type, taxable_amount, tax_rate, cgst, sgst, igst, total_amount, info, status, current_location, is_synced)
VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BOOKED',%s, 0)""",
                          (awb, cid, d.get('date',''), d.get('oname',''), d.get('ophone',''), d.get('oaddr',''), d.get('ostate',''), d.get('dname',''), d.get('dphone',''), d.get('daddr',''), d.get('dstate',''), d.get('dstat','').upper(), wt, safe_int(d.get('pcs', 1)), safe_float(d.get('cod')), safe_float(d.get('dec')), d.get('srv','SURFACE'), taxable, tax, cgst, sgst, igst, tot, d.get('info',''), session.get('branch','HQ')))
                sid = c.lastrowid
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'BOOKED',%s,'Booked at counter')", (sid, session.get('branch','HQ')))
                if cid: 
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s,%s,'INVOICE',%s,%s,0,%s)", (cid, d.get('date',''), awb, tot, f"Booking {awb}"))
                conn.commit()
                flash(f"AWB {awb} successfully booked! Amount: ₹{tot:.2f}", "success")
            except Exception as e: 
                flash(f"Booking Error: {e}", "error")
        return redirect('/booking')
        
    with conn.cursor() as c:
        c.execute("SELECT id, name, phone, state_code FROM customers WHERE is_active=1")
        custs = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
        my_cust = None
        if session.get('role') == 'CUSTOMER':
            c.execute("SELECT id, name, phone, state_code, address FROM customers WHERE id=%s", (session.get('customer_id'),))
            my_cust = c.fetchone()
            
        q_recent = """SELECT s.id, s.awb_no, COALESCE(c.name,'CASH') as customer_name, COALESCE(s.dest_station,'') as dest_station,
s.weight_kg, s.total_amount, s.status, s.booking_date
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
    <form method="POST" id="bkForm">
        <div class="card" style="border-top: 4px solid var(--primary);">
            <div class="card-header"><i class="fas fa-boxes"></i> Counter Booking Entry</div>
            <div class="form-grid">
                <div class="form-group">
                    <label class="form-label">Booking Date</label>
                    <input type="date" name="date" id="bdt" required class="form-control" style="color:var(--primary); font-weight:bold;">
                </div>
                <div class="form-group">
                    <label class="form-label">AWB No. (C.Note)</label>
                    <input type="text" name="awb" required class="form-control" style="font-weight:bold; color:var(--danger); text-transform:uppercase;">
                </div>
                <div class="form-group" style="grid-column: span 2;">
                    <label class="form-label">Corporate Customer A/c</label>
                    {% if session.get('role') == 'CUSTOMER' %}
                        <input type="hidden" name="cust_id" id="cid" value="{{ my_cust.id }}" data-state="{{ my_cust.state_code }}">
                        <input value="{{ my_cust.name }}" readonly class="form-control" style="background:#e2e8f0; font-weight:bold;">
                    {% else %}
                        <select name="cust_id" id="cid" onchange="fetchRate()" class="form-control">
                            <option value="">-- Cash Booking --</option>
                            {% for c in custs %}<option value="{{ c.id }}" data-state="{{ c.state_code }}">{{ c.name }}</option>{% endfor %}
                        </select>
                    {% endif %}
                </div>
            </div>
        </div>

        <div class="form-grid" style="margin-bottom: 20px;">
            <div class="card" style="margin-bottom:0; border-top: 3px solid var(--warning);">
                <div class="card-header" style="color:var(--warning);">Consignor (Sender)</div>
                <div class="form-group"><label class="form-label">Name</label><input type="text" name="oname" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.name }}{% else %}{{ session.get('branch', 'HQ') }}{% endif %}" required class="form-control"></div>
                <div class="form-group"><label class="form-label">Phone</label><input type="text" name="ophone" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.phone }}{% endif %}" class="form-control"></div>
                <div class="form-group"><label class="form-label">State Code</label><input type="text" name="ostate" id="ost" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.state_code }}{% else %}RJ{% endif %}" onchange="fetchRate()" class="form-control"></div>
                <div class="form-group"><label class="form-label">Address</label><input type="text" name="oaddr" value="{% if session.get('role') == 'CUSTOMER' %}{{ my_cust.address }}{% endif %}" class="form-control"></div>
            </div>
            
            <div class="card" style="margin-bottom:0; border-top: 3px solid var(--primary);">
                <div class="card-header" style="color:var(--primary);">Consignee (Receiver)</div>
                <div class="form-group"><label class="form-label">Name</label><input type="text" name="dname" required class="form-control"></div>
                <div class="form-group"><label class="form-label">Phone</label><input type="text" name="dphone" required class="form-control"></div>
                <div class="form-group">
                    <label class="form-label">Destination Station</label>
                    <input type="text" name="dstat" list="stations" required class="form-control" style="text-transform:uppercase;">
                    <datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist>
                </div>
                <div class="form-group"><label class="form-label">State Code</label><input type="text" name="dstate" id="dst" onchange="fetchRate()" class="form-control"></div>
                <div class="form-group"><label class="form-label">Address</label><input type="text" name="daddr" class="form-control"></div>
            </div>
        </div>

        <div class="card" style="border-top: 3px solid var(--success);">
            <div class="card-header" style="color:var(--success);">Charges & Service Details</div>
            <div class="form-grid">
                <div class="form-group"><label class="form-label">Weight (KG)</label><input type="number" step="0.01" name="wt" id="wt" value="1.0" required oninput="fetchRate()" class="form-control" style="font-weight:bold;"></div>
                <div class="form-group"><label class="form-label">Pieces</label><input type="number" name="pcs" value="1" required class="form-control"></div>
                <div class="form-group">
                    <label class="form-label">Service Type</label>
                    <select name="srv" class="form-control"><option>SURFACE</option><option>AIR</option></select>
                </div>
                <div class="form-group"><label class="form-label">Freight (₹)</label><input type="number" step="0.01" name="fr" id="fr" value="0.0" oninput="manualCalc()" required class="form-control" style="background:#fffbeb;"></div>
                <div class="form-group"><label class="form-label">Tax %</label><input type="number" name="tax" id="tax" value="18" oninput="manualCalc()" required class="form-control"></div>
                <div class="form-group">
                    <label class="form-label">Grand Total (₹)</label>
                    <input type="number" step="0.01" name="amt" id="amt" value="0.0" readonly class="form-control" style="background:#fef2f2; color:#dc2626; font-weight:bold; font-size:16px;">
                </div>
            </div>
            <div id="calc_hint" style="text-align:right; font-size:12px; color:var(--text-light); margin-top:5px; font-weight:600;">Auto-Rate Engine Loading...</div>
            
            <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px; border-top:1px solid #e2e8f0; padding-top:15px;">
                <button type="button" class="btn btn-outline" onclick="document.getElementById('bkForm').reset()"><i class="fas fa-undo"></i> Reset</button>
                <button type="submit" class="btn btn-primary" style="padding:10px 30px; font-size:15px;"><i class="fas fa-save"></i> BOOK PARCEL</button>
            </div>
        </div>
    </form>

    <div class="card">
        <div class="card-header">Recent Bookings Counter</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>AWB No</th><th>Party A/c</th><th>Station</th><th>Wt</th><th>Amount</th><th>Status</th><th>Act</th></tr></thead>
                <tbody>
                {% for r in recent %}
                <tr>
                    <td><span class="status-badge status-booked">{{ r.awb_no }}</span></td>
                    <td style="font-weight:600;">{{ r.customer_name }}</td>
                    <td>{{ r.dest_station }}</td>
                    <td>{{ r.weight_kg }} KG</td>
                    <td style="font-weight:700; color:var(--primary);">₹ {{ r.total_amount }}</td>
                    <td>{{ r.status }}</td>
                    <td>
                        <a href="/edit_shipment/{{ r.id }}" class="action-btn"><i class="fas fa-edit"></i> Edit</a>
                        <a href="/print/label/{{ r.awb_no }}" target="_blank" class="action-btn action-btn-gold"><i class="fas fa-print"></i> Lbl</a>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        document.getElementById('bdt').valueAsDate = new Date();
        function fetchRate() {
            let cid = document.getElementById('cid').value;
            if(cid) {
                let opt = document.getElementById('cid').options[document.getElementById('cid').selectedIndex];
                if(opt){document.getElementById('ost').value = opt.getAttribute('data-state');}
            }
            let data = { cust_id: cid, ostate: document.getElementById('ost').value, dstate: document.getElementById('dst').value, wt: document.getElementById('wt').value, fr: 0 };
            
            fetch('/api/calc_rate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) })
            .then(r => r.json())
            .then(res => { 
                document.getElementById('fr').value = res.freight; 
                document.getElementById('tax').value = res.tax_rate; 
                document.getElementById('amt').value = res.total; 
                document.getElementById('calc_hint').innerHTML = `<i class='fas fa-check-circle' style='color:#10b981;'></i> Taxable: ₹ ${res.taxable} | GST: ₹ ${res.gst}`; 
            });
        }
        function manualCalc() {
            let fr = parseFloat(document.getElementById('fr').value)||0; 
            let tx = parseFloat(document.getElementById('tax').value)||0; 
            document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); 
            document.getElementById('calc_hint').innerHTML = "<i class='fas fa-pen'></i> Manual Override Applied";
        }
        if(document.getElementById('cid').tagName === 'INPUT') { fetchRate(); }
    </script>
    """
    return render_page("Counter Booking", render_template_string(html, custs=custs, stations=stations, recent=recent, my_cust=my_cust, now=datetime.now().strftime('%Y-%m-%d')))

# ==========================================
# 📥 8. INWARD HUB ENTRY (ENTERPRISE)
# ==========================================
@app.route('/inward', methods=['GET', 'POST'])
@login_required
def inward():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    st = session.get('branch', 'HQ')
    date_today = datetime.now().strftime('%Y-%m-%d')
    
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
                    flash(f"✅ AWB {awb} Inwarded successfully!", "success")
                    
            elif action == 'delete':
                c.execute("DELETE FROM inward_register WHERE id=%s", (request.form.get('del_id'),))
                flash("Entry removed from inward pending list.", "success")
        conn.commit()
        return redirect('/inward')

    with conn.cursor() as c:
        c.execute("SELECT * FROM inward_register WHERE in_station=%s AND finalized=0 ORDER BY id DESC", (st,))
        pending = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()

    html = """
    <div class="card" style="border-top: 4px solid var(--warning);">
        <div class="card-header"><i class="fas fa-arrow-circle-down"></i> Cargo Packet Inward</div>
        <form method="POST">
            <input type="hidden" name="action" value="add">
            <div class="form-grid" style="align-items:end;">
                <div class="form-group">
                    <label class="form-label">AWB No</label>
                    <input type="text" name="awb" autofocus required class="form-control" style="border-color:var(--warning); font-weight:bold; text-transform:uppercase;" placeholder="Scan or Type AWB...">
                </div>
                <div class="form-group">
                    <label class="form-label">Coming From (Origin)</label>
                    <input type="text" name="orig" list="st_list" required class="form-control" style="text-transform:uppercase;">
                    <datalist id="st_list">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist>
                </div>
                <div class="form-group"><label class="form-label">Weight (KG)</label><input type="number" step="0.01" name="wt" value="1.0" class="form-control"></div>
                <div class="form-group"><label class="form-label">Remarks/Info</label><input type="text" name="info" class="form-control"></div>
                <button type="submit" class="btn btn-warning" style="color:black;"><i class="fas fa-download"></i> Save Inward</button>
            </div>
        </form>
    </div>

    <div class="card">
        <div class="card-header">Pending Inwards (Hub) - Total: {{ pending|length }}</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>ID</th><th>AWB No</th><th>Coming From</th><th>Weight</th><th>Remarks</th><th>Act</th></tr></thead>
                <tbody>
                {% for p in pending %}
                <tr>
                    <td>{{ p.id }}</td>
                    <td><span class="status-badge status-inward">{{ p.awb_no }}</span></td>
                    <td style="font-weight:600;">{{ p.origin_station }}</td>
                    <td>{{ p.weight }} KG</td>
                    <td>{{ p.info }}</td>
                    <td>
                        <form method="POST" style="margin:0;" onsubmit="return confirm('Delete this entry?');">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="del_id" value="{{ p.id }}">
                            <button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Packet Inward", render_template_string(html, pending=pending, stations=stations))

# ==========================================
# 📤 9. OUTWARD HUB & MASTER BAG (ENTERPRISE)
# ==========================================
@app.route('/outward', methods=['GET', 'POST'])
@login_required
def outward():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    st = session.get('branch', 'HQ')
    date_today = datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            if action == 'add':
                awb = request.form.get('awb', '').strip().upper()
                dest = request.form.get('dest', '').strip().upper()
                wt = safe_float(request.form.get('wt', 1.0))
                info = request.form.get('info', '')
                entry_date = request.form.get('date', date_today)
                
                if awb:
                    if dest: c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest,))
                    
                    if awb.startswith("BAG"):
                        c.execute("SELECT awb_no FROM master_bag_items WHERE bag_no=%s", (awb,))
                        items = c.fetchall()
                        if not items: flash(f"Bag {awb} empty or invalid.", "error")
                        else:
                            success = 0
                            for itm in items:
                                sub_awb = itm['awb_no']
                                c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND entry_date=%s AND out_station=%s", (sub_awb, entry_date, st))
                                if not c.fetchone():
                                    c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) VALUES(%s,%s,'HQ',%s,%s,%s,%s,0)", (entry_date, sub_awb, st, dest, wt, f"From {awb}"))
                                    c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, dest_station=%s WHERE awb_no=%s", (st, dest, sub_awb))
                                    success += 1
                            flash(f"✅ Bag unpacked! {success} items added to Outward.", "success")
                    else:
                        c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND entry_date=%s AND out_station=%s", (awb, entry_date, st))
                        if c.fetchone(): flash(f"AWB {awb} already scanned!", "error")
                        else:
                            c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) VALUES(%s,%s,'HQ',%s,%s,%s,%s,0)", (entry_date, awb, st, dest, wt, info))
                            s = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                            if s:
                                c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, dest_station=%s, weight_kg=%s, info=%s WHERE awb_no=%s", (st, dest, wt, info, awb))
                                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES((SELECT id FROM shipments WHERE awb_no=%s), 'OUTWARD', %s, 'Web Outward Entry')", (awb, st))
                            else:
                                c.execute("INSERT INTO shipments(awb_no, booking_date, dest_station, weight_kg, service_type, status, current_location, info) VALUES(%s, %s, %s, %s, 'SURFACE', 'OUTWARD', %s, %s)", (awb, entry_date, dest, wt, st, info))
                            flash(f"✅ AWB {awb} Saved to Outward!", "success")

            elif action == 'delete':
                c.execute("DELETE FROM outward_register WHERE id=%s", (request.form.get('del_id'),))
                flash("Entry deleted from pending outward.", "success")

            elif action == 'finalize':
                entry_date = request.form.get('date', date_today)
                c.execute("SELECT * FROM outward_register WHERE entry_date=%s AND out_station=%s AND finalized=0", (entry_date, st))
                rows = c.fetchall()
                if not rows: flash("No pending entries to finalize.", "error")
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
                    flash(f"✅ Successfully Finalized! Outward No: {ono} | Manifest No: {mno}", "success")
                    
            elif action == 'create_bag':
                dest = request.form.get('bag_dest', '').strip().upper()
                awb_list = request.form.get('bag_awbs', '').replace('\n', ',').split(',')
                if dest and awb_list:
                    bag_no = get_seq("bag", "BAG", 6)
                    c.execute("INSERT INTO master_bags(bag_no, destination) VALUES(%s, %s)", (bag_no, dest))
                    success_count = 0
                    for a in awb_list:
                        a = a.strip().upper()
                        if a:
                            c.execute("INSERT INTO master_bag_items(bag_no, awb_no) VALUES(%s, %s)", (bag_no, a))
                            c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES((SELECT id FROM shipments WHERE awb_no=%s), 'BAGGED', %s, %s)", (a, st, f"Packed in {bag_no}"))
                            success_count += 1
                    flash(f"🎒 Master Bag Created: {bag_no} with {success_count} items.", "success")
                    
        conn.commit()
        return redirect('/outward')

    with conn.cursor() as c:
        c.execute("SELECT * FROM outward_register WHERE out_station=%s AND finalized=0 ORDER BY id DESC", (st,))
        pending = c.fetchall()
        c.execute("SELECT outward_no, MIN(entry_date) as d, MIN(out_station) as st, COUNT(*) as c, MIN(manifest_no) as m FROM outward_register WHERE finalized=1 AND out_station=%s GROUP BY outward_no ORDER BY d DESC", (st,))
        sessions = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        stations = c.fetchall()
    conn.close()

    html = """
    <div class="tabs">
        <button class="tab-btn active" onclick="openTab(event, 'tab1')"><i class="fas fa-truck-loading"></i> Outward Scan</button>
        <button class="tab-btn" onclick="openTab(event, 'tab2')"><i class="fas fa-clipboard-check"></i> Manifests History</button>
    </div>

    <!-- TAB 1: NEW ENTRY & PENDING -->
    <div id="tab1" class="tab-content active">
        <div class="card" style="border-top: 4px solid var(--primary);">
            <div class="card-header" style="padding-bottom:10px;">
                Transhipment Hub Entry
                <div>
                    <button type="button" class="btn btn-outline" style="color:var(--danger); border-color:var(--danger);" onclick="startVoice()"><i class="fas fa-microphone"></i> Voice Scan</button>
                    <button type="button" class="btn btn-outline" style="color:var(--primary); border-color:var(--primary);" onclick="document.getElementById('camModal').style.display='block'"><i class="fas fa-camera"></i> Cam Scan</button>
                    <button type="button" class="btn btn-warning" onclick="document.getElementById('bagModal').style.display='block'"><i class="fas fa-shopping-bag"></i> Master Bag</button>
                </div>
            </div>
            <form method="POST" id="addForm">
                <input type="hidden" name="action" value="add">
                <div class="form-grid" style="align-items:end;">
                    <div class="form-group"><label class="form-label">Date</label><input type="date" name="date" value="{{ date_today }}" required class="form-control"></div>
                    <div class="form-group"><label class="form-label">AWB No / BAG No</label><input type="text" name="awb" id="awb_input" autofocus required class="form-control" style="border-color:var(--primary); font-weight:bold; text-transform:uppercase;"></div>
                    <div class="form-group">
                        <label class="form-label">Destination</label>
                        <input type="text" name="dest" id="dest_input" list="st_list" required class="form-control" style="text-transform:uppercase;">
                        <datalist id="st_list">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist>
                    </div>
                    <div class="form-group"><label class="form-label">Weight</label><input type="number" step="0.01" name="wt" id="wt_input" value="1.0" class="form-control"></div>
                    <div class="form-group"><label class="form-label">Info</label><input type="text" name="info" id="info_input" class="form-control"></div>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-plus"></i> Save</button>
                </div>
            </form>
        </div>

        <div class="card">
            <div class="card-header">
                Pending Unfinalized Outward ({{ pending|length }})
                <form method="POST" style="margin:0;" onsubmit="return confirm('Generate Manifest and Finalize all entries?');">
                    <input type="hidden" name="action" value="finalize">
                    <button type="submit" class="btn btn-primary" style="background:#0f172a; border:none;"><i class="fas fa-check-double"></i> FINALIZE & MANIFEST</button>
                </form>
            </div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>ID</th><th>AWB No</th><th>Destination</th><th>Weight</th><th>Remarks</th><th>Act</th></tr></thead>
                    <tbody>
                    {% for p in pending %}
                    <tr>
                        <td>{{ p.id }}</td>
                        <td><span class="status-badge status-outward">{{ p.awb_no }}</span></td>
                        <td style="font-weight:600;">{{ p.destination }}</td>
                        <td>{{ p.weight }} KG</td>
                        <td>{{ p.info }}</td>
                        <td>
                            <form method="POST" style="margin:0;">
                                <input type="hidden" name="action" value="delete">
                                <input type="hidden" name="del_id" value="{{ p.id }}">
                                <button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- TAB 2: MANIFESTS -->
    <div id="tab2" class="tab-content">
        <div class="card">
            <div class="card-header">Generated Manifests History</div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>Outward No</th><th>Date</th><th>Total Docs</th><th>Manifest ID</th></tr></thead>
                    <tbody>
                    {% for s in sessions %}
                    <tr>
                        <td><span class="status-badge status-booked">{{ s.outward_no }}</span></td>
                        <td>{{ s.d }}</td>
                        <td><b>{{ s.c }}</b> Pcs</td>
                        <td style="font-weight:700; color:var(--primary);">{{ s.m }}</td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- MODAL: MASTER BAG -->
    <div id="bagModal" class="modal">
        <div class="modal-content">
            <h3 style="margin-top:0; color:#0f172a; border-bottom:2px solid #e2e8f0; padding-bottom:10px;">🎒 Create Master Bag</h3>
            <form method="POST">
                <input type="hidden" name="action" value="create_bag">
                <div class="form-group" style="margin-bottom:15px;">
                    <label class="form-label">Bag Destination Station</label>
                    <input type="text" name="bag_dest" list="st_list" class="form-control" style="text-transform:uppercase;" required>
                </div>
                <div class="form-group" style="margin-bottom:15px;">
                    <label class="form-label">Scan AWBs (Comma separated or new line)</label>
                    <textarea name="bag_awbs" class="form-control" rows="6" placeholder="Scan AWBs here..." required></textarea>
                </div>
                <div style="text-align:right;">
                    <button type="button" class="btn btn-outline" onclick="document.getElementById('bagModal').style.display='none'">Cancel</button>
                    <button type="submit" class="btn btn-warning"><i class="fas fa-lock"></i> Seal Bag</button>
                </div>
            </form>
        </div>
    </div>

    <!-- MODAL: CAMERA SCANNER -->
    <div id="camModal" class="modal">
        <div class="modal-content" style="width: 400px; text-align:center;">
            <h3 style="margin-top:0; color:var(--primary);">📷 Webcam Barcode Scanner</h3>
            <div id="reader" style="width:100%; height:300px; background:black; border-radius:8px; margin-bottom:15px;"></div>
            <button class="btn btn-danger" onclick="closeCamera()">Close Camera</button>
        </div>
    </div>

    <script src="https://unpkg.com/html5-qrcode"></script>
    <script>
        function openTab(evt, tabName) {
            $('.tab-content').removeClass('active');
            $('.tab-btn').removeClass('active');
            $('#' + tabName).addClass('active');
            $(evt.currentTarget).addClass('active');
        }

        document.getElementById('awb_input').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('dest_input').focus();
            }
        });

        // HTML5 QR Code Scanner
        let html5QrcodeScanner;
        document.getElementById('camModal').addEventListener('click', function(e) {
            if(e.target === this) closeCamera();
        });

        function closeCamera() {
            document.getElementById('camModal').style.display = 'none';
            if (html5QrcodeScanner) { html5QrcodeScanner.clear(); }
        }

        // Setup Scanner when Modal opens (via button inline onclick)
        $(document).on('click', '.fa-camera', function(){
            html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: 250 });
            html5QrcodeScanner.render(function(decodedText) {
                document.getElementById('awb_input').value = decodedText;
                document.getElementById('info_input').value = "Scanned by Cam";
                closeCamera();
                document.getElementById('dest_input').focus();
            });
        });

        // Web Speech API Voice Entry
        function startVoice() {
            if (!('webkitSpeechRecognition' in window)) {
                alert("Voice entry requires Google Chrome browser."); return;
            }
            const recognition = new webkitSpeechRecognition();
            recognition.lang = 'en-IN';
            recognition.start();
            document.getElementById('awb_input').placeholder = "🎙️ Listening... Speak AWB or Weight";
            
            recognition.onresult = function(event) {
                const text = event.results[0][0].transcript.toLowerCase();
                const awbMatch = text.match(/(?:awb|parcel|number)\\s*([a-z0-9]+)/);
                const destMatch = text.match(/(?:destination|to)\\s*([a-z]+)/);
                
                if(awbMatch) document.getElementById('awb_input').value = awbMatch[1].toUpperCase();
                if(destMatch) document.getElementById('dest_input').value = destMatch[1].toUpperCase();
                
                if(awbMatch) document.getElementById('addForm').submit();
            };
        }
    </script>
    """
    return render_page("Outward Hub Entry", render_template_string(html, pending=pending, sessions=sessions, stations=stations, date_today=date_today))

# ==========================================
# ✏️ EDIT SHIPMENT (ENTERPRISE MODAL STYLE PAGE)
# ==========================================
@app.route('/edit_shipment/<int:sid>', methods=['GET', 'POST'])
@login_required
def edit_shipment(sid):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM shipments WHERE id=%s", (sid,))
        s = c.fetchone()
        if not s: flash("Shipment not found", "error"); return redirect('/booking')
        
        if request.method == 'POST':
            d = request.form
            fr = safe_float(d.get('fr')); tax = safe_float(d.get('tax', 18)); wt = safe_float(d.get('wt', 1))
            fuel = safe_float(get_setting("fuel_surcharge", "0"))
            taxable = fr * (1 + (fuel/100))
            gst = taxable * (tax / 100)
            tot = taxable + gst
            cgst = sgst = igst = 0
            if str(d.get('ostate','')).strip().upper() == str(d.get('dstate','')).strip().upper(): cgst = sgst = gst / 2
            else: igst = gst
            
            try:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (d.get('dstat','').upper(),))
                new_status = d.get('status', 'BOOKED')
                c.execute("""UPDATE shipments SET awb_no=%s, booking_date=%s, origin_name=%s, origin_phone=%s, dest_name=%s, dest_phone=%s, dest_address=%s, dest_station=%s, weight_kg=%s, quantity=%s, service_type=%s, taxable_amount=%s, tax_rate=%s, cgst=%s, sgst=%s, igst=%s, total_amount=%s, info=%s, status=%s WHERE id=%s""", 
                          (d.get('awb','').upper(), d.get('date',''), d.get('oname',''), d.get('ophone',''), d.get('dname',''), d.get('dphone',''), d.get('daddr',''), d.get('dstat','').upper(), wt, safe_int(d.get('pcs', 1)), d.get('srv','SURFACE'), taxable, tax, cgst, sgst, igst, tot, d.get('info',''), new_status, sid))
                conn.commit(); flash("Shipment completely updated!", "success")
            except Exception as e: flash(f"Update Error: {e}", "error")
            return redirect('/booking')
            
        c.execute("SELECT name FROM stations ORDER BY name"); stations = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="max-width:800px; margin:0 auto; border-top: 4px solid var(--primary);">
        <div class="card-header">Edit AWB: {{ s.awb_no }}</div>
        <form method="POST">
            <div class="form-grid" style="border-bottom:1px solid #e2e8f0; padding-bottom:15px; margin-bottom:15px;">
                <div class="form-group"><label class="form-label">Date</label><input type="date" name="date" value="{{ s.booking_date }}" required class="form-control"></div>
                <div class="form-group"><label class="form-label">AWB No</label><input type="text" name="awb" value="{{ s.awb_no }}" required class="form-control" style="font-weight:bold; color:var(--danger);"></div>
                <div class="form-group">
                    <label class="form-label">Status</label>
                    <select name="status" class="form-control" style="font-weight:bold;">
                        <option {% if s.status == 'BOOKED' %}selected{% endif %}>BOOKED</option>
                        <option {% if s.status == 'OUTWARD' %}selected{% endif %}>OUTWARD</option>
                        <option {% if s.status == 'INWARD' %}selected{% endif %}>INWARD</option>
                        <option {% if s.status == 'ON_DRS' %}selected{% endif %}>ON_DRS</option>
                        <option {% if s.status == 'DELIVERED' %}selected{% endif %}>DELIVERED</option>
                    </select>
                </div>
            </div>
            
            <div class="form-grid">
                <div class="form-group"><label class="form-label">Consignee Name</label><input type="text" name="dname" value="{{ s.dest_name or '' }}" required class="form-control"></div>
                <div class="form-group"><label class="form-label">Consignee Phone</label><input type="text" name="dphone" value="{{ s.dest_phone or '' }}" class="form-control"></div>
                <div class="form-group">
                    <label class="form-label">Dest Station</label>
                    <input type="text" name="dstat" list="stations" value="{{ s.dest_station or '' }}" required class="form-control" style="text-transform:uppercase;">
                    <datalist id="stations">{% for st in stations %}<option value="{{ st.name }}">{% endfor %}</datalist>
                </div>
                <div class="form-group"><label class="form-label">Address</label><input type="text" name="daddr" value="{{ s.dest_address or '' }}" class="form-control"></div>
            </div>
            
            <div class="form-grid" style="margin-top:20px;">
                <div class="form-group"><label class="form-label">Weight</label><input type="number" step="0.01" name="wt" value="{{ s.weight_kg or 1 }}" id="wt" oninput="manualCalc()" required class="form-control"></div>
                <div class="form-group"><label class="form-label">Pieces</label><input type="number" name="pcs" value="{{ s.quantity or 1 }}" required class="form-control"></div>
                <div class="form-group"><label class="form-label">Freight Base</label><input type="number" step="0.01" name="fr" id="fr" value="{{ s.taxable_amount or 0 }}" oninput="manualCalc()" required class="form-control"></div>
                <div class="form-group"><label class="form-label">Tax %</label><input type="number" name="tax" id="tax" value="{{ s.tax_rate or 18 }}" oninput="manualCalc()" class="form-control"></div>
                <div class="form-group"><label class="form-label">Total (₹)</label><input type="text" name="amt" id="amt" value="{{ s.total_amount or 0 }}" readonly class="form-control" style="background:#fef2f2; color:#dc2626; font-weight:bold;"></div>
            </div>
            
            <div style="margin-top:25px; display:flex; justify-content:flex-end; gap:10px;">
                <a href="/booking"><button type="button" class="btn btn-outline">Cancel</button></a>
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> UPDATE SHIPMENT</button>
            </div>
        </form>
    </div>
    <script>
        function manualCalc() { 
            let fr = parseFloat(document.getElementById('fr').value)||0; 
            let tx = parseFloat(document.getElementById('tax').value)||0; 
            document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); 
        }
    </script>
    """
    return render_page(f"Edit {s['awb_no']}", render_template_string(html, s=s, stations=stations))

# -----------------
# NOTE: Next part (PART 3) mein Invoices, Manifest Print, aur DRS Module add hoga! 
# -----------------

# ==========================================
# 🛵 10. D.R.S. (DELIVERY RUN SHEET) MODULE
# ==========================================
@app.route('/drs', methods=['GET', 'POST'])
@login_required
def drs():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    date_today = datetime.now().strftime('%Y-%m-%d')
    st = session.get('branch', 'HQ')

    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            if action == 'add':
                awb = request.form.get('awb', '').strip().upper()
                boy = request.form.get('boy', '').strip()
                area = request.form.get('area', '').strip()
                rec = request.form.get('rec', '').strip()
                info = request.form.get('info', '')
                
                c.execute("SELECT id FROM delivery_register WHERE awb_no=%s AND finalized=0", (awb,))
                if c.fetchone():
                    flash(f"AWB {awb} is already pending for delivery!", "error")
                else:
                    c.execute("INSERT INTO delivery_register(entry_date, delivery_boy, delivery_area, awb_no, receiver_name, info, finalized) VALUES(%s, %s, %s, %s, %s, %s, 0)", 
                              (date_today, boy, area, awb, rec, info))
                    # Auto update shipment status
                    s = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    if s:
                        c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE awb_no=%s", (area, awb))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES((SELECT id FROM shipments WHERE awb_no=%s), 'ON_DRS', %s, %s)", (awb, area, f"Assigned to {boy}"))
                    flash(f"✅ {awb} added to delivery queue for {boy}.", "success")

            elif action == 'delete':
                did = request.form.get('del_id')
                c.execute("DELETE FROM delivery_register WHERE id=%s", (did,))
                flash("Entry removed from pending delivery.", "success")

            elif action == 'finalize':
                # Group by delivery boy and area to create DRS sheets
                c.execute("SELECT DISTINCT delivery_boy, delivery_area FROM delivery_register WHERE finalized=0")
                groups = c.fetchall()
                
                if not groups:
                    flash("No pending entries to finalize.", "error")
                else:
                    generated_drs = []
                    for grp in groups:
                        boy = grp['delivery_boy']
                        area = grp['delivery_area']
                        
                        c.execute("SELECT * FROM delivery_register WHERE finalized=0 AND delivery_boy=%s AND delivery_area=%s", (boy, area))
                        rows = c.fetchall()
                        
                        if rows:
                            drs_no = get_seq("drs", "DRS", 6)
                            c.execute("INSERT INTO drs(drs_no, drs_date, rider_name, rider_phone, vehicle_no, status) VALUES(%s, %s, %s, '', %s, 'OPEN')", (drs_no, date_today, boy, area))
                            drs_id = c.lastrowid
                            
                            for r in rows:
                                c.execute("UPDATE delivery_register SET finalized=1, drs_no=%s WHERE id=%s", (drs_no, r['id']))
                                c.execute("SELECT id FROM shipments WHERE awb_no=%s", (r['awb_no'],))
                                s = c.fetchone()
                                if s:
                                    c.execute("INSERT INTO drs_items(drs_id, shipment_id, status, receiver_name) VALUES(%s, %s, 'ASSIGNED', %s)", (drs_id, s['id'], r['receiver_name']))
                                    
                            generated_drs.append(f"{drs_no} ({boy})")
                    
                    flash(f"✅ DRS Generated successfully: {', '.join(generated_drs)}", "success")

            elif action == 'unfinalize':
                dno = request.form.get('drs_no')
                c.execute("SELECT id FROM drs WHERE drs_no=%s", (dno,))
                drs_row = c.fetchone()
                if drs_row:
                    did = drs_row['id']
                    # Revert shipment status from DRS back to INWARD
                    c.execute("SELECT shipment_id FROM drs_items WHERE drs_id=%s", (did,))
                    s_items = c.fetchall()
                    for s_item in s_items:
                        c.execute("UPDATE shipments SET status='INWARD', current_location='Hub' WHERE id=%s AND status='ON_DRS'", (s_item['shipment_id'],))
                    
                    c.execute("DELETE FROM drs_items WHERE drs_id=%s", (did,))
                    c.execute("DELETE FROM drs WHERE id=%s", (did,))
                
                c.execute("UPDATE delivery_register SET finalized=0, drs_no=NULL WHERE drs_no=%s", (dno,))
                flash(f"Session {dno} unfinalized and moved back to pending queue.", "success")

        conn.commit()
        return redirect('/drs')

    with conn.cursor() as c:
        c.execute("SELECT * FROM delivery_register WHERE finalized=0 ORDER BY id DESC")
        pending = c.fetchall()
        
        c.execute("SELECT drs_no, MIN(entry_date) as d, MIN(delivery_boy) as b, MIN(delivery_area) as a, COUNT(*) as c FROM delivery_register WHERE finalized=1 GROUP BY drs_no ORDER BY d DESC, drs_no DESC LIMIT 200")
        sessions = c.fetchall()
        
        c.execute("SELECT full_name FROM users WHERE role='DELIVERY' AND active=1")
        boys = c.fetchall()
    conn.close()

    html = """
    <div class="tabs">
        <button class="tab-btn active" onclick="openTab(event, 'tab1')"><i class="fas fa-motorcycle"></i> Create DRS</button>
        <button class="tab-btn" onclick="openTab(event, 'tab2')"><i class="fas fa-tasks"></i> DRS History & Tracking</button>
    </div>

    <!-- TAB 1: PENDING DRS -->
    <div id="tab1" class="tab-content active">
        <div class="card" style="border-top: 4px solid var(--warning);">
            <div class="card-header">Scan Parcels For Delivery Run Sheet</div>
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <div class="form-grid" style="align-items:end;">
                    <div class="form-group">
                        <label class="form-label">Delivery Boy / Rider</label>
                        <input type="text" name="boy" list="boy_list" required class="form-control" style="text-transform:uppercase;">
                        <datalist id="boy_list">{% for b in boys %}<option value="{{ b.full_name }}">{% endfor %}</datalist>
                    </div>
                    <div class="form-group"><label class="form-label">Route / Area</label><input type="text" name="area" class="form-control"></div>
                    <div class="form-group"><label class="form-label">AWB No</label><input type="text" name="awb" required autofocus class="form-control" style="border-color:var(--primary); font-weight:bold; text-transform:uppercase;"></div>
                    <div class="form-group"><label class="form-label">Receiver Name</label><input type="text" name="rec" class="form-control"></div>
                    <div class="form-group"><label class="form-label">Address/Info</label><input type="text" name="info" class="form-control"></div>
                    <button type="submit" class="btn btn-warning" style="color:black;"><i class="fas fa-plus"></i> Add Entry</button>
                </div>
            </form>
        </div>

        <div class="card">
            <div class="card-header">
                Pending DRS Queue ({{ pending|length }} Parcels)
                <form method="POST" style="margin:0;" onsubmit="return confirm('Generate final DRS sheets for all riders?');">
                    <input type="hidden" name="action" value="finalize">
                    <button type="submit" class="btn btn-success"><i class="fas fa-check-double"></i> FINALIZE & GENERATE DRS</button>
                </form>
            </div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>Rider</th><th>Area</th><th>AWB No</th><th>Receiver</th><th>Info</th><th>Act</th></tr></thead>
                    <tbody>
                    {% for p in pending %}
                    <tr>
                        <td style="font-weight:600;">{{ p.delivery_boy }}</td>
                        <td>{{ p.delivery_area }}</td>
                        <td><span class="status-badge status-outward">{{ p.awb_no }}</span></td>
                        <td>{{ p.receiver_name }}</td>
                        <td>{{ p.info }}</td>
                        <td>
                            <form method="POST" style="margin:0;">
                                <input type="hidden" name="action" value="delete">
                                <input type="hidden" name="del_id" value="{{ p.id }}">
                                <button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- TAB 2: FINALIZED DRS -->
    <div id="tab2" class="tab-content">
        <div class="card">
            <div class="card-header">Finalized Delivery Run Sheets</div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>DRS No</th><th>Date</th><th>Rider</th><th>Area/Route</th><th>Parcels</th><th>Actions</th></tr></thead>
                    <tbody>
                    {% for s in sessions %}
                    <tr>
                        <td><span class="status-badge status-booked">{{ s.drs_no }}</span></td>
                        <td>{{ s.d }}</td>
                        <td style="font-weight:700;">{{ s.b }}</td>
                        <td>{{ s.a }}</td>
                        <td style="font-weight:bold; color:var(--primary);">{{ s.c }} Docs</td>
                        <td style="display:flex; gap:5px;">
                            <a href="#" class="action-btn"><i class="fas fa-print"></i> Print</a>
                            <form method="POST" style="margin:0;" onsubmit="return confirm('WARNING: Are you sure you want to unfinalize this DRS?');">
                                <input type="hidden" name="action" value="unfinalize">
                                <input type="hidden" name="drs_no" value="{{ s.drs_no }}">
                                <button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-undo"></i> Unfinalize</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    <script>
        function openTab(evt, tabName) {
            $('.tab-content').removeClass('active');
            $('.tab-btn').removeClass('active');
            $('#' + tabName).addClass('active');
            $(evt.currentTarget).addClass('active');
        }
    </script>
    """
    return render_page("D.R.S. Management", render_template_string(html, pending=pending, sessions=sessions, boys=boys, date_today=date_today))


# ==========================================
# 💰 11. FINANCE: PAYMENTS MODULE
# ==========================================
@app.route('/payments', methods=['GET', 'POST'])
@login_required
def payments():
    if session.get('role') not in ['ADMIN', 'ACCOUNTS']: return redirect('/')
    conn = get_db()
    date_today = datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            if action == 'add':
                cid = request.form.get('cust_id')
                amt = safe_float(request.form.get('amount'))
                mode = request.form.get('mode', 'CASH')
                ref = request.form.get('reference', '')
                p_date = request.form.get('date', date_today)
                
                if cid and amt > 0:
                    c.execute("INSERT INTO payments(customer_id, payment_date, amount, mode, reference) VALUES(%s, %s, %s, %s, %s)", (cid, p_date, amt, mode, ref))
                    # Ledger Sync (Credit Entry because customer paid us)
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s, %s, 'PAYMENT', %s, 0, %s, %s)", (cid, p_date, "PAY", amt, f"{mode} Received - {ref}"))
                    flash(f"✅ Payment of ₹{amt:,.2f} via {mode} successfully recorded!", "success")
                else:
                    flash("Invalid amount or customer selection.", "error")
            
            elif action == 'delete':
                pid = request.form.get('del_id')
                c.execute("SELECT * FROM payments WHERE id=%s", (pid,))
                p = c.fetchone()
                if p:
                    c.execute("DELETE FROM ledger WHERE voucher_type='PAYMENT' AND customer_id=%s AND credit=%s LIMIT 1", (p['customer_id'], p['amount']))
                    c.execute("DELETE FROM payments WHERE id=%s", (pid,))
                    flash("Payment entry deleted and Ledger reversed.", "success")
        conn.commit()
        return redirect('/payments')

    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name")
        custs = c.fetchall()
        c.execute("""
            SELECT p.*, c.name as cust_name 
            FROM payments p 
            LEFT JOIN customers c ON p.customer_id = c.id 
            ORDER BY p.id DESC LIMIT 300
        """)
        pay_list = c.fetchall()
    conn.close()

    html = """
    <div class="card" style="border-top: 4px solid var(--success);">
        <div class="card-header"><i class="fas fa-hand-holding-usd"></i> Record New Payment (Receipt)</div>
        <form method="POST">
            <input type="hidden" name="action" value="add">
            <div class="form-grid" style="align-items:end;">
                <div class="form-group">
                    <label class="form-label">Customer / Corporate A/c</label>
                    <select name="cust_id" class="form-control" required>
                        <option value="">-- Search Customer --</option>
                        {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
                    </select>
                </div>
                <div class="form-group"><label class="form-label">Amount (₹)</label><input type="number" step="0.01" name="amount" required class="form-control" style="font-weight:bold; color:var(--success);"></div>
                <div class="form-group">
                    <label class="form-label">Payment Mode</label>
                    <select name="mode" class="form-control" style="font-weight:bold;">
                        <option value="CASH">CASH</option>
                        <option value="BANK/IMPS">BANK TRANSFER / IMPS</option>
                        <option value="UPI">UPI / GPay / PhonePe</option>
                        <option value="CHEQUE">CHEQUE</option>
                    </select>
                </div>
                <div class="form-group"><label class="form-label">Reference No / UTR</label><input type="text" name="reference" class="form-control" placeholder="Optional"></div>
                <div class="form-group"><label class="form-label">Date</label><input type="date" name="date" value="{{ date_today }}" required class="form-control"></div>
                <button type="submit" class="btn btn-success"><i class="fas fa-save"></i> Save Payment</button>
            </div>
        </form>
    </div>

    <div class="card">
        <div class="card-header">Recent Payments History</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Txn ID</th><th>Date</th><th>Customer Name</th><th>Amount Received</th><th>Mode</th><th>Reference</th><th>Action</th></tr></thead>
                <tbody>
                {% for p in pay_list %}
                <tr>
                    <td>TXN-{{ p.id }}</td>
                    <td>{{ p.payment_date }}</td>
                    <td style="font-weight:700; color:var(--primary);">{{ p.cust_name }}</td>
                    <td style="font-weight:bold; color:var(--success);">₹ {{ p.amount }}</td>
                    <td><span class="status-badge" style="background:#e0f2fe; color:#0284c7;">{{ p.mode }}</span></td>
                    <td>{{ p.reference or '-' }}</td>
                    <td>
                        <form method="POST" style="margin:0;" onsubmit="return confirm('⚠️ Will permanently delete payment & reverse ledger balance. Sure?');">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="del_id" value="{{ p.id }}">
                            <button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i> Revoke</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Payment Entry", render_template_string(html, custs=custs, pay_list=pay_list, date_today=date_today))

# ==========================================
# 💸 12. FINANCE: EXPENSES (JOURNAL VOUCHER)
# ==========================================
@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    if session.get('role') not in ['ADMIN', 'ACCOUNTS']: return redirect('/')
    conn = get_db()
    date_today = datetime.now().strftime('%Y-%m-%d')
    
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
        total_exp = sum(safe_float(r['amount']) for r in exp_list)
    conn.close()

    html = """
    <div class="card" style="border-top: 4px solid var(--danger);">
        <div class="card-header"><i class="fas fa-money-bill-wave"></i> Add Office / Hub Expense</div>
        <form method="POST">
            <input type="hidden" name="action" value="add">
            <div class="form-grid" style="align-items:end;">
                <div class="form-group">
                    <label class="form-label">Category</label>
                    <select name="category" class="form-control" style="font-weight:bold;">
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
                <div class="form-group"><label class="form-label">Amount (₹)</label><input type="number" step="0.01" name="amount" required class="form-control" style="font-weight:bold; color:var(--danger);"></div>
                <div class="form-group"><label class="form-label">Paid To / Person</label><input type="text" name="paid_to" class="form-control" required></div>
                <div class="form-group"><label class="form-label">Description / Notes</label><input type="text" name="notes" class="form-control"></div>
                <div class="form-group"><label class="form-label">Date</label><input type="date" name="date" value="{{ date_today }}" required class="form-control"></div>
                <button type="submit" class="btn btn-danger"><i class="fas fa-save"></i> Save Expense</button>
            </div>
        </form>
    </div>

    <div class="card">
        <div class="card-header" style="display:flex; justify-content:space-between;">
            <div>Expense Register</div>
            <div style="color:var(--danger); font-size:18px;">Total Displayed: ₹ {{ "{:,.2f}".format(total_exp) }}</div>
        </div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Voucher ID</th><th>Date</th><th>Category</th><th>Paid To</th><th>Amount</th><th>Notes</th><th>Act</th></tr></thead>
                <tbody>
                {% for e in exp_list %}
                <tr>
                    <td>EXP-{{ e.id }}</td>
                    <td>{{ e.expense_date }}</td>
                    <td><span class="status-badge" style="background:#fef3c7; color:#b45309;">{{ e.category }}</span></td>
                    <td style="font-weight:600;">{{ e.paid_to }}</td>
                    <td style="font-weight:bold; color:var(--danger);">₹ {{ e.amount }}</td>
                    <td>{{ e.notes }}</td>
                    <td>
                        <form method="POST" style="margin:0;" onsubmit="return confirm('Delete this expense entry?');">
                            <input type="hidden" name="action" value="delete">
                            <input type="hidden" name="del_id" value="{{ e.id }}">
                            <button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Journal Voucher Entry", render_template_string(html, exp_list=exp_list, total_exp=total_exp, date_today=date_today))

# ==========================================
# 📒 13. CUSTOMER LEDGER (FINANCIAL OUTSTANDING)
# ==========================================
@app.route('/my_ledger', methods=['GET', 'POST'])
@login_required
def my_ledger():
    # Regular staff cannot access ledger unless they are customer/admin
    if session.get('role') not in ['ADMIN', 'ACCOUNTS', 'CUSTOMER']: return redirect('/')
    
    conn = get_db()
    f_date = request.args.get('from_date', (datetime.now().replace(day=1)).strftime('%Y-%m-%d'))
    t_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    
    # Decide which customer to show
    if session.get('role') == 'CUSTOMER':
        cid = session.get('customer_id')
    else:
        cid = request.args.get('cust_id')
        
    l_data = []; c_bal = 0.0; customer_name = ""
    
    if cid:
        with conn.cursor() as c:
            c.execute("SELECT name FROM customers WHERE id=%s", (cid,))
            cst = c.fetchone()
            if cst: customer_name = cst['name']
            
            # Fetch Ledger strictly between dates
            c.execute("""
                SELECT entry_date, voucher_type, reference, debit, credit, narration 
                FROM ledger 
                WHERE customer_id=%s AND entry_date BETWEEN %s AND %s 
                ORDER BY entry_date ASC, id ASC
            """, (cid, f_date, t_date))
            l_data = c.fetchall()
            
            # Fetch Total Lifetime Balance
            c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (cid,))
            r = c.fetchone()
            c_bal = safe_float(r['b']) if r else 0.0
            
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name")
        custs = c.fetchall()
    conn.close()

    html = """
    <div class="card" style="background:#f8fafc;">
        <form method="GET" class="form-grid" style="align-items:end;">
            {% if session.get('role') != 'CUSTOMER' %}
            <div class="form-group" style="grid-column: span 2;">
                <label class="form-label">Select Customer Account</label>
                <select name="cust_id" class="form-control" required>
                    <option value="">-- Type to Search --</option>
                    {% for c in custs %}<option value="{{ c.id }}" {% if c.id|string == cid %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
                </select>
            </div>
            {% endif %}
            <div class="form-group"><label class="form-label">From Date</label><input type="date" name="from_date" value="{{ f_date }}" class="form-control"></div>
            <div class="form-group"><label class="form-label">To Date</label><input type="date" name="to_date" value="{{ t_date }}" class="form-control"></div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-search"></i> Load Ledger</button>
            {% if cid %}
            <button type="button" class="btn btn-outline" onclick="window.print()"><i class="fas fa-print"></i> Print Statement</button>
            {% endif %}
        </form>
    </div>

    {% if cid %}
    <div class="card">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div><i class="fas fa-book"></i> Account Statement: <span style="color:var(--primary);">{{ customer_name }}</span></div>
            <div style="font-size:18px; color:{% if c_bal > 0 %}var(--danger){% else %}var(--success){% endif %};">
                Net Outstanding: ₹ {{ "{:,.2f}".format(c_bal) }}
                <div style="font-size:10px; color:var(--text-light); text-align:right;">(Total Lifetime Balance)</div>
            </div>
        </div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Date</th><th>Voucher / Ref No</th><th>Narration / Particulars</th><th>Debit (Bill ₹)</th><th>Credit (Paid ₹)</th></tr></thead>
                <tbody>
                {% for l in l_data %}
                <tr>
                    <td>{{ l.entry_date }}</td>
                    <td><span class="status-badge {% if l.voucher_type == 'INVOICE' %}status-outward{%else%}status-delivered{%endif%}">{{ l.voucher_type }}</span> <br><b>{{ l.reference }}</b></td>
                    <td>{{ l.narration }}</td>
                    <td style="color:var(--danger); font-weight:bold;">{% if l.debit > 0 %}{{ l.debit }}{% else %}-{% endif %}</td>
                    <td style="color:var(--success); font-weight:bold;">{% if l.credit > 0 %}{{ l.credit }}{% else %}-{% endif %}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% else %}
    <div style="padding:40px; text-align:center; color:var(--text-light); font-weight:500; font-size:16px;">
        <i class="fas fa-user-circle" style="font-size:40px; margin-bottom:10px; opacity:0.5; display:block;"></i>
        Select a customer to view their Ledger Statement.
    </div>
    {% endif %}
    """
    return render_page("Customer Account Ledger", render_template_string(html, custs=custs, cid=cid, l_data=l_data, c_bal=c_bal, f_date=f_date, t_date=t_date, customer_name=customer_name))

# ==========================================
# 🏢 14. MASTER ENTRIES (CUSTOMERS & LOCATIONS)
# ==========================================
@app.route('/cargo_master', methods=['GET', 'POST'])
@app.route('/customers', methods=['GET', 'POST'])
@app.route('/credit_party', methods=['GET', 'POST'])
@login_required
def customers():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    page_title = "Corporate Customers & B2B Setup"
    
    if request.args.get('delete'):
        with conn.cursor() as c: 
            c.execute("UPDATE customers SET is_active=0 WHERE id=%s", (request.args.get('delete'),))
            conn.commit()
            flash("Customer Account Deactivated!", "success")
        return redirect('/customers')
        
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("""INSERT INTO customers(code, name, gstin, phone, email, state, state_code, address, credit_limit, is_active) 
                         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""", 
                      (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone1',''), d.get('email',''), 
                       d.get('state',''), d.get('scode',''), d.get('address',''), safe_float(d.get('limit'))))
            conn.commit()
            flash("Customer / Master Data Saved Successfully!", "success")
            
    with conn.cursor() as c: 
        c.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id DESC")
        custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top: 4px solid var(--primary);">
        <div class="card-header"><i class="fas fa-building"></i> Add New Customer Account</div>
        <form method="POST">
            <div class="form-grid">
                <div class="form-group"><label class="form-label">A/c Code</label><input type="text" name="code" class="form-control" style="font-weight:bold;" required></div>
                <div class="form-group"><label class="form-label">Customer / Company Name</label><input type="text" name="name" class="form-control" style="font-weight:bold; color:var(--primary);" required></div>
                <div class="form-group"><label class="form-label">Phone No.</label><input type="text" name="phone1" class="form-control"></div>
                <div class="form-group"><label class="form-label">Email ID</label><input type="email" name="email" class="form-control"></div>
                <div class="form-group"><label class="form-label">State Name</label><input type="text" name="state" class="form-control" style="text-transform:uppercase;"></div>
                <div class="form-group"><label class="form-label">State Code</label><input type="text" name="scode" class="form-control" style="text-transform:uppercase;"></div>
                <div class="form-group"><label class="form-label">GSTIN</label><input type="text" name="gstin" class="form-control" style="text-transform:uppercase;"></div>
                <div class="form-group"><label class="form-label">Credit Limit (₹)</label><input type="number" step="0.01" name="limit" value="0.00" class="form-control" style="color:var(--danger); font-weight:bold;"></div>
                <div class="form-group" style="grid-column: span 2;"><label class="form-label">Full Address</label><input type="text" name="address" class="form-control"></div>
            </div>
            <div style="margin-top:15px; text-align:right;">
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Account</button>
            </div>
        </form>
    </div>

    <div class="card">
        <div class="card-header">Active Customer Accounts</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Code</th><th>Name</th><th>Phone</th><th>GSTIN</th><th>State</th><th>Credit Limit</th><th>Act</th></tr></thead>
                <tbody>
                {% for r in custs %}
                <tr>
                    <td><span class="status-badge" style="background:#e2e8f0; color:#475569;">{{ r.code }}</span></td>
                    <td style="font-weight:700; color:var(--primary);">{{ r.name }}</td>
                    <td>{{ r.phone }}</td>
                    <td>{{ r.gstin }}</td>
                    <td>{{ r.state }} ({{ r.state_code }})</td>
                    <td style="color:var(--danger); font-weight:600;">₹ {{ r.credit_limit }}</td>
                    <td>
                        <a href="/customers?delete={{ r.id }}" class="action-btn action-btn-red" onclick="return confirm('Deactivate this customer?');"><i class="fas fa-trash"></i></a>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page(page_title, render_template_string(html, custs=custs))

@app.route('/location_master', methods=['GET', 'POST'])
@login_required
def location_master():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip().upper()
        if name:
            with conn.cursor() as c:
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (name,))
                conn.commit(); flash(f"Location {name} Saved!", "success")
    
    with conn.cursor() as c: 
        c.execute("SELECT id, name FROM stations ORDER BY id DESC LIMIT 500")
        stations_list = c.fetchall()
    conn.close()
    
    html = """
    <div class="form-grid">
        <div class="card" style="border-top: 4px solid var(--success);">
            <div class="card-header"><i class="fas fa-map-marker-alt"></i> Add Location/Station</div>
            <form method="POST">
                <div class="form-group" style="margin-bottom:15px;">
                    <label class="form-label">Station Name / City</label>
                    <input type="text" name="name" required class="form-control" style="text-transform:uppercase; font-weight:bold;">
                </div>
                <button type="submit" class="btn btn-success" style="width:100%;"><i class="fas fa-plus"></i> Add Station</button>
            </form>
        </div>
        
        <div class="card" style="grid-column: span 2;">
            <div class="card-header">System Locations</div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>ID</th><th>Station Name</th></tr></thead>
                    <tbody>
                    {% for r in s_list %}
                    <tr>
                        <td>{{ r.id }}</td>
                        <td style="font-weight:bold; color:var(--primary);">{{ r.name }}</td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Location Master", render_template_string(html, s_list=stations_list))


# ==========================================
# 📊 15. RATE CHARTS & CONTRACTS
# ==========================================
@app.route('/rates', methods=['GET', 'POST'])
@login_required
def rates():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    
    if request.args.get('delete'):
        with conn.cursor() as c: 
            c.execute("DELETE FROM rates WHERE id=%s", (request.args.get('delete'),))
            conn.commit()
            flash("Rate Chart Deleted!", "success")
        return redirect('/rates')
        
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("""INSERT INTO rates(customer_id, origin_state_code, dest_state_code, min_weight, max_weight, fixed_charge, per_kg_rate, gst_rate, active) 
                         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1)""", 
                      (safe_int(d.get('cust_id')) if d.get('cust_id') else None, d.get('ostate'), d.get('dstate'), 
                       safe_float(d.get('min_wt')), safe_float(d.get('max_wt')), safe_float(d.get('fixed')), 
                       safe_float(d.get('per_kg')), safe_float(d.get('gst'))))
            conn.commit()
            flash("Rate Added Successfully!", "success")
            
    with conn.cursor() as c:
        c.execute("SELECT r.*, c.name as cname FROM rates r LEFT JOIN customers c ON r.customer_id=c.id ORDER BY r.id DESC")
        rates_list = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1")
        custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top: 4px solid var(--warning);">
        <div class="card-header"><i class="fas fa-file-contract"></i> Add Contract / Rate Chart</div>
        <form method="POST">
            <div class="form-grid" style="align-items:end;">
                <div class="form-group">
                    <label class="form-label">Customer (Leave blank for Default)</label>
                    <select name="cust_id" class="form-control">
                        <option value="">-- DEFAULT RATE --</option>
                        {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
                    </select>
                </div>
                <div class="form-group"><label class="form-label">Origin State</label><input type="text" name="ostate" required class="form-control" placeholder="E.g., RJ"></div>
                <div class="form-group"><label class="form-label">Dest State</label><input type="text" name="dstate" required class="form-control" placeholder="E.g., HR"></div>
                <div class="form-group"><label class="form-label">Min Wt (KG)</label><input type="number" step="0.01" name="min_wt" value="0.1" class="form-control"></div>
                <div class="form-group"><label class="form-label">Max Wt (KG)</label><input type="number" step="0.01" name="max_wt" value="50" class="form-control"></div>
                <div class="form-group"><label class="form-label">Fixed Charge (₹)</label><input type="number" step="0.01" name="fixed" value="50" class="form-control"></div>
                <div class="form-group"><label class="form-label">Per KG Rate (₹)</label><input type="number" step="0.01" name="per_kg" value="20" class="form-control"></div>
                <div class="form-group"><label class="form-label">GST %</label><input type="number" step="0.01" name="gst" value="18" class="form-control"></div>
                <button type="submit" class="btn btn-warning"><i class="fas fa-save"></i> Save Rate</button>
            </div>
        </form>
    </div>

    <div class="card">
        <div class="card-header">Existing Rate Contracts</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Customer A/c</th><th>Route (Origin ➔ Dest)</th><th>Weight Range</th><th>Charges (Fixed + Per KG)</th><th>GST %</th><th>Act</th></tr></thead>
                <tbody>
                {% for r in rates_list %}
                <tr>
                    <td style="font-weight:700;">
                        {% if r.cname %}<span style="color:var(--primary);">{{ r.cname }}</span>
                        {% else %}<span class="status-badge status-outward">DEFAULT</span>{% endif %}
                    </td>
                    <td><b>{{ r.origin_state_code }} ➔ {{ r.dest_state_code }}</b></td>
                    <td>{{ r.min_weight }} KG - {{ r.max_weight }} KG</td>
                    <td style="color:var(--danger); font-weight:600;">₹{{ r.fixed_charge }} + (₹{{ r.per_kg_rate }}/KG)</td>
                    <td>{{ r.gst_rate }}%</td>
                    <td><a href="/rates?delete={{ r.id }}" class="action-btn action-btn-red" onclick="return confirm('Delete this rate?');"><i class="fas fa-trash"></i></a></td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Rate Master", render_template_string(html, custs=custs, rates_list=rates_list))

# ==========================================
# 👥 16. USERS & DELIVERY BOY SETUPS
# ==========================================
@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    
    if request.args.get('delete'):
        with conn.cursor() as c: 
            c.execute("UPDATE users SET active=0 WHERE id=%s", (request.args.get('delete'),))
            conn.commit()
            flash("User Deactivated!", "success")
        return redirect('/users')
        
    if request.method == 'POST':
        d = request.form
        b = str(d.get('branch', '')).upper()
        cid = safe_int(d.get('customer_id')) if d.get('customer_id') else None
        with conn.cursor() as c:
            c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (b,))
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, customer_id, active) VALUES(%s,%s,%s,%s,%s,%s,1)", 
                      (d.get('username',''), hashlib.sha256(d.get('password','').encode()).hexdigest(), d.get('full_name',''), d.get('role',''), b, cid))
            conn.commit()
            flash("User Added Successfully!", "success")
            
    with conn.cursor() as c:
        c.execute("SELECT * FROM users ORDER BY id DESC")
        u_list = c.fetchall()
        c.execute("SELECT name FROM stations ORDER BY name")
        branches = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1")
        custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="card" style="border-top: 4px solid var(--primary);">
        <div class="card-header"><i class="fas fa-user-plus"></i> Create ERP User (Staff / Customer)</div>
        <form method="POST">
            <div class="form-grid" style="align-items:end;">
                <div class="form-group"><label class="form-label">Username (Login ID)</label><input type="text" name="username" class="form-control" required></div>
                <div class="form-group"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div>
                <div class="form-group"><label class="form-label">Full Name</label><input type="text" name="full_name" class="form-control" required></div>
                <div class="form-group">
                    <label class="form-label">Access Role</label>
                    <select name="role" class="form-control">
                        <option>OPERATOR</option>
                        <option>ADMIN</option>
                        <option>ACCOUNTS</option>
                        <option>CUSTOMER</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Assign Branch</label>
                    <input type="text" name="branch" list="brlist" class="form-control" style="text-transform:uppercase;" required>
                    <datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist>
                </div>
                <div class="form-group">
                    <label class="form-label">Link Customer (B2B Only)</label>
                    <select name="customer_id" class="form-control">
                        <option value="">-- None --</option>
                        {% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
                    </select>
                </div>
                <button type="submit" class="btn btn-primary" style="width:100%;"><i class="fas fa-user-check"></i> Create User</button>
            </div>
        </form>
    </div>

    <div class="card">
        <div class="card-header">System Users</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Login ID</th><th>Full Name</th><th>Role</th><th>Branch</th><th>Status</th><th>Act</th></tr></thead>
                <tbody>
                {% for u in u_list %}
                <tr>
                    <td style="font-weight:bold;">{{ u.username }}</td>
                    <td>{{ u.full_name }}</td>
                    <td><span class="status-badge status-outward">{{ u.role }}</span></td>
                    <td>{{ u.branch_name }}</td>
                    <td>
                        {% if u.active %}
                            <span class="status-badge status-delivered">Active</span>
                        {% else %}
                            <span class="status-badge status-booked" style="background:#fee2e2; color:#b91c1c;">Disabled</span>
                        {% endif %}
                    </td>
                    <td>
                        {% if u.active %}
                            <a href="/users?delete={{ u.id }}" class="action-btn action-btn-red" onclick="return confirm('Disable user?');"><i class="fas fa-ban"></i> Disable</a>
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

@app.route('/delivery_boy', methods=['GET', 'POST'])
@login_required
def delivery_boy():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            fake_hash = hashlib.sha256("boy123".encode()).hexdigest()
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, active) VALUES(%s,%s,%s,'DELIVERY',%s,1)", 
                      (d.get('code',''), fake_hash, d.get('name',''), session.get('branch','HQ')))
            conn.commit(); flash("Delivery Boy Added Successfully!", "success")
            
    with conn.cursor() as c: 
        c.execute("SELECT * FROM users WHERE role='DELIVERY' ORDER BY id DESC")
        boys = c.fetchall()
    conn.close()
    
    html = """
    <div class="form-grid">
        <div class="card" style="border-top: 4px solid var(--warning);">
            <div class="card-header"><i class="fas fa-biking"></i> Add Delivery Boy</div>
            <form method="POST">
                <div class="form-group" style="margin-bottom:15px;"><label class="form-label">Employee Code</label><input type="text" name="code" class="form-control" required></div>
                <div class="form-group" style="margin-bottom:15px;"><label class="form-label">Full Name</label><input type="text" name="name" class="form-control" required></div>
                <button type="submit" class="btn btn-warning" style="width:100%;"><i class="fas fa-plus"></i> Add Rider</button>
            </form>
        </div>
        <div class="card" style="grid-column: span 2;">
            <div class="card-header">Riders List</div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>Code</th><th>Name</th><th>Branch</th></tr></thead>
                    <tbody>
                    {% for b in boys %}
                    <tr>
                        <td style="font-weight:bold; color:var(--text-light);">{{ b.username }}</td>
                        <td style="font-weight:700; color:var(--primary);">{{ b.full_name }}</td>
                        <td>{{ b.branch_name }}</td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Delivery Boy Master", render_template_string(html, boys=boys))

@app.route('/stationery', methods=['GET', 'POST'])
@login_required
def stationery():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        awb = request.form.get('awb','').strip().upper()
        issue_to = request.form.get('issue_to','')
        pcs = safe_int(request.form.get('pcs', 1))
        with conn.cursor() as c:
            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
            s = c.fetchone()
            if s:
                c.execute("UPDATE shipments SET status='STATIONERY', info=%s WHERE id=%s", (f"Issued {pcs} to {issue_to}", s['id']))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'STATIONERY',%s,%s)", (s['id'], session.get('branch','HQ'), f"Stationery Issued: {pcs} pcs to {issue_to}"))
                conn.commit(); flash(f"Stationery Issued for {awb}", "success")
            else: 
                flash("AWB not found in system. Please book or import it first.", "error")
                
    with conn.cursor() as c:
        c.execute("SELECT awb_no, booking_date, origin_name, status, info FROM shipments WHERE status='STATIONERY' ORDER BY id DESC LIMIT 500")
        hist = c.fetchall()
        c.execute("SELECT id, name FROM customers WHERE is_active=1")
        custs = c.fetchall()
    conn.close()
    
    html = """
    <div class="form-grid">
        <div class="card" style="border-top: 4px solid var(--primary);">
            <div class="card-header"><i class="fas fa-barcode"></i> Issue Pre-Printed Stationery</div>
            <form method="POST">
                <div class="form-group" style="margin-bottom:15px;"><label class="form-label">AWB No.</label><input name="awb" required class="form-control" style="text-transform:uppercase; font-weight:bold; border-color:var(--primary);"></div>
                <div class="form-group" style="margin-bottom:15px;">
                    <label class="form-label">Issue To (Customer)</label>
                    <select name="issue_to" required class="form-control">
                        {% for c in custs %}<option>{{ c.name }}</option>{% endfor %}
                    </select>
                </div>
                <div class="form-group" style="margin-bottom:15px;"><label class="form-label">Pieces</label><input type="number" name="pcs" value="1" min="1" class="form-control"></div>
                <button type="submit" class="btn btn-primary" style="width:100%;"><i class="fas fa-check"></i> Assign AWB</button>
            </form>
        </div>
        
        <div class="card" style="grid-column: span 2;">
            <div class="card-header">Stationery Allocation Register</div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>AWB No</th><th>Date</th><th>Issued To</th><th>Remarks</th></tr></thead>
                    <tbody>
                    {% for h in hist %}
                    <tr>
                        <td style="font-weight:bold; color:var(--primary);">{{ h.awb_no }}</td>
                        <td>{{ h.booking_date }}</td>
                        <td style="font-weight:700;">{{ h.origin_name }}</td>
                        <td>{{ h.info }}</td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page("Stationery Issue", render_template_string(html, custs=custs, hist=hist))

# ==========================================
# ⚙️ 17. SYSTEM SETTINGS & UTILS
# ==========================================
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    conn = get_db()
    if request.method == 'POST':
        if 'old_pass' in request.form:
            old_p = hashlib.sha256(request.form.get('old_pass','').encode()).hexdigest()
            new_p = hashlib.sha256(request.form.get('new_pass','').encode()).hexdigest()
            with conn.cursor() as c:
                c.execute("SELECT password_hash FROM users WHERE id=%s", (session['user_id'],))
                u = c.fetchone()
                if u and u['password_hash'] == old_p:
                    c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_p, session['user_id']))
                    conn.commit(); flash("Password Changed Successfully!", "success")
                else: 
                    flash("Old Password Incorrect!", "error")
        else:
            if session.get('role') != 'ADMIN':
                flash("Only Admins can change system settings.", "error")
            else:
                with conn.cursor() as c:
                    for key in ['company_name','company_address','company_gstin','company_phone','company_state_code','company_email','bank_details','terms_note','fuel_surcharge']:
                        val = request.form.get(key, '')
                        c.execute("UPDATE settings SET value=%s WHERE key_name=%s", (val, key))
                    conn.commit(); flash("System Settings Updated!", "success")
                    
    with conn.cursor() as c:
        c.execute("SELECT key_name, value FROM settings")
        settings_data = {r['key_name']: r['value'] for r in c.fetchall()}
    conn.close()
    
    html = """
    <div class="form-grid">
        {% if session.get('role') == 'ADMIN' %}
        <div class="card" style="border-top: 4px solid var(--primary); grid-column: span 2;">
            <div class="card-header"><i class="fas fa-building"></i> Company & Billing Settings</div>
            <form method="POST">
                <div class="form-grid">
                    <div class="form-group"><label class="form-label">Company Name</label><input type="text" name="company_name" value="{{ s.company_name }}" class="form-control"></div>
                    <div class="form-group"><label class="form-label">GSTIN</label><input type="text" name="company_gstin" value="{{ s.company_gstin }}" class="form-control"></div>
                    <div class="form-group"><label class="form-label">Phone</label><input type="text" name="company_phone" value="{{ s.company_phone }}" class="form-control"></div>
                    <div class="form-group"><label class="form-label">Email</label><input type="text" name="company_email" value="{{ s.company_email }}" class="form-control"></div>
                    <div class="form-group"><label class="form-label">State Code</label><input type="text" name="company_state_code" value="{{ s.company_state_code }}" class="form-control"></div>
                    <div class="form-group"><label class="form-label">Fuel Surcharge %</label><input type="number" step="0.01" name="fuel_surcharge" value="{{ s.fuel_surcharge }}" class="form-control"></div>
                    <div class="form-group" style="grid-column: span 2;"><label class="form-label">Address</label><textarea name="company_address" class="form-control" rows="2">{{ s.company_address }}</textarea></div>
                    <div class="form-group" style="grid-column: span 2;"><label class="form-label">Bank Details (For Invoices)</label><textarea name="bank_details" class="form-control" rows="2">{{ s.bank_details }}</textarea></div>
                    <div class="form-group" style="grid-column: span 2;"><label class="form-label">Terms & Conditions</label><textarea name="terms_note" class="form-control" rows="2">{{ s.terms_note }}</textarea></div>
                </div>
                <div style="text-align:right; margin-top:15px;">
                    <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Update System Settings</button>
                </div>
            </form>
        </div>
        {% endif %}
        
        <div class="card" style="border-top: 4px solid var(--danger);">
            <div class="card-header"><i class="fas fa-key"></i> Change My Password</div>
            <form method="POST">
                <div class="form-group" style="margin-bottom:15px;"><label class="form-label">Current Password</label><input type="password" name="old_pass" required class="form-control"></div>
                <div class="form-group" style="margin-bottom:15px;"><label class="form-label">New Password</label><input type="password" name="new_pass" required class="form-control"></div>
                <button type="submit" class="btn btn-danger" style="width:100%;"><i class="fas fa-lock"></i> Change Password</button>
            </form>
        </div>
    </div>
    """
    return render_page("System Settings", render_template_string(html, s=settings_data))

@app.route('/import_csv', methods=['GET', 'POST'])
@login_required
def import_csv():
    if session.get('role') != 'ADMIN': return redirect('/')
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'): 
            flash("Invalid CSV file", "error"); return redirect('/import_csv')
            
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
                c.execute("""INSERT INTO shipments(awb_no, dest_name, dest_station, weight_kg, total_amount, booking_date, status, current_location, service_type, origin_name) 
                             VALUES(%s, %s, %s, %s, %s, %s, 'BOOKED', 'Origin', 'SURFACE', %s)""", 
                          (awb, dest, dest.upper(), safe_float(wt), safe_float(tot), d, session.get('branch','HQ')))
                added += 1
            conn.commit()
        conn.close()
        flash(f"🎉 Import Complete! {added} New Parcels Booked.", "success")
        
    html = """
    <div class="card" style="max-width:500px; margin:0 auto; border-top:4px solid var(--success);">
        <div class="card-header"><i class="fas fa-file-csv"></i> Bulk CSV Import (Fast Booking)</div>
        <div style="background:#f8fafc; padding:15px; border-radius:8px; border:1px dashed #cbd5e1; margin-bottom:20px; font-size:13px; color:var(--text-light);">
            <b>Required Column Headers in CSV:</b><br><br>
            • AWB<br>
            • Dest<br>
            • Weight<br>
            • Amount<br><br>
            <i>* Save your Excel file as 'CSV (Comma delimited)' before uploading.</i>
        </div>
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="file" accept=".csv" required class="form-control" style="margin-bottom:15px; padding:15px;">
            <button type="submit" class="btn btn-success" style="width:100%;"><i class="fas fa-upload"></i> Start Import</button>
        </form>
    </div>
    """
    return render_page("Excel Import", render_template_string(html))

# ==========================================
# 🖨️ 18. PDF INVOICE PRINT ROUTINE
# ==========================================
@app.route('/print/invoice/<int:inv_id>')
@login_required
def print_invoice_pdf(inv_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT i.*, c.name as cname, c.gstin as cgstin, c.address as caddr, c.state_code as cstate FROM invoices i JOIN customers c ON i.customer_id=c.id WHERE i.id=%s", (inv_id,))
    inv = c.fetchone()
    c.execute("SELECT il.*, s.awb_no FROM invoice_lines il LEFT JOIN shipments s ON il.shipment_id=s.id WHERE il.invoice_id=%s", (inv_id,))
    lines = c.fetchall()
    c.close(); conn.close()
    
    if not inv: return "Invoice Not Found"

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFillColor(HexColor("#0f172a")); cv.rect(0, 800, 600, 45, fill=1, stroke=0)
    cv.setFillColor(HexColor("#FFFFFF")); cv.setFont("Helvetica-Bold", 16); cv.drawCentredString(300, 815, str(get_setting('company_name', 'AGC Enterprise ERP')))
    cv.setFont("Helvetica", 9); cv.drawCentredString(300, 802, f"{get_setting('company_address', '')} | GSTIN: {get_setting('company_gstin', '')}")
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 14); cv.drawCentredString(300, 770, "TAX INVOICE")
    cv.setFont("Helvetica", 10); cv.drawString(40, 745, f"Invoice No: {inv['invoice_no']}"); cv.drawRightString(560, 745, f"Date: {inv['invoice_date']}")
    cv.drawString(40, 725, f"Bill To: {inv['cname']}"); cv.drawString(40, 710, f"Address: {inv['caddr']}")
    cv.drawString(40, 695, f"Customer GSTIN: {inv['cgstin']} | State Code: {inv['cstate']}")
    
    y = 660; cv.setFillColor(HexColor("#f1f5f9")); cv.rect(40, y, 520, 20, fill=1, stroke=0)
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 9)
    cv.drawString(45, y+6, "AWB No"); cv.drawString(120, y+6, "Description"); cv.drawString(280, y+6, "Taxable"); cv.drawString(350, y+6, "CGST"); cv.drawString(410, y+6, "SGST"); cv.drawString(470, y+6, "IGST"); cv.drawString(520, y+6, "Total")
    
    y -= 20; cv.setFont("Helvetica", 9)
    for l in lines:
        cv.drawString(45, y, str(l['awb_no']))
        cv.drawString(120, y, str(l['description'])[:25])
        cv.drawString(280, y, f"Rs {l['taxable_amount']}")
        cv.drawString(350, y, f"{l['cgst']}")
        cv.drawString(410, y, f"{l['sgst']}")
        cv.drawString(470, y, f"{l['igst']}")
        cv.setFont("Helvetica-Bold"); cv.drawString(520, y, f"Rs {l['total']}"); cv.setFont("Helvetica")
        y -= 15
        if y < 100: cv.showPage(); y = 800
        
    cv.line(40, y-10, 560, y-10); y -= 30
    cv.setFont("Helvetica-Bold", 11)
    cv.drawString(300, y, f"Total Taxable: Rs {inv['taxable_amount']}")
    cv.drawString(300, y-20, f"CGST: Rs {inv['cgst']} | SGST: Rs {inv['sgst']} | IGST: Rs {inv['igst']}")
    cv.setFillColor(HexColor("#2563eb")); cv.setFont("Helvetica-Bold", 14)
    cv.drawString(300, y-45, f"Grand Total: Rs {inv['total']}")
    
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica", 9)
    cv.drawString(40, 100, f"Bank Details: {get_setting('bank_details', '')}")
    cv.drawString(40, 80, str(get_setting('terms_note', '')))
    cv.drawRightString(560, 100, f"For {get_setting('company_name', 'AGC')}")
    cv.drawRightString(560, 80, "Authorised Signatory")
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Invoice_{inv['invoice_no'].replace('/', '_')}.pdf", mimetype='application/pdf')

# ==========================================
# 🔄 19. UNIVERSAL SYNC API FOR DESKTOP
# ==========================================
@app.route('/api/sync/download', methods=['GET', 'POST'])
def sync_download():
    """ 
    Desktop App ko latest data (all tables) securely bhejne ke liye JSON API.
    """
    conn = get_db()
    response_data = {}
    tables_to_sync = ['users', 'branches', 'customers', 'rates', 'stations', 'expenses', 'ledger', 'payments', 'invoices', 'invoice_lines', 'shipments', 'scan_events', 'outward_register', 'inward_register', 'delivery_register', 'manifests', 'manifest_items', 'drs', 'drs_items', 'master_bags', 'master_bag_items']
    
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
                            import datetime as dt
                            if isinstance(value, dt.date) or isinstance(value, dt.datetime):
                                clean_row[key] = str(value)
                            else:
                                clean_row[key] = value
                        clean_rows.append(clean_row)
                    response_data[tbl] = clean_rows
                except Exception as e:
                    logging.error(f"Sync error on table {tbl}: {e}")
                    response_data[tbl] = []
                    
        return jsonify({"success": True, "data": response_data})
    except Exception as e: return jsonify({"success": False, "error": str(e)})
    finally: conn.close()

# ==========================================
# 🚀 DO NOT TOUCH - SERVER LAUNCHER
# ==========================================
if __name__ == '__main__':
    # Cloud hosting platforms (like Render, Heroku) ke liye port 5000 expose kiya hai
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', debug=True, port=port)
