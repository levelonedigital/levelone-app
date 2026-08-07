import os
import uuid
import traceback
import requests
import secrets
import re
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
    
    cur.execute('''CREATE TABLE IF NOT EXISTS courses (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        image_url TEXT,
        start_date DATE,
        price DECIMAL(10,2),
        discount_pct INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
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
def index(): 
    """Muestra la Landing Page pública con cursos activos"""
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT id, title, description, image_url, start_date, price, discount_pct FROM courses WHERE status='active' ORDER BY start_date ASC")
    rows = cur.fetchall(); conn.close()
    
    cursos = []
    for r in rows:
        cursos.append({
            'title': r['title'],
            'description': r['description'] or '',
            'image_url': r['image_url'] or '',
            'start_date': r['start_date'].strftime('%d/%m/%Y') if r['start_date'] else '',
            'price': float(r['price']) if r['price'] else 0,
            'discount_pct': int(r['discount_pct']) if r['discount_pct'] else 0
        })
    return render_template("index.html", cursos=cursos)

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
    cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND status='entregado'", (uid,))
    cnt = cur.fetchone()["cnt"]
    u["can_sell"] = (cnt < 3)

    cur.execute("""SELECT c.* FROM cycles c JOIN cycle_levels cl ON c.id = cl.cycle_id WHERE c.l5_user_id = %s AND cl.user_id = %s AND cl.level = 5 ORDER BY c.id DESC LIMIT 1""", (uid, uid))
    active_cycle = cur.fetchone()
    cycle_id = active_cycle["id"] if active_cycle else None
    
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
        step = pending["step"]; cid = pending["cycle_id"] or cycle_id
        if step == 1: cur.execute("SELECT cbu_alias FROM users WHERE sticker_id=%s", ('ADMIN001',)); row = cur.fetchone()
        elif step == 2: cur.execute("SELECT u.cbu_alias FROM cycle_levels cl JOIN users u ON cl.user_id = u.id WHERE cl.cycle_id=%s AND cl.level=1 LIMIT 1", (cid,)); row = cur.fetchone()
        elif step == 3: cur.execute("SELECT cbu_alias FROM users WHERE id=%s", (uid,)); row = cur.fetchone()
        else: row = None
        pending_cbu = row["cbu_alias"] if row else "No configurado"
        pending_phone = pending["buyer_phone"] or "No configurado"

    confirmations = []
    if sticker == 'ADMIN001':
        cur.execute("SELECT id, sticker_code, buyer_name, buyer_cbu, buyer_cbu_titular, buyer_cbu_dni, buyer_cbu_entidad, buyer_phone, cycle_id, step, status FROM stickers WHERE step=1 AND status='sent' ORDER BY created_at DESC")
        confirmations = cur.fetchall()
    elif level != 5 and role != "graduated":
        cur.execute('''SELECT s.id, s.sticker_code, s.buyer_name, s.buyer_cbu, s.buyer_cbu_titular, s.buyer_cbu_dni, s.buyer_cbu_entidad, s.buyer_phone, s.cycle_id, s.step, s.status FROM stickers s JOIN cycle_levels cl ON s.cycle_id = cl.cycle_id WHERE s.step=2 AND s.status='sent' AND cl.level=1 AND cl.user_id=%s''', (uid,))
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
    cur.execute("""SELECT s.created_at, s.sticker_code, s.buyer_name, s.buyer_cbu, s.buyer_cbu_titular, s.buyer_cbu_dni, s.buyer_cbu_entidad, s.status FROM stickers s JOIN cycle_levels cl ON s.cycle_id = cl.cycle_id WHERE cl.user_id = %s AND cl.level = 1 AND s.step = 2 AND s.status IN ('confirmed', 'entregado') ORDER BY s.created_at DESC LIMIT 20""", (session["user_id"],))
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
        cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND status='entregado'", (row_u["id"],))
        completed = cur.fetchone()["cnt"]
        if completed >= 3: flash("🎓 Ciclo completado. ¡Felicitaciones!"); conn.close(); return redirect("/dashboard")
        
        name = request.form.get("name","").strip()
        phone = request.form.get("phone","").strip()
        email = request.form.get("email","").strip()
        cbu = request.form.get("cbu","").strip()
        
        # 🟢 NUEVO: Capturar nombre personalizado para el sticker
        sticker_name = request.form.get("sticker_name", "").strip()
        
        if not all([name, phone, email, cbu]):
            flash("Todos los campos son obligatorios."); conn.close(); return redirect("/dashboard")
        
        # 🟢 VALIDACIÓN: Formato del nombre personalizado (solo letras, números y _)
        if sticker_name:
            if not re.match(r'^[a-zA-Z0-9_]+$', sticker_name):
                flash("❌ El nombre del sticker solo puede contener letras, números y guión bajo (_). Sin espacios ni símbolos."); conn.close(); return redirect("/dashboard")
            
            # 🟢 VALIDACIÓN: Unicidad global
            cur.execute("SELECT id FROM users WHERE sticker_id=%s", (sticker_name,))
            if cur.fetchone():
                flash(f"❌ El nombre '{sticker_name}' ya está en uso. Elegí otro."); conn.close(); return redirect("/dashboard")
            
            # Usar el nombre personalizado como sticker_id y sticker_code
            code = sticker_name
        else:
            # Fallback: generar código automático STK-XXXX si no se proporcionó nombre
            code = "STK-"+str(uuid.uuid4())[:6].upper()
        
        cur.execute("INSERT INTO cycles (l5_user_id) VALUES (%s) RETURNING id", (row_u["id"],)); cycle_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (row_u["id"], cycle_id, 5))
        cur.execute("UPDATE users SET current_level=5 WHERE id=%s", (row_u["id"],))
        current_parent = row_u["id"]
        for lvl in [4, 3, 2, 1]:
            cur.execute("SELECT parent_id FROM referral_tree WHERE child_id=%s", (current_parent,)); up = cur.fetchone()
            if not up: break
            parent_id = up["parent_id"]
            cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (parent_id, cycle_id, lvl))
            cur.execute("SELECT sticker_id FROM users WHERE id=%s", (parent_id,)); p_data = cur.fetchone()
            if p_data and p_data["sticker_id"] == "ADMIN001": break
            cur.execute("UPDATE users SET current_level=%s WHERE id=%s", (lvl, parent_id)); current_parent = parent_id
        cur.execute("SELECT id FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status IN ('pending', 'sent') LIMIT 1", (row_u["id"], cycle_id))
        if cur.fetchone(): flash("⏳ Esperá a que se confirme y envíen los datos del sticker actual."); conn.close(); return redirect(url_for("dashboard", cycle_id=cycle_id))
        step = completed + 1
        temp_pass = "Temp-"+str(uuid.uuid4())[:8]
        cur.execute('''INSERT INTO stickers (sticker_code,seller_id,cycle_id,buyer_name,buyer_phone,buyer_email,buyer_cbu,buyer_cbu_titular,buyer_cbu_dni,buyer_cbu_entidad,step,confirmation_token,temp_pass,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', (code,row_u["id"],cycle_id,name,phone,email,cbu, request.form.get("cbu_titular","").strip(), request.form.get("cbu_dni","").strip(), request.form.get("cbu_entidad","").strip(), step,str(uuid.uuid4())[:12],temp_pass,'pending'))
        cur.execute('''INSERT INTO users (sticker_id,full_name,phone,email,cbu_alias,password_hash,role) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (code,name,phone,email,cbu,generate_password_hash(temp_pass,method='pbkdf2:sha256'),'inactive'))
        new_id = cur.fetchone()["id"]
        if new_id: cur.execute("INSERT INTO referral_tree (parent_id, child_id) VALUES (%s,%s) ON CONFLICT (parent_id,child_id) DO NOTHING", (row_u["id"], new_id))
        conn.commit(); flash(f"✅ Sticker creado: {code}"); return redirect(url_for("dashboard", cycle_id=cycle_id))
    except Exception as e: conn.rollback(); print(f"[ERROR CREAR] {traceback.format_exc()}", flush=True); flash(f"❌ Error: {str(e)}")
    finally: conn.close()
    return redirect("/dashboard")

@app.route("/marcar_enviado/<int:sticker_id>", methods=["POST"])
def marcar_enviado(sticker_id):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,)); s = cur.fetchone()
    if s and s["status"] == "pending":
        # 🟢 NUEVO: Enviar email de confirmación al responsable correspondiente
        try:
            step = s["step"]; cid = s["cycle_id"]
            responsable = None
            
            # Determinar a quién enviar según el step
            if step == 1:
                cur.execute("SELECT sticker_id, full_name, email, password_hash FROM users WHERE sticker_id='ADMIN001'")
                responsable = cur.fetchone()
            elif step == 2:
                cur.execute("""
                    SELECT u.sticker_id, u.full_name, u.email, u.password_hash 
                    FROM cycle_levels cl 
                    JOIN users u ON cl.user_id = u.id 
                    WHERE cl.cycle_id=%s AND cl.level=1 LIMIT 1
                """, (cid,))
                responsable = cur.fetchone()
            elif step == 3:
                cur.execute("SELECT sticker_id, full_name, email, password_hash FROM users WHERE id=%s", (s["seller_id"],))
                responsable = cur.fetchone()
            
            if responsable and responsable["email"]:
                app_url = request.host_url.rstrip('/') + "/dashboard"
                # Extraer solo los primeros 15 caracteres del hash para mostrar (no es la contraseña real)
                pwd_display = responsable["password_hash"][:15] + "..." if responsable["password_hash"] else "No definida"
                
                url = "https://api.brevo.com/v3/smtp/email"
                headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
                payload = {
                    "sender": {"name": os.environ.get("BREVO_SENDER_NAME", "levelONE"), "email": os.environ.get("BREVO_SENDER_EMAIL", "notificaciones@levelone.uno")},
                    "to": [{"email": responsable["email"], "name": responsable["full_name"]}],
                    "subject": f"🔔 Confirmación de pago requerida | Sticker {s['sticker_code']}",
                    "htmlContent": f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Confirmación de pago - LevelONE</title>
<style>
  body {{ margin:0;padding:0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh; }}
  .container {{ max-width:520px;margin:20px auto;background:white;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.15);overflow:hidden; }}
  .header {{ text-align:center;padding:24px 20px 16px;background:rgba(255,255,255,0.95); }}
  .header h1 {{ margin:0;color:#667eea;font-size:24px;font-weight:700; }}
  .content {{ padding:0 24px 24px 24px; }}
  .credentials {{ background:#f8f9ff;border-left:4px solid #667eea;padding:16px;margin:24px 0;border-radius:0 8px 8px 0; }}
  .credentials code {{ background:#eef2ff;padding:4px 10px;border-radius:4px;color:#667eea;font-weight:600; }}
  .btn {{ display:inline-block;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;text-decoration:none;padding:14px 36px;border-radius:10px;font-weight:600;font-size:16px;box-shadow:0 4px 14px rgba(102,126,234,0.4); }}
  .footer {{ text-align:center;padding:20px;background:#f8f9fa;border-top:1px solid #e9ecef;color:#6c757d;font-size:12px; }}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🔔 Confirmación de pago</h1>
      <p style="margin:12px 0 0 0;color:#333;font-size:15px;">Hola <strong>{responsable['full_name']}</strong>, hay un pago pendiente de confirmar ✨</p>
    </div>
    <div class="content">
      <p style="color:#555;font-size:14px;">El sticker <strong>{s['sticker_code']}</strong> ({s['buyer_name']}) ha sido marcado como enviado. Por favor, confirmá que recibiste el pago para continuar con el proceso.</p>
      
      <div class="credentials">
        <p style="margin:0 0 12px 0;color:#333;font-weight:600;font-size:15px;">🔑 Tus credenciales de acceso</p>
        <p style="margin:8px 0;color:#555;font-size:14px;"><strong>Usuario:</strong> <code>{responsable['sticker_id']}</code></p>
        <p style="margin:8px 0;color:#555;font-size:14px;"><strong>Contraseña:</strong> <code>{pwd_display}</code> <small style="color:#718096">(la real está encriptada)</small></p>
        <p style="margin:12px 0 0 0;color:#555;font-size:14px;"><strong>Link de acceso:</strong> <a href="{app_url}" style="color:#667eea;text-decoration:none;font-weight:600;">{app_url}</a></p>
      </div>
      
      <div style="text-align:center;margin:32px 0 24px 0;">
        <a href="{app_url}" class="btn">Ir a Pagos por Confirmar</a>
      </div>
      
      <p style="color:#6c757d;font-size:13px;text-align:center;">
        💡 Una vez en el dashboard, buscá la sección "📥 Pagos por Confirmar" para gestionar este pago.
      </p>
    </div>
    <div class="footer">
      <p style="margin:0 0 6px 0;">© 2026 levelONE. Todos los derechos reservados.</p>
      <p style="margin:0;color:#999;">Si no solicitaste esta notificación, contactá a admin@levelone.com</p>
    </div>
  </div>
</body>
</html>
                    """
                }
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                response.raise_for_status()
                print(f"[BREVO] ✅ Email de confirmación enviado a {responsable['email']}. Status: {response.status_code}", flush=True)
        except Exception as e:
            print(f"[BREVO] ❌ Error enviando email de confirmación: {e}", flush=True)
            # No interrumpimos el flujo principal si falla el email
        
        # Lógica original: actualizar estado a 'sent'
        cur.execute("UPDATE stickers SET status='sent' WHERE id=%s", (sticker_id,))
        conn.commit()
        flash("📤 Marcado como enviado. Esperando confirmación de pago...")
    conn.close()
    return redirect("/dashboard")

@app.route("/resolver_confirmacion/<int:sticker_id>/<action>", methods=["POST"])
def resolver_confirmacion(sticker_id, action):
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,)); s = cur.fetchone()
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
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,)); s = cur.fetchone()
        if s and s["status"] == "confirmed":
            buyer_email = s["buyer_email"]; temp_pass = s["temp_pass"]; sticker_code = s["sticker_code"]; buyer_name = s["buyer_name"]
            app_terms_url = request.host_url.rstrip('/') + "/terminos"; app_url = request.host_url.rstrip('/') + "/ingresar"
            try:
                url = "https://api.brevo.com/v3/smtp/email"
                headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
                payload = {"sender": {"name": os.environ.get("BREVO_SENDER_NAME", "levelONE"), "email": os.environ.get("BREVO_SENDER_EMAIL", "notificaciones@levelone.uno")}, "to": [{"email": buyer_email, "name": buyer_name}], "subject": f"🎉 ¡BIENVENIDO/A A LEVELONE! | {sticker_code}", "htmlContent": f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Bienvenido a LevelONE</title><style>@media only screen and (max-width: 600px) {{ body {{ background-color: #1a1a2e !important; }} .container {{ width: 100% !important; border-radius: 0 !important; }} }}</style></head><body style="margin:0;padding:0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;"><div style="max-width:520px;margin:20px auto;background:white;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.15);overflow:hidden;"><div style="text-align:center;padding:24px 20px 16px;background:rgba(255,255,255,0.95);"><h1 style="margin:0;color:#667eea;font-size:24px;font-weight:700;">🎉 ¡BIENVENIDO/A A LEVELONE!</h1><p style="margin:12px 0 0 0;color:#333;font-size:15px;">Tu sticker <strong>{sticker_code}</strong> ha sido activado correctamente ✅</p><p style="margin:8px 0 0 0;color:#555;font-size:14px;">Ahora ya formás parte de la comunidad LevelONE.</p><p style="margin:12px 0 0 0;color:#667eea;font-weight:600;font-size:14px;">🌟 Tu plataforma para aprender y crecer</p></div><div style="padding:0 24px 24px 24px;"><div style="background:#f8f9fa;border:2px dashed #667eea;padding:20px;border-radius:12px;text-align:center;margin:20px 0;"><img src="https://levelone.uno/static/sticker.jpg" alt="Sticker levelONE" style="max-width:100%;height:auto;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.15);"><p style="margin:12px 0 0 0;color:#444;font-size:14px;font-weight:600;">🎟️ Tu Sticker LevelONE</p><p style="margin:4px 0 0 0;color:#666;font-size:13px;">Este es tu Sticker LevelONE</p></div><div style="margin:24px 0;"><p style="color:#333;font-weight:600;margin:0 0 12px 0;font-size:15px;">👉 Es tu ingreso a una comunidad con beneficios reales:</p><ul style="color:#555;font-size:14px;margin:0 0 12px 0;padding-left:20px;line-height:1.8;"><li>📲 Acceso a la comunidad privada de WhatsApp</li><li>🎓 Capacitaciones en ventas, marketing y ventas online</li><li>💸 Hasta 50% de descuento en cursos presenciales y virtuales</li><li>🚀 La posibilidad de participar en el sistema y generar ingresos</li></ul><p style="color:#555;font-size:14px;margin:0;">Tu sticker es la herramienta que te permite crecer, aprender y avanzar dentro de LevelONE.</p></div><div style="background:#f8f9ff;border-left:4px solid #667eea;padding:16px;margin:24px 0;border-radius:0 8px 8px 0;"><p style="margin:0 0 12px 0;color:#333;font-weight:600;font-size:15px;">🔐 Datos de acceso a la plataforma</p><p style="margin:8px 0;color:#555;font-size:14px;"><strong>Usuario:</strong> <code style="background:#eef2ff;padding:4px 10px;border-radius:4px;color:#667eea;font-weight:600;">{sticker_code}</code></p><p style="margin:8px 0;color:#555;font-size:14px;"><strong>Contraseña:</strong> <code style="background:#eef2ff;padding:4px 10px;border-radius:4px;color:#667eea;font-weight:600;">{temp_pass}</code></p><p style="margin:12px 0 0 0;color:#555;font-size:14px;"><strong>Link de acceso:</strong> <a href="{app_url}" style="color:#667eea;text-decoration:none;font-weight:600;">{app_url}</a></p></div><div style="background:#fff3cd;border:1px solid #ffeaa7;padding:16px;border-radius:8px;margin:24px 0;"><p style="margin:0 0 10px 0;color:#856404;font-size:14px;font-weight:600;">⏳ Plazo de Activación</p><p style="margin:0 0 8px 0;color:#856404;font-size:13px;line-height:1.5;">Tenés 7 días desde la activación de tu sticker para completar tus primeras 3 ventas iniciales dentro del sistema.</p><p style="margin:0 0 8px 0;color:#856404;font-size:13px;line-height:1.5;">⚠️ Si no completás este proceso dentro del plazo establecido, el acceso al sistema podrá cancelarse sin reintegro.</p><p style="margin:0;color:#856404;font-size:13px;line-height:1.5;">💡 Te recomendamos aprovechar desde el primer día la comunidad y las capacitaciones disponibles para avanzar más rápido.</p></div><div style="background:#e8f4fd;border-left:4px solid #0d6efd;padding:16px;margin:24px 0;border-radius:0 8px 8px 0;"><p style="margin:0 0 10px 0;color:#0b5ed7;font-weight:600;font-size:15px;">🤝 Comunidad LevelONE</p><p style="margin:0 0 8px 0;color:#333;font-size:13px;line-height:1.5;">Desde este momento también podés acceder a nuestra comunidad privada, donde vas a encontrar:</p><p style="margin:0;color:#555;font-size:13px;">acompañamiento • seguimiento • soporte • estrategias de venta • información importante para tu crecimiento</p></div><div style="background:#f8f9fa;border:1px solid #dee2e6;padding:16px;border-radius:8px;margin:24px 0;"><p style="margin:0 0 10px 0;color:#495057;font-weight:600;font-size:14px;">📜 Importante</p><p style="margin:0 0 6px 0;color:#6c757d;font-size:13px;line-height:1.5;">LevelONE no es un sistema de inversión ni promete ganancias automáticas.</p><p style="margin:0 0 6px 0;color:#6c757d;font-size:13px;line-height:1.5;">Los resultados dependen de tu actividad, compromiso y del acompañamiento de tu red.</p><p style="margin:0;color:#6c757d;font-size:13px;line-height:1.5;">Tu participación en el sistema es opcional: el sticker ya incluye beneficios reales desde el momento de la compra.</p></div><div style="text-align:center;margin:28px 0 20px 0;"><p style="margin:0 0 6px 0;color:#333;font-weight:600;font-size:14px;">📄 Términos y Condiciones</p><p style="margin:0 0 10px 0;color:#555;font-size:13px;">Al activar tu sticker aceptás nuestras Bases y Condiciones de uso de la plataforma.</p><p style="margin:0;font-size:13px;">👉 Podés consultarlas aquí: <a href="{app_terms_url}" style="color:#667eea;text-decoration:underline;font-weight:600;">Bases y Condiciones</a></p></div><div style="text-align:center;margin:32px 0 24px 0;"><p style="margin:0 0 10px 0;color:#333;font-weight:600;font-size:16px;">🚀 Tu próximo paso</p><p style="margin:0 0 20px 0;color:#555;font-size:14px;line-height:1.5;">Ingresá ahora a tu plataforma, activá tu red y comenzá a avanzar.<br>Tu crecimiento empieza hoy. Bienvenido a LevelONE.</p><a href="{app_url}" style="display:inline-block;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;text-decoration:none;padding:14px 36px;border-radius:10px;font-weight:600;font-size:16px;box-shadow:0 4px 14px rgba(102,126,234,0.4);">Ingresar a la plataforma</a></div></div><div style="text-align:center;padding:20px;background:#f8f9fa;border-top:1px solid #e9ecef;color:#6c757d;font-size:12px;"><p style="margin:0 0 6px 0;">© 2026 levelONE. Todos los derechos reservados.</p><p style="margin:0;color:#999;">Si no solicitaste este acceso, contactá a quien te vendió el sticker.</p></div></div></body></html>"""}
                response = requests.post(url, json=payload, headers=headers, timeout=10); response.raise_for_status()
                print(f"[BREVO] ✅ Email enviado a {buyer_email}. Status: {response.status_code}", flush=True)
            except Exception as e: print(f"[BREVO] ❌ Error: {e}", flush=True); flash("⚠️ El email no pudo enviarse, pero el acceso está activado.")
            cur.execute("UPDATE stickers SET status='entregado' WHERE id=%s", (sticker_id,)); cid, sid = s["cycle_id"], s["seller_id"]
            cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE cycle_id=%s AND seller_id=%s AND status='entregado'", (cid, sid)); entregados = cur.fetchone()["cnt"]
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

@app.route("/debug-rutas")
def debug_rutas():
    rutas = []
    for rule in app.url_map.iter_rules(): rutas.append(f"{sorted(rule.methods)} {rule.rule} → {rule.endpoint}")
    return "<pre>" + "<br>".join(sorted(rutas)) + "</pre>"

@app.route("/admin/cursos", methods=["GET", "POST"])
def admin_cursos():
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],))
    row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")
    
    if request.method == "POST":
        titulo = request.form.get("titulo", "").strip()
        desc = request.form.get("descripcion", "").strip()
        img = request.form.get("imagen", "").strip()
        fecha = request.form.get("fecha_inicio", "").strip() or None
        precio = request.form.get("precio", "").strip() or None
        descuento = request.form.get("descuento", "0").strip() or 0
        estado = request.form.get("estado", "active")
        if titulo:
            cur.execute('''INSERT INTO courses (title, description, image_url, start_date, price, discount_pct, status) VALUES (%s,%s,%s,%s,%s,%s,%s)''', (titulo, desc, img, fecha, precio, descuento, estado))
            conn.commit(); flash("✅ Curso agregado correctamente.")
            
    cur.execute("SELECT * FROM courses ORDER BY created_at DESC"); cursos = cur.fetchall(); conn.close()
    
    html = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Admin Cursos</title><style>body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;padding:40px}.card{background:#1a1a2e;padding:20px;border-radius:12px;margin-bottom:20px;border:1px solid #333}input,select,textarea{width:100%;padding:10px;margin:5px 0 15px;background:#0f0f1a;color:#fff;border:1px solid #444;border-radius:8px}button{background:#667eea;color:#fff;padding:10px 20px;border:none;border-radius:8px;cursor:pointer}table{width:100%;border-collapse:collapse;margin-top:20px}th,td{padding:12px;border-bottom:1px solid #333;text-align:left}.badge{padding:4px 8px;border-radius:4px;font-size:0.8rem}.active{background:#38a169}.inactive{background:#e53e3e}a{color:#667eea;text-decoration:none;margin-right:15px}.btn-toggle{padding:5px 10px;border:none;border-radius:4px;color:#fff;cursor:pointer;font-size:0.85rem}</style></head><body>
    <h2>📚 Gestión de Cursos</h2><a href="/dashboard">← Volver</a>
    <div class="card"><form method="POST"><h3>Agregar Curso</h3>
    <input name="titulo" placeholder="Título *" required><textarea name="descripcion" placeholder="Descripción" rows="2"></textarea>
    <input name="imagen" placeholder="URL de imagen (opcional)"><input name="fecha_inicio" type="date">
    <input name="precio" type="number" step="0.01" placeholder="Precio base"><input name="descuento" type="number" min="0" max="100" placeholder="Descuento %">
    <select name="estado"><option value="active">Activo</option><option value="inactive">Inactivo</option></select>
    <button type="submit">Guardar</button></form></div>
    <table><thead><tr><th>Título</th><th>Precio</th><th>Desc.</th><th>Inicio</th><th>Estado</th><th>Acción</th></tr></thead><tbody>"""
    
    for c in cursos:
        badge = f"<span class='badge {'active' if c['status']=='active' else 'inactive'}'>{c['status']}</span>"
        btn_color = "#e53e3e" if c['status']=='active' else "#38a169"
        btn_text = "Desactivar" if c['status']=='active' else "Activar"
        html += f"<tr><td>{c['title']}</td><td>${c['price'] or '-'}</td><td>{c['discount_pct']}%</td><td>{c['start_date'] or '-'}</td><td>{badge}</td><td><a href='/admin/cursos/toggle/{c['id']}' style='background:{btn_color};color:#fff;padding:5px 10px;border-radius:4px;text-decoration:none;font-size:0.85rem'>{btn_text}</a></td></tr>"
        
    html += "</tbody></table></body></html>"
    return render_template_string(html)

@app.route("/admin/cursos/toggle/<int:course_id>")
def toggle_curso(course_id):
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],))
    row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")
    cur.execute("UPDATE courses SET status = CASE WHEN status='active' THEN 'inactive' ELSE 'active' END WHERE id=%s", (course_id,))
    conn.commit(); conn.close()
    flash("✅ Estado del curso actualizado.")
    return redirect("/admin/cursos")

@app.route("/admin/reset_password/<int:user_id>", methods=["POST"])
def admin_reset_password(user_id):
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],))
    row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001":
        conn.close(); return redirect("/dashboard")
    
    cur.execute("SELECT sticker_id, full_name, email, password_hash FROM users WHERE id=%s", (user_id,))
    target = cur.fetchone()
    if not target:
        conn.close(); flash("❌ Usuario no encontrado."); return redirect(request.referrer or "/dashboard")
    
    new_pass = "Temp-" + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
    new_hash = generate_password_hash(new_pass, method='pbkdf2:sha256')
    
    cur.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_hash, user_id))
    conn.commit()
    
    try:
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
        app_url = request.host_url.rstrip('/') + "/ingresar"
        
        payload = {
            "sender": {"name": os.environ.get("BREVO_SENDER_NAME", "levelONE"), "email": os.environ.get("BREVO_SENDER_EMAIL", "notificaciones@levelone.uno")},
            "to": [{"email": target["email"], "name": target["full_name"]}],
            "subject": f"🔐 Tu contraseña fue actualizada | {target['sticker_id']}",
            "htmlContent": f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Contraseña actualizada - LevelONE</title>
<style>
  body {{ margin:0;padding:0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh; }}
  .container {{ max-width:520px;margin:20px auto;background:white;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.15);overflow:hidden; }}
  .header {{ text-align:center;padding:24px 20px 16px;background:rgba(255,255,255,0.95); }}
  .header h1 {{ margin:0;color:#667eea;font-size:24px;font-weight:700; }}
  .content {{ padding:0 24px 24px 24px; }}
  .credentials {{ background:#f8f9ff;border-left:4px solid #667eea;padding:16px;margin:24px 0;border-radius:0 8px 8px 0; }}
  .credentials code {{ background:#eef2ff;padding:4px 10px;border-radius:4px;color:#667eea;font-weight:600; }}
  .motivational {{ background:#e8f4fd;border-left:4px solid #0d6efd;padding:16px;margin:24px 0;border-radius:0 8px 8px 0; }}
  .btn {{ display:inline-block;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;text-decoration:none;padding:14px 36px;border-radius:10px;font-weight:600;font-size:16px;box-shadow:0 4px 14px rgba(102,126,234,0.4); }}
  .footer {{ text-align:center;padding:20px;background:#f8f9fa;border-top:1px solid #e9ecef;color:#6c757d;font-size:12px; }}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🔐 Contraseña actualizada</h1>
      <p style="margin:12px 0 0 0;color:#333;font-size:15px;">Hola <strong>{target['full_name']}</strong>, tu acceso fue actualizado ✨</p>
    </div>
    <div class="content">
      <p style="color:#555;font-size:14px;">Por seguridad, tu contraseña temporal ha sido restablecida por el equipo de administración.</p>
      
      <div class="credentials">
        <p style="margin:0 0 12px 0;color:#333;font-weight:600;font-size:15px;">🔑 Tus nuevas credenciales</p>
        <p style="margin:8px 0;color:#555;font-size:14px;"><strong>Usuario:</strong> <code>{target['sticker_id']}</code></p>
        <p style="margin:8px 0;color:#555;font-size:14px;"><strong>Contraseña:</strong> <code>{new_pass}</code></p>
        <p style="margin:12px 0 0 0;color:#555;font-size:14px;"><strong>Link de acceso:</strong> <a href="{app_url}" style="color:#667eea;text-decoration:none;font-weight:600;">{app_url}</a></p>
      </div>
      
      <div class="motivational">
        <p style="margin:0 0 10px 0;color:#0b5ed7;font-weight:600;font-size:15px;">💪 Frase del día</p>
        <p style="margin:0;color:#333;font-size:14px;">"Cada sticker que vendés te acerca más a tu meta. ¡Seguí creciendo y construyendo tu red!"</p>
      </div>
      
      <div style="text-align:center;margin:32px 0 24px 0;">
        <a href="{app_url}" class="btn">Ingresar a la plataforma</a>
      </div>
      
      <p style="color:#6c757d;font-size:13px;text-align:center;">
        ⚠️ Por seguridad, te recomendamos cambiar esta contraseña temporal desde tu perfil al ingresar.
      </p>
    </div>
    <div class="footer">
      <p style="margin:0 0 6px 0;">© 2026 levelONE. Todos los derechos reservados.</p>
      <p style="margin:0;color:#999;">Si no solicitaste este cambio, contactá a admin@levelone.com</p>
    </div>
  </div>
</body>
</html>
            """
        }
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"[BREVO] ✅ Email de reset enviado a {target['email']}. Status: {response.status_code}", flush=True)
    except Exception as e:
        print(f"[BREVO] ❌ Error enviando email de reset: {e}", flush=True)
        flash("⚠️ Contraseña actualizada, pero el email no pudo enviarse.")
    
    conn.close()
    flash(f"✅ Contraseña restablecida para {target['full_name']} ({target['sticker_id']}). Nueva clave: {new_pass}")
    return redirect(request.referrer or "/admin/red")

@app.route("/admin/edit_user/<int:user_id>", methods=["GET", "POST"])
def admin_edit_user(user_id):
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],))
    row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")

    cur.execute("SELECT sticker_id, full_name, phone, email, address, cbu_alias FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone()
    if not user: conn.close(); return redirect("/admin/red")

    if request.method == "POST":
        new_name = request.form.get("full_name", "").strip()
        new_phone = request.form.get("phone", "").strip()
        new_email = request.form.get("email", "").strip()
        new_address = request.form.get("address", "").strip()
        new_cbu = request.form.get("cbu_alias", "").strip()

        if not all([new_name, new_phone, new_email]):
            conn.close(); flash("❌ Nombre, teléfono y email son obligatorios."); return redirect("/admin/red")

        new_pass = "Temp-" + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        new_hash = generate_password_hash(new_pass, method='pbkdf2:sha256')

        cur.execute('''UPDATE users SET full_name=%s, phone=%s, email=%s, address=%s, cbu_alias=%s, password_hash=%s WHERE id=%s''',
                    (new_name, new_phone, new_email, new_address, new_cbu, new_hash, user_id))
        conn.commit()

        try:
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
            app_url = request.host_url.rstrip('/') + "/ingresar"
            
            payload = {
                "sender": {"name": os.environ.get("BREVO_SENDER_NAME", "levelONE"), "email": os.environ.get("BREVO_SENDER_EMAIL", "notificaciones@levelone.uno")},
                "to": [{"email": new_email, "name": new_name}],
                "subject": f"📝 Datos actualizados y nueva contraseña | {user['sticker_id']}",
                "htmlContent": f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Datos actualizados - LevelONE</title>
<style>body{{margin:0;padding:0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;}}.container{{max-width:520px;margin:20px auto;background:white;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,0.15);overflow:hidden;}}.header{{text-align:center;padding:24px 20px 16px;background:rgba(255,255,255,0.95);}}.header h1{{margin:0;color:#667eea;font-size:24px;font-weight:700;}}.content{{padding:0 24px 24px 24px;}}.credentials{{background:#f8f9ff;border-left:4px solid #667eea;padding:16px;margin:24px 0;border-radius:0 8px 8px 0;}}.credentials code{{background:#eef2ff;padding:4px 10px;border-radius:4px;color:#667eea;font-weight:600;}}.motivational{{background:#e8f4fd;border-left:4px solid #0d6efd;padding:16px;margin:24px 0;border-radius:0 8px 8px 0;}}.btn{{display:inline-block;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;text-decoration:none;padding:14px 36px;border-radius:10px;font-weight:600;font-size:16px;box-shadow:0 4px 14px rgba(102,126,234,0.4);}}.footer{{text-align:center;padding:20px;background:#f8f9fa;border-top:1px solid #e9ecef;color:#6c757d;font-size:12px;}}</style></head>
<body><div class="container"><div class="header"><h1>📝 Datos actualizados</h1><p style="margin:12px 0 0 0;color:#333;font-size:15px;">Hola <strong>{new_name}</strong>, tu perfil fue actualizado ✨</p></div>
<div class="content"><p style="color:#555;font-size:14px;">Tus datos de contacto han sido modificados por administración. Tu acceso sigue vinculado al sticker <strong>{user['sticker_id']}</strong>.</p>
<div class="credentials"><p style="margin:0 0 12px 0;color:#333;font-weight:600;font-size:15px;">🔑 Nuevas credenciales</p>
<p style="margin:8px 0;color:#555;font-size:14px;"><strong>Usuario:</strong> <code>{user['sticker_id']}</code></p>
<p style="margin:8px 0;color:#555;font-size:14px;"><strong>Contraseña:</strong> <code>{new_pass}</code></p>
<p style="margin:12px 0 0 0;color:#555;font-size:14px;"><strong>Link de acceso:</strong> <a href="{app_url}" style="color:#667eea;text-decoration:none;font-weight:600;">{app_url}</a></p></div>
<div class="motivational"><p style="margin:0 0 10px 0;color:#0b5ed7;font-weight:600;font-size:15px;">💪 Frase del día</p><p style="margin:0;color:#333;font-size:14px;">"Tu crecimiento no tiene límites. Aprovechá esta nueva etapa y seguí construyendo tu red con todo."</p></div>
<div style="text-align:center;margin:32px 0 24px 0;"><a href="{app_url}" class="btn">Ingresar a la plataforma</a></div>
<p style="color:#6c757d;font-size:13px;text-align:center;">⚠️ Por seguridad, te recomendamos cambiar esta contraseña temporal al ingresar.</p></div>
<div class="footer"><p style="margin:0 0 6px 0;">© 2026 levelONE. Todos los derechos reservados.</p><p style="margin:0;color:#999;">Si no solicitaste este cambio, contactá a admin@levelone.com</p></div></div></body></html>"""
            }
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            print(f"[BREVO] ✅ Email de actualización enviado a {new_email}. Status: {response.status_code}", flush=True)
        except Exception as e:
            print(f"[BREVO] ❌ Error enviando email de actualización: {e}", flush=True)
            flash("⚠️ Datos actualizados, pero el email no pudo enviarse.")

        conn.close()
        flash(f"✅ Datos de {user['sticker_id']} actualizados. Nueva clave: {new_pass}")
        return redirect("/admin/red")

    conn.close()
    form_html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Gestionar Usuario</title><style>body{{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;padding:40px}}.card{{background:#1a1a2e;padding:25px;border-radius:12px;border:1px solid #333}}input{{width:100%;padding:10px;margin:5px 0 15px;background:#0f0f1a;color:#fff;border:1px solid #444;border-radius:8px}}button{{background:#667eea;color:#fff;padding:12px 24px;border:none;border-radius:8px;cursor:pointer}}a{{color:#667eea;text-decoration:none}}</style></head><body>
    <h2>✏️ Gestionar Usuario</h2><a href="/admin/red">← Volver</a>
    <div class="card"><form method="POST" onsubmit="return confirm('⚠️ ¿Estás seguro? Se actualizarán todos los datos de {user['sticker_id']} y se enviará una nueva contraseña al email nuevo.');">
        <h3>Editar datos de {user['sticker_id']}</h3>
        <label>Nombre completo</label><input name="full_name" value="{user['full_name'] or ''}" required>
        <label>Teléfono</label><input name="phone" value="{user['phone'] or ''}" required>
        <label>Email (se enviarán las credenciales aquí)</label><input name="email" value="{user['email'] or ''}" type="email" required>
        <label>Dirección</label><input name="address" value="{user['address'] or ''}">
        <label>CBU / Alias</label><input name="cbu_alias" value="{user['cbu_alias'] or ''}">
        <button type="submit">💾 Guardar cambios y generar nueva clave</button>
    </form></div></body></html>"""
    return render_template_string(form_html)

@app.route("/admin/red")
def admin_red():
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],))
    row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")

    query = request.args.get("q", "").strip()
    target = None
    ancestors = []
    descendants = []

    try:
        if query:
            cur.execute("SELECT id, sticker_id, full_name, phone, current_level, password_hash, role FROM users WHERE sticker_id ILIKE %s OR full_name ILIKE %s LIMIT 1", (f"%{query}%", f"%{query}%"))
            target = cur.fetchone()

            if target:
                tid = target["id"]
                
                try:
                    cur.execute("SELECT cycle_id, level FROM cycle_levels WHERE user_id=%s ORDER BY id DESC LIMIT 1", (tid,))
                    user_cycle = cur.fetchone()
                    
                    if user_cycle and user_cycle["cycle_id"]:
                        cycle_id = user_cycle["cycle_id"]
                        user_level_in_cycle = user_cycle["level"] or 5
                        
                        if user_level_in_cycle > 1:
                            for target_level in range(user_level_in_cycle - 1, 0, -1):
                                try:
                                    cur.execute("""
                                        SELECT u.id, u.sticker_id, u.full_name, u.phone, u.current_level 
                                        FROM cycle_levels cl 
                                        JOIN users u ON cl.user_id = u.id 
                                        WHERE cl.cycle_id = %s AND cl.level = %s
                                    """, (cycle_id, target_level))
                                    ancestor_data = cur.fetchone()
                                    if ancestor_data:
                                        ancestors.append(dict(ancestor_data))
                                except Exception as e:
                                    print(f"[DEBUG] Error buscando ascendiente nivel {target_level}: {e}", flush=True)
                                    continue
                except Exception as e:
                    print(f"[DEBUG] Error buscando ciclo del usuario: {e}", flush=True)
                
                try:
                    queue = [(tid, 1, target["sticker_id"])]
                    visited = set()
                    
                    while queue and len(descendants) < 50:
                        parent_id, depth, parent_stk = queue.pop(0)
                        if depth > 3 or parent_id in visited: continue
                        visited.add(parent_id)
                        
                        cur.execute("SELECT child_id FROM referral_tree WHERE parent_id=%s", (parent_id,))
                        for r in cur.fetchall():
                            child_id = r["child_id"]
                            if child_id and child_id not in visited:
                                cur.execute("SELECT id, sticker_id, full_name, phone, current_level, password_hash FROM users WHERE id=%s", (child_id,))
                                child_data = cur.fetchone()
                                if child_data:
                                    descendants.append({
                                        "nivel": depth,
                                        "padre_stk": parent_stk,
                                        "data": dict(child_data)
                                    })
                                    if depth < 3:
                                        queue.append((child_id, depth + 1, child_data["sticker_id"]))
                except Exception as e:
                    print(f"[DEBUG] Error buscando descendientes: {e}", flush=True)
    except Exception as e:
        print(f"[DEBUG] Error general en admin_red: {e}", flush=True)
        flash(f"⚠️ Error al cargar la red: {str(e)}")
    finally:
        conn.close()

    def user_buttons(user_id, user_name):
        return f"""
        <div style="display:flex;gap:8px;margin-top:8px;">
            <a href="/admin/edit_user/{user_id}" style="background:#38a169;color:#fff;padding:5px 10px;border-radius:4px;text-decoration:none;font-size:0.8rem;font-weight:600;">✏️ Gestionar</a>
            <a href="/admin/reset_password/{user_id}" onclick="return confirm('⚠️ ¿Seguro que querés restablecer la contraseña de {user_name}?')" style="background:#f6e05e;color:#1a1a2e;padding:5px 10px;border-radius:4px;text-decoration:none;font-size:0.8rem;font-weight:600;">🔑 Reset</a>
        </div>
        """

    html = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Admin Red</title><style>body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;padding:40px}.search{display:flex;gap:10px;margin-bottom:30px}input{flex:1;padding:12px;background:#1a1a2e;color:#fff;border:1px solid #444;border-radius:8px}button{background:#667eea;color:#fff;padding:12px 24px;border:none;border-radius:8px;cursor:pointer}.card{background:#1a1a2e;padding:20px;border-radius:12px;margin-bottom:20px;border:1px solid #333}.section{margin-bottom:30px}.section h3{color:#667eea;margin-bottom:15px}.node{margin-bottom:10px;padding:10px;background:#0f0f1a;border-radius:8px}.lvl1{border-left:3px solid #667eea;padding-left:15px}.lvl2{border-left:3px solid #38a169;padding-left:30px}.lvl3{border-left:3px solid #f6e05e;padding-left:45px}.info{font-size:0.9rem;color:#a0aec0}.info span{color:#fff;font-weight:600}a{color:#667eea;text-decoration:none}code{background:#1a1a2e;padding:2px 5px;border-radius:3px}</style></head><body><h2>🌳 Visor de Ciclo</h2><a href="/dashboard">← Volver</a><form method="GET" class="search"><input name="q" placeholder="Buscar por Sticker o Nombre..." value=\"""" + query + """\"><button type="submit">Buscar</button></form>"""

    if target:
        if ancestors:
            html += '<div class="section"><h3>🔝 Ascendientes de este Ciclo</h3>'
            for a in ancestors:
                html += f"""<div class="node"><div class="info"><span>{a['full_name']}</span> | STK: {a['sticker_id']} | Tel: {a['phone']} | Nivel: {a['current_level']}</div>{user_buttons(a['id'], a['full_name'])}</div>"""
            html += '</div>'

        pwd_display = target['password_hash'][:15] + "..." if target['password_hash'] else "No definida"
        html += f"""<div class="section" style="background:#1a1a2e;padding:25px;border-radius:12px;border:2px solid #667eea;text-align:center;">
            <h3 style="margin:0 0 10px 0;color:#fff;">🎯 Usuario Buscado</h3>
            <div class="info" style="font-size:1.1rem;"><span>{target['full_name']}</span> | STK: {target['sticker_id']}<br>Tel: {target['phone']} | Nivel: {target['current_level']} | Rol: {target['role']}</div>
            <div class="info" style="margin-top:10px;">Pass: <code style="color:#f6e05e">{pwd_display}</code></div>
            {user_buttons(target['id'], target['full_name'])}
        </div>"""

        html += '<div class="section"><h3>🔽 Red de Ventas (Hijos → Nietos → Bisnietos)</h3>'
        if not descendants:
            html += '<p class="info">No hay descendientes registrados aún.</p>'
        else:
            for d in descendants:
                u = d["data"]; pwd_disp = u['password_hash'][:15] + "..." if u['password_hash'] else "No definida"
                nivel_label = {1: "👤 Hijo", 2: "👶 Nieto", 3: "👣 Bisnieto"}.get(d["nivel"], "Descendiente")
                nivel_class = {1: "lvl1", 2: "lvl2", 3: "lvl3"}.get(d["nivel"], "")
                html += f"""<div class="node {nivel_class}"><div class="info">{nivel_label} (Vendido por: {d['padre_stk']})</div><div class="info">STK: {u['sticker_id']} | Nombre: {u['full_name']} | Tel: {u['phone']}</div><div class="info">Nivel: {u['current_level']} | Pass: <code style="color:#f6e05e">{pwd_disp}</code></div>{user_buttons(u['id'], u['full_name'])}</div>"""
        html += '</div>'
    elif query:
        html += "<p style='color:#e53e3e'>❌ Usuario no encontrado.</p>"
    html += "</body></html>"
    return render_template_string(html)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
