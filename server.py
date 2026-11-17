import os
import sqlite3
import secrets
from datetime import datetime
from typing import Optional
import urllib.request
import urllib.parse
import json

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ==========================================
# 1. CONFIGURATION (FILL THESE IN ON VPS)
# ==========================================
ADMIN_PASSWORD = "CHANGE_THIS_TO_YOUR_SECRET_PASSWORD"
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"   # From @BotFather
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"       # From @userinfobot
DB_PATH = "/var/www/qvaxzion/qvaxzion.db"

app = FastAPI(title="QVAXZION Luxury Flagship Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 2. DATABASE INITIALIZATION (SQLITE)
# ==========================================
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_ref TEXT UNIQUE,
            client_name TEXT NOT NULL,
            client_contact TEXT NOT NULL,
            item_name TEXT NOT NULL,
            size_spec TEXT,
            order_type TEXT NOT NULL,
            notes TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vip_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_code TEXT UNIQUE NOT NULL,
            member_name TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    # Seed one master VIP key if empty
    c.execute("SELECT COUNT(*) FROM vip_keys")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO vip_keys (access_code, member_name, active, created_at) VALUES (?, ?, 1, ?)",
            ("QVAX-FOUNDER-001", "Founding Member", datetime.utcnow().isoformat())
        )
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 3. INSTANT TELEGRAM PHONE NOTIFICATION
# ==========================================
def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or "YOUR_TELEGRAM" in TELEGRAM_BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload)
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"Alert failed: {e}")

# ==========================================
# 4. DATA MODELS
# ==========================================
class OrderRequest(BaseModel):
    client_name: str
    client_contact: str
    item_name: str
    size_spec: Optional[str] = "Bespoke / Standard"
    order_type: str = "Capsule Order"  # e.g., Capsule Order, 1-of-1 Footwear, Private Fitting
    notes: Optional[str] = ""

class VIPVerifyRequest(BaseModel):
    access_code: str

class StatusUpdateRequest(BaseModel):
    status: str

class NewVIPKeyRequest(BaseModel):
    member_name: str
    custom_code: Optional[str] = None

# ==========================================
# 5. PUBLIC STOREFRONT ENDPOINTS
# ==========================================
@app.post("/api/orders")
def create_order(order: OrderRequest):
    order_ref = f"QVAX-{secrets.token_hex(3).upper()}"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO orders (order_ref, client_name, client_contact, item_name, size_spec, order_type, notes, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
    """, (order_ref, order.client_name, order.client_contact, order.item_name, order.size_spec, order.order_type, order.notes, now))
    conn.commit()
    conn.close()

    alert_msg = (
        f"🖤 *NEW QVAXZION {order.order_type.upper()}*\n"
        f"*Ref:* `{order_ref}`\n"
        f"*Piece:* {order.item_name}\n"
        f"*Size/Spec:* {order.size_spec}\n"
        f"*Client:* {order.client_name}\n"
        f"*Contact:* {order.client_contact}\n"
        f"*Notes:* {order.notes or 'None'}"
    )
    send_telegram_alert(alert_msg)

    return {"status": "success", "order_ref": order_ref, "message": "Request logged with QVAXZION Concierge."}

@app.post("/api/vip/verify")
def verify_vip(req: VIPVerifyRequest):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT member_name FROM vip_keys WHERE access_code = ? AND active = 1", (req.access_code.strip(),))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or revoked VIP Vault key.")
    return {"status": "unlocked", "member_name": row[0]}

# ==========================================
# 6. PROTECTED ADMIN COMMAND ENDPOINTS
# ==========================================
def check_admin(x_admin_password: Optional[str]):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized Admin Access")

@app.get("/api/admin/orders")
def list_orders(x_admin_password: Optional[str] = Header(None)):
    check_admin(x_admin_password)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return {"orders": rows}

@app.patch("/api/admin/orders/{order_ref}")
def update_order_status(order_ref: str, req: StatusUpdateRequest, x_admin_password: Optional[str] = Header(None)):
    check_admin(x_admin_password)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE orders SET status = ? WHERE order_ref = ?", (req.status, order_ref))
    conn.commit()
    conn.close()
    return {"status": "updated", "order_ref": order_ref, "new_status": req.status}

@app.post("/api/admin/vip")
def create_vip_key(req: NewVIPKeyRequest, x_admin_password: Optional[str] = Header(None)):
    check_admin(x_admin_password)
    code = req.custom_code.strip().upper() if req.custom_code else f"QVAX-{secrets.token_hex(3).upper()}"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO vip_keys (access_code, member_name, active, created_at) VALUES (?, ?, 1, ?)", (code, req.member_name, now))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="VIP Code already exists.")
    conn.close()
    return {"status": "created", "access_code": code, "member_name": req.member_name}
