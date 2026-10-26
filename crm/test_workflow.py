import urllib.parse
import unittest, tempfile, subprocess, os, sys, time, json, urllib.request, urllib.error, http.cookiejar, socket
from pathlib import Path

class Workflow(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory()
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  cls.url=f'http://127.0.0.1:{port}/api/'
  cls.process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py'))],env={**os.environ,'CRM_DB':cls.tmp.name+'/test.sqlite3','PORT':str(port)},stdout=subprocess.DEVNULL)
  cls.owner=cls.client()
  for _ in range(80):
   try:cls.call(cls.owner,'setup');break
   except OSError:time.sleep(.05)
 @classmethod
 def tearDownClass(cls):cls.process.terminate();cls.process.wait();cls.tmp.cleanup()
 @staticmethod
 def client():return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 @classmethod
 def call(cls,client,path,data=None):
  req=urllib.request.Request(cls.url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
  try:
   with client.open(req) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def test_repair_and_permissions(self):
  a=self.owner
  self.assertEqual(self.call(a,'orders')[0],401)
  self.assertEqual(self.call(a,'setup',{'name':'Владелец','email':'owner@example.test','password':'test-password-123','branch':'Центр'})[0],200)
  self.assertEqual(self.call(a,'setup',{'name':'Взлом'})[0],401)
  self.assertEqual(self.call(a,'login',{'email':'owner@example.test','password':'wrong'})[0],401)
  self.assertEqual(self.call(a,'login',{'email':'owner@example.test','password':'test-password-123'})[0],200)
  self.assertEqual(self.call(a,'branches',{'name':'Север'})[0],200)
  self.assertEqual(self.call(a,'users',{'name':'Мастер','email':'master@example.test','password':'test-password-123','role':'master','branches':[1]})[0],200)
  self.assertEqual(self.call(a,'users',{'name':'Приёмщик','email':'manager@example.test','password':'test-password-123','role':'manager','branches':[2]})[0],200)
  code,created=self.call(a,'orders',{'branch_id':1,'client':'Тестовый клиент','phone':'+70000000000','device':'Ноутбук','fault':'Не включается','master_id':2,'estimate':'5500.25'})
  self.assertEqual(code,200);oid=created['id'];base='orders/'+str(oid)
  master=self.client();self.call(master,'login',{'email':'master@example.test','password':'test-password-123'})
  manager=self.client();self.call(manager,'login',{'email':'manager@example.test','password':'test-password-123'})
  self.assertEqual(self.call(manager,base)[0],403)
  self.assertEqual(self.call(manager,'orders')[1],[])
  self.assertEqual(self.call(master,'users',{'disable':1})[0],403)
  self.assertEqual(self.call(master,base+'/items',{'name':'Ремонт питания','kind':'Работа','quantity':1,'price':'5500.25','warranty':90})[0],200)
  self.assertEqual(self.call(master,base+'/payments',{'amount':1,'method':'Наличные'})[0],403)
  self.assertEqual(self.call(a,base+'/status',{'status':'Выдан','version':1})[0],400)
  self.assertEqual(self.call(a,base+'/payments',{'amount':'NaN','method':'Карта'})[0],400)
  self.assertEqual(self.call(a,base+'/payments',{'amount':'5500.25','method':'Карта'})[0],200)
  self.assertEqual(self.call(a,base+'/status',{'status':'Готов к выдаче','version':1})[0],200)
  self.assertEqual(self.call(a,base+'/status',{'status':'Ремонт','version':1})[0],400)
  self.assertEqual(self.call(a,base+'/status',{'status':'Выдан','version':2})[0],200)
  self.assertEqual(self.call(a,base+'/comment',{'text':'Клиент забрал устройство'})[0],200)
  detail=self.call(a,base)[1];self.assertEqual(detail['order']['status'],'Выдан');self.assertEqual(detail['payments'][0]['amount'],550025);self.assertEqual(len(detail['events']),6)
  self.assertEqual(self.call(a,'users',{'disable':2})[0],200)
  self.assertEqual(self.call(master,'orders')[0],401)
  self.assertEqual(self.call(a,'orders')[1][0]['paid'],550025)

class ClientCatalogWorkflow(Workflow):
 def test_repair_and_permissions(self):
  a=self.owner
  self.call(a,'setup',{'name':'Владелец','email':'owner@example.test','password':'test-password-123','branch':'Центр'})
  self.call(a,'login',{'email':'owner@example.test','password':'test-password-123'})
  self.assertEqual(self.call(self.client(),'catalog')[0],401)
  self.call(a,'branches',{'name':'Север'})
  self.call(a,'users',{'name':'Приёмщик','email':'manager@example.test','password':'test-password-123','role':'manager','branches':[2]})
  self.call(a,'users',{'name':'Мастер','email':'master@example.test','password':'test-password-123','role':'master','branches':[1]})
  for value in ['Apple iPhone 13','  APPLE   IPHONE 13  ']:
   self.assertEqual(self.call(a,'catalog',{'kind':'device','value':value})[0],200)
  self.assertEqual(len(self.call(a,'catalog')[1]),1)
  self.assertEqual(self.call(a,'catalog',{'kind':'unknown','value':'test'})[0],400)
  self.assertEqual(self.call(a,'catalog',{'kind':'fault','value':' '})[0],400)
  self.assertEqual(self.call(a,'catalog',{'kind':'fault','value':'x'*301})[0],400)
  order={'branch_id':1,'client':'Иванов Иван Иванович','phone':'+7 (900) 123-45-67','device':'Apple iPhone 13','fault':'Не включается; Нет зарядки','appearance':'Царапины; Потёртости'}
  self.assertEqual(self.call(a,'orders',order)[0],200)
  for term in ['иванов','ИВАНОВ','900123','8 (900) 123-45-67','+7 (900) 123-45-67']:
   result=self.call(a,'clients?q='+urllib.parse.quote(term))[1]
   self.assertEqual(len(result),1,term);self.assertEqual(result[0]['name'],order['client']);self.assertEqual(result[0]['phone'],order['phone'])
  self.assertEqual(self.call(a,'clients?q='+urllib.parse.quote('несуществующий'))[1],[])
  manager=self.client();self.call(manager,'login',{'email':'manager@example.test','password':'test-password-123'})
  self.assertEqual(len(self.call(manager,'clients?q='+urllib.parse.quote('Иванов'))[1]),1)
  self.assertEqual(self.call(manager,'orders')[1],[])
  self.assertEqual(self.call(a,'orders',{**order,'phone':'8 900 123 45 67'})[0],200)
  self.assertEqual(len(self.call(a,'clients?q=900123')[1]),1)
  catalog=self.call(a,'catalog')[1]
  self.assertEqual(len(catalog),5)
  self.assertEqual({x['value'] for x in catalog if x['kind']=='appearance'},{'Царапины','Потёртости'})
  master=self.client();self.call(master,'login',{'email':'master@example.test','password':'test-password-123'})
  self.assertEqual(self.call(master,'clients?q=900123')[0],403)
  self.assertEqual(self.call(master,'catalog')[0],403)
  self.assertEqual(self.call(a,'orders',{**order,'phone':'abc'})[0],400)
  self.assertEqual(len(self.call(a,'orders')[1]),2)
  # Restart to verify persistent clients and options and migration repeatability.
  self.process.terminate();self.process.wait()
  self.__class__.process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py'))],env={**os.environ,'CRM_DB':self.tmp.name+'/test.sqlite3','PORT':self.url.split(':')[-1].split('/')[0]},stdout=subprocess.DEVNULL)
  for _ in range(80):
   try:self.call(a,'setup');break
   except OSError:time.sleep(.05)
  self.assertEqual(len(self.call(a,'clients?q=900123')[1]),1)
  self.assertEqual(len(self.call(a,'catalog')[1]),5)

class Migration(unittest.TestCase):
 def test_existing_orders_backfilled_without_changes(self):
  import importlib.util,sqlite3
  spec=importlib.util.spec_from_file_location('crm_server',Path(__file__).with_name('server.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as directory:
   module.DB=directory+'/old.sqlite3';module.initialize()
   with module.connection() as c:
    c.execute("DELETE FROM migrations")
    c.execute("INSERT INTO branches(name) VALUES('Центр')")
    c.execute("INSERT INTO orders(branch_id,client,phone,device,fault,appearance,status) VALUES(1,'Петров Пётр','8 (900) 555-66-77','Ноутбук','Не включается','Царапины','Новый')")
    before=tuple(c.execute('SELECT * FROM orders').fetchone())
   module.initialize();module.initialize()
   with module.connection() as c:
    self.assertEqual(tuple(c.execute('SELECT * FROM orders').fetchone()),before)
    self.assertEqual(c.execute('SELECT normalized_phone FROM clients').fetchone()[0],'79005556677')
    self.assertEqual(c.execute('SELECT count(*) FROM catalog').fetchone()[0],3)

class UpgradeMigration(unittest.TestCase):
 def test_diagnosis_added_to_previous_database(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('upgrade_server',Path(__file__).with_name('server.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as directory:
   module.DB=directory+'/previous.sqlite3';module.initialize()
   with module.connection() as c:
    c.execute("ALTER TABLE orders DROP COLUMN diagnosis")
    c.execute("DELETE FROM migrations WHERE name='work_catalog_v1'")
    c.execute("INSERT INTO branches(name) VALUES('Центр')")
    c.execute("INSERT INTO orders(branch_id,client,phone,device,fault,status) VALUES(1,'Иванов','+79001234567','Ноутбук','Не включается','Новый')")
    c.execute("INSERT INTO items(order_id,name,kind,quantity,price,warranty) VALUES(1,'Ремонт питания','Работа',1,500000,90)")
    before=dict(c.execute('SELECT * FROM orders').fetchone())
   module.initialize();module.initialize()
   with module.connection() as c:
    after=dict(c.execute('SELECT * FROM orders').fetchone());self.assertEqual(after.pop('diagnosis'),'');self.assertEqual(before,after)
    self.assertEqual(c.execute("SELECT count(*) FROM catalog WHERE kind='work'").fetchone()[0],1)
    self.assertEqual(c.execute('SELECT price FROM items').fetchone()[0],500000)

class StockDocumentsWorkflow(Workflow):
 def test_repair_and_permissions(self):
  from concurrent.futures import ThreadPoolExecutor
  a=self.owner
  self.call(a,'setup',{'name':'Владелец','email':'owner@example.test','password':'test-password-123','branch':'Центр'})
  self.call(a,'login',{'email':'owner@example.test','password':'test-password-123'})
  self.call(a,'branches',{'name':'Север'})
  self.call(a,'users',{'name':'Мастер','email':'master@example.test','password':'test-password-123','role':'master','branches':[1]})
  self.call(a,'users',{'name':'Приёмщик','email':'manager@example.test','password':'test-password-123','role':'manager','branches':[2]})
  master=self.client();self.call(master,'login',{'email':'master@example.test','password':'test-password-123'})
  manager=self.client();self.call(manager,'login',{'email':'manager@example.test','password':'test-password-123'})
  order={'branch_id':1,'client':'Иванов','phone':'89001234567','device':'iPhone','fault':'Нет питания','appearance':'Потёртости','equipment':'Чехол','master_id':2}
  self.assertEqual(self.call(a,'orders',{**order,'phone':'+12025550123'})[0],400)
  self.assertEqual(self.call(a,'orders',{**order,'phone':'+7900'})[0],400)
  code,created=self.call(a,'orders',order);self.assertEqual(code,200);base='orders/'+str(created['id'])
  self.assertEqual(self.call(a,base)[1]['order']['phone'],'+7 (900) 123-45-67')
  self.assertEqual(self.call(master,'works',{'value':'Ремонт питания'})[0],200)
  self.assertEqual(self.call(a,base+'/items',{'name':'Ремонт питания','kind':'Работа','price':'5500.25','quantity':1,'warranty':90})[0],200)
  self.assertEqual(self.call(a,base+'/items',{'name':'Старый материал','kind':'Материал','price':'100','quantity':1,'warranty':0})[0],200)
  self.assertEqual(len(self.call(a,'works')[1]),1)
  work=self.call(a,base)[1]['items'][0]['id']
  payload={'branch_id':1,'name':'Секретная запчасть <script>','sku':'AKB-13','quantity':2,'unit_cost':'1000.10'}
  self.assertEqual(self.call(master,'stock',payload)[0],403)
  self.assertEqual(self.call(manager,'stock',payload)[0],403)
  self.assertEqual(self.call(a,'stock',{**payload,'quantity':1.5})[0],400)
  code,part=self.call(a,'stock',payload);self.assertEqual(code,200);sid=part['id']
  self.assertEqual(self.call(a,'stock',payload)[0],400)
  other=self.call(a,'stock',{**payload,'branch_id':2,'sku':'OTHER'})[1]['id']
  self.assertEqual(self.call(manager,'stock')[1][0]['branch_id'],2)
  self.assertEqual(self.call(manager,'stock/'+str(sid)+'/receive',{'quantity':1,'unit_cost':10})[0],403)
  self.assertEqual(self.call(master,base+'/parts',{'item_id':work,'stock_id':other,'quantity':1})[0],400)
  self.assertEqual(self.call(master,base+'/parts',{'item_id':work+1,'stock_id':sid,'quantity':1})[0],400)
  self.assertEqual(self.call(master,base+'/parts',{'item_id':work,'stock_id':sid,'quantity':3})[0],400)
  self.assertEqual(self.call(a,base)[1]['parts'],[])
  allocation={'item_id':work,'stock_id':sid,'quantity':1}
  self.assertEqual(self.call(master,base+'/parts',allocation)[0],200)
  detail=self.call(a,base)[1];self.assertEqual(detail['parts'][0]['unit_cost'],100010)
  self.assertEqual(self.call(a,'orders')[1][0]['total'],560025)
  self.assertEqual(self.call(a,'stock/'+str(sid)+'/receive',{'quantity':1,'unit_cost':'2000.30'})[0],200)
  part=next(p for p in self.call(a,'stock')[1] if p['id']==sid)
  self.assertEqual(part['quantity'],2);self.assertEqual(part['unit_cost'],150020)
  self.assertEqual(self.call(a,base)[1]['parts'][0]['unit_cost'],100010)
  # Competing users cannot both consume more than the available stock.
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(lambda client:self.call(client,base+'/parts',{**allocation,'quantity':2})[0],[a,master]))
  self.assertEqual(sorted(results),[200,400])
  self.assertEqual(next(p for p in self.call(a,'stock')[1] if p['id']==sid)['quantity'],0)
  self.assertEqual(sum(p['quantity'] for p in self.call(a,base)[1]['parts']),3)
  self.assertEqual(self.call(a,base+'/diagnosis',{'text':'Повреждение цепи <script>alert(1)</script>','version':1})[0],200)
  self.assertEqual(self.call(a,base+'/diagnosis',{'text':'Устаревшее','version':1})[0],400)
  def document(client,kind):
   with client.open(self.url+base+'/print?type='+kind) as response:return response.read().decode()
  reception=document(a,'intake');self.assertIn('Акт приема на диагностику',reception);self.assertIn('Потёртости',reception);self.assertIn('Чехол',reception)
  diagnosis=document(master,'diagnosis');self.assertIn('Повреждение цепи &lt;script&gt;',diagnosis);self.assertNotIn('<script>',diagnosis)
  completion=document(a,'completion');self.assertIn('Ремонт питания',completion);self.assertIn('90 дн.',completion);self.assertIn('5 500.25',completion);self.assertNotIn('Секретная запчасть',completion);self.assertNotIn('Старый материал',completion);self.assertNotIn('Прибыль',completion);self.assertNotIn('Себестоимость',completion)
  self.assertEqual(self.call(manager,base+'/print?type=completion')[0],403)
  self.assertEqual(self.call(self.client(),base+'/print?type=completion')[0],401)
  self.call(a,base+'/payments',{'amount':'5600.25','method':'Карта'})
  self.assertEqual(self.call(a,base+'/status',{'status':'Выдан','version':2})[0],200)
  self.assertEqual(self.call(a,base+'/parts',allocation)[0],400)
  with __import__('sqlite3').connect(self.tmp.name+'/test.sqlite3') as c:
   self.assertEqual(c.execute('SELECT sum(quantity) FROM stock_movements WHERE stock_id=?',(sid,)).fetchone()[0],0)

if __name__=='__main__':unittest.main(verbosity=2)
