"""Accruals are frozen on issue. All amounts use integer kopecks."""
from datetime import datetime, date, timedelta, timezone

def accrue_salary(c,oid,timestamp):
 for item in c.execute("SELECT * FROM items WHERE order_id=? AND kind='Работа' AND deleted=0",(oid,)).fetchall():
  free=c.execute('SELECT no_payment FROM orders WHERE id=?',(oid,)).fetchone()[0]
  revenue=0 if free else item['quantity']*item['price']
  cost=c.execute('SELECT coalesce(sum(quantity*unit_cost),0) FROM item_parts WHERE item_id=?',(item['id'],)).fetchone()[0]
  net=revenue-cost
  share=(max(0,net)*40+50)//100
  c.execute('INSERT OR IGNORE INTO earnings(item_id,master_id,revenue,cost,master_share,service_share,issued_at) VALUES(?,?,?,?,?,?,?)',(item['id'],item['master_id'],revenue,cost,share,net-share,timestamp))

def dashboard(c,user,branch_ids,query):
 today=datetime.now(timezone(timedelta(hours=3))).date()
 start=date.fromisoformat(query.get('from',[today.isoformat()])[0]);end=date.fromisoformat(query.get('to',[today.isoformat()])[0])
 if end<start:raise ValueError('Конец периода должен быть не раньше начала')
 bid=query.get('branch',[''])[0]
 if bid:
  if int(bid) not in branch_ids:raise ValueError('Нет доступа к филиалу')
  branch_ids=[int(bid)]
 lower=(datetime.combine(start,datetime.min.time())-timedelta(hours=3)).isoformat(' ')
 upper=(datetime.combine(end+timedelta(days=1),datetime.min.time())-timedelta(hours=3)).isoformat(' ')
 allowed={o['id']:o for o in c.execute('SELECT id,branch_id,master_id,created,issued_at,status FROM orders WHERE deleted=0') if o['branch_id'] in branch_ids and (user['role']!='master' or o['master_id']==user['id'] or c.execute('SELECT 1 FROM items WHERE order_id=? AND master_id=? AND deleted=0',(o['id'],user['id'])).fetchone())}
 accepted=sum(lower<=o['created']<upper for o in allowed.values())
 issued=sum(bool(o['issued_at']) and lower<=o['issued_at']<upper for o in allowed.values())
 payroll={};revenue=cost=master_total=service=0
 for r in c.execute('SELECT e.*,i.order_id,i.name work_name,u.name master_name FROM earnings e JOIN items i ON i.id=e.item_id LEFT JOIN users u ON u.id=e.master_id WHERE e.issued_at>=? AND e.issued_at<? ORDER BY e.issued_at DESC',(lower,upper)):
  if r['order_id'] not in allowed or (user['role']=='master' and r['master_id']!=user['id']):continue
  revenue+=r['revenue'];cost+=r['cost'];master_total+=r['master_share'];service+=r['service_share']
  person=payroll.setdefault(r['master_id'],{'id':r['master_id'],'name':r['master_name'] or 'Не назначен (старые заказы)','works':0,'revenue':0,'cost':0,'salary':0,'service':0,'details':[]})
  person['works']+=1;person['revenue']+=r['revenue'];person['cost']+=r['cost'];person['salary']+=r['master_share'];person['service']+=r['service_share']
  person['details'].append({'order_id':r['order_id'],'name':r['work_name'],'date':r['issued_at'],'salary':r['master_share']})
 return {'from':start.isoformat(),'to':end.isoformat(),'accepted':accepted,'issued':issued,'revenue':revenue,'cost':cost,'profit':revenue-cost,'salary':master_total,'service':service,'payroll':list(payroll.values())}
