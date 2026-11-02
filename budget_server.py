#!/usr/bin/env python3
"""Private, local-only budget dashboard. Python standard library; amounts in cents."""
import argparse, copy, csv, datetime as dt, decimal, fcntl, hashlib, io, json, os
from collections import Counter
import re, secrets, shutil, tempfile, uuid, webbrowser, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler

CATEGORIES = dict.fromkeys(['Rent + utilities','Car loan','Auto insurance','Groceries+Food','Gas','Subscriptions','Miscellaneous'], 0)
CATEGORY_MAP = {'groceries':'Groceries+Food','restaurants':'Groceries+Food','dining & drinks':'Groceries+Food',
                'food & dining':'Groceries+Food','fast food':'Groceries+Food','coffee shops':'Groceries+Food',
                'gasoline/fuel':'Gas','dues & subscriptions':'Subscriptions','rent':'Rent + utilities',
                'utilities':'Rent + utilities','auto insurance':'Auto insurance'}
CATEGORY_MAP.update(dict.fromkeys(['general merchandise', 'automotive', 'travel', 'clothing/shoes', 'telephone', 'electronics', 'service charges/fees', 'other expenses', 'personal care', 'charitable giving', 'entertainment', 'shopping', 'entertainment & rec.', 'fees', 'medical', 'healthcare'], 'Miscellaneous'))
SUBSCRIPTION_CATEGORY = 'Subscriptions'
FALLBACK_CATEGORY = 'Miscellaneous'
CATEGORY_GROUPS = {'Needs':list(CATEGORIES)[:5], 'Wants':list(CATEGORIES)[5:]}
FOOD_SOURCES = ['restaurants','dining & drinks','food & dining','fast food','coffee shops']
KINDS = ['expense','refund','reimbursement','income','card_payment','transfer','review','duplicate']
FIELDS = ['record_type','id','date','month','description','account','amount','category','treatment',
          'transaction_id','linked_transaction_id','source_file','source_row','notes','details']
MAX_BYTES = 10*1024*1024
csv.field_size_limit(MAX_BYTES)
class Invalid(ValueError): pass

def uid(): return uuid.uuid4().hex

def cents(value):
    try: v=decimal.Decimal(str(value))
    except decimal.InvalidOperation: raise Invalid('Enter a valid dollar amount.')
    if not v.is_finite() or abs(v)>decimal.Decimal('100000000') or v*100 != (v*100).to_integral_value():
        raise Invalid('Amounts must be finite dollars with at most two decimal places.')
    return int(v*100)

def dollars(value): return f'{value/100:.2f}'

def configure(path):
    """Load the data directory's local configuration before opening its records."""
    global SUBSCRIPTION_CATEGORY, FALLBACK_CATEGORY
    if not path.exists(): return
    try:
        config=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(config,dict) or set(config)!={'categories','category_map','subscription_category','fallback_category','groups'}:
            raise Invalid('Use the keys in config.example.json.')
        raw=config['categories']
        if not isinstance(raw,dict) or not raw or any(not isinstance(k,str) or not k.strip() or k!=k.strip() or len(k)>80 for k in raw):
            raise Invalid('Categories need distinct, nonempty names of at most 80 characters.')
        categories={k:cents(v) for k,v in raw.items()}
        if any(v<0 for v in categories.values()): raise Invalid('Starting budgets must be nonnegative.')
        mapping=config['category_map']
        if not isinstance(mapping,dict) or any(not isinstance(k,str) or not k.strip() or not isinstance(v,str) or v not in categories for k,v in mapping.items()):
            raise Invalid('Each source category must map to a configured budget category.')
        for key in ['subscription_category','fallback_category']:
            if not isinstance(config[key],str) or config[key] not in categories:
                raise Invalid(f'{key} must name a configured category.')
        groups=config['groups']
        if not isinstance(groups,dict) or any(not isinstance(k,str) or not k.strip() or not isinstance(v,list) for k,v in groups.items()):
            raise Invalid('Groups must map names to lists of categories.')
        members=[c for group in groups.values() for c in group]
        if any(not isinstance(c,str) for c in members) or len(members)!=len(set(members)) or set(members)!=set(categories):
            raise Invalid('Groups must contain every category exactly once.')
        normalized={k.strip().casefold():v for k,v in mapping.items()}
        if len(normalized)!=len(mapping): raise Invalid('Source category names must be distinct ignoring case and spaces.')
    except (ValueError,TypeError,OSError) as e:
        raise Invalid(f'Invalid configuration: {e}') from e
    CATEGORIES.clear(); CATEGORIES.update(categories)
    CATEGORY_MAP.clear(); CATEGORY_MAP.update(normalized)
    CATEGORY_GROUPS.clear(); CATEGORY_GROUPS.update(groups)
    SUBSCRIPTION_CATEGORY=config['subscription_category']; FALLBACK_CATEGORY=config['fallback_category']


def valid_month(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',value): raise Invalid('Choose a valid month.')
    if not 1900 <= int(value[:4]) <= 2200: raise Invalid('Month must be between 1900 and 2200.')
    return value

def valid_date(value):
    try: result=dt.date.fromisoformat(value).isoformat()
    except (ValueError,TypeError): raise Invalid('Enter a valid date.')
    valid_month(result[:7]); return result

def empty(): return {'transactions':[],'allocations':[],'links':[],'budgets':{},'months':{},'imports':[]}

def ensure_month(s,month):
    valid_month(month)
    if month not in s['budgets']:
        prior=[m for m in s['budgets'] if m<month]
        s['budgets'][month]=copy.deepcopy(s['budgets'][max(prior)] if prior else CATEGORIES)
    s['months'].setdefault(month,{'reviewed':False,'zero_categories':[]})

def mark_draft(s):
    # A retroactive allocation/link can change more than the currently open month.
    for value in s['months'].values(): value['reviewed']=False

def tx_by_id(s,ident):
    for t in s['transactions']:
        if t['id']==ident: return t
    raise Invalid('Transaction no longer exists. Refresh and try again.')

def fingerprint(t):
    identity=[t['date'],t['account'].strip().casefold(),t['description'].strip().casefold(),t['cents']]
    if t.get('source_account_identity'): identity.append(t['source_account_identity'])
    return hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()

def classify(description,category,amount):
    c=category.casefold()
    if c in ['credit card payments','credit card payment']: return 'card_payment','Card payment'
    if c in ['transfers','internal transfers','transfer','securities trades','investment']:
        return 'transfer','Transfer'
    if amount>0 and c in ['interest','income','paychecks/salary','paycheck']: return 'income','Income'
    cat=CATEGORY_MAP.get(c)
    if cat is None and category in CATEGORIES: cat=category
    if cat is None: return 'review','Needs review'
    return ('refund' if amount>0 else 'expense'),cat

def merge_food_category(s):
    for t in s['transactions']:
        if t.get('subcategory','') not in ['', 'Food'] or (t.get('subcategory') and t['category']!='Miscellaneous'):
            raise Invalid('Invalid legacy food subcategory.')
        food=t.get('subcategory','Food' if t.get('source_category','').casefold() in FOOD_SOURCES else '')
        if t['category']=='Groceries' or (t['category']=='Miscellaneous' and food=='Food'):
            t['category']='Groceries+Food'
        t['subcategory']=''
    for month,budget in s['budgets'].items():
        if 'Groceries' in budget:
            if 'Groceries+Food' in budget: raise Invalid('Budget contains both old and merged grocery categories.')
            s['budgets'][month]={'Groceries+Food' if c=='Groceries' else c:v for c,v in budget.items()}
            # A grocery-only zero-spend confirmation does not cover restaurant spending.
            s['months'][month]['zero_categories']=[c for c in s['months'][month].get('zero_categories',[]) if c!='Groceries']
            s['months'][month]['reviewed']=False

def parse_export(text,name):
    try: return _parse_export(text,name)
    except csv.Error as e: raise Invalid(f'Unable to parse CSV: {e}')

def _parse_export(text,name):
    if len(text.encode('utf-8'))>MAX_BYTES: raise Invalid('Export exceeds 10 MB.')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')),strict=True)
    headers=reader.fieldnames or []
    if len(headers)!=len(set(headers)): raise Invalid('CSV has duplicate column headers. Export it again with one column per field.')
    fields=set(headers)
    legacy={'Date','Account Name','Name','Amount','Category','Original Date'}.issubset(fields)
    if not legacy and not {'Date','Account','Description','Category','Amount'}.issubset(fields):
        raise Invalid('Choose an Empower CSV with Date, Account, Description, Category and Amount columns.')
    result=[]
    for i,row in enumerate(reader,2):
        if row.get(None) is not None: raise Invalid(f'CSV row {i}: extra cells do not match the header.')
        if not any(row.values()): continue
        try:
            date=valid_date(row['Date'].strip())
            amount_text=row['Amount'].strip()
            if not re.fullmatch(r'(?:[+-]?\$?|\$[+-]?)(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?',amount_text):
                raise Invalid('Use decimal dollars with correctly grouped thousands, such as -1,234.56 or -$12.34.')
            amount=cents(amount_text.replace(',','').replace('$',''))*(-1 if legacy else 1)
            if not amount: raise Invalid('Zero-amount rows need to be removed from this import copy.')
            description=((row.get('Custom Name') or row.get('Name')) if legacy else row['Description']).strip()
            account=(row['Account Name'] if legacy else row['Account']).strip()
            institution=(row.get('Institution Name') or '').strip() if legacy else ''
            account_number=(row.get('Account Number') or '').strip() if legacy else ''
            source_account_identity=hashlib.sha256(json.dumps([institution.casefold(),account_number.casefold()]).encode()).hexdigest() if institution or account_number else ''
            if legacy and (institution or account_number):
                account+=' · '+institution+(' · ending '+account_number[-4:] if account_number else '')
            category=row['Category'].strip()
            if not description or not account: raise Invalid('Description and account are required.')
        except (KeyError,AttributeError,Invalid) as e: raise Invalid(f'CSV row {i}: {e}')
        kind,cat=classify(description,category,amount)
        t={'id':uid(),'date':date,'description':description,'account':account,'cents':amount,
           'category':cat,'kind':kind,'notes':'','source_file':name,'source_row':i,'manual':False,
           'source_category':category,'source_tags':row.get('Transaction Tags' if legacy else 'Tags',''),
           'original_amount':row['Amount'],'source_account_identity':source_account_identity,'format':'legacy-positive-charges' if legacy else 'empower',
           'reviewed':False}
        t['subcategory']=''
        t['fingerprint']=fingerprint(t); result.append(t)
    if not result: raise Invalid('This CSV has no transactions.')
    return result

class Store:
    def __init__(self,folder):
        self.folder=Path(folder); self.path=self.folder/'dashboard_data.csv'
    def revision(self): return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else 'new'
    def load(self):
        s=empty()
        if not self.path.exists(): return s
        try:
            schema_count=0
            with self.path.open(newline='',encoding='utf-8') as f:
                reader=csv.DictReader(f,strict=True)
                if reader.fieldnames!=FIELDS: raise Invalid('dashboard_data.csv has an unexpected header. Restore a backup before continuing.')
                for r in reader:
                    if None in r or any(value is None for value in r.values()): raise Invalid('Dashboard CSV row does not match its header.')
                    k=r['record_type']; details=json.loads(r['details'] or '{}')
                    if not isinstance(details,dict): raise Invalid('Dashboard CSV details must be a JSON object.')
                    if k=='transaction':
                        s['transactions'].append(dict(details,id=r['id'],date=r['date'],description=r['description'],account=r['account'],
                            cents=cents(r['amount']),category=r['category'],kind=r['treatment'],notes=r['notes'],
                            source_file=r['source_file'],source_row=int(r['source_row'] or 0)))
                    elif k=='allocation': s['allocations'].append({'transaction_id':r['transaction_id'],'month':r['month'],'cents':cents(r['amount'])})
                    elif k=='link': s['links'].append({'id':r['id'],'credit_id':r['transaction_id'],'expense_id':r['linked_transaction_id'],'cents':cents(r['amount'])})
                    elif k=='budget': s['budgets'].setdefault(r['month'],{})[r['category']]=cents(r['amount'])
                    elif k=='month': s['months'][r['month']]=details
                    elif k=='import': s['imports'].append(dict(details,id=r['id'],name=r['source_file']))
                    elif k=='schema':
                        schema_count+=1
                        schema_version=details.get('version')
                        if schema_version not in [1,2]: raise Invalid('Unsupported dashboard CSV version.')
                    else: raise Invalid('Unrecognized record type in dashboard_data.csv.')
            if schema_count!=1: raise Invalid('Dashboard CSV must contain exactly one schema record.')
            if schema_version==1: merge_food_category(s)
            for t in s['transactions']: t.setdefault('subcategory','')
            validate(s)
        except (OSError,ValueError,KeyError,TypeError,AttributeError,csv.Error) as e: raise Invalid(f'Unable to read dashboard_data.csv safely: {e}')
        return s
    def save(self,s):
        validate(s)
        rows=[]
        def add(k,**values): rows.append(dict(record_type=k,**values))
        add('schema',details=json.dumps({'version':2}))
        base={'id','date','description','account','cents','category','kind','notes','source_file','source_row'}
        for t in s['transactions']:
            add('transaction',id=t['id'],date=t['date'],description=t['description'],account=t['account'],amount=dollars(t['cents']),category=t['category'],treatment=t['kind'],notes=t['notes'],source_file=t['source_file'],source_row=t['source_row'],details=json.dumps({k:v for k,v in t.items() if k not in base},ensure_ascii=False))
        for a in s['allocations']: add('allocation',transaction_id=a['transaction_id'],month=a['month'],amount=dollars(a['cents']))
        for l in s['links']: add('link',id=l['id'],transaction_id=l['credit_id'],linked_transaction_id=l['expense_id'],amount=dollars(l['cents']))
        for month,budget in sorted(s['budgets'].items()):
            for category,value in budget.items(): add('budget',month=month,category=category,amount=dollars(value))
        for month,data in sorted(s['months'].items()): add('month',month=month,details=json.dumps(data))
        for imp in s['imports']: add('import',id=imp['id'],source_file=imp['name'],details=json.dumps({k:v for k,v in imp.items() if k not in ['id','name']}))
        if self.path.exists():
            backups=self.folder/'backups'; backups.mkdir(exist_ok=True,mode=0o700)
            target=backups/(dt.datetime.now().strftime('%Y%m%d-%H%M%S-')+uid()[:8]+'.csv')
            shutil.copy2(self.path,target); os.chmod(target,0o600)
            for old in sorted(backups.glob('*.csv'))[:-30]: old.unlink()
        fd,tmp=tempfile.mkstemp(prefix='.dashboard-',dir=self.folder)
        try:
            with os.fdopen(fd,'w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows); f.flush(); os.fsync(f.fileno())
            os.chmod(tmp,0o600); os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)


def validate(s):
    ts={t['id']:t for t in s['transactions']}
    if len(ts)!=len(s['transactions']): raise Invalid('Duplicate transaction IDs.')
    for t in ts.values():
        valid_date(t['date'])
        if t.get('subcategory',''): raise Invalid('Use the Groceries+Food category instead of a Food subcategory.')
        if t['kind'] not in KINDS or not t['description'].strip(): raise Invalid('Invalid transaction treatment or description.')
        if not isinstance(t['cents'],int) or not t['cents']: raise Invalid('Transaction amount must be nonzero cents.')
        if t['kind']=='expense' and (t['cents']>=0 or t['category'] not in CATEGORIES): raise Invalid('Expenses need a negative original amount and a budget category.')
        if t['kind'] in ['refund','reimbursement'] and t['cents']<=0: raise Invalid('Refunds and repayments need a positive original amount.')
    allocated={}; seen=set()
    for a in s['allocations']:
        t=ts.get(a['transaction_id']); valid_month(a['month'])
        if not t or t['kind']!='expense' or not isinstance(a['cents'],int) or a['cents']<=0: raise Invalid('Allocations must be positive amounts attached to an expense.')
        key=(t['id'],a['month'])
        if key in seen: raise Invalid('Use only one allocation row per month.')
        seen.add(key); allocated[t['id']]=allocated.get(t['id'],0)+a['cents']
        if a['month'] not in s['budgets']: raise Invalid('Allocation month is missing a budget.')
    for t in ts.values():
        if t['kind']=='expense' and allocated.get(t['id'],0)!=-t['cents']: raise Invalid('Monthly allocations must add up to the original charge.')
    credits={}; expenses={}; pairs=set()
    for l in s['links']:
        c=ts.get(l['credit_id']); e=ts.get(l['expense_id']); v=l['cents']; pair=(l['credit_id'],l['expense_id'])
        if pair in pairs: raise Invalid('Combine duplicate links to the same expense.')
        pairs.add(pair)
        if not c or not e or c['kind'] not in ['refund','reimbursement'] or e['kind']!='expense' or not isinstance(v,int) or v<=0: raise Invalid('Link a positive refund or repayment to an expense.')
        credits[c['id']]=credits.get(c['id'],0)+v; expenses[e['id']]=expenses.get(e['id'],0)+v
    if any(v>ts[k]['cents'] for k,v in credits.items()): raise Invalid('Linked amounts exceed the credit received.')
    if any(v>-ts[k]['cents'] for k,v in expenses.items()): raise Invalid('Refunds and repayments exceed the original expense.')
    if set(s['budgets'])!=set(s['months']): raise Invalid('Month metadata and budgets do not match.')
    for t in ts.values():
        if t['date'][:7] not in s['budgets']: raise Invalid('Transaction month is missing a budget.')
    for month,b in s['budgets'].items():
        valid_month(month)
        if not isinstance(s['months'][month].get('excluded',False),bool): raise Invalid('Month exclusion must be true or false.')
        if set(b)!=set(CATEGORIES) or any(not isinstance(v,int) or v<0 for v in b.values()): raise Invalid('Saved budget categories must match config.json, with nonnegative amounts. Restore the matching config before reopening existing data.')


def split_proportionally(total,allocations):
    denom=sum(a['cents'] for a in allocations)
    values=[total*a['cents']//denom for a in allocations]
    remainder=total-sum(values)
    order=sorted(range(len(values)),key=lambda i:(-(total*allocations[i]['cents']%denom),allocations[i]['month']))
    for i in order[:remainder]: values[i]+=1
    return values

def snapshot(s):
    out=copy.deepcopy(s); summaries={}
    allocations_by_id={}; links_by_id={}
    for allocation in s['allocations']:
        allocations_by_id.setdefault(allocation['transaction_id'],[]).append(allocation)
    for link in s['links']:
        links_by_id.setdefault(link['credit_id'],[]).append(link)
        links_by_id.setdefault(link['expense_id'],[]).append(link)
    for month,budget in s['budgets'].items():
        summaries[month]={'budget':budget,'categories':{c:{'gross':0,'credits':0,'net':0,'count':0} for c in CATEGORIES},'unresolved':0,'unresolved_cents':0,'missing':[],'reviewed':s['months'][month]['reviewed']}
    for t in out['transactions']:
        t.setdefault('subcategory','')
        t['allocations']=allocations_by_id.get(t['id'],[])
        t['links']=links_by_id.get(t['id'],[])
        t['linked_cents']=sum(l['cents'] for l in t['links'])
        t['review_reason']=''
        if t['kind']=='review': t['review_reason']='Choose a category and treatment.'
        elif t.get('recurring_review'): t['review_reason']='The subscription pattern changed. Confirm this expense’s category; its linked credits are preserved.'
        elif t['kind'] in ['refund','reimbursement'] and t['linked_cents']<t['cents']: t['review_reason']='Link the remaining credit to its original expense.'
        if t['review_reason']:
            month=t['date'][:7]
            if month in summaries:
                summaries[month]['unresolved']+=1; summaries[month]['unresolved_cents']+=abs(t['cents'])-t['linked_cents']
        if t['kind']=='expense':
            allocations=t['allocations']; credits=split_proportionally(t['linked_cents'],allocations)
            t['net_cents']=-t['cents']-t['linked_cents']
            for a,credit in zip(allocations,credits):
                value=summaries[a['month']]['categories'][t['category']]
                value['gross']+=a['cents']; value['credits']+=credit; value['net']+=a['cents']-credit; value['count']+=1
    for month,v in summaries.items():
        v['missing']=[c for c in CATEGORIES if not v['categories'][c]['count'] and c not in s['months'][month].get('zero_categories',[])]
        v['total']=sum(x['net'] for x in v['categories'].values()); v['gross']=sum(x['gross'] for x in v['categories'].values()); v['credits']=sum(x['credits'] for x in v['categories'].values())
        v['planned']=sum(v['budget'].values()); v['complete']=not(v['missing'] or v['unresolved'])
    out['summaries']=summaries; out['categories']=list(CATEGORIES); out['groups']=CATEGORY_GROUPS; out['fallback_category']=FALLBACK_CATEGORY; out['kinds']=KINDS
    return out


def add_transaction(s,t):
    s['transactions'].append(t); ensure_month(s,t['date'][:7])
    if t['kind']=='expense': s['allocations'].append({'transaction_id':t['id'],'month':t['date'][:7],'cents':-t['cents']})


def recurring_vendor(description):
    # Normalize spelling/punctuation and wallet prefixes, retaining merchant numbers.
    name=re.sub(r'^\s*(?:aplpay|apple\s+pay)\s+', '', description.casefold())
    return ' '.join(re.findall(r'[^\W_]+',name,flags=re.UNICODE))


def detect_subscriptions(s):
    before={t['id']:(t['kind'],t['category'],t.get('subcategory','')) for t in s['transactions']}
    linked_ids={link['expense_id'] for link in s['links']}
    # Re-evaluate prior automatic decisions as refunds or duplicate exclusions change evidence.
    for t in s['transactions']:
        prior=t.pop('auto_subscription',None)
        if prior and not t.get('reviewed'):
            t.update(prior['original'])
            if t['kind']!='expense' and t['id'] in linked_ids:
                # Keep linked credits and allocations valid while requesting a category review.
                t.update(kind='expense',category=FALLBACK_CATEGORY,subcategory='',recurring_review=True)
            if t['kind']!='expense': s['allocations']=[a for a in s['allocations'] if a['transaction_id']!=t['id']]
    refunded=Counter()
    for link in s['links']: refunded[link['expense_id']]+=link['cents']
    groups={}
    for t in s['transactions']:
        if t['cents']>=0 or t['kind'] not in ['expense','review'] or t.get('manual'): continue
        if t['category'] not in [FALLBACK_CATEGORY,SUBSCRIPTION_CATEGORY,'Needs review']: continue
        if t.get('reviewed') and t['category']!=SUBSCRIPTION_CATEGORY: continue
        if refunded[t['id']]>=-t['cents']: continue
        vendor=recurring_vendor(t['description'])
        if vendor: groups.setdefault((vendor,t['cents']),{}).setdefault(t['date'][:7],[]).append(t)
    for by_month in groups.values():
        # More than one matching charge in a month is ambiguous; no silent duplicate collapse.
        unique=sorted((rows[0] for rows in by_month.values() if len(rows)==1),key=lambda t:t['date'])
        runs=[];run=[]
        for t in unique:
            if run:
                previous=dt.date.fromisoformat(run[-1]['date']);current=dt.date.fromisoformat(t['date'])
                adjacent=(current.year*12+current.month)-(previous.year*12+previous.month)==1
                monthly=adjacent and 20<=(current-previous).days<=40 and abs(current.day-previous.day)<=7
                if not monthly:
                    if len(run)>=2:runs.append(run)
                    run=[]
            run.append(t)
        if len(run)>=2:runs.append(run)
        for run in runs:
            evidence=[t['id'] for t in run]
            for t in run:
                if t.get('reviewed') or t['category']==SUBSCRIPTION_CATEGORY:continue
                original={k:t.get(k,'') for k in ['kind','category','subcategory','recurring_review']}
                t.update(kind='expense',category=SUBSCRIPTION_CATEGORY,subcategory='',recurring_review=False)
                t['auto_subscription']={'original':original,'evidence':evidence}
                if original['kind']!='expense':
                    s['allocations'].append({'transaction_id':t['id'],'month':t['date'][:7],'cents':-t['cents']})
    changed=[t for t in s['transactions'] if before[t['id']]!=(t['kind'],t['category'],t.get('subcategory',''))]
    for t in changed:
        months={t['date'][:7]}|{a['month'] for a in s['allocations'] if a['transaction_id']==t['id']}
        for month in months:s['months'][month]['reviewed']=False
    return sum('auto_subscription' in t for t in s['transactions'])


def mutate(s,action,p):
    if action=='transaction':
        isnew=not p.get('id')
        if isnew:
            t={'id':uid(),'manual':True,'source_file':'Manual entry','source_row':0,'source_category':'Manual','source_tags':'','format':'manual','notes':'','reviewed':True}
            t.update(date=valid_date(p['date']),description=p['description'].strip(),account=p.get('account','Manual').strip() or 'Manual',cents=cents(p['amount']))
            s['transactions'].append(t)
        else: t=tx_by_id(s,p['id'])
        old_kind=t.get('kind'); kind=p.get('kind','expense')
        if kind not in KINDS: raise Invalid('Choose a valid treatment.')
        if not isnew and t.get('manual'):
            t.update(date=valid_date(p['date']),description=p['description'].strip(),account=p.get('account','Manual').strip() or 'Manual',cents=cents(p['amount']))
        if old_kind and kind!=old_kind and any(l['expense_id']==t['id'] or l['credit_id']==t['id'] for l in s['links']): raise Invalid('Remove linked credits before changing treatment.')
        t['kind']=kind; t['category']=p.get('category','Needs review'); t['notes']=str(p.get('notes',''))[:10000]; t['reviewed']=True
        t.pop('auto_subscription',None); t.pop('recurring_review',None)
        fixed={'card_payment':'Card payment','transfer':'Transfer','income':'Income','review':'Needs review','duplicate':'Duplicate'}
        if kind in fixed: t['category']=fixed[kind]
        t['subcategory']=''
        ensure_month(s,t['date'][:7])
        s['allocations']=[a for a in s['allocations'] if a['transaction_id']!=t['id']]
        if kind=='expense':
            allocs=p.get('allocations') or [{'month':t['date'][:7],'amount':dollars(-t['cents'])}]
            for a in allocs:
                month=valid_month(a['month']); ensure_month(s,month)
                s['allocations'].append({'transaction_id':t['id'],'month':month,'cents':cents(a['amount'])})
        mark_draft(s)
    elif action=='links':
        t=tx_by_id(s,p['id'])
        if t['kind'] not in ['refund','reimbursement']: raise Invalid('First mark this credit as a refund or reimbursement.')
        s['links']=[l for l in s['links'] if l['credit_id']!=t['id']]
        for link in p['links']:
            s['links'].append({'id':uid(),'credit_id':t['id'],'expense_id':link['expense_id'],'cents':cents(link['amount'])})
        mark_draft(s)
    elif action=='budget':
        month=valid_month(p['month']); ensure_month(s,month)
        s['budgets'][month]={c:cents(p['budget'][c]) for c in CATEGORIES}; s['months'][month]['reviewed']=False
    elif action=='visibility':
        excluded=p.get('excluded')
        if not isinstance(excluded,list) or any(m not in s['months'] for m in excluded): raise Invalid('Choose existing months to exclude.')
        for m,meta in s['months'].items(): meta['excluded']=m in excluded
    elif action=='month':
        month=valid_month(p['month']); ensure_month(s,month)
        zeros=p.get('zero_categories',s['months'][month].get('zero_categories',[]))
        if any(c not in CATEGORIES for c in zeros): raise Invalid('Unknown zero-spend category.')
        s['months'][month]['zero_categories']=zeros
        if p.get('reviewed') and not snapshot(s)['summaries'][month]['complete']: raise Invalid('Resolve uncertain transactions and confirm missing categories before marking this month reviewed.')
        s['months'][month]['reviewed']=bool(p.get('reviewed',False))
    else: raise Invalid('Unknown action.')
    if action in ['transaction','links']: detect_subscriptions(s)
    validate(s)


def preview_import(s,text,name):
    digest=hashlib.sha256(text.lstrip('\ufeff').replace('\r\n','\n').replace('\r','\n').encode()).hexdigest()
    if any(i['id']==digest for i in s['imports']): return {'already_imported':True,'name':name,'digest':digest,'rows':[]}
    rows=parse_export(text,name)
    existing={}
    for t in s['transactions']:
        if not t.get('manual'): existing.setdefault(t.get('fingerprint') or fingerprint(t),[]).append(t['id'])
    occurrences=Counter(); incoming=Counter(t['fingerprint'] for t in rows)
    for t in rows:
        exact=existing.get(t['fingerprint'],[])
        occurrences[t['fingerprint']]+=1
        # Count matches one-for-one. Repeated real charges must not collapse into one row.
        covered=occurrences[t['fingerprint']]<=len(exact)
        matches=list(exact)
        for x in s['transactions']:
            if not x.get('manual') and x['id'] not in matches and x['cents']==t['cents'] and abs((dt.date.fromisoformat(x['date'])-dt.date.fromisoformat(t['date'])).days)<=3:
                matches.append(x['id'])
        manual=[x['id'] for x in s['transactions'] if x.get('manual') and x['cents']==t['cents'] and abs((dt.date.fromisoformat(x['date'])-dt.date.fromisoformat(t['date'])).days)<=7]
        t.update(matches=matches,manual_matches=manual,exact_matches=exact,
                 suggested_choice='skip' if covered else '',batch_count=incoming[t['fingerprint']])
    return {'already_imported':False,'name':name,'digest':digest,'rows':rows,'format':rows[0]['format']}

def commit_import(s,preview,choices):
    if preview['already_imported']: raise Invalid('This exact export is already imported.')
    used=set(); added=skipped=reconciled=0
    for row in preview['rows']:
        t=copy.deepcopy(row); matches=t.pop('matches'); manual=t.pop('manual_matches')
        t.pop('exact_matches',None); t.pop('suggested_choice',None); batch_count=t.pop('batch_count',1)
        choice=choices.get(str(t['source_row']))
        if matches or manual or batch_count>1:
            if choice is None: raise Invalid('Choose what to do with each possible overlap before importing.')
        else: choice=choice or 'add'
        if choice=='skip': skipped+=1; continue
        if choice.startswith('replace:'):
            ident=choice.split(':',1)[1]
            if ident not in manual or ident in used: raise Invalid('Choose a distinct matching manual entry to reconcile.')
            old=tx_by_id(s,ident); used.add(ident)
            old['manual_original']={'date':old['date'],'description':old['description'],'account':old['account']}
            for k in ['date','description','account','cents','source_file','source_row','source_category','source_tags','format','fingerprint','source_account_identity']: old[k]=t[k]
            old['manual']=False; old['reconciled_manual']=True; ensure_month(s,t['date'][:7]); reconciled+=1
        elif choice=='add': add_transaction(s,t); added+=1
        else: raise Invalid('Invalid overlap choice.')
    s['imports'].append({'id':preview['digest'],'name':preview['name'],'rows':len(preview['rows']),'imported_at':dt.datetime.now(dt.timezone.utc).isoformat(),'added':added,'skipped':skipped,'reconciled':reconciled})
    detected=detect_subscriptions(s)
    mark_draft(s); validate(s)
    return {'added':added,'skipped':skipped,'reconciled':reconciled,'detected_subscriptions':detected}

class BudgetHTTPServer(ThreadingHTTPServer):
    # Browsers may preconnect without sending a request; don't let that block the app.
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.data_lock=threading.RLock()
    def get_request(self):
        connection,address=super().get_request()
        connection.settimeout(15)
        return connection,address


def healthy_runtime(info):
    try:
        url=info['url']; parsed=urlparse(url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path!='/': return False
        with build_opener(ProxyHandler({})).open(Request(url+'health'),timeout=2) as response:
            result=json.load(response)
        return result.get('app')=='personal-budget' and result.get('pid')==info['pid']
    except (OSError,ValueError,KeyError,TypeError): return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def response(self,status,body,ctype='application/json'):
        if isinstance(body,(dict,list)): body=json.dumps(body,ensure_ascii=False).encode()
        elif isinstance(body,str): body=body.encode()
        self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers(); self.wfile.write(body)
    def authorized(self,api=False):
        host=self.headers.get('Host',''); allowed=f'127.0.0.1:{self.server.server_port}'
        if host!=allowed: self.response(403,{'error':'Open the dashboard through its local launcher.'}); return False
        if api and not secrets.compare_digest(self.headers.get('X-Budget-Token',''),self.server.token): self.response(403,{'error':'Refresh the dashboard to reconnect.'}); return False
        if self.command=='POST' and self.headers.get('Origin')!=f'http://{allowed}': self.response(403,{'error':'Only the local dashboard may save changes.'}); return False
        return True
    def do_GET(self):
        path=urlparse(self.path).path
        if not self.authorized(path.startswith('/api/')): return
        try:
            if path=='/health':
                self.response(200,{'app':'personal-budget','pid':os.getpid()}); return
            if path=='/api/state':
                with self.server.data_lock:
                    s=self.server.store.load(); result=snapshot(s); result['revision']=self.server.store.revision(); result['folder']=str(self.server.store.folder)
                result['available_files']=[p.name for p in sorted(self.server.store.folder.iterdir()) if p.is_file() and p.suffix.lower()=='.csv' and p.name.lower()!='dashboard_data.csv']
                self.response(200,result)
            elif path=='/api/download':
                with self.server.data_lock: saved=self.server.store.path.read_bytes()
                self.response(200,saved,'text/csv; charset=utf-8')
            elif path in ['/','/budget.html','/app.js','/style.css']:
                name='budget.html' if path in ['/','/budget.html'] else path[1:]
                data=(Path(__file__).parent/name).read_text().replace('__BUDGET_TOKEN__',self.server.token)
                self.response(200,data,{'budget.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}[name])
            else: self.response(404,{'error':'Not found'})
        except (Invalid,OSError) as e: self.response(400,{'error':str(e)})
    def do_POST(self):
        if not self.authorized(True): return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<1 or n>MAX_BYTES*2: raise Invalid('Request is empty or too large.')
            # Read the request before taking the lock: an idle upload mustn't block saves.
            p=json.loads(self.rfile.read(n))
            if not isinstance(p,dict): raise Invalid('Request must be a JSON object.')
            with self.server.data_lock: self.save_request(p)
        except (Invalid,KeyError,ValueError,OSError,TypeError) as e: self.response(400,{'error':str(e)})
    def save_request(self,p):
        try:
            s=self.server.store.load()
            if p.get('revision')!=self.server.store.revision(): self.response(409,{'error':'Data changed in another window. Refresh before saving.'}); return
            action=urlparse(self.path).path.removeprefix('/api/')
            if action=='preview':
                if p.get('filename'):
                    name=p['filename']
                    if Path(name).name!=name or name.lower()=='dashboard_data.csv' or not name.lower().endswith('.csv'): raise Invalid('Choose a source CSV in the budget folder.')
                    text=(self.server.store.folder/name).read_text(encoding='utf-8-sig')
                else: text=p.get('text',''); name=Path(p.get('name','export.csv')).name
                preview=preview_import(s,text,name); token=secrets.token_urlsafe(20)
                # A preview is valid only for the exact data it was compared against.
                self.server.previews[token]=(preview,text,self.server.store.revision())
                while len(self.server.previews)>20: self.server.previews.pop(next(iter(self.server.previews)))
                preview['token']=token; self.response(200,preview); return
            if action=='import':
                entry=self.server.previews.get(p.get('token'))
                if not entry: raise Invalid('Import preview expired. Preview the file again.')
                preview,text,revision=entry
                if revision!=self.server.store.revision(): raise Invalid('Data changed after this preview. Preview the file again before importing.')
                result=commit_import(s,preview,p.get('choices',{}))
                archive=self.server.store.folder/'imports'; archive.mkdir(exist_ok=True,mode=0o700)
                path=archive/(preview['digest'][:12]+'-'+Path(preview['name']).name)
                if not path.exists(): path.write_text(text,encoding='utf-8'); os.chmod(path,0o600)
            else: mutate(s,action,p); result={'saved':True}
            self.server.store.save(s)
            if action=='import': self.server.previews.pop(p['token'],None)
            self.response(200,result)
        except (Invalid,KeyError,ValueError,OSError,TypeError) as e: self.response(400,{'error':str(e)})


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--data-dir',type=Path,default=Path(__file__).parent/'data'); ap.add_argument('--port',type=int,default=0); ap.add_argument('--no-browser',action='store_true'); args=ap.parse_args()
    folder=args.data_dir.resolve(); folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=(folder/'.budget.lock').open('a'); runtime=folder/'.budget-runtime.json'
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        # A second launcher can arrive before the first server writes its address.
        info={}
        for _ in range(10):
            try: info=json.loads(runtime.read_text())
            except (OSError,ValueError): pass
            if healthy_runtime(info):
                url=info['url']; print('Dashboard already running at '+url,flush=True)
                if not args.no_browser: webbrowser.open(url)
                return
            time.sleep(.2)
        raise RuntimeError('The existing budget server is not responding. Close its Terminal window, then run Open Budget.command again. Your saved data is unchanged.')
    configure(folder/'config.json')
    store=Store(folder)
    if not store.path.exists():
        s=empty(); ensure_month(s,dt.date.today().strftime('%Y-%m')); store.save(s)
    else: store.load()
    server=BudgetHTTPServer(('127.0.0.1',args.port),Handler); server.store=store; server.token=secrets.token_urlsafe(32); server.previews={}
    url=f'http://127.0.0.1:{server.server_port}/'; runtime.write_text(json.dumps({'url':url,'pid':os.getpid()})); os.chmod(runtime,0o600)
    print('Budget dashboard: '+url+'\nChanges save to '+str(store.path)+'\nKeep this window open. Press Control-C to stop.',flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); runtime.unlink(missing_ok=True); lock.close()

if __name__=='__main__': main()
