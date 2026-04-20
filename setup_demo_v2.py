import sqlite3
from werkzeug.security import generate_password_hash

DB = "/home/MarcosSalomon/levelone.db"
conn = sqlite3.connect(DB)
c = conn.cursor()
pwd = generate_password_hash("de")
mail = "level.one.digital2000@gmail.com"

print("🧹 Limpiando datos anteriores...")
c.execute("DELETE FROM referral_tree WHERE parent_id IN (SELECT id FROM users WHERE sticker_id LIKE 'DEMO-%')")
c.execute("DELETE FROM users WHERE sticker_id LIKE 'DEMO-%'")
conn.commit()

users = {1:[], 2:[], 3:[], 4:[], 5:[]}

# L1
c.execute("INSERT OR REPLACE INTO users (sticker_id,full_name,phone,email,address,cbu_alias,password_hash,current_level,referrals_completed_count,is_level1,role,graduated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
          ("DEMO-L1-01","Nivel 1","+5491100000001",mail,None,"admin.levelone.mp",pwd,1,0,1,"level1",None))
users[1].append(c.lastrowid)

# L2 (3)
for i in range(3):
    sid=f"DEMO-L2-{i+1:02d}"
    c.execute("INSERT OR REPLACE INTO users (sticker_id,full_name,phone,email,address,cbu_alias,password_hash,current_level,referrals_completed_count,is_level1,role,graduated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (sid,f"Nivel 2-{i+1}",f"+5491120000{i}",mail,None,f"l2u{i+1}.cbu.mp",pwd,2,0,0,"seller",None))
    uid=c.lastrowid; users[2].append(uid)
    c.execute("INSERT OR IGNORE INTO referral_tree (parent_id,child_id) VALUES (?,?)",(users[1][0],uid))

# L3 (9)
l3=[]
for i in range(9):
    p=users[2][i//3]
    sid=f"DEMO-L3-{i+1:02d}"
    c.execute("INSERT OR REPLACE INTO users (sticker_id,full_name,phone,email,address,cbu_alias,password_hash,current_level,referrals_completed_count,is_level1,role,graduated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (sid,f"Nivel 3-{i+1}",f"+5491130000{i:02d}",mail,None,f"l3u{i+1}.cbu.mp",pwd,3,0,0,"seller",None))
    uid=c.lastrowid; l3.append(uid)
    c.execute("INSERT OR IGNORE INTO referral_tree (parent_id,child_id) VALUES (?,?)",(p,uid))
users[3]=l3

# L4 (27)
l4=[]
for i in range(27):
    p=users[3][i//3]
    sid=f"DEMO-L4-{i+1:02d}"
    c.execute("INSERT OR REPLACE INTO users (sticker_id,full_name,phone,email,address,cbu_alias,password_hash,current_level,referrals_completed_count,is_level1,role,graduated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (sid,f"Nivel 4-{i+1}",f"+549114000{i:02d}",mail,None,f"l4u{i+1}.cbu.mp",pwd,4,0,0,"seller",None))
    uid=c.lastrowid; l4.append(uid)
    c.execute("INSERT OR IGNORE INTO referral_tree (parent_id,child_id) VALUES (?,?)",(p,uid))
users[4]=l4

# L5 (81)
for i in range(81):
    p=users[4][i//3]
    sid=f"DEMO-L5-{i+1:02d}"
    c.execute("INSERT OR REPLACE INTO users (sticker_id,full_name,phone,email,address,cbu_alias,password_hash,current_level,referrals_completed_count,is_level1,role,graduated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (sid,f"Nivel 5-{i+1}",f"+54911500{i:02d}",mail,None,f"l5u{i+1}.cbu.mp",pwd,5,0,0,"seller",None))
    c.execute("INSERT OR IGNORE INTO referral_tree (parent_id,child_id) VALUES (?,?)",(p,c.lastrowid))

conn.commit()
total = c.execute("SELECT COUNT(*) FROM users WHERE sticker_id LIKE 'DEMO-%'").fetchone()[0]
print(f"✅ Finalizado. Usuarios DEMO en DB: {total}")
if total == 121: print("🎉 RED COMPLETA LISTA.")
else: print(f"⚠️ Se insertaron {total}. Revisá si faltaron.")
conn.close()