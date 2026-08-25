# ============================================================
# CGS COURIER ERP - WEB EDITION
# PART 1 - CORE CONFIGURATION, DATABASE & AUTHENTICATION
# ============================================================

import os
import re
import io
import csv
import json
import uuid
import hashlib
import logging
import datetime
from functools import wraps
from decimal import Decimal, InvalidOperation

import pymysql
import pymysql.cursors

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    render_template_string,
    send_file,
    abort
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_BEFORE_PRODUCTION"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

if os.environ.get("FLASK_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("cgs_erp")


# ============================================================
# COMPANY DEFAULTS
# ============================================================

DEFAULT_SETTINGS = {
    "company_name": "CGS COURIER, NOHAR",
    "company_address": "",
    "company_phone": "",
    "company_email": "",
    "company_gstin": "",
    "company_state": "RAJASTHAN",
    "company_state_code": "08",
    "tax_rate": "18",
    "fuel_surcharge": "0",
    "awb_prefix": "CGS",
    "terms_note": (
        "Liability is subject to company terms and conditions."
    ),
    "bank_details": ""
}


# ============================================================
# BASIC HELPER FUNCTIONS
# ============================================================

def safe_float(value, default=0.0):
    """Convert a value to float safely."""

    try:
        if value is None or value == "":
            return float(default)

        return float(value)

    except (
        ValueError,
        TypeError,
        InvalidOperation
    ):
        return float(default)


def safe_int(value, default=0):
    """Convert a value to integer safely."""

    try:
        if value is None or value == "":
            return int(default)

        return int(float(value))

    except (
        ValueError,
        TypeError
    ):
        return int(default)


def sha256_hash(value):
    """Legacy SHA-256 password hash compatibility."""

    value = str(value or "")

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def clean_text(value, max_length=None):
    """Clean basic form text safely."""

    value = str(value or "").strip()

    if max_length:
        value = value[:max_length]

    return value


def normalize_awb(value):
    """Normalize AWB number."""

    value = clean_text(
        value,
        100
    ).upper()

    value = re.sub(
        r"\s+",
        "",
        value
    )

    return value


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

def get_db():
    """
    Return a MySQL connection.

    Environment variables supported:

    DB_HOST
    DB_PORT
    DB_USER
    DB_PASSWORD
    DB_NAME

    Compatible with Render, Aiven, Neon-compatible MySQL services,
    and normal MySQL hosting.
    """

    host = os.environ.get(
        "DB_HOST",
        os.environ.get(
            "MYSQL_HOST",
            "localhost"
        )
    )

    port = safe_int(
        os.environ.get(
            "DB_PORT",
            os.environ.get(
                "MYSQL_PORT",
                "3306"
            )
        ),
        3306
    )

    user = os.environ.get(
        "DB_USER",
        os.environ.get(
            "MYSQL_USER",
            "root"
        )
    )

    password = os.environ.get(
        "DB_PASSWORD",
        os.environ.get(
            "MYSQL_PASSWORD",
            ""
        )
    )

    database = os.environ.get(
        "DB_NAME",
        os.environ.get(
            "MYSQL_DATABASE",
            "agc_erp"
        )
    )

    use_ssl = (
        os.environ.get(
            "DB_SSL",
            "false"
        ).lower()
        in (
            "1",
            "true",
            "yes"
        )
    )

    connection_args = {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
        "charset": "utf8mb4"
    }

    if use_ssl:
        connection_args["ssl"] = {}

    try:
        conn = pymysql.connect(
            **connection_args
        )

        return conn

    except Exception:
        logger.exception(
            "Database connection failed"
        )
        raise


# Backward compatibility.
# The complete code will use get_db(), but this alias prevents
# accidental NameError if an older helper references this name.
get_db_connection = get_db


# ============================================================
# DATABASE QUERY HELPERS
# ============================================================

def db_fetchone(query, params=None):
    """Execute SELECT query and return one row."""

    conn = None
    cursor = None

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            query,
            params or ()
        )

        return cursor.fetchone()

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


def db_fetchall(query, params=None):
    """Execute SELECT query and return all rows."""

    conn = None
    cursor = None

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            query,
            params or ()
        )

        return cursor.fetchall()

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


def db_execute(query, params=None):
    """
    Execute INSERT, UPDATE or DELETE safely.

    Returns:
        {
            "lastrowid": ...,
            "rowcount": ...
        }
    """

    conn = None
    cursor = None

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            query,
            params or ()
        )

        conn.commit()

        return {
            "lastrowid": cursor.lastrowid,
            "rowcount": cursor.rowcount
        }

    except Exception:
        if conn:
            conn.rollback()

        logger.exception(
            "Database execute error"
        )

        raise

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ============================================================
# LOGIN REQUIRED DECORATOR
# ============================================================

def login_required(view):

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        if not session.get("user_id"):

            flash(
                "Please login first.",
                "error"
            )

            return redirect(
                url_for("login")
            )

        return view(
            *args,
            **kwargs
        )

    return wrapped_view


# ============================================================
# ADMIN REQUIRED DECORATOR
# ============================================================

def admin_required(view):

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        if not session.get("user_id"):

            flash(
                "Please login first.",
                "error"
            )

            return redirect(
                url_for("login")
            )

        role = str(
            session.get(
                "role",
                ""
            )
        ).upper()

        if role != "ADMIN":

            flash(
                "Administrator access required.",
                "error"
            )

            return redirect(
                url_for("dashboard")
            )

        return view(
            *args,
            **kwargs
        )

    return wrapped_view


# ============================================================
# PASSWORD COMPATIBILITY
# ============================================================

def verify_password(
    plain_password,
    stored_password
):
    """
    Supports both:
    1. Existing SHA-256 hashes.
    2. New Werkzeug password hashes.

    This prevents existing users from suddenly being unable
    to login after upgrading the ERP.
    """

    plain_password = str(
        plain_password or ""
    )

    stored_password = str(
        stored_password or ""
    )

    if not stored_password:
        return False

    if stored_password == sha256_hash(
        plain_password
    ):
        return True

    try:
        return check_password_hash(
            stored_password,
            plain_password
        )

    except (
        ValueError,
        TypeError
    ):
        return False


# ============================================================
# SETTINGS HELPERS
# ============================================================

def get_setting(key, default=""):

    try:

        row = db_fetchone(
            """
            SELECT value
            FROM settings
            WHERE key_name=%s
            """,
            (key,)
        )

        if (
            row
            and row.get("value") is not None
        ):
            return str(
                row["value"]
            )

    except Exception:
        logger.exception(
            "Unable to read setting: %s",
            key
        )

    return default


def set_setting(key, value):

    db_execute(
        """
        INSERT INTO settings
        (
            key_name,
            value
        )
        VALUES
        (
            %s,
            %s
        )
        ON DUPLICATE KEY UPDATE
            value=VALUES(value)
        """,
        (
            str(key),
            str(value)
        )
    )


# ============================================================
# PAGE RENDERING HELPER
# ============================================================

BASE_HTML = """
<!DOCTYPE html>
<html lang="en">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <title>
        {{ title }} | {{ company_name }}
    </title>

    <script src="https://cdn.tailwindcss.com"></script>

    <link
        rel="stylesheet"
        href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"
    >

    <style>

        body {
            background: #f1f5f9;
        }

        .sidebar-link {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            border-radius: 8px;
            margin-bottom: 4px;
            color: #cbd5e1;
            text-decoration: none;
        }

        .sidebar-link:hover {
            background: #1e293b;
            color: white;
        }

        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow:
                0 1px 3px rgba(0,0,0,.08);
        }

        .btn-primary {
            background: #2563eb;
            color: white;
            padding: 9px 14px;
            border-radius: 8px;
            display: inline-block;
            text-decoration: none;
            border: none;
            cursor: pointer;
        }

        .btn-success {
            background: #16a34a;
            color: white;
            padding: 9px 14px;
            border-radius: 8px;
            display: inline-block;
            text-decoration: none;
            border: none;
            cursor: pointer;
        }

        .btn-danger {
            background: #dc2626;
            color: white;
            padding: 9px 14px;
            border-radius: 8px;
            border: none;
            cursor: pointer;
        }

        input,
        select,
        textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            outline: none;
        }

        input:focus,
        select:focus,
        textarea:focus {
            border-color: #2563eb;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th,
        td {
            padding: 10px;
            border-bottom: 1px solid #e2e8f0;
            text-align: left;
        }

        th {
            background: #f8fafc;
        }

    </style>

</head>

<body>

{% if session.get('user_id') %}

<div class="flex min-h-screen">

    <aside
        class="w-64 bg-slate-900 p-4 hidden md:block"
    >

        <div class="mb-8">

            <h1
                class="text-xl font-bold text-white"
            >
                {{ company_name }}
            </h1>

            <p
                class="text-xs text-slate-400 mt-1"
            >
                Courier ERP
            </p>

        </div>

        <a
            href="/"
            class="sidebar-link"
        >
            <i class="fas fa-chart-line"></i>
            Dashboard
        </a>

        <a
            href="/booking"
            class="sidebar-link"
        >
            <i class="fas fa-plus-circle"></i>
            Booking
        </a>

        <a
            href="/shipments"
            class="sidebar-link"
        >
            <i class="fas fa-box"></i>
            Shipments
        </a>

        <a
            href="/customers"
            class="sidebar-link"
        >
            <i class="fas fa-users"></i>
            Customers
        </a>

        <a
            href="/payments"
            class="sidebar-link"
        >
            <i class="fas fa-money-bill"></i>
            Payments
        </a>

        <a
            href="/invoices"
            class="sidebar-link"
        >
            <i class="fas fa-file-invoice"></i>
            Invoices
        </a>

        <a
            href="/ledger"
            class="sidebar-link"
        >
            <i class="fas fa-book"></i>
            Ledger
        </a>

        <a
            href="/drs"
            class="sidebar-link"
        >
            <i class="fas fa-truck"></i>
            DRS
        </a>

        {% if session.get('role', '').upper() == 'ADMIN' %}

        <a
            href="/users"
            class="sidebar-link"
        >
            <i class="fas fa-user-cog"></i>
            Users
        </a>

        <a
            href="/settings"
            class="sidebar-link"
        >
            <i class="fas fa-gear"></i>
            Settings
        </a>

        {% endif %}

        <a
            href="/logout"
            class="sidebar-link"
        >
            <i class="fas fa-sign-out-alt"></i>
            Logout
        </a>

    </aside>

    <main class="flex-1 p-4 md:p-6">

        <div
            class="flex justify-between items-center mb-6"
        >

            <div>

                <h2
                    class="text-xl font-bold text-slate-800"
                >
                    {{ title }}
                </h2>

                <p
                    class="text-sm text-slate-500"
                >
                    Welcome,
                    {{ session.get('full_name', 'User') }}
                </p>

            </div>

            <div
                class="text-sm text-slate-500"
            >
                {{ current_date }}
            </div>

        </div>

        {% with messages =
            get_flashed_messages(with_categories=true)
        %}

            {% for category, message in messages %}

                <div
                    class="
                        mb-4
                        p-3
                        rounded-lg
                        {% if category == 'success' %}
                            bg-green-100 text-green-800
                        {% else %}
                            bg-red-100 text-red-800
                        {% endif %}
                    "
                >

                    {{ message }}

                </div>

            {% endfor %}

        {% endwith %}

        {{ content | safe }}

    </main>

</div>

{% else %}

{{ content | safe }}

{% endif %}

</body>

</html>
"""


def render_page(
    title,
    content,
    **context
):

    base_context = {
        "title": title,
        "content": content,
        "company_name": get_setting(
            "company_name",
            DEFAULT_SETTINGS["company_name"]
        ),
        "current_date": datetime.datetime.now().strftime(
            "%d-%m-%Y"
        )
    }

    base_context.update(
        context
    )

    return render_template_string(
        BASE_HTML,
        **base_context
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if session.get("user_id"):

        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        username = clean_text(
            request.form.get(
                "username",
                ""
            ),
            100
        )

        password = str(
            request.form.get(
                "password",
                ""
            )
        )

        user = None

        try:

            user = db_fetchone(
                """
                SELECT *
                FROM users
                WHERE username=%s
                AND active=1
                LIMIT 1
                """,
                (username,)
            )

        except Exception:
            logger.exception(
                "Login database error"
            )

            flash(
                "Unable to connect to the database.",
                "error"
            )

        if user and verify_password(
            password,
            user.get(
                "password_hash",
                ""
            )
        ):

            session.clear()

            session.update({
                "user_id": user["id"],
                "username": user["username"],
                "full_name": (
                    user.get("full_name")
                    or user["username"]
                ),
                "role": (
                    user.get("role")
                    or "STAFF"
                ).upper(),
                "branch": (
                    user.get("branch_name")
                    or "HQ"
                ),
                "customer_id": user.get(
                    "customer_id"
                )
            })

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid username or password.",
            "error"
        )

    login_html = """
    <div
        class="
            min-h-screen
            flex
            items-center
            justify-center
            p-4
        "
    >

        <div
            class="
                bg-white
                w-full
                max-w-md
                rounded-2xl
                shadow-lg
                p-8
            "
        >

            <div class="text-center mb-6">

                <h1
                    class="
                        text-2xl
                        font-bold
                        text-slate-800
                    "
                >
                    {{ company_name }}
                </h1>

                <p
                    class="
                        text-sm
                        text-slate-500
                        mt-2
                    "
                >
                    Courier ERP Login
                </p>

            </div>

            <form method="POST">

                <div class="mb-4">

                    <label
                        class="
                            block
                            mb-2
                            text-sm
                            font-medium
                        "
                    >
                        Username
                    </label>

                    <input
                        type="text"
                        name="username"
                        required
                        autocomplete="username"
                    >

                </div>

                <div class="mb-6">

                    <label
                        class="
                            block
                            mb-2
                            text-sm
                            font-medium
                        "
                    >
                        Password
                    </label>

                    <input
                        type="password"
                        name="password"
                        required
                        autocomplete="current-password"
                    >

                </div>

                <button
                    type="submit"
                    class="
                        btn-primary
                        w-full
                    "
                >
                    Login
                </button>

            </form>

        </div>

    </div>
    """

    content = render_template_string(
        login_html,
        company_name=get_setting(
            "company_name",
            DEFAULT_SETTINGS["company_name"]
        )
    )

    return render_page(
        "Login",
        content
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out successfully.",
        "success"
    )

    return redirect(
        url_for("login")
    )


# ============================================================
# PART 1 END
# ============================================================

# ============================================================
# PART 2 - DATABASE INITIALIZATION, AUTO HEAL & CORE HELPERS
# ============================================================

def table_exists(table_name):
    """Check whether a table exists."""

    row = db_fetchone(
        """
        SELECT COUNT(*) AS total
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        AND table_name = %s
        """,
        (table_name,)
    )

    return bool(
        row
        and int(row.get("total", 0)) > 0
    )


def get_table_columns(table_name):
    """Return a set containing existing column names."""

    rows = db_fetchall(
        """
        SELECT COLUMN_NAME
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
        AND table_name = %s
        """,
        (table_name,)
    )

    return {
        row["COLUMN_NAME"]
        for row in rows
    }


def add_column_if_missing(
    table_name,
    column_name,
    column_definition
):
    """
    Add a database column only when it does not already exist.

    Table and column names are controlled internally, while the
    SQL definition is provided by this application only.
    """

    columns = get_table_columns(
        table_name
    )

    if column_name in columns:
        return False

    query = (
        f"ALTER TABLE `{table_name}` "
        f"ADD COLUMN `{column_name}` "
        f"{column_definition}"
    )

    db_execute(query)

    logger.info(
        "Added column %s.%s",
        table_name,
        column_name
    )

    return True


def create_tables():
    """
    Create all core tables.

    Existing tables are not removed.
    The following auto_heal_db() function handles missing columns.
    """

    conn = None
    cursor = None

    try:
        conn = get_db()
        cursor = conn.cursor()

        # ----------------------------------------------------
        # SETTINGS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                key_name VARCHAR(100) NOT NULL UNIQUE,
                value TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # CUSTOMERS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                company_name VARCHAR(255) DEFAULT '',
                phone VARCHAR(50) DEFAULT '',
                email VARCHAR(255) DEFAULT '',
                address TEXT,
                city VARCHAR(100) DEFAULT '',
                state VARCHAR(100) DEFAULT '',
                pincode VARCHAR(20) DEFAULT '',
                gstin VARCHAR(50) DEFAULT '',
                credit_limit DECIMAL(14,2) DEFAULT 0,
                opening_balance DECIMAL(14,2) DEFAULT 0,
                status VARCHAR(30) DEFAULT 'ACTIVE',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # USERS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(500) NOT NULL,
                full_name VARCHAR(255) DEFAULT '',
                role VARCHAR(50) DEFAULT 'STAFF',
                branch_name VARCHAR(255) DEFAULT 'HQ',
                customer_id BIGINT NULL,
                active TINYINT(1) DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # NETWORKS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS networks (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                network_name VARCHAR(255) NOT NULL,
                contact_person VARCHAR(255) DEFAULT '',
                phone VARCHAR(50) DEFAULT '',
                email VARCHAR(255) DEFAULT '',
                address TEXT,
                tracking_url VARCHAR(500) DEFAULT '',
                status VARCHAR(30) DEFAULT 'ACTIVE',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_network_name (network_name)
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # SHIPMENTS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                awb_no VARCHAR(100) NOT NULL UNIQUE,
                booking_date DATE NULL,
                customer_id BIGINT NULL,

                sender_name VARCHAR(255) DEFAULT '',
                sender_phone VARCHAR(50) DEFAULT '',
                sender_address TEXT,

                receiver_name VARCHAR(255) DEFAULT '',
                receiver_phone VARCHAR(50) DEFAULT '',
                receiver_address TEXT,

                origin VARCHAR(150) DEFAULT '',
                destination VARCHAR(150) DEFAULT '',
                pincode VARCHAR(20) DEFAULT '',

                network_id BIGINT NULL,
                network_name VARCHAR(255) DEFAULT '',

                shipment_type VARCHAR(100) DEFAULT '',
                service_type VARCHAR(100) DEFAULT '',

                pieces INT DEFAULT 1,
                actual_weight DECIMAL(12,3) DEFAULT 0,
                chargeable_weight DECIMAL(12,3) DEFAULT 0,

                freight DECIMAL(14,2) DEFAULT 0,
                fuel_charge DECIMAL(14,2) DEFAULT 0,
                other_charge DECIMAL(14,2) DEFAULT 0,
                gst_amount DECIMAL(14,2) DEFAULT 0,
                total_amount DECIMAL(14,2) DEFAULT 0,

                payment_mode VARCHAR(50) DEFAULT 'CASH',
                status VARCHAR(100) DEFAULT 'BOOKED',
                remarks TEXT,

                invoice_id BIGINT NULL,

                created_by BIGINT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,

                INDEX idx_shipments_awb (awb_no),
                INDEX idx_shipments_customer (customer_id),
                INDEX idx_shipments_status (status),
                INDEX idx_shipments_booking_date (booking_date)
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # SHIPMENT TRACKING
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shipment_tracking (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                shipment_id BIGINT NOT NULL,
                status VARCHAR(100) NOT NULL,
                location VARCHAR(255) DEFAULT '',
                remarks TEXT,
                created_by BIGINT NULL,
                tracking_time DATETIME DEFAULT CURRENT_TIMESTAMP,

                INDEX idx_tracking_shipment (shipment_id),
                INDEX idx_tracking_time (tracking_time)
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # PAYMENTS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                receipt_no VARCHAR(100) DEFAULT '',
                customer_id BIGINT NOT NULL,
                amount DECIMAL(14,2) DEFAULT 0,
                payment_mode VARCHAR(50) DEFAULT 'CASH',
                reference_no VARCHAR(255) DEFAULT '',
                payment_date DATE NULL,
                remarks TEXT,
                created_by BIGINT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

                INDEX idx_payments_customer (customer_id),
                INDEX idx_payments_date (payment_date)
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # INVOICES
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                invoice_no VARCHAR(100) NOT NULL UNIQUE,
                customer_id BIGINT NULL,
                invoice_date DATE NULL,
                due_date DATE NULL,

                subtotal DECIMAL(14,2) DEFAULT 0,
                tax_rate DECIMAL(8,2) DEFAULT 0,
                tax_amount DECIMAL(14,2) DEFAULT 0,
                total_amount DECIMAL(14,2) DEFAULT 0,

                status VARCHAR(50) DEFAULT 'UNPAID',
                remarks TEXT,

                created_by BIGINT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

                INDEX idx_invoices_customer (customer_id),
                INDEX idx_invoices_date (invoice_date)
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # INVOICE SHIPMENTS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoice_shipments (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                invoice_id BIGINT NOT NULL,
                shipment_id BIGINT NOT NULL,
                amount DECIMAL(14,2) DEFAULT 0,

                UNIQUE KEY uq_invoice_shipment (
                    invoice_id,
                    shipment_id
                ),

                INDEX idx_invoice_shipments_invoice (
                    invoice_id
                ),

                INDEX idx_invoice_shipments_shipment (
                    shipment_id
                )
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # DRS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                drs_no VARCHAR(100) NOT NULL UNIQUE,
                drs_date DATE NULL,
                destination VARCHAR(150) DEFAULT '',
                delivery_boy VARCHAR(255) DEFAULT '',
                phone VARCHAR(50) DEFAULT '',
                status VARCHAR(50) DEFAULT 'OPEN',
                remarks TEXT,
                created_by BIGINT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # DRS SHIPMENTS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drs_shipments (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                drs_id BIGINT NOT NULL,
                shipment_id BIGINT NOT NULL,
                delivery_status VARCHAR(100) DEFAULT 'OUT FOR DELIVERY',
                remarks TEXT,
                delivered_at DATETIME NULL,

                UNIQUE KEY uq_drs_shipment (
                    drs_id,
                    shipment_id
                ),

                INDEX idx_drs_shipments_drs (drs_id),
                INDEX idx_drs_shipments_shipment (shipment_id)
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        # ----------------------------------------------------
        # STAFF
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS staff (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                phone VARCHAR(50) DEFAULT '',
                email VARCHAR(255) DEFAULT '',
                address TEXT,
                designation VARCHAR(100) DEFAULT '',
                salary DECIMAL(14,2) DEFAULT 0,
                status VARCHAR(30) DEFAULT 'ACTIVE',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
            DEFAULT CHARSET=utf8mb4
        """)

        conn.commit()

        logger.info(
            "Core database tables checked successfully."
        )

    except Exception:
        if conn:
            conn.rollback()

        logger.exception(
            "Unable to create database tables."
        )

        raise

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


def auto_heal_db():
    """
    Add important missing columns to existing databases.

    This makes the application compatible with an older database
    without deleting existing data.
    """

    schema = {
        "settings": {
            "key_name": "VARCHAR(100) NOT NULL",
            "value": "TEXT NULL"
        },

        "customers": {
            "name": "VARCHAR(255) DEFAULT ''",
            "company_name": "VARCHAR(255) DEFAULT ''",
            "phone": "VARCHAR(50) DEFAULT ''",
            "email": "VARCHAR(255) DEFAULT ''",
            "address": "TEXT NULL",
            "city": "VARCHAR(100) DEFAULT ''",
            "state": "VARCHAR(100) DEFAULT ''",
            "pincode": "VARCHAR(20) DEFAULT ''",
            "gstin": "VARCHAR(50) DEFAULT ''",
            "credit_limit": "DECIMAL(14,2) DEFAULT 0",
            "opening_balance": "DECIMAL(14,2) DEFAULT 0",
            "status": "VARCHAR(30) DEFAULT 'ACTIVE'"
        },

        "users": {
            "username": "VARCHAR(100) DEFAULT ''",
            "password_hash": "VARCHAR(500) DEFAULT ''",
            "full_name": "VARCHAR(255) DEFAULT ''",
            "role": "VARCHAR(50) DEFAULT 'STAFF'",
            "branch_name": "VARCHAR(255) DEFAULT 'HQ'",
            "customer_id": "BIGINT NULL",
            "active": "TINYINT(1) DEFAULT 1"
        },

        "networks": {
            "network_name": "VARCHAR(255) DEFAULT ''",
            "contact_person": "VARCHAR(255) DEFAULT ''",
            "phone": "VARCHAR(50) DEFAULT ''",
            "email": "VARCHAR(255) DEFAULT ''",
            "address": "TEXT NULL",
            "tracking_url": "VARCHAR(500) DEFAULT ''",
            "status": "VARCHAR(30) DEFAULT 'ACTIVE'"
        },

        "shipments": {
            "awb_no": "VARCHAR(100) DEFAULT ''",
            "booking_date": "DATE NULL",
            "customer_id": "BIGINT NULL",
            "sender_name": "VARCHAR(255) DEFAULT ''",
            "sender_phone": "VARCHAR(50) DEFAULT ''",
            "sender_address": "TEXT NULL",
            "receiver_name": "VARCHAR(255) DEFAULT ''",
            "receiver_phone": "VARCHAR(50) DEFAULT ''",
            "receiver_address": "TEXT NULL",
            "origin": "VARCHAR(150) DEFAULT ''",
            "destination": "VARCHAR(150) DEFAULT ''",
            "pincode": "VARCHAR(20) DEFAULT ''",
            "network_id": "BIGINT NULL",
            "network_name": "VARCHAR(255) DEFAULT ''",
            "shipment_type": "VARCHAR(100) DEFAULT ''",
            "service_type": "VARCHAR(100) DEFAULT ''",
            "pieces": "INT DEFAULT 1",
            "actual_weight": "DECIMAL(12,3) DEFAULT 0",
            "chargeable_weight": "DECIMAL(12,3) DEFAULT 0",
            "freight": "DECIMAL(14,2) DEFAULT 0",
            "fuel_charge": "DECIMAL(14,2) DEFAULT 0",
            "other_charge": "DECIMAL(14,2) DEFAULT 0",
            "gst_amount": "DECIMAL(14,2) DEFAULT 0",
            "total_amount": "DECIMAL(14,2) DEFAULT 0",
            "payment_mode": "VARCHAR(50) DEFAULT 'CASH'",
            "status": "VARCHAR(100) DEFAULT 'BOOKED'",
            "remarks": "TEXT NULL",
            "invoice_id": "BIGINT NULL",
            "created_by": "BIGINT NULL"
        },

        "shipment_tracking": {
            "shipment_id": "BIGINT NULL",
            "status": "VARCHAR(100) DEFAULT ''",
            "location": "VARCHAR(255) DEFAULT ''",
            "remarks": "TEXT NULL",
            "created_by": "BIGINT NULL",
            "tracking_time": "DATETIME NULL"
        },

        "payments": {
            "receipt_no": "VARCHAR(100) DEFAULT ''",
            "customer_id": "BIGINT NULL",
            "amount": "DECIMAL(14,2) DEFAULT 0",
            "payment_mode": "VARCHAR(50) DEFAULT 'CASH'",
            "reference_no": "VARCHAR(255) DEFAULT ''",
            "payment_date": "DATE NULL",
            "remarks": "TEXT NULL",
            "created_by": "BIGINT NULL"
        },

        "invoices": {
            "invoice_no": "VARCHAR(100) DEFAULT ''",
            "customer_id": "BIGINT NULL",
            "invoice_date": "DATE NULL",
            "due_date": "DATE NULL",
            "subtotal": "DECIMAL(14,2) DEFAULT 0",
            "tax_rate": "DECIMAL(8,2) DEFAULT 0",
            "tax_amount": "DECIMAL(14,2) DEFAULT 0",
            "total_amount": "DECIMAL(14,2) DEFAULT 0",
            "status": "VARCHAR(50) DEFAULT 'UNPAID'",
            "remarks": "TEXT NULL",
            "created_by": "BIGINT NULL"
        },

        "staff": {
            "name": "VARCHAR(255) DEFAULT ''",
            "phone": "VARCHAR(50) DEFAULT ''",
            "email": "VARCHAR(255) DEFAULT ''",
            "address": "TEXT NULL",
            "designation": "VARCHAR(100) DEFAULT ''",
            "salary": "DECIMAL(14,2) DEFAULT 0",
            "status": "VARCHAR(30) DEFAULT 'ACTIVE'"
        }
    }

    for table_name, columns in schema.items():

        if not table_exists(table_name):
            continue

        for column_name, definition in columns.items():

            try:

                add_column_if_missing(
                    table_name,
                    column_name,
                    definition
                )

            except Exception:

                logger.exception(
                    "Auto-heal failed for %s.%s",
                    table_name,
                    column_name
                )


def ensure_default_settings():
    """Insert default company settings if missing."""

    for key, value in DEFAULT_SETTINGS.items():

        row = db_fetchone(
            """
            SELECT id
            FROM settings
            WHERE key_name=%s
            LIMIT 1
            """,
            (key,)
        )

        if not row:

            db_execute(
                """
                INSERT INTO settings
                (
                    key_name,
                    value
                )
                VALUES
                (
                    %s,
                    %s
                )
                """,
                (
                    key,
                    value
                )
            )


def ensure_default_admin():
    """
    Create default administrator only if no admin user exists.

    Default credentials:
    Username: admin
    Password: admin123

    Change the password after first login.
    """

    admin = db_fetchone(
        """
        SELECT id
        FROM users
        WHERE UPPER(role)='ADMIN'
        LIMIT 1
        """
    )

    if admin:
        return

    existing_user = db_fetchone(
        """
        SELECT id
        FROM users
        WHERE username=%s
        LIMIT 1
        """,
        ("admin",)
    )

    password_hash = generate_password_hash(
        "admin123"
    )

    if existing_user:

        db_execute(
            """
            UPDATE users
            SET
                password_hash=%s,
                role='ADMIN',
                active=1
            WHERE id=%s
            """,
            (
                password_hash,
                existing_user["id"]
            )
        )

    else:

        db_execute(
            """
            INSERT INTO users
            (
                username,
                password_hash,
                full_name,
                role,
                branch_name,
                active
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                "admin",
                password_hash,
                "Administrator",
                "ADMIN",
                "HQ",
                1
            )
        )

    logger.info(
        "Default administrator ensured."
    )


def generate_next_number(
    table_name,
    column_name,
    prefix,
    digits=6
):
    """
    Generate a sequential document number.

    Example:
    CGS000001
    INV-000001
    DRS-000001

    Only internally controlled table and column names should
    be passed to this helper.
    """

    allowed_tables = {
        "shipments",
        "invoices",
        "payments",
        "drs"
    }

    if table_name not in allowed_tables:

        raise ValueError(
            "Invalid table for sequence generation."
        )

    row = db_fetchone(
        f"""
        SELECT id
        FROM `{table_name}`
        ORDER BY id DESC
        LIMIT 1
        """
    )

    next_id = 1

    if row and row.get("id"):

        next_id = (
            safe_int(
                row["id"],
                0
            )
            + 1
        )

    return (
        f"{prefix}"
        f"{next_id:0{digits}d}"
    )


def generate_awb():

    prefix = clean_text(
        get_setting(
            "awb_prefix",
            DEFAULT_SETTINGS["awb_prefix"]
        ),
        20
    ).upper()

    if not prefix:
        prefix = "CGS"

    return generate_next_number(
        "shipments",
        "awb_no",
        prefix,
        8
    )


def generate_invoice_no():

    return generate_next_number(
        "invoices",
        "invoice_no",
        "INV-",
        6
    )


def generate_receipt_no():

    return generate_next_number(
        "payments",
        "receipt_no",
        "RCT-",
        6
    )


def generate_drs_no():

    return generate_next_number(
        "drs",
        "drs_no",
        "DRS-",
        6
    )


def get_customer_by_id(customer_id):

    customer_id = safe_int(
        customer_id
    )

    if customer_id <= 0:
        return None

    return db_fetchone(
        """
        SELECT *
        FROM customers
        WHERE id=%s
        LIMIT 1
        """,
        (customer_id,)
    )


def get_shipment_by_id(shipment_id):

    shipment_id = safe_int(
        shipment_id
    )

    if shipment_id <= 0:
        return None

    return db_fetchone(
        """
        SELECT *
        FROM shipments
        WHERE id=%s
        LIMIT 1
        """,
        (shipment_id,)
    )


def get_shipment_by_awb(awb_no):

    awb_no = normalize_awb(
        awb_no
    )

    if not awb_no:
        return None

    return db_fetchone(
        """
        SELECT *
        FROM shipments
        WHERE awb_no=%s
        LIMIT 1
        """,
        (awb_no,)
    )


def calculate_shipment_amounts(
    freight,
    fuel_charge,
    other_charge,
    tax_rate
):
    """
    Calculate shipment charges consistently.
    """

    freight = safe_float(
        freight
    )

    fuel_charge = safe_float(
        fuel_charge
    )

    other_charge = safe_float(
        other_charge
    )

    tax_rate = safe_float(
        tax_rate
    )

    subtotal = (
        freight
        + fuel_charge
        + other_charge
    )

    gst_amount = round(
        subtotal
        * tax_rate
        / 100,
        2
    )

    total_amount = round(
        subtotal
        + gst_amount,
        2
    )

    return {
        "freight": freight,
        "fuel_charge": fuel_charge,
        "other_charge": other_charge,
        "subtotal": round(
            subtotal,
            2
        ),
        "tax_rate": tax_rate,
        "gst_amount": gst_amount,
        "total_amount": total_amount
    }


def initialize_database():
    """
    Complete safe initialization sequence.

    1. Create missing tables.
    2. Add important missing columns.
    3. Add default settings.
    4. Ensure one administrator exists.
    """

    logger.info(
        "Starting database initialization."
    )

    create_tables()

    auto_heal_db()

    ensure_default_settings()

    ensure_default_admin()

    logger.info(
        "Database initialization completed."
    )


# ============================================================
# PART 2 END
# ============================================================

# ============================================================
# PART 3 - DASHBOARD & CUSTOMER MANAGEMENT
# ============================================================


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
@login_required
def dashboard():

    today = datetime.date.today()

    stats = {
        "total_shipments": 0,
        "today_shipments": 0,
        "total_customers": 0,
        "pending_amount": 0.0
    }

    try:

        row = db_fetchone("""
            SELECT COUNT(*) AS total
            FROM shipments
        """)

        if row:
            stats["total_shipments"] = safe_int(
                row.get("total", 0)
            )

        row = db_fetchone("""
            SELECT COUNT(*) AS total
            FROM shipments
            WHERE booking_date=%s
        """, (today,))

        if row:
            stats["today_shipments"] = safe_int(
                row.get("total", 0)
            )

        row = db_fetchone("""
            SELECT COUNT(*) AS total
            FROM customers
            WHERE status='ACTIVE'
        """)

        if row:
            stats["total_customers"] = safe_int(
                row.get("total", 0)
            )

        row = db_fetchone("""
            SELECT COALESCE(
                SUM(total_amount),
                0
            ) AS total
            FROM invoices
            WHERE status IN (
                'UNPAID',
                'PARTIAL'
            )
        """)

        if row:
            stats["pending_amount"] = safe_float(
                row.get("total", 0)
            )

        recent_shipments = db_fetchall("""
            SELECT
                s.id,
                s.awb_no,
                s.booking_date,
                s.sender_name,
                s.receiver_name,
                s.destination,
                s.total_amount,
                s.status,
                c.name AS customer_name
            FROM shipments s
            LEFT JOIN customers c
                ON c.id=s.customer_id
            ORDER BY s.id DESC
            LIMIT 10
        """)

    except Exception:

        logger.exception(
            "Dashboard data loading failed."
        )

        recent_shipments = []

    dashboard_html = """
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">

        <div class="card">
            <div class="text-sm text-slate-500">
                Total Shipments
            </div>

            <div class="text-3xl font-bold text-slate-800 mt-2">
                {{ stats.total_shipments }}
            </div>
        </div>

        <div class="card">
            <div class="text-sm text-slate-500">
                Today's Bookings
            </div>

            <div class="text-3xl font-bold text-blue-600 mt-2">
                {{ stats.today_shipments }}
            </div>
        </div>

        <div class="card">
            <div class="text-sm text-slate-500">
                Active Customers
            </div>

            <div class="text-3xl font-bold text-green-600 mt-2">
                {{ stats.total_customers }}
            </div>
        </div>

        <div class="card">
            <div class="text-sm text-slate-500">
                Pending Invoice Amount
            </div>

            <div class="text-2xl font-bold text-red-600 mt-2">
                ₹ {{ "%.2f"|format(stats.pending_amount) }}
            </div>
        </div>

    </div>


    <div class="grid grid-cols-1 xl:grid-cols-3 gap-6">

        <div class="xl:col-span-2 card">

            <div class="flex justify-between items-center mb-4">

                <h3 class="text-lg font-bold text-slate-800">
                    Recent Shipments
                </h3>

                <a
                    href="/shipments"
                    class="text-sm text-blue-600"
                >
                    View All
                </a>

            </div>

            <div class="overflow-x-auto">

                <table>

                    <thead>

                        <tr>
                            <th>AWB</th>
                            <th>Customer</th>
                            <th>Receiver</th>
                            <th>Destination</th>
                            <th>Amount</th>
                            <th>Status</th>
                        </tr>

                    </thead>

                    <tbody>

                    {% if recent_shipments %}

                        {% for shipment in recent_shipments %}

                        <tr>

                            <td class="font-medium">
                                {{ shipment.awb_no }}
                            </td>

                            <td>
                                {{ shipment.customer_name or '-' }}
                            </td>

                            <td>
                                {{ shipment.receiver_name or '-' }}
                            </td>

                            <td>
                                {{ shipment.destination or '-' }}
                            </td>

                            <td>
                                ₹ {{ "%.2f"|format(
                                    shipment.total_amount or 0
                                ) }}
                            </td>

                            <td>

                                <span class="text-sm">

                                    {{ shipment.status or 'BOOKED' }}

                                </span>

                            </td>

                        </tr>

                        {% endfor %}

                    {% else %}

                        <tr>

                            <td
                                colspan="6"
                                class="
                                    text-center
                                    text-slate-500
                                    py-8
                                "
                            >
                                No shipments found.
                            </td>

                        </tr>

                    {% endif %}

                    </tbody>

                </table>

            </div>

        </div>


        <div class="card">

            <h3 class="text-lg font-bold text-slate-800 mb-4">
                Quick Actions
            </h3>

            <div class="space-y-3">

                <a
                    href="/booking"
                    class="
                        btn-primary
                        w-full
                        text-center
                    "
                >
                    <i class="fas fa-plus-circle"></i>
                    New Booking
                </a>

                <a
                    href="/customers/add"
                    class="
                        btn-success
                        w-full
                        text-center
                    "
                >
                    <i class="fas fa-user-plus"></i>
                    Add Customer
                </a>

                <a
                    href="/shipments"
                    class="
                        block
                        w-full
                        text-center
                        border
                        border-slate-300
                        rounded-lg
                        p-2
                        hover:bg-slate-50
                    "
                >
                    <i class="fas fa-search"></i>
                    Search Shipment
                </a>

            </div>

        </div>

    </div>
    """

    content = render_template_string(
        dashboard_html,
        stats=stats,
        recent_shipments=recent_shipments
    )

    return render_page(
        "Dashboard",
        content
    )


# ============================================================
# CUSTOMER LIST
# ============================================================

@app.route("/customers")
@login_required
def customers():

    search = clean_text(
        request.args.get(
            "search",
            ""
        ),
        100
    )

    query = """
        SELECT
            c.*,

            (
                SELECT COUNT(*)
                FROM shipments s
                WHERE s.customer_id=c.id
            ) AS shipment_count

        FROM customers c
    """

    params = []

    if search:

        like_value = f"%{search}%"

        query += """
            WHERE
                c.name LIKE %s
                OR c.company_name LIKE %s
                OR c.phone LIKE %s
                OR c.email LIKE %s
                OR c.city LIKE %s
        """

        params = [
            like_value,
            like_value,
            like_value,
            like_value,
            like_value
        ]

    query += """
        ORDER BY c.id DESC
    """

    try:

        customer_rows = db_fetchall(
            query,
            tuple(params)
        )

    except Exception:

        logger.exception(
            "Customer list loading failed."
        )

        customer_rows = []

        flash(
            "Unable to load customers.",
            "error"
        )

    customers_html = """
    <div class="card">

        <div
            class="
                flex
                flex-col
                md:flex-row
                justify-between
                gap-4
                mb-5
            "
        >

            <form
                method="GET"
                class="
                    flex
                    gap-2
                    w-full
                    md:max-w-xl
                "
            >

                <input
                    type="text"
                    name="search"
                    value="{{ search }}"
                    placeholder="
                        Search name, company,
                        phone, email or city
                    "
                >

                <button
                    type="submit"
                    class="btn-primary"
                >
                    <i class="fas fa-search"></i>
                </button>

            </form>

            <a
                href="/customers/add"
                class="
                    btn-success
                    whitespace-nowrap
                    text-center
                "
            >
                <i class="fas fa-user-plus"></i>
                Add Customer
            </a>

        </div>


        <div class="overflow-x-auto">

            <table>

                <thead>

                    <tr>
                        <th>ID</th>
                        <th>Customer</th>
                        <th>Company</th>
                        <th>Phone</th>
                        <th>City</th>
                        <th>GSTIN</th>
                        <th>Shipments</th>
                        <th>Status</th>
                        <th>Action</th>
                    </tr>

                </thead>

                <tbody>

                {% if customers %}

                    {% for customer in customers %}

                    <tr>

                        <td>
                            {{ customer.id }}
                        </td>

                        <td class="font-medium">
                            {{ customer.name }}
                        </td>

                        <td>
                            {{ customer.company_name or '-' }}
                        </td>

                        <td>
                            {{ customer.phone or '-' }}
                        </td>

                        <td>
                            {{ customer.city or '-' }}
                        </td>

                        <td>
                            {{ customer.gstin or '-' }}
                        </td>

                        <td>
                            {{ customer.shipment_count }}
                        </td>

                        <td>

                            {% if customer.status == 'ACTIVE' %}

                                <span
                                    class="
                                        text-green-600
                                        font-medium
                                    "
                                >
                                    ACTIVE
                                </span>

                            {% else %}

                                <span
                                    class="
                                        text-red-600
                                        font-medium
                                    "
                                >
                                    {{ customer.status }}
                                </span>

                            {% endif %}

                        </td>

                        <td>

                            <div
                                class="
                                    flex
                                    gap-2
                                    items-center
                                "
                            >

                                <a
                                    href="/customers/edit/{{ customer.id }}"
                                    class="
                                        text-blue-600
                                    "
                                    title="Edit Customer"
                                >
                                    <i
                                        class="fas fa-edit"
                                    ></i>
                                </a>

                                {% if
                                    session.get(
                                        'role',
                                        ''
                                    ).upper() == 'ADMIN'
                                %}

                                <form
                                    method="POST"
                                    action="/customers/delete/{{ customer.id }}"
                                    onsubmit="
                                        return confirm(
                                            'Delete this customer?'
                                        );
                                    "
                                >

                                    <button
                                        type="submit"
                                        class="
                                            text-red-600
                                        "
                                        title="Delete Customer"
                                    >
                                        <i
                                            class="fas fa-trash"
                                        ></i>
                                    </button>

                                </form>

                                {% endif %}

                            </div>

                        </td>

                    </tr>

                    {% endfor %}

                {% else %}

                    <tr>

                        <td
                            colspan="9"
                            class="
                                text-center
                                text-slate-500
                                py-8
                            "
                        >
                            No customers found.
                        </td>

                    </tr>

                {% endif %}

                </tbody>

            </table>

        </div>

    </div>
    """

    content = render_template_string(
        customers_html,
        customers=customer_rows,
        search=search
    )

    return render_page(
        "Customers",
        content
    )


# ============================================================
# CUSTOMER FORM HTML
# ============================================================

def customer_form_html(
    customer=None,
    action_url="/customers/add"
):

    customer = customer or {}

    form_html = """
    <div class="max-w-5xl mx-auto">

        <form
            method="POST"
            action="{{ action_url }}"
            class="card"
        >

            <div
                class="
                    grid
                    grid-cols-1
                    md:grid-cols-2
                    gap-5
                "
            >

                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Customer Name *
                    </label>

                    <input
                        type="text"
                        name="name"
                        value="{{ customer.get('name', '') }}"
                        required
                    >

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Company Name
                    </label>

                    <input
                        type="text"
                        name="company_name"
                        value="{{ customer.get('company_name', '') }}"
                    >

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Phone
                    </label>

                    <input
                        type="text"
                        name="phone"
                        value="{{ customer.get('phone', '') }}"
                    >

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Email
                    </label>

                    <input
                        type="email"
                        name="email"
                        value="{{ customer.get('email', '') }}"
                    >

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        GSTIN
                    </label>

                    <input
                        type="text"
                        name="gstin"
                        value="{{ customer.get('gstin', '') }}"
                        maxlength="50"
                        style="text-transform:uppercase"
                    >

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Credit Limit
                    </label>

                    <input
                        type="number"
                        name="credit_limit"
                        min="0"
                        step="0.01"
                        value="{{ customer.get('credit_limit', 0) }}"
                    >

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Opening Balance
                    </label>

                    <input
                        type="number"
                        name="opening_balance"
                        step="0.01"
                        value="{{ customer.get('opening_balance', 0) }}"
                    >

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Status
                    </label>

                    <select name="status">

                        <option
                            value="ACTIVE"
                            {% if
                                customer.get(
                                    'status',
                                    'ACTIVE'
                                ) == 'ACTIVE'
                            %}
                                selected
                            {% endif %}
                        >
                            ACTIVE
                        </option>

                        <option
                            value="INACTIVE"
                            {% if
                                customer.get(
                                    'status',
                                    ''
                                ) == 'INACTIVE'
                            %}
                                selected
                            {% endif %}
                        >
                            INACTIVE
                        </option>

                    </select>

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        City
                    </label>

                    <input
                        type="text"
                        name="city"
                        value="{{ customer.get('city', '') }}"
                    >

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        State
                    </label>

                    <input
                        type="text"
                        name="state"
                        value="{{ customer.get('state', '') }}"
                    >

                </div>


                <div class="md:col-span-2">

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Address
                    </label>

                    <textarea
                        name="address"
                        rows="3"
                    >{{ customer.get('address', '') }}</textarea>

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Pincode
                    </label>

                    <input
                        type="text"
                        name="pincode"
                        value="{{ customer.get('pincode', '') }}"
                        maxlength="20"
                    >

                </div>

            </div>


            <div
                class="
                    flex
                    justify-end
                    gap-3
                    mt-6
                "
            >

                <a
                    href="/customers"
                    class="
                        border
                        border-slate-300
                        px-4
                        py-2
                        rounded-lg
                    "
                >
                    Cancel
                </a>

                <button
                    type="submit"
                    class="btn-primary"
                >
                    <i class="fas fa-save"></i>
                    Save Customer
                </button>

            </div>

        </form>

    </div>
    """

    return render_template_string(
        form_html,
        customer=customer,
        action_url=action_url
    )


# ============================================================
# ADD CUSTOMER
# ============================================================

@app.route(
    "/customers/add",
    methods=["GET", "POST"]
)
@login_required
def add_customer():

    if request.method == "POST":

        name = clean_text(
            request.form.get(
                "name",
                ""
            ),
            255
        )

        company_name = clean_text(
            request.form.get(
                "company_name",
                ""
            ),
            255
        )

        phone = clean_text(
            request.form.get(
                "phone",
                ""
            ),
            50
        )

        email = clean_text(
            request.form.get(
                "email",
                ""
            ),
            255
        )

        gstin = clean_text(
            request.form.get(
                "gstin",
                ""
            ),
            50
        ).upper()

        city = clean_text(
            request.form.get(
                "city",
                ""
            ),
            100
        )

        state = clean_text(
            request.form.get(
                "state",
                ""
            ),
            100
        )

        pincode = clean_text(
            request.form.get(
                "pincode",
                ""
            ),
            20
        )

        address = clean_text(
            request.form.get(
                "address",
                ""
            )
        )

        credit_limit = safe_float(
            request.form.get(
                "credit_limit",
                0
            )
        )

        opening_balance = safe_float(
            request.form.get(
                "opening_balance",
                0
            )
        )

        status = clean_text(
            request.form.get(
                "status",
                "ACTIVE"
            ),
            30
        ).upper()

        if status not in (
            "ACTIVE",
            "INACTIVE"
        ):
            status = "ACTIVE"

        if not name:

            flash(
                "Customer name is required.",
                "error"
            )

            customer_data = dict(
                request.form
            )

            return render_page(
                "Add Customer",
                customer_form_html(
                    customer_data,
                    "/customers/add"
                )
            )

        try:

            duplicate = db_fetchone(
                """
                SELECT id
                FROM customers
                WHERE
                    name=%s
                    AND phone=%s
                LIMIT 1
                """,
                (
                    name,
                    phone
                )
            )

            if duplicate:

                flash(
                    "A customer with the same "
                    "name and phone already exists.",
                    "error"
                )

                customer_data = dict(
                    request.form
                )

                return render_page(
                    "Add Customer",
                    customer_form_html(
                        customer_data,
                        "/customers/add"
                    )
                )

            db_execute("""
                INSERT INTO customers
                (
                    name,
                    company_name,
                    phone,
                    email,
                    address,
                    city,
                    state,
                    pincode,
                    gstin,
                    credit_limit,
                    opening_balance,
                    status
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (
                name,
                company_name,
                phone,
                email,
                address,
                city,
                state,
                pincode,
                gstin,
                credit_limit,
                opening_balance,
                status
            ))

            flash(
                "Customer added successfully.",
                "success"
            )

            return redirect(
                url_for("customers")
            )

        except Exception:

            logger.exception(
                "Customer creation failed."
            )

            flash(
                "Unable to add customer.",
                "error"
            )

    return render_page(
        "Add Customer",
        customer_form_html(
            {},
            "/customers/add"
        )
    )


# ============================================================
# EDIT CUSTOMER
# ============================================================

@app.route(
    "/customers/edit/<int:cid>",
    methods=["GET", "POST"]
)
@login_required
def edit_customer(cid):

    customer = get_customer_by_id(
        cid
    )

    if not customer:

        flash(
            "Customer not found.",
            "error"
        )

        return redirect(
            url_for("customers")
        )

    if request.method == "POST":

        name = clean_text(
            request.form.get(
                "name",
                ""
            ),
            255
        )

        if not name:

            flash(
                "Customer name is required.",
                "error"
            )

            customer_data = dict(
                request.form
            )

            customer_data["id"] = cid

            return render_page(
                "Edit Customer",
                customer_form_html(
                    customer_data,
                    f"/customers/edit/{cid}"
                )
            )

        company_name = clean_text(
            request.form.get(
                "company_name",
                ""
            ),
            255
        )

        phone = clean_text(
            request.form.get(
                "phone",
                ""
            ),
            50
        )

        email = clean_text(
            request.form.get(
                "email",
                ""
            ),
            255
        )

        gstin = clean_text(
            request.form.get(
                "gstin",
                ""
            ),
            50
        ).upper()

        city = clean_text(
            request.form.get(
                "city",
                ""
            ),
            100
        )

        state = clean_text(
            request.form.get(
                "state",
                ""
            ),
            100
        )

        pincode = clean_text(
            request.form.get(
                "pincode",
                ""
            ),
            20
        )

        address = clean_text(
            request.form.get(
                "address",
                ""
            )
        )

        credit_limit = safe_float(
            request.form.get(
                "credit_limit",
                0
            )
        )

        opening_balance = safe_float(
            request.form.get(
                "opening_balance",
                0
            )
        )

        status = clean_text(
            request.form.get(
                "status",
                "ACTIVE"
            ),
            30
        ).upper()

        if status not in (
            "ACTIVE",
            "INACTIVE"
        ):
            status = "ACTIVE"

        try:

            db_execute("""
                UPDATE customers
                SET
                    name=%s,
                    company_name=%s,
                    phone=%s,
                    email=%s,
                    address=%s,
                    city=%s,
                    state=%s,
                    pincode=%s,
                    gstin=%s,
                    credit_limit=%s,
                    opening_balance=%s,
                    status=%s
                WHERE id=%s
            """, (
                name,
                company_name,
                phone,
                email,
                address,
                city,
                state,
                pincode,
                gstin,
                credit_limit,
                opening_balance,
                status,
                cid
            ))

            flash(
                "Customer updated successfully.",
                "success"
            )

            return redirect(
                url_for("customers")
            )

        except Exception:

            logger.exception(
                "Customer update failed."
            )

            flash(
                "Unable to update customer.",
                "error"
            )

    customer = get_customer_by_id(
        cid
    )

    return render_page(
        "Edit Customer",
        customer_form_html(
            customer,
            f"/customers/edit/{cid}"
        )
    )


# ============================================================
# DELETE CUSTOMER
# ============================================================

@app.route(
    "/customers/delete/<int:cid>",
    methods=["POST"]
)
@admin_required
def delete_customer(cid):

    customer = get_customer_by_id(
        cid
    )

    if not customer:

        flash(
            "Customer not found.",
            "error"
        )

        return redirect(
            url_for("customers")
        )

    try:

        shipment_count = db_fetchone("""
            SELECT COUNT(*) AS total
            FROM shipments
            WHERE customer_id=%s
        """, (cid,))

        payment_count = db_fetchone("""
            SELECT COUNT(*) AS total
            FROM payments
            WHERE customer_id=%s
        """, (cid,))

        invoice_count = db_fetchone("""
            SELECT COUNT(*) AS total
            FROM invoices
            WHERE customer_id=%s
        """, (cid,))

        shipment_total = safe_int(
            shipment_count.get("total", 0)
            if shipment_count else 0
        )

        payment_total = safe_int(
            payment_count.get("total", 0)
            if payment_count else 0
        )

        invoice_total = safe_int(
            invoice_count.get("total", 0)
            if invoice_count else 0
        )

        if (
            shipment_total > 0
            or payment_total > 0
            or invoice_total > 0
        ):

            flash(
                "This customer cannot be deleted because "
                "related shipment, payment or invoice records exist. "
                "Set the customer status to INACTIVE instead.",
                "error"
            )

            return redirect(
                url_for("customers")
            )

        db_execute("""
            DELETE FROM customers
            WHERE id=%s
        """, (cid,))

        flash(
            "Customer deleted successfully.",
            "success"
        )

    except Exception:

        logger.exception(
            "Customer deletion failed."
        )

        flash(
            "Unable to delete customer.",
            "error"
        )

    return redirect(
        url_for("customers")
    )


# ============================================================
# CUSTOMER SEARCH API
# ============================================================

@app.route("/api/customers/search")
@login_required
def api_search_customers():

    query_text = clean_text(
        request.args.get(
            "q",
            ""
        ),
        100
    )

    if len(query_text) < 1:
        return jsonify([])

    like_value = f"%{query_text}%"

    try:

        rows = db_fetchall("""
            SELECT
                id,
                name,
                company_name,
                phone,
                city,
                gstin
            FROM customers
            WHERE
                status='ACTIVE'
                AND
                (
                    name LIKE %s
                    OR company_name LIKE %s
                    OR phone LIKE %s
                )
            ORDER BY name ASC
            LIMIT 20
        """, (
            like_value,
            like_value,
            like_value
        ))

        return jsonify(
            rows
        )

    except Exception:

        logger.exception(
            "Customer API search failed."
        )

        return jsonify({
            "error": "Unable to search customers."
        }), 500


# ============================================================
# PART 3 END
# ============================================================

# ============================================================
# PART 4 - BOOKING & SHIPMENT MANAGEMENT
# ============================================================


# ============================================================
# SHIPMENT LIST
# ============================================================

@app.route("/shipments")
@login_required
def shipments():

    search = clean_text(
        request.args.get("search", ""),
        100
    )

    status_filter = clean_text(
        request.args.get("status", ""),
        50
    ).upper()

    query = """
        SELECT
            s.*,
            c.name AS customer_name
        FROM shipments s
        LEFT JOIN customers c
            ON c.id = s.customer_id
        WHERE 1=1
    """

    params = []

    if search:

        like_value = f"%{search}%"

        query += """
            AND (
                s.awb_no LIKE %s
                OR s.sender_name LIKE %s
                OR s.receiver_name LIKE %s
                OR s.destination LIKE %s
                OR c.name LIKE %s
                OR s.receiver_phone LIKE %s
            )
        """

        params.extend([
            like_value,
            like_value,
            like_value,
            like_value,
            like_value,
            like_value
        ])

    if status_filter:

        query += """
            AND UPPER(s.status)=%s
        """

        params.append(
            status_filter
        )

    query += """
        ORDER BY
            s.id DESC
        LIMIT 500
    """

    try:

        shipment_rows = db_fetchall(
            query,
            tuple(params)
        )

    except Exception:

        logger.exception(
            "Shipment list loading failed."
        )

        shipment_rows = []

        flash(
            "Unable to load shipments.",
            "error"
        )

    shipments_html = """
    <div class="card">

        <div
            class="
                flex
                flex-col
                lg:flex-row
                justify-between
                gap-4
                mb-5
            "
        >

            <form
                method="GET"
                class="
                    flex
                    flex-col
                    md:flex-row
                    gap-2
                    w-full
                "
            >

                <input
                    type="text"
                    name="search"
                    value="{{ search }}"
                    placeholder="
                        Search AWB, sender, receiver,
                        phone, destination or customer
                    "
                    class="flex-1"
                >

                <select
                    name="status"
                    class="md:w-52"
                >

                    <option value="">
                        All Status
                    </option>

                    {% for item in shipment_statuses %}

                    <option
                        value="{{ item }}"
                        {% if
                            status_filter == item
                        %}
                            selected
                        {% endif %}
                    >
                        {{ item }}
                    </option>

                    {% endfor %}

                </select>

                <button
                    type="submit"
                    class="btn-primary"
                >
                    <i class="fas fa-search"></i>
                    Search
                </button>

            </form>

            <a
                href="/booking"
                class="
                    btn-success
                    whitespace-nowrap
                    text-center
                "
            >
                <i class="fas fa-plus-circle"></i>
                New Booking
            </a>

        </div>


        <div class="overflow-x-auto">

            <table>

                <thead>

                    <tr>
                        <th>AWB</th>
                        <th>Date</th>
                        <th>Customer</th>
                        <th>Sender</th>
                        <th>Receiver</th>
                        <th>Destination</th>
                        <th>Amount</th>
                        <th>Status</th>
                        <th>Action</th>
                    </tr>

                </thead>

                <tbody>

                {% if shipments %}

                    {% for shipment in shipments %}

                    <tr>

                        <td class="font-medium">

                            <a
                                href="/shipments/view/{{ shipment.id }}"
                                class="text-blue-600"
                            >
                                {{ shipment.awb_no }}
                            </a>

                        </td>

                        <td>

                            {% if shipment.booking_date %}

                                {{ shipment.booking_date }}

                            {% else %}

                                -

                            {% endif %}

                        </td>

                        <td>

                            {{ shipment.customer_name or '-' }}

                        </td>

                        <td>

                            {{ shipment.sender_name or '-' }}

                        </td>

                        <td>

                            {{ shipment.receiver_name or '-' }}

                        </td>

                        <td>

                            {{ shipment.destination or '-' }}

                        </td>

                        <td>

                            ₹ {{ "%.2f"|format(
                                shipment.total_amount or 0
                            ) }}

                        </td>

                        <td>

                            <span class="font-medium">

                                {{ shipment.status or 'BOOKED' }}

                            </span>

                        </td>

                        <td>

                            <div class="flex gap-3">

                                <a
                                    href="/shipments/view/{{ shipment.id }}"
                                    class="text-blue-600"
                                    title="View"
                                >
                                    <i class="fas fa-eye"></i>
                                </a>

                                <a
                                    href="/shipments/edit/{{ shipment.id }}"
                                    class="text-green-600"
                                    title="Edit"
                                >
                                    <i class="fas fa-edit"></i>
                                </a>

                                <a
                                    href="/tracking/{{ shipment.awb_no }}"
                                    class="text-purple-600"
                                    title="Tracking"
                                >
                                    <i class="fas fa-map-marker-alt"></i>
                                </a>

                                {% if
                                    session.get(
                                        'role',
                                        ''
                                    ).upper() == 'ADMIN'
                                %}

                                <form
                                    method="POST"
                                    action="/shipments/delete/{{ shipment.id }}"
                                    onsubmit="
                                        return confirm(
                                            'Delete this shipment?'
                                        );
                                    "
                                >

                                    <button
                                        type="submit"
                                        class="text-red-600"
                                        title="Delete"
                                    >
                                        <i class="fas fa-trash"></i>
                                    </button>

                                </form>

                                {% endif %}

                            </div>

                        </td>

                    </tr>

                    {% endfor %}

                {% else %}

                    <tr>

                        <td
                            colspan="9"
                            class="
                                text-center
                                text-slate-500
                                py-8
                            "
                        >
                            No shipments found.
                        </td>

                    </tr>

                {% endif %}

                </tbody>

            </table>

        </div>

    </div>
    """

    shipment_statuses = [
        "BOOKED",
        "PICKED UP",
        "IN TRANSIT",
        "RECEIVED AT HUB",
        "OUT FOR DELIVERY",
        "DELIVERED",
        "RTO",
        "CANCELLED"
    ]

    content = render_template_string(
        shipments_html,
        shipments=shipment_rows,
        search=search,
        status_filter=status_filter,
        shipment_statuses=shipment_statuses
    )

    return render_page(
        "Shipments",
        content
    )


# ============================================================
# BOOKING / SHIPMENT FORM
# ============================================================

def shipment_form_html(
    shipment=None,
    action_url="/booking"
):

    shipment = shipment or {}

    try:

        customer_rows = db_fetchall("""
            SELECT
                id,
                name,
                company_name,
                phone
            FROM customers
            WHERE status='ACTIVE'
            ORDER BY name ASC
        """)

    except Exception:

        logger.exception(
            "Unable to load customers for booking."
        )

        customer_rows = []

    try:

        network_rows = db_fetchall("""
            SELECT
                id,
                network_name,
                tracking_url
            FROM networks
            WHERE status='ACTIVE'
            ORDER BY network_name ASC
        """)

    except Exception:

        logger.exception(
            "Unable to load networks for booking."
        )

        network_rows = []

    tax_rate = safe_float(
        get_setting(
            "gst_rate",
            "18"
        )
    )

    form_html = """
    <div class="max-w-6xl mx-auto">

        <form
            method="POST"
            action="{{ action_url }}"
            class="card"
        >

            <div
                class="
                    flex
                    flex-col
                    md:flex-row
                    justify-between
                    gap-4
                    mb-6
                "
            >

                <div>

                    <h3
                        class="
                            text-xl
                            font-bold
                            text-slate-800
                        "
                    >
                        Shipment Booking
                    </h3>

                    <p
                        class="
                            text-sm
                            text-slate-500
                        "
                    >
                        Enter complete shipment details.
                    </p>

                </div>

                <div class="md:w-64">

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        AWB Number
                    </label>

                    <input
                        type="text"
                        name="awb_no"
                        value="{{ shipment.get('awb_no', '') }}"
                        placeholder="Auto Generated"
                    >

                </div>

            </div>


            <!-- CUSTOMER & BOOKING -->

            <div
                class="
                    border-b
                    pb-5
                    mb-5
                "
            >

                <h4
                    class="
                        font-bold
                        text-slate-700
                        mb-4
                    "
                >
                    Booking Details
                </h4>

                <div
                    class="
                        grid
                        grid-cols-1
                        md:grid-cols-3
                        gap-4
                    "
                >

                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Booking Date
                        </label>

                        <input
                            type="date"
                            name="booking_date"
                            value="{{ shipment.get('booking_date', today) }}"
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Customer
                        </label>

                        <select name="customer_id">

                            <option value="">
                                Walk-in Customer
                            </option>

                            {% for customer in customers %}

                            <option
                                value="{{ customer.id }}"
                                {% if
                                    shipment.get(
                                        'customer_id'
                                    )|string
                                    ==
                                    customer.id|string
                                %}
                                    selected
                                {% endif %}
                            >

                                {{ customer.name }}

                                {% if customer.company_name %}

                                    -
                                    {{ customer.company_name }}

                                {% endif %}

                            </option>

                            {% endfor %}

                        </select>

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Payment Mode
                        </label>

                        <select name="payment_mode">

                            {% for mode in payment_modes %}

                            <option
                                value="{{ mode }}"
                                {% if
                                    shipment.get(
                                        'payment_mode',
                                        'CASH'
                                    ) == mode
                                %}
                                    selected
                                {% endif %}
                            >
                                {{ mode }}
                            </option>

                            {% endfor %}

                        </select>

                    </div>

                </div>

            </div>


            <!-- SENDER -->

            <div
                class="
                    border-b
                    pb-5
                    mb-5
                "
            >

                <h4
                    class="
                        font-bold
                        text-slate-700
                        mb-4
                    "
                >
                    Sender Details
                </h4>

                <div
                    class="
                        grid
                        grid-cols-1
                        md:grid-cols-2
                        gap-4
                    "
                >

                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Sender Name *
                        </label>

                        <input
                            type="text"
                            name="sender_name"
                            value="{{ shipment.get('sender_name', '') }}"
                            required
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Sender Phone
                        </label>

                        <input
                            type="text"
                            name="sender_phone"
                            value="{{ shipment.get('sender_phone', '') }}"
                        >

                    </div>


                    <div class="md:col-span-2">

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Sender Address
                        </label>

                        <textarea
                            name="sender_address"
                            rows="3"
                        >{{ shipment.get('sender_address', '') }}</textarea>

                    </div>

                </div>

            </div>


            <!-- RECEIVER -->

            <div
                class="
                    border-b
                    pb-5
                    mb-5
                "
            >

                <h4
                    class="
                        font-bold
                        text-slate-700
                        mb-4
                    "
                >
                    Receiver Details
                </h4>

                <div
                    class="
                        grid
                        grid-cols-1
                        md:grid-cols-2
                        gap-4
                    "
                >

                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Receiver Name *
                        </label>

                        <input
                            type="text"
                            name="receiver_name"
                            value="{{ shipment.get('receiver_name', '') }}"
                            required
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Receiver Phone
                        </label>

                        <input
                            type="text"
                            name="receiver_phone"
                            value="{{ shipment.get('receiver_phone', '') }}"
                        >

                    </div>


                    <div class="md:col-span-2">

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Receiver Address
                        </label>

                        <textarea
                            name="receiver_address"
                            rows="3"
                        >{{ shipment.get('receiver_address', '') }}</textarea>

                    </div>

                </div>

            </div>


            <!-- ROUTE -->

            <div
                class="
                    border-b
                    pb-5
                    mb-5
                "
            >

                <h4
                    class="
                        font-bold
                        text-slate-700
                        mb-4
                    "
                >
                    Route & Service
                </h4>

                <div
                    class="
                        grid
                        grid-cols-1
                        md:grid-cols-3
                        gap-4
                    "
                >

                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Origin
                        </label>

                        <input
                            type="text"
                            name="origin"
                            value="{{ shipment.get('origin', '') }}"
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Destination *
                        </label>

                        <input
                            type="text"
                            name="destination"
                            value="{{ shipment.get('destination', '') }}"
                            required
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Pincode
                        </label>

                        <input
                            type="text"
                            name="pincode"
                            value="{{ shipment.get('pincode', '') }}"
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Network
                        </label>

                        <select name="network_id">

                            <option value="">
                                Select Network
                            </option>

                            {% for network in networks %}

                            <option
                                value="{{ network.id }}"
                                {% if
                                    shipment.get(
                                        'network_id'
                                    )|string
                                    ==
                                    network.id|string
                                %}
                                    selected
                                {% endif %}
                            >
                                {{ network.network_name }}
                            </option>

                            {% endfor %}

                        </select>

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Shipment Type
                        </label>

                        <select name="shipment_type">

                            {% for item in shipment_types %}

                            <option
                                value="{{ item }}"
                                {% if
                                    shipment.get(
                                        'shipment_type',
                                        'PARCEL'
                                    ) == item
                                %}
                                    selected
                                {% endif %}
                            >
                                {{ item }}
                            </option>

                            {% endfor %}

                        </select>

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Service Type
                        </label>

                        <select name="service_type">

                            {% for item in service_types %}

                            <option
                                value="{{ item }}"
                                {% if
                                    shipment.get(
                                        'service_type',
                                        'STANDARD'
                                    ) == item
                                %}
                                    selected
                                {% endif %}
                            >
                                {{ item }}
                            </option>

                            {% endfor %}

                        </select>

                    </div>

                </div>

            </div>


            <!-- WEIGHT -->

            <div
                class="
                    border-b
                    pb-5
                    mb-5
                "
            >

                <h4
                    class="
                        font-bold
                        text-slate-700
                        mb-4
                    "
                >
                    Package Details
                </h4>

                <div
                    class="
                        grid
                        grid-cols-1
                        md:grid-cols-3
                        gap-4
                    "
                >

                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Pieces
                        </label>

                        <input
                            type="number"
                            name="pieces"
                            min="1"
                            value="{{ shipment.get('pieces', 1) }}"
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Actual Weight (KG)
                        </label>

                        <input
                            type="number"
                            name="actual_weight"
                            min="0"
                            step="0.001"
                            value="{{ shipment.get('actual_weight', 0) }}"
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Chargeable Weight (KG)
                        </label>

                        <input
                            type="number"
                            name="chargeable_weight"
                            min="0"
                            step="0.001"
                            value="{{ shipment.get('chargeable_weight', 0) }}"
                        >

                    </div>

                </div>

            </div>


            <!-- CHARGES -->

            <div
                class="
                    border-b
                    pb-5
                    mb-5
                "
            >

                <h4
                    class="
                        font-bold
                        text-slate-700
                        mb-4
                    "
                >
                    Charges
                </h4>

                <div
                    class="
                        grid
                        grid-cols-1
                        md:grid-cols-4
                        gap-4
                    "
                >

                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Freight
                        </label>

                        <input
                            type="number"
                            name="freight"
                            min="0"
                            step="0.01"
                            value="{{ shipment.get('freight', 0) }}"
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Fuel Charge
                        </label>

                        <input
                            type="number"
                            name="fuel_charge"
                            min="0"
                            step="0.01"
                            value="{{ shipment.get('fuel_charge', 0) }}"
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            Other Charge
                        </label>

                        <input
                            type="number"
                            name="other_charge"
                            min="0"
                            step="0.01"
                            value="{{ shipment.get('other_charge', 0) }}"
                        >

                    </div>


                    <div>

                        <label
                            class="
                                block
                                mb-2
                                font-medium
                            "
                        >
                            GST Rate %
                        </label>

                        <input
                            type="number"
                            name="tax_rate"
                            min="0"
                            step="0.01"
                            value="{{ shipment.get('tax_rate', tax_rate) }}"
                        >

                    </div>

                </div>

            </div>


            <!-- STATUS -->

            <div
                class="
                    grid
                    grid-cols-1
                    md:grid-cols-2
                    gap-4
                "
            >

                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Shipment Status
                    </label>

                    <select name="status">

                        {% for item in shipment_statuses %}

                        <option
                            value="{{ item }}"
                            {% if
                                shipment.get(
                                    'status',
                                    'BOOKED'
                                ) == item
                            %}
                                selected
                            {% endif %}
                        >
                            {{ item }}
                        </option>

                        {% endfor %}

                    </select>

                </div>


                <div>

                    <label
                        class="
                            block
                            mb-2
                            font-medium
                        "
                    >
                        Remarks
                    </label>

                    <textarea
                        name="remarks"
                        rows="3"
                    >{{ shipment.get('remarks', '') }}</textarea>

                </div>

            </div>


            <div
                class="
                    flex
                    justify-end
                    gap-3
                    mt-7
                "
            >

                <a
                    href="/shipments"
                    class="
                        border
                        border-slate-300
                        px-4
                        py-2
                        rounded-lg
                    "
                >
                    Cancel
                </a>

                <button
                    type="submit"
                    class="btn-primary"
                >
                    <i class="fas fa-save"></i>
                    Save Shipment
                </button>

            </div>

        </form>

    </div>
    """

    shipment_statuses = [
        "BOOKED",
        "PICKED UP",
        "IN TRANSIT",
        "RECEIVED AT HUB",
        "OUT FOR DELIVERY",
        "DELIVERED",
        "RTO",
        "CANCELLED"
    ]

    payment_modes = [
        "CASH",
        "CREDIT",
        "TO PAY",
        "BANK",
        "ONLINE"
    ]

    shipment_types = [
        "DOCUMENT",
        "PARCEL",
        "BOX",
        "ENVELOPE",
        "OTHER"
    ]

    service_types = [
        "STANDARD",
        "EXPRESS",
        "SURFACE",
        "AIR"
    ]

    return render_template_string(
        form_html,
        shipment=shipment,
        customers=customer_rows,
        networks=network_rows,
        today=datetime.date.today().isoformat(),
        tax_rate=tax_rate,
        shipment_statuses=shipment_statuses,
        payment_modes=payment_modes,
        shipment_types=shipment_types,
        service_types=service_types,
        action_url=action_url
    )


# ============================================================
# BOOKING
# ============================================================

@app.route(
    "/booking",
    methods=["GET", "POST"]
)
@login_required
def booking():

    if request.method == "POST":

        awb_no = normalize_awb(
            request.form.get(
                "awb_no",
                ""
            )
        )

        if not awb_no:

            awb_no = generate_awb()

        existing = get_shipment_by_awb(
            awb_no
        )

        if existing:

            flash(
                "AWB number already exists.",
                "error"
            )

            return render_page(
                "New Booking",
                shipment_form_html(
                    dict(request.form),
                    "/booking"
                )
            )

        sender_name = clean_text(
            request.form.get(
                "sender_name",
                ""
            ),
            255
        )

        receiver_name = clean_text(
            request.form.get(
                "receiver_name",
                ""
            ),
            255
        )

        destination = clean_text(
            request.form.get(
                "destination",
                ""
            ),
            150
        )

        if not sender_name:

            flash(
                "Sender name is required.",
                "error"
            )

            return render_page(
                "New Booking",
                shipment_form_html(
                    dict(request.form),
                    "/booking"
                )
            )

        if not receiver_name:

            flash(
                "Receiver name is required.",
                "error"
            )

            return render_page(
                "New Booking",
                shipment_form_html(
                    dict(request.form),
                    "/booking"
                )
            )

        if not destination:

            flash(
                "Destination is required.",
                "error"
            )

            return render_page(
                "New Booking",
                shipment_form_html(
                    dict(request.form),
                    "/booking"
                )
            )

        customer_id = safe_int(
            request.form.get(
                "customer_id",
                0
            )
        )

        if customer_id <= 0:

            customer_id = None

        network_id = safe_int(
            request.form.get(
                "network_id",
                0
            )
        )

        if network_id <= 0:

            network_id = None

        network_name = ""

        if network_id:

            network = db_fetchone("""
                SELECT network_name
                FROM networks
                WHERE id=%s
                LIMIT 1
            """, (
                network_id,
            ))

            if network:

                network_name = (
                    network.get(
                        "network_name",
                        ""
                    )
                )

        booking_date_text = clean_text(
            request.form.get(
                "booking_date",
                ""
            ),
            20
        )

        booking_date = parse_date(
            booking_date_text
        )

        if not booking_date:

            booking_date = datetime.date.today()

        freight = safe_float(
            request.form.get(
                "freight",
                0
            )
        )

        fuel_charge = safe_float(
            request.form.get(
                "fuel_charge",
                0
            )
        )

        other_charge = safe_float(
            request.form.get(
                "other_charge",
                0
            )
        )

        tax_rate = safe_float(
            request.form.get(
                "tax_rate",
                get_setting(
                    "gst_rate",
                    "18"
                )
            )
        )

        amounts = calculate_shipment_amounts(
            freight,
            fuel_charge,
            other_charge,
            tax_rate
        )

        try:

            shipment_id = db_execute(
                """
                INSERT INTO shipments
                (
                    awb_no,
                    booking_date,
                    customer_id,

                    sender_name,
                    sender_phone,
                    sender_address,

                    receiver_name,
                    receiver_phone,
                    receiver_address,

                    origin,
                    destination,
                    pincode,

                    network_id,
                    network_name,

                    shipment_type,
                    service_type,

                    pieces,
                    actual_weight,
                    chargeable_weight,

                    freight,
                    fuel_charge,
                    other_charge,
                    gst_amount,
                    total_amount,

                    payment_mode,
                    status,
                    remarks,

                    created_by
                )
                VALUES
                (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s
                )
                """,
                (
                    awb_no,
                    booking_date,
                    customer_id,

                    sender_name,
                    clean_text(
                        request.form.get(
                            "sender_phone",
                            ""
                        ),
                        50
                    ),
                    clean_text(
                        request.form.get(
                            "sender_address",
                            ""
                        )
                    ),

                    receiver_name,
                    clean_text(
                        request.form.get(
                            "receiver_phone",
                            ""
                        ),
                        50
                    ),
                    clean_text(
                        request.form.get(
                            "receiver_address",
                            ""
                        )
                    ),

                    clean_text(
                        request.form.get(
                            "origin",
                            ""
                        ),
                        150
                    ),
                    destination,
                    clean_text(
                        request.form.get(
                            "pincode",
                            ""
                        ),
                        20
                    ),

                    network_id,
                    network_name,

                    clean_text(
                        request.form.get(
                            "shipment_type",
                            "PARCEL"
                        ),
                        100
                    ).upper(),

                    clean_text(
                        request.form.get(
                            "service_type",
                            "STANDARD"
                        ),
                        100
                    ).upper(),

                    max(
                        1,
                        safe_int(
                            request.form.get(
                                "pieces",
                                1
                            ),
                            1
                        )
                    ),

                    safe_float(
                        request.form.get(
                            "actual_weight",
                            0
                        )
                    ),

                    safe_float(
                        request.form.get(
                            "chargeable_weight",
                            0
                        )
                    ),

                    amounts["freight"],
                    amounts["fuel_charge"],
                    amounts["other_charge"],
                    amounts["gst_amount"],
                    amounts["total_amount"],

                    clean_text(
                        request.form.get(
                            "payment_mode",
                            "CASH"
                        ),
                        50
                    ).upper(),

                    clean_text(
                        request.form.get(
                            "status",
                            "BOOKED"
                        ),
                        100
                    ).upper(),

                    clean_text(
                        request.form.get(
                            "remarks",
                            ""
                        )
                    ),

                    session.get("user_id")
                )
            )

            if not shipment_id:

                shipment = get_shipment_by_awb(
                    awb_no
                )

                if shipment:

                    shipment_id = shipment.get(
                        "id"
                    )

            if shipment_id:

                db_execute(
                    """
                    INSERT INTO shipment_tracking
                    (
                        shipment_id,
                        status,
                        location,
                        remarks,
                        created_by,
                        tracking_time
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        NOW()
                    )
                    """,
                    (
                        shipment_id,
                        clean_text(
                            request.form.get(
                                "status",
                                "BOOKED"
                            ),
                            100
                        ).upper(),

                        clean_text(
                            request.form.get(
                                "origin",
                                ""
                            ),
                            255
                        ),

                        "Shipment booked.",

                        session.get(
                            "user_id"
                        )
                    )
                )

            flash(
                f"Shipment booked successfully. AWB: {awb_no}",
                "success"
            )

            return redirect(
                url_for(
                    "view_shipment",
                    sid=shipment_id
                )
            )

        except Exception:

            logger.exception(
                "Shipment booking failed."
            )

            flash(
                "Unable to save shipment.",
                "error"
            )

            return render_page(
                "New Booking",
                shipment_form_html(
                    dict(request.form),
                    "/booking"
                )
            )

    return render_page(
        "New Booking",
        shipment_form_html(
            {},
            "/booking"
        )
    )


# ============================================================
# VIEW SHIPMENT
# ============================================================

@app.route("/shipments/view/<int:sid>")
@login_required
def view_shipment(sid):

    shipment = db_fetchone(
        """
        SELECT
            s.*,
            c.name AS customer_name,
            c.company_name,
            c.phone AS customer_phone
        FROM shipments s
        LEFT JOIN customers c
            ON c.id=s.customer_id
        WHERE s.id=%s
        LIMIT 1
        """,
        (sid,)
    )

    if not shipment:

        flash(
            "Shipment not found.",
            "error"
        )

        return redirect(
            url_for("shipments")
        )

    tracking_rows = db_fetchall(
        """
        SELECT *
        FROM shipment_tracking
        WHERE shipment_id=%s
        ORDER BY tracking_time DESC, id DESC
        """,
        (sid,)
    )

    shipment_html = """
    <div class="max-w-6xl mx-auto">

        <div
            class="
                flex
                flex-col
                md:flex-row
                justify-between
                gap-4
                mb-5
            "
        >

            <div>

                <h2
                    class="
                        text-2xl
                        font-bold
                        text-slate-800
                    "
                >
                    Shipment: {{ shipment.awb_no }}
                </h2>

                <p
                    class="
                        text-slate-500
                    "
                >
                    {{ shipment.status }}
                </p>

            </div>

            <div
                class="
                    flex
                    gap-3
                    flex-wrap
                "
            >

                <a
                    href="/shipments/edit/{{ shipment.id }}"
                    class="btn-primary"
                >
                    <i class="fas fa-edit"></i>
                    Edit
                </a>

                <a
                    href="/tracking/{{ shipment.awb_no }}"
                    class="
                        border
                        border-slate-300
                        px-4
                        py-2
                        rounded-lg
                    "
                >
                    <i class="fas fa-map-marker-alt"></i>
                    Tracking
                </a>

            </div>

        </div>


        <div
            class="
                grid
                grid-cols-1
                lg:grid-cols-2
                gap-5
            "
        >

            <div class="card">

                <h3
                    class="
                        font-bold
                        text-lg
                        mb-4
                    "
                >
                    Shipment Details
                </h3>

                <div class="space-y-2">

                    <p>
                        <strong>Booking Date:</strong>
                        {{ shipment.booking_date or '-' }}
                    </p>

                    <p>
                        <strong>Customer:</strong>
                        {{ shipment.customer_name or 'Walk-in Customer' }}
                    </p>

                    <p>
                        <strong>Origin:</strong>
                        {{ shipment.origin or '-' }}
                    </p>

                    <p>
                        <strong>Destination:</strong>
                        {{ shipment.destination or '-' }}
                    </p>

                    <p>
                        <strong>Network:</strong>
                        {{ shipment.network_name or '-' }}
                    </p>

                    <p>
                        <strong>Shipment Type:</strong>
                        {{ shipment.shipment_type or '-' }}
                    </p>

                    <p>
                        <strong>Service:</strong>
                        {{ shipment.service_type or '-' }}
                    </p>

                    <p>
                        <strong>Pieces:</strong>
                        {{ shipment.pieces or 0 }}
                    </p>

                    <p>
                        <strong>Actual Weight:</strong>
                        {{ shipment.actual_weight or 0 }} KG
                    </p>

                    <p>
                        <strong>Chargeable Weight:</strong>
                        {{ shipment.chargeable_weight or 0 }} KG
                    </p>

                    <p>
                        <strong>Total Amount:</strong>
                        ₹ {{ "%.2f"|format(
                            shipment.total_amount or 0
                        ) }}
                    </p>

                </div>

            </div>


            <div class="card">

                <h3
                    class="
                        font-bold
                        text-lg
                        mb-4
                    "
                >
                    Sender
                </h3>

                <div class="space-y-2">

                    <p>
                        <strong>Name:</strong>
                        {{ shipment.sender_name or '-' }}
                    </p>

                    <p>
                        <strong>Phone:</strong>
                        {{ shipment.sender_phone or '-' }}
                    </p>

                    <p>
                        <strong>Address:</strong>
                        {{ shipment.sender_address or '-' }}
                    </p>

                </div>

                <hr class="my-5">

                <h3
                    class="
                        font-bold
                        text-lg
                        mb-4
                    "
                >
                    Receiver
                </h3>

                <div class="space-y-2">

                    <p>
                        <strong>Name:</strong>
                        {{ shipment.receiver_name or '-' }}
                    </p>

                    <p>
                        <strong>Phone:</strong>
                        {{ shipment.receiver_phone or '-' }}
                    </p>

                    <p>
                        <strong>Address:</strong>
                        {{ shipment.receiver_address or '-' }}
                    </p>

                </div>

            </div>

        </div>


        <div class="card mt-5">

            <h3
                class="
                    font-bold
                    text-lg
                    mb-4
                "
            >
                Tracking History
            </h3>

            <div class="overflow-x-auto">

                <table>

                    <thead>

                        <tr>
                            <th>Date & Time</th>
                            <th>Status</th>
                            <th>Location</th>
                            <th>Remarks</th>
                        </tr>

                    </thead>

                    <tbody>

                    {% if tracking_rows %}

                        {% for item in tracking_rows %}

                        <tr>

                            <td>

                                {{ item.tracking_time or '-' }}

                            </td>

                            <td>

                                {{ item.status }}

                            </td>

                            <td>

                                {{ item.location or '-' }}

                            </td>

                            <td>

                                {{ item.remarks or '-' }}

                            </td>

                        </tr>

                        {% endfor %}

                    {% else %}

                        <tr>

                            <td
                                colspan="4"
                                class="
                                    text-center
                                    py-6
                                    text-slate-500
                                "
                            >
                                No tracking history.
                            </td>

                        </tr>

                    {% endif %}

                    </tbody>

                </table>

            </div>

        </div>

    </div>
    """

    content = render_template_string(
        shipment_html,
        shipment=shipment,
        tracking_rows=tracking_rows
    )

    return render_page(
        f"Shipment {shipment['awb_no']}",
        content
    )


# ============================================================
# EDIT SHIPMENT
# ============================================================

@app.route(
    "/shipments/edit/<int:sid>",
    methods=["GET", "POST"]
)
@login_required
def edit_shipment(sid):

    shipment = get_shipment_by_id(
        sid
    )

    if not shipment:

        flash(
            "Shipment not found.",
            "error"
        )

        return redirect(
            url_for("shipments")
        )

    if request.method == "POST":

        awb_no = normalize_awb(
            request.form.get(
                "awb_no",
                shipment["awb_no"]
            )
        )

        if not awb_no:

            awb_no = shipment["awb_no"]

        duplicate = db_fetchone(
            """
            SELECT id
            FROM shipments
            WHERE
                awb_no=%s
                AND id<>%s
            LIMIT 1
            """,
            (
                awb_no,
                sid
            )
        )

        if duplicate:

            flash(
                "Another shipment already uses this AWB number.",
                "error"
            )

            return render_page(
                "Edit Shipment",
                shipment_form_html(
                    dict(request.form),
                    f"/shipments/edit/{sid}"
                )
            )

        sender_name = clean_text(
            request.form.get(
                "sender_name",
                ""
            ),
            255
        )

        receiver_name = clean_text(
            request.form.get(
                "receiver_name",
                ""
            ),
            255
        )

        destination = clean_text(
            request.form.get(
                "destination",
                ""
            ),
            150
        )

        if (
            not sender_name
            or not receiver_name
            or not destination
        ):

            flash(
                "Sender, receiver and destination are required.",
                "error"
            )

            return render_page(
                "Edit Shipment",
                shipment_form_html(
                    dict(request.form),
                    f"/shipments/edit/{sid}"
                )
            )

        customer_id = safe_int(
            request.form.get(
                "customer_id",
                0
            )
        )

        if customer_id <= 0:

            customer_id = None

        network_id = safe_int(
            request.form.get(
                "network_id",
                0
            )
        )

        if network_id <= 0:

            network_id = None

        network_name = ""

        if network_id:

            network = db_fetchone(
                """
                SELECT network_name
                FROM networks
                WHERE id=%s
                LIMIT 1
                """,
                (network_id,)
            )

            if network:

                network_name = network.get(
                    "network_name",
                    ""
                )

        booking_date = parse_date(
            clean_text(
                request.form.get(
                    "booking_date",
                    ""
                ),
                20
            )
        )

        if not booking_date:

            booking_date = shipment.get(
                "booking_date"
            )

        freight = safe_float(
            request.form.get(
                "freight",
                0
            )
        )

        fuel_charge = safe_float(
            request.form.get(
                "fuel_charge",
                0
            )
        )

        other_charge = safe_float(
            request.form.get(
                "other_charge",
                0
            )
        )

        tax_rate = safe_float(
            request.form.get(
                "tax_rate",
                get_setting(
                    "gst_rate",
                    "18"
                )
            )
        )

        amounts = calculate_shipment_amounts(
            freight,
            fuel_charge,
            other_charge,
            tax_rate
        )

        new_status = clean_text(
            request.form.get(
                "status",
                shipment.get(
                    "status",
                    "BOOKED"
                )
            ),
            100
        ).upper()

        old_status = clean_text(
            shipment.get(
                "status",
                "BOOKED"
            ),
            100
        ).upper()

        try:

            db_execute(
                """
                UPDATE shipments
                SET
                    awb_no=%s,
                    booking_date=%s,
                    customer_id=%s,

                    sender_name=%s,
                    sender_phone=%s,
                    sender_address=%s,

                    receiver_name=%s,
                    receiver_phone=%s,
                    receiver_address=%s,

                    origin=%s,
                    destination=%s,
                    pincode=%s,

                    network_id=%s,
                    network_name=%s,

                    shipment_type=%s,
                    service_type=%s,

                    pieces=%s,
                    actual_weight=%s,
                    chargeable_weight=%s,

                    freight=%s,
                    fuel_charge=%s,
                    other_charge=%s,
                    gst_amount=%s,
                    total_amount=%s,

                    payment_mode=%s,
                    status=%s,
                    remarks=%s

                WHERE id=%s
                """,
                (
                    awb_no,
                    booking_date,
                    customer_id,

                    sender_name,
                    clean_text(
                        request.form.get(
                            "sender_phone",
                            ""
                        ),
                        50
                    ),
                    clean_text(
                        request.form.get(
                            "sender_address",
                            ""
                        )
                    ),

                    receiver_name,
                    clean_text(
                        request.form.get(
                            "receiver_phone",
                            ""
                        ),
                        50
                    ),
                    clean_text(
                        request.form.get(
                            "receiver_address",
                            ""
                        )
                    ),

                    clean_text(
                        request.form.get(
                            "origin",
                            ""
                        ),
                        150
                    ),

                    destination,

                    clean_text(
                        request.form.get(
                            "pincode",
                            ""
                        ),
                        20
                    ),

                    network_id,
                    network_name,

                    clean_text(
                        request.form.get(
                            "shipment_type",
                            "PARCEL"
                        ),
                        100
                    ).upper(),

                    clean_text(
                        request.form.get(
                            "service_type",
                            "STANDARD"
                        ),
                        100
                    ).upper(),

                    max(
                        1,
                        safe_int(
                            request.form.get(
                                "pieces",
                                1
                            ),
                            1
                        )
                    ),

                    safe_float(
                        request.form.get(
                            "actual_weight",
                            0
                        )
                    ),

                    safe_float(
                        request.form.get(
                            "chargeable_weight",
                            0
                        )
                    ),

                    amounts["freight"],
                    amounts["fuel_charge"],
                    amounts["other_charge"],
                    amounts["gst_amount"],
                    amounts["total_amount"],

                    clean_text(
                        request.form.get(
                            "payment_mode",
                            "CASH"
                        ),
                        50
                    ).upper(),

                    new_status,

                    clean_text(
                        request.form.get(
                            "remarks",
                            ""
                        )
                    ),

                    sid
                )
            )

            if new_status != old_status:

                db_execute(
                    """
                    INSERT INTO shipment_tracking
                    (
                        shipment_id,
                        status,
                        location,
                        remarks,
                        created_by,
                        tracking_time
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        NOW()
                    )
                    """,
                    (
                        sid,
                        new_status,

                        clean_text(
                            request.form.get(
                                "destination",
                                ""
                            ),
                            255
                        ),

                        "Shipment status updated.",

                        session.get(
                            "user_id"
                        )
                    )
                )

            flash(
                "Shipment updated successfully.",
                "success"
            )

            return redirect(
                url_for(
                    "view_shipment",
                    sid=sid
                )
            )

        except Exception:

            logger.exception(
                "Shipment update failed."
            )

            flash(
                "Unable to update shipment.",
                "error"
            )

    shipment = get_shipment_by_id(
        sid
    )

    return render_page(
        "Edit Shipment",
        shipment_form_html(
            shipment,
            f"/shipments/edit/{sid}"
        )
    )


# ============================================================
# DELETE SHIPMENT
# ============================================================

@app.route(
    "/shipments/delete/<int:sid>",
    methods=["POST"]
)
@admin_required
def delete_shipment(sid):

    shipment = get_shipment_by_id(
        sid
    )

    if not shipment:

        flash(
            "Shipment not found.",
            "error"
        )

        return redirect(
            url_for("shipments")
        )

    try:

        invoice_link = db_fetchone(
            """
            SELECT id
            FROM invoice_shipments
            WHERE shipment_id=%s
            LIMIT 1
            """,
            (sid,)
        )

        if invoice_link:

            flash(
                "This shipment is linked with an invoice and "
                "cannot be deleted.",
                "error"
            )

            return redirect(
                url_for("shipments")
            )

        db_execute(
            """
            DELETE FROM shipment_tracking
            WHERE shipment_id=%s
            """,
            (sid,)
        )

        db_execute(
            """
            DELETE FROM drs_shipments
            WHERE shipment_id=%s
            """,
            (sid,)
        )

        db_execute(
            """
            DELETE FROM shipments
            WHERE id=%s
            """,
            (sid,)
        )

        flash(
            "Shipment deleted successfully.",
            "success"
        )

    except Exception:

        logger.exception(
            "Shipment deletion failed."
        )

        flash(
            "Unable to delete shipment.",
            "error"
        )

    return redirect(
        url_for("shipments")
    )


# ============================================================
# ADD MANUAL TRACKING UPDATE
# ============================================================

@app.route(
    "/shipments/<int:sid>/tracking/add",
    methods=["POST"]
)
@login_required
def add_tracking_update(sid):

    shipment = get_shipment_by_id(
        sid
    )

    if not shipment:

        return jsonify({
            "success": False,
            "message": "Shipment not found."
        }), 404

    status = clean_text(
        request.form.get(
            "status",
            ""
        ),
        100
    ).upper()

    location = clean_text(
        request.form.get(
            "location",
            ""
        ),
        255
    )

    remarks = clean_text(
        request.form.get(
            "remarks",
            ""
        )
    )

    if not status:

        return jsonify({
            "success": False,
            "message": "Status is required."
        }), 400

    try:

        db_execute(
            """
            INSERT INTO shipment_tracking
            (
                shipment_id,
                status,
                location,
                remarks,
                created_by,
                tracking_time
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                NOW()
            )
            """,
            (
                sid,
                status,
                location,
                remarks,
                session.get(
                    "user_id"
                )
            )
        )

        db_execute(
            """
            UPDATE shipments
            SET status=%s
            WHERE id=%s
            """,
            (
                status,
                sid
            )
        )

        return jsonify({
            "success": True,
            "message": "Tracking updated successfully."
        })

    except Exception:

        logger.exception(
            "Tracking update failed."
        )

        return jsonify({
            "success": False,
            "message": "Unable to update tracking."
        }), 500


# ============================================================
# PUBLIC TRACKING PAGE
# ============================================================

@app.route(
    "/tracking",
    methods=["GET"]
)
def tracking_search():

    awb_no = normalize_awb(
        request.args.get(
            "awb",
            ""
        )
    )

    shipment = None
    tracking_rows = []

    if awb_no:

        shipment = get_shipment_by_awb(
            awb_no
        )

        if shipment:

            tracking_rows = db_fetchall(
                """
                SELECT
                    status,
                    location,
                    remarks,
                    tracking_time
                FROM shipment_tracking
                WHERE shipment_id=%s
                ORDER BY
                    tracking_time DESC,
                    id DESC
                """,
                (
                    shipment["id"],
                )
            )

    tracking_html = """
    <div class="max-w-4xl mx-auto">

        <div class="card">

            <h2
                class="
                    text-2xl
                    font-bold
                    text-slate-800
                    mb-5
                "
            >
                Track Your Shipment
            </h2>

            <form
                method="GET"
                action="/tracking"
                class="
                    flex
                    flex-col
                    md:flex-row
                    gap-3
                "
            >

                <input
                    type="text"
                    name="awb"
                    value="{{ awb_no }}"
                    placeholder="Enter AWB Number"
                    class="flex-1"
                    required
                >

                <button
                    type="submit"
                    class="btn-primary"
                >
                    <i class="fas fa-search"></i>
                    Track
                </button>

            </form>

        </div>


        {% if awb_no %}

            {% if shipment %}

            <div class="card mt-5">

                <div
                    class="
                        flex
                        flex-col
                        md:flex-row
                        justify-between
                        gap-4
                        mb-5
                    "
                >

                    <div>

                        <p
                            class="
                                text-sm
                                text-slate-500
                            "
                        >
                            AWB Number
                        </p>

                        <h3
                            class="
                                text-xl
                                font-bold
                            "
                        >
                            {{ shipment.awb_no }}
                        </h3>

                    </div>

                    <div>

                        <p
                            class="
                                text-sm
                                text-slate-500
                            "
                        >
                            Current Status
                        </p>

                        <h3
                            class="
                                text-xl
                                font-bold
                                text-green-600
                            "
                        >
                            {{ shipment.status }}
                        </h3>

                    </div>

                </div>

                <div class="space-y-4">

                    {% for item in tracking_rows %}

                    <div
                        class="
                            border-l-4
                            border-blue-500
                            pl-4
                            py-1
                        "
                    >

                        <div
                            class="
                                font-bold
                            "
                        >
                            {{ item.status }}
                        </div>

                        <div
                            class="
                                text-sm
                                text-slate-500
                            "
                        >
                            {{ item.location or '-' }}
                        </div>

                        {% if item.remarks %}

                        <div
                            class="
                                text-sm
                                mt-1
                            "
                        >
                            {{ item.remarks }}
                        </div>

                        {% endif %}

                        <div
                            class="
                                text-xs
                                text-slate-400
                                mt-1
                            "
                        >
                            {{ item.tracking_time }}
                        </div>

                    </div>

                    {% else %}

                    <p
                        class="
                            text-slate-500
                        "
                    >
                        No tracking updates available.
                    </p>

                    {% endfor %}

                </div>

            </div>

            {% else %}

            <div
                class="
                    card
                    mt-5
                    text-center
                    text-red-600
                "
            >

                Shipment not found for AWB:

                <strong>
                    {{ awb_no }}
                </strong>

            </div>

            {% endif %}

        {% endif %}

    </div>
    """

    return render_page(
        "Track Shipment",
        render_template_string(
            tracking_html,
            awb_no=awb_no,
            shipment=shipment,
            tracking_rows=tracking_rows
        )
    )


# ============================================================
# TRACKING DIRECT AWB URL
# ============================================================

@app.route("/tracking/<awb_no>")
def tracking_direct(awb_no):

    normalized_awb = normalize_awb(
        awb_no
    )

    return redirect(
        url_for(
            "tracking_search",
            awb=normalized_awb
        )
    )


# ============================================================
# SHIPMENT SEARCH API
# ============================================================

@app.route("/api/shipments/search")
@login_required
def api_search_shipments():

    query_text = clean_text(
        request.args.get(
            "q",
            ""
        ),
        100
    )

    if not query_text:

        return jsonify([])

    like_value = f"%{query_text}%"

    try:

        rows = db_fetchall(
            """
            SELECT
                id,
                awb_no,
                sender_name,
                receiver_name,
                destination,
                status,
                total_amount
            FROM shipments
            WHERE
                awb_no LIKE %s
                OR sender_name LIKE %s
                OR receiver_name LIKE %s
                OR receiver_phone LIKE %s
            ORDER BY id DESC
            LIMIT 30
            """,
            (
                like_value,
                like_value,
                like_value,
                like_value
            )
        )

        return jsonify(
            rows
        )

    except Exception:

        logger.exception(
            "Shipment API search failed."
        )

        return jsonify({
            "error": "Unable to search shipments."
        }), 500


# ============================================================
# PART 4 END
# ============================================================

# ============================================================
# CUSTOMER DETAILS
# ============================================================

@app.route("/customers/<int:cid>")
@login_required
def customer_details(cid):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM customers WHERE id = %s",
        (cid,)
    )

    customer = cur.fetchone()

    if not customer:
        cur.close()
        conn.close()

        flash("Customer not found.", "danger")
        return redirect(url_for("customers"))

    cur.execute(
        """
        SELECT *
        FROM shipments
        WHERE customer_id = %s
        ORDER BY created_at DESC
        """,
        (cid,)
    )

    shipments = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "customer_details.html",
        customer=customer,
        shipments=shipments
    )


# ============================================================
# SEARCH
# ============================================================

@app.route("/search")
@login_required
def search():
    query = request.args.get("q", "").strip()

    results = {
        "shipments": [],
        "customers": []
    }

    if not query:
        return render_template(
            "search.html",
            query=query,
            results=results
        )

    conn = get_db_connection()
    cur = conn.cursor()

    search_value = f"%{query}%"

    try:
        cur.execute(
            """
            SELECT *
            FROM shipments
            WHERE
                awb_number LIKE %s
                OR sender_name LIKE %s
                OR receiver_name LIKE %s
                OR receiver_phone LIKE %s
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (
                search_value,
                search_value,
                search_value,
                search_value
            )
        )

        results["shipments"] = cur.fetchall()

        cur.execute(
            """
            SELECT *
            FROM customers
            WHERE
                name LIKE %s
                OR phone LIKE %s
                OR email LIKE %s
            ORDER BY name ASC
            LIMIT 50
            """,
            (
                search_value,
                search_value,
                search_value
            )
        )

        results["customers"] = cur.fetchall()

    finally:
        cur.close()
        conn.close()

    return render_template(
        "search.html",
        query=query,
        results=results
    )


# ============================================================
# PUBLIC TRACKING PAGE
# ============================================================

@app.route("/track", methods=["GET", "POST"])
def public_track():
    shipment = None
    awb = ""

    if request.method == "POST":
        awb = request.form.get("awb_number", "").strip()
    else:
        awb = request.args.get("awb", "").strip()

    if awb:
        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute(
                """
                SELECT *
                FROM shipments
                WHERE awb_number = %s
                """,
                (awb,)
            )

            shipment = cur.fetchone()

        finally:
            cur.close()
            conn.close()

    return render_template(
        "track.html",
        shipment=shipment,
        awb=awb
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health_check():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT 1")
        cur.fetchone()

        cur.close()
        conn.close()

        return {
            "status": "ok",
            "database": "connected"
        }, 200

    except Exception as e:
        return {
            "status": "error",
            "database": str(e)
        }, 500


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):
    return render_template(
        "error.html",
        error_code=404,
        error_message="The page you are looking for does not exist."
    ), 404


@app.errorhandler(500)
def internal_server_error(error):
    return render_template(
        "error.html",
        error_code=500,
        error_message="An internal server error occurred."
    ), 500


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_application():
    """
    Initialize all required database tables.
    """

    try:
        init_db()
        print("Database initialization completed successfully.")

    except Exception as e:
        print(f"Database initialization error: {e}")


# ============================================================
# APPLICATION ENTRY POINT
# ============================================================

initialize_application()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
