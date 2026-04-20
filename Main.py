import os
import uuid
import traceback
from datetime import datetime, timedelta
from collections import deque

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "levelone_produccion_segura_2026")

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def get_cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def init_db():
    conn = get_db()
    cur = get_cur(conn)
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, sticker_id TEXT UNIQUE NOT NULL,
        full_name TEXT, phone TEXT, email TEXT, address TEXT, cbu_alias TEXT NOT NULL,
        password_hash TEXT NOT NULL, current_level INTEGER DEFAULT 5,
        referrals_completed_count INTEGER DEFAULT 0, is_level1 BOOLEAN DEFAULT FALSE,
        role TEXT DEFAULT 'seller', graduated_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS referral_tree (
        id SERIAL PRIMARY KEY, parent_id INTEGER, child_id INTEGER, UNIQUE(parent_id, child_id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS cycles (
        id SERIAL PRIMARY KEY, l5_user_id INTEGER NOT NULL, status TEXT DEFAULT 'active', completed_at TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS cycle_levels (
        id SERIAL PRIMARY KEY, user_id INTEGER, cycle_id INTEGER,
        level INTEGER DEFAULT 5, is_graduated BOOLEAN DEFAULT FALSE, UNIQUE(user_id, cycle_id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS stickers (
        id SERIAL PRIMARY KEY, sticker_code TEXT UNIQUE NOT NULL,
        seller_id INTEGER, cycle_id INTEGER, buyer_name TEXT, buyer_phone TEXT,
        buyer_email TEXT, buyer_cbu TEXT, step INTEGER DEFAULT 1,
        confirmation_token TEXT, temp_pass TEXT, status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cur.execute("SELECT id FROM users WHERE sticker_id=%s", ('ADMIN001',))
    if not cur.fetchone():
        cur.execute('''INSERT INTO users (sticker_id, full_name, email, phone, cbu_alias, password_hash, current_level, is_level1, role)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                     ('ADMIN001', 'Administrador', 'admin@levelone.com', '+5491100000000', 'admin.levelone.mp',
                      generate_password_hash("Admin2026!", method='pbkdf2:sha256'), 1, True, 'level1'))
    conn.commit()
    print("✅ DB lista.", flush=True)
    conn.close()

init_db()

@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/ingresar", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        sid = request.form["sticker_id"].strip()
        pwd = request.form["password"].strip()
        conn = get_db()
        cur = get_cur(conn)
        cur.execute("SELECT * FROM users WHERE sticker_id=%s", (sid,))
        row_u = cur.fetchone()
        if row_u and check_password_hash(row_u["password_hash"], pwd):
            session["user_id"] = row_u["id"]
            session["role"] = row_u["role"]
            conn.close()
            return redirect(url_for("dashboard"))
        flash("Sticker o contraseña incorrectos.")
        conn.close()
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    cur = get_cur(conn)
    
    cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
    row_u = cur.fetchone()
    if not row_u:
        session.clear()
        conn.close()
        return redirect(url_for("login"))
    
    u = dict(row_u)
    uid = u.get("id")
    role = u.get("role", "seller")
    sticker = u.get("sticker_id", "")
    level = u.get("current_level", 5)

    if level == 5:
        cur.execute("SELECT * FROM cycles WHERE l5_user_id=%s", (uid,))
        cycles = cur.fetchall()
    else:
        cur.execute("SELECT * FROM cycles WHERE l5_user_id=%s OR id IN (SELECT cycle_id FROM cycle_levels WHERE user_id=%s)", (uid, uid))
        cycles = cur.fetchall()
        
    cycle_id = request.args.get("cycle_id", type=int)
    if not cycle_id and cycles:
        cycle_id = cycles[-1]["id"]
    
    active_cycle = None
    if cycle_id:
        cur.execute("SELECT * FROM cycles WHERE id=%s", (cycle_id,))
        active_cycle = cur.fetchone()
        
    cycle_level = level
    is_graduated_cycle = False
    if active_cycle:
        cur.execute("SELECT level, is_graduated FROM cycle_levels WHERE user_id=%s AND cycle_id=%s", (uid, cycle_id))
        cl = cur.fetchone()
        if cl:
            cycle_level = cl["level"]
            is_graduated_cycle = bool(cl["is_graduated"])

    pending = None
    if level == 5 and active_cycle:
        cur.execute("SELECT * FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status IN ('pending', 'sent', 'confirmed') ORDER BY created_at DESC LIMIT 1", (uid, active_cycle["id"]))
        pending_row = cur.fetchone()
        pending = dict(pending_row) if pending_row else None

    pending_cbu = "No configurado"
    pending_phone = "No configurado"
    if pending:
        step = pending["step"]
        cid = pending["cycle_id"] or active_cycle["id"]
        if step == 1:
            cur.execute("SELECT cbu_alias FROM users WHERE sticker_id=%s", ('ADMIN001',))
            row = cur.fetchone()
        elif step == 2:
            cur.execute("SELECT user_id FROM cycle_levels WHERE cycle_id=%s AND level=1 LIMIT 1", (cid,))
            l1_row = cur.fetchone()
            if l1_row:
                cur.execute("SELECT cbu_alias FROM users WHERE id=%s", (l1_row["user_id"],))
                row = cur.fetchone()
            else:
                row = None
        else:
            cur.execute("SELECT cbu_alias FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
        pending_cbu = row["cbu_alias"] if row else "No configurado"
        pending_phone = pending["buyer_phone"] or "No configurado"

    confirmations = []
    if sticker == 'ADMIN001':
        cur.execute("SELECT id, sticker_code, buyer_name, buyer_cbu, cycle_id, step, status FROM stickers WHERE step=1 AND status='sent' ORDER BY created_at DESC")
        confirmations = cur.fetchall()
    elif level != 5 and role != "graduated":
        cur.execute("SELECT cycle_id FROM cycle_levels WHERE user_id=%s AND level=1", (uid,))
        l1_cycles = [r["cycle_id"] for r in cur.fetchall()]
        if l1_cycles:
            ph = ','.join(['%s'] * len(l1_cycles))
            query = f"SELECT id, sticker_code, buyer_name, buyer_cbu, cycle_id, step, status FROM stickers WHERE step=2 AND status='sent' AND cycle_id IN ({ph})"
            cur.execute(query, l1_cycles)
            confirmations = cur.fetchall()

    participants = []
    if level != 5 and sticker != "ADMIN001" and role != "graduated":
        try:
            desc_ids = []
            queue, visited = deque([uid]), set([uid])
            while queue:
                curr = queue.popleft()
                cur.execute("SELECT child_id FROM referral_tree WHERE parent_id=%s", (curr,))
                for r in cur.fetchall():
                    cid = r["child_id"]
                    if cid and cid not in visited:
                        visited.add(cid)
                        desc_ids.append(cid)
                        queue.append(cid)
            all_ids = [uid] + desc_ids
            ph = ','.join(['%s'] * len(all_ids))
            cur.execute(f"SELECT id, sticker_id, full_name, phone, current_level FROM users WHERE id IN ({ph})", all_ids)
            participants = [dict(p) for p in cur.fetchall()]
            sales_map = {}
            cur.execute(f"SELECT seller_id, COUNT(*) as cnt FROM stickers WHERE seller_id IN ({ph}) AND status='entregado' GROUP BY seller_id", all_ids)
            for r in cur.fetchall():
                sales_map[r["seller_id"]] = r["cnt"]
            for p in participants:
                p["sales_done"] = 3 if (sales_map.get(p["id"], 0) == 0 and p["current_level"] < 5) else sales_map.get(p["id"], 0)
                if active_cycle:
                    cur.execute("SELECT level FROM cycle_levels WHERE user_id=%s AND cycle_id=%s", (p["id"], cycle_id))
                    cl = cur.fetchone()
                    p["level"] = cl["level"] if cl else p["current_level"]
                else:
                    p["level"] = p["current_level"]
        except:
            pass

    my_sales_history = []
    income_history = []
    cur.execute("SELECT * FROM stickers WHERE seller_id=%s ORDER BY created_at DESC", (uid,))
    my_sales_history = [dict(s) for s in cur.fetchall()]
    if sticker == "ADMIN001":
        cur.execute("SELECT * FROM stickers WHERE step=1 AND status IN ('confirmed', 'entregado') ORDER BY created_at DESC")
        income_history = [dict(r) for r in cur.fetchall()]
    elif level == 5:
        cur.execute("SELECT * FROM stickers WHERE seller_id=%s AND status='entregado' ORDER BY created_at DESC", (uid,))
        income_history = [dict(r) for r in cur.fetchall()]
    else:
        cur.execute("SELECT cycle_id FROM cycle_levels WHERE user_id=%s AND level=1", (uid,))
        l1_cycles = [r["cycle_id"] for r in cur.fetchall()]
        if l1_cycles:
            ph = ','.join(['%s'] * len(l1_cycles))
            cur.execute(f"SELECT * FROM stickers WHERE step=2 AND status IN ('confirmed', 'entregado') AND cycle_id IN ({ph}) ORDER BY created_at DESC", l1_cycles)
            income_history = [dict(r) for r in cur.fetchall()]

    try:
        active_cycles_display = [c for c in cycles if not (c["completed_at"] and (datetime.now() - datetime.strptime(c["completed_at"], "%Y-%m-%d %H:%M:%S")).days > 30)]
    except:
        active_cycles_display = cycles

    conn.close()
    return render_template("dashboard.html", user=u, cycles=active_cycles_display, active_cycle=active_cycle, cycle_level=cycle_level, is_graduated_cycle=is_graduated_cycle, participants=participants, pending=pending, pending_cbu=pending_cbu, pending_phone=pending_phone, confirmations=confirmations, my_sales=[{"sale":s,"num":len(my_sales_history)-i} for i,s in enumerate(my_sales_history)], income=[{"sale":s,"num":len(income_history)-i} for i,s in enumerate(income_history)])

@app.route("/crear_sticker", methods=["POST"])
def crear_sticker():
    if "user_id" not in session:
        return redirect("/login")
    conn = get_db()
    cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
        row_u = cur.fetchone()
        if not row_u or row_u["current_level"] != 5:
            flash("Solo Nivel 5 puede crear stickers.")
            conn.close()
            return redirect("/dashboard")
        name = request.form.get("name","").strip()
        phone = request.form.get("phone","").strip()
        email = request.form.get("email","").strip()
        cbu = request.form.get("cbu","").strip()
        if not all([name, phone, email, cbu]):
            flash("Todos los campos son obligatorios.")
            conn.close()
            return redirect("/dashboard")

        cur.execute("SELECT id FROM cycles WHERE l5_user_id=%s AND status='active'", (row_u["id"],))
        cycle = cur.fetchone()
        if not cycle:
            cur.execute("INSERT INTO cycles (l5_user_id) VALUES (%s) RETURNING id", (row_u["id"],))
            cycle_id = cur.fetchone()["id"]
            cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO NOTHING", (row_u["id"], cycle_id, 5))
            parent = row_u["id"]
            while True:
                cur.execute("SELECT parent_id FROM referral_tree WHERE child_id=%s", (parent,))
                up = cur.fetchone()
                if not up:
                    break
                parent = up["parent_id"]
                cur.execute("SELECT current_level FROM users WHERE id=%s", (parent,))
                pr = cur.fetchone()
                lvl = pr["current_level"] if pr else 1
                cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO NOTHING", (parent, cycle_id, lvl))
        else:
            cycle_id = cycle["id"]

        cur.execute("SELECT id FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status != 'entregado' LIMIT 1", (row_u["id"], cycle_id))
        if cur.fetchone():
            flash("Espera a completar el sticker actual.")
            conn.close()
            return redirect(url_for("dashboard", cycle_id=cycle_id))
        cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status='entregado'", (row_u["id"], cycle_id))
        completed = cur.fetchone()["cnt"]
        if completed >= 3:
            flash("Ciclo completado.")
            conn.close()
            return redirect(url_for("dashboard", cycle_id=cycle_id))

        code = "STK-"+str(uuid.uuid4())[:6].upper()
        temp_pass = "Temp-"+str(uuid.uuid4())[:8]
        cur.execute('''INSERT INTO stickers (sticker_code,seller_id,cycle_id,buyer_name,buyer_phone,buyer_email,buyer_cbu,step,confirmation_token,temp_pass,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (code,row_u["id"],cycle_id,name,phone,email,cbu,completed+1,str(uuid.uuid4())[:12],temp_pass,'pending'))
        cur.execute('''INSERT INTO users (sticker_id,full_name,phone,email,cbu_alias,password_hash,role) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (code,name,phone,email,cbu,generate_password_hash(temp_pass,method='pbkdf2:sha256'),'inactive'))
        new_id = cur.fetchone()["id"]
        if new_id:
            cur.execute("INSERT INTO referral_tree (parent_id, child_id) VALUES (%s,%s) ON CONFLICT (parent_id,child_id) DO NOTHING", (row_u["id"], new_id))
        conn.commit()
        flash("Sticker creado.")
        return redirect(url_for("dashboard", cycle_id=cycle_id))
    except Exception as e:
        conn.rollback()
        print(f"[ERROR CREAR] {traceback.format_exc()}", flush=True)
        flash(f"Error: {str(e)}")
    finally:
        conn.close()
    return redirect("/dashboard")

@app.route("/marcar_enviado/<int:sticker_id>", methods=["POST"])
def marcar_enviado(sticker_id):
    conn = get_db()
    cur = get_cur(conn)
    cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,))
    s = cur.fetchone()
    if s and s["status"] == "pending":
        cur.execute("UPDATE stickers SET status='sent' WHERE id=%s", (sticker_id,))
    conn.commit()
    conn.close()
    return redirect("/dashboard")

@app.route("/resolver_confirmacion/<int:sticker_id>/<action>", methods=["POST"])
def resolver_confirmacion(sticker_id, action):
    conn = get_db()
    cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,))
        s = cur.fetchone()
        if s and s["status"] == "sent":
            if action == "confirm":
                new_step = s["step"] + 1
                cur.execute("UPDATE stickers SET status='sent', step=%s WHERE id=%s", (new_step, s["id"]))
            else:
                cur.execute("UPDATE stickers SET status='pending' WHERE id=%s", (sticker_id,))
        conn.commit()
        if s and s["cycle_id"]:
            return redirect(url_for("dashboard", cycle_id=s["cycle_id"]))
    finally:
        cur.close()
        conn.close()
    return redirect("/dashboard")

@app.route("/confirmar_paso3/<int:sticker_id>", methods=["POST"])
def confirmar_paso3(sticker_id):
    conn = get_db()
    cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,))
        s = cur.fetchone()
        if s and s["step"] == 3 and s["status"] != "entregado":
            cur.execute("UPDATE stickers SET status='entregado' WHERE id=%s", (sticker_id,))
            cid, sid = s["cycle_id"], s["seller_id"]
            cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status='entregado'", (sid, cid))
            entregados = cur.fetchone()["cnt"]
            if entregados == 3:
                cur.execute("UPDATE users SET current_level=4 WHERE id=%s", (sid,))
                cur.execute("UPDATE cycle_levels SET level=4 WHERE user_id=%s AND cycle_id=%s", (sid, cid))
                parent = sid
                while True:
                    cur.execute("SELECT parent_id FROM referral_tree WHERE child_id=%s", (parent,))
                    row = cur.fetchone()
                    if not row:
                        break
                    parent = row["parent_id"]
                    cur.execute("SELECT level FROM cycle_levels WHERE user_id=%s AND cycle_id=%s", (parent, cid))
                    cl = cur.fetchone()
                    if cl:
                        nl = max(1, cl["level"]-1)
                        cur.execute("UPDATE cycle_levels SET level=%s, is_graduated=%s WHERE user_id=%s AND cycle_id=%s", (nl, nl==1, parent, cid))
                        cur.execute("UPDATE users SET current_level=%s WHERE id=%s", (nl, parent))
                cur.execute("UPDATE cycles SET status='completed', completed_at=%s WHERE id=%s", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cid))
            conn.commit()
            flash("✅ Venta confirmada. Ciclo cerrado.")
        else:
            flash("Estado incorrecto.")
    finally:
        cur.close()
        conn.close()
    return redirect("/dashboard")

@app.route("/enviar_acceso/<int:sticker_id>", methods=["POST"])
def enviar_acceso(sticker_id):
    conn = get_db()
    cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,))
        s = cur.fetchone()
        if not s or s["status"] != "confirmed":
            flash("Pago no confirmado.")
            conn.close()
            return redirect("/dashboard")
        cur.execute("UPDATE stickers SET status='entregado' WHERE id=%s", (sticker_id,))
        conn.commit()
        flash("Acceso enviado.")
    finally:
        cur.close()
        conn.close()
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/ingresar")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
