import os
import uuid
import sys
import traceback
from datetime import datetime, timedelta
from collections import deque

try: import resend
except ImportError: resend = None
try: from twilio.rest import Client
except ImportError: Client = None

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "levelone_produccion_segura_2026")
DB_NAME = "levelone.db"

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE = os.environ.get("TWILIO_PHONE", "")

if resend and RESEND_API_KEY: resend.api_key = RESEND_API_KEY
else: resend = None

twilio_client = None
if Client and TWILIO_SID and TWILIO_TOKEN and TWILIO_PHONE:
    try: twilio_client = Client(TWILIO_SID, TWILIO_TOKEN)
    except: twilio_client = None

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, sticker_id TEXT UNIQUE NOT NULL,
        full_name TEXT, phone TEXT, email TEXT, address TEXT, cbu_alias TEXT NOT NULL,
        password_hash TEXT NOT NULL, current_level INTEGER DEFAULT 5,
        referrals_completed_count INTEGER DEFAULT 0, is_level1 BOOLEAN DEFAULT 0,
        role TEXT DEFAULT 'seller', graduated_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS referral_tree (
        id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER, child_id INTEGER, UNIQUE(parent_id, child_id)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT, l5_user_id INTEGER NOT NULL, status TEXT DEFAULT 'active', completed_at TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS cycle_levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, cycle_id INTEGER,
        level INTEGER DEFAULT 5, is_graduated BOOLEAN DEFAULT 0, UNIQUE(user_id, cycle_id)
    )''')
    try: conn.execute("ALTER TABLE cycles ADD COLUMN completed_at TIMESTAMP")
    except: pass
    try: conn.execute("ALTER TABLE cycle_levels ADD COLUMN is_graduated BOOLEAN DEFAULT 0")
    except: pass
    try: conn.execute("ALTER TABLE stickers ADD COLUMN cycle_id INTEGER")
    except: pass
    conn.commit()

    cur = conn.execute("SELECT id FROM users WHERE sticker_id='ADMIN001'")
    if not cur.fetchone():
        conn.execute('''INSERT INTO users (sticker_id, full_name, email, phone, cbu_alias, password_hash, current_level, is_level1, role)
                        VALUES ('ADMIN001', 'Administrador', 'admin@levelone.com', '+5491100000000', 'admin.levelone.mp', ?, 1, 1, 'level1')''',
                     (generate_password_hash("Admin2026!", method='pbkdf2:sha256'),))
    conn.commit()
    print("Sistema listo. Historial dual implementado.", flush=True)
    conn.close()

init_db()

@app.route("/")
def index(): return redirect(url_for("login"))

@app.route("/ingresar", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        sid = request.form["sticker_id"].strip()
        pwd = request.form["password"].strip()
        conn = get_db()
        row_u = conn.execute("SELECT * FROM users WHERE sticker_id=?", (sid,)).fetchone()
        if row_u and check_password_hash(row_u["password_hash"], pwd):
            session["user_id"] = row_u["id"]; session["role"] = row_u["role"]
            conn.close(); return redirect(url_for("dashboard"))
        flash("Sticker o contraseña incorrectos."); conn.close()
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session: return redirect(url_for("login"))
    conn = get_db()
    row_u = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not row_u: session.clear(); conn.close(); return redirect(url_for("login"))
    
    u = dict(row_u)
    uid = u.get("id"); role = u.get("role", "seller")
    sticker = u.get("sticker_id", ""); level = u.get("current_level", 5)

    if level == 5:
        try: cycles = conn.execute("SELECT * FROM cycles WHERE l5_user_id=?", (uid,)).fetchall()
        except: cycles = []
    else:
        try: cycles = conn.execute("SELECT * FROM cycles WHERE l5_user_id=? OR id IN (SELECT cycle_id FROM cycle_levels WHERE user_id=?)", (uid, uid)).fetchall()
        except: cycles = []
    
    cycle_id = request.args.get("cycle_id", type=int)
    if not cycle_id and cycles: cycle_id = cycles[-1]["id"]
    active_cycle = conn.execute("SELECT * FROM cycles WHERE id=?", (cycle_id,)).fetchone() if cycle_id else None
    
    cycle_level = level; is_graduated_cycle = False
    if active_cycle:
        try:
            cl = conn.execute("SELECT level, is_graduated FROM cycle_levels WHERE user_id=? AND cycle_id=?", (uid, cycle_id)).fetchone()
            if cl: cycle_level = cl["level"]; is_graduated_cycle = bool(cl["is_graduated"])
        except: pass

    completed_count = 0; pending = None
    pending_cbu = "No configurado"; pending_phone = "No configurado"
    confirmations = []; participants = []

    # 🔵 Red de descendientes (para tabla de estado)
    if level != 5 and sticker != "ADMIN001" and role != "graduated":
        try:
            desc_ids = []; queue, visited = deque([uid]), set([uid])
            while queue:
                curr = queue.popleft()
                rows = conn.execute("SELECT child_id FROM referral_tree WHERE parent_id=?", (curr,)).fetchall()
                for r in rows:
                    cid = r["child_id"]
                    if cid and cid not in visited: visited.add(cid); desc_ids.append(cid); queue.append(cid)

            all_ids = [uid] + desc_ids
            ph = ','.join('?' * len(all_ids))
            participants = conn.execute(f"SELECT id, sticker_id, full_name, phone, current_level FROM users WHERE id IN ({ph})", all_ids).fetchall()
            participants = [dict(p) for p in participants]
            
            sales_map = {}
            try:
                cnt_rows = conn.execute(f"SELECT seller_id, COUNT(*) as cnt FROM stickers WHERE seller_id IN ({ph}) AND LOWER(status) = 'entregado' GROUP BY seller_id", all_ids).fetchall()
                sales_map = {r["seller_id"]: r["cnt"] for r in cnt_rows}
            except: pass

            for p in participants:
                raw = sales_map.get(p["id"], 0)
                p["sales_done"] = 3 if (raw == 0 and p["current_level"] < 5) else raw
                if active_cycle:
                    cl = conn.execute("SELECT level FROM cycle_levels WHERE user_id=? AND cycle_id=?", (p["id"], cycle_id)).fetchone()
                    p["level"] = cl["level"] if cl else p["current_level"]
                else: p["level"] = p["current_level"]
        except: pass

    # CBU PENDING
    if pending:
        step = pending["step"]; cid = pending["cycle_id"] if pending["cycle_id"] else cycle_id
        if step == 1: row = conn.execute("SELECT cbu_alias FROM users WHERE sticker_id='ADMIN001'").fetchone()
        elif step == 2 and cid:
            l1_row = conn.execute("SELECT user_id FROM cycle_levels WHERE cycle_id=? AND level=1 LIMIT 1", (cid,)).fetchone()
            row = conn.execute("SELECT cbu_alias FROM users WHERE id=?", (l1_row["user_id"],)).fetchone() if l1_row else None
        else: row = conn.execute("SELECT cbu_alias FROM users WHERE id=?", (uid,)).fetchone()
        pending_cbu = row["cbu_alias"] if row else "No configurado"
        pending_phone = pending["buyer_phone"] or "No configurado"

    # CONFIRMACIONES PASO 2
    if level != 5 and sticker != "ADMIN001" and role != "graduated":
        try:
            l1_cycles = [r[0] for r in conn.execute("SELECT cycle_id FROM cycle_levels WHERE user_id=? AND level=1", (uid,)).fetchall()]
            if l1_cycles:
                ph2 = ','.join('?' * len(l1_cycles))
                confirmations = conn.execute(f"SELECT * FROM stickers WHERE step=2 AND status IN ('sent', 'confirmed') AND cycle_id IN ({ph2})", l1_cycles).fetchall()
        except: pass

    # 📊 HISTORIAL DUAL
    my_sales_history = []
    income_history = []
    try:
        # 1. MIS VENTAS (Todos ven lo que vendieron)
        sales_rows = conn.execute("SELECT * FROM stickers WHERE seller_id=? ORDER BY created_at DESC", (uid,)).fetchall()
        my_sales_history = [dict(s) for s in sales_rows]
        
        # 2. INGRESOS CONFIRMADOS (Solo pagos recibidos según step)
        if sticker == "ADMIN001":
            inc_rows = conn.execute("SELECT * FROM stickers WHERE step=1 AND status IN ('confirmed', 'entregado') ORDER BY created_at DESC").fetchall()
            income_history = [dict(r) for r in inc_rows]
        elif level == 5:
            inc_rows = conn.execute("SELECT * FROM stickers WHERE seller_id=? AND status='entregado' ORDER BY created_at DESC", (uid,)).fetchall()
            income_history = [dict(r) for r in inc_rows]
        else:
            l1_cycles = [r[0] for r in conn.execute("SELECT cycle_id FROM cycle_levels WHERE user_id=? AND level=1", (uid,)).fetchall()]
            if l1_cycles:
                ph = ','.join('?'*len(l1_cycles))
                inc_rows = conn.execute(f"SELECT * FROM stickers WHERE step=2 AND status IN ('confirmed', 'entregado') AND cycle_id IN ({ph}) ORDER BY created_at DESC", l1_cycles).fetchall()
                income_history = [dict(r) for r in inc_rows]
    except Exception as e: print(f"[ERROR HISTORIAL] {e}", flush=True)

    try: active_cycles_display = [c for c in cycles if not (c["completed_at"] and (datetime.now() - datetime.strptime(c["completed_at"], "%Y-%m-%d %H:%M:%S")).days > 30)]
    except: active_cycles_display = cycles

    # Preparar para template
    total_sales = len(my_sales_history)
    my_sales_with_num = [{"sale": s, "num": total_sales - i} for i, s in enumerate(my_sales_history)]
    total_income = len(income_history)
    income_with_num = [{"sale": s, "num": total_income - i} for i, s in enumerate(income_history)]

    conn.close()
    return render_template("dashboard.html", user=u, cycles=active_cycles_display, active_cycle=active_cycle, cycle_level=cycle_level, is_graduated_cycle=is_graduated_cycle, participants=participants, pending=pending, pending_cbu=pending_cbu, pending_phone=pending_phone, confirmations=confirmations, my_sales=my_sales_with_num, income=income_with_num, completed_count=completed_count)

@app.route("/crear_sticker", methods=["POST"])
def crear_sticker():
    if "user_id" not in session: return redirect("/login")
    conn = get_db(); cur = conn.cursor()
    try:
        row_u = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not row_u: conn.close(); return redirect("/dashboard")
        u = dict(row_u)
        
        if u.get("current_level") != 5: flash("Solo Nivel 5 puede crear stickers."); conn.close(); return redirect("/dashboard")
        
        name = request.form.get("name","").strip(); phone = request.form.get("phone","").strip()
        email = request.form.get("email","").strip(); cbu = request.form.get("cbu","").strip()
        if not all([name, phone, email, cbu]): flash("Todos los campos son obligatorios."); conn.close(); return redirect("/dashboard")

        cycle = cur.execute("SELECT id FROM cycles WHERE l5_user_id=? AND status='active'", (u["id"],)).fetchone()
        
        if not cycle:
            cur.execute("INSERT INTO cycles (l5_user_id) VALUES (?)", (u["id"],))
            cycle_id = cur.lastrowid
            cur.execute("INSERT OR IGNORE INTO cycle_levels (user_id, cycle_id, level) VALUES (?, ?, ?)", (u["id"], cycle_id, u["current_level"]))
            parent = u["id"]
            while True:
                up = cur.execute("SELECT parent_id FROM referral_tree WHERE child_id=?", (parent,)).fetchone()
                if not up: break
                parent = up["parent_id"]
                p_row = cur.execute("SELECT current_level FROM users WHERE id=?", (parent,)).fetchone()
                lvl = p_row["current_level"] if p_row else 1
                cur.execute("INSERT OR IGNORE INTO cycle_levels (user_id, cycle_id, level) VALUES (?, ?, ?)", (parent, cycle_id, lvl))
        else:
            cycle_id = cycle["id"]

        pending_check = cur.execute("SELECT id FROM stickers WHERE seller_id=? AND cycle_id=? AND status != 'entregado' LIMIT 1", (u["id"], cycle_id)).fetchone()
        if pending_check: flash("Espera a completar el sticker actual."); conn.close(); return redirect(url_for("dashboard", cycle_id=cycle_id))

        completed = cur.execute("SELECT COUNT(*) FROM stickers WHERE seller_id=? AND cycle_id=? AND status='entregado'", (u["id"], cycle_id)).fetchone()[0]
        if completed >= 3: flash("Ciclo completado."); conn.close(); return redirect(url_for("dashboard", cycle_id=cycle_id))

        code = "STK-" + str(uuid.uuid4())[:6].upper()
        token, temp_pass = str(uuid.uuid4())[:12], "Temp-" + str(uuid.uuid4())[:8]
        step = completed + 1
        cur.execute('''INSERT INTO stickers (sticker_code, seller_id, cycle_id, buyer_name, buyer_phone, buyer_email, buyer_cbu, step, confirmation_token, temp_pass, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (code, u["id"], cycle_id, name, phone, email, cbu, step, token, temp_pass, 'pending'))
        cur.execute('''INSERT INTO users (sticker_id, full_name, phone, email, cbu_alias, password_hash, role) VALUES (?,?,?,?,?,?,?)''', (code, name, phone, email, cbu, generate_password_hash(temp_pass, method='pbkdf2:sha256'), 'inactive'))
        
        new_user_id = cur.lastrowid
        if new_user_id:
            cur.execute("INSERT OR IGNORE INTO referral_tree (parent_id, child_id) VALUES (?, ?)", (u["id"], new_user_id))
            
        conn.commit(); flash("Sticker creado."); return redirect(url_for("dashboard", cycle_id=cycle_id))
    except Exception as e: conn.rollback(); print(f"[ERROR CREAR] {traceback.format_exc()}", flush=True); flash(f"Error: {str(e)}")
    finally: conn.close()
    return redirect("/dashboard")

@app.route("/enviar_acceso/<int:sticker_id>", methods=["POST"])
def enviar_acceso(sticker_id):
    conn = get_db()
    s = conn.execute("SELECT * FROM stickers WHERE id=?", (sticker_id,)).fetchone()
    if not s or s["status"] != "confirmed": flash("Pago no confirmado."); conn.close(); return redirect("/dashboard")
    if resend and RESEND_API_KEY and s["buyer_email"]:
        try: resend.Emails.send({"from": "onboarding@resend.dev", "to": [s["buyer_email"]], "subject": "Acceso levelONE", "text": f"Sticker: {s['sticker_code']}\nPass: {s['temp_pass']}"})
        except: pass
    conn.execute("UPDATE stickers SET status='entregado' WHERE id=?", (sticker_id,))
    cycle_id, seller_id = s["cycle_id"], s["seller_id"]
    entregados = conn.execute("SELECT COUNT(*) FROM stickers WHERE seller_id=? AND cycle_id=? AND status='entregado'", (seller_id, cycle_id)).fetchone()[0]
    if entregados == 3:  
        print(f"[DEBUG] 3ra venta cycle_id={cycle_id}. Aplicando cascada global...", flush=True)
        conn.execute("UPDATE users SET current_level=4 WHERE id=?", (seller_id,))
        conn.execute("UPDATE cycle_levels SET level=4 WHERE user_id=? AND cycle_id=?", (seller_id, cycle_id))
        
        parent = seller_id
        while True:
            row = conn.execute("SELECT parent_id FROM referral_tree WHERE child_id=?", (parent,)).fetchone()
            if not row: break
            parent = row["parent_id"]
            cl = conn.execute("SELECT level FROM cycle_levels WHERE user_id=? AND cycle_id=?", (parent, cycle_id)).fetchone()
            if cl:
                new_lvl = max(1, cl["level"] - 1)
                conn.execute("UPDATE cycle_levels SET level=?, is_graduated=? WHERE user_id=? AND cycle_id=?", (new_lvl, new_lvl==1, parent, cycle_id))
                conn.execute("UPDATE users SET current_level=? WHERE id=?", (new_lvl, parent))
                
        conn.execute("UPDATE cycles SET status='completed', completed_at=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cycle_id))
        
        l1s = conn.execute("SELECT id FROM users WHERE current_level=1 OR is_level1=1").fetchall()
        for l1 in l1s:
            l1_id = l1["id"]
            l5_desc = []; q, vis = deque([l1_id]), set([l1_id])
            while q:
                c = q.popleft()
                for ch in conn.execute("SELECT child_id FROM referral_tree WHERE parent_id=?", (c,)).fetchall():
                    cid = ch["child_id"]
                    if cid not in vis:
                        vis.add(cid); q.append(cid)
                        lvl = conn.execute("SELECT current_level FROM users WHERE id=?", (cid,)).fetchone()
                        if lvl and lvl["current_level"] == 5: l5_desc.append(cid)
            cnt_81 = sum(1 for lid in l5_desc if conn.execute("SELECT COUNT(*) FROM stickers WHERE seller_id=? AND status='entregado'", (lid,)).fetchone()[0] >= 3)
            if cnt_81 >= 81:
                conn.execute("UPDATE users SET role='graduated', graduated_at=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), l1_id))
                print(f"L1 ID {l1_id} graduado! 81/81 L5s completados.", flush=True)
        print(f"[DEBUG] Cascada global y verificacion 81 L5s aplicada.", flush=True)
    conn.commit(); conn.close()
    flash("Acceso enviado. Ciclo cerrado y niveles actualizados." if entregados == 3 else "Acceso enviado. Venta registrada.")
    return redirect("/dashboard")

@app.route("/marcar_enviado/<int:sticker_id>", methods=["POST"])
def marcar_enviado(sticker_id):
    conn = get_db()
    s = conn.execute("SELECT * FROM stickers WHERE id=?", (sticker_id,)).fetchone()
    if s and s["status"] == "pending": conn.execute("UPDATE stickers SET status='sent' WHERE id=?", (sticker_id,))
    conn.commit(); conn.close(); return redirect("/dashboard")

@app.route("/resolver_confirmacion/<int:sticker_id>/<action>", methods=["POST"])
def resolver_confirmacion(sticker_id, action):
    conn = get_db()
    s = conn.execute("SELECT * FROM stickers WHERE id=?", (sticker_id,)).fetchone()
    if s and s["status"] == "sent":
        if action == "confirm": conn.execute("UPDATE stickers SET status='confirmed', step=? WHERE id=?", (s["step"]+1, s["id"]))
        else: conn.execute("UPDATE stickers SET status='pending' WHERE id=?", (sticker_id,))
    conn.commit(); conn.close(); return redirect("/dashboard")

@app.route("/logout")
def logout(): session.clear(); return redirect("/ingresar")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)