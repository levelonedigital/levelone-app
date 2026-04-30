import os
import uuid
import traceback
import requests
from datetime import datetime, timedelta
from collections import deque

from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, flash, jsonify
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
        buyer_email TEXT, buyer_cbu TEXT, buyer_cbu_titular TEXT, buyer_cbu_dni TEXT, buyer_cbu_entidad TEXT,
        step INTEGER DEFAULT 1, confirmation_token TEXT, temp_pass TEXT, status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cur.execute("SELECT id FROM users WHERE sticker_id=%s", ('ADMIN001',))
    if not cur.fetchone():
        cur.execute('''INSERT INTO users (sticker_id, full_name, email, phone, cbu_alias, password_hash, current_level, is_level1, role, terms_accepted_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                     ('ADMIN001', 'Administrador', 'admin@levelone.com', '+5491100000000', 'admin.levelone.mp',
                      generate_password_hash("Admin2026!", method='pbkdf2:sha256'), 1, True, 'level1', datetime.now()))

    conn.commit()
    print("✅ DB inicializada (Tablas + Admin listos).", flush=True)
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
            except: pass
            conn.close()
            return redirect(url_for("dashboard"))
        flash("Sticker o contraseña incorrectos.")
        conn.close()
    return render_template("login.html")

@app.route("/terminos")
def terminos():
    terminos_html = """
    <!DOCTYPE html>
    <html lang="es">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Bases y Condiciones - LevelONE</title>
    <style>body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:#f4f7f6;color:#333;line-height:1.6;margin:0;padding:20px}.container{max-width:800px;margin:0 auto;background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.1)}h1{color:#4a5568;border-bottom:2px solid #e2e8f0;padding-bottom:10px}h2{color:#2d3748;margin-top:30px}p{margin-bottom:15px}ul{margin-bottom:15px;padding-left:20px}li{margin-bottom:8px}.alert{background:#fff3cd;color:#856404;padding:15px;border-radius:8px;border-left:4px solid #ffeeba;margin:20px 0}.btn-back{display:inline-block;background:#667eea;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;margin-top:20px;font-weight:600}.btn-back:hover{background:#5a67d8}footer{text-align:center;margin-top:40px;color:#718096;font-size:.9em}</style>
    </head><body><div class="container">
    <h1>📄 Bases y Condiciones de Uso</h1><p>Última actualización: Abril 2026. Bienvenido a LevelONE.</p>
    <h2>1. Activación y Acceso</h2><p>El acceso se otorga mediante la compra de un Sticker levelONE.</p>
    <h2>2. Plazo de Actividad</h2><p>Dispone de 7 días para completar sus 3 ventas iniciales.</p>
    <div class="alert">⚠️ Si no completa el proceso en el plazo, el acceso podrá cancelarse sin reintegro.</div>
    <h2>3. Naturaleza del Sistema</h2><p>LevelONE es educativa/comercial. No promete ganancias automáticas.</p>
    <ul><li>Resultados dependen de su actividad.</li><li>La participación en referidos es opcional.</li></ul>
    <h2>4. Comunidad y Beneficios</h2><ul><li>Comunidad WhatsApp</li><li>Capacitaciones</li><li>Descuentos</li><li>Generación de ingresos</li></ul>
    <h2>5. Cancelación y Reintegros</h2><p>No se realizan reintegros tras activación.</p>
    <p style="text-align:center;margin-top:40px"><a href="/" class="btn-back">Volver</a></p>
    </div><footer>© 2026 LevelONE.</footer></body></html>
    """
    return render_template_string(terminos_html)

@app.route("/accept_terms")
def accept_terms():
    if "user_id" not in session: return redirect(url_for("login"))
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
    row_u = cur.fetchone(); conn.close()
    try:
        if not row_u or row_u.get("terms_accepted_at") is not None: return redirect(url_for("dashboard"))
    except: return redirect(url_for("dashboard"))
    return render_template("login.html", show_terms_modal=True, user=row_u)

@app.route("/api/accept_terms", methods=["POST"])
def api_accept_terms():
    if "user_id" not in session: return jsonify({"success": False, "error": "No autenticado"}), 401
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("UPDATE users SET terms_accepted_at=%s, terms_version=%s WHERE id=%s",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "v1.0", session["user_id"]))
        conn.commit(); return jsonify({"success": True})
    except Exception as e: conn.rollback(); return jsonify({"success": False, "error": str(e)}), 500
    finally: conn.close()

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session: return redirect(url_for("login"))
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
    row_u = cur.fetchone()
    if not row_u: session.clear(); conn.close(); return redirect(url_for("login"))
    try:
        if row_u.get("terms_accepted_at") is None: conn.close(); return redirect(url_for("accept_terms"))
    except: pass
    
    u = dict(row_u); uid = u.get("id"); role = u.get("role", "seller"); sticker = u.get("sticker_id", ""); level = u.get("current_level", 5)

    # 🔍 Buscar EXCLUSIVAMENTE el ciclo donde el usuario es Nivel 5
    cur.execute("""
        SELECT c.* FROM cycles c
        JOIN cycle_levels cl ON c.id = cl.cycle_id
        WHERE c.l5_user_id = %s AND cl.user_id = %s AND cl.level = 5
        ORDER BY c.id DESC
    """, (uid, uid))
    active_cycle = cur.fetchone()
    
    cycle_id = request.args.get("cycle_id", type=int)
    if not cycle_id and active_cycle: cycle_id = active_cycle["id"]
    elif not cycle_id and active_cycle: cycle_id = active_cycle["id"]
    
    cycle_level = level; is_graduated_cycle = False
    if cycle_id:
        cur.execute("SELECT level, is_graduated FROM cycle_levels WHERE user_id=%s AND cycle_id=%s", (uid, cycle_id))
        cl = cur.fetchone()
        if cl: cycle_level = cl["level"]; is_graduated_cycle = bool(cl["is_graduated"])
    u["current_level"] = cycle_level

    pending = None
    if cycle_id:
        cur.execute("SELECT * FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status IN ('pending', 'sent', 'confirmed') ORDER BY created_at DESC LIMIT 1", (uid, cycle_id))
        pending_row = cur.fetchone()
        pending = dict(pending_row) if pending_row else None

    pending_cbu = "No configurado"; pending_phone = "No configurado"
    if pending:
        step = pending["step"]
        cid = pending["cycle_id"] or (active_cycle["id"] if active_cycle else None)
        # Usar step (1,2,3) para determinar CBU
        if step == 1:
            cur.execute("SELECT cbu_alias FROM users WHERE sticker_id=%s", ('ADMIN001',)); row = cur.fetchone()
        elif step == 2:
            cur.execute("SELECT u.cbu_alias FROM cycle_levels cl JOIN users u ON cl.user_id = u.id WHERE cl.cycle_id=%s AND cl.level=1 LIMIT 1", (cid,)); row = cur.fetchone()
        elif step == 3:
            cur.execute("SELECT cbu_alias FROM users WHERE id=%s", (uid,)); row = cur.fetchone()
        else: row = None
        pending_cbu = row["cbu_alias"] if row else "No configurado"
        pending_phone = pending["buyer_phone"] or "No configurado"

    confirmations = []
    if sticker == 'ADMIN001':
        cur.execute("SELECT id, sticker_code, buyer_name, buyer_cbu, buyer_cbu_titular, buyer_cbu_dni, buyer_cbu_entidad, buyer_phone, cycle_id, step, status FROM stickers WHERE step=1 AND status='sent' ORDER BY created_at DESC")
        confirmations = cur.fetchall()
    elif level != 5 and role != "graduated":
        cur.execute('''SELECT s.id, s.sticker_code, s.buyer_name, s.buyer_cbu, s.buyer_cbu_titular, s.buyer_cbu_dni, s.buyer_cbu_entidad, s.buyer_phone, s.cycle_id, s.step, s.status 
                      FROM stickers s JOIN cycle_levels cl ON s.cycle_id = cl.cycle_id
                      WHERE s.step=2 AND s.status='sent' AND cl.level=1 AND cl.user_id=%s''', (uid,))
        confirmations = cur.fetchall()

    participants = []
    if level != 5 and sticker != "ADMIN001" and role != "graduated":
        try:
            desc_ids = []; queue, visited = deque([uid]), set([uid])
            while queue:
                curr = queue.popleft()
                cur.execute("SELECT child_id FROM referral_tree WHERE parent_id=%s", (curr,))
                for r in cur.fetchall():
                    cid_r = r["child_id"]
                    if cid_r and cid_r not in visited: visited.add(cid_r); desc_ids.append(cid_r); queue.append(cid_r)
            all_ids = [uid] + desc_ids; ph = ','.join(['%s'] * len(all_ids))
            cur.execute(f"SELECT id, sticker_id, full_name, phone, current_level FROM users WHERE id IN ({ph})", all_ids)
            participants = [dict(p) for p in cur.fetchall()]
            sales_map = {}
            cur.execute(f"SELECT seller_id, COUNT(*) as cnt FROM stickers WHERE seller_id IN ({ph}) AND status='entregado' GROUP BY seller_id", all_ids)
            for r in cur.fetchall(): sales_map[r["seller_id"]] = r["cnt"]
            for p in participants:
                p["sales_done"] = 3 if (sales_map.get(p["id"], 0) == 0 and p["current_level"] < 5) else sales_map.get(p["id"], 0)
                if active_cycle:
                    cur.execute("SELECT level FROM cycle_levels WHERE user_id=%s AND cycle_id=%s", (p["id"], cycle_id)); cl = cur.fetchone()
                    p["level"] = cl["level"] if cl else p["current_level"]
                else: p["level"] = p["current_level"]
        except: pass

    my_sales_history = []; income_history = []
    # Historial GLOBAL por usuario
    cur.execute("SELECT id, sticker_code, temp_pass, buyer_name, buyer_cbu, buyer_cbu_titular, buyer_cbu_dni, buyer_cbu_entidad, buyer_phone, status, created_at FROM stickers WHERE seller_id=%s ORDER BY created_at DESC", (uid,))
    my_sales_history = [dict(s) for s in cur.fetchall()]
    
    if sticker == "ADMIN001":
        cur.execute("SELECT * FROM stickers WHERE step=1 AND status IN ('confirmed', 'entregado') ORDER BY created_at DESC"); income_history = [dict(r) for r in cur.fetchall()]
    elif level == 5:
        cur.execute("SELECT * FROM stickers WHERE seller_id=%s AND status='entregado' ORDER BY created_at DESC", (uid,)); income_history = [dict(r) for r in cur.fetchall()]
    else:
        cur.execute("SELECT cycle_id FROM cycle_levels WHERE user_id=%s AND level=1", (uid,)); l1_cycles = [r["cycle_id"] for r in cur.fetchall()]
        if l1_cycles:
            ph = ','.join(['%s'] * len(l1_cycles))
            cur.execute(f"SELECT * FROM stickers WHERE step=2 AND status IN ('confirmed', 'entregado') AND cycle_id IN ({ph}) ORDER BY created_at DESC", l1_cycles)
            income_history = [dict(r) for r in cur.fetchall()]

    try:
        cycles_list = [active_cycle] if active_cycle else []
        active_cycles_display = [c for c in cycles_list if not (c.get("completed_at") and (datetime.now() - datetime.strptime(c["completed_at"], "%Y-%m-%d %H:%M:%S")).days > 30)]
    except: active_cycles_display = [active_cycle] if active_cycle else []
    
    cur.execute("SELECT cbu_alias FROM users WHERE sticker_id=%s", ('ADMIN001',))
    admin_cbu = cur.fetchone()["cbu_alias"] if cur.rowcount > 0 else "No configurado"
    
    cur.execute("SELECT mp_enabled, mp_payment_link FROM users WHERE sticker_id='ADMIN001'")
    mp_cfg = cur.fetchone()
    mp_enabled = mp_cfg["mp_enabled"] if mp_cfg else False
    mp_link = mp_cfg["mp_payment_link"] if mp_cfg else ""
    
    cur.execute("""SELECT s.created_at, s.sticker_code, s.buyer_name, s.buyer_cbu, s.buyer_cbu_titular, s.buyer_cbu_dni, s.buyer_cbu_entidad, s.status
        FROM stickers s JOIN cycle_levels cl ON s.cycle_id = cl.cycle_id
        WHERE cl.user_id = %s AND cl.level = 1 AND s.step = 2 AND s.status IN ('confirmed', 'entregado')
        ORDER BY s.created_at DESC LIMIT 20""", (session["user_id"],))
    l1_payments = cur.fetchall()
    
    conn.close()
    return render_template("dashboard.html", user=u, admin_cbu=admin_cbu, cycles=active_cycles_display, active_cycle=active_cycle, cycle_level=cycle_level, is_graduated_cycle=is_graduated_cycle, participants=participants, pending=pending, pending_cbu=pending_cbu, pending_phone=pending_phone, confirmations=confirmations, my_sales=[{"sale":s,"num":len(my_sales_history)-i} for i,s in enumerate(my_sales_history)], income=[{"sale":s,"num":len(income_history)-i} for i,s in enumerate(income_history)], l1_payments=l1_payments, mp_enabled=mp_enabled, mp_link=mp_link)

@app.route("/crear_sticker", methods=["POST"])
def crear_sticker():
    if "user_id" not in session: return redirect("/login")
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],))
        row_u = cur.fetchone()
        
        # 🔍 NUEVO: Validar que tenga AL MENOS UN ciclo activo donde es Nivel 5 y tenga <3 ventas entregadas
        cur.execute("""
            SELECT c.id FROM cycles c
            JOIN cycle_levels cl ON c.id = cl.cycle_id
            LEFT JOIN stickers s ON c.id = s.cycle_id AND s.seller_id = %s AND s.status = 'entregado'
            WHERE c.l5_user_id = %s AND cl.level = 5 AND c.status = 'active'
            GROUP BY c.id
            HAVING COUNT(s.id) < 3
            LIMIT 1
        """, (row_u["id"], row_u["id"]))
        puede_vender = cur.fetchone()
        
        if not row_u or not puede_vender:
            flash("Solo Nivel 5 puede crear stickers.")
            conn.close()
            return redirect("/dashboard")
            
        name = request.form.get("name","").strip(); phone = request.form.get("phone","").strip()
        email = request.form.get("email","").strip(); cbu = request.form.get("cbu","").strip()
        if not all([name, phone, email, cbu]):
            flash("Todos los campos son obligatorios."); conn.close(); return redirect("/dashboard")

        cur.execute("INSERT INTO cycles (l5_user_id) VALUES (%s) RETURNING id", (row_u["id"],))
        cycle_id = cur.fetchone()["id"]

        cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (row_u["id"], cycle_id, 5))
        cur.execute("UPDATE users SET current_level=5 WHERE id=%s", (row_u["id"],))

        # Asignar niveles 4,3,2,1. Registrar ADMIN en cycle_levels pero no tocar su current_level global
        current_parent = row_u["id"]
        for lvl in [4, 3, 2, 1]:
            cur.execute("SELECT parent_id FROM referral_tree WHERE child_id=%s", (current_parent,))
            up = cur.fetchone()
            if not up: break
            parent_id = up["parent_id"]
            cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (parent_id, cycle_id, lvl))
            cur.execute("SELECT sticker_id FROM users WHERE id=%s", (parent_id,))
            p_data = cur.fetchone()
            if p_data and p_data["sticker_id"] == "ADMIN001": break
            cur.execute("UPDATE users SET current_level=%s WHERE id=%s", (lvl, parent_id))
            current_parent = parent_id

        cur.execute("SELECT id FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status IN ('pending', 'sent') LIMIT 1", (row_u["id"], cycle_id))
        if cur.fetchone():
            flash("⏳ Esperá a que se confirme y envíen los datos del sticker actual."); conn.close(); return redirect(url_for("dashboard", cycle_id=cycle_id))
            
        # Lógica original de step (1, 2, 3) basado en ventas entregadas
        cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND status='entregado'", (row_u["id"],))
        completed = cur.fetchone()["cnt"]
        step = completed + 1

        code = "STK-"+str(uuid.uuid4())[:6].upper(); temp_pass = "Temp-"+str(uuid.uuid4())[:8]
        cur.execute('''INSERT INTO stickers (sticker_code,seller_id,cycle_id,buyer_name,buyer_phone,buyer_email,buyer_cbu,buyer_cbu_titular,buyer_cbu_dni,buyer_cbu_entidad,step,confirmation_token,temp_pass,status) 
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', 
                    (code,row_u["id"],cycle_id,name,phone,email,cbu, request.form.get("cbu_titular","").strip(), request.form.get("cbu_dni","").strip(), request.form.get("cbu_entidad","").strip(), step,str(uuid.uuid4())[:12],temp_pass,'pending'))
        cur.execute('''INSERT INTO users (sticker_id,full_name,phone,email,cbu_alias,password_hash,role) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id''', 
                    (code,name,phone,email,cbu,generate_password_hash(temp_pass,method='pbkdf2:sha256'),'inactive'))
        new_id = cur.fetchone()["id"]
        if new_id: cur.execute("INSERT INTO referral_tree (parent_id, child_id) VALUES (%s,%s) ON CONFLICT (parent_id,child_id) DO NOTHING", (row_u["id"], new_id))
        conn.commit(); flash("✅ Sticker creado."); return redirect(url_for("dashboard", cycle_id=cycle_id))
    except Exception as e:
        conn.rollback(); print(f"[ERROR CREAR] {traceback.format_exc()}", flush=True); flash(f"❌ Error: {str(e)}")
    finally: conn.close()
    return redirect("/dashboard")

@app.route("/marcar_enviado/<int:sticker_id>", methods=["POST"])
def marcar_enviado(sticker_id):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,))
    s = cur.fetchone()
    if s and s["status"] == "pending":
        cur.execute("UPDATE stickers SET status='sent' WHERE id=%s", (sticker_id,))
        conn.commit(); flash("📤 Marcado como enviado. Esperando confirmación de pago...")
    conn.close(); return redirect("/dashboard")

@app.route("/resolver_confirmacion/<int:sticker_id>/<action>", methods=["POST"])
def resolver_confirmacion(sticker_id, action):
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,))
        s = cur.fetchone()
        if s and s["status"] == "sent":
            if action == "confirm": cur.execute("UPDATE stickers SET status='confirmed' WHERE id=%s", (sticker_id,)); conn.commit(); flash("✅ Pago confirmado. Ahora podés enviar las credenciales.")
            else: cur.execute("UPDATE stickers SET status='pending' WHERE id=%s", (sticker_id,)); conn.commit(); flash("⚠️ Pago rechazado. Revisá con el comprador.")
        if s and s["cycle_id"]: return redirect(url_for("dashboard", cycle_id=s["cycle_id"]))
    finally: cur.close(); conn.close()
    return redirect("/dashboard")

@app.route("/admin/cambiar_cbu", methods=["POST"])
def admin_cambiar_cbu():
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],)); row = cur.fetchone()
        if not row or row["sticker_id"] != "ADMIN001": flash("⛔ Acceso denegado."); conn.close(); return redirect("/dashboard")
        nuevo_cbu = request.form.get("nuevo_cbu", "").strip()
        if not nuevo_cbu: flash("⚠️ El campo CBU no puede estar vacío."); conn.close(); return redirect("/dashboard")
        cur.execute("UPDATE users SET cbu_alias=%s WHERE sticker_id='ADMIN001'", (nuevo_cbu,)); conn.commit(); flash("✅ CBU administrativo actualizado.")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {str(e)}")
    finally: conn.close(); return redirect("/dashboard")

@app.route("/admin/mp_config", methods=["POST"])
def admin_mp_config():
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],)); row = cur.fetchone()
        if not row or row["sticker_id"] != "ADMIN001": return redirect("/dashboard")
        enabled = request.form.get("mp_enabled") == "on"; link = request.form.get("mp_link", "").strip()
        cur.execute("UPDATE users SET mp_enabled=%s, mp_payment_link=%s WHERE sticker_id='ADMIN001'", (enabled, link)); conn.commit(); flash("✅ Configuración MP actualizada.")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {str(e)}")
    finally: conn.close(); return redirect("/dashboard")

@app.route("/enviar_datos_email/<int:sticker_id>", methods=["POST"])
def enviar_datos_email(sticker_id):
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,))
        s = cur.fetchone()
        if s and s["status"] == "confirmed":
            buyer_email = s["buyer_email"]; temp_pass = s["temp_pass"]; sticker_code = s["sticker_code"]; buyer_name = s["buyer_name"]
            app_terms_url = request.host_url.rstrip('/') + "/terminos"; app_url = request.host_url.rstrip('/') + "/ingresar"
            try:
                url = "https://api.brevo.com/v3/smtp/email"
                headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
                payload = {"sender": {"name": os.environ.get("BREVO_SENDER_NAME", "levelONE"), "email": os.environ.get("BREVO_SENDER_EMAIL", "notificaciones@levelone.uno")}, "to": [{"email": buyer_email, "name": buyer_name}], "subject": f"🎉 ¡BIENVENIDO/A A LEVELONE! | {sticker_code}", "htmlContent": f"<h1>Bienvenido</h1><p>Usuario: {sticker_code} | Pass: {temp_pass} | Link: <a href='{app_url}'>{app_url}</a></p>"}
                response = requests.post(url, json=payload, headers=headers, timeout=10); response.raise_for_status()
                print(f"[BREVO] ✅ Email enviado a {buyer_email}. Status: {response.status_code}", flush=True)
            except Exception as e: print(f"[BREVO] ❌ Error: {e}", flush=True); flash("⚠️ El email no pudo enviarse, pero el acceso está activado.")

            cur.execute("UPDATE stickers SET status='entregado' WHERE id=%s", (sticker_id,))
            cid, sid = s["cycle_id"], s["seller_id"]
            
            # Cierre específico POR CICLO
            cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE cycle_id=%s AND seller_id=%s AND status='entregado'", (cid, sid))
            entregados = cur.fetchone()["cnt"]
            
            if entregados == 3:
                cur.execute("UPDATE cycle_levels SET is_graduated = TRUE WHERE cycle_id = %s AND level = 1", (cid,))
                cur.execute("UPDATE cycle_levels SET level = level - 1 WHERE cycle_id = %s AND level > 1", (cid,))
                cur.execute("SELECT user_id, level FROM cycle_levels WHERE cycle_id = %s", (cid,))
                for row in cur.fetchall(): cur.execute("UPDATE users SET current_level = %s WHERE id = %s", (row["level"], row["user_id"]))
                cur.execute("UPDATE cycles SET status='completed', completed_at=%s WHERE id=%s", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cid))
                flash("🎉 ¡Ciclo completado! L1 graduado. Demás bajaron de nivel.")
            else: flash("✅ Credenciales enviadas. Sticker entregado.")
            conn.commit()
        else: flash("⚠️ Estado incorrecto. El pago debe estar confirmado primero.")
    finally: cur.close(); conn.close()
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear(); return redirect("/ingresar")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
