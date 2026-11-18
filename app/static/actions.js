const alloyState={busy:false};const meta=JSON.parse(document.querySelector('#run-meta').textContent);const feedback=document.querySelector('#feedback');
async function submitAlloy(url,payload){if(alloyState.busy)return;alloyState.busy=true;feedback.textContent='正在复算…';document.querySelectorAll('button').forEach(b=>b.disabled=true);try{const options={method:'POST'};if(payload instanceof FormData){options.body=payload}else{options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(payload)}const response=await fetch(url,options);const data=await response.json();if(!response.ok)throw Error(data.message||'请求失败，请重试');if(data.manifest){location.href=location.pathname+'?run_id='+encodeURIComponent(data.manifest.run_id)}else{location.reload()}}catch(error){feedback.textContent=error.message}finally{alloyState.busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false)}}
document.querySelector('#sample').addEventListener('click',()=>submitAlloy('/api/run',{}));document.querySelector('#submit').addEventListener('click',()=>submitAlloy('/api/run',{csv:document.querySelector('#csv').value}));document.querySelector('#upload').addEventListener('click',()=>{const file=document.querySelector('#file').files[0];if(!file){feedback.textContent='先选择CSV文件。';return}const form=new FormData();form.append('file',file);submitAlloy('/api/run',form)});document.querySelectorAll('[data-decision]').forEach(button=>button.addEventListener('click',()=>submitAlloy('/api/review',{...meta,decision:button.dataset.decision})));document.querySelector('#print').addEventListener('click',()=>window.print());
function idemKey(batch,grade){const store=window.localStorage;const name='idem_'+batch+'_'+grade;let key=store.getItem(name);if(!key){key=(crypto.randomUUID?crypto.randomUUID():'id-'+Date.now()+'-'+Math.random().toString(16).slice(2));store.setItem(name,key)}return key}
async function openRelease(button){
  const panel=document.querySelector('#release-feedback');panel.textContent='正在提交放行单…';
  const payload={run_id:meta.id,batch:button.dataset.batch,grade:button.dataset.grade,idem_key:idemKey(button.dataset.batch,button.dataset.grade)};
  try{
    const response=await fetch('/api/releases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await response.json();
    if(!response.ok)throw Error(data.message||'放行失败');
    panel.textContent='放行单已生效：'+data.id+'（重试不会重复开立）';location.reload();
  }catch(error){panel.textContent=error.message}
}
document.querySelectorAll('[data-release]').forEach(button=>button.addEventListener('click',()=>openRelease(button)));
const whatifButton=document.querySelector('#whatif-run');
if(whatifButton){whatifButton.addEventListener('click',async()=>{
  const out=document.querySelector('#whatif-out'),tip=document.querySelector('#whatif-feedback');tip.textContent='试算中…';out.innerHTML='';
  const payload={orders:document.querySelector('#orders-csv').value,now:document.querySelector('#now-iso').value.trim(),retest_hours:document.querySelector('#retest-hours').value.trim()};
  try{
    const response=await fetch('/api/m8',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await response.json();
    if(!response.ok)throw Error(data.message||'试算失败');
    tip.textContent='';
    data.rows.forEach(r=>{
      const card=document.createElement('article');card.className='decision decision--'+r['决定'];
      card.innerHTML='<div class="decision__head"><h3>炉次 '+r['炉次']+'</h3><span class="badge badge--'+r['决定']+'">'+r['决定']+'</span>'+(r['放行牌号']!='—'?'<span class="grade-tag">'+r['放行牌号']+'</span>':'')+'</div><p class="basis">'+r['依据']+'</p>';
      out.appendChild(card);
    });
  }catch(error){tip.textContent=error.message}
});}
