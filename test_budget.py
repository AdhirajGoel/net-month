import copy,csv,io,json,tempfile,unittest
from pathlib import Path
from budget_server import *

class BudgetTests(unittest.TestCase):
 def source(self):
  return 'Date,Account,Description,Category,Tags,Amount\n2026-09-08,Card,Example Mobile,Telephone,,-299.00\n2026-09-08,Card,Example Mobile,Telephone,,-299.00\n2026-10-09,Card,Example Mobile,Telephone,,299.00\n2026-10-09,Card,Payment,Credit Card Payments,,100.00\n'
 def initial(self):
  s=empty();p=preview_import(s,self.source(),'source.csv');commit_import(s,p,{str(t['source_row']):'add' for t in p['rows']});return s
 def manual(self,s,date,amount,kind='expense',category='Gas',description='Manual test'):
  mutate(s,'transaction',dict(date=date,amount=amount,kind=kind,category=category,description=description,account='Manual',allocations=[]));return s['transactions'][-1]
 def test_roundtrip_preserves_source_and_duplicates(self):
  with tempfile.TemporaryDirectory() as d:
   s=self.initial();store=Store(d);store.save(s);self.assertEqual(s,store.load());self.assertEqual(len(store.load()['transactions']),4)
   self.assertTrue(preview_import(s,self.source(),'renamed.csv')['already_imported'])
   store.save(s);self.assertEqual(len(list((Path(d)/'backups').glob('*.csv'))),1)
 def test_refund_crossmonth_and_partial_repayment(self):
  s=self.initial();expense=s['transactions'][0];refund=s['transactions'][2]
  mutate(s,'links',{'id':refund['id'],'links':[{'expense_id':expense['id'],'amount':'299'}]})
  sums=snapshot(s)['summaries'];self.assertEqual(sums['2026-09']['total'],29900);self.assertEqual(sums['2026-10']['total'],0)
  self.assertEqual(sums['2026-09']['credits'],29900)
  gas=self.manual(s,'2026-09-10','-60');repay=self.manual(s,'2026-10-10','30','reimbursement')
  mutate(s,'links',{'id':repay['id'],'links':[{'expense_id':gas['id'],'amount':'30'}]})
  self.assertEqual(snapshot(s)['summaries']['2026-09']['categories']['Gas']['net'],3000)
 def test_allocation_cent_rounding_and_credit_restatement(self):
  s=empty();t=self.manual(s,'2026-09-01','-10.01')
  mutate(s,'transaction',dict(id=t['id'],date=t['date'],amount='-10.01',description=t['description'],kind='expense',category='Gas',allocations=[{'month':'2026-09','amount':'3.34'},{'month':'2026-10','amount':'3.34'},{'month':'2026-11','amount':'3.33'}]))
  c=self.manual(s,'2026-12-01','1.00','refund')
  mutate(s,'links',{'id':c['id'],'links':[{'expense_id':t['id'],'amount':'1.00'}]})
  snap=snapshot(s);self.assertEqual(sum(v['credits'] for v in snap['summaries'].values()),100)
  self.assertEqual(sum(v['total'] for v in snap['summaries'].values()),901)
  self.assertEqual([snap['summaries'][m]['credits'] for m in ['2026-09','2026-10','2026-11']],[34,33,33])
 def test_invalid_edits_fail(self):
  s=self.initial();expense=s['transactions'][0];credit=s['transactions'][2]
  with self.assertRaises(Invalid):mutate(copy.deepcopy(s),'links',{'id':credit['id'],'links':[{'expense_id':expense['id'],'amount':'300'}]})
  with self.assertRaises(Invalid):mutate(copy.deepcopy(s),'transaction',{'id':expense['id'],'kind':'expense','category':'Gas','allocations':[{'month':'2026-09','amount':'298'}]})
  for amount in ['NaN','Infinity','1.001']:
   with self.assertRaises(Invalid):cents(amount)
 def test_partial_links_multiple_targets(self):
  s=self.initial();credit=s['transactions'][2];a,b=s['transactions'][:2]
  mutate(s,'links',{'id':credit['id'],'links':[{'expense_id':a['id'],'amount':'100'},{'expense_id':b['id'],'amount':'150'}]})
  snap=snapshot(s);self.assertEqual(snap['summaries']['2026-09']['total'],34800);self.assertEqual(snap['summaries']['2026-10']['unresolved_cents'],4900)
 def test_overlap_choices_and_manual_reconciliation(self):
  s=empty();manual=self.manual(s,'2026-09-08','-299',description='Phone plan')
  mutate(s,'transaction',dict(id=manual['id'],date=manual['date'],amount='-299',description='Phone plan',kind='expense',category='Subscriptions',allocations=[{'month':'2026-08','amount':'299'}]))
  p=preview_import(s,self.source(),'source.csv');self.assertIn(manual['id'],p['rows'][0]['manual_matches'])
  with self.assertRaises(Invalid):commit_import(copy.deepcopy(s),p,{})
  commit_import(s,p,{'2':'replace:'+manual['id'],'3':'add'})
  self.assertEqual(len(s['transactions']),4);self.assertFalse(s['transactions'][0]['manual']);self.assertTrue(s['transactions'][0]['reconciled_manual'])
  self.assertEqual(snapshot(s)['summaries']['2026-08']['total'],29900)
  p=preview_import(s,self.source().replace('299.00','299.00',1)+'2026-11-01,Card,Coffee,Restaurants,,-5\n','overlap.csv')
  self.assertTrue(p['rows'][0]['matches']);self.assertEqual(len(p['rows'][0]['matches']),2)
 def test_budget_history_and_review(self):
  s=empty();t=self.manual(s,'2026-09-01','-60');mutate(s,'month',{'month':'2026-09','zero_categories':[c for c in CATEGORIES if c!='Gas'],'reviewed':True})
  self.assertTrue(s['months']['2026-09']['reviewed']);ensure_month(s,'2026-10');original=copy.deepcopy(s['budgets']['2026-09'])
  b={c:dollars(v) for c,v in CATEGORIES.items()};b['Gas']='500';mutate(s,'budget',{'month':'2026-10','budget':b});self.assertEqual(s['budgets']['2026-09'],original)
  c=self.manual(s,'2026-10-10','30','reimbursement');mutate(s,'links',{'id':c['id'],'links':[{'expense_id':t['id'],'amount':'30'}]});self.assertFalse(s['months']['2026-09']['reviewed'])
 def test_legacy_sign_conversion(self):
  text='Date,Original Date,Account Name,Name,Amount,Category\n2026-09-01,2026-09-01,Card,Grocer,25,Groceries\n2026-09-02,2026-09-02,Cash,Interest,-1,Income\n'
  r=parse_export(text,'old.csv');self.assertEqual([t['cents'] for t in r],[-2500,100]);self.assertEqual(r[1]['kind'],'income')
 def test_counted_duplicates_reordered_and_extra_occurrences(self):
  s=self.initial()
  lines=self.source().strip().splitlines();changed='\n'.join([lines[0],*reversed(lines[1:]),lines[1]])+'\n'
  p=preview_import(s,changed,'reordered.csv')
  self.assertEqual(sum(t['suggested_choice']=='skip' for t in p['rows']),4)
  self.assertEqual([t['suggested_choice'] for t in p['rows'] if t['cents']==-29900],['skip','skip',''])
  choices={str(t['source_row']):t['suggested_choice'] or 'add' for t in p['rows']}
  result=commit_import(s,p,choices);self.assertEqual({k:result[k] for k in ['added','skipped','reconciled']},{'added':1,'skipped':4,'reconciled':0})
  self.assertEqual(len(s['transactions']),5)
 def test_first_import_identical_rows_require_choice(self):
  s=empty();p=preview_import(s,self.source(),'source.csv')
  with self.assertRaises(Invalid):commit_import(copy.deepcopy(s),p,{})
  self.assertEqual(p['rows'][0]['batch_count'],2)
  commit_import(s,p,{'2':'add','3':'add'});self.assertEqual(len(s['transactions']),4)
 def test_fuzzy_different_account_never_defaults_skip(self):
  s=self.initial();p=preview_import(s,self.source().replace(',Card,',',Another Card,'),'other.csv')
  self.assertTrue(all(not t['suggested_choice'] for t in p['rows']))
  self.assertTrue(p['rows'][0]['matches'])
 def test_visibility_roundtrip_preserves_totals_and_links(self):
  s=self.initial();e=s['transactions'][0];c=s['transactions'][2]
  mutate(s,'links',{'id':c['id'],'links':[{'expense_id':e['id'],'amount':'299'}]})
  sums=snapshot(s)['summaries'];mutate(s,'visibility',{'excluded':['2026-09','2026-10']})
  self.assertEqual(snapshot(s)['summaries'],sums)
  self.assertTrue(all(m['excluded'] for m in s['months'].values()))
  with tempfile.TemporaryDirectory() as d:
   st=Store(d);st.save(s);s=st.load();self.assertTrue(s['months']['2026-09']['excluded'])
  ensure_month(s,'2026-11');self.assertFalse(s['months']['2026-11'].get('excluded',False))
  mutate(s,'visibility',{'excluded':[]});self.assertFalse(any(m['excluded'] for m in s['months'].values()))
  with self.assertRaises(Invalid):mutate(s,'visibility',{'excluded':['1900-01']})
 def test_combined_food_category_and_linked_credit(self):
  s=empty();t=self.manual(s,'2026-09-01','-60',category='Groceries+Food')
  c=self.manual(s,'2026-10-01','20',kind='refund')
  mutate(s,'links',{'id':c['id'],'links':[{'expense_id':t['id'],'amount':'20'}]})
  snap=snapshot(s)['summaries']['2026-09']
  self.assertEqual(snap['categories']['Groceries+Food'],{'gross':6000,'credits':2000,'net':4000,'count':1})
  self.assertEqual(snap['categories']['Groceries+Food']['net'],snap['total'])
  self.assertNotIn('food',snap)
 def test_food_and_openai_import_categories(self):
  for category in ['Groceries',*FOOD_SOURCES]:
   rows=parse_export(f'Date,Account,Description,Category,Amount\n2026-09-01,Card,Meal,{category},-20\n','food.csv')
   self.assertEqual(rows[0]['category'],'Groceries+Food')
   self.assertEqual(rows[0]['subcategory'],'')
  self.assertEqual(classify('Example service','Online Services',-10000),('review','Needs review'))
  self.assertEqual(classify('Example service','Dues & Subscriptions',10000),('refund','Subscriptions'))
  self.assertEqual(classify('Example service','Credit Card Payments',-10000),('card_payment','Card payment'))
 def test_legacy_food_migration_preserves_data_and_opt_out(self):
  s=empty()
  grocery=self.manual(s,'2026-09-01','-40',category='Groceries+Food',description='Grocer')
  food=self.manual(s,'2026-09-02','-60',category='Groceries+Food',description='Food')
  legacy=self.manual(s,'2026-09-03','-10',category='Groceries+Food',description='Legacy food')
  optout=self.manual(s,'2026-09-04','-3',category='Miscellaneous',description='Explicit opt out')
  credit=self.manual(s,'2026-10-01','20',kind='refund',category='Groceries+Food')
  mutate(s,'links',{'id':credit['id'],'links':[{'expense_id':food['id'],'amount':'20'}]})
  expected=snapshot(s)['summaries']
  with tempfile.TemporaryDirectory() as d:
   st=Store(d);st.save(s)
   with st.path.open(newline='') as f: rows=list(csv.DictReader(f))
   for r in rows:
    details=json.loads(r['details'] or '{}')
    if r['record_type']=='schema': details['version']=1
    if r['record_type']=='budget' and r['category']=='Groceries+Food': r['category']='Groceries'
    if r['record_type']=='month': details.update(reviewed=True,zero_categories=['Groceries'])
    if r['record_type']=='transaction':
     if r['id'] in [grocery['id'],credit['id']]: r['category']='Groceries'
     if r['id']==food['id']: r['category']='Miscellaneous';details['subcategory']='Food'
     if r['id']==legacy['id']: r['category']='Miscellaneous';details.pop('subcategory');details['source_category']='Restaurants'
     if r['id']==optout['id']: details['source_category']='Restaurants'
    r['details']=json.dumps(details)
   with st.path.open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
   migrated=st.load()
   self.assertEqual(snapshot(migrated)['summaries'],expected)
   self.assertEqual(migrated['allocations'],s['allocations']);self.assertEqual(migrated['links'],s['links'])
   self.assertEqual(tx_by_id(migrated,optout['id'])['category'],'Miscellaneous')
   self.assertEqual(tx_by_id(migrated,legacy['id'])['source_category'],'Restaurants')
   self.assertEqual(migrated['budgets'],s['budgets'])
   st.save(migrated);self.assertEqual(st.load(),migrated)
 def test_legacy_accounts_with_same_name_are_not_exact_matches(self):
  text='Date,Original Date,Account Name,Institution Name,Account Number,Name,Amount,Category\n2026-09-01,2026-09-01,Checking,Bank A,1111,Coffee,5,Restaurants\n'
  s=empty();p=preview_import(s,text,'a.csv');commit_import(s,p,{})
  for changed in [text.replace('1111','2222'),text.replace('Bank A','Bank B')]:
   p=preview_import(s,changed,'b.csv');self.assertFalse(p['rows'][0]['exact_matches']);self.assertEqual(p['rows'][0]['suggested_choice'],'');self.assertTrue(p['rows'][0]['matches'])
  # Pre-upgrade legacy rows without account identity can only be fuzzy matches.
  old=s['transactions'][0];old['account']='Checking';old.pop('source_account_identity');old['fingerprint']=fingerprint(old)
  p=preview_import(s,text+'2026-09-02,2026-09-02,Checking,Bank A,1111,Lunch,10,Restaurants\n','c.csv')
  self.assertFalse(p['rows'][0]['exact_matches']);self.assertEqual(p['rows'][0]['suggested_choice'],'')
 def test_malformed_exports_fail_safely_and_large_fields_parse(self):
  for text in ['Date,Account,Description,Category,Amount,Amount\n2026-09-01,Card,Lunch,Restaurants,-1,-2\n',
               'Date,Account,Description,Category,Amount\n2026-09-01,Card,Lunch,Restaurants,-1,extra\n',
               'Date,Account,Description,Category,Amount\n2026-09-01,Card,"unclosed,Restaurants,-1\n']:
   with self.assertRaises(Invalid):parse_export(text,'bad.csv')
  text='Date,Account,Description,Category,Amount\n2026-09-01,Card,'+'x'*150000+',Restaurants,-1\n'
  self.assertEqual(len(parse_export(text,'large.csv')),1)
 def test_corrupt_metadata_fails_without_overwrite(self):
  for details in ['[]','null','42']:
   with tempfile.TemporaryDirectory() as d:
    st=Store(d);st.save(self.initial());text=st.path.read_text();rows=list(csv.DictReader(io.StringIO(text)));rows[0]['details']=details
    with st.path.open('w',newline='') as f:
     w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
    before=st.path.read_bytes()
    with self.assertRaises(Invalid):st.load()
    self.assertEqual(st.path.read_bytes(),before)
 def test_missing_or_duplicate_schema_fails(self):
  with tempfile.TemporaryDirectory() as d:
   st=Store(d);st.save(self.initial());rows=list(csv.DictReader(io.StringIO(st.path.read_text())))
   for bad in [[r for r in rows if r['record_type']!='schema'],rows+[rows[0]],[]]:
    with st.path.open('w',newline='') as f:
     w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(bad)
    with self.assertRaises(Invalid):st.load()
 def test_corrupt_csv_fails_without_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   st=Store(d);st.path.write_text('wrong,header\n1,2\n')
   with self.assertRaises(Invalid):st.load()
   self.assertEqual(st.path.read_text(),'wrong,header\n1,2\n')
 def test_failed_disk_replace_preserves_saved_data(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   st=Store(d);s=self.initial();st.save(s);before=st.path.read_bytes()
   self.manual(s,'2026-10-12','-12')
   with patch('budget_server.os.replace',side_effect=OSError('Simulated disk failure')):
    with self.assertRaises(OSError):st.save(s)
   self.assertEqual(st.path.read_bytes(),before)
   self.assertEqual(list(Path(d).glob('.dashboard-*')),[])
   self.assertEqual(next((Path(d)/'backups').glob('*.csv')).read_bytes(),before)

class RecurringTests(unittest.TestCase):
 def imported(self,rows):
  s=empty();text='Date,Account,Description,Category,Amount\n'+'\n'.join(rows)+'\n'
  p=preview_import(s,text,'test.csv');commit_import(s,p,{str(t['source_row']):'add' for t in p['rows']});return s
 def test_second_import_detects_prior_and_new_charge(self):
  s=self.imported(['2026-09-15,Card,Example App,Online Services,-20'])
  self.assertEqual(s['transactions'][0]['kind'],'review')
  text='Date,Account,Description,Category,Amount\n2026-10-16,Card,EXAMPLE APP,Online Services,-20\n'
  p=preview_import(s,text,'next.csv');r=commit_import(s,p,{})
  self.assertEqual(r['detected_subscriptions'],2)
  self.assertTrue(all(t['category']=='Subscriptions' for t in s['transactions']))
  self.assertEqual(snapshot(s)['summaries']['2026-09']['total'],2000)
  self.assertEqual(len(s['allocations']),2)
  detect_subscriptions(s);self.assertEqual(len(s['allocations']),2);validate(s)
  with tempfile.TemporaryDirectory() as d:
   st=Store(d);st.save(s);self.assertEqual(st.load(),s)
 def test_year_boundary_wallet_normalization_and_month_end(self):
  for dates in [('2026-12-31','2027-01-31'),('2026-01-31','2026-02-28')]:
   s=self.imported([f'{dates[0]},Card,AplPay Example.App,Online Services,-20',f'{dates[1]},New Card,Example App,Online Services,-20'])
   self.assertTrue(all(t.get('auto_subscription') for t in s['transactions']))
 def test_nonmonthly_or_price_changes_do_not_match(self):
  for dates,amount in [(('2026-09-01','2026-11-01'),'-20'),(('2026-09-01','2026-10-29'),'-20'),(('2026-09-15','2026-10-15'),'-21'),(('2026-09-15','2026-09-16'),'-20')]:
   s=self.imported([f'{dates[0]},Card,Vendor,Online Services,-20',f'{dates[1]},Card,Vendor,Online Services,{amount}'])
   self.assertFalse(any(t.get('auto_subscription') for t in s['transactions']))
 def test_food_needs_and_duplicate_months_do_not_match(self):
  for category in ['Restaurants','Groceries','Gasoline/Fuel','Rent','Utilities','Auto Insurance','Credit Card Payments','Transfers']:
   s=self.imported([f'2026-09-01,Card,Vendor,{category},-20',f'2026-10-01,Card,Vendor,{category},-20'])
   self.assertFalse(any(t.get('auto_subscription') for t in s['transactions']))
  s=self.imported(['2026-09-01,Card,Vendor,Online Services,-20','2026-09-01,Card,Vendor,Online Services,-20','2026-10-01,Card,Vendor,Online Services,-20'])
  self.assertFalse(any(t.get('auto_subscription') for t in s['transactions']))
 def test_manual_override_and_hidden_month_evidence(self):
  s=self.imported(['2026-09-01,Card,Vendor,Online Services,-20','2026-10-01,Card,Vendor,Online Services,-20'])
  mutate(s,'visibility',{'excluded':['2026-09']});detect_subscriptions(s)
  self.assertEqual(s['transactions'][0]['category'],'Subscriptions')
  t=s['transactions'][0];mutate(s,'transaction',{'id':t['id'],'kind':'expense','category':'Miscellaneous','allocations':[{'month':'2026-09','amount':'20'}]})
  self.assertEqual(t['category'],'Miscellaneous');self.assertFalse(t.get('auto_subscription'))
  detect_subscriptions(s);self.assertEqual(t['category'],'Miscellaneous')
 def test_refund_can_remove_pattern_without_breaking_links(self):
  s=self.imported(['2026-09-01,Card,Vendor,Online Services,-20','2026-10-01,Card,Vendor,Online Services,-20','2026-10-02,Card,Vendor,Telephone,20'])
  first,second,credit=s['transactions'];mutate(s,'links',{'id':credit['id'],'links':[{'expense_id':second['id'],'amount':'20'}]})
  validate(s);self.assertEqual(len(s['links']),1);self.assertEqual(second['kind'],'expense');self.assertTrue(second['recurring_review']);self.assertEqual(first['kind'],'review')
  self.assertEqual(snapshot(s)['summaries']['2026-10']['total'],0)
  mutate(s,'links',{'id':credit['id'],'links':[]});self.assertTrue(all(t.get('auto_subscription') for t in s['transactions'][:2]));validate(s)
 def test_annual_allocations_are_not_monthly_evidence(self):
  s=self.imported(['2026-09-01,Card,Annual vendor,Telephone,-120'])
  t=s['transactions'][0];mutate(s,'transaction',{'id':t['id'],'kind':'expense','category':'Miscellaneous','allocations':[{'month':'2026-09','amount':'60'},{'month':'2026-10','amount':'60'}]})
  self.assertFalse(t.get('auto_subscription'));self.assertEqual(t['category'],'Miscellaneous')

class StartupTests(unittest.TestCase):
 def setUp(self):
  import threading
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
  s=empty();ensure_month(s,'2026-09');self.store.save(s)
  self.server=BudgetHTTPServer(('127.0.0.1',0),Handler);self.server.store=self.store;self.server.token='test-token';self.server.previews={}
  self.url=f'http://127.0.0.1:{self.server.server_port}/'
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
 def request(self,path,payload=None):
  from urllib.error import HTTPError
  from urllib.request import Request,build_opener,ProxyHandler
  headers={'X-Budget-Token':'test-token','Origin':self.url.rstrip('/'),'Content-Type':'application/json'}
  req=Request(self.url+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
  try:
   with build_opener(ProxyHandler({})).open(req,timeout=2) as r:return r.status,json.load(r)
  except HTTPError as e:return e.code,json.load(e)
 def test_idle_browser_connection_and_upload_do_not_block(self):
  import socket
  idle=socket.create_connection(('127.0.0.1',self.server.server_port))
  upload=socket.create_connection(('127.0.0.1',self.server.server_port))
  try:
   headers=f'POST /api/visibility HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\nOrigin: {self.url.rstrip("/")}\r\nX-Budget-Token: test-token\r\nContent-Length: 1000\r\n\r\n'
   upload.sendall(headers.encode())
   self.assertEqual(self.request('health')[0],200)
   self.assertEqual(self.request('api/state')[0],200)
   status,_=self.request('api/visibility',{'revision':self.store.revision(),'excluded':['2026-09']});self.assertEqual(status,200)
  finally:
   # Complete a valid JSON body so the pending handler exits without a noisy reset.
   upload.sendall(b'{}'+b' '*998);upload.recv(4096);upload.close();idle.close()
 def test_concurrent_saves_check_revision_inside_lock(self):
  from concurrent.futures import ThreadPoolExecutor
  revision=self.store.revision()
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(lambda _:self.request('api/visibility',{'revision':revision,'excluded':['2026-09']}),range(2)))
  self.assertEqual(sorted(code for code,_ in results),[200,409]);self.assertTrue(self.store.load()['months']['2026-09']['excluded'])
 def test_launcher_checks_matching_live_process(self):
  self.assertTrue(healthy_runtime({'url':self.url,'pid':os.getpid()}))
  self.assertFalse(healthy_runtime({'url':self.url,'pid':-1}))
  self.assertFalse(healthy_runtime({'url':'http://example.com/','pid':os.getpid()}))
 def test_folder_import_accepts_uppercase_csv_and_rejects_dashboard(self):
  source=Path(self.temp.name)/'EXPORT.CSV'
  source.write_text('Date,Account,Description,Category,Amount\n2026-09-01,Card,Example,Groceries,-20\n')
  (Path(self.temp.name)/'directory.csv').mkdir()
  self.assertEqual(self.request('api/state')[1]['available_files'],['EXPORT.CSV'])
  status,preview=self.request('api/preview',{'revision':self.store.revision(),'filename':'EXPORT.CSV'})
  self.assertEqual(status,200);self.assertEqual(len(preview['rows']),1)
  for name in ['dashboard_data.csv','DASHBOARD_DATA.CSV','../EXPORT.CSV']:
   self.assertEqual(self.request('api/preview',{'revision':self.store.revision(),'filename':name})[0],400)

if __name__=='__main__': unittest.main(verbosity=2)
