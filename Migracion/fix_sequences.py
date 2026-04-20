import psycopg2

# 🔑 PEGÁ ACÁ LA MISMA URL QUE USASTE PARA MIGRAR
DATABASE_URL = "postgresql://postgres:NRvgqWEiKQNNdBKfYRKzPQLrHWIhdkHK@roundhouse.proxy.rlwy.net:16706/railway"

print("🔄 Sincronizando contadores de PostgreSQL...")
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

queries = [
    "SELECT setval('users_id_seq', COALESCE(MAX(id), 1)) FROM users;",
    "SELECT setval('referral_tree_id_seq', COALESCE(MAX(id), 1)) FROM referral_tree;",
    "SELECT setval('cycles_id_seq', COALESCE(MAX(id), 1)) FROM cycles;",
    "SELECT setval('cycle_levels_id_seq', COALESCE(MAX(id), 1)) FROM cycle_levels;",
    "SELECT setval('stickers_id_seq', COALESCE(MAX(id), 1)) FROM stickers;"
]

for q in queries:
    cur.execute(q)
    table_name = q.split("'")[1].split("_id_seq")[0]
    print(f"  ✅ {table_name}")

conn.commit()
cur.close()
conn.close()
print("\n🎉 ¡Listo! Probá crear el sticker de nuevo. El error de IDs duplicados no volverá.")
