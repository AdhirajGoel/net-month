const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const elements=new Map();
const element=id=>{
 if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',open:false,addEventListener(){},setAttribute(){},querySelectorAll:()=>[],querySelector:()=>({disabled:false}),close(){this.open=false;},classList:{toggle(){}}});
 return elements.get(id);
};
const categories=['Rent + utilities','Car loan','Auto insurance','Groceries+Food','Gas','Subscriptions','Miscellaneous'];
const fixture={budgets:{},months:{},summaries:{},categories,transactions:[],imports:[]};
for(const m of ['2026-09','2026-10','2027-08']){
 fixture.budgets[m]=Object.fromEntries(categories.map(c=>[c,10000]));
 fixture.months[m]={reviewed:false,zero_categories:[]};
 fixture.summaries[m]={categories:Object.fromEntries(categories.map(c=>[c,{count:m==='2026-10'?1:0,gross:0,credits:0,net:0}])),budget:fixture.budgets[m],planned:70000,total:0,gross:0,credits:0,missing:[],unresolved:0,complete:true};
}
const context=vm.createContext({
 document:{getElementById:element,querySelector:()=>({content:'test'}),querySelectorAll:()=>[]},
 sessionStorage:{getItem:()=>null},
 fetch:async()=>({ok:true,json:async()=>fixture}),
 Date:class extends Date{constructor(...args){super(...(args.length?args:['2026-10-30T12:00:00']));}},
});
const source=fs.readFileSync(__dirname+'/app.js','utf8');
// Load the real UI functions without its automatic first network request.
vm.runInContext(source.slice(0,source.lastIndexOf('refresh().catch')),context);
const run=code=>vm.runInContext(code,context);

(async()=>{
 run("view='review'");
 await run('refresh()');
 assert.equal(run('month'),'2026-10','Open October instead of a future allocation month');
 assert.doesNotMatch(element('main-content').innerHTML,/class="zero-check"/,'Recorded spending must not prompt for zero-spend confirmation');
 run('renderMonth()');
 assert.match(element('main-content').innerHTML,/data-category="Groceries\+Food"/);
 assert.doesNotMatch(element('main-content').innerHTML,/Food within Miscellaneous|data-category="food"/,'Food appears only in the combined category');

 run("month='2026-09'");
 await run('refresh()');
 assert.equal(run('month'),'2026-09','Keep an explicitly selected month after saving');
 assert.match(element('main-content').innerHTML,/No rent \+ utilities spending in September 2026/);

 run("month='';temporaryHidden.add('2026-10')");
 await run('refresh()');
 assert.equal(run('month'),'2026-09','Prefer the latest visible past month when the current month is hidden');

 fixture.months['2026-09'].excluded=true;
 run('render()');
 assert.equal(run('month'),'2027-08','Allow a future month when it is the only visible month');
 fixture.months['2027-08'].excluded=true;
 run('render()');
 assert.equal(run('month'),'','Handle all months hidden');
 assert.equal(element('month-heading').textContent,'All months hidden');

 // Exercise the actual save function: a failed reload must never invite a duplicate save.
 run("view='review';month='2026-10';temporaryHidden.clear()");
 let posts=0;
 context.fetch=async(path,settings)=>{
  if(settings.method==='POST'){posts++;return {ok:true,json:async()=>({saved:true})};}
  throw Error('Offline during refresh');
 };
 element('editor').open=true;
 await assert.rejects(run("save('transaction',{})"),/Your change was saved/);
 assert.equal(element('save-status').textContent,'Saved · reload needed');
 assert.equal(element('editor').open,false);
 await assert.rejects(run("save('transaction',{})"),/Reload saved data/);
 assert.equal(posts,1,'Do not resend a committed change');

 run('needsReload=false');element('editor').open=true;
 context.fetch=async()=>({ok:false,status:400,json:async()=>({error:'Allocations do not add up'})});
 await assert.rejects(run("save('transaction',{})"),/Allocations do not add up/);
 assert.equal(element('editor').open,true,'Keep the draft after a rejected edit');
 assert.equal(run('needsReload'),false);
 assert.equal(element('save-status').textContent,'Not saved');

 context.fetch=async()=>{throw Error('Connection lost');};
 await assert.rejects(run("save('transaction',{})"),/may already be saved/);
 assert.equal(element('save-status').textContent,'Save unconfirmed');
 assert.equal(run('needsReload'),true);

 run('needsReload=false');
 context.fetch=async()=>({ok:false,status:409,json:async()=>({error:'Data changed in another window'})});
 await assert.rejects(run("save('transaction',{})"),/another window/);
 assert.equal(run('needsReload'),true);

 run('needsReload=false');let release;
 context.fetch=async(path,settings)=>settings.method==='POST'?new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({saved:true})});}):{ok:true,json:async()=>fixture};
 const pending=run("save('transaction',{})");
 await assert.rejects(run("save('transaction',{})"),/already in progress/);
 release();await pending;
 assert.equal(run('saving'),false);
 assert.equal(element('save-status').textContent,'Saved locally');
 console.log('Month selection, coverage, save failures and concurrent-save regression checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
