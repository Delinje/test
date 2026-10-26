import os, json, sqlite3, secrets, hashlib, hmac, time
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie

ROOT = Path(__file__).parent
DB = os.environ.get('CRM_DB', str(ROOT / 'data.sqlite3'))
STATUSES = ['Новый','Ожидается прием','Диагностика','Диагностика у главного инженера','Ремонт','Ждем запчасть/товар','Ожидает сборки/доставки','Ждем решение заказчика','Нет связи с заказчиком','В сторонний сервис','Уведомить о готовности','Готов к выдаче','Без ремонта','Выдан','Передан на склад','Выдан без ремонта']
def connection():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def password(value, salt=None):
 salt=salt or secrets.token_hex(16)
 return salt+':'+hashlib.scrypt(value.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
def initialize():
 with connection() as c:
  c.executescript('''
CREATE TABLE IF NOT EXISTS branches(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS access(user_id INTEGER REFERENCES users(id),branch_id INTEGER REFERENCES branches(id),PRIMARY KEY(user_id,branch_id));
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),expires REAL);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,branch_id INTEGER NOT NULL REFERENCES branches(id),client TEXT NOT NULL,phone TEXT NOT NULL,device TEXT NOT NULL,serial TEXT DEFAULT '',appearance TEXT DEFAULT '',equipment TEXT DEFAULT '',fault TEXT NOT NULL,comment TEXT DEFAULT '',status TEXT NOT NULL,master_id INTEGER REFERENCES users(id),deadline TEXT DEFAULT '',estimate INTEGER DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP,version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(id),name TEXT NOT NULL,kind TEXT NOT NULL,quantity INTEGER NOT NULL,price INTEGER NOT NULL,warranty INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(id),amount INTEGER NOT NULL,method TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(id),user_id INTEGER REFERENCES users(id),text TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
''')
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
   with connection() as c:self.api(c)
  except (ValueError,KeyError,TypeError) as e:self.reply({'error':str(e)},400)
  except sqlite3.IntegrityError:self.reply({'error':'Проверьте данные: запись уже существует или связана с другими данными'},400)
  except Exception:self.reply({'error':'Внутренняя ошибка сервера'},500)
 def api(self,c):
  p=self.path; data={}
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
   rows=c.execute('SELECT o.*,u.name master_name,b.name branch_name,(SELECT coalesce(sum(quantity*price),0) FROM items WHERE order_id=o.id) total,(SELECT coalesce(sum(amount),0) FROM payments WHERE order_id=o.id) paid FROM orders o JOIN branches b ON b.id=o.branch_id LEFT JOIN users u ON u.id=o.master_id ORDER BY o.id DESC').fetchall()
   self.reply([dict(x) for x in rows if x['branch_id'] in ids and (u['role']!='master' or x['master_id']==u['id'])]);return
  if p=='/api/orders' and self.command=='POST':
   if u['role']=='master':self.reply({'error':'Создание доступно приёмщику'},403);return
   if int(data['branch_id']) not in ids:self.reply({'error':'Нет доступа к филиалу'},403);return
   for key in ('client','phone','device','fault'):
    if not str(data.get(key,'')).strip():raise ValueError('Заполните клиента, телефон, устройство и неисправность')
   master=int(data['master_id']) if data.get('master_id') else None
   if master and not c.execute("SELECT 1 FROM users WHERE id=? AND active=1 AND (role='owner' OR EXISTS(SELECT 1 FROM access WHERE user_id=users.id AND branch_id=?))",(master,int(data['branch_id']))).fetchone():raise ValueError('Мастер не имеет доступа к филиалу')
   keys=['branch_id','client','phone','device','serial','appearance','equipment','fault','comment','master_id','deadline','estimate']
   values=[data.get(k,'') for k in keys];values[0]=int(data['branch_id']);values[9]=master;values[11]=money(data.get('estimate',0))
   oid=c.execute('INSERT INTO orders('+','.join(keys)+',status) VALUES('+','.join('?' for _ in range(13))+')',values+['Новый']).lastrowid;event(oid,'Заказ создан');self.reply({'id':oid});return
  if p.startswith('/api/orders/'):
   parts=p.split('/');oid=int(parts[3]);o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
   if not o or o['branch_id'] not in ids or (u['role']=='master' and o['master_id']!=u['id']):self.reply({'error':'Заказ недоступен'},403);return
   if self.command=='GET':
    self.reply({'order':dict(o),'items':[dict(x) for x in c.execute('SELECT * FROM items WHERE order_id=?',(oid,))],'payments':[dict(x) for x in c.execute('SELECT * FROM payments WHERE order_id=?',(oid,))],'events':[dict(x) for x in c.execute('SELECT e.*,u.name author FROM events e JOIN users u ON u.id=e.user_id WHERE order_id=? ORDER BY e.id DESC',(oid,))]});return
   action=parts[4]
   if action=='status':
    if data['status'] not in STATUSES:raise ValueError('Неизвестный статус')
    if data['status'] in ('Выдан','Выдан без ремонта'):
     if u['role']=='master':raise ValueError('Выдача доступна приёмщику')
     total=c.execute('SELECT coalesce(sum(quantity*price),0) FROM items WHERE order_id=?',(oid,)).fetchone()[0];paid=c.execute('SELECT coalesce(sum(amount),0) FROM payments WHERE order_id=?',(oid,)).fetchone()[0]
     if paid<total:raise ValueError('Перед выдачей погасите задолженность')
    changed=c.execute('UPDATE orders SET status=?,version=version+1 WHERE id=? AND version=?',(data['status'],oid,data['version'])).rowcount
    if not changed:raise ValueError('Заказ изменён другим сотрудником. Откройте его повторно')
    event(oid,o['status']+' → '+data['status'])
   elif action=='comment':
    if not data['text'].strip():raise ValueError('Пустой комментарий')
    event(oid,data['text'].strip())
   elif action=='items':
    if o['status'] in ('Выдан','Выдан без ремонта'):raise ValueError('Заказ уже выдан')
    quantity=int(data['quantity']);price=money(data['price']);warranty=int(data.get('warranty',0))
    if quantity<1 or price<0 or warranty<0 or not data['name'].strip() or data['kind'] not in ('Работа','Материал'):raise ValueError('Проверьте позицию')
    c.execute('INSERT INTO items(order_id,name,kind,quantity,price,warranty) VALUES(?,?,?,?,?,?)',(oid,data['name'],data['kind'],quantity,price,warranty));event(oid,'Добавлено: '+data['name'])
   elif action=='payments':
    if u['role']=='master':self.reply({'error':'Приём оплаты доступен приёмщику'},403);return
    amount=money(data['amount'])
    if amount<=0 or data['method'] not in ('Наличные','Карта','Перевод'):raise ValueError('Проверьте оплату')
    c.execute('INSERT INTO payments(order_id,amount,method) VALUES(?,?,?)',(oid,amount,data['method']));event(oid,'Оплата: '+format(amount/100,'.2f')+' ₽, '+data['method'])
   else:raise ValueError('Неизвестное действие')
   self.reply({'ok':True});return
  self.reply({'error':'Не найдено'},404)
if __name__=='__main__':
 initialize();ThreadingHTTPServer((os.environ.get('CRM_HOST','127.0.0.1'),int(os.environ.get('PORT','8000'))),Handler).serve_forever()
