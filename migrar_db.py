import sqlite3
import psycopg2
import os
from urllib.parse import urlparse

# 🔑 CONFIGURACIÓN
# Reemplazá esta línea con tu DATABASE_URL de Railway (la que copiaste antes)
DATABASE_URL = "postgres://usuario:password@host:puerto/nombre_db"

# Ruta a tu base de datos SQLite original
SQLITE_DB = "levelone.db"

print("🔹 Iniciando migración SQLite -> PostgreSQL...")

# 1. Conectar a Postgres
p = urlparse(DATABASE_URL)
pg_conn = psycopg2.connect(dbname=p.path[1:], user=p.username, password=p.password, host=p.hostname, port=p.port)
pg_cur = pg_conn.cursor()

# 2. Conectar a SQLite
sq_conn = sqlite3.connect(SQLITE_DB)
sq_conn.row_factory = sqlite3.Row
sq_cur = sq_conn.cursor()

# 3. Tablas a migrar (en orden para respetar claves foráneas)
tables = ["users", "referral_tree", "cycles", "cycle_levels", "stickers"]

for table in tables:
    try:
        sq_cur.execute(f"SELECT * FROM {table}")
        rows = sq_cur.fetchall()
        if not rows:
            print(f"  ⏭️  {table}: vacía, saltando.")
            continue
            
        columns = rows[0].keys()
        cols_str = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        
        count = 0
        for row in rows:
            values = [row[col] for col in columns]
            # ON CONFLICT DO NOTHING evita errores si ya existe el ID
            pg_cur.execute(
                f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING",
                values
            )
            count += 1
        pg_conn.commit()
        print(f"  ✅ {table}: {count} registros migrados.")
        
    except Exception as e:
        pg_conn.rollback()
        print(f"  ❌ Error en {table}: {e}")

# 4. Sincronizar secuencias de Postgres (para que los AUTOINCREMENT/ SERIAL sigan funcionando)
for table in tables:
    try:
        pg_cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1), false)")
    except: pass
pg_conn.commit()

pg_conn.close()
sq_conn.close()
print("\n🎉 Migración completada. Base de datos lista.")