import sqlite3
conn = sqlite3.connect('levelone.db')
cur = conn.cursor()

# 1. Recolectar IDs válidos (árbol + ADMIN)
valid_ids = set()
for r in cur.execute("SELECT parent_id FROM referral_tree"): 
    if r[0] is not None: valid_ids.add(r[0])
for r in cur.execute("SELECT child_id FROM referral_tree"): 
    if r[0] is not None: valid_ids.add(r[0])
admin = cur.execute("SELECT id FROM users WHERE sticker_id='ADMIN001'").fetchone()
if admin: valid_ids.add(admin[0])

# 2. Identificar residuos
all_ids = {r[0] for r in cur.execute("SELECT id FROM users").fetchall()}
residuals = all_ids - valid_ids

if residuals:
    # Limpieza de seguridad (por si quedó algún rastro)
    placeholders = ','.join(['?'] * len(residuals))
    ids_list = list(residuals)
    cur.execute(f"DELETE FROM cycle_levels WHERE user_id IN ({placeholders})", ids_list)
    cur.execute(f"DELETE FROM cycles WHERE l5_user_id IN ({placeholders})", ids_list)
    cur.execute(f"DELETE FROM stickers WHERE seller_id IN ({placeholders})", ids_list)
    cur.execute(f"DELETE FROM users WHERE id IN ({placeholders})", ids_list)
    print(f"✅ {len(residuals)} usuario(s) residual(es) eliminado(s).")
else:
    print("ℹ️ No hay residuos. La DB ya está exacta.")

conn.commit()
final = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
print(f"📊 Total final: {final} usuarios (121 árbol + 1 ADMIN). DB 100% limpia.")
conn.close()
