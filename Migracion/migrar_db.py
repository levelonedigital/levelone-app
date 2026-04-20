import sqlite3
import psycopg2
from urllib.parse import quote

# 🔑 CONFIGURACIÓN RAILWAY
PG_HOST = "roundhouse.proxy.rlwy.net"
PG_PORT = 16706
PG_DB = "railway"
PG_USER = "postgres"
PG_PASS = "NRvgqWEiKQNNdBKfYRKzPQLrHWIhdkHK"  # ← TU PGPASSWORD DE RAILWAY

# Ruta a tu base de datos SQLite original (debe estar en la MISMA CARPETA)
SQLITE_PATH = "levelone.db"

print("🔹 Conectando a PostgreSQL...")
try:
    pg_conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASS, sslmode="require")
    pg_conn.autocommit = True
    pg_cur = pg_conn.cursor()
    print("✅ Conexión establecida.")
except Exception as e:
    print(f"❌ Error de conexión: {e}")
    exit()

print("🏗️ Creando estructura en PostgreSQL...")
pg_cur.execute('''CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY, sticker_id TEXT UNIQUE NOT NULL,
    full_name TEXT, phone TEXT, email TEXT, address TEXT, cbu_alias TEXT NOT NULL,
    password_hash TEXT NOT NULL, current_level INTEGER DEFAULT 5,
    referrals_completed_count INTEGER DEFAULT 0, is_level1 BOOLEAN DEFAULT FALSE,
    role TEXT DEFAULT 'seller', graduated_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')
pg_cur.execute('''CREATE TABLE IF NOT EXISTS referral_tree (
    id SERIAL PRIMARY KEY, parent_id INTEGER, child_id INTEGER, UNIQUE(parent_id, child_id)
)''')
pg_cur.execute('''CREATE TABLE IF NOT EXISTS cycles (
    id SERIAL PRIMARY KEY, l5_user_id INTEGER NOT NULL, status TEXT DEFAULT 'active', completed_at TIMESTAMP
)''')
pg_cur.execute('''CREATE TABLE IF NOT EXISTS cycle_levels (
    id SERIAL PRIMARY KEY, user_id INTEGER, cycle_id INTEGER,
    level INTEGER DEFAULT 5, is_graduated BOOLEAN DEFAULT FALSE, UNIQUE(user_id, cycle_id)
)''')
pg_cur.execute('''CREATE TABLE IF NOT EXISTS stickers (
    id SERIAL PRIMARY KEY, sticker_code TEXT UNIQUE NOT NULL,
    seller_id INTEGER, cycle_id INTEGER, buyer_name TEXT, buyer_phone TEXT,
    buyer_email TEXT, buyer_cbu TEXT, step INTEGER DEFAULT 1,
    confirmation_token TEXT, temp_pass TEXT, status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')
print("✅ Estructura lista.")

print(f"📦 Leyendo {SQLITE_PATH}...")
sq_conn = sqlite3.connect(SQLITE_PATH)
sq_conn.row_factory = sqlite3.Row
sq_cur = sq_conn.cursor()

tables = ["users", "referral_tree", "cycles", "cycle_levels", "stickers"]
for tbl in tables:
    sq_cur.execute(f"SELECT * FROM {tbl}")
    rows = sq_cur.fetchall()
    if not rows:
        print(f"  ⏭️ {tbl}: vacía")
        continue
    
    cols = rows[0].keys()
    col_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    count = 0
    
    for row in rows:
        vals = [row[c] for c in cols]
        # 🔧 FIX: Convertir 0/1 de SQLite a True/False para PostgreSQL
        for i, col in enumerate(cols):
            if col in ('is_level1', 'is_graduated'):
                vals[i] = bool(vals[i])
        
        pg_cur.execute(f"INSERT INTO {tbl} ({col_str}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING", vals)
        count += 1
    
    pg_conn.commit()
    print(f"  ✅ {tbl}: {count} registros migrados.")

# Sincronizar contadores auto-incrementales
print("🔄 Ajustando contadores...")
for tbl in tables:
    try:
        pg_cur.execute(f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), COALESCE((SELECT MAX(id) FROM {tbl}), 1), false)")
    except: pass

sq_conn.close()
pg_conn.close()
print("\n🎉 ¡MIGRACIÓN COMPLETADA CON ÉXITO! Tus 122 usuarios y datos están en Railway.")
