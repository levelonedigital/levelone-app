import sqlite3
conn = sqlite3.connect('levelone.db')
cur = conn.cursor()

print("🧹 Eliminando solo datos transaccionales...")
cur.execute("DELETE FROM stickers")
cur.execute("DELETE FROM cycle_levels")
cur.execute("DELETE FROM cycles")
conn.commit()

users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
tree = cur.execute("SELECT COUNT(*) FROM referral_tree").fetchone()[0]
cycles = cur.execute("SELECT COUNT(*) FROM cycles").fetchone()[0]
stickers = cur.execute("SELECT COUNT(*) FROM stickers").fetchone()[0]

print(f"✅ Usuarios: {users} | Árbol: {tree} | Ciclos: {cycles} | Stickers: {stickers}")
print("🚀 DB lista para Fase 1 desde 0. Niveles L1-L5 preservados.")
conn.close()
