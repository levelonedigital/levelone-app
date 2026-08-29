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

MP_MONTO_VENTA = 30000.0
MP_MONTO_LICENCIA_DIRECTA = 60000.0

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def get_cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# 🟢 NUEVO: elimina una venta pendiente y todo lo que creó (usuario, vínculo, ciclo)
def _eliminar_venta_pendiente(cur, sticker_id, code, cid):
    cur.execute("SELECT id FROM users WHERE sticker_id=%s", (code,)); bu = cur.fetchone()
    if bu:
        cur.execute("DELETE FROM referral_tree WHERE child_id=%s", (bu["id"],))
        cur.execute("DELETE FROM users WHERE id=%s", (bu["id"],))
    cur.execute("DELETE FROM stickers WHERE id=%s", (sticker_id,))
    if cid:
        cur.execute("DELETE FROM cycle_levels WHERE cycle_id=%s", (cid,))
        cur.execute("DELETE FROM cycles WHERE id=%s", (cid,))

# 🟢 NUEVO: auto-limpia ventas pending con más de 12hs (se llama al interactuar)
def limpiar_pendientes_viejas(cur, conn):
    limite = datetime.now() - timedelta(hours=12)
    cur.execute("SELECT id, sticker_code, cycle_id FROM stickers WHERE status='pending' AND created_at < %s", (limite,))
    viejas = cur.fetchall()
    for s in viejas:
        _eliminar_venta_pendiente(cur, s["id"], s["sticker_code"], s["cycle_id"])
    if viejas:
        conn.commit()
        print(f"[LIMPIEZA] 🗑️ {len(viejas)} venta(s) pendiente(s) de +12hs eliminada(s).", flush=True)

def crear_pago_mp(sticker_code, step, monto, buyer_name=None, buyer_email=None, ref_prefix="STK"):
    token = os.environ.get("MP_ACCESS_TOKEN")
    if not token:
        print("[MP] ⚠️ No hay MP_ACCESS_TOKEN cargado.", flush=True)
        return None, None
    try:
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        reference = f"{ref_prefix}-{sticker_code}-P{step}"
        payload = {
            "items": [{
                "title": f"levelONE - Licencia {sticker_code} (paso {step})",
                "quantity": 1,
                "unit_price": float(monto),
                "currency_id": "ARS"
            }],
            "external_reference": reference,
            "notification_url": "https://levelone.uno/mp/webhook",
            "statement_descriptor": "LEVELONE",
            "back_urls": {
                "success": "https://levelone.uno/ingresar",
                "pending": "https://levelone.uno/ingresar",
                "failure": "https://levelone.uno/"
            }
        }
        if buyer_email:
            payload["payer"] = {"email": buyer_email, "name": buyer_name or ""}
        r = requests.post("https://api.mercadopago.com/checkout/preferences", json=payload, headers=headers, timeout=10)
        print(f"[MP] Respuesta preferencia {reference}: {r.status_code}", flush=True)
        r.raise_for_status()
        data = r.json()
        return data.get("id"), data.get("init_point")
    except Exception as e:
        print(f"[MP] ❌ Error creando link: {e}", flush=True)
        return None, None

def init_db():
    conn = get_db(); cur = get_cur(conn)
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
        id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT, image_url TEXT,
        start_date DATE, price DECIMAL(10,2), discount_pct INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    try:
        cur.execute("ALTER TABLE stickers ADD COLUMN IF NOT EXISTS mp_link TEXT")
        cur.execute("ALTER TABLE stickers ADD COLUMN IF NOT EXISTS mp_payment_id TEXT")
    except Exception as e:
        print(f"[DB] Nota columnas MP: {e}", flush=True)
    cur.execute("SELECT id FROM users WHERE sticker_id=%s", ('ADMIN001',))
    if not cur.fetchone():
        cur.execute('''INSERT INTO users (sticker_id, full_name, email, phone, cbu_alias, password_hash, current_level, is_level1, role, terms_accepted_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                     ('ADMIN001', 'Administrador', 'admin@levelone.com', '+5491100000000', 'admin.levelone.mp',
                      generate_password_hash("Admin2026!", method='pbkdf2:sha256'), 1, True, 'level1', datetime.now()))
    conn.commit(); print("✅ DB inicializada.", flush=True); conn.close()

init_db()

@app.route("/")
def index():
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT id, title, description, image_url, start_date, price, discount_pct FROM courses WHERE status='active' ORDER BY start_date ASC")
    rows = cur.fetchall(); conn.close()
    cursos = []
    for r in rows:
        cursos.append({'title': r['title'], 'description': r['description'] or '', 'image_url': r['image_url'] or '',
            'start_date': r['start_date'].strftime('%d/%m/%Y') if r['start_date'] else '',
            'price': float(r['price']) if r['price'] else 0, 'discount_pct': int(r['discount_pct']) if r['discount_pct'] else 0})
    return render_template("index.html", cursos=cursos)

@app.route("/comprar")
def comprar():
    ref = request.args.get("ref","").strip()
    con_codigo = request.args.get("con_codigo","").strip()
    return render_template("comprar.html", ref_code=ref, con_codigo=con_codigo)

@app.route("/procesar_compra", methods=["POST"])
def procesar_compra():
    conn = get_db(); cur = get_cur(conn)
    try:
        limpiar_pendientes_viejas(cur, conn)
        name = request.form.get("name","").strip(); phone = request.form.get("phone","").strip()
        email = request.form.get("email","").strip(); cbu = request.form.get("cbu","").strip()
        cbu_titular = request.form.get("cbu_titular","").strip(); cbu_dni = request.form.get("cbu_dni","").strip()
        cbu_entidad = request.form.get("cbu_entidad","").strip(); sticker_name = request.form.get("sticker_name","").strip()
        ref_code = request.form.get("ref_code","").strip()

        def volver():
            if ref_code: return redirect("/comprar?ref=" + ref_code)
            return redirect("/comprar")

        if not all([name, phone, email, cbu, sticker_name]):
            flash("❌ Nombre, teléfono, email, CBU y usuario son obligatorios."); conn.close(); return volver()
        if not re.match(r'^[a-zA-Z0-9_]+$', sticker_name):
            flash("❌ El usuario solo puede contener letras, números y guión bajo."); conn.close(); return volver()
        cur.execute("SELECT id FROM users WHERE sticker_id=%s", (sticker_name,))
        if cur.fetchone():
            flash(f"❌ El usuario '{sticker_name}' ya está en uso."); conn.close(); return volver()

        referrer_id = None; use_referral = False
        if ref_code:
            cur.execute("SELECT id, sticker_id, full_name, current_level, role FROM users WHERE sticker_id=%s", (ref_code,))
            referrer_data = cur.fetchone()
            if not referrer_data:
                flash(f"❌ El código '{ref_code}' no existe. Podés comprar directo o probar otro."); conn.close(); return volver()
            cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND status='entregado'", (referrer_data["id"],))
            if referrer_data["role"] == "graduated" or cur.fetchone()["cnt"] >= 3:
                flash(f"⚠️ El código '{ref_code}' ya completó su ciclo. Podés comprar directo a la plataforma."); conn.close(); return volver()
            cur.execute("""SELECT s.id FROM cycles c JOIN cycle_levels cl ON c.id=cl.cycle_id JOIN stickers s ON s.cycle_id=c.id
                         WHERE c.l5_user_id=%s AND cl.user_id=%s AND cl.level=5 AND s.status IN ('pending','sent','confirmed') LIMIT 1""",
                         (referrer_data["id"], referrer_data["id"]))
            if cur.fetchone():
                flash(f"⚠️ El código '{ref_code}' tiene una venta en curso."); conn.close(); return volver()
            referrer_id = referrer_data["id"]; use_referral = True; monto = MP_MONTO_VENTA
        else:
            monto = MP_MONTO_LICENCIA_DIRECTA

        temp_pass = "Temp-" + str(uuid.uuid4())[:8]

        if use_referral:
            seller_id = referrer_id
            cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND status='entregado'", (seller_id,))
            completed = cur.fetchone()["cnt"]
            step = completed + 1

            cur.execute('''INSERT INTO users (sticker_id, full_name, phone, email, cbu_alias, password_hash, role)
                           VALUES (%s,%s,%s,%s,%s,%s,'inactive') RETURNING id''',
                        (sticker_name, name, phone, email, cbu, generate_password_hash(temp_pass, method='pbkdf2:sha256')))
            buyer_id = cur.fetchone()["id"]

            cur.execute("INSERT INTO cycles (l5_user_id) VALUES (%s) RETURNING id", (seller_id,)); cycle_id = cur.fetchone()["id"]
            cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (seller_id, cycle_id, 5))
            cur.execute("UPDATE users SET current_level=5 WHERE id=%s", (seller_id,))
            current_parent = seller_id
            for lvl in [4, 3, 2, 1]:
                cur.execute("SELECT parent_id FROM referral_tree WHERE child_id=%s", (current_parent,)); up = cur.fetchone()
                if not up: break
                parent_id = up["parent_id"]
                cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (parent_id, cycle_id, lvl))
                cur.execute("SELECT sticker_id FROM users WHERE id=%s", (parent_id,)); p_data = cur.fetchone()
                if p_data and p_data["sticker_id"] == "ADMIN001": break
                cur.execute("UPDATE users SET current_level=%s WHERE id=%s", (lvl, parent_id)); current_parent = parent_id
            cur.execute("SELECT user_id FROM cycle_levels WHERE cycle_id=%s AND level=1", (cycle_id,))
            if not cur.fetchone():
                cur.execute("SELECT id FROM users WHERE sticker_id='ADMIN001'"); admin_row = cur.fetchone()
                if admin_row:
                    cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (admin_row["id"], cycle_id, 1))

            cur.execute("INSERT INTO referral_tree (parent_id, child_id) VALUES (%s,%s) ON CONFLICT (parent_id,child_id) DO NOTHING", (seller_id, buyer_id))

            cur.execute('''INSERT INTO stickers (sticker_code, seller_id, cycle_id, buyer_name, buyer_phone, buyer_email, buyer_cbu, buyer_cbu_titular, buyer_cbu_dni, buyer_cbu_entidad, step, confirmation_token, temp_pass, status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING id''',
                        (sticker_name, seller_id, cycle_id, name, phone, email, cbu, cbu_titular, cbu_dni, cbu_entidad, step, str(uuid.uuid4())[:12], temp_pass))
            sticker_new_id = cur.fetchone()["id"]

            should_generate_mp = False
            if step == 1: should_generate_mp = True
            elif step == 2:
                cur.execute("SELECT u.sticker_id FROM cycle_levels cl JOIN users u ON cl.user_id=u.id WHERE cl.cycle_id=%s AND cl.level=1", (cycle_id,))
                l1_row = cur.fetchone()
                if l1_row and l1_row["sticker_id"] == "ADMIN001": should_generate_mp = True
            mp_pref_id, mp_link_gen = (None, None)
            if should_generate_mp:
                mp_pref_id, mp_link_gen = crear_pago_mp(sticker_name, step, monto, name, email, ref_prefix="REF")
            if mp_link_gen:
                cur.execute("UPDATE stickers SET mp_link=%s, mp_payment_id=%s WHERE id=%s", (mp_link_gen, mp_pref_id, sticker_new_id))
                conn.commit(); print(f"[WEB COMPRA] ✅ REF {sticker_name} (paso {step}) creado", flush=True); conn.close(); return redirect(mp_link_gen)
            else:
                conn.commit(); flash(f"✅ Usuario '{sticker_name}' creado. Contraseña: {temp_pass}"); conn.close(); return redirect("/ingresar")
        else:
            cur.execute('''INSERT INTO users (sticker_id, full_name, phone, email, cbu_alias, password_hash, role)
                           VALUES (%s,%s,%s,%s,%s,%s,'seller') RETURNING id''',
                        (sticker_name, name, phone, email, cbu, generate_password_hash(temp_pass, method='pbkdf2:sha256')))
            buyer_id = cur.fetchone()["id"]
            cur.execute("INSERT INTO cycles (l5_user_id) VALUES (%s) RETURNING id", (buyer_id,)); cycle_id = cur.fetchone()["id"]
            cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,5)", (buyer_id, cycle_id))
            cur.execute("UPDATE users SET current_level=5 WHERE id=%s", (buyer_id,))
            cur.execute("SELECT id FROM users WHERE sticker_id='ADMIN001'"); admin_row = cur.fetchone()
            if admin_row:
                cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,1)", (admin_row["id"], cycle_id))
            cur.execute('''INSERT INTO stickers (sticker_code, seller_id, cycle_id, buyer_name, buyer_phone, buyer_email, buyer_cbu, buyer_cbu_titular, buyer_cbu_dni, buyer_cbu_entidad, step, confirmation_token, temp_pass, status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING id''',
                        (sticker_name, admin_row["id"], cycle_id, name, phone, email, cbu, cbu_titular, cbu_dni, cbu_entidad, 1, str(uuid.uuid4())[:12], temp_pass))
            sticker_new_id = cur.fetchone()["id"]
            mp_pref_id, mp_link_gen = crear_pago_mp(sticker_name, 1, monto, name, email, ref_prefix="WEB")
            if mp_link_gen:
                cur.execute("UPDATE stickers SET mp_link=%s, mp_payment_id=%s WHERE id=%s", (mp_link_gen, mp_pref_id, sticker_new_id))
                conn.commit(); print(f"[WEB COMPRA] ✅ WEB {sticker_name} creado", flush=True); conn.close(); return redirect(mp_link_gen)
            else:
                conn.commit(); flash(f"✅ Usuario '{sticker_name}' creado. Contraseña: {temp_pass}"); conn.close(); return redirect("/ingresar")
    except Exception as e:
        conn.rollback(); print(f"[WEB COMPRA] ❌ Error: {traceback.format_exc()}", flush=True); flash(f"❌ Error: {str(e)}")
    finally:
        try: conn.close()
        except: pass
    return redirect("/comprar")

# 🟢 NUEVO: el vendedor cancela una venta pendiente (antes de que el comprador pague)
@app.route("/cancelar_venta/<int:sticker_id>", methods=["POST"])
def cancelar_venta(sticker_id):
    if "user_id" not in session: return redirect("/login")
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,)); s = cur.fetchone()
        if not s:
            conn.close(); flash("⚠️ Venta no encontrada."); return redirect("/dashboard")
        if s["seller_id"] != session["user_id"]:
            conn.close(); flash("⛔ No podés cancelar esta venta."); return redirect("/dashboard")
        if s["status"] != "pending":
            conn.close(); flash("⚠️ Solo se pueden cancelar ventas pendientes de pago."); return redirect("/dashboard")
        _eliminar_venta_pendiente(cur, s["id"], s["sticker_code"], s["cycle_id"])
        conn.commit(); flash("🗑️ Venta cancelada y usuario liberado.")
    except Exception as e:
        conn.rollback(); print(f"[CANCELAR] ❌ Error: {traceback.format_exc()}", flush=True); flash(f"❌ Error: {str(e)}")
    finally: conn.close()
    return redirect("/dashboard")

@app.route("/ingresar", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        sid = request.form["sticker_id"].strip(); pwd = request.form["password"].strip()
        conn = get_db(); cur = get_cur(conn)
        cur.execute("SELECT * FROM users WHERE sticker_id=%s", (sid,)); row_u = cur.fetchone()
        if row_u and check_password_hash(row_u["password_hash"], pwd):
            session["user_id"] = row_u["id"]; session["role"] = row_u["role"]
            try:
                if row_u.get("terms_accepted_at") is None:
                    conn.close(); return redirect(url_for("accept_terms"))
            except: pass
            conn.close(); return redirect(url_for("dashboard"))
        flash("Sticker o contraseña incorrectos."); conn.close()
    return render_template("login.html")

@app.route("/terminos")
def terminos():
    return render_template_string("""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Términos y Condiciones - levelONE</title>
    <style>body{font-family:'Segoe UI',sans-serif;background:#f4f7f6;color:#333;line-height:1.6;margin:0;padding:20px}.container{max-width:850px;margin:0 auto;background:#fff;padding:40px;border-radius:12px}h1{color:#4a5568;border-bottom:2px solid #e2e8f0;padding-bottom:10px}h2{color:#2d3748;margin-top:30px;border-bottom:1px solid #edf2f7;padding-bottom:6px}.logo-center{text-align:center;margin-bottom:20px}.logo-center img{height:60px}.alert{background:#fff3cd;color:#856404;padding:15px;border-radius:8px;margin:20px 0}.disclaimer{background:#f7fafc;border-left:4px solid #667eea;padding:20px;border-radius:8px;margin:30px 0}.btn-back{display:inline-block;background:#667eea;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;margin-top:20px}ul{margin-bottom:15px}li{margin-bottom:6px}</style>
    </head><body><div class="container">
    <div class="logo-center"><img src="/static/Logo.png" alt="levelONE"></div>
    <h1>📜 Términos y Condiciones – levelONE</h1>
    <p><em>Última actualización: Agosto 2026.</em></p>

    <h2>1. Naturaleza del servicio</h2>
    <p>LevelONE es una plataforma digital que ofrece:</p>
    <ul>
      <li>Acceso a una comunidad privada de usuarios</li>
      <li>Beneficios asociados a capacitaciones y contenidos</li>
      <li>La posibilidad de participar en un sistema de actividad en red basado en la venta de productos</li>
    </ul>
    <p>La adquisición de la <strong>licencia LevelONE</strong> constituye la compra de un producto con beneficios asociados, siendo el acceso a la plataforma una funcionalidad adicional.</p>

    <h2>2. Producto y beneficios incluidos</h2>
    <p>Al adquirir la <strong>licencia LevelONE</strong>, el usuario obtiene:</p>
    <ul>
      <li>Acceso a una comunidad privada (por ejemplo, WhatsApp u otros medios definidos por la plataforma)</li>
      <li>Acceso a capacitaciones en áreas como ventas, marketing y herramientas digitales, con un beneficio de <strong>hasta el 80% de descuento</strong> sobre el valor de las mismas</li>
      <li>Acceso a contenidos, materiales o recursos que la plataforma pueda ofrecer</li>
    </ul>
    <p>Las capacitaciones podrán ser en modalidad presencial o virtual, y estarán sujetas a disponibilidad, organización, cantidad de participantes y condiciones específicas.</p>

    <h2>3. Condiciones de participación</h2>
    <p>Para utilizar la plataforma, el usuario debe:</p>
    <ul>
      <li>Ser mayor de 18 años</li>
      <li>Aceptar los presentes términos y condiciones. <strong>La aceptación queda registrada al momento del primer ingreso y es condición para usar la plataforma.</strong></li>
      <li>Comprender el funcionamiento del sistema</li>
      <li>Actuar de manera activa si decide participar en la red</li>
    </ul>

    <h2>4. Sistema de actividad en red (opcional)</h2>
    <p>LevelONE ofrece la posibilidad opcional de participar en un sistema de actividad en red basado en la <strong>venta de licencias</strong>. El usuario:</p>
    <ul>
      <li>No está obligado a participar en dicho sistema</li>
      <li>Puede utilizar el producto únicamente por sus beneficios asociados</li>
      <li>La participación en el sistema implica actividad comercial y seguimiento de red</li>
    </ul>

    <h2>5. Funcionamiento del sistema</h2>
    <p>En caso de participar en la red:</p>
    <ul>
      <li>El usuario podrá avanzar por niveles mediante la venta de licencias</li>
      <li>El sistema se estructura en niveles (del 5 al 1)</li>
      <li>El avance depende tanto de la actividad individual como de la red</li>
    </ul>

    <h2>6. Flujo de pagos</h2>
    <p>Los pagos dentro del sistema son procesados por la entidad de procesamiento de pagos que la plataforma habilite al momento de cada operación.</p>
    <p><strong>Distribución:</strong></p>
    <ul>
      <li><strong>1° venta:</strong> destinada a mantenimiento y estructura</li>
      <li><strong>2° venta:</strong> destinada a un usuario en Nivel 1</li>
      <li><strong>3° venta:</strong> destinada al propio usuario</li>
    </ul>
    <p>Cuando el destinatario del pago es un usuario (2° y 3° venta), la acreditación se confirma entre usuarios y la plataforma <strong>no retiene ni administra esos fondos</strong>, no actuando como intermediaria financiera respecto de los montos que corresponden a los usuarios.</p>

    <h2>7. Límite y graduación</h2>
    <p>Los usuarios que alcanzan el Nivel 1 podrán recibir hasta un máximo de <strong>81 pagos</strong>. Al alcanzar dicho límite:</p>
    <ul>
      <li>Se considera completado el ciclo</li>
      <li>El usuario es graduado</li>
      <li>Finaliza su participación en ese ciclo</li>
    </ul>

    <h2>8. Naturaleza de los ingresos</h2>
    <p>El usuario reconoce que:</p>
    <ul>
      <li>No se trata de una inversión</li>
      <li>No existen ingresos garantizados</li>
      <li>Los resultados dependen de su actividad y la de su red</li>
    </ul>

    <h2>9. Responsabilidad del usuario</h2>
    <p>El usuario es responsable de:</p>
    <ul>
      <li>Su participación en el sistema</li>
      <li>La gestión de su red</li>
      <li>La coordinación de pagos con otros usuarios</li>
      <li>Verificar las transacciones realizadas</li>
    </ul>

    <h2>10. Plazos y cancelaciones</h2>
    <ul>
      <li>El usuario dispone de un plazo de <strong>7 días corridos</strong> para completar sus 3 ventas iniciales dentro del sistema.</li>
      <li>Una venta iniciada que no se paga dentro de las <strong>12 horas</strong> se cancela y libera automáticamente.</li>
      <li>En caso de no cumplir, la participación podrá ser cancelada</li>
      <li>No se garantizan reintegros</li>
      <li>Se anula su membresía / licencia en LevelONE</li>
    </ul>

    <h2>11. Capacitaciones</h2>
    <p>Las capacitaciones:</p>
    <ul>
      <li>No son obligatorias</li>
      <li>Se ofrecen como beneficio adicional</li>
      <li>Están sujetas a disponibilidad</li>
      <li>Pueden variar en contenido, modalidad y frecuencia</li>
    </ul>
    <p>El descuento ofrecido (<strong>hasta 80%</strong>) no constituye obligación permanente y puede ser modificado.</p>

    <h2>12. Comunidad</h2>
    <p>El acceso a la comunidad:</p>
    <ul>
      <li>Es un beneficio incluido con la compra</li>
      <li>Puede estar sujeto a normas de conducta</li>
      <li>Puede ser restringido o cancelado ante incumplimientos</li>
    </ul>

    <h2>13. Exclusión de responsabilidad</h2>
    <p>La plataforma:</p>
    <ul>
      <li>No garantiza resultados económicos</li>
      <li>No se responsabiliza por pérdidas o falta de ganancias</li>
      <li>No interviene en conflictos entre usuarios</li>
      <li>No asegura continuidad del sistema</li>
    </ul>

    <h2>14. Licencia y credenciales</h2>
    <ul>
      <li>La <strong>licencia LevelONE</strong> es personal e intransferible.</li>
      <li>Las credenciales de acceso (usuario y contraseña) son personales y el usuario es responsable de custodiarlas.</li>
      <li>Si la compra se realiza con un <strong>código de referido</strong> de un usuario activo, o directamente a un usuario activo, la licencia accede a un <strong>precio especial</strong> respecto de su valor oficial.</li>
    </ul>

    <h2>15. Declaración del usuario</h2>
    <p>El usuario declara que:</p>
    <ul>
      <li>Comprende el funcionamiento del sistema</li>
      <li>Acepta participar de forma voluntaria</li>
      <li>Entiende los riesgos asociados</li>
    </ul>

    <div class="disclaimer">
      <h2 style="margin-top:0;">⚖️ DESCARGO DE RESPONSABILIDAD</h2>
      <p>LevelONE es una plataforma orientada a la comercialización de productos y acceso a beneficios formativos.</p>
      <p><strong>No constituye:</strong></p>
      <ul>
        <li>Un sistema de inversión</li>
        <li>Un esquema financiero</li>
        <li>Una promesa de rentabilidad</li>
        <li>Un sistema de ingresos pasivos garantizados</li>
      </ul>
      <p>La participación en el sistema de red es opcional y depende de la actividad del usuario.</p>
      <p>Los resultados pueden variar significativamente y dependen de múltiples factores, incluyendo:</p>
      <ul>
        <li>Habilidades comerciales</li>
        <li>Compromiso</li>
        <li>Actividad de terceros</li>
      </ul>
      <p>La empresa no será responsable por pérdidas económicas, falta de resultados, ni conflictos entre usuarios.</p>
      <p><strong>El usuario participa bajo su exclusiva responsabilidad.</strong></p>
    </div>

    <p style="text-align:center"><a href="/" class="btn-back">Volver al inicio</a></p></div></body></html>""")

@app.route("/accept_terms")
def accept_terms():
    if "user_id" not in session: return redirect(url_for("login"))
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],)); row_u = cur.fetchone(); conn.close()
    try:
        if not row_u or row_u.get("terms_accepted_at") is not None: return redirect(url_for("dashboard"))
    except: return redirect(url_for("dashboard"))
    return render_template("login.html", show_terms_modal=True, user=row_u)

@app.route("/api/accept_terms", methods=["POST"])
def api_accept_terms():
    if "user_id" not in session: return jsonify({"success": False}), 401
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("UPDATE users SET terms_accepted_at=%s, terms_version=%s WHERE id=%s", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "v2.0", session["user_id"]))
        conn.commit(); return jsonify({"success": True})
    except Exception as e: conn.rollback(); return jsonify({"success": False}), 500
    finally: conn.close()

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session: return redirect(url_for("login"))
    conn = get_db(); cur = get_cur(conn)
    limpiar_pendientes_viejas(cur, conn)
    cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],)); row_u = cur.fetchone()
    if not row_u: session.clear(); conn.close(); return redirect(url_for("login"))
    try:
        if row_u.get("terms_accepted_at") is None: conn.close(); return redirect(url_for("accept_terms"))
    except: pass
    u = dict(row_u); uid = u.get("id"); role = u.get("role", "seller"); sticker = u.get("sticker_id", ""); level = u.get("current_level", 5)
    cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND status='entregado'", (uid,)); cnt = cur.fetchone()["cnt"]
    u["can_sell"] = (cnt < 3); u["completed_count"] = cnt
    cur.execute("""SELECT c.* FROM cycles c JOIN cycle_levels cl ON c.id=cl.cycle_id WHERE c.l5_user_id=%s AND cl.user_id=%s AND cl.level=5 ORDER BY c.id DESC LIMIT 1""", (uid, uid))
    active_cycle = cur.fetchone(); cycle_id = active_cycle["id"] if active_cycle else None
    cycle_level = level; is_graduated_cycle = False
    if cycle_id:
        cur.execute("SELECT level, is_graduated FROM cycle_levels WHERE user_id=%s AND cycle_id=%s", (uid, cycle_id)); cl = cur.fetchone()
        if cl: cycle_level = cl["level"]; is_graduated_cycle = bool(cl["is_graduated"])
    u["current_level"] = cycle_level
    pending = None
    if cycle_id:
        cur.execute("SELECT * FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status IN ('pending','sent','confirmed') ORDER BY created_at DESC LIMIT 1", (uid, cycle_id))
        pr = cur.fetchone(); pending = dict(pr) if pr else None
    pending_cbu = "No configurado"; pending_phone = "No configurado"
    if pending:
        step = pending["step"]; cid = pending["cycle_id"] or cycle_id
        if step == 1: cur.execute("SELECT cbu_alias FROM users WHERE sticker_id=%s", ('ADMIN001',)); row = cur.fetchone()
        elif step == 2: cur.execute("SELECT u.cbu_alias FROM cycle_levels cl JOIN users u ON cl.user_id=u.id WHERE cl.cycle_id=%s AND cl.level=1 LIMIT 1", (cid,)); row = cur.fetchone()
        elif step == 3: cur.execute("SELECT cbu_alias FROM users WHERE id=%s", (uid,)); row = cur.fetchone()
        else: row = None
        pending_cbu = row["cbu_alias"] if row else "No configurado"; pending_phone = pending["buyer_phone"] or "No configurado"
    confirmations = []
    if sticker == 'ADMIN001':
        cur.execute("""SELECT id, sticker_code, buyer_name, buyer_cbu, buyer_cbu_titular, buyer_cbu_dni, buyer_cbu_entidad, buyer_phone, cycle_id, step, status
            FROM stickers WHERE status='sent' AND (step=1 OR (step=2 AND cycle_id IN (SELECT cycle_id FROM cycle_levels WHERE user_id=(SELECT id FROM users WHERE sticker_id='ADMIN001') AND level=1))) ORDER BY created_at DESC""")
        confirmations = cur.fetchall()
    elif level != 5 and role != "graduated":
        cur.execute('''SELECT s.id, s.sticker_code, s.buyer_name, s.buyer_cbu, s.buyer_cbu_titular, s.buyer_cbu_dni, s.buyer_cbu_entidad, s.buyer_phone, s.cycle_id, s.step, s.status FROM stickers s JOIN cycle_levels cl ON s.cycle_id=cl.cycle_id WHERE s.step=2 AND s.status='sent' AND cl.level=1 AND cl.user_id=%s''', (uid,))
        confirmations = cur.fetchall()
    participants = []
    if level != 5 and sticker != "ADMIN001" and role != "graduated":
        try:
            desc_ids = []; queue, visited = deque([uid]), set([uid])
            while queue:
                curr = queue.popleft()
                cur.execute("SELECT child_id FROM referral_tree WHERE parent_id=%s", (curr,))
                for r in cur.fetchall():
                    c2 = r["child_id"]
                    if c2 and c2 not in visited: visited.add(c2); desc_ids.append(c2); queue.append(c2)
            all_ids = [uid] + desc_ids; ph = ','.join(['%s']*len(all_ids))
            cur.execute(f"SELECT id, sticker_id, full_name, phone, current_level FROM users WHERE id IN ({ph})", all_ids)
            participants = [dict(p) for p in cur.fetchall()]
            sales_map = {}
            cur.execute(f"SELECT seller_id, COUNT(*) as cnt FROM stickers WHERE seller_id IN ({ph}) AND status='entregado' GROUP BY seller_id", all_ids)
            for r in cur.fetchall(): sales_map[r["seller_id"]] = r["cnt"]
            for p in participants:
                p["sales_done"] = 3 if (sales_map.get(p["id"],0)==0 and p["current_level"]<5) else sales_map.get(p["id"],0)
                if active_cycle:
                    cur.execute("SELECT level FROM cycle_levels WHERE user_id=%s AND cycle_id=%s", (p["id"], cycle_id)); cl = cur.fetchone()
                    p["level"] = cl["level"] if cl else p["current_level"]
                else: p["level"] = p["current_level"]
        except: pass
    my_sales_history = []; income_history = []
    cur.execute("SELECT id, sticker_code, temp_pass, buyer_name, buyer_cbu, buyer_cbu_titular, buyer_cbu_dni, buyer_cbu_entidad, buyer_phone, status, created_at FROM stickers WHERE seller_id=%s ORDER BY created_at DESC", (uid,))
    my_sales_history = [dict(s) for s in cur.fetchall()]
    if sticker == "ADMIN001":
        cur.execute("SELECT * FROM stickers WHERE step=1 AND status IN ('confirmed','entregado') ORDER BY created_at DESC"); income_history = [dict(r) for r in cur.fetchall()]
    elif level == 5:
        cur.execute("SELECT * FROM stickers WHERE seller_id=%s AND status='entregado' ORDER BY created_at DESC", (uid,)); income_history = [dict(r) for r in cur.fetchall()]
    else:
        cur.execute("SELECT cycle_id FROM cycle_levels WHERE user_id=%s AND level=1", (uid,)); l1c = [r["cycle_id"] for r in cur.fetchall()]
        if l1c:
            ph = ','.join(['%s']*len(l1c))
            cur.execute(f"SELECT * FROM stickers WHERE step=2 AND status IN ('confirmed','entregado') AND cycle_id IN ({ph}) ORDER BY created_at DESC", l1c)
            income_history = [dict(r) for r in cur.fetchall()]
    try:
        cl_list = [active_cycle] if active_cycle else []
        active_cycles_display = [c for c in cl_list if not (c.get("completed_at") and (datetime.now()-datetime.strptime(c["completed_at"],"%Y-%m-%d %H:%M:%S")).days>30)]
    except: active_cycles_display = [active_cycle] if active_cycle else []
    cur.execute("SELECT cbu_alias FROM users WHERE sticker_id=%s", ('ADMIN001',)); admin_cbu = cur.fetchone()["cbu_alias"] if cur.rowcount>0 else "No configurado"
    cur.execute("SELECT mp_enabled, mp_payment_link FROM users WHERE sticker_id='ADMIN001'"); mp_cfg = cur.fetchone()
    mp_enabled = mp_cfg["mp_enabled"] if mp_cfg else False; mp_link = mp_cfg["mp_payment_link"] if mp_cfg else ""
    cur.execute("""SELECT s.created_at, s.sticker_code, s.buyer_name, s.buyer_cbu, s.buyer_cbu_titular, s.buyer_cbu_dni, s.buyer_cbu_entidad, s.status FROM stickers s JOIN cycle_levels cl ON s.cycle_id=cl.cycle_id WHERE cl.user_id=%s AND cl.level=1 AND s.step=2 AND s.status IN ('confirmed','entregado') ORDER BY s.created_at DESC LIMIT 20""", (session["user_id"],))
    l1_payments = cur.fetchall()
    referral_link = f"https://levelone.uno/?ref={sticker}" if sticker and sticker != "ADMIN001" else ""
    conn.close()
    return render_template("dashboard.html", user=u, admin_cbu=admin_cbu, cycles=active_cycles_display, active_cycle=active_cycle, cycle_level=cycle_level, is_graduated_cycle=is_graduated_cycle, participants=participants, pending=pending, pending_cbu=pending_cbu, pending_phone=pending_phone, confirmations=confirmations, my_sales=[{"sale":s,"num":len(my_sales_history)-i} for i,s in enumerate(my_sales_history)], income=[{"sale":s,"num":len(income_history)-i} for i,s in enumerate(income_history)], l1_payments=l1_payments, mp_enabled=mp_enabled, mp_link=mp_link, referral_link=referral_link)

@app.route("/crear_sticker", methods=["POST"])
def crear_sticker():
    if "user_id" not in session: return redirect("/login")
    conn = get_db(); cur = get_cur(conn)
    try:
        limpiar_pendientes_viejas(cur, conn)
        cur.execute("SELECT * FROM users WHERE id=%s", (session["user_id"],)); row_u = cur.fetchone()
        cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE seller_id=%s AND status='entregado'", (row_u["id"],)); completed = cur.fetchone()["cnt"]
        if completed >= 3: flash("🎓 Ciclo completado."); conn.close(); return redirect("/dashboard")
        name = request.form.get("name","").strip(); phone = request.form.get("phone","").strip()
        email = request.form.get("email","").strip(); cbu = request.form.get("cbu","").strip()
        sticker_name = request.form.get("sticker_name","").strip()
        if not all([name, phone, email, cbu]):
            flash("Todos los campos son obligatorios."); conn.close(); return redirect("/dashboard")
        if sticker_name:
            if not re.match(r'^[a-zA-Z0-9_]+$', sticker_name):
                flash("❌ Nombre inválido."); conn.close(); return redirect("/dashboard")
            cur.execute("SELECT id FROM users WHERE sticker_id=%s", (sticker_name,))
            if cur.fetchone():
                flash(f"❌ '{sticker_name}' ya existe."); conn.close(); return redirect("/dashboard")
            code = sticker_name
        else:
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
        cur.execute("SELECT user_id FROM cycle_levels WHERE cycle_id=%s AND level=1", (cycle_id,))
        if not cur.fetchone():
            cur.execute("SELECT id FROM users WHERE sticker_id='ADMIN001'"); admin_row = cur.fetchone()
            if admin_row:
                cur.execute("INSERT INTO cycle_levels (user_id, cycle_id, level) VALUES (%s,%s,%s) ON CONFLICT (user_id,cycle_id) DO UPDATE SET level=EXCLUDED.level", (admin_row["id"], cycle_id, 1))
        cur.execute("SELECT id FROM stickers WHERE seller_id=%s AND cycle_id=%s AND status IN ('pending','sent') LIMIT 1", (row_u["id"], cycle_id))
        if cur.fetchone(): flash("⏳ Esperá a que se confirme el sticker actual."); conn.close(); return redirect(url_for("dashboard", cycle_id=cycle_id))
        step = completed + 1
        temp_pass = "Temp-"+str(uuid.uuid4())[:8]
        cur.execute('''INSERT INTO stickers (sticker_code,seller_id,cycle_id,buyer_name,buyer_phone,buyer_email,buyer_cbu,buyer_cbu_titular,buyer_cbu_dni,buyer_cbu_entidad,step,confirmation_token,temp_pass,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (code,row_u["id"],cycle_id,name,phone,email,cbu,request.form.get("cbu_titular","").strip(),request.form.get("cbu_dni","").strip(),request.form.get("cbu_entidad","").strip(),step,str(uuid.uuid4())[:12],temp_pass,'pending'))
        sticker_new_id = cur.fetchone()["id"]
        should_generate_mp = False
        if step == 1: should_generate_mp = True
        elif step == 2:
            cur.execute("SELECT u.sticker_id FROM cycle_levels cl JOIN users u ON cl.user_id=u.id WHERE cl.cycle_id=%s AND cl.level=1", (cycle_id,)); l1_row = cur.fetchone()
            if l1_row and l1_row["sticker_id"] == "ADMIN001": should_generate_mp = True
        if should_generate_mp:
            mp_pref_id, mp_link_gen = crear_pago_mp(code, step, MP_MONTO_VENTA, name, email, ref_prefix="STK")
            if mp_link_gen:
                cur.execute("UPDATE stickers SET mp_link=%s, mp_payment_id=%s WHERE id=%s", (mp_link_gen, mp_pref_id, sticker_new_id))
        cur.execute('''INSERT INTO users (sticker_id,full_name,phone,email,cbu_alias,password_hash,role) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (code,name,phone,email,cbu,generate_password_hash(temp_pass,method='pbkdf2:sha256'),'inactive'))
        new_id = cur.fetchone()["id"]
        if new_id: cur.execute("INSERT INTO referral_tree (parent_id, child_id) VALUES (%s,%s) ON CONFLICT (parent_id,child_id) DO NOTHING", (row_u["id"], new_id))
        conn.commit(); flash(f"✅ Licencia creada: {code}"); return redirect(url_for("dashboard", cycle_id=cycle_id))
    except Exception as e: conn.rollback(); print(f"[ERROR CREAR] {traceback.format_exc()}", flush=True); flash(f"❌ Error: {str(e)}")
    finally: conn.close()
    return redirect("/dashboard")

@app.route("/mp/webhook", methods=["GET", "POST"])
def mp_webhook():
    if request.method == "GET": return jsonify({"status": "ok"}), 200
    try:
        data = request.get_json(silent=True) or {}
        print(f"[MP-WEBHOOK] Notificación: {data}", flush=True)
        token = os.environ.get("MP_ACCESS_TOKEN")
        if not token: return jsonify({"status": "ok"}), 200
        payment_id = None; tipo = data.get("type") or data.get("topic")
        if tipo in ("payment", "payment.updated"):
            payment_id = (data.get("data") or {}).get("id")
            if not payment_id:
                res = data.get("resource") or ""
                if "/payments/" in res: payment_id = res.split("/payments/")[-1]
            if not payment_id: payment_id = data.get("id")
        if not payment_id: return jsonify({"status": "ok"}), 200
        r = requests.get(f"https://api.mercadopago.com/v1/payments/{payment_id}", headers={"Authorization": "Bearer "+token}, timeout=10)
        r.raise_for_status(); pago = r.json(); status = pago.get("status"); ref = pago.get("external_reference") or ""
        print(f"[MP-WEBHOOK] Pago {payment_id} | status={status} | ref={ref}", flush=True)
        if status != "approved": return jsonify({"status": "ok"}), 200

        if ref.startswith("WEB-") and ref.endswith("-P1"):
            code = ref[4:-3]; conn = get_db(); cur = get_cur(conn)
            try:
                cur.execute("SELECT id, status, buyer_email, buyer_name, temp_pass, sticker_code FROM stickers WHERE sticker_code=%s", (code,)); s = cur.fetchone()
                if s and s["status"] in ("pending","sent"):
                    cur.execute("UPDATE stickers SET status='entregado' WHERE id=%s", (s["id"],)); conn.commit()
                    print(f"[MP-WEBHOOK] ✅ WEB {code} activación completada.", flush=True)
                    _enviar_bienvenida(s["buyer_email"], s["buyer_name"], s["sticker_code"], s["temp_pass"])
            finally: conn.close()
            return jsonify({"status": "ok"}), 200

        if ref.startswith("STK-") and ref.endswith("-P1"):
            code = ref[4:-3]; conn = get_db(); cur = get_cur(conn)
            try:
                cur.execute("SELECT s.id, s.status, s.seller_id, s.buyer_name, s.sticker_code, u.full_name, u.email FROM stickers s JOIN users u ON u.id=s.seller_id WHERE s.sticker_code=%s", (code,)); s = cur.fetchone()
                if s and s["status"] in ("pending","sent"):
                    cur.execute("UPDATE stickers SET status='confirmed' WHERE id=%s", (s["id"],)); conn.commit()
                    print(f"[MP-WEBHOOK] ✅ STK-P1 {code} confirmado.", flush=True)
                    if s["email"]:
                        _avisar_vendedor_credenciales(s["email"], s["full_name"], s["sticker_code"], s["buyer_name"])
            finally: conn.close()
            return jsonify({"status": "ok"}), 200

        if ref.startswith("STK-") and ref.endswith("-P2"):
            code = ref[4:-3]; conn = get_db(); cur = get_cur(conn)
            try:
                cur.execute("""SELECT s.id, s.status, s.seller_id, s.buyer_name, s.sticker_code, u.sticker_id AS l1,
                              v.full_name AS seller_name, v.email AS seller_email
                              FROM stickers s
                              LEFT JOIN cycle_levels cl ON cl.cycle_id=s.cycle_id AND cl.level=1
                              LEFT JOIN users u ON u.id=cl.user_id
                              LEFT JOIN users v ON v.id=s.seller_id
                              WHERE s.sticker_code=%s""", (code,)); s = cur.fetchone()
                if s and s["status"] in ("pending","sent"):
                    if s["l1"] == "ADMIN001":
                        cur.execute("UPDATE stickers SET status='confirmed' WHERE id=%s", (s["id"],)); conn.commit()
                        print(f"[MP-WEBHOOK] ✅ STK-P2 {code} confirmado (L1 plataforma).", flush=True)
                        if s["seller_email"]:
                            _avisar_vendedor_credenciales(s["seller_email"], s["seller_name"], s["sticker_code"], s["buyer_name"])
                    else:
                        print(f"[MP-WEBHOOK] ⏸️ STK-P2 {code} espera confirmación manual.", flush=True)
            finally: conn.close()
            return jsonify({"status": "ok"}), 200

        if ref.startswith("REF-") and "-P" in ref:
            parts = ref[4:].rsplit("-P", 1)
            if len(parts) == 2:
                code = parts[0]; conn = get_db(); cur = get_cur(conn)
                try:
                    cur.execute("""SELECT s.id, s.status, s.seller_id, s.buyer_name, s.sticker_code, u.full_name AS seller_name, u.email AS seller_email
                                  FROM stickers s JOIN users u ON u.id=s.seller_id WHERE s.sticker_code=%s""", (code,)); s = cur.fetchone()
                    if s and s["status"] in ("pending","sent"):
                        cur.execute("UPDATE stickers SET status='confirmed' WHERE id=%s", (s["id"],)); conn.commit()
                        print(f"[MP-WEBHOOK] ✅ REF {code} confirmado (paso {parts[1]}).", flush=True)
                        if s["seller_email"]:
                            _avisar_vendedor_credenciales(s["seller_email"], s["seller_name"], s["sticker_code"], s["buyer_name"])
                finally: conn.close()
            return jsonify({"status": "ok"}), 200

        print(f"[MP-WEBHOOK] Referencia no reconocida: {ref}", flush=True)
    except Exception as e:
        print(f"[MP-WEBHOOK] ❌ Error: {e}", flush=True)
    return jsonify({"status": "ok"}), 200

def _enviar_bienvenida(buyer_email, buyer_name, sticker_code, temp_pass):
    try:
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
        payload = {"sender": {"name": "levelONE", "email": "notificaciones@levelone.uno"}, "to": [{"email": buyer_email, "name": buyer_name}],
            "subject": f"🎉 ¡BIENVENIDO/A A LEVELONE! | {sticker_code}",
            "htmlContent": f"""<!DOCTYPE html><html><body style="margin:0;font-family:sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);"><div style="max-width:520px;margin:20px auto;background:white;border-radius:16px;"><div style="text-align:center;padding:24px;"><img src="https://levelone.uno/static/Logo.png" alt="levelONE" style="height:52px;margin-bottom:12px;"><h1 style="color:#667eea;">🎉 ¡BIENVENIDO/A!</h1><p>Tu licencia <strong>{sticker_code}</strong> está activa ✅</p></div><div style="padding:0 24px 24px;"><div style="background:#f8f9ff;border-left:4px solid #667eea;padding:16px;margin:24px 0;"><p><strong>Usuario:</strong> <code>{sticker_code}</code></p><p><strong>Contraseña:</strong> <code>{temp_pass}</code></p><p><strong>Link:</strong> <a href="https://levelone.uno/ingresar">levelone.uno/ingresar</a></p></div><div style="text-align:center;"><a href="https://levelone.uno/ingresar" style="display:inline-block;background:#667eea;color:white;padding:14px 36px;border-radius:10px;text-decoration:none;">Ingresar</a></div></div></div></body></html>"""}
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"[BREVO] ✅ Email WEB enviado a {buyer_email}. Status: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"[BREVO] ❌ Error email WEB: {e}", flush=True)

def _avisar_vendedor_credenciales(email, nombre, sticker_code, buyer_name):
    try:
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
        payload = {"sender": {"name": "levelONE", "email": "notificaciones@levelone.uno"}, "to": [{"email": email, "name": nombre}],
            "subject": f"✅ Pago aprobado de tu venta | {sticker_code}",
            "htmlContent": f"""<!DOCTYPE html><html><body style="margin:0;font-family:sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);"><div style="max-width:520px;margin:20px auto;background:white;border-radius:16px;"><div style="text-align:center;padding:24px;"><img src="https://levelone.uno/static/Logo.png" alt="levelONE" style="height:52px;margin-bottom:12px;"><h1 style="color:#667eea;">✅ Pago aprobado</h1><p>Hola <strong>{nombre}</strong>, el pago correspondiente a tu venta de la licencia <strong>{sticker_code}</strong> fue confirmado.</p></div><div style="padding:0 24px 24px;"><div style="background:#f8f9ff;border-left:4px solid #667eea;padding:16px;margin:24px 0;"><p><strong>Comprador:</strong> {buyer_name}</p><p>El pago ya fue acreditado por Mercado Pago.</p><p>Ya podés ingresar a tu dashboard y enviar las credenciales al comprador.</p></div><div style="text-align:center;"><a href="https://levelone.uno/dashboard" style="display:inline-block;background:#667eea;color:white;padding:14px 36px;border-radius:10px;text-decoration:none;">Enviar credenciales</a></div></div></div></body></html>"""}
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"[BREVO] ✅ Aviso al vendedor enviado a {email}. Status: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"[BREVO] ❌ Error aviso vendedor: {e}", flush=True)

@app.route("/marcar_enviado/<int:sticker_id>", methods=["POST"])
def marcar_enviado(sticker_id):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,)); s = cur.fetchone()
    if s and s["status"] == "pending":
        try:
            step = s["step"]; cid = s["cycle_id"]; responsable = None
            if step == 1: cur.execute("SELECT sticker_id, full_name, email, password_hash FROM users WHERE sticker_id='ADMIN001'"); responsable = cur.fetchone()
            elif step == 2: cur.execute("""SELECT u.sticker_id, u.full_name, u.email, u.password_hash FROM cycle_levels cl JOIN users u ON cl.user_id=u.id WHERE cl.cycle_id=%s AND cl.level=1 LIMIT 1""", (cid,)); responsable = cur.fetchone()
            elif step == 3: cur.execute("SELECT sticker_id, full_name, email, password_hash FROM users WHERE id=%s", (s["seller_id"],)); responsable = cur.fetchone()
            if responsable and responsable["email"]:
                app_url = request.host_url.rstrip('/') + "/dashboard"
                url = "https://api.brevo.com/v3/smtp/email"
                headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
                payload = {"sender": {"name": "levelONE", "email": "notificaciones@levelone.uno"}, "to": [{"email": responsable["email"], "name": responsable["full_name"]}],
                    "subject": f"🔔 Confirmación de pago | {s['sticker_code']}",
                    "htmlContent": f"<html><body style='font-family:sans-serif;padding:20px;'><div style='text-align:center;margin-bottom:16px;'><img src='https://levelone.uno/static/Logo.png' alt='levelONE' style='height:48px;'></div><h2>🔔 Confirmación de pago</h2><p>Hola <strong>{responsable['full_name']}</strong>, hay un pago pendiente.</p><p>Licencia: <strong>{s['sticker_code']}</strong> ({s['buyer_name']})</p><p><strong>Usuario:</strong> <code>{responsable['sticker_id']}</code></p><p><strong>Link:</strong> <a href='{app_url}'>{app_url}</a></p></body></html>"}
                requests.post(url, json=payload, headers=headers, timeout=10)
        except Exception as e: print(f"[BREVO] Error: {e}", flush=True)
        cur.execute("UPDATE stickers SET status='sent' WHERE id=%s", (sticker_id,)); conn.commit(); flash("📤 Marcado como enviado.")
    conn.close(); return redirect("/dashboard")

@app.route("/resolver_confirmacion/<int:sticker_id>/<action>", methods=["POST"])
def resolver_confirmacion(sticker_id, action):
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT * FROM stickers WHERE id=%s", (sticker_id,)); s = cur.fetchone()
        if s and s["status"] == "sent":
            if action == "confirm":
                cur.execute("UPDATE stickers SET status='confirmed' WHERE id=%s", (sticker_id,)); conn.commit(); flash("✅ Pago confirmado.")
                cur.execute("SELECT u.full_name, u.email FROM users u WHERE u.id=%s", (s["seller_id"],))
                vend = cur.fetchone()
                if vend and vend["email"]:
                    _avisar_vendedor_credenciales(vend["email"], vend["full_name"], s["sticker_code"], s["buyer_name"])
            else: cur.execute("UPDATE stickers SET status='pending' WHERE id=%s", (sticker_id,)); conn.commit(); flash("⚠️ Pago rechazado.")
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
        nuevo_cbu = request.form.get("nuevo_cbu","").strip()
        if not nuevo_cbu: flash("⚠️ CBU vacío."); conn.close(); return redirect("/dashboard")
        cur.execute("UPDATE users SET cbu_alias=%s WHERE sticker_id='ADMIN001'", (nuevo_cbu,)); conn.commit(); flash("✅ CBU actualizado.")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {str(e)}")
    finally: conn.close(); return redirect("/dashboard")

@app.route("/admin/mp_config", methods=["POST"])
def admin_mp_config():
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    try:
        cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],)); row = cur.fetchone()
        if not row or row["sticker_id"] != "ADMIN001": return redirect("/dashboard")
        enabled = request.form.get("mp_enabled") == "on"; link = request.form.get("mp_link","").strip()
        cur.execute("UPDATE users SET mp_enabled=%s, mp_payment_link=%s WHERE sticker_id='ADMIN001'", (enabled, link)); conn.commit(); flash("✅ MP actualizado.")
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
                payload = {"sender": {"name": "levelONE", "email": "notificaciones@levelone.uno"}, "to": [{"email": buyer_email, "name": buyer_name}], "subject": f"🎉 ¡BIENVENIDO/A A LEVELONE! | {sticker_code}", "htmlContent": f"""<!DOCTYPE html><html><body style="margin:0;font-family:sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);"><div style="max-width:520px;margin:20px auto;background:white;border-radius:16px;"><div style="text-align:center;padding:24px;"><img src="https://levelone.uno/static/Logo.png" alt="levelONE" style="height:52px;margin-bottom:12px;"><h1 style="color:#667eea;">🎉 ¡BIENVENIDO/A!</h1><p>Tu licencia <strong>{sticker_code}</strong> está activa ✅</p></div><div style="padding:0 24px 24px;"><div style="background:#f8f9ff;border-left:4px solid #667eea;padding:16px;margin:24px 0;"><p><strong>Usuario:</strong> <code>{sticker_code}</code></p><p><strong>Contraseña:</strong> <code>{temp_pass}</code></p><p><strong>Link:</strong> <a href="{app_url}">{app_url}</a></p></div><div style="text-align:center;"><a href="{app_url}" style="display:inline-block;background:#667eea;color:white;padding:14px 36px;border-radius:10px;text-decoration:none;">Ingresar</a></div><p style="margin-top:20px;"><a href="{app_terms_url}">Términos</a></p></div></div></body></html>"""}
                response = requests.post(url, json=payload, headers=headers, timeout=10); print(f"[BREVO] Email enviado: {response.status_code}", flush=True)
            except Exception as e: print(f"[BREVO] Error: {e}", flush=True); flash("⚠️ Email no enviado.")
            cur.execute("UPDATE stickers SET status='entregado' WHERE id=%s", (sticker_id,)); cid, sid = s["cycle_id"], s["seller_id"]
            cur.execute("SELECT COUNT(*) as cnt FROM stickers WHERE cycle_id=%s AND seller_id=%s AND status='entregado'", (cid, sid)); entregados = cur.fetchone()["cnt"]
            if entregados == 3:
                cur.execute("UPDATE cycle_levels SET is_graduated = TRUE WHERE cycle_id = %s AND level = 1", (cid,))
                cur.execute("UPDATE cycle_levels SET level = level - 1 WHERE cycle_id = %s AND level > 1", (cid,))
                cur.execute("SELECT user_id, level FROM cycle_levels WHERE cycle_id = %s", (cid,))
                for row in cur.fetchall(): cur.execute("UPDATE users SET current_level = %s WHERE id = %s", (row["level"], row["user_id"]))
                cur.execute("UPDATE cycles SET status='completed', completed_at=%s WHERE id=%s", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cid))
                flash("🎉 ¡Ciclo completado!")
            else: flash("✅ Licencia entregada.")
            conn.commit()
        else: flash("⚠️ Estado incorrecto.")
    finally: cur.close(); conn.close()
    return redirect("/dashboard")

@app.route("/logout")
def logout(): session.clear(); return redirect("/ingresar")

@app.route("/debug-rutas")
def debug_rutas():
    rutas = []
    for rule in app.url_map.iter_rules(): rutas.append(f"{sorted(rule.methods)} {rule.rule} → {rule.endpoint}")
    return "<pre>" + "<br>".join(sorted(rutas)) + "</pre>"

@app.route("/admin/cursos", methods=["GET", "POST"])
def admin_cursos():
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],)); row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")
    if request.method == "POST":
        titulo = request.form.get("titulo","").strip(); desc = request.form.get("descripcion","").strip(); img = request.form.get("imagen","").strip()
        fecha = request.form.get("fecha_inicio","").strip() or None; precio = request.form.get("precio","").strip() or None
        descuento = request.form.get("descuento","0").strip() or 0; estado = request.form.get("estado","active")
        if titulo:
            cur.execute('''INSERT INTO courses (title, description, image_url, start_date, price, discount_pct, status) VALUES (%s,%s,%s,%s,%s,%s,%s)''', (titulo, desc, img, fecha, precio, descuento, estado)); conn.commit(); flash("✅ Curso agregado.")
    cur.execute("SELECT * FROM courses ORDER BY created_at DESC"); cursos = cur.fetchall(); conn.close()
    html = """<!DOCTYPE html><html><head><title>Admin Cursos</title><style>body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;padding:40px}.card{background:#1a1a2e;padding:20px;border-radius:12px;margin-bottom:20px;border:1px solid #333}input,select,textarea{width:100%;padding:10px;margin:5px 0 15px;background:#0f0f1a;color:#fff;border:1px solid #444;border-radius:8px}button{background:#667eea;color:#fff;padding:10px 20px;border:none;border-radius:8px;cursor:pointer}table{width:100%;border-collapse:collapse;margin-top:20px}th,td{padding:12px;border-bottom:1px solid #333;text-align:left}.badge{padding:4px 8px;border-radius:4px;font-size:0.8rem}.active{background:#38a169}.inactive{background:#e53e3e}a{color:#667eea;text-decoration:none;margin-right:15px}</style></head><body>
    <h2>📚 Gestión de Cursos</h2><a href="/dashboard">← Volver</a>
    <div class="card"><form method="POST"><h3>Agregar Curso</h3><input name="titulo" placeholder="Título *" required><textarea name="descripcion" rows="2"></textarea><input name="imagen"><input name="fecha_inicio" type="date"><input name="precio" type="number" step="0.01"><input name="descuento" type="number" min="0" max="100"><select name="estado"><option value="active">Activo</option><option value="inactive">Inactivo</option></select><button type="submit">Guardar</button></form></div>
    <table><thead><tr><th>Título</th><th>Precio</th><th>Desc.</th><th>Inicio</th><th>Estado</th><th>Acción</th></tr></thead><tbody>"""
    for c in cursos:
        badge = f"<span class='badge {'active' if c['status']=='active' else 'inactive'}'>{c['status']}</span>"
        btn_color = "#e53e3e" if c['status']=='active' else "#38a169"; btn_text = "Desactivar" if c['status']=='active' else "Activar"
        html += f"<tr><td>{c['title']}</td><td>${c['price'] or '-'}</td><td>{c['discount_pct']}%</td><td>{c['start_date'] or '-'}</td><td>{badge}</td><td><a href='/admin/cursos/toggle/{c['id']}' style='background:{btn_color};color:#fff;padding:5px 10px;border-radius:4px;text-decoration:none'>{btn_text}</a></td></tr>"
    html += "</tbody></table></body></html>"
    return render_template_string(html)

@app.route("/admin/cursos/toggle/<int:course_id>")
def toggle_curso(course_id):
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],)); row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")
    cur.execute("UPDATE courses SET status = CASE WHEN status='active' THEN 'inactive' ELSE 'active' END WHERE id=%s", (course_id,)); conn.commit(); conn.close()
    flash("✅ Estado actualizado."); return redirect("/admin/cursos")

@app.route("/admin/reset_password/<int:user_id>", methods=["POST"])
def admin_reset_password(user_id):
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],)); row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")
    cur.execute("SELECT sticker_id, full_name, email FROM users WHERE id=%s", (user_id,)); target = cur.fetchone()
    if not target: conn.close(); flash("❌ No encontrado."); return redirect(request.referrer or "/dashboard")
    new_pass = "Temp-" + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
    cur.execute("UPDATE users SET password_hash=%s WHERE id=%s", (generate_password_hash(new_pass, method='pbkdf2:sha256'), user_id)); conn.commit()
    try:
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
        payload = {"sender": {"name": "levelONE", "email": "notificaciones@levelone.uno"}, "to": [{"email": target["email"], "name": target["full_name"]}], "subject": f"🔐 Contraseña actualizada | {target['sticker_id']}", "htmlContent": f"<html><body><div style='text-align:center;margin-bottom:16px;'><img src='https://levelone.uno/static/Logo.png' alt='levelONE' style='height:48px;'></div><h2>🔐 Nueva clave</h2><p>Hola {target['full_name']}, tu clave: <strong>{new_pass}</strong></p><p><a href='https://levelone.uno/ingresar'>Ingresar</a></p></body></html>"}
        requests.post(url, json=payload, headers=headers, timeout=10)
    except: pass
    conn.close(); flash(f"✅ Clave: {new_pass}"); return redirect(request.referrer or "/admin/red")

@app.route("/admin/edit_user/<int:user_id>", methods=["GET", "POST"])
def admin_edit_user(user_id):
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],)); row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")
    cur.execute("SELECT sticker_id, full_name, phone, email, address, cbu_alias FROM users WHERE id=%s", (user_id,)); user = cur.fetchone()
    if not user: conn.close(); return redirect("/admin/red")
    if request.method == "POST":
        new_name = request.form.get("full_name","").strip(); new_phone = request.form.get("phone","").strip(); new_email = request.form.get("email","").strip()
        new_address = request.form.get("address","").strip(); new_cbu = request.form.get("cbu_alias","").strip()
        if not all([new_name, new_phone, new_email]): conn.close(); flash("❌ Faltan datos."); return redirect("/admin/red")
        new_pass = "Temp-" + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        cur.execute('''UPDATE users SET full_name=%s, phone=%s, email=%s, address=%s, cbu_alias=%s, password_hash=%s WHERE id=%s''', (new_name, new_phone, new_email, new_address, new_cbu, generate_password_hash(new_pass, method='pbkdf2:sha256'), user_id)); conn.commit()
        try:
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {"accept": "application/json", "content-type": "application/json", "api-key": os.environ.get("BREVO_API_KEY")}
            payload = {"sender": {"name": "levelONE", "email": "notificaciones@levelone.uno"}, "to": [{"email": new_email, "name": new_name}], "subject": f"📝 Datos actualizados | {user['sticker_id']}", "htmlContent": f"<html><body><div style='text-align:center;margin-bottom:16px;'><img src='https://levelone.uno/static/Logo.png' alt='levelONE' style='height:48px;'></div><h2>📝 Actualizado</h2><p>Hola {new_name}, tu clave: <strong>{new_pass}</strong></p></body></html>"}
            requests.post(url, json=payload, headers=headers, timeout=10)
        except: pass
        conn.close(); flash(f"✅ Actualizado. Clave: {new_pass}"); return redirect("/admin/red")
    conn.close()
    return render_template_string(f"""<!DOCTYPE html><html><head><title>Editar</title><style>body{{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;padding:40px}}.card{{background:#1a1a2e;padding:25px;border-radius:12px}}input{{width:100%;padding:10px;margin:5px 0 15px;background:#0f0f1a;color:#fff;border:1px solid #444;border-radius:8px}}button{{background:#667eea;color:#fff;padding:12px 24px;border:none;border-radius:8px}}a{{color:#667eea}}</style></head><body><h2>✏️ Editar</h2><a href="/admin/red">← Volver</a><div class="card"><form method="POST"><label>Nombre</label><input name="full_name" value="{user['full_name'] or ''}" required><label>Teléfono</label><input name="phone" value="{user['phone'] or ''}" required><label>Email</label><input name="email" value="{user['email'] or ''}" required><label>Dirección</label><input name="address" value="{user['address'] or ''}"><label>CBU</label><input name="cbu_alias" value="{user['cbu_alias'] or ''}"><button type="submit">💾 Guardar</button></form></div></body></html>""")

@app.route("/admin/red")
def admin_red():
    if "user_id" not in session: return redirect("/ingresar")
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],)); row = cur.fetchone()
    if not row or row["sticker_id"] != "ADMIN001": conn.close(); return redirect("/dashboard")
    query = request.args.get("q","").strip()
    target = None; ancestors = []; descendants = []; sin_ciclo = False; niveles_candidatos = []
    try:
        if query:
            cur.execute("SELECT id, sticker_id, full_name, phone, current_level, password_hash, role FROM users WHERE sticker_id ILIKE %s OR full_name ILIKE %s LIMIT 1", (f"%{query}%", f"%{query}%"))
            target = cur.fetchone()
            if target:
                tid = target["id"]
                try:
                    cur.execute("SELECT cycle_id, level FROM cycle_levels WHERE user_id=%s ORDER BY id DESC LIMIT 1", (tid,)); user_cycle = cur.fetchone()
                    if user_cycle and user_cycle["cycle_id"]:
                        cycle_id = user_cycle["cycle_id"]; ul = user_cycle["level"] or 5
                        for tl in range(4, 0, -1):
                            if tl >= ul: continue
                            niveles_candidatos.append(tl)
                            try:
                                cur.execute("""SELECT u.id, u.sticker_id, u.full_name, u.phone, u.current_level FROM cycle_levels cl JOIN users u ON cl.user_id=u.id WHERE cl.cycle_id=%s AND cl.level=%s""", (cycle_id, tl))
                                ad = cur.fetchone()
                                if ad: a = dict(ad); a["nivel_ciclo"] = tl; ancestors.append(a)
                            except: continue
                    else:
                        sin_ciclo = True; current = tid; niveles_candidatos = [4,3,2,1]
                        for tl in [4,3,2,1]:
                            cur.execute("SELECT parent_id FROM referral_tree WHERE child_id=%s", (current,)); up = cur.fetchone()
                            if not up or not up["parent_id"]: break
                            pid = up["parent_id"]
                            cur.execute("SELECT id, sticker_id, full_name, phone, current_level FROM users WHERE id=%s", (pid,)); pd = cur.fetchone()
                            if not pd: break
                            a = dict(pd); a["nivel_ciclo"] = tl; ancestors.append(a)
                            if pd["sticker_id"] == "ADMIN001": break
                            current = pid
                        if not any(x.get("nivel_ciclo") == 1 for x in ancestors):
                            cur.execute("SELECT id, sticker_id, full_name, phone, current_level FROM users WHERE sticker_id='ADMIN001'"); ad = cur.fetchone()
                            if ad: a = dict(ad); a["nivel_ciclo"] = 1; a["full_name"] = "🏢 Plataforma"; ancestors.append(a)
                except Exception as e: print(f"[DEBUG] Error: {e}", flush=True)
                try:
                    queue = [(tid, 1, target["sticker_id"])]; visited = set()
                    while queue and len(descendants) < 50:
                        pid, depth, pstk = queue.pop(0)
                        if depth > 3 or pid in visited: continue
                        visited.add(pid)
                        cur.execute("SELECT child_id FROM referral_tree WHERE parent_id=%s", (pid,))
                        for r in cur.fetchall():
                            cid = r["child_id"]
                            if cid and cid not in visited:
                                cur.execute("SELECT id, sticker_id, full_name, phone, current_level, password_hash FROM users WHERE id=%s", (cid,)); cd = cur.fetchone()
                                if cd:
                                    descendants.append({"nivel": depth, "padre_stk": pstk, "data": dict(cd)})
                                    if depth < 3: queue.append((cid, depth+1, cd["sticker_id"]))
                except Exception as e: print(f"[DEBUG] Error: {e}", flush=True)
    except Exception as e: print(f"[DEBUG] Error: {e}", flush=True); flash(f"⚠️ Error: {str(e)}")
    finally: conn.close()
    def user_buttons(uid2, uname):
        return f"""<div style="display:flex;gap:8px;margin-top:8px;"><a href="/admin/edit_user/{uid2}" style="background:#38a169;color:#fff;padding:5px 10px;border-radius:4px;text-decoration:none;font-size:0.8rem;">✏️ Gestionar</a><a href="/admin/reset_password/{uid2}" onclick="return confirm('¿Resetear?')" style="background:#f6e05e;color:#1a1a2e;padding:5px 10px;border-radius:4px;text-decoration:none;font-size:0.8rem;">🔑 Reset</a></div>"""
    html = """<!DOCTYPE html><html><head><title>Admin Red</title><style>body{font-family:Inter,sans-serif;background:#0a0a0a;color:#fff;padding:40px}.search{display:flex;gap:10px;margin-bottom:30px}input{flex:1;padding:12px;background:#1a1a2e;color:#fff;border:1px solid #444;border-radius:8px}button{background:#667eea;color:#fff;padding:12px 24px;border:none;border-radius:8px}.section{margin-bottom:30px}.section h3{color:#667eea;margin-bottom:15px}.node{margin-bottom:10px;padding:10px;background:#0f0f1a;border-radius:8px}.vacante{margin-bottom:10px;padding:10px;background:#0f0f1a;border-radius:8px;border:1px dashed #444;opacity:0.6}.info{font-size:0.9rem;color:#a0aec0}.info span{color:#fff;font-weight:600}a{color:#667eea;text-decoration:none}code{background:#1a1a2e;padding:2px 5px;border-radius:3px}</style></head><body><h2>🌳 Visor de Ciclo</h2><a href="/dashboard">← Volver</a><form method="GET" class="search"><input name="q" placeholder="Buscar..." value=\"""" + query + """"><button type="submit">Buscar</button></form>"""
    if target:
        pwd_display = target['password_hash'][:15] + "..." if target['password_hash'] else "No definida"
        html += f"""<div class="section" style="background:#1a1a2e;padding:25px;border-radius:12px;border:2px solid #667eea;text-align:center;"><h3>🎯 Buscado</h3><div class="info"><span>{target['full_name']}</span> | STK: {target['sticker_id']}<br>Tel: {target['phone']} | Nivel: {target['current_level']}</div><div class="info">Pass: <code style="color:#f6e05e">{pwd_display}</code></div>{user_buttons(target['id'], target['full_name'])}</div>"""
        if niveles_candidatos:
            titulo_asc = "🔝 Ascendientes del Ciclo" if not sin_ciclo else "🔝 Ascendientes (referidos)"
            html += f'<div class="section"><h3>{titulo_asc}</h3>'
            by_level = {a["nivel_ciclo"]: a for a in ancestors}
            for lvl in niveles_candidatos:
                a = by_level.get(lvl)
                if a: html += f"""<div class="node"><div class="info"><span>{a['full_name']}</span> | STK: {a['sticker_id']} | Nivel ciclo: {lvl}</div>{user_buttons(a['id'], a['full_name'])}</div>"""
                else: html += f"""<div class="vacante"><div class="info">— Vacante — | Nivel ciclo: {lvl}</div></div>"""
            html += '</div>'
        html += '<div class="section"><h3>🔽 Red de Ventas</h3>'
        if not descendants: html += '<p class="info">No hay descendientes.</p>'
        else:
            for d in descendants:
                u2 = d["data"]; pwd_disp = u2['password_hash'][:15] + "..." if u2['password_hash'] else "No definida"
                nl = {1: "👤 Hijo", 2: "👶 Nieto", 3: "👣 Bisnieto"}.get(d["nivel"], "Descendiente")
                html += f"""<div class="node"><div class="info">{nl} (Vendido por: {d['padre_stk']})</div><div class="info">STK: {u2['sticker_id']} | {u2['full_name']}</div><div class="info">Pass: <code style="color:#f6e05e">{pwd_disp}</code></div>{user_buttons(u2['id'], u2['full_name'])}</div>"""
        html += '</div>'
    elif query: html += "<p style='color:#e53e3e'>❌ No encontrado.</p>"
    html += "</body></html>"
    return render_template_string(html)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
