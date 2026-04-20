import psycopg2
from urllib.parse import quote

# 🔑 COMPLETAR CON TUS DATOS REALES DE RAILWAY
# (Andá a postgres → Variables en Railway para ver estos valores)
config = {
    "host": "roundhouse.proxy.rlwy.net",
    "port": 16706,
    "dbname": "railway",
    "user": "postgres",
    "password": "PEGAR_CONTRASEÑA_AQUI",  # ← Si tiene @ : / ? #, codificala con quote()
}

# Codificar contraseña si tiene caracteres especiales
if any(c in config["password"] for c in "@:/?#[]"):
    config["password"] = quote(config["password"], safe='')
    print(f"🔐 Contraseña codificada: {config['password'][:10]}...")

print("🔹 Probando conexión a PostgreSQL en Railway...")

try:
    conn = psycopg2.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["dbname"],
        user=config["user"],
        password=config["password"],
        sslmode="require",  # ⚠️ OBLIGATORIO para Railway
        connect_timeout=10
    )
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print(f"✅ ¡Conexión exitosa!")
    print(f"📦 Versión de Postgres: {version[:50]}...")
    conn.close()
except Exception as e:
    print(f"❌ Error: {e}")
    print("\n💡 Posibles causas:")
    print("   1. Contraseña con caracteres especiales no codificada")
    print("   2. Falta sslmode='require'")
    print("   3. IP no autorizada (agregá tu IP en Railway → postgres → Settings)")