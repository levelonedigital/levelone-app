import sqlite3
conn = sqlite3.connect('levelone.db')
cur = conn.cursor()

print("🔧 Creando tablas nuevas si no existen...")
cur.execute('''CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, l5_user_id INTEGER NOT NULL, status TEXT DEFAULT 'active', completed_at TIMESTAMP
)''')
cur.execute('''CREATE TABLE IF NOT EXISTS cycle_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, cycle_id INTEGER,
    level INTEGER DEFAULT 5, is_graduated BOOLEAN DEFAULT 0, UNIQUE(user_id, cycle_id)
)''')
try: cur.execute("ALTER TABLE stickers ADD COLUMN cycle_id INTEGER")
except: pass

print("🔗 Migrando datos a la nueva estructura...")
cur.execute("INSERT OR IGNORE INTO cycles (id, l5_user_id, status) VALUES (1, 1, 'completed')")
cur.execute("UPDATE stickers SET cycle_id = 1 WHERE cycle_id IS NULL")

users = cur.execute("SELECT id, current_level FROM users").fetchall()
for uid, lvl in users:
    cur.execute("INSERT OR IGNORE INTO cycle_levels (user_id, cycle_id, level) VALUES (?, 1, ?)", (uid, lvl))

sellers = cur.execute("SELECT id FROM users WHERE role='seller' OR current_level IN (4,5)").fetchall()
for s in sellers:
    cnt = cur.execute("SELECT COUNT(*) FROM stickers WHERE seller_id=? AND status='entregado'", (s[0],)).fetchone()[0]
    if cnt >= 3:
        cur.execute("UPDATE cycles SET status='completed', completed_at=datetime('now') WHERE l5_user_id=?", (s[0],))

conn.commit()
conn.close()
print("✅ DB adaptada correctamente. Volvé a la pestaña Web y clic en Reload.")
