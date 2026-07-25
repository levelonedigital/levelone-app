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
    <h1>📄 Bases y Condiciones de Uso</h1><p>Última actualización: Abril 2026. Bienven
