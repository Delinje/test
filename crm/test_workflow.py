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

if __name__=='__main__':unittest.main(verbosity=2)
