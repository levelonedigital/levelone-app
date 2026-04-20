import sqlite3
conn = sqlite3.connect('levelone.db')
cur = conn.cursor()

# Ver CBU actual
actual = cur.execute("SELECT cbu_alias FROM users WHERE sticker_id='ADMIN001'").fetchone()
print(f"🔍 CBU actual de ADMIN001: {actual[0]}")

# ⬇️ CAMBIÁ ESTE VALOR POR TU CBU/ALIAS REAL
NUEVO_CBU = "CBU.DE.PRUEBA"

cur.execute("UPDATE users SET cbu_alias=? WHERE sticker_id='ADMIN001'", (NUEVO_CBU,))
conn.commit()

# Verificación
verif = cur.execute("SELECT cbu_alias FROM users WHERE sticker_id='ADMIN001'").fetchone()
print(f"✅ CBU actualizado correctamente a: {verif[0]}")
conn.close()
