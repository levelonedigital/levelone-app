# =============================================================================
# cursos.py - MÓDULO INDEPENDIENTE DE CURSOS (Blueprint)
# Todo lo relacionado a cursos vive acá. NO toca el sistema de referidos.
# =============================================================================
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, date
from functools import wraps
from io import BytesIO
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file, abort)

cursos_bp = Blueprint('cursos', __name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def get_cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def login_requerido(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/ingresar")
        return f(*args, **kwargs)
    return wrapper

def admin_requerido(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session: return redirect("/ingresar")
        conn = get_db(); cur = get_cur(conn)
        cur.execute("SELECT sticker_id FROM users WHERE id=%s", (session["user_id"],))
        r = cur.fetchone(); conn.close()
        if not r or r["sticker_id"] != "ADMIN001": return redirect("/portal")
        return f(*args, **kwargs)
    return wrapper

def _es_admin(cur, user_id):
    cur.execute("SELECT sticker_id FROM users WHERE id=%s", (user_id,))
    r = cur.fetchone()
    return bool(r and r["sticker_id"] == "ADMIN001")

def _fecha(v):
    if not v: return None
    try: return datetime.strptime(v, "%Y-%m-%d").date()
    except Exception: return None

def _num(v, default=None):
    try: return float(v) if v not in (None, "") else default
    except Exception: return default

def _youtube_embed(url):
    if not url: return ""
    if "embed/" in url: return url
    if "watch?v=" in url: return url.replace("watch?v=", "embed/")
    if "youtu.be/" in url: return url.replace("youtu.be/", "www.youtube.com/embed/")
    return url

def _inscripto(cur, user_id, course_id):
    cur.execute("SELECT id FROM course_enrollments WHERE user_id=%s AND course_id=%s AND status='active'", (user_id, course_id))
    return cur.fetchone() is not None

def init_db_cursos():
    """Crea tablas de cursos y agrega columnas nuevas SIN tocar las existentes."""
    conn = get_db(); cur = get_cur(conn)
    alters = [
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS end_date DATE",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS price_regular DECIMAL(10,2)",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS price_levelone DECIMAL(10,2)",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS has_exam BOOLEAN DEFAULT FALSE",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS exam_pass_score INTEGER DEFAULT 70",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS exam_attempts INTEGER DEFAULT 3",
        "ALTER TABLE exam_questions ADD COLUMN IF NOT EXISTS lesson_id INTEGER",
    ]
    for a in alters:
        try:
            cur.execute(a)
        except Exception:
            conn.rollback()
    cur.execute('''CREATE TABLE IF NOT EXISTS lessons (
        id SERIAL PRIMARY KEY,
        course_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content_type TEXT DEFAULT 'text',
        content_url TEXT,
        content_text TEXT,
        pdf_data BYTEA,
        pdf_filename TEXT,
        order_idx INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS exam_questions (
        id SERIAL PRIMARY KEY,
        course_id INTEGER NOT NULL,
        lesson_id INTEGER,
        question TEXT NOT NULL,
        option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
        correct_option TEXT DEFAULT 'A',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS course_enrollments (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        payment_id TEXT,
        status TEXT DEFAULT 'active',
        UNIQUE(user_id, course_id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS exam_results (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        lesson_id INTEGER,
        score INTEGER DEFAULT 0,
        passed BOOLEAN DEFAULT FALSE,
        attempts INTEGER DEFAULT 0,
        taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    print("✅ DB de Cursos inicializada.", flush=True)
    conn.close()

# =============================================================================
# PORTAL DE SELECCIÓN (post-login)
# =============================================================================
@cursos_bp.route("/portal")
@login_requerido
def portal():
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT sticker_id, role, full_name FROM users WHERE id=%s", (session["user_id"],))
    u = cur.fetchone(); conn.close()
    is_admin = bool(u and u["sticker_id"] == "ADMIN001")
    return render_template("portal.html", is_admin=is_admin, user=u)

# =============================================================================
# CATÁLOGO DE CURSOS DEL ALUMNO (solo ve ACTIVOS)
# =============================================================================
@cursos_bp.route("/cursos")
@login_requerido
def catalogo():
    conn = get_db(); cur = get_cur(conn)
    hoy = date.today()
    cur.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM course_enrollments e WHERE e.course_id=c.id AND e.user_id=%s AND e.status='active') AS inscrito
        FROM courses c
        WHERE c.status='active'
          AND (c.start_date IS NULL OR c.start_date <= %s)
          AND (c.end_date IS NULL OR c.end_date >= %s)
        ORDER BY c.start_date ASC
    """, (session["user_id"], hoy, hoy))
    cursos = [dict(r) for r in cur.fetchall()]
    conn.close()
    for c in cursos:
        c["es_gratis"] = (not c.get("price_levelone")) or float(c["price_levelone"] or 0) == 0
    return render_template("cursos_catalogo.html", cursos=cursos)

# =============================================================================
# VISTA DEL CURSO (alumno inscripto O admin sin inscripción)
# =============================================================================
@cursos_bp.route("/curso/<int:cid>")
@login_requerido
def curso_detalle(cid):
    conn = get_db(); cur = get_cur(conn)
    es_admin = _es_admin(cur, session["user_id"])
    if es_admin:
        cur.execute("SELECT * FROM courses WHERE id=%s", (cid,))
    else:
        cur.execute("SELECT * FROM courses WHERE id=%s AND status='active'", (cid,))
    curso = cur.fetchone()
    if not curso:
        conn.close(); flash("⚠️ Curso no disponible."); return redirect("/cursos")
    inscrito = _inscripto(cur, session["user_id"], cid) or es_admin
    lecciones = []
    if inscrito:
        cur.execute("SELECT id,title,content_type,order_idx FROM lessons WHERE course_id=%s ORDER BY order_idx", (cid,))
        lecciones = cur.fetchall()
    conn.close()
    es_gratis = (not curso.get("price_levelone")) or float(curso["price_levelone"] or 0) == 0
    return render_template("curso_detalle.html", curso=curso, inscrito=inscrito, lecciones=lecciones, es_gratis=es_gratis)

@cursos_bp.route("/curso/<int:cid>/inscribir", methods=["POST"])
@login_requerido
def curso_inscribir(cid):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT price_levelone FROM courses WHERE id=%s", (cid,)); c = cur.fetchone()
    if not c or (c["price_levelone"] and float(c["price_levelone"]) > 0):
        conn.close(); flash("⚠️ Este curso es pago."); return redirect(f"/curso/{cid}")
    cur.execute("INSERT INTO course_enrollments (user_id,course_id) VALUES (%s,%s) ON CONFLICT (user_id,course_id) DO NOTHING",
        (session["user_id"], cid))
    conn.commit(); conn.close()
    flash("✅ Te inscribiste al curso. ¡A aprender!")
    return redirect(f"/curso/{cid}")

@cursos_bp.route("/curso/<int:cid>/leccion/<int:lid>")
@login_requerido
def curso_leccion(cid, lid):
    conn = get_db(); cur = get_cur(conn)
    if not (_inscripto(cur, session["user_id"], cid) or _es_admin(cur, session["user_id"])):
        conn.close(); flash("⚠️ Debes inscribirte al curso primero."); return redirect(f"/curso/{cid}")
    cur.execute("SELECT * FROM courses WHERE id=%s", (cid,)); curso = cur.fetchone()
    cur.execute("SELECT * FROM lessons WHERE id=%s AND course_id=%s", (lid, cid)); leccion = cur.fetchone()
    if not leccion:
        conn.close(); flash("⚠️ Lección no encontrada."); return redirect(f"/curso/{cid}")
    cur.execute("SELECT id,title,order_idx FROM lessons WHERE course_id=%s ORDER BY order_idx", (cid,))
    todas = cur.fetchall(); conn.close()
    idx = next((i for i,l in enumerate(todas) if l["id"]==lid), 0)
    prev = todas[idx-1]["id"] if idx > 0 else None
    nxt  = todas[idx+1]["id"] if idx < len(todas)-1 else None
    leccion = dict(leccion)
    leccion["video_embed"] = _youtube_embed(leccion.get("content_url"))
    return render_template("curso_leccion.html", curso=curso, leccion=leccion, prev=prev, nxt=nxt, cid=cid)

@cursos_bp.route("/curso/<int:cid>/leccion/<int:lid>/pdf")
@login_requerido
def curso_leccion_pdf(cid, lid):
    conn = get_db(); cur = get_cur(conn)
    if not (_inscripto(cur, session["user_id"], cid) or _es_admin(cur, session["user_id"])):
        conn.close(); abort(403)
    cur.execute("SELECT pdf_data, pdf_filename FROM lessons WHERE id=%s AND course_id=%s", (lid, cid))
    l = cur.fetchone(); conn.close()
    if not l or not l["pdf_data"]: abort(404)
    return send_file(BytesIO(l["pdf_data"]), mimetype="application/pdf",
                     download_name=l["pdf_filename"] or "documento.pdf")

# =============================================================================
# GESTIÓN DE CURSOS (ADMIN)
# =============================================================================
@cursos_bp.route("/admin/cursos2")
@admin_requerido
def admin_cursos2():
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM courses ORDER BY created_at DESC")
    cursos = cur.fetchall(); conn.close()
    return render_template("admin_cursos2.html", cursos=cursos)

@cursos_bp.route("/admin/cursos2/crear", methods=["POST"])
@admin_requerido
def admin_cursos2_crear():
    conn = get_db(); cur = get_cur(conn)
    pr = _num(request.form.get("price_regular"), 0) or 0
    pl = _num(request.form.get("price_levelone"), 0) or 0
    disc = int(round((1 - pl/pr)*100)) if pr > 0 else 0
    # Los cursos NUEVOS se crean siempre INACTIVOS (revisión antes de publicar)
    cur.execute("""INSERT INTO courses (title, description, image_url, start_date, end_date,
                   price, discount_pct, price_regular, price_levelone, has_exam, exam_pass_score, exam_attempts, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'inactive')""",
        (request.form.get("title","").strip(), request.form.get("description","").strip(),
         request.form.get("image_url","").strip(), _fecha(request.form.get("start_date")), _fecha(request.form.get("end_date")),
         pr, disc, pr, pl, request.form.get("has_exam")=="on",
         int(request.form.get("exam_pass_score") or 70), int(request.form.get("exam_attempts") or 3)))
    conn.commit(); conn.close()
    flash("✅ Curso creado como INACTIVO. Previsualizalo y activalo cuando esté listo.")
    return redirect("/admin/cursos2")

@cursos_bp.route("/admin/cursos2/toggle/<int:cid>", methods=["POST"])
@admin_requerido
def admin_cursos2_toggle(cid):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT status FROM courses WHERE id=%s", (cid,)); c = cur.fetchone()
    if not c:
        conn.close(); return redirect("/admin/cursos2")
    nuevo = 'inactive' if c["status"] == 'active' else 'active'
    cur.execute("UPDATE courses SET status=%s WHERE id=%s", (nuevo, cid))
    conn.commit(); conn.close()
    flash("🟢 Curso ACTIVADO: ya lo ven los alumnos." if nuevo == 'active'
          else "🔴 Curso DESACTIVADO: solo lo ve el admin.")
    return redirect("/admin/cursos2")

@cursos_bp.route("/admin/cursos2/editar/<int:cid>", methods=["GET","POST"])
@admin_requerido
def admin_cursos2_editar(cid):
    conn = get_db(); cur = get_cur(conn)
    if request.method == "POST":
        pr = _num(request.form.get("price_regular"), 0) or 0
        pl = _num(request.form.get("price_levelone"), 0) or 0
        disc = int(round((1 - pl/pr)*100)) if pr > 0 else 0
        cur.execute("""UPDATE courses SET title=%s, description=%s, image_url=%s, start_date=%s, end_date=%s,
                       price=%s, discount_pct=%s, price_regular=%s, price_levelone=%s, has_exam=%s,
                       exam_pass_score=%s, exam_attempts=%s, status=%s WHERE id=%s""",
            (request.form.get("title","").strip(), request.form.get("description","").strip(),
             request.form.get("image_url","").strip(), _fecha(request.form.get("start_date")), _fecha(request.form.get("end_date")),
             pr, disc, pr, pl, request.form.get("has_exam")=="on",
             int(request.form.get("exam_pass_score") or 70), int(request.form.get("exam_attempts") or 3),
             request.form.get("status","active"), cid))
        conn.commit(); conn.close()
        flash("✅ Curso actualizado.")
        return redirect("/admin/cursos2")
    cur.execute("SELECT * FROM courses WHERE id=%s", (cid,)); c = cur.fetchone(); conn.close()
    return render_template("admin_curso_editar.html", c=c)

@cursos_bp.route("/admin/cursos2/eliminar/<int:cid>", methods=["POST"])
@admin_requerido
def admin_cursos2_eliminar(cid):
    conn = get_db(); cur = get_cur(conn)
    for t in ["lessons","exam_questions","course_enrollments","exam_results"]:
        cur.execute(f"DELETE FROM {t} WHERE course_id=%s", (cid,))
    cur.execute("DELETE FROM courses WHERE id=%s", (cid,))
    conn.commit(); conn.close()
    flash("🗑️ Curso eliminado.")
    return redirect("/admin/cursos2")

# ---------- LECCIONES ----------
@cursos_bp.route("/admin/cursos2/lecciones/<int:cid>")
@admin_requerido
def admin_lecciones(cid):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM courses WHERE id=%s", (cid,)); curso = cur.fetchone()
    cur.execute("SELECT id,title,content_type,order_idx,pdf_filename FROM lessons WHERE course_id=%s ORDER BY order_idx", (cid,))
    lecciones = cur.fetchall(); conn.close()
    return render_template("admin_lecciones.html", curso=curso, lecciones=lecciones)

@cursos_bp.route("/admin/cursos2/lecciones/agregar", methods=["POST"])
@admin_requerido
def admin_lecciones_agregar():
    cid = int(request.form.get("course_id"))
    pdf_data = None; pdf_filename = None
    f = request.files.get("pdf_file")
    if f and f.filename:
        pdf_data = f.read(); pdf_filename = f.filename
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT COALESCE(MAX(order_idx),0)+1 AS n FROM lessons WHERE course_id=%s", (cid,))
    n = cur.fetchone()["n"]
    cur.execute("""INSERT INTO lessons (course_id,title,content_type,content_url,content_text,pdf_data,pdf_filename,order_idx)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (cid, request.form.get("title","").strip(), request.form.get("content_type","text"),
         request.form.get("content_url","").strip(), request.form.get("content_text","").strip(),
         pdf_data, pdf_filename, n))
    conn.commit(); conn.close()
    flash("✅ Lección agregada.")
    return redirect(f"/admin/cursos2/lecciones/{cid}")

@cursos_bp.route("/admin/cursos2/lecciones/editar/<int:lid>", methods=["GET","POST"])
@admin_requerido
def admin_lecciones_editar(lid):
    conn = get_db(); cur = get_cur(conn)
    if request.method == "POST":
        f = request.files.get("pdf_file")
        if f and f.filename:
            pdf_data = f.read(); pdf_filename = f.filename
            cur.execute("""UPDATE lessons SET title=%s, content_type=%s, content_url=%s, content_text=%s,
                           pdf_data=%s, pdf_filename=%s WHERE id=%s""",
                (request.form.get("title","").strip(), request.form.get("content_type","text"),
                 request.form.get("content_url","").strip(), request.form.get("content_text","").strip(),
                 pdf_data, pdf_filename, lid))
        else:
            cur.execute("""UPDATE lessons SET title=%s, content_type=%s, content_url=%s, content_text=%s WHERE id=%s""",
                (request.form.get("title","").strip(), request.form.get("content_type","text"),
                 request.form.get("content_url","").strip(), request.form.get("content_text","").strip(), lid))
        conn.commit()
        cur.execute("SELECT course_id FROM lessons WHERE id=%s", (lid,)); r = cur.fetchone(); conn.close()
        flash("✅ Lección actualizada.")
        return redirect(f"/admin/cursos2/lecciones/{r['course_id']}")
    cur.execute("SELECT * FROM lessons WHERE id=%s", (lid,)); l = cur.fetchone(); conn.close()
    return render_template("admin_leccion_editar.html", l=l)

@cursos_bp.route("/admin/cursos2/lecciones/eliminar/<int:lid>", methods=["POST"])
@admin_requerido
def admin_lecciones_eliminar(lid):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT course_id FROM lessons WHERE id=%s", (lid,)); r = cur.fetchone()
    cur.execute("DELETE FROM exam_questions WHERE lesson_id=%s", (lid,))
    cur.execute("DELETE FROM lessons WHERE id=%s", (lid,))
    conn.commit(); cid = r["course_id"] if r else 0; conn.close()
    flash("🗑️ Lección eliminada.")
    return redirect(f"/admin/cursos2/lecciones/{cid}")

# ---------- EXAMEN FINAL ----------
@cursos_bp.route("/admin/cursos2/preguntas/<int:cid>")
@admin_requerido
def admin_preguntas(cid):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM courses WHERE id=%s", (cid,)); curso = cur.fetchone()
    cur.execute("SELECT * FROM exam_questions WHERE course_id=%s AND lesson_id IS NULL ORDER BY id", (cid,))
    preguntas = cur.fetchall(); conn.close()
    return render_template("admin_preguntas.html", curso=curso, preguntas=preguntas, leccion=None)

@cursos_bp.route("/admin/cursos2/preguntas/agregar", methods=["POST"])
@admin_requerido
def admin_preguntas_agregar():
    cid = int(request.form.get("course_id"))
    conn = get_db(); cur = get_cur(conn)
    cur.execute("""INSERT INTO exam_questions (course_id,lesson_id,question,option_a,option_b,option_c,option_d,correct_option)
                   VALUES (%s,NULL,%s,%s,%s,%s,%s,%s)""",
        (cid, request.form.get("question","").strip(), request.form.get("option_a","").strip(),
         request.form.get("option_b","").strip(), request.form.get("option_c","").strip(),
         request.form.get("option_d","").strip(), request.form.get("correct_option","A")))
    conn.commit(); conn.close()
    flash("✅ Pregunta agregada al examen final.")
    return redirect(f"/admin/cursos2/preguntas/{cid}")

# ---------- EXAMEN POR LECCIÓN ----------
@cursos_bp.route("/admin/cursos2/preguntas_leccion/<int:lid>")
@admin_requerido
def admin_preguntas_leccion(lid):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT * FROM lessons WHERE id=%s", (lid,)); leccion = cur.fetchone()
    cur.execute("SELECT * FROM courses WHERE id=%s", (leccion["course_id"],)); curso = cur.fetchone()
    cur.execute("SELECT * FROM exam_questions WHERE lesson_id=%s ORDER BY id", (lid,))
    preguntas = cur.fetchall(); conn.close()
    return render_template("admin_preguntas.html", curso=curso, preguntas=preguntas, leccion=leccion)

@cursos_bp.route("/admin/cursos2/preguntas_leccion/agregar", methods=["POST"])
@admin_requerido
def admin_preguntas_leccion_agregar():
    lid = int(request.form.get("lesson_id"))
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT course_id FROM lessons WHERE id=%s", (lid,)); r = cur.fetchone()
    cur.execute("""INSERT INTO exam_questions (course_id,lesson_id,question,option_a,option_b,option_c,option_d,correct_option)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (r["course_id"], lid, request.form.get("question","").strip(), request.form.get("option_a","").strip(),
         request.form.get("option_b","").strip(), request.form.get("option_c","").strip(),
         request.form.get("option_d","").strip(), request.form.get("correct_option","A")))
    conn.commit(); conn.close()
    flash("✅ Pregunta de lección agregada.")
    return redirect(f"/admin/cursos2/preguntas_leccion/{lid}")

# ---------- ELIMINAR PREGUNTA (final o lección) ----------
@cursos_bp.route("/admin/cursos2/preguntas/eliminar/<int:pid>", methods=["POST"])
@admin_requerido
def admin_preguntas_eliminar(pid):
    conn = get_db(); cur = get_cur(conn)
    cur.execute("SELECT course_id, lesson_id FROM exam_questions WHERE id=%s", (pid,)); r = cur.fetchone()
    cur.execute("DELETE FROM exam_questions WHERE id=%s", (pid,))
    conn.commit(); conn.close()
    flash("🗑️ Pregunta eliminada.")
    if r and r["lesson_id"]: return redirect(f"/admin/cursos2/preguntas_leccion/{r['lesson_id']}")
    return redirect(f"/admin/cursos2/preguntas/{r['course_id'] if r else 0}")
