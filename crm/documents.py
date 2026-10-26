"""Customer-facing documents: private parts and purchase costs never enter templates."""
from html import escape
from datetime import datetime, timezone, timedelta

TITLES = {
 'intake': 'Акт приема на диагностику',
 'completion': 'Акт выполненных работ',
 'diagnosis': 'Акт диагностики',
}

def render_document(kind, order, items, branch):
 if kind not in TITLES:raise ValueError('Выберите тип документа')
 e=lambda value:escape(str(value or '—'))
 rub=lambda value:f'{value/100:,.2f}'.replace(',',' ')+' ₽'
 def line(title,value):return f'<p><b>{e(title)}:</b> {e(value)}</p>'
 title=TITLES[kind]
 shared=line('Клиент',order['client'])+line('Телефон',order['phone'])+line('Устройство',order['device'])+line('Серийный номер / IMEI',order['serial'])
 if kind=='intake':
  content=shared+line('Внешнее состояние',order['appearance'])+line('Комплектация',order['equipment'])+line('Заявленная неисправность',order['fault'])+line('Ориентировочная стоимость',rub(order['estimate']))+line('Дата приема',order['created'])
  signature='Устройство передал / принял'
 elif kind=='diagnosis':
  if not order.get('diagnosis','').strip():raise ValueError('Сначала сохраните заключение диагностики')
  content=shared+line('Заявленная неисправность',order['fault'])+'<h2>Заключение диагностики</h2><div class="conclusion">'+e(order['diagnosis'])+'</div>'
  signature='Заключение выдал / получил'
 else:
  works=[i for i in items if i['kind']=='Работа']
  rows=''.join(f'<tr><td>{e(i["name"])}</td><td>{i["quantity"]}</td><td>{rub(i["price"])}</td><td>{rub(i["quantity"]*i["price"])}</td><td>{i["warranty"]} дн.</td></tr>' for i in works)
  total=sum(i['quantity']*i['price'] for i in works)
  content=shared+'<table><thead><tr><th>Выполненная работа</th><th>Кол.</th><th>Цена</th><th>Сумма</th><th>Гарантия</th></tr></thead><tbody>'+rows+'</tbody></table><p class="total">Итого за работы: '+rub(total)+'</p>'
  signature='Работы сдал / принял'
 today=datetime.now(timezone(timedelta(hours=3))).strftime('%d.%m.%Y')
 return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} — Р-{order['id']}</title><style>
 body{{font:14px Arial,sans-serif;color:#111;max-width:900px;margin:35px auto;padding:0 24px}}h1{{font-size:24px}}h2{{font-size:18px}}p,.conclusion{{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}}table{{border-collapse:collapse;width:100%;margin:30px 0}}td,th{{border:1px solid #aaa;text-align:left;padding:10px;overflow-wrap:anywhere}}.total{{text-align:right;font-weight:bold}}.signatures{{display:flex;justify-content:space-between;gap:30px;margin-top:70px}}button{{padding:12px 18px;cursor:pointer}}@media print{{button{{display:none}}body{{margin:0;max-width:none;padding:0}}tr{{break-inside:avoid}}}}@page{{size:A4;margin:18mm}}
 </style></head><body><button onclick="window.print()">Печать / сохранить PDF</button><h1>{title}</h1><p>Заказ № Р-{order['id']} · {today}</p>{line('Сервисный центр / филиал',branch)}{content}<p>{signature}</p><div class="signatures"><span>Сотрудник __________________</span><span>Клиент __________________</span></div></body></html>'''
