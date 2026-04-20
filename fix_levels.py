import sqlite3
from collections import deque

conn = sqlite3.connect('levelone.db')
cur = conn.cursor()

# 1. Encontrar raíces (usuarios sin padre en el árbol)
all_ids = {r[0] for r in cur.execute("SELECT id FROM users").fetchall()}
child_ids = {r[0] for r in cur.execute("SELECT child_id FROM referral_tree").fetchall()}
roots = all_ids - child_ids

# 2. BFS para calcular nivel real por profundidad
queue = deque()
for r in roots: queue.append((r, 1))

level_map = {}
visited = set()
while queue:
    uid, lvl = queue.popleft()
    if uid in visited: continue
    visited.add(uid)
    level_map[uid] = lvl
    # ch es una tupla (child_id,), usamos ch[0]
    for ch in cur.execute("SELECT child_id FROM referral_tree WHERE parent_id=?", (uid,)).fetchall():
        queue.append((ch[0], lvl + 1))

# 3. Aplicar corrección
for uid, lvl in level_map.items():
    cur.execute("UPDATE users SET current_level = ? WHERE id = ?", (lvl, uid))

conn.commit()
print(f"✅ Niveles globales corregidos para {len(level_map)} usuarios.")
print("   L1→1 | L2→2 | L3→3 | L4→4 | L5→5")
conn.close()
