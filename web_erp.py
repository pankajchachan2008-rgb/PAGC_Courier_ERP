from flask import Flask, request, session, redirect, url_for, render_template_string, flash, send_file, jsonify
import pymysql, configparser, hashlib, io, os, csv, logging, json
import threading, requests
from functools import wraps
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import inch, mm
from reportlab.graphics.barcode import code128
from reportlab.lib.colors import HexColor
from werkzeug.exceptions import HTTPException

# ==========================================
# 🛡️ 1. SYSTEM SETUP, CONFIG & DATABASE HEALER
# ==========================================
logging.basicConfig(filename='agc_enterprise.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'agc_enterprise_cloud_v4_secure_master')

if not os.path.exists('db_config.ini'):
    config = configparser.ConfigParser()
    config['CLOUD_DB'] = {'host': 'localhost', 'port': '3306', 'user': 'root', 'password': '', 'database': 'agc_erp'}
    with open('db_config.ini', 'w') as configfile: config.write(configfile)

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
        else: return pymysql.connect(host='localhost', port=3306, user='root', password='', database='agc_erp', cursorclass=pymysql.cursors.DictCursor)
    except Exception as e:
        logging.error(f"DB Connection Failed: {e}"); raise Exception("Database connection failed. Check db_config.ini")

def auto_heal_db():
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
            
            defs = {"company_name": "AGC ENTERPRISE", "company_address": "Head Office: Nohar", "company_gstin": "08ADQPC7585D1Z9", "company_phone": "+91 7357073316", "company_state_code": "08", "company_website": "https://agcgroup.in", "terms_note": "Liability limited to declared value only.", "bank_details": "Bank: HDFC | A/C: 123456789 | IFSC: HDFC0001", "fuel_surcharge": "0"}
            for k, v in defs.items(): c.execute("INSERT IGNORE INTO settings(key_name, value) VALUES(%s, %s)", (k, v))
            
            c.execute("SELECT id FROM users WHERE username='admin'")
            if not c.fetchone(): c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, active) VALUES('admin', %s, 'Super Admin', 'ADMIN', 'HQ', 1)", (hashlib.sha256("admin123".encode()).hexdigest(),))
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
            --bg-color: #f1f5f9; --sidebar-bg: #0f172a; --sidebar-hover: #1e293b;
            --primary: #2563eb; --primary-hover: #1d4ed8; --success: #10b981;
            --danger: #ef4444; --warning: #f59e0b; --text-dark: #1e293b;
            --text-light: #64748b; --white: #ffffff; --border: #e2e8f0;
        }
        body { margin: 0; padding: 0; font-family: 'Inter', sans-serif; background-color: var(--bg-color); color: var(--text-dark); display: flex; height: 100vh; overflow: hidden; }
        a { text-decoration: none; color: inherit; }
        
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

        .main-wrapper { flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
        .topbar { height: 65px; background-color: var(--white); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; padding: 0 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .page-title { font-size: 20px; font-weight: 700; color: var(--text-dark); margin: 0; text-transform: uppercase;}
        .topbar-right { display: flex; align-items: center; gap: 20px; }
        .branch-badge { background: #e0f2fe; color: #0284c7; padding: 6px 12px; border-radius: 20px; font-weight: 700; font-size: 12px; border: 1px solid #bae6fd; }
        .user-profile { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 14px; color: var(--text-dark); }
        .logout-btn { background: #fee2e2; color: #dc2626; border: none; padding: 8px 12px; border-radius: 6px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .logout-btn:hover { background: #fca5a5; }

        .content { flex: 1; padding: 25px; overflow-y: auto; background-color: var(--bg-color); }
        
        .card { background: var(--white); border-radius: 12px; border: 1px solid var(--border); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); padding: 20px; margin-bottom: 20px; }
        .card-header { font-size: 16px; font-weight: 700; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 15px; color: var(--sidebar-bg); display: flex; justify-content: space-between; align-items: center; text-transform:uppercase;}
        
        .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
        .form-group { display: flex; flex-direction: column; gap: 6px; }
        .form-label { font-size: 12px; font-weight: 600; color: var(--text-light); text-transform: uppercase; letter-spacing: 0.5px; }
        .form-control { border: 1px solid #cbd5e1; border-radius: 8px; padding: 10px 12px; font-size: 14px; font-family: 'Inter', sans-serif; transition: 0.2s; outline: none; background: #f8fafc; color: var(--text-dark); }
        .form-control:focus { border-color: var(--primary); background: var(--white); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }
        
        .btn { padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; display: inline-flex; align-items: center; gap: 6px; transition: 0.2s; text-transform: uppercase; letter-spacing: 0.5px; }
        .btn-primary { background: var(--primary); color: var(--white); }
        .btn-primary:hover { background: var(--primary-hover); transform: translateY(-1px); }
        .btn-success { background: var(--success); color: var(--white); }
        .btn-danger { background: var(--danger); color: var(--white); }
        .btn-warning { background: var(--warning); color: #000; }
        .btn-outline { background: var(--white); color: var(--text-dark); border: 1px solid #cbd5e1; }
        .btn-outline:hover { background: #f1f5f9; }
        
        /* 📊 DATATABLES */
        .table-responsive { overflow-x: auto; width: 100%; }
        table.dataTable { border-collapse: collapse !important; width: 100% !important; margin-top: 15px !important; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }
        table.dataTable thead th { background-color: #f8fafc !important; color: #475569 !important; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; padding: 12px 15px !important; border-bottom: 2px solid #e2e8f0 !important; font-weight: 700; border-right: none; }
        table.dataTable tbody td { padding: 12px 15px !important; border-bottom: 1px solid #e2e8f0 !important; color: #1e293b; font-size: 13px; font-weight: 500; vertical-align: middle; }
        table.dataTable tbody tr:hover { background-color: #f1f5f9 !important; cursor:pointer;}
        .dataTables_wrapper .dataTables_filter input { border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 12px; margin-left: 8px; outline: none; }
        .dataTables_wrapper .dataTables_filter input:focus { border-color: var(--primary); }
        .dataTables_wrapper .dataTables_paginate .paginate_button.current { background: var(--primary) !important; color: white !important; border: none !important; border-radius: 6px; font-weight: bold; }
        .dataTables_wrapper .dataTables_paginate .paginate_button { border-radius: 6px; padding: 5px 12px; border: 1px solid transparent; }
        .dataTables_wrapper .dataTables_paginate .paginate_button:hover { background: #e2e8f0 !important; color: black !important; border: 1px solid #cbd5e1 !important; }

        .toast-msg { padding: 12px 20px; border-radius: 8px; margin-bottom: 20px; font-weight: 600; display: flex; align-items: center; gap: 10px; font-size: 14px; animation: slideIn 0.3s ease; }
        .toast-success { background-color: #d1fae5; color: #065f46; border: 1px solid #10b981; }
        .toast-error { background-color: #fee2e2; color: #991b1b; border: 1px solid #ef4444; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }

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
    <div class="sidebar">
        <div class="brand"><i class="fas fa-cube" style="color: #f59e0b;"></i> AGC ERP</div>
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
                        <li><a href="/delivery_boy" class="sub-link">Delivery Boys</a></li>
                        <li><a href="/import_csv" class="sub-link">Excel Import</a></li>
                        <li><a href="/settings" class="sub-link">Settings</a></li>
                    </ul>
                </li>
            {% endif %}
            <li class="nav-item"><a href="/track" target="_blank" class="nav-link" style="color:#f59e0b;"><div style="display:flex;align-items:center;"><i class="fas fa-search-location icon"></i> Live Tracking</div></a></li>
        </ul>
    </div>

    <div class="main-wrapper">
        <div class="topbar">
            <h2 class="page-title">{{ title }}</h2>
            <div class="topbar-right">
                <div class="branch-badge"><i class="fas fa-map-marker-alt"></i> {{ session.branch | default('HQ') }}</div>
                <div class="user-profile"><i class="fas fa-user-circle" style="font-size: 24px; color:#94a3b8;"></i> {{ session.full_name | default('Admin') }}</div>
                <a href="/logout"><button class="logout-btn"><i class="fas fa-power-off"></i> Logout</button></a>
            </div>
        </div>
        <div class="content">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}{% for category, message in messages %}
                    <div class="toast-msg toast-{{ category }}"><i class="fas {% if category == 'success' %}fa-check-circle{% else %}fa-exclamation-circle{% endif %}"></i> {{ message }}</div>
                {% endfor %}{% endif %}
            {% endwith %}
            {{ content | safe }}
        </div>
    </div>

    <script>
        function toggleMenu(elem) { $(elem).toggleClass('open'); $(elem).find('.nav-link').toggleClass('active'); }
        $(document).ready(function() {
            if ($('.datatable').length) {
                $('.datatable').DataTable({
                    "pageLength": 100, "order": [], 
                    "language": { "search": "<b><i class='fas fa-search'></i> Quick Find:</b>", "lengthMenu": "Show _MENU_ rows" }
                });
            }
        });
        function openModal(id) { document.getElementById(id).style.display = 'block'; }
        function closeModal(id) { document.getElementById(id).style.display = 'none'; }
    </script>
</body>
</html>
"""

def render_page(title, content):
    return render_template_string(ENTERPRISE_BASE_HTML, title=title, content=content)

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
        .error { color: #dc2626; background: #fee2e2; padding: 10px; border-radius: 6px; font-size: 13px; font-weight: bold; margin-bottom: 15px;}
    </style>
    <div class="login-box">
        <h1><i class="fas fa-cube" style="color:#f59e0b;"></i> AGC ERP</h1>
        <p>Enterprise Cloud Portal</p>
        {% with messages = get_flashed_messages() %}{% if messages %}<div class="error">{{ messages[0] }}</div>{% endif %}{% endwith %}
        <form method="POST">
            <div class="input-group"><label>User ID</label><input name="username" required autocomplete="off" placeholder="Enter your username"></div>
            <div class="input-group"><label>Password</label><input type="password" name="password" required placeholder="Enter your password"></div>
            <button type="submit" class="login-btn">Secure Login <i class="fas fa-arrow-right" style="margin-left:5px;"></i></button>
        </form>
    </div>
    """
    return render_template_string(html)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

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

def fetch_network_tracking(network_name, network_awb):
    external_events = []
    network = str(network_name).strip().upper()
    try:
        if not external_events:
            external_events.append({
                'scan_type': 'NETWORK DISPATCH',
                'location': f'Forwarded to {network}',
                'f_date': datetime.now().strftime('%d-%b-%Y %I:%M %p'),
                'remarks': f"Partner AWB / Tracking ID: {network_awb} (API pending)"
            })
    except Exception as e: logging.error(f"External API Error for {network}: {e}")
    return external_events

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
        <div class="header"><h1>AGC Courier Tracking</h1><p style="color: #64748b;">Track your shipments in real-time</p></div>
        <form method="GET" action="/track" class="search-box"><input type="text" name="awb" class="search-input" placeholder="Enter AWB Number..." value="{{ awb }}" autofocus><button type="submit" class="search-btn">TRACK</button></form>
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

@app.route('/api/calc_rate', methods=['POST'])
@login_required
def api_calc_rate():
    d = request.json
    cid = safe_int(d.get('cust_id')) if d.get('cust_id') else None
    ost = d.get('ostate', ''); dst = d.get('dstate', '')
    wt = safe_float(d.get('wt')); fr = safe_float(d.get('fr')); tx = safe_float(d.get('tax'))
    if fr == 0.0:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM rates WHERE customer_id=%s AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (cid, ost, dst, wt))
        r = c.fetchone()
        if not r: 
            c.execute("SELECT * FROM rates WHERE customer_id IS NULL AND origin_state_code=%s AND dest_state_code=%s AND %s BETWEEN min_weight AND max_weight ORDER BY id DESC LIMIT 1", (ost, dst, wt))
            r = c.fetchone()
        c.close(); conn.close()
        if r: 
            fr = safe_float(r['fixed_charge']) + (wt * safe_float(r['per_kg_rate'])); tx = safe_float(r['gst_rate'])
        else: fr = wt * 25.0
    fuel = safe_float(get_setting("fuel_surcharge", "0"))
    taxable = fr * (1 + (fuel/100)); gst_amt = taxable * (tx/100); total = taxable + gst_amt
    return jsonify({"freight": round(fr,2), "taxable": round(taxable,2), "gst": round(gst_amt,2), "total": round(total,2), "tax_rate": tx})

@app.route('/api/get_awb_info/<awb>', methods=['GET'])
@login_required
def api_get_awb_info(awb):
    conn = get_db()
    with conn.cursor() as c: c.execute("SELECT dest_station, dest_name, weight_kg FROM shipments WHERE awb_no=%s", (awb.upper(),)); s = c.fetchone()
    conn.close()
    if s: return jsonify({"success": True, "dest_station": s['dest_station'], "dest_name": s['dest_name'], "weight": s['weight_kg']})
    return jsonify({"success": False})

# ==========================================
# 📦 7. COUNTER BOOKING
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
        if str(d.get('ostate','')).strip().upper() == str(d.get('dstate','')).strip().upper(): cgst = sgst = gst / 2
        else: igst = gst
            
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
            except Exception as e: flash(f"Booking Error: {e}", "error")
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
    <form method="POST" id="bkForm">
        <div class="card" style="border-top: 4px solid var(--primary);">
            <div class="card-header"><i class="fas fa-boxes"></i> Counter Booking Entry</div>
            <div class="form-grid">
                <div class="form-group"><label class="form-label">Booking Date</label><input type="date" name="date" id="bdt" required class="form-control" style="color:var(--primary); font-weight:bold;"></div>
                <div class="form-group"><label class="form-label">AWB No. (C.Note)</label><input type="text" name="awb" required class="form-control" style="font-weight:bold; color:var(--danger); text-transform:uppercase;"></div>
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
                <div class="form-group"><label class="form-label">Destination Station</label><input type="text" name="dstat" list="stations" required class="form-control" style="text-transform:uppercase;"><datalist id="stations">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
                <div class="form-group"><label class="form-label">State Code</label><input type="text" name="dstate" id="dst" onchange="fetchRate()" class="form-control"></div>
                <div class="form-group"><label class="form-label">Address</label><input type="text" name="daddr" class="form-control"></div>
            </div>
        </div>

        <div class="card" style="border-top: 3px solid var(--success);">
            <div class="card-header" style="color:var(--success);">Charges & Service Details</div>
            <div class="form-grid">
                <div class="form-group"><label class="form-label">Weight (KG)</label><input type="number" step="0.01" name="wt" id="wt" value="1.0" required oninput="fetchRate()" class="form-control" style="font-weight:bold;"></div>
                <div class="form-group"><label class="form-label">Pieces</label><input type="number" name="pcs" value="1" required class="form-control"></div>
                <div class="form-group"><label class="form-label">Service Type</label><select name="srv" class="form-control"><option>SURFACE</option><option>AIR</option></select></div>
                <div class="form-group"><label class="form-label">Freight (₹)</label><input type="number" step="0.01" name="fr" id="fr" value="0.0" oninput="manualCalc()" required class="form-control" style="background:#fffbeb;"></div>
                <div class="form-group"><label class="form-label">Tax %</label><input type="number" name="tax" id="tax" value="18" oninput="manualCalc()" required class="form-control"></div>
                <div class="form-group"><label class="form-label">Grand Total (₹)</label><input type="number" step="0.01" name="amt" id="amt" value="0.0" readonly class="form-control" style="background:#fef2f2; color:#dc2626; font-weight:bold; font-size:16px;"></div>
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
                        <a href="/print/receipt/{{ r.awb_no }}" target="_blank" class="action-btn action-btn-gold"><i class="fas fa-receipt"></i> Rec</a>
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
            .then(r => r.json()).then(res => { 
                document.getElementById('fr').value = res.freight; document.getElementById('tax').value = res.tax_rate; document.getElementById('amt').value = res.total; 
                document.getElementById('calc_hint').innerHTML = `<i class='fas fa-check-circle' style='color:#10b981;'></i> Taxable: ₹ ${res.taxable} | GST: ₹ ${res.gst}`; 
            });
        }
        function manualCalc() {
            let fr = parseFloat(document.getElementById('fr').value)||0; let tx = parseFloat(document.getElementById('tax').value)||0; 
            document.getElementById('amt').value = (fr + (fr * tx / 100)).toFixed(2); 
            document.getElementById('calc_hint').innerHTML = "<i class='fas fa-pen'></i> Manual Override Applied";
        }
        if(document.getElementById('cid').tagName === 'INPUT') { fetchRate(); }
    </script>
    """
    return render_page("Counter Booking", render_template_string(html, custs=custs, stations=stations, recent=recent, my_cust=my_cust, now=datetime.now().strftime('%Y-%m-%d')))

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
            taxable = fr * (1 + (fuel/100)); gst = taxable * (tax / 100); tot = taxable + gst
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
                <div class="form-group"><label class="form-label">Dest Station</label><input type="text" name="dstat" list="stations" value="{{ s.dest_station or '' }}" required class="form-control" style="text-transform:uppercase;"><datalist id="stations">{% for st in stations %}<option value="{{ st.name }}">{% endfor %}</datalist></div>
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

# ==========================================
# 📥 8. INWARD HUB ENTRY
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
                if c.fetchone(): flash(f"AWB {awb} already inwarded today!", "error")
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
                <div class="form-group"><label class="form-label">AWB No</label><input type="text" name="awb" autofocus required class="form-control" style="border-color:var(--warning); font-weight:bold; text-transform:uppercase;" placeholder="Scan AWB..."></div>
                <div class="form-group">
                    <label class="form-label">Coming From (Origin)</label>
                    <input type="text" name="orig" list="st_list" required class="form-control" style="text-transform:uppercase;">
                    <datalist id="st_list">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist>
                </div>
                <div class="form-group"><label class="form-label">Weight (KG)</label><input type="number" step="0.01" name="wt" value="1.0" class="form-control"></div>
                <div class="form-group"><label class="form-label">Remarks</label><input type="text" name="info" class="form-control"></div>
                <button type="submit" class="btn btn-warning" style="color:black;"><i class="fas fa-download"></i> Save Inward</button>
            </div>
        </form>
    </div>

    <div class="card">
        <div class="card-header">Pending Inwards ({{ pending|length }})</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>AWB No</th><th>Coming From</th><th>Weight</th><th>Remarks</th><th>Act</th></tr></thead>
                <tbody>
                {% for p in pending %}
                <tr>
                    <td><span class="status-badge status-inward">{{ p.awb_no }}</span></td>
                    <td style="font-weight:600;">{{ p.origin_station }}</td>
                    <td>{{ p.weight }} KG</td>
                    <td>{{ p.info }}</td>
                    <td>
                        <form method="POST" style="margin:0;"><input type="hidden" name="action" value="delete"><input type="hidden" name="del_id" value="{{ p.id }}"><button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button></form>
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
# 📤 9. OUTWARD HUB & MASTER BAG
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
                                c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND entry_date=%s AND out_station=%s", (sub_awb, date_today, st))
                                if not c.fetchone():
                                    c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) VALUES(%s,%s,'HQ',%s,%s,%s,%s,0)", (date_today, sub_awb, st, dest, wt, f"From {awb}"))
                                    c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, dest_station=%s WHERE awb_no=%s", (st, dest, sub_awb))
                                    success += 1
                            flash(f"✅ Bag unpacked! {success} items mapped to {dest}.", "success")
                    else:
                        c.execute("SELECT id FROM outward_register WHERE awb_no=%s AND entry_date=%s AND out_station=%s", (awb, date_today, st))
                        if c.fetchone(): flash(f"AWB {awb} already scanned!", "error")
                        else:
                            c.execute("INSERT INTO outward_register(entry_date, awb_no, origin_station, out_station, destination, weight, info, finalized) VALUES(%s,%s,'HQ',%s,%s,%s,%s,0)", (date_today, awb, st, dest, wt, info))
                            s = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                            if s:
                                c.execute("UPDATE shipments SET status='OUTWARD', current_location=%s, dest_station=%s, weight_kg=%s, info=%s WHERE awb_no=%s", (st, dest, wt, info, awb))
                                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES((SELECT id FROM shipments WHERE awb_no=%s), 'OUTWARD', %s, %s)", (awb, st, f"Forwarded to {dest}"))
                            else:
                                c.execute("INSERT INTO shipments(awb_no, booking_date, dest_station, weight_kg, service_type, status, current_location, info) VALUES(%s, %s, %s, %s, 'SURFACE', 'OUTWARD', %s, %s)", (awb, date_today, dest, wt, st, info))
                            flash(f"✅ AWB {awb} Forwarded to {dest}!", "success")

            elif action == 'delete':
                c.execute("DELETE FROM outward_register WHERE id=%s", (request.form.get('del_id'),))
                flash("Entry deleted from pending outward.", "success")

            elif action == 'finalize':
                c.execute("SELECT * FROM outward_register WHERE entry_date=%s AND out_station=%s AND finalized=0", (date_today, st))
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
                            c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES((SELECT id FROM shipments WHERE awb_no=%s), 'BAGGED', %s, %s)", (a, st, f"Packed in {bag_no} to {dest}"))
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

    <div id="tab1" class="tab-content active">
        <div class="card" style="border-top: 4px solid var(--primary);">
            <div class="card-header" style="padding-bottom:10px;">
                Transhipment Hub Entry
                <div><button type="button" class="btn btn-warning" onclick="document.getElementById('bagModal').style.display='block'"><i class="fas fa-shopping-bag"></i> Master Bag</button></div>
            </div>
            <form method="POST" id="addForm">
                <input type="hidden" name="action" value="add">
                <div class="form-grid" style="align-items:end;">
                    <div class="form-group"><label class="form-label">AWB No / BAG No</label><input type="text" name="awb" id="awb_input" autofocus required class="form-control" style="border-color:var(--primary); font-weight:bold; text-transform:uppercase;"></div>
                    <div class="form-group"><label class="form-label" style="color:var(--danger);">Next Hub / Destination</label><input type="text" name="dest" id="dest_input" list="st_list" required class="form-control" style="text-transform:uppercase; border-color:var(--danger);"><datalist id="st_list">{% for s in stations %}<option value="{{ s.name }}">{% endfor %}</datalist></div>
                    <div class="form-group"><label class="form-label">Weight</label><input type="number" step="0.01" name="wt" id="wt_input" value="1.0" class="form-control"></div>
                    <div class="form-group"><label class="form-label">Info</label><input type="text" name="info" id="info_input" class="form-control"></div>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-plus"></i> Save</button>
                </div>
            </form>
        </div>

        <div class="card">
            <div class="card-header">Pending Outward List ({{ pending|length }}) <form method="POST" style="margin:0;" onsubmit="return confirm('Generate Manifest and Finalize all entries?');"><input type="hidden" name="action" value="finalize"><button type="submit" class="btn btn-success"><i class="fas fa-check-double"></i> FINALIZE & MANIFEST</button></form></div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>AWB No</th><th>Next Hub (Dest)</th><th>Weight</th><th>Remarks</th><th>Act</th></tr></thead>
                    <tbody>
                    {% for p in pending %}
                    <tr>
                        <td><span class="status-badge status-outward">{{ p.awb_no }}</span></td>
                        <td style="font-weight:700; color:var(--danger);">{{ p.destination }}</td>
                        <td>{{ p.weight }} KG</td>
                        <td>{{ p.info }}</td>
                        <td><form method="POST" style="margin:0;"><input type="hidden" name="action" value="delete"><input type="hidden" name="del_id" value="{{ p.id }}"><button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button></form></td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div id="tab2" class="tab-content">
        <div class="card">
            <div class="card-header">Generated Manifests History</div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>Outward No</th><th>Date</th><th>Total Docs</th><th>Manifest ID</th></tr></thead>
                    <tbody>
                    {% for s in sessions %}
                    <tr><td><span class="status-badge status-booked">{{ s.outward_no }}</span></td><td>{{ s.d }}</td><td><b>{{ s.c }}</b> Pcs</td><td style="font-weight:700; color:var(--primary);">{{ s.m }}</td></tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div id="bagModal" class="modal">
        <div class="modal-content">
            <h3 style="margin-top:0; color:#0f172a; border-bottom:2px solid #e2e8f0; padding-bottom:10px;">🎒 Create Master Bag</h3>
            <form method="POST">
                <input type="hidden" name="action" value="create_bag">
                <div class="form-group" style="margin-bottom:15px;"><label class="form-label">Bag Destination / Next Hub</label><input type="text" name="bag_dest" list="st_list" class="form-control" style="text-transform:uppercase;" required></div>
                <div class="form-group" style="margin-bottom:15px;"><label class="form-label">Scan AWBs (Comma separated or new line)</label><textarea name="bag_awbs" class="form-control" rows="6" placeholder="Scan AWBs here..." required></textarea></div>
                <div style="text-align:right;"><button type="button" class="btn btn-outline" onclick="document.getElementById('bagModal').style.display='none'">Cancel</button><button type="submit" class="btn btn-warning"><i class="fas fa-lock"></i> Seal Bag</button></div>
            </form>
        </div>
    </div>

    <script>
        function openTab(evt, tabName) { $('.tab-content').removeClass('active'); $('.tab-btn').removeClass('active'); $('#' + tabName).addClass('active'); $(evt.currentTarget).addClass('active'); }
        document.getElementById('awb_input').addEventListener('keypress', function(e) { if (e.key === 'Enter') { e.preventDefault(); document.getElementById('dest_input').focus(); } });
    </script>
    """
    return render_page("Outward Hub Entry", render_template_string(html, pending=pending, sessions=sessions, stations=stations, date_today=date_today))

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
                if c.fetchone(): flash(f"AWB {awb} is already pending for delivery!", "error")
                else:
                    c.execute("INSERT INTO delivery_register(entry_date, delivery_boy, delivery_area, awb_no, receiver_name, info, finalized) VALUES(%s, %s, %s, %s, %s, %s, 0)", (date_today, boy, area, awb, rec, info))
                    s = c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                    if s:
                        c.execute("UPDATE shipments SET status='ON_DRS', current_location=%s WHERE awb_no=%s", (area, awb))
                        c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES((SELECT id FROM shipments WHERE awb_no=%s), 'ON_DRS', %s, %s)", (awb, area, f"Assigned to {boy}"))
                    flash(f"✅ {awb} assigned to {boy}.", "success")

            elif action == 'delete':
                c.execute("DELETE FROM delivery_register WHERE id=%s", (request.form.get('del_id'),))

            elif action == 'finalize':
                c.execute("SELECT DISTINCT delivery_boy, delivery_area FROM delivery_register WHERE finalized=0")
                groups = c.fetchall()
                if not groups: flash("No pending entries.", "error")
                else:
                    for grp in groups:
                        boy = grp['delivery_boy']; area = grp['delivery_area']
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
                                if s: c.execute("INSERT INTO drs_items(drs_id, shipment_id, status, receiver_name) VALUES(%s, %s, 'ASSIGNED', %s)", (drs_id, s['id'], r['receiver_name']))
                    flash("✅ DRS Generated successfully", "success")

            elif action == 'unfinalize':
                dno = request.form.get('drs_no')
                c.execute("SELECT id FROM drs WHERE drs_no=%s", (dno,))
                drs_row = c.fetchone()
                if drs_row:
                    did = drs_row['id']
                    c.execute("SELECT shipment_id FROM drs_items WHERE drs_id=%s", (did,))
                    for s_item in c.fetchall():
                        c.execute("UPDATE shipments SET status='INWARD', current_location='Hub' WHERE id=%s AND status='ON_DRS'", (s_item['shipment_id'],))
                    c.execute("DELETE FROM drs_items WHERE drs_id=%s", (did,))
                    c.execute("DELETE FROM drs WHERE id=%s", (did,))
                c.execute("UPDATE delivery_register SET finalized=0, drs_no=NULL WHERE drs_no=%s", (dno,))
                flash(f"DRS {dno} unfinalized.", "success")
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
        <button class="tab-btn" onclick="openTab(event, 'tab2')"><i class="fas fa-tasks"></i> Finalized DRS History</button>
    </div>
    
    <div id="tab1" class="tab-content active">
        <div class="card" style="border-top: 4px solid var(--warning);">
            <div class="card-header">Scan Parcels For Delivery Sheet</div>
            <form method="POST">
                <input type="hidden" name="action" value="add">
                <div class="form-grid" style="align-items:end;">
                    <div class="form-group"><label class="form-label">Delivery Boy</label><input type="text" name="boy" list="boy_list" required class="form-control" style="text-transform:uppercase;"><datalist id="boy_list">{% for b in boys %}<option value="{{ b.full_name }}">{% endfor %}</datalist></div>
                    <div class="form-group"><label class="form-label">Area</label><input type="text" name="area" class="form-control"></div>
                    <div class="form-group"><label class="form-label">AWB No</label><input type="text" name="awb" required autofocus class="form-control" style="border-color:var(--primary); font-weight:bold; text-transform:uppercase;"></div>
                    <div class="form-group"><label class="form-label">Receiver Name</label><input type="text" name="rec" class="form-control"></div>
                    <button type="submit" class="btn btn-warning"><i class="fas fa-plus"></i> Add</button>
                </div>
            </form>
        </div>

        <div class="card">
            <div class="card-header">Pending Delivery Queue ({{ pending|length }}) <form method="POST" style="margin:0;" onsubmit="return confirm('Generate final DRS sheets?');"><input type="hidden" name="action" value="finalize"><button type="submit" class="btn btn-success"><i class="fas fa-check-double"></i> GENERATE DRS</button></form></div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>Rider</th><th>Area</th><th>AWB No</th><th>Receiver</th><th>Info</th><th>Act</th></tr></thead>
                    <tbody>
                    {% for p in pending %}
                    <tr><td style="font-weight:600;">{{ p.delivery_boy }}</td><td>{{ p.delivery_area }}</td><td><span class="status-badge status-outward">{{ p.awb_no }}</span></td><td>{{ p.receiver_name }}</td><td>{{ p.info }}</td><td><form method="POST" style="margin:0;"><input type="hidden" name="action" value="delete"><input type="hidden" name="del_id" value="{{ p.id }}"><button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button></form></td></tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div id="tab2" class="tab-content">
        <div class="card">
            <div class="card-header">Finalized Delivery Sheets</div>
            <div class="table-responsive">
                <table class="datatable">
                    <thead><tr><th>DRS No</th><th>Date</th><th>Rider</th><th>Area</th><th>Docs</th><th>Act</th></tr></thead>
                    <tbody>
                    {% for s in sessions %}
                    <tr><td><span class="status-badge status-booked">{{ s.drs_no }}</span></td><td>{{ s.d }}</td><td style="font-weight:700;">{{ s.b }}</td><td>{{ s.a }}</td><td style="font-weight:bold; color:var(--primary);">{{ s.c }} Docs</td><td><form method="POST" style="margin:0;" onsubmit="return confirm('Unfinalize this DRS?');"><input type="hidden" name="action" value="unfinalize"><input type="hidden" name="drs_no" value="{{ s.drs_no }}"><button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-undo"></i></button></form></td></tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    <script>function openTab(evt, tabName) { $('.tab-content').removeClass('active'); $('.tab-btn').removeClass('active'); $('#' + tabName).addClass('active'); $(evt.currentTarget).addClass('active'); }</script>
    """
    return render_page("D.R.S. Management", render_template_string(html, pending=pending, sessions=sessions, boys=boys))

# ==========================================
# 💰 11. FINANCE: AUTO-INVOICING ENGINE
# ==========================================
@app.route('/invoices', methods=['GET', 'POST'])
@login_required
def invoices():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    date_today = datetime.now().strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        with conn.cursor() as c:
            if action == 'generate':
                cid = request.form.get('cust_id')
                if not cid: flash("Select customer to generate invoice.", "error")
                else:
                    c.execute("""SELECT * FROM shipments WHERE customer_id=%s AND total_amount > 0 AND status != 'CANCELLED' AND id NOT IN (SELECT shipment_id FROM invoice_lines WHERE shipment_id IS NOT NULL)""", (cid,))
                    rows = c.fetchall()
                    if not rows: flash("No pending uninvoiced shipments found.", "error")
                    else:
                        tt = sum(safe_float(r.get("taxable_amount")) for r in rows)
                        cg = sum(safe_float(r.get("cgst")) for r in rows)
                        sg = sum(safe_float(r.get("sgst")) for r in rows)
                        ig = sum(safe_float(r.get("igst")) for r in rows)
                        tot = sum(safe_float(r.get("total_amount")) for r in rows)
                        inv_no = get_seq("invoice", "INV/", 5)
                        
                        c.execute("INSERT INTO invoices(invoice_no, invoice_date, customer_id, taxable_amount, cgst, sgst, igst, total, status) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, 'UNPAID')", (inv_no, date_today, cid, tt, cg, sg, ig, tot))
                        iid = c.lastrowid
                        
                        for r in rows: c.execute("INSERT INTO invoice_lines(invoice_id, description, shipment_id, taxable_amount, cgst, sgst, igst, total) VALUES(%s, %s, %s, %s, %s, %s, %s, %s)", (iid, f"AWB {r['awb_no']}", r['id'], safe_float(r['taxable_amount']), safe_float(r['cgst']), safe_float(r['sgst']), safe_float(r['igst']), safe_float(r['total_amount'])))
                        c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s, %s, 'INVOICE', %s, %s, 0, %s)", (cid, date_today, inv_no, tot, f"Auto Generated Invoice: {inv_no}"))
                        flash(f"✅ Auto-Invoice {inv_no} Generated! Total Billed: ₹ {tot:,.2f}", "success")

            elif action == 'edit_status':
                c.execute("UPDATE invoices SET status=%s WHERE id=%s", (request.form.get('status'), request.form.get('inv_id')))
                flash("Invoice status updated.", "success")
                
            elif action == 'delete':
                iid = request.form.get('del_id')
                c.execute("SELECT invoice_no, customer_id FROM invoices WHERE id=%s", (iid,))
                inv = c.fetchone()
                if inv:
                    c.execute("DELETE FROM ledger WHERE voucher_type='INVOICE' AND reference=%s", (inv['invoice_no'],))
                    c.execute("DELETE FROM invoice_lines WHERE invoice_id=%s", (iid,))
                    c.execute("DELETE FROM invoices WHERE id=%s", (iid,))
                    flash("🗑️ Invoice deleted and Ledger reversed.", "success")
        conn.commit(); return redirect('/invoices')

    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name"); custs = c.fetchall()
        c.execute("SELECT i.*, c.name as cust_name FROM invoices i LEFT JOIN customers c ON i.customer_id = c.id ORDER BY i.id DESC LIMIT 300"); inv_list = c.fetchall()
    conn.close()

    html = """
    <div class="card" style="background: #eef2ff; border-color: #c7d2fe;">
        <div class="card-header" style="color: #4f46e5; border-bottom-color: #c7d2fe;">🛠️ SYSTEMATIC AUTO-BILLING ENGINE</div>
        <form method="POST" onsubmit="return confirm('Generate Invoice for this customer?');" class="form-grid" style="align-items:flex-end;">
            <input type="hidden" name="action" value="generate">
            <div class="form-group"><label class="form-label">Select Corporate Customer A/c</label><select name="cust_id" class="form-control" required><option value="">-- Choose Customer --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div>
            <button type="submit" class="btn btn-primary" style="background:#f59e0b; border:none;"><i class="fas fa-bolt"></i> GENERATE AUTO-INVOICE</button>
        </form>
    </div>

    <div class="card">
        <div class="card-header">Generated Invoice Register</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Inv No</th><th>Date</th><th>Customer</th><th>Taxable</th><th>GST</th><th>Total</th><th>Status</th><th>Options</th></tr></thead>
                <tbody>
                {% for i in inv_list %}
                <tr>
                    <td><span class="status-badge" style="background:#fee2e2; color:#b91c1c;">{{ i.invoice_no }}</span></td>
                    <td>{{ i.invoice_date }}</td><td style="font-weight:700;">{{ i.cust_name }}</td>
                    <td>₹ {{ i.taxable_amount }}</td><td>₹ {{ i.cgst + i.sgst + i.igst }}</td>
                    <td style="font-weight:800; color:#2563eb;">₹ {{ i.total }}</td>
                    <td><span class="status-badge {% if i.status=='PAID' %}status-delivered{%else%}status-inward{%endif%}">{{ i.status }}</span></td>
                    <td style="display:flex; gap:5px;">
                        <a href="/print/invoice/{{ i.id }}" target="_blank" class="action-btn action-btn-gold"><i class="fas fa-print"></i></a>
                        <button onclick="openModal('modal_{{ i.id }}')" class="action-btn"><i class="fas fa-pen"></i></button>
                        <form method="POST" style="margin:0;" onsubmit="return confirm('Delete invoice and reverse ledger?');"><input type="hidden" name="action" value="delete"><input type="hidden" name="del_id" value="{{ i.id }}"><button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button></form>
                        <div id="modal_{{ i.id }}" class="modal"><div class="modal-content"><h3>Update Status ({{ i.invoice_no }})</h3><form method="POST"><input type="hidden" name="action" value="edit_status"><input type="hidden" name="inv_id" value="{{ i.id }}"><select name="status" class="form-control"><option {% if i.status=='UNPAID' %}selected{% endif %}>UNPAID</option><option {% if i.status=='PAID' %}selected{% endif %}>PAID</option></select><div style="text-align:right; margin-top:15px;"><button type="button" class="btn btn-danger" onclick="closeModal('modal_{{ i.id }}')">Cancel</button><button type="submit" class="btn btn-success">Save</button></div></form></div></div>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Account Bill Section", render_template_string(html, custs=custs, inv_list=inv_list))

# ==========================================
# 💰 12. FINANCE: PAYMENTS & EXPENSES
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
                cid = request.form.get('cust_id'); amt = safe_float(request.form.get('amount')); mode = request.form.get('mode', 'CASH'); ref = request.form.get('reference', '')
                if cid and amt > 0:
                    c.execute("INSERT INTO payments(customer_id, payment_date, amount, mode, reference) VALUES(%s, %s, %s, %s, %s)", (cid, date_today, amt, mode, ref))
                    c.execute("INSERT INTO ledger(customer_id, entry_date, voucher_type, reference, debit, credit, narration) VALUES(%s, %s, 'PAYMENT', %s, 0, %s, %s)", (cid, date_today, "PAY", amt, f"{mode} Received - {ref}"))
                    flash(f"✅ Payment of ₹{amt:,.2f} recorded!", "success")
            elif action == 'delete':
                pid = request.form.get('del_id')
                c.execute("SELECT * FROM payments WHERE id=%s", (pid,))
                p = c.fetchone()
                if p:
                    c.execute("DELETE FROM ledger WHERE voucher_type='PAYMENT' AND customer_id=%s AND credit=%s LIMIT 1", (p['customer_id'], p['amount']))
                    c.execute("DELETE FROM payments WHERE id=%s", (pid,))
                    flash("Payment deleted and Ledger reversed.", "success")
        conn.commit(); return redirect('/payments')
    with conn.cursor() as c:
        c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name"); custs = c.fetchall()
        c.execute("SELECT p.*, c.name as cust_name FROM payments p LEFT JOIN customers c ON p.customer_id = c.id ORDER BY p.id DESC LIMIT 300"); pay_list = c.fetchall()
    conn.close()
    html = """
    <div class="card" style="border-top: 4px solid var(--success);">
        <div class="card-header"><i class="fas fa-hand-holding-usd"></i> Record Receipt</div>
        <form method="POST"><input type="hidden" name="action" value="add"><div class="form-grid" style="align-items:end;"><div class="form-group"><label class="form-label">Customer A/c</label><select name="cust_id" class="form-control" required><option value="">-- Search --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div class="form-group"><label class="form-label">Amount (₹)</label><input type="number" step="0.01" name="amount" required class="form-control" style="font-weight:bold; color:var(--success);"></div><div class="form-group"><label class="form-label">Mode</label><select name="mode" class="form-control"><option>CASH</option><option>BANK</option><option>UPI</option></select></div><div class="form-group"><label class="form-label">Ref / UTR</label><input type="text" name="reference" class="form-control"></div><button type="submit" class="btn btn-success"><i class="fas fa-save"></i> Save</button></div></form>
    </div>
    <div class="card">
        <div class="card-header">Recent Payments</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Date</th><th>Customer Name</th><th>Amount Received</th><th>Mode</th><th>Reference</th><th>Act</th></tr></thead>
                <tbody>
                {% for p in pay_list %}<tr><td>{{ p.payment_date }}</td><td style="font-weight:700;">{{ p.cust_name }}</td><td style="font-weight:bold; color:var(--success);">₹ {{ p.amount }}</td><td><span class="status-badge" style="background:#e0f2fe; color:#0284c7;">{{ p.mode }}</span></td><td>{{ p.reference or '-' }}</td><td><form method="POST" style="margin:0;" onsubmit="return confirm('Revoke payment?');"><input type="hidden" name="action" value="delete"><input type="hidden" name="del_id" value="{{ p.id }}"><button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button></form></td></tr>{% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Payment Entry", render_template_string(html, custs=custs, pay_list=pay_list))

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
                amt = safe_float(request.form.get('amount'))
                if amt > 0:
                    c.execute("INSERT INTO expenses(expense_date, category, amount, paid_to, notes) VALUES(%s, %s, %s, %s, %s)", (date_today, request.form.get('category'), amt, request.form.get('paid_to', ''), request.form.get('notes', '')))
                    flash(f"✅ Expense of ₹{amt:,.2f} recorded.", "success")
            elif action == 'delete':
                c.execute("DELETE FROM expenses WHERE id=%s", (request.form.get('del_id'),))
        conn.commit(); return redirect('/expenses')
    with conn.cursor() as c:
        c.execute("SELECT * FROM expenses ORDER BY id DESC LIMIT 300"); exp_list = c.fetchall()
        total_exp = sum(safe_float(r['amount']) for r in exp_list)
    conn.close()
    html = """
    <div class="card" style="border-top: 4px solid var(--danger);">
        <div class="card-header"><i class="fas fa-money-bill-wave"></i> Add Office Expense</div>
        <form method="POST"><input type="hidden" name="action" value="add"><div class="form-grid" style="align-items:end;"><div class="form-group"><label class="form-label">Category</label><select name="category" class="form-control"><option>Fuel & Transport</option><option>Office Rent</option><option>Salary</option><option>Miscellaneous</option></select></div><div class="form-group"><label class="form-label">Amount (₹)</label><input type="number" step="0.01" name="amount" required class="form-control" style="font-weight:bold; color:var(--danger);"></div><div class="form-group"><label class="form-label">Paid To</label><input type="text" name="paid_to" class="form-control" required></div><div class="form-group"><label class="form-label">Notes</label><input type="text" name="notes" class="form-control"></div><button type="submit" class="btn btn-danger"><i class="fas fa-save"></i> Save</button></div></form>
    </div>
    <div class="card">
        <div class="card-header" style="display:flex; justify-content:space-between;"><div>Expense Register</div><div style="color:var(--danger); font-size:16px;">Total Displayed: ₹ {{ "{:,.2f}".format(total_exp) }}</div></div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Date</th><th>Category</th><th>Paid To</th><th>Amount</th><th>Notes</th><th>Act</th></tr></thead>
                <tbody>
                {% for e in exp_list %}<tr><td>{{ e.expense_date }}</td><td><span class="status-badge" style="background:#fef3c7; color:#b45309;">{{ e.category }}</span></td><td style="font-weight:600;">{{ e.paid_to }}</td><td style="font-weight:bold; color:var(--danger);">₹ {{ e.amount }}</td><td>{{ e.notes }}</td><td><form method="POST" style="margin:0;"><input type="hidden" name="action" value="delete"><input type="hidden" name="del_id" value="{{ e.id }}"><button type="submit" class="action-btn action-btn-red" style="border:none;"><i class="fas fa-trash"></i></button></form></td></tr>{% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Journal Voucher", render_template_string(html, exp_list=exp_list, total_exp=total_exp))

@app.route('/my_ledger', methods=['GET', 'POST'])
@login_required
def my_ledger():
    if session.get('role') not in ['ADMIN', 'ACCOUNTS', 'CUSTOMER']: return redirect('/')
    conn = get_db()
    f_date = request.args.get('from_date', (datetime.now().replace(day=1)).strftime('%Y-%m-%d'))
    t_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    cid = session.get('customer_id') if session.get('role') == 'CUSTOMER' else request.args.get('cust_id')
        
    l_data = []; c_bal = 0.0; customer_name = ""
    if cid:
        with conn.cursor() as c:
            c.execute("SELECT name FROM customers WHERE id=%s", (cid,))
            cst = c.fetchone()
            if cst: customer_name = cst['name']
            c.execute("SELECT entry_date, voucher_type, reference, debit, credit, narration FROM ledger WHERE customer_id=%s AND entry_date BETWEEN %s AND %s ORDER BY entry_date ASC, id ASC", (cid, f_date, t_date))
            l_data = c.fetchall()
            c.execute("SELECT COALESCE(SUM(debit-credit),0) b FROM ledger WHERE customer_id=%s", (cid,))
            r = c.fetchone()
            c_bal = safe_float(r['b']) if r else 0.0
            
    with conn.cursor() as c: c.execute("SELECT id, name FROM customers WHERE is_active=1 ORDER BY name"); custs = c.fetchall()
    conn.close()

    html = """
    <div class="card" style="background:#f8fafc;">
        <form method="GET" class="form-grid" style="align-items:end;">
            {% if session.get('role') != 'CUSTOMER' %}
            <div class="form-group" style="grid-column: span 2;"><label class="form-label">Select Customer Account</label><select name="cust_id" class="form-control" required><option value="">-- Type to Search --</option>{% for c in custs %}<option value="{{ c.id }}" {% if c.id|string == cid %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select></div>
            {% endif %}
            <div class="form-group"><label class="form-label">From Date</label><input type="date" name="from_date" value="{{ f_date }}" class="form-control"></div>
            <div class="form-group"><label class="form-label">To Date</label><input type="date" name="to_date" value="{{ t_date }}" class="form-control"></div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-search"></i> Load Ledger</button>
            {% if cid %}<button type="button" class="btn btn-outline" onclick="window.print()"><i class="fas fa-print"></i> Print</button>{% endif %}
        </form>
    </div>
    {% if cid %}
    <div class="card">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div><i class="fas fa-book"></i> Statement: <span style="color:var(--primary);">{{ customer_name }}</span></div>
            <div style="font-size:18px; color:{% if c_bal > 0 %}var(--danger){% else %}var(--success){% endif %};">Net Outstanding: ₹ {{ "{:,.2f}".format(c_bal) }}</div>
        </div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Date</th><th>Voucher / Ref No</th><th>Narration / Particulars</th><th>Debit (Bill ₹)</th><th>Credit (Paid ₹)</th></tr></thead>
                <tbody>
                {% for l in l_data %}<tr><td>{{ l.entry_date }}</td><td><span class="status-badge {% if l.voucher_type == 'INVOICE' %}status-outward{%else%}status-delivered{%endif%}">{{ l.voucher_type }}</span> <br><b>{{ l.reference }}</b></td><td>{{ l.narration }}</td><td style="color:var(--danger); font-weight:bold;">{% if l.debit > 0 %}{{ l.debit }}{% else %}-{% endif %}</td><td style="color:var(--success); font-weight:bold;">{% if l.credit > 0 %}{{ l.credit }}{% else %}-{% endif %}</td></tr>{% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endif %}
    """
    return render_page("Customer Account Ledger", render_template_string(html, custs=custs, cid=cid, l_data=l_data, c_bal=c_bal, f_date=f_date, t_date=t_date, customer_name=customer_name))

# ==========================================
# 🏢 13. MASTER ENTRIES & CONFIG
# ==========================================
@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE customers SET is_active=0 WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Customer Deactivated!", "success"); return redirect('/customers')
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c:
            c.execute("""INSERT INTO customers(code, name, gstin, phone, email, state, state_code, address, credit_limit, is_active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""", (d.get('code',''), d.get('name',''), d.get('gstin',''), d.get('phone1',''), d.get('email',''), d.get('state',''), d.get('scode',''), d.get('address',''), safe_float(d.get('limit'))))
            conn.commit(); flash("Customer Saved Successfully!", "success")
    with conn.cursor() as c: c.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY id DESC"); custs = c.fetchall()
    conn.close()
    html = """
    <div class="card" style="border-top: 4px solid var(--primary);">
        <div class="card-header"><i class="fas fa-building"></i> Add New Customer Account</div>
        <form method="POST"><div class="form-grid"><div class="form-group"><label class="form-label">A/c Code</label><input type="text" name="code" class="form-control" style="font-weight:bold;" required></div><div class="form-group"><label class="form-label">Company Name</label><input type="text" name="name" class="form-control" style="font-weight:bold; color:var(--primary);" required></div><div class="form-group"><label class="form-label">Phone No.</label><input type="text" name="phone1" class="form-control"></div><div class="form-group"><label class="form-label">Email ID</label><input type="email" name="email" class="form-control"></div><div class="form-group"><label class="form-label">State Name</label><input type="text" name="state" class="form-control" style="text-transform:uppercase;"></div><div class="form-group"><label class="form-label">State Code</label><input type="text" name="scode" class="form-control" style="text-transform:uppercase;"></div><div class="form-group"><label class="form-label">GSTIN</label><input type="text" name="gstin" class="form-control" style="text-transform:uppercase;"></div><div class="form-group"><label class="form-label">Credit Limit (₹)</label><input type="number" step="0.01" name="limit" value="0.00" class="form-control" style="color:var(--danger); font-weight:bold;"></div><div class="form-group" style="grid-column: span 2;"><label class="form-label">Address</label><input type="text" name="address" class="form-control"></div></div><div style="margin-top:15px; text-align:right;"><button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Account</button></div></form>
    </div>
    <div class="card">
        <div class="card-header">Active Customers</div>
        <div class="table-responsive">
            <table class="datatable">
                <thead><tr><th>Code</th><th>Name</th><th>Phone</th><th>GSTIN</th><th>Limit</th><th>Act</th></tr></thead>
                <tbody>{% for r in custs %}<tr><td><span class="status-badge" style="background:#e2e8f0; color:#475569;">{{ r.code }}</span></td><td style="font-weight:700; color:var(--primary);">{{ r.name }}</td><td>{{ r.phone }}</td><td>{{ r.gstin }}</td><td style="color:var(--danger); font-weight:600;">₹ {{ r.credit_limit }}</td><td><a href="/customers?delete={{ r.id }}" class="action-btn action-btn-red" onclick="return confirm('Deactivate?');"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</tbody>
            </table>
        </div>
    </div>
    """
    return render_page("Customers Setup", render_template_string(html, custs=custs))

@app.route('/location_master', methods=['GET', 'POST'])
@login_required
def location_master():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip().upper()
        if name:
            with conn.cursor() as c: c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (name,)); conn.commit(); flash(f"Location {name} Saved!", "success")
    with conn.cursor() as c: c.execute("SELECT id, name FROM stations ORDER BY id DESC LIMIT 500"); stations_list = c.fetchall()
    conn.close()
    html = """
    <div class="form-grid">
        <div class="card" style="border-top: 4px solid var(--success);">
            <div class="card-header"><i class="fas fa-map-marker-alt"></i> Add Station</div>
            <form method="POST"><div class="form-group" style="margin-bottom:15px;"><label class="form-label">Station / City Name</label><input type="text" name="name" required class="form-control" style="text-transform:uppercase; font-weight:bold;"></div><button type="submit" class="btn btn-success" style="width:100%;"><i class="fas fa-plus"></i> Add</button></form>
        </div>
        <div class="card" style="grid-column: span 2;"><div class="card-header">System Locations</div><div class="table-responsive"><table class="datatable"><thead><tr><th>ID</th><th>Station Name</th></tr></thead><tbody>{% for r in s_list %}<tr><td>{{ r.id }}</td><td style="font-weight:bold; color:var(--primary);">{{ r.name }}</td></tr>{% endfor %}</tbody></table></div></div>
    </div>
    """
    return render_page("Location Master", render_template_string(html, s_list=stations_list))

@app.route('/rates', methods=['GET', 'POST'])
@login_required
def rates():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("DELETE FROM rates WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("Rate Chart Deleted!", "success"); return redirect('/rates')
    if request.method == 'POST':
        d = request.form
        with conn.cursor() as c: c.execute("""INSERT INTO rates(customer_id, origin_state_code, dest_state_code, min_weight, max_weight, fixed_charge, per_kg_rate, gst_rate, active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1)""", (safe_int(d.get('cust_id')) if d.get('cust_id') else None, d.get('ostate'), d.get('dstate'), safe_float(d.get('min_wt')), safe_float(d.get('max_wt')), safe_float(d.get('fixed')), safe_float(d.get('per_kg')), safe_float(d.get('gst')))); conn.commit(); flash("Rate Added!", "success")
    with conn.cursor() as c: c.execute("SELECT r.*, c.name as cname FROM rates r LEFT JOIN customers c ON r.customer_id=c.id ORDER BY r.id DESC"); rates_list = c.fetchall(); c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    html = """
    <div class="card" style="border-top: 4px solid var(--warning);"><div class="card-header"><i class="fas fa-file-contract"></i> Add Rate Chart</div><form method="POST"><div class="form-grid" style="align-items:end;"><div class="form-group"><label class="form-label">Customer</label><select name="cust_id" class="form-control"><option value="">-- DEFAULT RATE --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><div class="form-group"><label class="form-label">Origin State</label><input type="text" name="ostate" required class="form-control" placeholder="RJ"></div><div class="form-group"><label class="form-label">Dest State</label><input type="text" name="dstate" required class="form-control" placeholder="HR"></div><div class="form-group"><label class="form-label">Min Wt</label><input type="number" step="0.01" name="min_wt" value="0.1" class="form-control"></div><div class="form-group"><label class="form-label">Max Wt</label><input type="number" step="0.01" name="max_wt" value="50" class="form-control"></div><div class="form-group"><label class="form-label">Fixed (₹)</label><input type="number" step="0.01" name="fixed" value="50" class="form-control"></div><div class="form-group"><label class="form-label">Per KG (₹)</label><input type="number" step="0.01" name="per_kg" value="20" class="form-control"></div><div class="form-group"><label class="form-label">GST %</label><input type="number" step="0.01" name="gst" value="18" class="form-control"></div><button type="submit" class="btn btn-warning"><i class="fas fa-save"></i> Save Rate</button></div></form></div>
    <div class="card"><div class="card-header">Existing Contracts</div><div class="table-responsive"><table class="datatable"><thead><tr><th>Customer A/c</th><th>Route</th><th>Weight Range</th><th>Charges</th><th>GST %</th><th>Act</th></tr></thead><tbody>{% for r in rates_list %}<tr><td style="font-weight:700;">{% if r.cname %}<span style="color:var(--primary);">{{ r.cname }}</span>{% else %}<span class="status-badge status-outward">DEFAULT</span>{% endif %}</td><td><b>{{ r.origin_state_code }} ➔ {{ r.dest_state_code }}</b></td><td>{{ r.min_weight }} - {{ r.max_weight }} KG</td><td style="color:var(--danger); font-weight:600;">₹{{ r.fixed_charge }} + (₹{{ r.per_kg_rate }}/KG)</td><td>{{ r.gst_rate }}%</td><td><a href="/rates?delete={{ r.id }}" class="action-btn action-btn-red" onclick="return confirm('Delete?');"><i class="fas fa-trash"></i></a></td></tr>{% endfor %}</tbody></table></div></div>
    """
    return render_page("Rate Master", render_template_string(html, custs=custs, rates_list=rates_list))

@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if session.get('role') != 'ADMIN': return redirect('/')
    conn = get_db()
    if request.args.get('delete'):
        with conn.cursor() as c: c.execute("UPDATE users SET active=0 WHERE id=%s", (request.args.get('delete'),)); conn.commit(); flash("User Deactivated!", "success"); return redirect('/users')
    if request.method == 'POST':
        d = request.form; b = str(d.get('branch', '')).upper(); cid = safe_int(d.get('customer_id')) if d.get('customer_id') else None
        with conn.cursor() as c:
            c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (b,))
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, customer_id, active) VALUES(%s,%s,%s,%s,%s,%s,1)", (d.get('username',''), hashlib.sha256(d.get('password','').encode()).hexdigest(), d.get('full_name',''), d.get('role',''), b, cid))
            conn.commit(); flash("User Added!", "success")
    with conn.cursor() as c: c.execute("SELECT * FROM users ORDER BY id DESC"); u_list = c.fetchall(); c.execute("SELECT name FROM stations ORDER BY name"); branches = c.fetchall(); c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    html = """
    <div class="card" style="border-top: 4px solid var(--primary);"><div class="card-header"><i class="fas fa-user-plus"></i> Create User</div><form method="POST"><div class="form-grid" style="align-items:end;"><div class="form-group"><label class="form-label">Username</label><input type="text" name="username" class="form-control" required></div><div class="form-group"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div><div class="form-group"><label class="form-label">Full Name</label><input type="text" name="full_name" class="form-control" required></div><div class="form-group"><label class="form-label">Role</label><select name="role" class="form-control"><option>OPERATOR</option><option>ADMIN</option><option>ACCOUNTS</option><option>CUSTOMER</option></select></div><div class="form-group"><label class="form-label">Branch</label><input type="text" name="branch" list="brlist" class="form-control" style="text-transform:uppercase;" required><datalist id="brlist">{% for b in branches %}<option value="{{ b.name }}">{% endfor %}</datalist></div><div class="form-group"><label class="form-label">Link Customer (B2B)</label><select name="customer_id" class="form-control"><option value="">-- None --</option>{% for c in custs %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></div><button type="submit" class="btn btn-primary" style="width:100%;"><i class="fas fa-check"></i> Create</button></div></form></div>
    <div class="card"><div class="card-header">System Users</div><div class="table-responsive"><table class="datatable"><thead><tr><th>Login ID</th><th>Full Name</th><th>Role</th><th>Branch</th><th>Status</th><th>Act</th></tr></thead><tbody>{% for u in u_list %}<tr><td style="font-weight:bold;">{{ u.username }}</td><td>{{ u.full_name }}</td><td><span class="status-badge status-outward">{{ u.role }}</span></td><td>{{ u.branch_name }}</td><td>{% if u.active %}<span class="status-badge status-delivered">Active</span>{% else %}<span class="status-badge status-booked" style="background:#fee2e2; color:#b91c1c;">Disabled</span>{% endif %}</td><td>{% if u.active %}<a href="/users?delete={{ u.id }}" class="action-btn action-btn-red" onclick="return confirm('Disable user?');"><i class="fas fa-ban"></i> Disable</a>{% endif %}</td></tr>{% endfor %}</tbody></table></div></div>
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
            c.execute("INSERT INTO users(username, password_hash, full_name, role, branch_name, active) VALUES(%s,%s,%s,'DELIVERY',%s,1)", (d.get('code',''), fake_hash, d.get('name',''), session.get('branch','HQ')))
            conn.commit(); flash("Rider Added!", "success")
    with conn.cursor() as c: c.execute("SELECT * FROM users WHERE role='DELIVERY' ORDER BY id DESC"); boys = c.fetchall()
    conn.close()
    html = """<div class="form-grid"><div class="card" style="border-top: 4px solid var(--warning);"><div class="card-header"><i class="fas fa-biking"></i> Add Delivery Boy</div><form method="POST"><div class="form-group" style="margin-bottom:15px;"><label class="form-label">Employee Code</label><input type="text" name="code" class="form-control" required></div><div class="form-group" style="margin-bottom:15px;"><label class="form-label">Full Name</label><input type="text" name="name" class="form-control" required></div><button type="submit" class="btn btn-warning" style="width:100%;"><i class="fas fa-plus"></i> Add Rider</button></form></div><div class="card" style="grid-column: span 2;"><div class="card-header">Riders List</div><div class="table-responsive"><table class="datatable"><thead><tr><th>Code</th><th>Name</th><th>Branch</th></tr></thead><tbody>{% for b in boys %}<tr><td style="font-weight:bold; color:var(--text-light);">{{ b.username }}</td><td style="font-weight:700; color:var(--primary);">{{ b.full_name }}</td><td>{{ b.branch_name }}</td></tr>{% endfor %}</tbody></table></div></div></div>"""
    return render_page("Delivery Boys", render_template_string(html, boys=boys))

@app.route('/stationery', methods=['GET', 'POST'])
@login_required
def stationery():
    if session.get('role') == 'CUSTOMER': return redirect('/')
    conn = get_db()
    if request.method == 'POST':
        awb = request.form.get('awb','').strip().upper(); issue_to = request.form.get('issue_to',''); pcs = safe_int(request.form.get('pcs', 1))
        with conn.cursor() as c:
            c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
            s = c.fetchone()
            if s:
                c.execute("UPDATE shipments SET status='STATIONERY', info=%s WHERE id=%s", (f"Issued {pcs} to {issue_to}", s['id']))
                c.execute("INSERT INTO scan_events(shipment_id, scan_type, location, remarks) VALUES(%s,'STATIONERY',%s,%s)", (s['id'], session.get('branch','HQ'), f"Stationery Issued: {pcs} pcs to {issue_to}"))
                conn.commit(); flash(f"Stationery Issued for {awb}", "success")
            else: flash("AWB not found in system.", "error")
    with conn.cursor() as c: c.execute("SELECT awb_no, booking_date, origin_name, status, info FROM shipments WHERE status='STATIONERY' ORDER BY id DESC LIMIT 500"); hist = c.fetchall(); c.execute("SELECT id, name FROM customers WHERE is_active=1"); custs = c.fetchall()
    conn.close()
    html = """<div class="form-grid"><div class="card" style="border-top: 4px solid var(--primary);"><div class="card-header"><i class="fas fa-barcode"></i> Issue Pre-Printed Stationery</div><form method="POST"><div class="form-group" style="margin-bottom:15px;"><label class="form-label">AWB No.</label><input name="awb" required class="form-control" style="text-transform:uppercase; font-weight:bold;"></div><div class="form-group" style="margin-bottom:15px;"><label class="form-label">Issue To</label><select name="issue_to" required class="form-control">{% for c in custs %}<option>{{ c.name }}</option>{% endfor %}</select></div><div class="form-group" style="margin-bottom:15px;"><label class="form-label">Pieces</label><input type="number" name="pcs" value="1" min="1" class="form-control"></div><button type="submit" class="btn btn-primary" style="width:100%;"><i class="fas fa-check"></i> Assign</button></form></div><div class="card" style="grid-column: span 2;"><div class="card-header">Allocation Register</div><div class="table-responsive"><table class="datatable"><thead><tr><th>AWB No</th><th>Date</th><th>Issued To</th><th>Remarks</th></tr></thead><tbody>{% for h in hist %}<tr><td style="font-weight:bold; color:var(--primary);">{{ h.awb_no }}</td><td>{{ h.booking_date }}</td><td style="font-weight:700;">{{ h.origin_name }}</td><td>{{ h.info }}</td></tr>{% endfor %}</tbody></table></div></div></div>"""
    return render_page("Stationery", render_template_string(html, custs=custs, hist=hist))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    conn = get_db()
    if request.method == 'POST':
        if 'old_pass' in request.form:
            old_p = hashlib.sha256(request.form.get('old_pass','').encode()).hexdigest(); new_p = hashlib.sha256(request.form.get('new_pass','').encode()).hexdigest()
            with conn.cursor() as c:
                c.execute("SELECT password_hash FROM users WHERE id=%s", (session['user_id'],)); u = c.fetchone()
                if u and u['password_hash'] == old_p:
                    c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_p, session['user_id']))
                    conn.commit(); flash("Password Changed Successfully!", "success")
                else: flash("Old Password Incorrect!", "error")
        else:
            if session.get('role') != 'ADMIN': flash("Only Admins can change settings.", "error")
            else:
                with conn.cursor() as c:
                    for key in ['company_name','company_address','company_gstin','company_phone','company_state_code','company_email','bank_details','terms_note','fuel_surcharge']:
                        val = request.form.get(key, '')
                        c.execute("UPDATE settings SET value=%s WHERE key_name=%s", (val, key))
                    conn.commit(); flash("System Settings Updated!", "success")
    with conn.cursor() as c: c.execute("SELECT key_name, value FROM settings"); settings_data = {r['key_name']: r['value'] for r in c.fetchall()}
    conn.close()
    html = """
    <div class="form-grid">
        {% if session.get('role') == 'ADMIN' %}
        <div class="card" style="border-top: 4px solid var(--primary); grid-column: span 2;">
            <div class="card-header"><i class="fas fa-building"></i> Company Settings</div>
            <form method="POST"><div class="form-grid"><div class="form-group"><label class="form-label">Company Name</label><input type="text" name="company_name" value="{{ s.company_name }}" class="form-control"></div><div class="form-group"><label class="form-label">GSTIN</label><input type="text" name="company_gstin" value="{{ s.company_gstin }}" class="form-control"></div><div class="form-group"><label class="form-label">Phone</label><input type="text" name="company_phone" value="{{ s.company_phone }}" class="form-control"></div><div class="form-group"><label class="form-label">Email</label><input type="text" name="company_email" value="{{ s.company_email }}" class="form-control"></div><div class="form-group"><label class="form-label">State Code</label><input type="text" name="company_state_code" value="{{ s.company_state_code }}" class="form-control"></div><div class="form-group"><label class="form-label">Fuel Surcharge %</label><input type="number" step="0.01" name="fuel_surcharge" value="{{ s.fuel_surcharge }}" class="form-control"></div><div class="form-group" style="grid-column: span 2;"><label class="form-label">Address</label><textarea name="company_address" class="form-control" rows="2">{{ s.company_address }}</textarea></div><div class="form-group" style="grid-column: span 2;"><label class="form-label">Bank Details</label><textarea name="bank_details" class="form-control" rows="2">{{ s.bank_details }}</textarea></div><div class="form-group" style="grid-column: span 2;"><label class="form-label">Terms</label><textarea name="terms_note" class="form-control" rows="2">{{ s.terms_note }}</textarea></div></div><div style="text-align:right; margin-top:15px;"><button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save</button></div></form>
        </div>
        {% endif %}
        <div class="card" style="border-top: 4px solid var(--danger);">
            <div class="card-header"><i class="fas fa-key"></i> Change Password</div>
            <form method="POST"><div class="form-group" style="margin-bottom:15px;"><label class="form-label">Current Password</label><input type="password" name="old_pass" required class="form-control"></div><div class="form-group" style="margin-bottom:15px;"><label class="form-label">New Password</label><input type="password" name="new_pass" required class="form-control"></div><button type="submit" class="btn btn-danger" style="width:100%;"><i class="fas fa-lock"></i> Update</button></form>
        </div>
    </div>
    """
    return render_page("Settings", render_template_string(html, s=settings_data))

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
                awb = str(awb).strip().upper()
                c.execute("SELECT id FROM shipments WHERE awb_no=%s", (awb,))
                if c.fetchone(): continue
                dest = row.get(headers.get("dest", "Dest")) or row.get("Dest Station", "UNKNOWN"); wt = row.get(headers.get("weight", "Weight")) or "1"; tot = row.get(headers.get("amount", "Amount")) or "0"; d = datetime.now().strftime("%Y-%m-%d")
                c.execute("INSERT IGNORE INTO stations(name) VALUES(%s)", (dest.upper(),))
                c.execute("""INSERT INTO shipments(awb_no, dest_name, dest_station, weight_kg, total_amount, booking_date, status, current_location, service_type, origin_name) VALUES(%s, %s, %s, %s, %s, %s, 'BOOKED', 'Origin', 'SURFACE', %s)""", (awb, dest, dest.upper(), safe_float(wt), safe_float(tot), d, session.get('branch','HQ')))
                added += 1
            conn.commit()
        conn.close(); flash(f"🎉 Import Complete! {added} New Parcels Booked.", "success")
    html = """
    <div class="card" style="max-width:500px; margin:0 auto; border-top:4px solid var(--success);">
        <div class="card-header"><i class="fas fa-file-csv"></i> Bulk CSV Import (Fast Booking)</div>
        <div style="background:#f8fafc; padding:15px; border-radius:8px; border:1px dashed #cbd5e1; margin-bottom:20px; font-size:13px; color:var(--text-light);">
            <b>Required Column Headers in CSV:</b><br><br>• AWB<br>• Dest<br>• Weight<br>• Amount<br><br><i>* Save your Excel file as 'CSV (Comma delimited)' before uploading.</i>
        </div>
        <form method="POST" enctype="multipart/form-data"><input type="file" name="file" accept=".csv" required class="form-control" style="margin-bottom:15px; padding:15px;"><button type="submit" class="btn btn-success" style="width:100%;"><i class="fas fa-upload"></i> Start Import</button></form>
    </div>
    """
    return render_page("Excel Import", render_template_string(html))

# ==========================================
# 📊 14. DYNAMIC REPORTS ENGINE
# ==========================================
@app.route('/module/<category>/<action>', methods=['GET', 'POST'])
@login_required
def dynamic_module(category, action):
    title_category = category.replace('_', ' ').upper(); title_action = action.replace('_', ' ').upper(); page_title = f"{title_action} [{title_category}]"
    f_date = request.args.get('from_date', datetime.now().strftime('%Y-%m-%d')); t_date = request.args.get('to_date', datetime.now().strftime('%Y-%m-%d'))
    data_found = False; table_headers = []; table_rows = []
    
    conn = get_db()
    with conn.cursor() as c:
        q_map = {
            'cash_billing_register': (f"SELECT id, awb_no, booking_date, dest_name, weight_kg, total_amount FROM shipments WHERE customer_id IS NULL AND booking_date BETWEEN '{f_date}' AND '{t_date}' LIMIT 500", ["ID", "AWB", "Date", "Dest", "Weight", "Total Amount", "Actions"]),
            'credit_billing': (f"SELECT s.id, s.awb_no, s.booking_date, c.name, s.total_amount FROM shipments s JOIN customers c ON s.customer_id=c.id WHERE s.customer_id IS NOT NULL AND s.booking_date BETWEEN '{f_date}' AND '{t_date}' LIMIT 500", ["ID", "AWB", "Date", "Customer", "Amount", "Actions"]),
            'outward_register': (f"SELECT id, entry_date, awb_no, out_station, destination, weight FROM outward_register WHERE entry_date BETWEEN '{f_date}' AND '{t_date}' ORDER BY id DESC LIMIT 500", ["ID", "Date", "AWB", "Out-Station", "Dest (Next Hub)", "Weight", "Actions"]),
            'cargo_inward': (f"SELECT id, entry_date, awb_no, origin_station, in_station, weight FROM inward_register WHERE entry_date BETWEEN '{f_date}' AND '{t_date}' ORDER BY id DESC LIMIT 500", ["ID", "Date", "AWB", "Origin", "In-Station", "Weight", "Actions"]),
            'drs_status': (f"SELECT id, drs_no, drs_date, rider_name, status FROM drs WHERE drs_date BETWEEN '{f_date}' AND '{t_date}' LIMIT 500", ["ID", "DRS No", "Date", "Delivery Boy", "Status", "Actions"]),
            'manifest_register': (f"SELECT id, manifest_no, manifest_type, from_location, to_location, status, DATE(created_at) FROM manifests WHERE DATE(created_at) BETWEEN '{f_date}' AND '{t_date}'", ["ID", "Manifest No", "Type", "Origin", "Destination", "Status", "Date", "Actions"]),
            'daily_collection': (f"SELECT id, payment_date, mode, amount as total_collected FROM payments WHERE payment_date BETWEEN '{f_date}' AND '{t_date}' LIMIT 500", ["ID", "Date", "Payment Mode", "Total Collected", "Actions"])
        }
        query_data = q_map.get(action, (f"SELECT id, awb_no, booking_date, dest_name, status FROM shipments WHERE booking_date BETWEEN '{f_date}' AND '{t_date}' LIMIT 500", ["ID", "AWB", "Date", "Dest", "Status", "Actions"]))

        try:
            c.execute(query_data[0])
            rows = c.fetchall()
            if rows:
                data_found = True; table_headers = query_data[1]
                for r in rows:
                    row_vals = [str(v) for v in r.values()]
                    if 'awb_no' in r: row_vals.append(f"<a href='/edit_shipment/{r['id']}' class='action-btn'><i class='fas fa-edit'></i> Edit</a>")
                    elif 'invoice_no' in r: row_vals.append(f"<a href='/print/invoice/{r['id']}' target='_blank' class='action-btn action-btn-gold'><i class='fas fa-print'></i> Print</a>")
                    else: row_vals.append(f"<button class='action-btn'><i class='fas fa-eye'></i> View</button>")
                    table_rows.append(row_vals)
        except Exception as e: logging.error(f"Report Error: {e}")
    conn.close()
    
    html = """
    <div class="card" style="background: #f8fafc; border: 1px solid #cbd5e1; margin-bottom: 20px;">
        <form method="GET" style="display:flex; gap:15px; align-items:flex-end;">
            <div class="form-group"><label class="form-label">From Date</label><input type="date" name="from_date" class="form-control" value="{{ f_date }}"></div>
            <div class="form-group"><label class="form-label">To Date</label><input type="date" name="to_date" class="form-control" value="{{ t_date }}"></div>
            <button type="submit" class="btn btn-primary"><i class="fas fa-search"></i> Filter Data</button>
            <button type="button" class="btn btn-outline" onclick="window.print()"><i class="fas fa-print"></i> Print</button>
        </form>
    </div>
    <div class="card">
        {% if has_data %}
            <div class="table-responsive"><table class="datatable"><thead><tr>{% for h in headers %}<th>{{ h }}</th>{% endfor %}</tr></thead><tbody>{% for row in rows %}<tr>{% for cell in row %}<td>{{ cell | safe }}</td>{% endfor %}</tr>{% endfor %}</tbody></table></div>
        {% else %}
            <div style="padding:40px; text-align:center; color:#dc2626; font-weight:bold; font-size:16px;"><i class="fas fa-box-open" style="font-size:40px; margin-bottom:10px; color:#fca5a5; display:block;"></i>No Data Found.</div>
        {% endif %}
    </div>
    """
    return render_page(page_title, render_template_string(html, has_data=data_found, headers=table_headers, rows=table_rows, f_date=f_date, t_date=t_date))

# ==========================================
# 🔍 15. FOOTER TRACKING ENGINE
# ==========================================
@app.route('/track_doc', methods=['POST'])
@login_required
def track_doc():
    doc_no = request.form.get('awb', '').strip().upper(); doc_type = request.form.get('doc_type', '')
    error_html = "<html><body style='font-family:Tahoma; padding:20px; background:#fee2e2; color:#991b1b; border:1px solid #ef4444; text-align:center; border-radius:8px;'><h2>Error!</h2><p>{}</p><br><button onclick='window.close()' style='padding:8px 15px; cursor:pointer; background:#ef4444; color:white; border:none; border-radius:4px;'>Close</button></body></html>"
    view_html = """<html><head><title>{{ title }}</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"><style>body { font-family: 'Inter', sans-serif; background: #f1f5f9; padding: 30px; color: #1e293b; } .card { background: white; border-radius: 12px; padding: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); max-width: 900px; margin: 0 auto; border-top: 4px solid #2563eb; } h2 { margin-top: 0; color: #0f172a; text-transform: uppercase; font-size: 20px; border-bottom: 2px solid #e2e8f0; padding-bottom: 15px; } .info-box { background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 6px; margin-bottom: 20px; font-weight: 600; color: #b45309; } table { width: 100%; border-collapse: collapse; margin-top: 15px; } th { background: #f8fafc; color: #475569; padding: 12px; text-align: left; font-size: 13px; text-transform: uppercase; border-bottom: 2px solid #e2e8f0; } td { padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; } .btn { background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 6px; font-weight: 600; cursor: pointer; margin-top: 20px; } .btn:hover { background: #1d4ed8; }</style></head><body><div class="card"><h2>{{ title }}</h2><div class="info-box">{{ info_html | safe }}</div>{% if rows %}<table><tr>{% for h in headers %}<th>{{ h }}</th>{% endfor %}</tr>{% for r in rows %}<tr>{% for c in r %}<td>{{ c }}</td>{% endfor %}</tr>{% endfor %}</table>{% endif %}<div style="text-align:right;"><button class="btn" onclick="window.close()">Close Window</button></div></div></body></html>"""
    
    if not doc_no: return error_html.format("Please enter a Document Number.")
    conn = get_db()
    try:
        with conn.cursor() as c:
            if doc_type == 'c_note' or doc_type == 'pkg_slip': return redirect(url_for('track', awb=doc_no))
            elif doc_type == 'drs':
                c.execute("SELECT * FROM drs WHERE drs_no=%s OR id=%s", (doc_no, doc_no.replace('DRS', '').strip() if doc_no.replace('DRS', '').strip().isdigit() else None))
                drs = c.fetchone()
                if drs:
                    c.execute("SELECT s.awb_no, di.receiver_name, s.dest_address, di.status FROM drs_items di JOIN shipments s ON s.id=di.shipment_id WHERE di.drs_id=%s", (drs['id'],))
                    items = c.fetchall()
                    info = f"DRS No: {drs['drs_no']} &nbsp;|&nbsp; Rider: {drs['rider_name']} &nbsp;|&nbsp; Area: {drs['vehicle_no']} &nbsp;|&nbsp; Status: {drs['status']}"
                    headers = ["AWB No", "Receiver", "Address", "Status"]
                    rows = [[i['awb_no'], i['receiver_name'], i['dest_address'], i['status']] for i in items]
                    return render_template_string(view_html, title="D.R.S. Details", info_html=info, headers=headers, rows=rows)
                return error_html.format("DRS not found.")
            elif doc_type == 'm_fest':
                c.execute("SELECT * FROM manifests WHERE manifest_no=%s OR id=%s", (doc_no, doc_no.replace('MF', '').strip() if doc_no.replace('MF', '').strip().isdigit() else None))
                m = c.fetchone()
                if m:
                    c.execute("SELECT s.awb_no, s.dest_name, s.weight_kg FROM manifest_items mi JOIN shipments s ON s.id=mi.shipment_id WHERE mi.manifest_id=%s", (m['id'],))
                    items = c.fetchall()
                    info = f"Manifest No: {m['manifest_no']} &nbsp;|&nbsp; Route: {m['from_location']} ➔ {m['to_location']} &nbsp;|&nbsp; Status: {m['status']}"
                    headers = ["AWB No", "Consignee", "Weight (KG)"]
                    rows = [[i['awb_no'], i['dest_name'], i['weight_kg']] for i in items]
                    return render_template_string(view_html, title="Manifest Details", info_html=info, headers=headers, rows=rows)
                return error_html.format("Manifest not found.")
            elif doc_type == 'invoice':
                c.execute("SELECT id FROM invoices WHERE invoice_no=%s OR id=%s", (doc_no, doc_no.replace('INV/', '').strip() if doc_no.replace('INV/', '').strip().isdigit() else None))
                inv = c.fetchone()
                if inv: return redirect(f"/print/invoice/{inv['id']}")
                return error_html.format("Invoice not found.")
            elif doc_type == 'network':
                c.execute("SELECT awb_no, network, network_awb, destination, entry_date FROM outward_register WHERE awb_no=%s AND network != 'SELF'", (doc_no,))
                net = c.fetchone()
                if net:
                    info = f"Forwarding Information for AWB: {net['awb_no']}"
                    headers = ["Network", "Tracking ID", "Dest", "Date"]
                    rows = [[net['network'], net['network_awb'], net['destination'], net['entry_date']]]
                    return render_template_string(view_html, title="Network Status", info_html=info, headers=headers, rows=rows)
                return error_html.format("No network forwarding found.")
            elif doc_type == 'pincode':
                c.execute("SELECT awb_no, dest_name, dest_address, current_location, status FROM shipments WHERE dest_address LIKE %s OR dest_station LIKE %s ORDER BY id DESC LIMIT 100", (f"%{doc_no}%", f"%{doc_no}%"))
                pins = c.fetchall()
                if pins:
                    info = f"Recent shipments matching: '{doc_no}'"
                    headers = ["AWB No", "Receiver", "Address", "Hub", "Status"]
                    rows = [[p['awb_no'], p['dest_name'], p['dest_address'], p['current_location'], p['status']] for p in pins]
                    return render_template_string(view_html, title="Pincode Search", info_html=info, headers=headers, rows=rows)
                return error_html.format("No shipments found.")
    except Exception as e: return error_html.format(str(e))
    finally: conn.close()
    return error_html.format("Invalid request.")

# ==========================================
# 🖨️ 16. PDF LABEL & RECEIPT GENERATOR
# ==========================================
@app.route('/print/label/<awb>')
@login_required
def print_label(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
        s = c.fetchone()
        if not s: return "Shipment Not Found"
        c.execute("SELECT * FROM customers WHERE id=%s", (s['customer_id'],))
        cust = c.fetchone()
    conn.close()

    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=(4*inch, 6*inch))
    cv.setStrokeColor(HexColor("#000000")); cv.setLineWidth(1.5)
    cv.roundRect(4*mm, 4*mm, 93*mm, 144*mm, 2*mm)
    cv.setLineWidth(1); cv.line(4*mm, 130*mm, 97*mm, 130*mm)
    cv.setFillColor(HexColor("#000000")); cv.rect(33*mm, 130*mm, 64*mm, 18*mm, fill=1, stroke=0)
    cv.setFont("Helvetica-BoldOblique", 18); cv.setFillColor(HexColor("#FFFFFF"))
    cv.drawString(38*mm, 136*mm, "AGC")
    cv.setFont("Helvetica-Bold", 12); cv.setFillColor(HexColor("#000000"))
    cv.drawCentredString(50*mm, 141*mm, get_setting("company_name", "AGC COURIER"))
    cv.setFont("Helvetica-Bold", 8); cv.setFillColor(HexColor("#475569"))
    cv.drawCentredString(50*mm, 135*mm, "PRE-PAID" if s['cod_amount'] == 0 else f"COD: Rs {s['cod_amount']}")
    
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica", 8)
    cv.drawString(8*mm, 124*mm, "Shipper / Origin:")
    cv.setFont("Helvetica-Bold", 11)
    cv.drawString(8*mm, 118*mm, (cust['name'] if cust else s['origin_name'])[:25])
    
    cv.setLineWidth(1); cv.roundRect(6*mm, 52*mm, 89*mm, 60*mm, 2*mm, fill=0, stroke=1)
    cv.setFillColor(HexColor("#000000")); cv.rect(6*mm, 104*mm, 89*mm, 8*mm, fill=1, stroke=0)
    cv.setFont("Helvetica-Bold", 9); cv.setFillColor(HexColor("#FFFFFF"))
    cv.drawString(8*mm, 106*mm, "DELIVER TO (CONSIGNEE DETAILS):")
    
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 10)
    cv.drawString(8*mm, 95*mm, f"Name: {s['dest_name']}")
    cv.setFont("Helvetica", 9)
    cv.drawString(8*mm, 85*mm, f"Addr: {str(s['dest_address'])[:35]}")
    cv.drawString(8*mm, 75*mm, f"City: {s['dest_station']}")
    cv.drawString(8*mm, 65*mm, f"Phone: {s['dest_phone']}")
    
    cv.roundRect(6*mm, 34*mm, 89*mm, 15*mm, 2*mm, fill=0, stroke=1)
    cv.setFont("Helvetica-Bold", 8)
    cv.drawString(8*mm, 43*mm, f"Date: {s['booking_date']}   |   Pieces: {s['quantity']}")
    cv.drawString(8*mm, 37*mm, f"Weight: {s['weight_kg']} KG   |   Service: {s['service_type']}")
    
    barcode = code128.Code128(awb, barHeight=14*mm, barWidth=0.55*mm)
    barcode.drawOn(cv, 18*mm, 15*mm)
    cv.setFont("Helvetica-Bold", 15); cv.drawCentredString(50.5*mm, 8*mm, awb)
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Label_{awb}.pdf", mimetype='application/pdf')

@app.route('/print/receipt/<awb>')
@login_required
def print_receipt(awb):
    conn = get_db()
    with conn.cursor() as c:
        c.execute("SELECT * FROM shipments WHERE awb_no=%s", (awb,))
        s = c.fetchone()
        if not s: return "Shipment Not Found"
        c.execute("SELECT * FROM customers WHERE id=%s", (s['customer_id'],))
        cust = c.fetchone()
    conn.close()

    buf = io.BytesIO(); cv = canvas.Canvas(buf, pagesize=(A4[0], A4[1]/2))
    w, h = A4[0], A4[1]/2
    
    cv.setFillColor(HexColor("#0f172a")); cv.rect(20, h-50, w-40, 40, fill=1, stroke=0)
    cv.setFillColor(HexColor("#ffffff")); cv.setFont("Helvetica-Bold", 16)
    cv.drawString(30, h-35, get_setting("company_name", "AGC COURIER"))
    cv.setFont("Helvetica", 10); cv.drawString(30, h-45, get_setting("company_address", ""))
    cv.drawRightString(w-30, h-35, "BOOKING RECEIPT")
    cv.drawRightString(w-30, h-45, f"Date: {s['booking_date']}")
    
    cv.setFillColor(HexColor("#000000")); cv.setFont("Helvetica-Bold", 12)
    cv.drawString(30, h-75, f"AWB No: {awb}")
    barcode = code128.Code128(awb, barHeight=30, barWidth=1.2)
    barcode.drawOn(cv, 30, h-115)
    
    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(30, h-140, "CONSIGNOR:")
    cv.setFont("Helvetica", 10)
    cv.drawString(30, h-155, (cust['name'] if cust else s['origin_name']))
    cv.drawString(30, h-170, str(s['origin_phone'] or ''))
    
    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(300, h-140, "CONSIGNEE:")
    cv.setFont("Helvetica", 10)
    cv.drawString(300, h-155, s['dest_name'])
    cv.drawString(300, h-170, f"{s['dest_station']} | Ph: {s['dest_phone']}")
    
    cv.line(30, h-190, w-30, h-190)
    cv.setFont("Helvetica-Bold", 10)
    cv.drawString(30, h-210, f"Weight: {s['weight_kg']} KG | Pieces: {s['quantity']} | Service: {s['service_type']}")
    cv.drawString(300, h-210, f"Grand Total: Rs {s['total_amount']}")
    
    cv.setFont("Helvetica", 8); cv.drawString(30, 30, get_setting("terms_note", ""))
    cv.drawRightString(w-30, 30, "Authorized Signatory")
    
    cv.showPage(); cv.save(); buf.seek(0)
    return send_file(buf, download_name=f"Receipt_{awb}.pdf", mimetype='application/pdf')

# ==========================================
# 🔄 17. UNIVERSAL SYNC API FOR DESKTOP
# ==========================================
@app.route('/api/sync/download', methods=['GET', 'POST'])
def sync_download():
    """ Desktop App ko latest data (all tables) securely bhejne ke liye JSON API. """
    conn = get_db(); response_data = {}
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
                            if isinstance(value, dt.date) or isinstance(value, dt.datetime): clean_row[key] = str(value)
                            else: clean_row[key] = value
                        clean_rows.append(clean_row)
                    response_data[tbl] = clean_rows
                except Exception as e:
                    logging.error(f"Sync error on table {tbl}: {e}"); response_data[tbl] = []
        return jsonify({"success": True, "data": response_data})
    except Exception as e: return jsonify({"success": False, "error": str(e)})
    finally: conn.close()

# ==========================================
# 🚀 DO NOT TOUCH - SERVER LAUNCHER
# ==========================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', debug=True, port=port)
