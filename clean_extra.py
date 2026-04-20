import sqlite3
conn = sqlite3.connect('levelone.db')
cur = conn.cursor()

# 1. Recolectar todos los IDs que pertenecen al árbol o son Admin
tree_ids = set()
for row in cur.execute("SELECT parent_id FROM referral_tree"):
    if row[0]: tree_ids.add(row[0])
for row in cur.execute("SELECT child_id FROM referral_tree"):
    if row[0]: tree_ids.add(row[0])
admin = cur.execute("SELECT id FROM users WHERE sticker_id='ADMIN001'").fetchone()
if admin: tree_ids.add(admin[0])

# 2. Identificar y eliminar extras
all_users = cur.execute("SELECT id FROM users").fetchall()
extras = [u[0] for u in all_users if u[0] not in tree_ids]

if extras:
    placeholders = ','.join(['?'] * len(extras))
    cur.execute(f"DELETE FROM users WHERE id IN ({placeholders})", extras)
    print(f"✅ {len(extras)} usuarios extra eliminados.")
else:
    print("ℹ️ No se encontraron usuarios extra.")

conn.commit()
final = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
print(f"📊 Total final: {final} usuarios. DB 100% limpia.")
conn.close()
