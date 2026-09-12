# =============================================================================
# cursos.py - MÓDULO INDEPENDIENTE DE CURSOS (Blueprint)
# Todo lo relacionado a cursos vive acá. NO toca el sistema de referidos.
# =============================================================================
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, date
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

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

def init_db_cursos():
    """Crea las tablas de cursos y agrega columnas nuevas a la tabla courses SIN tocar las existentes."""
    conn = get_db(); cur = get_cur(conn)
    alters = [
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS end_date DATE",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS price_regular DECIMAL(10,2)",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS price_levelone DECIMAL(10,2)",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS has_exam BOOLEAN DEFAULT FALSE",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS exam_pass_score INTEGER DEFAULT 70",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS exam_attempts INTEGER DEFAULT 3",
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
# CATÁLOGO DE CURSOS DEL ALUMNO
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
