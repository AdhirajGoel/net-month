'use strict';
const root=document.getElementById('budget-mock'), main=document.getElementById('main-content'), dialog=document.getElementById('editor');
const token=document.querySelector('meta[name="budget-token"]').content;
let data=null, month='', view='month', query='', categoryFilter='', scope='visible', page=0, editing=null, allocationDraft=[], linkDraft=[], importPreview=null;
let temporaryHidden=new Set();
try{temporaryHidden=new Set(JSON.parse(sessionStorage.getItem('budget-hidden-months')||'[]'));}catch{}
const visibleMonths=()=>Object.keys(data.budgets).filter(m=>!data.months[m].excluded&&!temporaryHidden.has(m)).sort();
function rememberHidden(){try{sessionStorage.setItem('budget-hidden-months',JSON.stringify([...temporaryHidden]));}catch{}}
let sortField='date',sortDirection='desc';
let saving=false,needsReload=false;
const pageSize=25, money=(c)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(c/100);
const inputMoney=c=>(c/100).toFixed(2), monthName=m=>new Date(m+'-02T12:00:00').toLocaleDateString('en-US',{month:'long',year:'numeric'});
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kindLabel={expense:'Expense',refund:'Refund',reimbursement:'Reimbursement',income:'Income',card_payment:'Card payment',transfer:'Transfer',review:'Needs review',duplicate:'Duplicate / excluded'};
const tx=id=>data.transactions.find(t=>t.id===id);
const accountName=s=>s.replace(/\s*-\s*Ending in\s*\d+\s*$/,'').replace('( )','').trim();
function action(label,name,extra='',cls=''){return `<button type="button" class="bm-action ${cls}" data-action="${name}" ${extra}>${label}</button>`;}
function options(values,selected){return values.map(v=>`<option value="${esc(v)}" ${v===selected?'selected':''}>${esc(v)}</option>`).join('');}
function flash(text,error=false){const e=document.getElementById('global-message');e.hidden=!text;e.textContent=text;e.classList.toggle('bm-error',error);}
async function api(path,payload){
 const settings={headers:{'X-Budget-Token':token}};
 if(payload!==undefined){settings.method='POST';settings.headers['Content-Type']='application/json';settings.body=JSON.stringify({...payload,revision:data?.revision});}
 let r,result;
 try{r=await fetch('/api/'+path,settings);result=await r.json();}
 catch(e){if(payload!==undefined)e.uncertain=true;throw e;}
 if(!r.ok){const e=Error(result.error||'Unable to save.');e.status=r.status;throw e;}return result;
}
async function refresh(){data=await api('state');render();document.getElementById('save-status').textContent='Saved locally';}
async function save(path,payload,close=true){
 if(saving)throw Error('A save is already in progress.');
 if(needsReload)throw Error('Reload saved data before making another change.');
 saving=true;let committed=false;
 const controls=[...root.querySelectorAll('button,input,select,textarea')].filter(e=>!e.disabled);
 controls.forEach(e=>e.disabled=true);root.setAttribute('aria-busy','true');
 document.getElementById('save-status').textContent='Saving…';
 try{const result=await api(path,payload);committed=true;await refresh();if(close)dialog.close();flash('Saved to dashboard_data.csv.');return result;}
 catch(e){
  needsReload=committed||!!e.uncertain||e.status===409;
  document.getElementById('save-status').textContent=committed?'Saved · reload needed':e.uncertain?'Save unconfirmed':'Not saved';
  if(committed){dialog.close();throw Error('Your change was saved, but the display could not reload. Reload saved data before making another change.');}
  if(e.uncertain)throw Error('The save response was lost. Your change may already be saved. Check the saved data before entering it again.');
  throw e;
 }finally{saving=false;controls.forEach(e=>e.disabled=false);root.setAttribute('aria-busy','false');}
}
function showError(e){
 if(e.status===409)needsReload=true;
 const target=dialog.open?document.getElementById('editor-error'):document.getElementById('global-message');
 target.hidden=false;target.classList.add('bm-error');target.innerHTML=esc(e.message);
 if(needsReload||!data)target.innerHTML+=`<div class="bm-section-gap">${action(dialog.open?'Discard draft and reload saved data':'Reload saved data','reload')}</div>`;
 target.scrollIntoView({block:'nearest'});target.focus();
}
function panel(title,body,hint=''){return `<section class="bm-panel"><div class="bm-panel-head"><h2>${title}</h2><span class="bm-small">${hint}</span></div>${body}</section>`;}
function render(){
 document.querySelectorAll('[data-view]').forEach(b=>{const selected=b.dataset.view===view;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;});
 main.setAttribute('aria-labelledby','tab-'+view);
 const months=visibleMonths().reverse();
 if(!months.includes(month)){
  const now=new Date(),current=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
  month=months.find(m=>m<=current)||months.at(-1)||'';
 }
 if(scope!=='all'&&scope!=='visible'&&!months.includes(scope))scope='visible';
 document.getElementById('month-heading').textContent=month?monthName(month):'All months hidden';
 if(!month){
  document.getElementById('sidebar').innerHTML=`<section><div class="bm-kicker">Monthly snapshot</div><p class="bm-note">All months are hidden. Your data is preserved.</p>${action('Manage months','manage-months')}${action('Add month','new-month')}${action('Download dashboard CSV','download')}</section>`;
  if(view==='transactions')renderLedger();else main.innerHTML=panel('No visible months',`<p class="bm-note">Restore months to see budgets and trends. You can still import data or search all transactions.</p><div class="bm-actions bm-section-gap">${action('Manage months','manage-months')}${action('Search transactions','transactions')}</div>`);
  return;
 }
 const budget=data.budgets[month];
 document.getElementById('sidebar').innerHTML=`<section><label class="bm-kicker" for="month-select">Monthly snapshot</label><select id="month-select" class="bm-month">${months.map(m=>`<option value="${m}" ${m===month?'selected':''}>${monthName(m)}</option>`).join('')}</select><p class="bm-note">${data.months[month].reviewed?'Reviewed':'Draft'} · ${data.transactions.filter(t=>t.date.startsWith(month)).length} dated transactions</p>${action('Add month','new-month')}${action('Manage months','manage-months')}<p class="bm-note">${Object.keys(data.budgets).length-months.length} hidden month(s)</p></section><section class="bm-plan-section"><div class="bm-kicker">Intended budget</div><div class="bm-budget-lines">${Object.entries(data.groups||{'Categories':data.categories}).map(([group,categories])=>`<div class="bm-rail-group needs"><span>${esc(group)}</span><span>${money(categories.reduce((sum,c)=>sum+budget[c],0))}</span></div>${categories.map(c=>`<div class="bm-rail-row"><span>${esc(c)}</span><span>${money(budget[c])}</span></div>`).join('')}`).join('')}</div>${action('Edit this month’s budget','budget')}<p class="bm-note">Budgets are saved per month. New months inherit the preceding plan.</p></section><details class="bm-data-section"><summary class="bm-kicker">Your data</summary><div class="bm-rail-row"><span>Transactions</span><span>${data.transactions.length}</span></div><div class="bm-rail-row"><span>Imported files</span><span>${data.imports.length}</span></div>${action('Download dashboard CSV','download')}<p class="bm-note">Saved only on this Mac.</p></details>`;
 if(view==='month')renderMonth();if(view==='transactions')renderLedger();if(view==='trends')renderTrends();if(view==='review')renderReview();
}
function renderMonth(){
 const s=data.summaries[month];
 const cards=[['Intended spending',money(s.planned),'Your category budgets'],['Net allocated spending',money(s.total),`${money(s.gross)} gross − ${money(s.credits)} linked credits`],['Budget variance',s.complete?money(Math.abs(s.planned-s.total)):'Pending review',s.complete?(s.total>s.planned?'Over budget':'Under budget'):`${s.unresolved} unresolved · ${s.missing.length} unconfirmed categories`]];
 main.innerHTML=`<div class="bm-kpis">${cards.map(([label,value,sub])=>`<div class="bm-kpi"><div class="bm-kpi-label">${label}</div><div class="bm-value ${value==='Pending review'?'bm-text-value':''}">${value}</div><div class="bm-kpi-sub">${sub}</div></div>`).join('')}</div><div class="bm-callout"><div><strong>${s.reviewed?'Month reviewed':s.complete?'Ready to review':'This month is a draft'}</strong><p>${s.reviewed?'Later edits or reimbursements will reopen the snapshot.':s.complete?'Confirm the account coverage and mark the month reviewed.':'Resolve uncertain transactions and confirm categories with no recorded spending.'}</p></div>${action('Review month','review')}</div>`;
 const rows=data.categories.map((c,i)=>{const r=s.categories[c],missing=s.missing.includes(c);return `<tr><td><button class="bm-category" type="button" data-action="category" data-category="${esc(c)}">${esc(c)}</button>${r.count?`<div class="bm-bar ${(data.groups?.Wants||[]).includes(c)?'wants':''}"><span style="width:${Math.min(100,Math.max(0,r.net/(s.budget[c]||1)*100))}%"></span></div>`:''}</td><td>${money(s.budget[c])}</td><td>${money(r.gross)}</td><td>${money(r.credits)}</td><td>${missing?'<span class="bm-absent">Not identified</span>':money(r.net)}</td><td class="${r.net>s.budget[c]?'bm-over':'bm-absent'}">${missing?'—':money(r.net-s.budget[c])}</td></tr>`;}).join('');
 main.innerHTML+=panel('Plan vs. actual',`<div class="bm-scroll-table"><table class="bm-table"><thead><tr><th>Category</th><th>Plan</th><th>Gross</th><th>Credits</th><th>Net actual</th><th>Actual − plan</th></tr></thead><tbody>${rows}<tr class="bm-total"><td>Total</td><td>${money(s.planned)}</td><td>${money(s.gross)}</td><td>${money(s.credits)}</td><td>${money(s.total)}</td><td>${s.complete?money(s.total-s.planned):'Draft'}</td></tr></tbody></table></div><p class="bm-note">Actuals use allocated months. Linked refunds and reimbursements reduce the original expense’s months. Unlinked credits remain in Review.</p>`,'Click a category to inspect transactions');
 main.innerHTML+=panel('Monthly snapshot',`<p class="bm-note">${data.imports.length} export${data.imports.length===1?'':'s'} imported. Original transactions, manual entries and adjustments remain searchable.</p><div class="bm-actions bm-section-gap">${action('View transactions','transactions')}${action('Compare months','trends')}</div>`);
}
function relevant(t,m){return t.kind==='expense'?t.allocations.some(a=>a.month===m):t.date.startsWith(m);}
function filtered(){const terms=query.toLowerCase().trim().split(/\s+/).filter(Boolean);return data.transactions.filter(t=>{
 const links=t.links.map(l=>tx(l.expense_id===t.id?l.credit_id:l.expense_id)?.description||'').join(' ');
 const text=[t.description,t.account,t.date,inputMoney(t.cents),money(t.cents),t.category,t.auto_subscription?'detected monthly subscription recurring':'',t.source_category,t.kind,kindLabel[t.kind],t.notes,t.manual?'manual':'imported',t.allocations.map(a=>a.month).join(' '),links].join(' ').toLowerCase();
 return terms.every(w=>text.includes(w))&&(!categoryFilter||t.category===categoryFilter)&&(scope==='all'||(scope==='visible'?visibleMonths().some(m=>relevant(t,m)):relevant(t,scope)));
 }).sort((a,b)=>{const av=a[sortField],bv=b[sortField];const comparison=sortField==='cents'?av-bv:String(av).localeCompare(String(bv),undefined,{numeric:true,sensitivity:'base'});return (sortDirection==='asc'?comparison:-comparison)||a.id.localeCompare(b.id);});}
function renderLedger(){
 main.innerHTML=panel('All transactions',`<label class="bm-search-label" for="search">Search across every imported and manual transaction</label><input id="search" class="bm-search" type="search" value="${esc(query)}" placeholder="Merchant, account, category, date, amount or note"><div class="bm-filter-row"><select id="scope-filter" aria-label="Transaction month scope"><option value="visible">Visible months</option><option value="all">All months, including hidden</option>${visibleMonths().reverse().map(m=>`<option value="${m}" ${m===scope?'selected':''}>${monthName(m)} allocations</option>`).join('')}</select><select id="category-filter" aria-label="Transaction category"><option value="">All categories</option>${options([...new Set([...data.categories,...data.transactions.map(t=>t.category)])].sort(),categoryFilter)}</select></div><div class="bm-filter-row"><label class="bm-field-label">Sort by<select id="sort-field">${[['date','Date'],['description','Description'],['account','Account'],['category','Category'],['cents','Amount (signed)']].map(([v,l])=>`<option value="${v}" ${sortField===v?'selected':''}>${l}</option>`).join('')}</select></label><label class="bm-field-label">Order<select id="sort-direction"><option value="asc" ${sortDirection==='asc'?'selected':''}>Ascending</option><option value="desc" ${sortDirection==='desc'?'selected':''}>Descending</option></select></label></div><div class="bm-actions">${action('Clear filters','clear-filters')}</div><div class="bm-ledger-meta"><span id="search-status" role="status" aria-live="polite"></span><span>Original signed amounts; negatives are charges.</span></div><table class="bm-table bm-ledger"><thead><tr><th>Date</th><th>Description / account</th><th>Category / treatment</th><th>Amount</th></tr></thead><tbody id="ledger-rows"></tbody></table><div class="bm-pagination"><span id="page-status" class="bm-small"></span><div class="bm-page-actions">${action('Previous','prev')}${action('Next','next')}</div></div>`,'Every source row is retained');
 document.getElementById('scope-filter').value=scope;renderLedgerRows();
}
function renderLedgerRows(){
 const rows=filtered(), pages=Math.max(1,Math.ceil(rows.length/pageSize));page=Math.min(page,pages-1);
 document.getElementById('search-status').textContent=`${rows.length} of ${data.transactions.length} transactions`;
 document.getElementById('page-status').textContent=`Page ${page+1} of ${pages}`;
 main.querySelector('[data-action=prev]').disabled=page===0;main.querySelector('[data-action=next]').disabled=page===pages-1;
 document.getElementById('ledger-rows').innerHTML=rows.slice(page*pageSize,(page+1)*pageSize).map(t=>`<tr data-id="${t.id}"><td>${t.date}${t.manual?'<span class="bm-tag">Manual</span>':t.reconciled_manual?'<span class="bm-ledger-sub">Reconciled manual</span>':''}</td><td>${esc(t.description)}<span class="bm-ledger-sub">${esc(accountName(t.account))}</span>${t.notes?`<span class="bm-ledger-sub">${esc(t.notes)}</span>`:''}${t.links.length?`<span class="bm-ledger-sub">Linked: ${money(t.linked_cents)} · ${esc(t.links.map(l=>tx(l.expense_id===t.id?l.credit_id:l.expense_id)?.description).join(', '))}</span>`:''}</td><td><span class="bm-tag ${t.review_reason?'bm-tag-review':''}">${esc(t.category)}</span><span class="bm-ledger-sub">${kindLabel[t.kind]} · ${esc(t.source_category)}</span>${t.kind==='expense'?`<span class="bm-ledger-sub">${t.allocations.map(a=>a.month).join(', ')} · net ${money(t.net_cents)}</span>`:''}${t.auto_subscription?`<span class="bm-ledger-sub">Detected monthly subscription · ${t.auto_subscription.evidence.length} months</span>`:''}${t.review_reason?`<span class="bm-ledger-sub">${esc(t.review_reason)}</span>`:''}</td><td>${t.cents>0?'+':''}${money(t.cents)}${action('Edit','edit',`data-id="${t.id}"`)}${['refund','reimbursement'].includes(t.kind)?action('Link credit','link',`data-id="${t.id}"`):''}</td></tr>`).join('')||'<tr><td colspan="4" class="bm-ledger-empty">No matching transactions.</td></tr>';
}
function renderTrends(){
 const months=visibleMonths().slice(-12),max=Math.max(1,...months.flatMap(m=>[data.summaries[m].total,data.summaries[m].planned]));
 const chart=`<div class="bm-history-chart" role="img" aria-label="Monthly spending and budget in dollars">${months.map(m=>{const s=data.summaries[m];return `<div class="bm-history-col"><div class="bm-history-value">${money(s.total)}</div><div class="bm-history-bars"><div class="bm-actual-mark" style="height:${s.total/max*100}%" title="Net spending ${money(s.total)}"></div><div class="bm-budget-mark" style="height:${s.planned/max*100}%" title="Budget ${money(s.planned)}"></div></div><div class="bm-history-month">${m}<br>${s.reviewed?'Reviewed':'Draft'}</div></div>`;}).join('')}</div>`;
 main.innerHTML=panel('Month to month',chart+'<p class="bm-note">Purple: net allocated spending. Gray: intended budget. Months without imported transactions may contain manually allocated expenses. Missing months aren’t treated as zero.</p>','Latest 12 visible months · USD');
 const shown=months.slice(-6);main.innerHTML+=panel('Category history',`<div class="bm-scroll-table"><table class="bm-table"><thead><tr><th>Category</th>${shown.map(m=>`<th>${m}</th>`).join('')}</tr></thead><tbody>${data.categories.map(c=>`<tr><td>${esc(c)}</td>${shown.map(m=>`<td>${data.summaries[m].missing.includes(c)?'Not identified':money(data.summaries[m].categories[c].net)}</td>`).join('')}</tr>`).join('')}<tr class="bm-total"><td>Total</td>${shown.map(m=>`<td>${money(data.summaries[m].total)}</td>`).join('')}</tr></tbody></table></div>`,'Latest 6 visible months');
}
function renderReview(){
 const summary=data.summaries[month], unresolved=data.transactions.filter(t=>t.review_reason&&t.date.startsWith(month));
 main.innerHTML=panel('Transactions to review',unresolved.map(t=>`<div class="bm-review-row"><div class="bm-review-title"><span>${esc(t.description)} · ${t.date}</span><span>${money(t.cents)}</span></div><p>${esc(t.review_reason)} Original category: ${esc(t.source_category)}.</p><div class="bm-actions bm-section-gap">${action('Edit category / treatment','edit',`data-id="${t.id}"`)}${['refund','reimbursement'].includes(t.kind)?action('Match refund or repayment','link',`data-id="${t.id}"`):''}</div></div>`).join('')||'<p class="bm-note">No unresolved transactions dated this month.</p>',`${unresolved.length} remaining`);
 const absent=data.categories.filter(c=>!summary.categories[c].count);
 main.innerHTML+=panel('Confirm monthly coverage',`<p class="bm-note">Confirm that the accounts you use are represented. Add missing expenses manually, or confirm a category had no spending.</p>${absent.map(c=>`<label class="bm-check"><input type="checkbox" class="zero-check" value="${esc(c)}" ${data.months[month].zero_categories.includes(c)?'checked':''}><span>No ${esc(c.toLowerCase())} spending in ${monthName(month)}</span></label>`).join('')}<div class="bm-actions bm-section-gap">${action('Save coverage','coverage')}${action('Add missing expense','manual')}${action('Mark month reviewed','finalize','', 'bm-primary')}</div><p class="bm-note">Refunds, repayments and later edits can revise older months. Those months return to Draft until reviewed again.</p>`);
}
function openEditor(title,body){document.getElementById('editor-content').innerHTML=`<div class="bm-editor-head"><h2 id="editor-title">${title}</h2>${action('Close','close')}</div><div id="editor-error" class="bm-error" role="alert" tabindex="-1"></div>${body}`;if(!dialog.open)dialog.showModal();dialog.scrollTop=0;}
function openTransaction(id){
 editing=id?tx(id):null;const t=editing||{date:(month||new Date().toISOString().slice(0,7))+'-01',description:'',account:'Manual',cents:-100,category:data.fallback_category||data.categories[0],kind:'expense',notes:'',manual:true};
 allocationDraft=editing?.allocations?.length?editing.allocations.map(a=>({month:a.month,amount:inputMoney(a.cents)})):[{month:t.date.slice(0,7),amount:inputMoney(Math.abs(t.cents))}];
 openEditor(editing?'Edit transaction':'Add manual entry',`<form id="transaction-form">${t.auto_subscription?`<div class="bm-import-summary"><strong>Detected monthly subscription</strong><p class="bm-note">The same vendor and amount recur in consecutive months, within seven days of the billing date. You can override the category below; saving this transaction makes your choice manual.</p>${t.auto_subscription.evidence.map(id=>{const x=tx(id);return x?`<p class="bm-tiny">${esc(x.date+' · '+x.description+' · '+x.account)} · ${money(x.cents)}</p>`:'';}).join('')}</div>`:''}<div class="bm-form-grid"><label class="bm-field-label">Date<input name="date" type="date" data-previous-month="${t.date.slice(0,7)}" value="${t.date}" ${t.manual?'':'readonly'} required></label><label class="bm-field-label">Original signed amount ($)<input name="amount" type="number" step="0.01" value="${inputMoney(t.cents)}" ${t.manual?'':'readonly'} required></label><label class="bm-field-label bm-wide">Description<input name="description" value="${esc(t.description)}" ${t.manual?'':'readonly'} required maxlength="500"></label><label class="bm-field-label bm-wide">Account<input name="account" value="${esc(t.account)}" ${t.manual?'':'readonly'}></label><label class="bm-field-label">Treatment<select name="kind" id="kind-select">${data.kinds.map(k=>`<option value="${k}" ${k===t.kind?'selected':''}>${kindLabel[k]}</option>`).join('')}</select></label><label class="bm-field-label">Budget category<select name="category" id="edit-category" ${['expense','refund','reimbursement'].includes(t.kind)?'':'disabled'}>${options(data.categories,data.categories.includes(t.category)?t.category:data.fallback_category||data.categories[0])}</select></label><label class="bm-field-label bm-wide">Notes<textarea name="notes">${esc(t.notes)}</textarea></label></div><p class="bm-note">Charges use negative amounts. Refunds and repayments use positive amounts. Imported dates and amounts remain unchanged.</p><div id="allocation-section" ${t.kind==='expense'?'':'hidden'}><h3 class="bm-section-gap">Allocate the full charge across months</h3><div id="allocation-rows"></div><div class="bm-split-tools">${action('Add month','allocation-add')}<label class="bm-field-label">Start month<input id="split-start" type="month" value="${t.date.slice(0,7)}"></label><label class="bm-field-label">Months<input id="split-count" type="number" min="1" max="120" value="12"></label>${action('Split evenly','split-even')}</div><p id="allocation-sum" class="bm-note"></p><p class="bm-note">Linked credits follow these months proportionally, with exact cent rounding.</p></div><p id="credit-instruction" class="bm-note" ${['refund','reimbursement'].includes(t.kind)?'':'hidden'}>Save the treatment, then use “Link credit” to match an earlier expense. You can link partial amounts or several expenses.</p><div class="bm-editor-actions"><button type="submit" class="bm-action bm-primary">Save transaction</button></div></form>`);
 renderAllocations();
 document.querySelectorAll('#allocation-section input').forEach(e=>e.disabled=t.kind!=='expense');
}

function renderAllocations(){
 document.getElementById('allocation-rows').innerHTML=allocationDraft.map((a,i)=>`<div class="bm-allocation-row"><input type="month" aria-label="Allocation month ${i+1}" data-allocation="${i}" data-field="month" value="${a.month}" required><input type="number" min="0.01" step="0.01" aria-label="Allocation amount ${i+1}" data-allocation="${i}" data-field="amount" value="${esc(a.amount)}" required>${action('Remove','allocation-remove',`data-index="${i}"`)}</div>`).join('');allocationSum();
}
function toCents(v){const n=Number(v);return Number.isFinite(n)?Math.round(n*100):0;}
function allocationSum(){const total=allocationDraft.reduce((s,a)=>s+toCents(a.amount),0),amount=Math.abs(toCents(document.querySelector('#transaction-form [name=amount]').value));document.getElementById('allocation-sum').textContent=`Allocated ${money(total)} of ${money(amount)} · Difference ${money(amount-total)}`;}
function openLink(id){
 editing=tx(id);linkDraft=editing.links.filter(l=>l.credit_id===id).map(l=>({expense_id:l.expense_id,amount:inputMoney(l.cents)}));
 if(!linkDraft.length)linkDraft=[{expense_id:'',amount:inputMoney(editing.cents)}];
 openEditor('Link refund or reimbursement',`<p>${esc(editing.description)} · ${editing.date} · <strong>${money(editing.cents)}</strong></p><p class="bm-note">Choose the original expense. Amount and merchant matches are suggestions; repeated charges require your choice. Credits reduce the expense’s allocated months, even in a prior year.</p><label class="bm-field-label bm-section-gap">Find an expense<input id="expense-search" type="search" placeholder="Merchant, date or amount"></label><div id="link-rows"></div><div class="bm-actions bm-section-gap">${action('Link another expense','link-add')}</div><p id="link-sum" class="bm-note"></p><div class="bm-editor-actions">${action('Save links','links-save','', 'bm-primary')}</div>`);renderLinks();
}
function renderLinks(){
 const needle=document.getElementById('expense-search').value.toLowerCase();
 const expenses=data.transactions.filter(t=>t.kind==='expense').sort((a,b)=>{
 const score=t=>(-t.cents===editing.cents?4:0)+(t.description.toLowerCase()===editing.description.toLowerCase()?6:0)+(t.date<=editing.date?1:0);
 return score(b)-score(a)||b.date.localeCompare(a.date);
 });
 document.getElementById('link-rows').innerHTML=linkDraft.map((l,i)=>`<div class="bm-link-row"><select aria-label="Original expense ${i+1}" data-link="${i}" data-field="expense_id"><option value="">Choose original expense</option>${expenses.filter(t=>t.id===l.expense_id||[t.description,t.date,money(-t.cents),inputMoney(-t.cents),t.account].join(' ').toLowerCase().includes(needle)).map(t=>`<option value="${t.id}" ${l.expense_id===t.id?'selected':''}>${esc(t.date+' · '+t.description+' · '+money(-t.cents)+(t.description===editing.description&&-t.cents===editing.cents?' · amount & merchant match':''))}</option>`).join('')}</select><input type="number" step="0.01" min="0.01" aria-label="Linked amount ${i+1}" data-link="${i}" data-field="amount" value="${esc(l.amount)}">${action('Remove','link-remove',`data-index="${i}"`)}</div>`).join('');linkSum();
}
function linkSum(){const sum=linkDraft.reduce((s,l)=>s+toCents(l.amount),0);document.getElementById('link-sum').textContent=`Linked ${money(sum)} of ${money(editing.cents)} · Unlinked ${money(editing.cents-sum)}. A partial credit stays in Review until fully linked or its treatment is changed.`;}
function openBudget(){openEditor('Budget for '+monthName(month),`<form id="budget-form"><div class="bm-form-grid">${data.categories.map(c=>`<label class="bm-field-label">${esc(c)} ($)<input name="${esc(c)}" type="number" step="0.01" min="0" value="${inputMoney(data.budgets[month][c])}" required></label>`).join('')}</div><p class="bm-note">Only this month changes. Existing months keep their saved targets.</p><div class="bm-editor-actions"><button type="submit" class="bm-action bm-primary">Save monthly budget</button></div></form>`);}
function openMonths(){
 openEditor('Manage months',`<p class="bm-note">Hide for this session applies only in this tab and survives reloads. Exclude until restored saves to your dashboard CSV. Neither option deletes data or changes expense allocations and linked credits.</p><form id="visibility-form">${Object.keys(data.months).sort().reverse().map(m=>`<label class="bm-field-label bm-section-gap">${monthName(m)}<select data-visibility="${m}"><option value="show" ${!data.months[m].excluded&&!temporaryHidden.has(m)?'selected':''}>Show</option><option value="temporary" ${!data.months[m].excluded&&temporaryHidden.has(m)?'selected':''}>Hide for this session</option><option value="exclude" ${data.months[m].excluded?'selected':''}>Exclude until restored (saved)</option></select></label>`).join('')}<div class="bm-editor-actions">${action('Show all months','show-all-months')}<button type="submit" class="bm-action bm-primary">Apply visibility</button></div></form><p class="bm-note">Hidden months leave the month selector, Trends and the default transaction view. Use “All months, including hidden” in Transactions to search everything.</p>`);
}
let previewSequence=0, importBusy=false;
function openImport(){previewSequence++;importPreview=null;openEditor('Import transactions',`<div id="import-drop" class="bm-drop"><strong>Drop your monthly CSV here</strong><p class="bm-note">Or choose a file below. No need to move or rename it.</p><label class="bm-field-label">Choose CSV<input id="import-file" type="file" accept=".csv,text/csv"></label></div><p class="bm-note">1. Choose a file. 2. Check overlaps. 3. Confirm. Your original export stays unchanged.</p><details class="bm-section-gap"><summary>Or use a CSV already in the budget folder</summary><div class="bm-file-list">${data.available_files.map(f=>action(esc(f),'preview-file',`data-file="${esc(f)}"`)).join('')}</div></details><div id="import-preview" aria-live="polite"></div>`);}
async function readImportFile(file){
 if(!file)return;
 importPreview=null;const sequence=++previewSequence;document.getElementById('import-preview').innerHTML='';
 if(!file.name.toLowerCase().endsWith('.csv'))throw Error('Choose a CSV export.');
 if(file.size>10*1024*1024)throw Error('Export exceeds 10 MB.');
 // Claim this selection before reading so a slower old read cannot replace a newer file.
 document.getElementById('import-preview').innerHTML='<p class="bm-progress-note">Reading export…</p>';
 const text=await file.text();if(sequence!==previewSequence)return;
 await preview({name:file.name,text},sequence);
}
async function preview(payload,sequence=++previewSequence){
 if(importBusy)return;
 importPreview=null;
 document.getElementById('editor-error').textContent='';
 document.getElementById('import-preview').innerHTML='<p class="bm-progress-note">Reading export…</p>';
 let p;try{p=await api('preview',payload);}catch(e){if(sequence!==previewSequence||!document.getElementById('import-preview'))return;document.getElementById('import-preview').innerHTML='';throw e;}
 if(sequence!==previewSequence||!document.getElementById('import-preview'))return;
 importPreview=p;
 if(p.already_imported){document.getElementById('import-preview').innerHTML='<p class="bm-note">This exact export has already been imported. Nothing will be added.</p>';return;}
 const conflicts=p.rows.filter(t=>t.matches.length||t.manual_matches.length||t.batch_count>1),months=[...new Set(p.rows.map(t=>t.date.slice(0,7)))].sort(),exact=conflicts.filter(t=>t.suggested_choice==='skip').length;
 document.getElementById('import-preview').innerHTML=`<div class="bm-import-summary"><strong>${esc(p.name)}</strong><p>${p.rows.length} rows · ${months[0]} through ${months.at(-1)}</p><p class="bm-note">${p.rows.length-conflicts.length} new rows. ${exact} exact overlaps preselected to skip, matched one-for-one by date, account, description and signed amount. ${conflicts.length-exact} rows need your choice.${p.format==='legacy-positive-charges'?' This older export uses positive charges; its signs will be converted to the dashboard convention.':''}</p><p class="bm-note">Exports have no stable transaction IDs. Check the choices below, especially repeated real charges. Nothing is saved until you confirm.</p></div>${conflicts.map(t=>`<details class="bm-import-row" ${t.suggested_choice?'':'open'}><summary>${t.suggested_choice?'Exact overlap · skip selected':'Needs a choice'} · ${t.date} · ${esc(t.description)} · ${money(t.cents)} · ${esc(t.account)}</summary><p class="bm-note">${t.batch_count>1?`${t.batch_count} identical rows occur in this file. These may be separate real charges. `:''}${t.exact_matches.length?`${t.exact_matches.length} matching record(s) already saved. `:''}${t.matches.length&&!t.exact_matches.length?'Same signed amount within three days; account or description may differ. ':''}</p>${[...new Set([...t.matches,...t.manual_matches])].map(id=>{const x=tx(id);return `<p class="bm-tiny">Existing: ${esc(x.date+' · '+x.description+' · '+x.account)} · ${money(x.cents)}${x.manual?' · Manual':''}</p>`;}).join('')}<select class="import-choice" data-row="${t.source_row}" aria-label="Import choice for row ${t.source_row}"><option value="">Choose how to handle this row</option><option value="skip" ${t.suggested_choice==='skip'?'selected':''}>Skip this row</option><option value="add">Add as a separate transaction</option>${t.manual_matches.map(id=>`<option value="replace:${id}">Reconcile manual: ${esc(tx(id).date+' · '+tx(id).description)}</option>`).join('')}</select></details>`).join('')}<div class="bm-editor-actions"><span id="import-totals" class="bm-note"></span>${action('Confirm import','import-confirm','', 'bm-primary')}</div>`;
 importTotals();
}
function importTotals(){
 if(!importPreview||importPreview.already_imported)return;
 const selections=[...document.querySelectorAll('.import-choice')].map(e=>e.value),skip=selections.filter(v=>v==='skip').length,reconcile=selections.filter(v=>v.startsWith('replace:')).length,pending=selections.filter(v=>!v).length;
 document.getElementById('import-totals').textContent=`${importPreview.rows.length-skip-reconcile-pending} to add · ${skip} to skip · ${reconcile} to reconcile${pending?` · ${pending} undecided`:''}`;
 document.querySelector('[data-action=import-confirm]').disabled=!!pending||importBusy;
}
root.addEventListener('dragover',e=>{if(e.target.closest('#import-drop')){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
root.addEventListener('drop',async e=>{if(!e.target.closest('#import-drop'))return;e.preventDefault();try{if(importBusy)return;if(e.dataTransfer.files.length!==1)throw Error('Drop one CSV at a time.');await readImportFile(e.dataTransfer.files[0]);}catch(error){showError(error);}});
dialog.addEventListener('cancel',e=>{if(saving)e.preventDefault();});
dialog.addEventListener('close',()=>{previewSequence++;});
root.addEventListener('keydown',e=>{
 const tab=e.target.closest('[data-view]');if(!tab||saving)return;
 const tabs=[...document.querySelectorAll('[data-view]')],index=tabs.indexOf(tab);
 const next={ArrowRight:(index+1)%tabs.length,ArrowLeft:(index+tabs.length-1)%tabs.length,Home:0,End:tabs.length-1}[e.key];
 if(next===undefined)return;e.preventDefault();tabs[next].focus();tabs[next].click();
});
root.addEventListener('click',async e=>{
 if(saving)return;
 if(e.target.closest('[data-action=reload]')){location.reload();return;}
 if(!data){showError(Error('Saved data has not loaded. Reload the dashboard to reconnect.'));return;}
 const nav=e.target.closest('[data-view]');if(nav){view=nav.dataset.view;render();return;}
 const b=e.target.closest('[data-action]');if(!b)return;const a=b.dataset.action;
 try{
  if(['month','transactions','trends','review'].includes(a)){view=a;render();}
  else if(a==='close'){previewSequence++;dialog.close();}
  else if(a==='manage-months')openMonths();
  else if(a==='show-all-months')document.querySelectorAll('[data-visibility]').forEach(e=>e.value='show');
  else if(a==='manual')openTransaction(null);
  else if(a==='edit')openTransaction(b.dataset.id);
  else if(a==='link')openLink(b.dataset.id);
  else if(a==='budget')openBudget();
  else if(a==='new-month')openEditor('Add a month',`<form id="month-form"><label class="bm-field-label">Month<input name="month" type="month" value="${month}" required></label><div class="bm-editor-actions"><button class="bm-action bm-primary" type="submit">Add month</button></div></form>`);
  else if(a==='category'){view='transactions';categoryFilter=b.dataset.category;scope=month;query='';page=0;render();}
  else if(a==='clear-filters'){query='';categoryFilter='';scope='visible';page=0;renderLedger();document.getElementById('search').focus();}
  else if(a==='prev'||a==='next'){page+=a==='next'?1:-1;renderLedgerRows();}
  else if(a==='allocation-add'){allocationDraft.push({month:month,amount:'0.00'});renderAllocations();}
  else if(a==='allocation-remove'){allocationDraft.splice(Number(b.dataset.index),1);renderAllocations();}
  else if(a==='split-even'){
   const start=document.getElementById('split-start').value,n=Number(document.getElementById('split-count').value),total=Math.abs(toCents(document.querySelector('#transaction-form [name=amount]').value));
   if(!start||!Number.isInteger(n)||n<1||n>120||total<n)throw Error('Choose a start month and 1–120 months, with at least one cent per month.');
   const [y,m]=start.split('-').map(Number);allocationDraft=Array.from({length:n},(_,i)=>({month:`${y+Math.floor((m-1+i)/12)}-${String((m-1+i)%12+1).padStart(2,'0')}`,amount:inputMoney(Math.floor(total/n)+(i<total%n?1:0))}));renderAllocations();
  }
  else if(a==='link-add'){linkDraft.push({expense_id:'',amount:'0.00'});renderLinks();}
  else if(a==='link-remove'){linkDraft.splice(Number(b.dataset.index),1);renderLinks();}
  else if(a==='links-save'){await save('links',{id:editing.id,links:linkDraft});}
  else if(a==='coverage'||a==='finalize'){const zeros=[...document.querySelectorAll('.zero-check:checked')].map(e=>e.value);await save('month',{month,zero_categories:zeros,reviewed:a==='finalize'},false);}
  else if(a==='import')openImport();
  else if(a==='preview-file')await preview({filename:b.dataset.file});
  else if(a==='import-confirm'){
   if(importBusy||!importPreview)return;
   const choices=Object.fromEntries([...document.querySelectorAll('.import-choice')].map(e=>[e.dataset.row,e.value]));
   if(Object.values(choices).some(v=>!v))throw Error('Choose what to do with every possible overlap.');
   importBusy=true;b.disabled=true;
   try{const result=await save('import',{token:importPreview.token,choices});flash(`Imported ${result.added} transactions; reconciled ${result.reconciled} manual entries; skipped ${result.skipped} rows. ${result.detected_subscriptions||0} transactions automatically tagged as monthly subscriptions across your imported history.`);}
   finally{importBusy=false;if(dialog.open&&document.getElementById('import-totals'))importTotals();}
  }
  else if(a==='download'){
   const response=await fetch('/api/download',{headers:{'X-Budget-Token':token}});if(!response.ok)throw Error('Unable to download saved data.');
   const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='dashboard_data.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
 }catch(error){showError(error);}
});
root.addEventListener('input',e=>{
 const t=e.target;
 if(t.id==='search'){query=t.value;page=0;renderLedgerRows();}
 if(t.dataset.allocation!==undefined){allocationDraft[Number(t.dataset.allocation)][t.dataset.field]=t.value;allocationSum();}
 if(t.dataset.link!==undefined){linkDraft[Number(t.dataset.link)][t.dataset.field]=t.value;linkSum();}
 if(t.id==='expense-search')renderLinks();
 if(t.name==='amount'&&document.getElementById('allocation-sum')){if(allocationDraft.length===1){allocationDraft[0].amount=inputMoney(Math.abs(toCents(t.value)));renderAllocations();}else allocationSum();}
});
root.addEventListener('change',async e=>{
 const t=e.target;
 try{
  if(t.id==='sort-field'||t.id==='sort-direction'){sortField=document.getElementById('sort-field').value;sortDirection=document.getElementById('sort-direction').value;page=0;renderLedgerRows();}
  if(t.id==='month-select'){month=t.value;render();}
  if(t.id==='category-filter'){categoryFilter=t.value;page=0;renderLedgerRows();}
  if(t.id==='scope-filter'){scope=t.value;page=0;renderLedgerRows();}
  if(t.name==='date'&&!editing){
   const next=t.value.slice(0,7),previous=t.dataset.previousMonth;
   if(next&&allocationDraft.length===1&&allocationDraft[0].month===previous){allocationDraft[0].month=next;renderAllocations();}
   if(next){if(document.getElementById('split-start').value===previous)document.getElementById('split-start').value=next;t.dataset.previousMonth=next;}
  }
  if(t.id==='kind-select'){document.getElementById('allocation-section').hidden=t.value!=='expense';document.getElementById('credit-instruction').hidden=!['refund','reimbursement'].includes(t.value);document.querySelector('[name=category]').disabled=!['expense','refund','reimbursement'].includes(t.value);document.querySelectorAll('#allocation-section input').forEach(e=>e.disabled=t.value!=='expense');}
  if(t.classList.contains('import-choice'))importTotals();
  if(t.id==='import-file'&&t.files[0]&&!importBusy)await readImportFile(t.files[0]);
 }catch(error){showError(error);}
});
root.addEventListener('submit',async e=>{
 e.preventDefault();if(saving)return;const form=e.target;const values=Object.fromEntries(new FormData(form));
 try{
  if(form.id==='transaction-form'){
   if(values.kind==='expense'&&!allocationDraft.length)throw Error('Add at least one allocation month for this expense.');
   await save('transaction',{...values,id:editing?.id,allocations:values.kind==='expense'?allocationDraft:[]});
  }
  if(form.id==='budget-form')await save('budget',{month,budget:values});
  if(form.id==='visibility-form'){
   const selections=[...form.querySelectorAll('[data-visibility]')],excluded=selections.filter(e=>e.value==='exclude').map(e=>e.dataset.visibility);
   const nextTemporary=new Set(selections.filter(e=>e.value==='temporary').map(e=>e.dataset.visibility));
   const previous=Object.keys(data.months).filter(m=>data.months[m].excluded).sort();
   if(JSON.stringify(previous)!==JSON.stringify([...excluded].sort()))await save('visibility',{excluded},false);
   temporaryHidden=nextTemporary;rememberHidden();render();dialog.close();flash('Month visibility updated. All transactions are preserved.');
  }
  if(form.id==='month-form'){await save('month',{month:values.month});month=values.month;render();if(!visibleMonths().includes(values.month))flash('This month is hidden. Restore it in Manage months.');}
 }catch(error){showError(error);}
});
refresh().catch(e=>{main.innerHTML='<p class="bm-error">Open the dashboard with Open Budget.command, then reload saved data.</p>';document.getElementById('save-status').textContent='Disconnected';showError(e);});
