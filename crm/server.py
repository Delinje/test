import os, json, sqlite3, secrets, hashlib, hmac, time
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs
from documents import render_document
from reporting import dashboard, accrue_salary
from work_defaults import DEFAULT_WORKS

ROOT = Path(__file__).parent
DB = os.environ.get('CRM_DB', str(ROOT / 'data.sqlite3'))
STATUSES = ['Новый','Ожидается прием','Диагностика','Диагностика у главного инженера','Ремонт','Ждем запчасть/товар','Ожидает сборки/доставки','Ждем решение заказчика','Нет связи с заказчиком','В сторонний сервис','Уведомить о готовности','Готов к выдаче','Без ремонта','Выдан','Передан на склад','Выдан без ремонта','Возврат']
def done_status(status):
 return status in ('Выдан','Выдан без ремонта','Передан на склад','Возврат')

def eligible_master(c,uid,branch_id):
 if not uid:raise ValueError('Выберите мастера работы')
 uid=int(uid)
 if not c.execute("SELECT 1 FROM users WHERE id=? AND active=1 AND (role='owner' OR EXISTS(SELECT 1 FROM access WHERE user_id=users.id AND branch_id=?))",(uid,branch_id)).fetchone():
  raise ValueError('Мастер не имеет доступа к филиалу')
 return uid

def restore_work_parts(c,item_id,user_id):
 for part in c.execute('SELECT * FROM item_parts WHERE item_id=?',(item_id,)).fetchall():
  original=c.execute('SELECT * FROM stock WHERE id=?',(part['stock_id'],)).fetchone()
  quantity=original['quantity']+part['quantity']
  cost=(original['quantity']*original['unit_cost']+part['quantity']*part['unit_cost']+quantity//2)//quantity
  c.execute('UPDATE stock SET quantity=?,unit_cost=? WHERE id=?',(quantity,cost,original['id']))
  c.execute('INSERT INTO stock_movements(stock_id,user_id,quantity,unit_cost,item_id) VALUES(?,?,?,?,?)',(original['id'],user_id,part['quantity'],part['unit_cost'],item_id))

def return_order(c,o,user_id,method,reason):
 if not o['issued_at']:raise ValueError('Возврат доступен после выдачи заказа')
 if o['returned_at'] or c.execute('SELECT 1 FROM order_returns WHERE order_id=?',(o['id'],)).fetchone():raise ValueError('Возврат уже оформлен')
 reason=str(reason).strip()
 if not reason or len(reason)>1000:raise ValueError('Укажите причину возврата до 1000 символов')
 amount=c.execute('SELECT coalesce(sum(amount),0) FROM payments WHERE order_id=?',(o['id'],)).fetchone()[0]
 if method not in ('Наличные','Карта','Перевод','Без оплаты') or (amount>0 and method=='Без оплаты'):raise ValueError('Выберите способ возврата денег')
 for item in c.execute('SELECT id FROM items WHERE order_id=? AND deleted=0',(o['id'],)).fetchall():restore_work_parts(c,item['id'],user_id)
 if amount>0:c.execute('INSERT INTO payments(order_id,amount,method) VALUES(?,?,?)',(o['id'],-amount,method))
 c.execute('INSERT INTO order_returns(order_id,user_id,amount,method,reason) VALUES(?,?,?,?,?)',(o['id'],user_id,max(0,amount),method,reason))
 c.execute("UPDATE orders SET returned_at=CURRENT_TIMESTAMP,status='Возврат',version=version+1 WHERE id=?",(o['id'],))
 c.execute('INSERT INTO events(order_id,user_id,text) VALUES(?,?,?)',(o['id'],user_id,'Возврат средств: '+format(max(0,amount)/100,'.2f')+' ₽ · '+method+'. Запчасти возвращены на склад, начисления мастеру отменены. Причина: '+reason))

def connection():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def password(value, salt=None):
 salt=salt or secrets.token_hex(16)
 return salt+':'+hashlib.scrypt(value.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
def normalize_phone(value):
 digits=''.join(ch for ch in str(value) if ch in '0123456789')
 if len(digits)==11 and digits.startswith('8'): digits='7'+digits[1:]
 if len(digits)==10: digits='7'+digits
 return digits

def format_phone(value):
 digits=normalize_phone(value)
 if len(digits)==11 and digits.startswith('7'):
  return f'+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}'
 return value

def positive_int(value):
 text=str(value)
 if not text.isascii() or not text.isdigit() or not 1<=int(text)<=1000000:
  raise ValueError('Количество должно быть целым положительным числом до 1 000 000')
 return int(text)

def save_catalog(c,kind,value):
 value=' '.join(str(value).split())
 if kind not in ('device','appearance','fault','work','brand','equipment') or not value or len(value)>300:
  raise ValueError('Укажите вариант длиной до 300 символов')
 c.execute('INSERT OR IGNORE INTO catalog(kind,value,normalized) VALUES(?,?,?)',(kind,value,value.casefold()))

def save_client(c,name,phone):
 normalized=normalize_phone(phone)
 if len(normalized)!=11 or not normalized.startswith('7'): raise ValueError('Укажите российский номер: +7 (XXX) XXX-XX-XX')
 phone=format_phone(normalized)
 c.execute('INSERT INTO clients(name,phone,normalized_phone) VALUES(?,?,?) ON CONFLICT(normalized_phone) DO UPDATE SET name=excluded.name,phone=excluded.phone',(name.strip(),phone.strip(),normalized))

def initialize():
 with connection() as c:
  c.executescript('''
CREATE TABLE IF NOT EXISTS stock(id INTEGER PRIMARY KEY,branch_id INTEGER NOT NULL REFERENCES branches(id),name TEXT NOT NULL,sku TEXT NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>=0),unit_cost INTEGER NOT NULL CHECK(unit_cost>=0),UNIQUE(branch_id,sku));
CREATE TABLE IF NOT EXISTS item_parts(id INTEGER PRIMARY KEY,item_id INTEGER NOT NULL REFERENCES items(id),stock_id INTEGER NOT NULL REFERENCES stock(id),quantity INTEGER NOT NULL CHECK(quantity>0),unit_cost INTEGER NOT NULL CHECK(unit_cost>=0),created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY,stock_id INTEGER NOT NULL REFERENCES stock(id),user_id INTEGER NOT NULL REFERENCES users(id),quantity INTEGER NOT NULL,unit_cost INTEGER NOT NULL,item_id INTEGER REFERENCES items(id),created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY,name TEXT NOT NULL,phone TEXT NOT NULL,normalized_phone TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS catalog(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,value TEXT NOT NULL,normalized TEXT NOT NULL,UNIQUE(kind,normalized));
CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS branches(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS access(user_id INTEGER REFERENCES users(id),branch_id INTEGER REFERENCES branches(id),PRIMARY KEY(user_id,branch_id));
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),expires REAL);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,branch_id INTEGER NOT NULL REFERENCES branches(id),client TEXT NOT NULL,phone TEXT NOT NULL,device TEXT NOT NULL,serial TEXT DEFAULT '',appearance TEXT DEFAULT '',equipment TEXT DEFAULT '',fault TEXT NOT NULL,comment TEXT DEFAULT '',status TEXT NOT NULL,master_id INTEGER REFERENCES users(id),deadline TEXT DEFAULT '',estimate INTEGER DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP,version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(id),name TEXT NOT NULL,kind TEXT NOT NULL,quantity INTEGER NOT NULL,price INTEGER NOT NULL,warranty INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(id),amount INTEGER NOT NULL,method TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(id),user_id INTEGER REFERENCES users(id),text TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
''')
  for table,name,definition in [('catalog','warranty','INTEGER NOT NULL DEFAULT 30'),('catalog','work_group',"TEXT NOT NULL DEFAULT ''"),('catalog','active','INTEGER NOT NULL DEFAULT 1'),('items','deleted','INTEGER NOT NULL DEFAULT 0'),('orders','no_payment','INTEGER NOT NULL DEFAULT 0'),('stock','group_id','INTEGER REFERENCES stock_groups(id)'),('orders','brand',"TEXT NOT NULL DEFAULT ''"),('orders','deleted','INTEGER NOT NULL DEFAULT 0'),('orders','returned_at','TEXT')]:
   if name not in {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}:
    c.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
  c.execute('CREATE TABLE IF NOT EXISTS order_returns(order_id INTEGER PRIMARY KEY REFERENCES orders(id),user_id INTEGER NOT NULL REFERENCES users(id),amount INTEGER NOT NULL,method TEXT NOT NULL,reason TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP)')
  c.execute('CREATE TABLE IF NOT EXISTS stock_groups(id INTEGER PRIMARY KEY,name TEXT NOT NULL,normalized TEXT NOT NULL UNIQUE)')
  if not c.execute("SELECT 1 FROM migrations WHERE name='starter_works_v1'").fetchone():
   for group,names in DEFAULT_WORKS.items():
    for name in names:
     save_catalog(c,'work',name)
     c.execute("UPDATE catalog SET work_group=? WHERE kind='work' AND normalized=? AND work_group=''",(group,name.casefold()))
   c.execute("INSERT INTO migrations VALUES('starter_works_v1')")
  if not c.execute("SELECT 1 FROM migrations WHERE name='client_catalog_v1'").fetchone():
   for o in c.execute('SELECT * FROM orders ORDER BY id').fetchall():
    digits=normalize_phone(o['phone'])
    if digits:
     c.execute('INSERT INTO clients(name,phone,normalized_phone) VALUES(?,?,?) ON CONFLICT(normalized_phone) DO UPDATE SET name=excluded.name,phone=excluded.phone',(o['client'],o['phone'],digits))
    for kind in ('device','appearance','fault'):
     for value in (o[kind] or '').split(';'):
      if value.strip() and len(' '.join(value.split()))<=300:save_catalog(c,kind,value)
   c.execute("INSERT INTO migrations VALUES('client_catalog_v1')")
  columns={x['name'] for x in c.execute('PRAGMA table_info(orders)')}
  if 'diagnosis' not in columns:c.execute("ALTER TABLE orders ADD COLUMN diagnosis TEXT NOT NULL DEFAULT ''")
  if not c.execute("SELECT 1 FROM migrations WHERE name='work_catalog_v1'").fetchone():
   for row in c.execute("SELECT DISTINCT name FROM items WHERE kind='Работа'").fetchall():
    if row['name'].strip() and len(' '.join(row['name'].split()))<=300:save_catalog(c,'work',row['name'])
   c.execute("INSERT INTO migrations VALUES('work_catalog_v1')")
  for name,definition in [('device_password',"TEXT NOT NULL DEFAULT ''"),('issued_at','TEXT')]:
   if name not in {x['name'] for x in c.execute('PRAGMA table_info(orders)')}:
    c.execute('ALTER TABLE orders ADD COLUMN '+name+' '+definition)
  if 'master_id' not in {x['name'] for x in c.execute('PRAGMA table_info(items)')}:
   c.execute('ALTER TABLE items ADD COLUMN master_id INTEGER REFERENCES users(id)')
   c.execute("UPDATE items SET master_id=(SELECT master_id FROM orders WHERE orders.id=items.order_id) WHERE kind='Работа'")
  c.execute('CREATE TABLE IF NOT EXISTS earnings(item_id INTEGER PRIMARY KEY REFERENCES items(id),master_id INTEGER REFERENCES users(id),revenue INTEGER NOT NULL,cost INTEGER NOT NULL,master_share INTEGER NOT NULL,service_share INTEGER NOT NULL,issued_at TEXT NOT NULL)')
  if not c.execute("SELECT 1 FROM migrations WHERE name='issuance_salary_v1'").fetchone():
   for row in c.execute("SELECT * FROM orders WHERE status IN ('Выдан','Выдан без ремонта')").fetchall():
    timestamp=c.execute("SELECT max(created) FROM events WHERE order_id=? AND (text LIKE '%→ Выдан' OR text LIKE '%→ Выдан без ремонта')",(row['id'],)).fetchone()[0] or row['created']
    c.execute('UPDATE orders SET issued_at=? WHERE id=?',(timestamp,row['id']))
    accrue_salary(c,row['id'],timestamp)
   c.execute("INSERT INTO migrations VALUES('issuance_salary_v1')")

def money(v):
 from decimal import Decimal, InvalidOperation
 try:
  x=Decimal(str(v))*100
  if not x.is_finite() or x!=x.to_integral_value() or abs(x)>10**11: raise ValueError('Некорректная сумма')
  return int(x)
 except (InvalidOperation,TypeError): raise ValueError('Некорректная сумма')
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def reply(self,data,status=200,cookie=None):
  body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store')
  if cookie:self.send_header('Set-Cookie',cookie)
  self.end_headers(); self.wfile.write(body)
 def do_GET(self): self.dispatch()
 def do_POST(self): self.dispatch()
 def dispatch(self):
  try:
   if not self.path.startswith('/api/'):
    files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
    if self.path not in files:self.reply({'error':'Не найдено'},404);return
    p=ROOT/'static'/files[self.path]; self.send_response(200);self.send_header('Content-Type',{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[p.suffix[1:]]);self.end_headers();self.wfile.write(p.read_bytes());return
   with connection() as c:
    if self.command=='POST':c.execute('BEGIN IMMEDIATE')
    self.api(c)
  except (ValueError,KeyError,TypeError) as e:self.reply({'error':str(e)},400)
  except sqlite3.IntegrityError:self.reply({'error':'Проверьте данные: запись уже существует или связана с другими данными'},400)
  except Exception:self.reply({'error':'Внутренняя ошибка сервера'},500)
 def api(self,c):
  url=urlsplit(self.path);p=url.path;query=parse_qs(url.query);data={}
  if self.command=='POST':
   if self.headers.get('Sec-Fetch-Site')=='cross-site':self.reply({'error':'Запрос запрещен'},403);return
   if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Ожидается JSON')
   length=int(self.headers.get('Content-Length','0'))
   if length>65536:raise ValueError('Слишком большой запрос')
   data=json.loads(self.rfile.read(length))
  count=c.execute('SELECT count(*) FROM users').fetchone()[0]
  if p=='/api/setup' and self.command=='GET':self.reply({'required':count==0});return
  if p=='/api/setup' and not count and self.command=='POST':
   if len(data['password'])<12:raise ValueError('Пароль: не менее 12 символов')
   c.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)',(data['name'].strip(),data['email'].strip().lower(),password(data['password']),'owner'));c.execute('INSERT INTO branches(name) VALUES(?)',(data.get('branch','Основной сервис'),));self.reply({'ok':True});return
  if p=='/api/login' and self.command=='POST':
   u=c.execute('SELECT * FROM users WHERE email=? AND active=1',(data['email'].strip().lower(),)).fetchone()
   valid=u and hmac.compare_digest(password(data['password'],u['password'].split(':')[0]),u['password'])
   if not valid:self.reply({'error':'Неверный логин или пароль'},401);return
   token=secrets.token_urlsafe(32);c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],time.time()+43200));self.reply({'ok':True},cookie='session='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'+('; Secure' if os.environ.get('CRM_SECURE_COOKIE')=='1' else ''));return
  cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''));token=cookies.get('session'); token=hashlib.sha256(token.value.encode()).hexdigest() if token else ''
  u=c.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>? AND u.active=1',(token,time.time())).fetchone()
  if not u:self.reply({'error':'Необходим вход'},401);return
  owner=u['role']=='owner'
  branches=[dict(x) for x in c.execute('SELECT * FROM branches' if owner else 'SELECT b.* FROM branches b JOIN access a ON a.branch_id=b.id WHERE a.user_id=?',() if owner else (u['id'],))]; ids=[x['id'] for x in branches]
  def event(oid,text):c.execute('INSERT INTO events(order_id,user_id,text) VALUES(?,?,?)',(oid,u['id'],text))
  if p=='/api/logout':
   c.execute('DELETE FROM sessions WHERE token=?',(token,));self.reply({'ok':True},cookie='session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0');return
  if p=='/api/state':
   users=[dict(x) for x in c.execute('SELECT id,name,email,role,active FROM users')]
   if not owner:
    users=[{k:v for k,v in x.items() if k!='email'} for x in users]
   self.reply({'user':{'id':u['id'],'name':u['name'],'role':u['role']},'branches':branches,'users':users,'statuses':STATUSES});return
  if p=='/api/dashboard':
   self.reply(dashboard(c,u,ids,query));return
  if p=='/api/works':
   if self.command=='POST':
    value=' '.join(data['value'].split());warranty=int(data.get('warranty',30));group=str(data.get('work_group','')).strip()
    if not value or len(value)>300 or not 0<=warranty<=3650:raise ValueError('Проверьте название и гарантию (0–3650 дней)')
    if data.get('id'):
     if u['role']=='master':self.reply({'error':'Редактирование справочника доступно приёмщику и владельцу'},403);return
     if not c.execute("UPDATE catalog SET value=?,normalized=?,warranty=?,work_group=?,active=? WHERE id=? AND kind='work'",(value,value.casefold(),warranty,group,0 if data.get('archived') else 1,int(data['id']))).rowcount:raise ValueError('Работа не найдена')
    else:
     save_catalog(c,'work',value)
     c.execute("UPDATE catalog SET warranty=?,work_group=? WHERE kind='work' AND normalized=?",(warranty,group,value.casefold()))
   self.reply([dict(x) for x in c.execute("SELECT id,value,warranty,work_group,active FROM catalog WHERE kind='work' ORDER BY value")]);return
  if p=='/api/stock-groups':
   if self.command=='POST':
    if u['role']=='master':self.reply({'error':'Нет прав на добавление групп'},403);return
    name=' '.join(data['name'].split())
    if not name or len(name)>100:raise ValueError('Укажите название группы до 100 символов')
    c.execute('INSERT OR IGNORE INTO stock_groups(name,normalized) VALUES(?,?)',(name,name.casefold()))
   self.reply([dict(x) for x in c.execute('SELECT * FROM stock_groups ORDER BY name')]);return
  if p=='/api/stock' or p.startswith('/api/stock/'):
   if self.command=='GET':
    rows=c.execute('SELECT s.*,b.name branch_name,g.name group_name FROM stock s JOIN branches b ON b.id=s.branch_id LEFT JOIN stock_groups g ON g.id=s.group_id ORDER BY s.name').fetchall()
    self.reply([dict(x) for x in rows if x['branch_id'] in ids]);return
   if u['role']=='master':self.reply({'error':'Поступление запчастей доступно владельцу и приёмщику'},403);return
   if p.endswith('/edit'):
    sid=int(p.split('/')[3]);part=c.execute('SELECT * FROM stock WHERE id=?',(sid,)).fetchone()
    if not part or part['branch_id'] not in ids:self.reply({'error':'Запчасть или товар недоступны'},403);return
    name=' '.join(str(data.get('name','')).split());sku=str(data.get('sku','')).strip()
    if not name or not sku or len(name)>300 or len(sku)>100:raise ValueError('Укажите название до 300 символов и артикул до 100 символов')
    group=int(data['group_id']) if data.get('group_id') else None
    c.execute('UPDATE stock SET name=?,sku=?,group_id=? WHERE id=?',(name,sku,group,sid))
    self.reply({'ok':True});return
   if p.endswith('/group'):
    sid=int(p.split('/')[3]);part=c.execute('SELECT * FROM stock WHERE id=?',(sid,)).fetchone()
    if not part or part['branch_id'] not in ids:self.reply({'error':'Запчасть недоступна'},403);return
    group=int(data['group_id']) if data.get('group_id') else None
    c.execute('UPDATE stock SET group_id=? WHERE id=?',(group,sid));self.reply({'ok':True});return
   qty=positive_int(data['quantity']);cost=money(data['unit_cost'])
   if cost<0:raise ValueError('Закупочная цена не может быть отрицательной')
   if p=='/api/stock':
    bid=int(data['branch_id'])
    if bid not in ids:self.reply({'error':'Нет доступа к филиалу'},403);return
    name=' '.join(data['name'].split());sku=data['sku'].strip()
    if not name or not sku or len(name)>300 or len(sku)>100:raise ValueError('Укажите название и артикул запчасти')
    group=int(data['group_id']) if data.get('group_id') else None
    sid=c.execute('INSERT INTO stock(branch_id,name,sku,quantity,unit_cost,group_id) VALUES(?,?,?,?,?,?)',(bid,name,sku,qty,cost,group)).lastrowid
   else:
    sid=int(p.split('/')[3]);part=c.execute('SELECT * FROM stock WHERE id=?',(sid,)).fetchone()
    if not part or part['branch_id'] not in ids:self.reply({'error':'Запчасть недоступна'},403);return
    # Weighted average cost; previously consumed parts retain their cost snapshot.
    average=(part['quantity']*part['unit_cost']+qty*cost+(part['quantity']+qty)//2)//(part['quantity']+qty)
    c.execute('UPDATE stock SET quantity=quantity+?,unit_cost=? WHERE id=?',(qty,average,sid))
   c.execute('INSERT INTO stock_movements(stock_id,user_id,quantity,unit_cost) VALUES(?,?,?,?)',(sid,u['id'],qty,cost))
   self.reply({'ok':True,'id':sid});return
  if p in ('/api/catalog','/api/clients'):
   if u['role']=='master':self.reply({'error':'Справочники доступны приёмщику и владельцу'},403);return
   if p=='/api/catalog':
    if self.command=='POST':
     save_catalog(c,data['kind'],data['value'])
    self.reply([dict(x) for x in c.execute("SELECT id,kind,value FROM catalog WHERE kind!='work' ORDER BY id")]);return
   if self.command!='GET':self.reply({'error':'Метод не поддерживается'},405);return
   term=' '.join(query.get('q',[''])[0].split()).casefold()
   if len(term)<2:self.reply([]);return
   digits=normalize_phone(term)
   # Client contacts are shared by the company; order access remains scoped by branch.
   matches=[]
   for row in c.execute('SELECT id,name,phone,normalized_phone FROM clients ORDER BY id DESC'):
    if term in row['name'].casefold() or (digits and digits in row['normalized_phone']):
     matches.append({'id':row['id'],'name':row['name'],'phone':row['phone']})
     if len(matches)==20:break
   self.reply(matches);return
  if p in ('/api/branches','/api/users') and self.command=='POST':
   if not owner:self.reply({'error':'Только владелец'},403);return
   if p.endswith('branches'):
    name=data['name'].strip()
    if not name:raise ValueError('Укажите название')
    c.execute('INSERT INTO branches(name) VALUES(?)',(name,))
   elif 'disable' in data:
    if int(data['disable'])==u['id']:raise ValueError('Нельзя отключить себя')
    c.execute('UPDATE users SET active=0 WHERE id=?',(data['disable'],));c.execute('DELETE FROM sessions WHERE user_id=?',(data['disable'],))
   else:
    if len(data['password'])<12:raise ValueError('Пароль: не менее 12 символов')
    if data['role'] not in ('manager','master'):raise ValueError('Неизвестная роль')
    if not data['branches'] or any(int(b) not in ids for b in data['branches']):raise ValueError('Выберите доступные филиалы')
    uid=c.execute('INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)',(data['name'],data['email'].strip().lower(),password(data['password']),data['role'])).lastrowid
    for b in data['branches']:c.execute('INSERT INTO access VALUES(?,?)',(uid,int(b)))
   self.reply({'ok':True});return
  if p=='/api/orders' and self.command=='GET':
   rows=c.execute('SELECT o.*,u.name master_name,b.name branch_name,CASE WHEN o.no_payment=1 OR o.returned_at IS NOT NULL THEN 0 ELSE (SELECT coalesce(sum(quantity*price),0) FROM items WHERE order_id=o.id AND deleted=0) END total,(SELECT coalesce(sum(amount),0) FROM payments WHERE order_id=o.id) paid FROM orders o JOIN branches b ON b.id=o.branch_id LEFT JOIN users u ON u.id=o.master_id WHERE o.deleted=0 ORDER BY o.id DESC').fetchall()
   self.reply([{k:v for k,v in dict(x).items() if k!='device_password'} for x in rows if x['branch_id'] in ids and (u['role']!='master' or x['master_id']==u['id'] or c.execute('SELECT 1 FROM items WHERE order_id=? AND master_id=? AND deleted=0',(x['id'],u['id'])).fetchone())]);return
  if p=='/api/orders' and self.command=='POST':
   if u['role']=='master':self.reply({'error':'Создание доступно приёмщику'},403);return
   if int(data['branch_id']) not in ids:self.reply({'error':'Нет доступа к филиалу'},403);return
   for key in ('client','phone','device','serial','appearance','device_password','equipment','fault'):
    if not str(data.get(key,'')).strip():raise ValueError('Обязательны ФИО, телефон, модель, IMEI/серийный номер, внешний вид, пароль, комплектация и неисправность. Если пароля или комплектации нет, укажите «нет».')
   master=int(data['master_id']) if data.get('master_id') else None
   if master and not c.execute("SELECT 1 FROM users WHERE id=? AND active=1 AND (role='owner' OR EXISTS(SELECT 1 FROM access WHERE user_id=users.id AND branch_id=?))",(master,int(data['branch_id']))).fetchone():raise ValueError('Мастер не имеет доступа к филиалу')
   keys=['branch_id','client','phone','device','serial','appearance','equipment','fault','comment','master_id','deadline','estimate','device_password','brand']
   values=[data.get(k,'') for k in keys];values[0]=int(data['branch_id']);values[2]=format_phone(data['phone']);values[9]=master;values[11]=money(data.get('estimate',0))
   # Save the reusable values and client in the same transaction as the order.
   save_client(c,data['client'],data['phone'])
   for kind in ('device','appearance','fault','brand','equipment'):
    for value in str(data.get(kind,'')).split(';'):
     if value.strip():save_catalog(c,kind,value)
   oid=c.execute('INSERT INTO orders('+','.join(keys)+',status) VALUES('+','.join('?' for _ in range(15))+')',values+['Новый']).lastrowid;event(oid,'Заказ создан');self.reply({'id':oid});return
  if p.startswith('/api/orders/'):
   parts=p.split('/');oid=int(parts[3]);o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
   if not o or o['deleted'] or o['branch_id'] not in ids or (u['role']=='master' and o['master_id']!=u['id'] and not c.execute('SELECT 1 FROM items WHERE order_id=? AND master_id=? AND deleted=0',(oid,u['id'])).fetchone()):self.reply({'error':'Заказ недоступен'},403);return
   if self.command=='GET':
    items=[dict(x) for x in c.execute('SELECT i.*,u.name master_name FROM items i LEFT JOIN users u ON u.id=i.master_id WHERE order_id=? AND i.deleted=0',(oid,))]
    if len(parts)>4 and parts[4]=='print':
     kind=query.get('type',[''])[0]
     branch_name=c.execute('SELECT name FROM branches WHERE id=?',(o['branch_id'],)).fetchone()[0]
     body=render_document(kind,dict(o),items,branch_name).encode()
     self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
    used=[dict(x) for x in c.execute('SELECT ip.*,s.name,s.sku FROM item_parts ip JOIN items i ON i.id=ip.item_id JOIN stock s ON s.id=ip.stock_id WHERE i.order_id=? AND i.deleted=0',(oid,))]
    self.reply({'order':dict(o),'items':items,'parts':used,'return':dict(c.execute('SELECT * FROM order_returns WHERE order_id=?',(oid,)).fetchone()) if o['returned_at'] else None,'payments':[dict(x) for x in c.execute('SELECT * FROM payments WHERE order_id=?',(oid,))],'events':[dict(x) for x in c.execute('SELECT e.*,u.name author FROM events e JOIN users u ON u.id=e.user_id WHERE order_id=? ORDER BY e.id DESC',(oid,))]});return
   action=parts[4]
   if action=='return':
    if u['role']=='master':self.reply({'error':'Возврат доступен владельцу и приёмщику'},403);return
    if int(data['version'])!=o['version']:raise ValueError('Заказ изменён. Откройте его повторно')
    return_order(c,o,u['id'],data.get('method',''),data.get('reason',''))
   elif action=='delete':
    if u['role']=='master':self.reply({'error':'Удаление доступно владельцу и приёмщику'},403);return
    settled=bool(o['issued_at'])
    if not settled and c.execute('SELECT 1 FROM payments WHERE order_id=?',(oid,)).fetchone():raise ValueError('Нельзя удалить заказ с платежами: сначала необходимо оформить возврат')
    if int(data['version'])!=o['version']:raise ValueError('Заказ изменён. Откройте его повторно')
    reason=str(data.get('reason','Клиент отказался оставлять устройство')).strip()
    if len(reason)>1000:raise ValueError('Причина удаления: до 1000 символов')
    if settled and not o['returned_at']:
     return_order(c,o,u['id'],data.get('method',''),reason)
    if not settled:
     for item in c.execute('SELECT id FROM items WHERE order_id=? AND deleted=0',(oid,)).fetchall():
      restore_work_parts(c,item['id'],u['id'])
     c.execute('UPDATE items SET deleted=1 WHERE order_id=?',(oid,))
    c.execute('UPDATE orders SET deleted=1,version=version+1 WHERE id=?',(oid,))
    event(oid,'Заказ удалён: '+reason+('. Оформлен возврат денег и запчастей; история операций сохранена.' if settled else '. Списанные запчасти возвращены на склад.'))
   elif action=='issue':
    if u['role']=='master':self.reply({'error':'Выдача доступна приёмщику'},403);return
    if o['issued_at'] or done_status(o['status']):raise ValueError('Заказ уже закрыт')
    if int(data['version'])!=o['version']:raise ValueError('Заказ изменён. Откройте его повторно')
    if data['status'] not in ('Выдан','Выдан без ремонта') or data['method'] not in ('Наличные','Карта','Перевод','Без оплаты'):
     raise ValueError('Выберите способ оплаты и тип выдачи')
    if c.execute("SELECT 1 FROM items WHERE order_id=? AND deleted=0 AND kind='Работа' AND master_id IS NULL",(oid,)).fetchone():
     raise ValueError('Назначьте мастера каждой работе перед выдачей')
    total=c.execute('SELECT coalesce(sum(quantity*price),0) FROM items WHERE order_id=? AND deleted=0',(oid,)).fetchone()[0]
    paid=c.execute('SELECT coalesce(sum(amount),0) FROM payments WHERE order_id=?',(oid,)).fetchone()[0]
    free=data['method']=='Без оплаты'
    if free and paid:raise ValueError('В заказе уже есть платежи. Бесплатная выдача требует отдельного возврата ранее внесённых денег.')
    if free:c.execute('UPDATE orders SET no_payment=1 WHERE id=?',(oid,))
    due=0 if free else max(0,total-paid)
    if due:
     c.execute('INSERT INTO payments(order_id,amount,method) VALUES(?,?,?)',(oid,due,data['method']))
     event(oid,'Оплата при выдаче: '+format(due/100,'.2f')+' ₽, '+data['method'])
    c.execute("UPDATE orders SET status=?,issued_at=CURRENT_TIMESTAMP,version=version+1 WHERE id=?",(data['status'],oid))
    timestamp=c.execute('SELECT issued_at FROM orders WHERE id=?',(oid,)).fetchone()[0]
    accrue_salary(c,oid,timestamp)
    event(oid,o['status']+' → '+data['status']+' · '+data['method'])
   elif action=='delete-work':
    if o['issued_at'] or done_status(o['status']):raise ValueError('Нельзя удалять работы после финансового закрытия заказа')
    if int(data['version'])!=o['version']:raise ValueError('Заказ изменён. Откройте его повторно')
    item=c.execute('SELECT * FROM items WHERE id=? AND order_id=? AND deleted=0',(int(data['item_id']),oid)).fetchone()
    if not item:raise ValueError('Работа не найдена или уже удалена')
    restore_work_parts(c,item['id'],u['id'])
    c.execute('UPDATE items SET deleted=1 WHERE id=?',(item['id'],))
    c.execute('UPDATE orders SET version=version+1 WHERE id=?',(oid,))
    event(oid,'Удалена работа «'+item['name']+'». Связанные запчасти возвращены на склад.')
   elif action=='assign-work':
    if o['issued_at'] or done_status(o['status']):raise ValueError('Выданный заказ нельзя менять')
    master=eligible_master(c,data['master_id'],o['branch_id'])
    if not c.execute("UPDATE items SET master_id=? WHERE id=? AND order_id=? AND kind='Работа' AND deleted=0",(master,int(data['item_id']),oid)).rowcount:
     raise ValueError('Работа не найдена')
    event(oid,'Изменён мастер работы')
    c.execute('UPDATE orders SET version=version+1 WHERE id=?',(oid,))
   elif action=='diagnosis':
    if o['issued_at'] or done_status(o['status']):raise ValueError('Выданный заказ нельзя менять')
    text=data['text'].strip()
    if len(text)>10000:raise ValueError('Заключение не должно превышать 10 000 символов')
    changed=c.execute('UPDATE orders SET diagnosis=?,version=version+1 WHERE id=? AND version=?',(text,oid,data['version'])).rowcount
    if not changed:raise ValueError('Заказ изменён другим сотрудником. Откройте его повторно')
    event(oid,'Сохранено заключение диагностики')
   elif action=='parts':
    if o['issued_at'] or done_status(o['status']):raise ValueError('Заказ уже закрыт')
    work=c.execute("SELECT * FROM items WHERE id=? AND order_id=? AND kind='Работа' AND deleted=0",(int(data['item_id']),oid)).fetchone()
    if not work:raise ValueError('Выберите работу этого заказа')
    part=c.execute('SELECT * FROM stock WHERE id=? AND branch_id=?',(int(data['stock_id']),o['branch_id'])).fetchone()
    if not part:raise ValueError('Выберите запчасть из филиала заказа')
    qty=positive_int(data['quantity'])
    if not c.execute('UPDATE stock SET quantity=quantity-? WHERE id=? AND quantity>=?',(qty,part['id'],qty)).rowcount:
     raise ValueError('Недостаточно запчастей на складе')
    c.execute('INSERT INTO item_parts(item_id,stock_id,quantity,unit_cost) VALUES(?,?,?,?)',(work['id'],part['id'],qty,part['unit_cost']))
    c.execute('INSERT INTO stock_movements(stock_id,user_id,quantity,unit_cost,item_id) VALUES(?,?,?,?,?)',(part['id'],u['id'],-qty,part['unit_cost'],work['id']))
    c.execute('UPDATE orders SET version=version+1 WHERE id=?',(oid,))
    event(oid,'К работе «'+work['name']+'» списана запчасть «'+part['name']+'», '+str(qty)+' шт.')
   elif action=='status':
    if data['status'] not in STATUSES:raise ValueError('Неизвестный статус')
    if o['issued_at'] and u['role']=='master':self.reply({'error':'Смена статуса выданного заказа доступна приёмщику'},403);return
    if not o['issued_at'] and done_status(data['status']):raise ValueError('Для закрытия заказа используйте кнопку выдачи')
    changed=c.execute('UPDATE orders SET status=?,version=version+1 WHERE id=? AND version=?',(data['status'],oid,data['version'])).rowcount
    if not changed:raise ValueError('Заказ изменён другим сотрудником. Откройте его повторно')
    event(oid,o['status']+' → '+data['status'])
   elif action=='comment':
    if not data['text'].strip():raise ValueError('Пустой комментарий')
    event(oid,data['text'].strip())
   elif action=='items':
    if o['issued_at'] or done_status(o['status']):raise ValueError('Заказ уже закрыт')
    quantity=positive_int(data['quantity']);price=money(data['price']);warranty=int(data.get('warranty',0))
    if quantity<1 or price<0 or warranty<0 or not data['name'].strip() or data['kind'] not in ('Работа','Материал'):raise ValueError('Проверьте позицию')
    master=eligible_master(c,data.get('master_id') or o['master_id'],o['branch_id']) if data['kind']=='Работа' else None
    if data['kind']=='Работа':save_catalog(c,'work',data['name'])
    c.execute('INSERT INTO items(order_id,name,kind,quantity,price,warranty,master_id) VALUES(?,?,?,?,?,?,?)',(oid,data['name'],data['kind'],quantity,price,warranty,master));event(oid,'Добавлено: '+data['name'])
    c.execute('UPDATE orders SET version=version+1 WHERE id=?',(oid,))
   elif action=='payments':
    if o['issued_at'] or done_status(o['status']):raise ValueError('Заказ уже закрыт')
    if u['role']=='master':self.reply({'error':'Приём оплаты доступен приёмщику'},403);return
    amount=money(data['amount'])
    if amount<=0 or data['method'] not in ('Наличные','Карта','Перевод'):raise ValueError('Проверьте оплату')
    c.execute('INSERT INTO payments(order_id,amount,method) VALUES(?,?,?)',(oid,amount,data['method']));event(oid,'Оплата: '+format(amount/100,'.2f')+' ₽, '+data['method'])
   else:raise ValueError('Неизвестное действие')
   self.reply({'ok':True});return
  self.reply({'error':'Не найдено'},404)
if __name__=='__main__':
 initialize();ThreadingHTTPServer((os.environ.get('CRM_HOST','127.0.0.1'),int(os.environ.get('PORT','8000'))),Handler).serve_forever()
