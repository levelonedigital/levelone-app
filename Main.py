import os
import uuid
import traceback
import requests
from datetime import datetime, timedelta
from collections import deque

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
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
    
    # Crear tablas (sin DROP para preservar datos entre deployments)
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, sticker_id TEXT UNIQUE NOT NULL,
        full_name TEXT, phone TEXT, email TEXT, address TEXT, cbu_alias TEXT NOT NULL,
        password_hash TEXT NOT NULL, current_level INTEGER DEFAULT 5,
        referrals_completed_count INTEGER DEFAULT 0, is_level1 BOOLEAN DEFAULT FALSE,
        role TEXT DEFAULT 'seller', graduated_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        terms_accepted_at TIMESTAMP NULL, terms_version TEXT DEFAULT 'v1.0'
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
    
    # Insertar Admin solo si no existe
    cur.execute("SELECT id FROM users WHERE sticker_id=%s", ('ADMIN001',))
    if not cur.fetchone():
        cur.execute('''INSERT INTO users (sticker_id, full_name, email, phone, cbu_alias, password_hash, current_level, is_level1, role, terms_accepted_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                     ('ADMIN001', 'Administrador', 'admin@levelone.com', '+5491100000000', 'admin.levelone.mp',
                      generate_password_hash("Admin2026!", method='pbkdf2:sha256'), 1, True, 'level1', datetime.now()))

    # Insertar usuarios demo solo si no existen
    users_data = [
        ('DEMO-L5-01', 'Nivel 5 Demo', '+5491150000001', 'l5@test.com', 'alias.l5', 5),
        ('DEMO-L4-01', 'Nivel 4 Demo', '+5491150000002', 'l4@test.com', 'alias.l4', 4),
        ('DEMO-L3-01', 'Nivel 3 Demo', '+5491150000003', 'l3@test.com', 'alias.l3', 3),
        ('DEMO-L2-01', 'Nivel 2 Demo', '+5491150000004', 'l2@test.com', 'alias.l2', 2),
        ('DEMO-L1-01', 'Nivel 1 Demo', '+5491150000005', 'l1@test.com', 'alias.l1', 1)
    ]
    inserted_ids = []
    for sid, name, phone, email, cbu, lvl in users_data:
        cur.execute('''INSERT INTO users (sticker_id, full_name, phone, email, cbu_alias, password_hash, current_level, role, terms_accepted_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (sticker_id) DO NOTHING RETURNING id''',
                     (sid, name, phone, email, cbu, generate_password_hash("Demo2026!", method='pbkdf2:sha256'), lvl, 'seller', datetime.now()))
        result = cur.fetchone()
        if result:
            inserted_ids.append(result["id"])
        else:
            cur.execute("SELECT id FROM users WHERE sticker_id=%s", (sid,))
            inserted_ids.append(cur.fetchone()["id"])

    # Crear ciclo base y niveles solo si no existen
    if inserted_ids:
        l5_id = inserted_ids[0]
        cur.execute("SELECT id FROM cycles WHERE l5_user_id=%s", (l5_id,))
        if not cur.fetchone():
            cur.execute("INSERT INTO cycles (l5_user_id) VALUES (%s) RETURNING id", (l5_id,))
            cycle_id = cur.fetchone()["id"]
            for i, uid in enumerate(inserted_ids):
                lvl = 5 - i
                cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO NOTHING", (uid, cycle_id, lvl))
                if i > 0:
                    cur.execute("INSERT INTO referral_tree (parent_id, child_id) VALUES (%s,%s) ON CONFLICT (parent_id,child_id) DO NOTHING", (inserted_ids[i-1], uid))
            
    conn.commit()
    print("✅ DB inicializada (datos preservados).", flush=True)
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
            try:
                if row_u.get("terms_accepted_at") is None:
                    conn.close()
                    return redirect(url_for("accept_terms"))
            except:
                pass
            conn.close()
            return redirect(url_for("dashboard"))
        flash("Sticker o contraseña incorrectos.")
        conn.close()
    return render_template("login.html")

@app.route("/accept_terms")
def accept_terms():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    cur = get_cur(conn)
    cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
    row_u = cur.fetchone()
    conn.close()
    try:
        if not row_u or row_u.get("terms_accepted_at") is not None:
            return redirect(url_for("dashboard"))
    except:
        return redirect(url_for("dashboard"))
    return render_template("login.html", show_terms_modal=True, user=row_u)

@app.route("/api/accept_terms", methods=["POST"])
def api_accept_terms():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "No autenticado"}), 401
    conn = get_db()
    cur = get_cur(conn)
    try:
        cur.execute("UPDATE users SET terms_accepted_at=%s, terms_version=%s WHERE id=%s",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "v1.0", session["user_id"]))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()

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
    try:
        if row_u.get("terms_accepted_at") is None:
            conn.close()
            return redirect(url_for("accept_terms"))
    except:
        pass
    
    u = dict(row_u)
    uid = u.get("id")
    role = u.get("role", "seller")
    sticker = u.get("sticker_id", "")
    level = u.get("current_level", 5)

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
            
    # Sincronizar nivel mostrado con el del ciclo activo
    u["current_level"] = cycle_level

    pending = None
    if active_cycle:
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
        elif step == 3:
            cur.execute("SELECT cbu_alias FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
        else:
            row = None
        pending_cbu = row["cbu_alias"] if row else "No configurado"
        pending_phone = pending["buyer_phone"] or "No configurado"

    confirmations = []
    if sticker == 'ADMIN001':
        cur.execute("SELECT id, sticker_code, buyer_name, buyer_cbu, buyer_phone, cycle_id, step, status FROM stickers WHERE step=1 AND status='sent' ORDER BY created_at DESC")
        confirmations = cur.fetchall()
    elif level != 5 and role != "graduated":
        cur.execute('''SELECT s.id, s.sticker_code, s.buyer_name, s.buyer_cbu, s.buyer_phone, s.cycle_id, s.step, s.status 
                      FROM stickers s
                      JOIN cycle_levels cl ON s.cycle_id = cl.cycle_id
                      WHERE s.step=2 AND s.status='sent' AND cl.level=1 AND cl.user_id=%s''', (uid,))
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
    cur.execute("SELECT id, sticker_code, temp_pass, buyer_name, buyer_cbu, buyer_phone, status, created_at FROM stickers WHERE seller_id=%s ORDER BY created_at DESC", (uid,))
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
    
    # Obtener CBU actual del Admin para mostrarlo en el formulario
    cur.execute("SELECT cbu_alias FROM users WHERE sticker_id=%s", ('ADMIN001',))
    admin_cbu = cur.fetchone()["cbu_alias"] if cur.rowcount > 0 else "No configurado"

    conn.close()
    return render_template("dashboard.html", user=u, admin_cbu=admin_cbu, cycles=active_cycles_display, active_cycle=active_cycle, cycle_level=cycle_level, is_graduated_cycle=is_graduated_cycle, participants=participants, pending=pending, pending_cbu=pending_cbu, pending_phone=pending_phone, confirmations=confirmations, my_sales=[{"sale":s,"num":len(my_sales_history)-i} for i,s in enumerate(my_sales_history)], income=[{"sale":s,"num":len(income_history)-i} for i,s in enumerate(income_history)])

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
            
            # 🔹 NUEVA LÓGICA: Asignar niveles 4->3->2->1 subiendo por la red de referidos
            parent_id = row_u["id"]
            for lvl in [4, 3, 2, 1]:
                cur.execute("SELECT parent_id FROM referral_tree WHERE child_id=%s", (parent_id,))
                up = cur.fetchone()
                if not up:
                    break  # Cadena terminada
                parent_id = up["parent_id"]
                
                cur.execute("SELECT sticker_id FROM users WHERE id=%s", (parent_id,))
                p_data = cur.fetchone()
                if p_data and p_data["sticker_id"] == "ADMIN001":
                    break  # El Admin no participa en ciclos
                    
                cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (parent_id, cycle_id, lvl))
                cur.execute("UPDATE users SET current_level=%s WHERE id=%s", (lvl, parent_id))
        else:
            cycle_id = cycle["id"]

        cur.execute("SELECT id FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status IN ('pending', 'sent') LIMIT 1", (row_u["id"], cycle_id))
        if cur.fetchone():
            flash("⏳ Esperá a que se confirme y envíen los datos del sticker actual.")
            conn.close()
            return redirect(url_for("dashboard", cycle_id=cycle_id))
            
        cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status='entregado'", (row_u["id"], cycle_id))
        completed = cur.fetchone()["cnt"]
        if completed >= 3:
            flash("🎓 Ciclo completado. ¡Felicitaciones!")
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
        flash("✅ Sticker creado.")
        return redirect(url_for("dashboard", cycle_id=cycle_id))
    except Exception as e:
        conn.rollback()
        print(f"[ERROR CREAR] {traceback.format_exc()}", flush=True)
        flash(f"❌ Error: {str(e)}")
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
        flash("📤 Marcado como enviado. Esperando confirmación de pago...")
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
                cur.execute("UPDATE stickers SET status='confirmed' WHERE id=%s", (sticker_id,))
                conn.commit()
                flash("✅ Pago confirmado. Ahora podés enviar las credenciales.")
            else:
                cur.execute("UPDATE stickers SET status='pending' WHERE id=%s", (sticker_id,))
                conn.commit()
                flash("⚠️ Pago rechazado. Revisá con el comprador.")
        if s and s["cycle_id"]:
            return redirect(url_for("dashboard", cycle_id=s["cycle_id"]))
    finally:
        cur.close()
        conn.close()
    return redirect("/dashboard")

@app.route("/admin/cambiar_cbu", methods=["POST"])
def admin_cambiar_cbu():
    if "user_id" not in session:
        return redirect("/ingresar")
    conn = get_db()
    cur = get_cur(conn)
    try:
        cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],))
        row = cur.fetchone()
        if not row or row["sticker_id"] != "ADMIN001":
            flash("⛔ Acceso denegado. Solo ADMIN001 puede modificar el CBU.")
            conn.close()
            return redirect("/dashboard")
        nuevo_cbu = request.form.get("nuevo_cbu", "").strip()
        if not nuevo_cbu:
            flash("⚠️ El campo CBU no puede estar vacío.")
            conn.close()
            return redirect("/dashboard")
        cur.execute("UPDATE users SET cbu_alias=%s WHERE sticker_id='ADMIN001'", (nuevo_cbu,))
        conn.commit()
        flash("✅ CBU administrativo actualizado correctamente.")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error al guardar: {str(e)}")
    finally:
        conn.close()
    return redirect("/dashboard")

@app.route("/enviar_datos_email/<int:sticker_id>", methods=["POST"])
def enviar_datos_email(sticker_id):
    conn = get_db()
    cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,))
        s = cur.fetchone()
        if s and s["status"] == "confirmed":
            buyer_email = s["buyer_email"]
            temp_pass = s["temp_pass"]
            sticker_code = s["sticker_code"]
            buyer_name = s["buyer_name"]
            app_url = request.host_url.rstrip('/') + "/ingresar"

            try:
                url = "https://api.brevo.com/v3/smtp/email"
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json",
                    "api-key": os.environ.get("BREVO_API_KEY")
                }
                payload = {
                    "sender": {
                        "name": os.environ.get("BREVO_SENDER_NAME", "levelONE"),
                        "email": os.environ.get("BREVO_SENDER_EMAIL", "notificaciones@levelone.uno")
                    },
                    "to": [{"email": buyer_email, "name": buyer_name}],
                    "subject": f"🎉 ¡Tu acceso a levelONE está listo! | {sticker_code}",
                    "htmlContent": f"""
                    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 520px; margin: 0 auto; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 16px;">
                        <div style="text-align: center; padding: 16px; background: rgba(255,255,255,0.95); border-radius: 12px; margin-bottom: 16px;">
                            <h1 style="margin: 0; color: #667eea; font-size: 24px; font-weight: 700;">🌟 levelONE</h1>
                            <p style="margin: 4px 0 0 0; color: #666; font-size: 14px;">Plataforma de Stickers Digitales</p>
                        </div>
                        <div style="background: white; padding: 24px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1);">
                            <h2 style="color: #333; margin: 0 0 12px 0; font-size: 20px;">¡Bienvenido, {buyer_name}! 🎉</h2>
                            <p style="color: #555; margin: 8px 0; line-height: 1.5;">Tu sticker <strong>{sticker_code}</strong> ha sido activado.</p>
                            <div style="background: #f8f9fa; border: 2px dashed #667eea; padding: 20px; border-radius: 12px; text-align: center; margin: 20px 0;">
                                <img src="https://levelone.uno/static/sticker.jpg" alt="Sticker levelONE" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                                <p style="margin: 16px 0 0 0; color: #444; font-size: 14px; line-height: 1.6;">
                                    🎫 <strong>Este es el sticker que compraste.</strong><br>
                                    El que te habilita para ingresar a la plataforma y poder generar tus ventas.
                                </p>
                            </div>
                            <div style="background: #f8f9ff; border-left: 4px solid #667eea; padding: 16px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                                <p style="margin: 0 0 8px 0; color: #333; font-weight: 600;">🔐 Tus datos de acceso (permanentes):</p>
                                <p style="margin: 4px 0; color: #555;"><strong>Sticker ID:</strong> <code style="background: #eef2ff; padding: 2px 8px; border-radius: 4px; color: #667eea;">{sticker_code}</code></p>
                                <p style="margin: 4px 0 0 0; color: #555;"><strong>Contraseña:</strong> <code style="background: #eef2ff; padding: 2px 8px; border-radius: 4px; color: #667eea;">{temp_pass}</code></p>
                            </div>
                            <div style="text-align: center; margin: 24px 0 16px 0;">
                                <a href="{app_url}" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; padding: 12px 32px; border-radius: 8px; display: inline-block; font-weight: 600; font-size: 16px; box-shadow: 0 4px 14px rgba(102, 126, 234, 0.4);">🚀 Ingresar a mi cuenta</a>
                            </div>
                            <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 12px; border-radius: 8px; margin-top: 20px;">
                                <p style="margin: 0 0 8px 0; color: #856404; font-size: 13px; line-height: 1.4;">
                                    ⏳ <strong>Plazo de actividad:</strong> Tenés 7 días desde la activación para completar tus 3 ventas. Pasado ese plazo, el acceso se cancela automáticamente y no se realizan reintegros.
                                </p>
                                <p style="margin: 0; color: #856404; font-size: 13px;">
                                    📖 <a href="https://levelone.uno/terminos" style="color: #856404; text-decoration: underline;">Leer Términos y Condiciones completos</a>
                                </p>
                            </div>
                        </div>
                        <div style="text-align: center; padding: 16px; color: rgba(255,255,255,0.9); font-size: 12px;">
                            <p style="margin: 0;">© 2026 levelONE. Todos los derechos reservados.</p>
                            <p style="margin: 4px 0 0 0; opacity: 0.8;">Si no solicitaste este acceso, contactá a quien te vendió el sticker.</p>
                        </div>
                    </div>
                    """
                }
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                response.raise_for_status()
                print(f"[BREVO] ✅ Email enviado a {buyer_email}. Status: {response.status_code}", flush=True)
            except Exception as e:
                print(f"[BREVO] ❌ Error: {e}", flush=True)
                flash("⚠️ El email no pudo enviarse, pero el acceso está activado.")

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
                flash("🎉 ¡Ciclo completado! Subiste de nivel.")
            else:
                flash("✅ Credenciales enviadas. Sticker entregado.")
                
            conn.commit()
        else:
            flash("⚠️ Estado incorrecto. El pago debe estar confirmado primero.")
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
