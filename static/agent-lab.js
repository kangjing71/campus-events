const role=location.pathname.split('/')[2];
const roles={planning:['策划','clipboard-list'],publicity:['宣传','megaphone'],registration:['报名','users'],onsite:['现场','radio'],review:['复盘','chart-no-axes-combined']};
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon=n=>`<i data-lucide="${n}"></i>`;
let key=sessionStorage.getItem('campus-key')||'', config=null, tasks=[], selected='', busy=false, current=null, runs=[], noticeTimer;
const drafts={};
const hashKey=new URLSearchParams(location.hash.slice(1)).get('key');
if(hashKey){key=hashKey;sessionStorage.setItem('campus-key',key);history.replaceState(null,'',location.pathname);}
try{runs=JSON.parse(sessionStorage.getItem('agent-lab-'+role)||'[]');if(!Array.isArray(runs))runs=[];}catch{runs=[];}
const labels={brief:'已提取需求',reply:'Agent 回复',questions:'补充问题',missing_fields:'仍需补充',summary:'总结',timeline:'活动时间线',preparation:'筹备时间线',roles:'人员分工',budget:'预算',materials:'物资',risks:'风险预案',targets:'成功指标',article:'公众号文案',group:'群聊文案',schedule:'宣传节奏',approved:'确认状态',answer:'答复草稿',needs_human:'需要人工补充',reason:'依据与说明',evidence:'事实依据',suggestions:'改进建议',needs_attention:'待处理事项',issues:'现场问题',adjustment:'调整建议',findings:'分析发现',metrics:'实际统计',comparison:'目标对比',generated_at:'生成时间',name:'名称',objective:'目标',type:'类型',level:'级别',format:'形式',date:'开始时间',location:'地点',audience:'参与对象',organizer:'主办方',owner:'负责人',capacity:'容量',duration:'时长（分钟）',constraints:'额外约束',time:'时间',title:'环节',day:'相对时间',task:'任务',role:'职责',item:'项目',amount:'金额',registration:'报名人数',attendance:'到场人数',attendance_rate:'到场率（%）',feedback:'反馈人数',satisfaction:'满意度',rating_count:'评分样本数',topic:'问题',evidence_ids:'证据编号',suggestion:'建议',item_id:'调整起点',minutes:'顺延分钟',observation:'事实发现',hypothesis:'可能原因',key:'指标',target:'目标',actual:'实际',met:'是否达成',id:'编号'};
async function api(path,data){const response=await fetch(path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+key},...(data===undefined?{}:{body:JSON.stringify(data)})});const value=await response.json();if(!response.ok){const error=new Error(value.error||'请求失败');error.status=response.status;throw error;}return value;}
function toast(message,error=false){const node=$('#toast');node.textContent=message;node.className=error?'error':'';node.style.display='block';clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>node.style.display='none',5000);}
function nav(){return `<header class="lab-top"><div class="brand"><span class="brand-mark">${icon('sprout')}</span>校园共创</div><a href="/">${icon('arrow-left')}活动工作台</a></header><main class="lab-main"><nav class="lab-nav" aria-label="业务 Agent">${Object.entries(roles).map(([id,[name,ico]])=>`<a href="/agents/${id}" class="${id===role?'active':''}" ${id===role?'aria-current="page"':''}>${icon(ico)}${name} Agent</a>`).join('')}</nav><div id="body"></div></main>`;}
function login(error=''){$('#lab').innerHTML=nav();$('#body').innerHTML=`<section class="lab-login"><h1>${roles[role][0]} Agent 独立测试</h1><form id="login-form"><div class="field"><label for="login-key">负责人访问密钥</label><input id="login-key" type="password" name="key" autocomplete="current-password" required></div>${error?`<div class="lab-error" role="alert">${esc(error)}</div>`:''}<div class="form-actions"><button class="primary" type="submit">进入测试${icon('arrow-right')}</button></div></form></section>`;window.refreshIcons();}
async function load(){const info=await api(`/api/agents/${role}/playground`);config=info.config;tasks=info.tasks;selected=selected||tasks[0].id;render();}
function capture(){if($('#input-json'))drafts[selected]={text:$('#input-json').value,message:$('#message').value};}
function render(){
  const task=tasks.find(t=>t.id===selected),draft=drafts[selected]||{text:JSON.stringify(task.input,null,2),message:task.message};
  $('#lab').innerHTML=nav();
  $('#body').innerHTML=`<div class="lab-title-row"><h1>${roles[role][0]} Agent 独立测试</h1><div class="actions"><button id="connection" ${config.mode!=='model'?'disabled':''}>${icon('plug-zap')}测试连接</button><button class="icon-btn" id="reload-config" title="刷新配置">${icon('refresh-cw')}</button></div></div><div class="lab-status"><span class="badge ${config.mode==='model'?'':'amber'}">${esc({model:'模型已配置',rules:'规则模式 · 未连接模型',error:'配置异常'}[config.mode]||'未知状态')}</span><span class="lab-config">${esc(config.model||'')} ${esc(config.protocol||'')} · ${esc(config.prompt_file||'')}</span></div><div class="inline-note lab-disclaimer">独立测试 · 示例输入 · 不写入正式活动</div>${config.error?`<div class="lab-error" role="alert">${esc(config.error)}</div>`:''}<div class="lab-grid"><section class="lab-input"><form id="test-form"><div class="lab-controls"><div class="field"><label for="task">测试任务</label><select id="task">${tasks.map(t=>`<option value="${t.id}" ${t.id===selected?'selected':''}>${esc(t.name)}</option>`).join('')}</select></div><button class="icon-btn" type="button" id="reset-input" title="恢复示例输入">${icon('rotate-ccw')}</button></div><div class="field"><label for="message">补充要求 / 对话消息</label><textarea id="message" class="lab-message" maxlength="6000" ${selected==='collect_brief'?'required':''}>${esc(draft.message)}</textarea></div><div class="spacer"></div><div class="field"><label for="input-json">测试数据（JSON）</label><textarea id="input-json" class="lab-textarea" spellcheck="false" required>${esc(draft.text)}</textarea></div><div id="input-error" role="alert"></div><div class="form-actions"><button class="primary" id="run-test" type="submit" ${config.mode==='error'?'disabled':''}>${icon('play')}${config.mode==='model'?'运行效果测试':'预览规则结果'}</button></div></form><div class="lab-history"><div class="field"><label for="history">本角色最近的测试</label><select id="history"><option value="">选择一条结果</option>${runs.map((r,i)=>`<option value="${i}">${esc(r.at)} · ${esc(r.task_name)} · ${r.run.mode==='model'?'模型':'规则'}</option>`).join('')}</select></div></div></section><section class="lab-result"><div class="section-head"><h2>生成结果</h2><div class="actions"><button class="icon-btn" id="copy-result" title="复制结果" ${current?'':'disabled'}>${icon('copy')}</button><button class="icon-btn" id="download-result" title="下载结果" ${current?'':'disabled'}>${icon('download')}</button></div></div><div id="result" aria-live="polite">${current?resultHTML(current):'<div class="empty">'+icon('flask-conical')+'<p>等待测试结果</p></div>'}</div></section></div>`;
  window.refreshIcons();
  if(!['collect_brief','generate_plan','generate_publicity','generate_recap','analyze_onsite'].includes(selected))$('#message').parentElement.style.display='none';
}
function human(value,depth=0){
  if(value===null)return '<span class="muted">暂无 / 无需调整</span>';
  if(typeof value==='boolean')return value?'是':'否';
  if(typeof value!=='object')return esc(labels[value]||value);
  if(Array.isArray(value)){
    if(!value.length)return '<span class="muted">无</span>';
    if(value.every(v=>v&&typeof v==='object'&&!Array.isArray(v))){const keys=[...new Set(value.flatMap(Object.keys))];return `<div class="table-wrap"><table><thead><tr>${keys.map(k=>`<th>${esc(labels[k]||k)}</th>`).join('')}</tr></thead><tbody>${value.map(v=>`<tr>${keys.map(k=>`<td>${human(v[k]??null,depth+1)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
    return '<ul>'+value.map(v=>'<li>'+human(v,depth+1)+'</li>').join('')+'</ul>';
  }
  return Object.entries(value).map(([k,v])=>`<h3>${esc(labels[k]||k)}</h3><div>${typeof v==='object'?human(v,depth+1):'<p>'+human(v,depth+1)+'</p>'}</div>`).join('');
}
function resultHTML(r){return `<div class="lab-meta"><span class="badge ${r.run.mode==='model'?'':'amber'}">${r.run.mode==='model'?'模型生成':'规则预览 · 非模型效果'}</span><span class="badge">结构校验通过</span><span class="muted">${r.run.duration_ms} ms · ${esc(r.task_name)}</span></div>${r.run.tools?.length?`<div class="lab-tools">工具调用：${r.run.tools.map(esc).join(' → ')}</div>`:''}<div class="lab-output">${human(r.result)}</div>${r.task==='collect_brief'?'<div class="form-actions"><button type="button" id="continue-chat">'+icon('message-square')+'继续补充需求</button></div>':''}<details class="lab-details"><summary>原始 JSON 与调用记录</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details><p class="lab-footer">测试结果未保存到正式活动</p>`;}
async function operation(fn){if(busy)return;busy=true;const controls=[...document.querySelectorAll('button,input,textarea,select')].map(n=>[n,n.disabled]);controls.forEach(([n])=>n.disabled=true);document.querySelectorAll('.lab-nav a,.lab-top a').forEach(a=>a.setAttribute('aria-disabled','true'));try{await fn();}catch(e){if(e.status===401){key='';sessionStorage.removeItem('campus-key');login(e.message);}else{toast(e.message,true);if($('#input-error'))$('#input-error').innerHTML=`<div class="lab-error">${esc(e.message)}</div>`;}}finally{busy=false;controls.forEach(([n,disabled])=>n.disabled=disabled);for(const id of ['#copy-result','#download-result'])if($(id))$(id).disabled=!current;document.querySelectorAll('[aria-disabled]').forEach(a=>a.removeAttribute('aria-disabled'));window.refreshIcons();}}
document.addEventListener('submit',ev=>{
  ev.preventDefault();
  if(ev.target.id==='login-form'){const value=new FormData(ev.target).get('key').trim();operation(async()=>{key=value;await load();sessionStorage.setItem('campus-key',key);});return;}
  if(ev.target.id==='test-form'){
    capture();let input;try{input=JSON.parse(drafts[selected].text);}catch{$('#input-error').innerHTML='<div class="lab-error">测试数据不是有效 JSON，请检查引号、逗号和括号。</div>';return;}
    const task=tasks.find(t=>t.id===selected),request={task:selected,input,message:drafts[selected].message};
    operation(async()=>{
      current=null;
      $('#input-error').innerHTML='';$('#result').innerHTML='<div class="lab-wait">'+icon('loader-circle')+'正在生成与校验…</div>';window.refreshIcons();
      try{const response=await api(`/api/agents/${role}/playground`,request);current={...response,task_name:task.name,at:new Date().toLocaleString('zh-CN'),request};runs.unshift(current);runs=runs.slice(0,10);try{sessionStorage.setItem('agent-lab-'+role,JSON.stringify(runs));}catch{toast('结果已生成，但浏览器历史空间不足',true);}render();}
      catch(e){if($('#result'))$('#result').innerHTML='<div class="lab-error">'+esc(e.message)+'</div>';throw e;}
    });
  }
});
document.addEventListener('change',ev=>{if(busy)return;if(ev.target.id==='task'){capture();selected=ev.target.value;current=null;render();}if(ev.target.id==='history'&&ev.target.value!==''){capture();current=runs[Number(ev.target.value)];selected=current.task;drafts[selected]={text:JSON.stringify(current.request.input,null,2),message:current.request.message};render();}});
document.addEventListener('click',ev=>{
  if(busy&&ev.target.closest('a')){ev.preventDefault();return;}
  const b=ev.target.closest('button');if(!b||b.disabled||busy)return;
  if(b.id==='reset-input'){delete drafts[selected];current=null;render();}
  if(b.id==='reload-config'){capture();operation(load);}
  if(b.id==='connection')operation(async()=>{await api(`/api/agents/${role}/test`,{});toast('连接与 JSON 输出测试通过');});
  if(b.id==='continue-chat'){drafts.collect_brief={text:JSON.stringify(current.next_input,null,2),message:''};selected='collect_brief';render();$('#message').focus();}
  if(b.id==='copy-result')operation(async()=>{await navigator.clipboard.writeText(JSON.stringify(current,null,2));toast('测试结果已复制');});
  if(b.id==='download-result'){const blob=new Blob([JSON.stringify(current,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=role+'-'+current.task+'-result.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
});
if(key)operation(load);else login();
