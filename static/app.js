const $ = (q) => document.querySelector(q);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<i data-lucide="${name}"></i>`;
const labels = {DRAFT:'待补全策划',WAITING_PLAN_CONFIRMATION:'策划待确认',PLAN_CONFIRMED:'待生成宣传',WAITING_PUBLICITY_CONFIRMATION:'宣传待确认',REGISTRATION_OPEN:'报名进行中',LIVE:'现场进行中',FEEDBACK:'反馈收集中',WAITING_REVIEW_CONFIRMATION:'复盘待确认',WAITING_RECAP_CONFIRMATION:'总结待确认',COMPLETED:'已归档'};
const pages = [['overview','layout-dashboard','活动总览'],['plan','clipboard-list','活动策划'],['publicity','megaphone','宣传中心'],['registration','users','报名管理'],['onsite','radio','现场执行'],['review','chart-no-axes-combined','活动复盘']];
const statePage = {DRAFT:'plan',WAITING_PLAN_CONFIRMATION:'plan',PLAN_CONFIRMED:'publicity',WAITING_PUBLICITY_CONFIRMATION:'publicity',REGISTRATION_OPEN:'registration',LIVE:'onsite',FEEDBACK:'review',WAITING_REVIEW_CONFIRMATION:'review',WAITING_RECAP_CONFIRMATION:'review',COMPLETED:'review'};
let events = [], event = null, page = 'overview', view = 'home', mode = 'rules', pubTab = 'article', publicData = null;
let agentSettings = {};
let publicOrigin = location.origin;
let fieldCounter = 0;
let key = sessionStorage.getItem('campus-key') || '', busy = false, timer;
const hashKey = new URLSearchParams(location.hash.slice(1)).get('key');
if (hashKey) { key = hashKey; sessionStorage.setItem('campus-key', key); history.replaceState(null,'',location.pathname); }
const publicId = location.pathname.startsWith('/join/') ? location.pathname.split('/')[2] : null;

async function api(path, body) {
  const options = {headers:{'Content-Type':'application/json'}};
  if (!path.startsWith('/api/public/')) options.headers.Authorization = 'Bearer ' + key;
  if (body !== undefined) { options.method = 'POST'; options.body = JSON.stringify(body); }
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
function toast(message, error=false) {
  const node = $('#toast'); node.textContent=message; node.className=error?'error':''; node.style.display='block';
  clearTimeout(timer); timer=setTimeout(()=>node.style.display='none',5000);
}
async function run(fn) {
  if (busy) return;
  busy=true;
  const buttons=[...document.querySelectorAll('button')].map(b=>[b,b.disabled]); buttons.forEach(([b])=>b.disabled=true);
  try { await fn(); } catch(e) { toast(e.message,true); }
  finally { busy=false; buttons.forEach(([b,disabled])=>b.disabled=disabled); refresh(); }
}
function refresh() { window.refreshIcons?.(); if (event && $('#qr')) drawQR(); }
function fmt(v) { return v ? String(v).replace('T',' ').slice(0,16) : '待确定'; }
function day(v) { return v ? String(v).slice(0,10).replaceAll('-','.') : '待确定'; }
function formData(form) { return Object.fromEntries(new FormData(form)); }
function badge(state) { return `<span class="badge ${state.includes('WAITING')?'amber':''}"><span class="dot"></span>${esc(labels[state])}</span>`; }
function link() { return publicOrigin + '/join/' + event.id; }
function empty(title, sub='', button='') { return `<div class="empty">${icon('folder-open')}<h2>${title}</h2><p>${sub}</p>${button}</div>`; }
function button(label, action, primary=false, ico='arrow-right') { return `<button ${primary?'class="primary"':''} data-action="${action}">${icon(ico)}${label}</button>`; }
function field(name,label,type='text',value='',extra='') { const id='f-'+name+'-'+(++fieldCounter);return `<div class="field"><label for="${id}">${label}</label><input id="${id}" name="${name}" type="${type}" value="${esc(value)}" ${extra}></div>`; }
function metricCards(e) {
  const m=e.metrics,b=e.brief, t=e.plan?.targets || {};
  return `<div class="stats">${[
    ['报名人数',m.registration,b.capacity || '—','users',b.capacity?Math.min(100,m.registration/b.capacity*100):0,'目标报名人数'],
    ['现场签到',m.attendance,t.attendance || '—','scan-line',m.registration?m.attendance/m.registration*100:0,m.attendance_rate===null?'暂无签到数据':`到场率 ${m.attendance_rate}%`],
    ['参与者反馈',m.feedback,t.feedback || '—','message-square',t.feedback?Math.min(100,m.feedback/t.feedback*100):0,'按参与者去重统计'],
    ['活动满意度',m.satisfaction??'—','5.0','star',m.satisfaction?m.satisfaction/5*100:0,m.rating_count?`${m.rating_count} 份有效评分`:'等待参与者评分']
  ].map(([label,value,target,ico,progress,note])=>`<div class="stat"><div class="stat-top">${label}${icon(ico)}</div><div class="stat-value">${value}<small>/ ${target}</small></div><div class="progress"><span style="width:${progress}%"></span></div><div class="stat-foot">${note}</div></div>`).join('')}</div>`;
}
function stages(e) {
  const index={DRAFT:0,WAITING_PLAN_CONFIRMATION:0,PLAN_CONFIRMED:1,WAITING_PUBLICITY_CONFIRMATION:1,REGISTRATION_OPEN:2,LIVE:3,FEEDBACK:4,WAITING_REVIEW_CONFIRMATION:4,WAITING_RECAP_CONFIRMATION:5,COMPLETED:6}[e.state];
  return `<div class="stages">${[['clipboard-check','策划确认'],['megaphone','宣传准备'],['users','活动报名'],['radio','现场执行'],['chart-no-axes-combined','反馈复盘'],['flag','总结归档']].map(([ico,label],i)=>`<div class="stage ${i<index?'done':i===index?'current':''}"><div class="stage-icon">${icon(i<index?'check':ico)}</div>${label}<small>${i<index?'已完成':i===index?'进行中':'待开始'}</small></div>`).join('')}</div>`;
}
const nextTasks={DRAFT:['补全活动策划','活动目标、时间地点与人员安排','开始策划'],WAITING_PLAN_CONFIRMATION:['策划方案待确认','核对活动安排、预算与成功指标','查看策划'],PLAN_CONFIRMED:['准备活动宣传','报名入口已创建，等待宣传内容','生成宣传'],WAITING_PUBLICITY_CONFIRMATION:['宣传内容待确认','确认后即可开放报名入口','预览宣传'],REGISTRATION_OPEN:['关注报名进度','核对参与者需求与待回复问题','管理报名'],LIVE:['活动现场进行中','关注签到、流程与实时反馈','进入现场'],FEEDBACK:['汇总参与者反馈','核对真实数据，生成活动复盘','查看复盘'],WAITING_REVIEW_CONFIRMATION:['复盘报告待确认','确认后生成活动总结宣传稿','审阅报告'],WAITING_RECAP_CONFIRMATION:['总结宣传待确认','确认文案后完成本次活动归档','查看总结'],COMPLETED:['本次活动已归档','活动数据与执行记录已保留','查看报告']};
function overview() {
  const e=event,b=e.brief;
  const tasks=nextTasks[e.state];
  return `<div class="overview-grid"><div class="event-feature">${badge(e.state)}<h2>${esc(b.name)}</h2><div class="event-meta"><span>${icon('calendar-days')}${day(b.date)}</span><span>${icon('map-pin')}${esc(b.location||'地点待确定')}</span><span>${icon('users')}${esc(b.organizer||'主办方待确定')}</span></div></div><div class="next-task"><span class="eyebrow">下一步 · NEXT UP</span><h3>${tasks[0]}</h3><p>${tasks[1]}</p><button class="primary" data-page="${statePage[e.state]}">${tasks[2]}${icon('arrow-up-right')}</button></div></div>
  ${metricCards(e)}<div class="section-head"><h2>活动进程</h2><span class="small muted">负责人确认后推进</span></div>${stages(e)}
  <div class="columns"><div><div class="section-head"><h2>智能协作</h2><span class="badge gray">6 个角色</span></div><div class="agent-list">${[['workflow','总控',labels[e.state]],['clipboard-list','策划',e.plan?'方案已生成 · 第 '+e.revision+' 版':'等待活动需求'],['megaphone','宣传',e.publicity?(e.publicity.approved?'宣传已确认':'文案待确认'):'等待策划确认'],['users','报名',e.registration_path?'累计 '+e.metrics.registration+' 人报名':'等待策划确认'],['radio','现场',e.state==='LIVE'?'现场执行中':'已签到 '+e.metrics.attendance+' 人'],['chart-no-axes-combined','复盘',e.review?'报告已生成':'等待活动数据']].map(([ico,name,status])=>`<div class="agent"><div class="agent-icon">${icon(ico)}</div><div><h3>${name}</h3><p>${esc(status)}</p></div></div>`).join('')}</div></div><div><div class="section-head"><h2>最近动态</h2><span class="small muted">${e.logs.length} 条记录</span></div>${logs(e.logs.slice(-4))}</div></div>`;
}
function logs(items) { return `<ul class="activity">${[...items].reverse().map(l=>`<li><p>${esc(l.message)}</p><time>${esc(l.agent)} · ${fmt(l.at)}</time></li>`).join('')}</ul>`; }
function planForm() {
  const b=event.brief;
  return `<form id="plan-form"><div class="form-grid">${field('name','活动名称 *','text',b.name,'required maxlength="100"')}${field('objective','活动目标','text',b.objective,'maxlength="500"')}${field('type','活动类型 *','text',b.type,'required placeholder="如：交流分享"')}${field('level','活动级别','text',b.level,'placeholder="如：校级"')}${field('format','活动形式 *','text',b.format,'required placeholder="如：线下分享与讨论"')}${field('audience','目标参与者 *','text',b.audience,'required')}${field('date','活动开始时间 *','datetime-local',b.date,'required')}${field('duration','活动时长（分钟） *','number',b.duration||120,'required min="30" max="720"')}${field('location','活动地点 *','text',b.location,'required')}${field('capacity','预计人数 *','number',b.capacity||100,'required min="1" max="100000"')}${field('budget','活动预算（元） *','number',b.budget??1000,'required min="0" step="0.01"')}${field('organizer','主办方','text',b.organizer,'maxlength="200"')}${field('owner','负责人','text',b.owner,'maxlength="100"')}<div class="field full"><label for="constraints">额外约束</label><textarea id="constraints" name="constraints" placeholder="嘉宾时间、场地限制、活动偏好……">${esc(b.constraints||'')}</textarea></div></div><div class="form-actions"><button class="primary" type="submit">${icon('sparkles')}${event.plan?'重新生成策划':'生成策划方案'}</button></div></form>`;
}
function chatBubble(m) {
  const qs=(m.questions||[]).map(q=>`<p>${esc(q)}</p>`).join('');
  const miss=m.missing_fields?.length?`<p class="small muted">待补充：${m.missing_fields.map(esc).join('、')}</p>`:'';
  return `<div class="chat-row ${m.role==='user'?'from-user':''}"><div class="chat-bubble"><p>${esc(m.content)}</p>${qs}${miss}</div></div>`;
}
function md(src) {
  const inline=s=>esc(s).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  let html='',list=false,table=null;
  const closeBlocks=()=>{if(list){html+='</ul>';list=false;}if(table){html+=`<div class="table-wrap"><table><thead><tr>${table[0].map(c=>`<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${table.slice(1).map(r=>`<tr>${r.map(c=>`<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;table=null;}};
  for(const raw of String(src).split('\n')){
    const line=raw.trim();
    if(!line){closeBlocks();continue;}
    if(line.startsWith('|')){
      const cells=line.split('|').slice(1,-1).map(c=>c.trim());
      if(cells.length&&cells.every(c=>/^:?-{2,}:?$/.test(c)))continue;
      if(list){html+='</ul>';list=false;}
      if(!table)table=[];
      table.push(cells);continue;
    }
    closeBlocks();
    const h=line.match(/^(#{1,3})\s+(.*)/);
    if(h){html+=`<h${h[1].length+2}>${inline(h[2])}</h${h[1].length+2}>`;continue;}
    const li=line.match(/^[-*]\s+(.*)/);
    if(li){html+=`${list?'':'<ul>'}<li>${inline(li[1])}</li>`;list=true;continue;}
    html+=`<p>${inline(line)}</p>`;
  }
  closeBlocks();
  return html;
}
const requiredFields=[['name','活动名称'],['type','活动类型'],['format','活动形式'],['audience','目标参与者'],['date','活动时间'],['location','活动地点'],['capacity','预计人数'],['budget','预算']];
function briefValue(b,k) {
  const v=b[k];
  if(v===undefined||v===null||String(v).trim()==='')return '';
  if(k==='date')return fmt(v);
  if(k==='capacity')return v+' 人';
  if(k==='budget')return '¥ '+Number(v).toLocaleString();
  return String(v);
}
function briefProgress(b) {
  const filled=requiredFields.filter(([k])=>briefValue(b,k)).length;
  return `<div class="brief-progress"><div class="brief-progress-head"><h3>已掌握的策划信息</h3><span class="small muted">${filled} / ${requiredFields.length}</span></div><div class="brief-fields">${requiredFields.map(([k,label])=>{const v=briefValue(b,k);return `<div class="brief-field ${v?'':'missing'}"><span class="brief-label">${label}</span><span class="brief-value">${v?esc(v):'待补充'}</span></div>`;}).join('')}</div></div>`;
}
function planDraft() {
  const e=event, msgs=e.planning_messages||[];
  const chips=[['补充时间与地点','计划下周五晚 7 点在学生活动中心举办，预计 100 人参加'],['补充形式与预算','以分享交流的形式进行，预算 1200 元，促进跨学院同学互动'],['补充嘉宾与规模','邀请 3 位已毕业的学长学姐做分享，规模 50 人左右，预算 500 元']];
  const welcome=`<div class="chat-welcome"><h2>为「${esc(e.brief.name)}」补充策划信息</h2><p>活动已创建。告诉我时间、地点、规模、预算等安排，我会逐步追问，信息齐全后我会生成完整方案。</p><div class="chips">${chips.map(([label,text])=>`<button class="chip" data-chat-example="${esc(text)}">${label}</button>`).join('')}</div></div>${briefProgress(e.brief)}`;
  const card=e.plan_md&&e.state==='WAITING_PLAN_CONFIRMATION'?`<div class="plan-card"><div class="plan-md">${md(e.plan_md)}</div><div class="plan-card-actions"><span class="small muted">确认无误后开始实施；如需调整，直接在下方告诉我。</span>${button('开始实施','confirm_plan',true,'check')}</div></div>`:'';
  const placeholder=msgs.length?'继续补充活动信息……':`例如：${e.brief.name}计划下周五晚 7 点在学生活动中心举办，预计 100 人，预算 1200 元`;
  const rulesEntry=mode==='rules'?`<div class="chat-rules-entry"><span class="small muted">未配置模型接口，可改用表单补充信息</span>${button('填写需求表单','edit-brief',false,'clipboard-list')}</div>`:'';
  return `<div class="chat-wrap"><div class="chat-scroll">${msgs.length?msgs.map(chatBubble).join(''):welcome}${card}</div>${rulesEntry}<div class="chat-compose"><form id="planning-chat-form"><label class="sr-only" for="planning-message">用一段话描述活动</label><textarea id="planning-message" name="message" required maxlength="6000" placeholder="${esc(placeholder)}"></textarea><button class="primary chat-send" type="submit" aria-label="发送">${icon('send')}</button></form></div></div>`;
}
function planView() {
  const e=event,p=e.plan;
  if (!p || e.state==='WAITING_PLAN_CONFIRMATION') return planDraft();
  return `<div class="section-head"><h2>活动方案 <span class="small muted">版本 ${e.revision}</span></h2>${badge(e.state)}</div><div class="prose">${esc(p.summary)}</div>
    <div class="columns section"><div><h2>活动流程安排</h2>${timeline(p.timeline)}</div><div><h2>筹备进度安排</h2><ul class="timeline">${p.preparation.map(t=>`<li><time>${t.day}</time><span>${esc(t.task)}</span></li>`).join('')}</ul></div></div>
    <div class="columns section"><div><div class="section-head"><h2>预算分配</h2><span class="small muted">总计 ¥ ${e.brief.budget.toLocaleString()}</span></div><table><thead><tr><th>预算项目</th><th>金额</th></tr></thead><tbody>${p.budget.map(b=>`<tr><td>${esc(b.item)}</td><td>¥ ${b.amount.toLocaleString()}</td></tr>`).join('')}</tbody></table><div class="section"><h2>物资需求</h2><ul class="check-list">${p.materials.map(m=>`<li>${esc(m)}</li>`).join('')}</ul></div></div><div><h2>人员分工</h2><ul class="timeline">${p.roles.map(r=>`<li><time>${esc(r.role)}</time><span>${esc(r.task)}</span></li>`).join('')}</ul><div class="section"><h2>风险预案</h2><ul class="check-list">${p.risks.map(r=>`<li>${esc(r)}</li>`).join('')}</ul></div></div></div><div class="section"><h2>活动成功指标</h2>${comparison(p.targets)}</div>`;
}
function timeline(items) { return `<ul class="timeline">${items.map(t=>`<li><time>${t.time.slice(11,16)}</time><span>${esc(t.title)}<small>${day(t.time)} · ${esc(t.owner)}</small></span></li>`).join('')}</ul>`; }
function comparison(targets, rows) {
  const names={registration:'报名人数',attendance:'到场人数',attendance_rate:'到场率 (%)',feedback:'反馈人数',satisfaction:'满意度 (5 分)'};
  return `<div class="table-wrap"><table><thead><tr><th>核心指标</th><th>目标</th>${rows?'<th>实际</th><th>结果</th>':''}</tr></thead><tbody>${Object.entries(targets).map(([k,v])=>{const r=rows?.find(x=>x.key===k);return `<tr><td>${names[k]}</td><td>${v}</td>${r?`<td><strong>${r.actual??'暂无数据'}</strong></td><td><span class="badge ${r.met===true?'':r.met===false?'amber':'gray'}">${r.met===true?'已达成':r.met===false?'未达成':'待评估'}</span></td>`:''}</tr>`;}).join('')}</tbody></table></div>`;
}
function publicityView(recap=false) {
  const e=event,p=recap?e.recap:e.publicity;
  if(!p) return empty('宣传内容尚未生成',e.state==='PLAN_CONFIRMED'?'策划已确认，报名入口已就绪。':'确认策划方案后进入宣传准备。',e.state==='PLAN_CONFIRMED'?button('生成宣传内容','publicity',true,'sparkles'):'');
  const editable=e.state===(recap?'WAITING_RECAP_CONFIRMATION':'WAITING_PUBLICITY_CONFIRMATION');
  return `${editable?'<div class="inline-note warning">文案待确认。本站不直接连接微信公众号或社交平台，确认后可复制文案与下载海报。</div>':'<div class="inline-note">文案已确认，可复制到外部渠道发布。</div>'}<div class="section-head"><h2>${recap?'活动总结宣传':'活动宣传素材'}</h2><div class="actions">${editable?button('修改文案',recap?'edit-recap':'edit-copy',false,'pencil')+button(recap?'确认总结并归档':'确认宣传并开放报名',recap?'confirm_recap':'confirm_publicity',true,'check'):''}</div></div><div class="split"><div><div class="tabbar"><button class="${pubTab==='article'?'active':''}" data-tab="article">微信公众号</button><button class="${pubTab==='group'?'active':''}" data-tab="group">微信群 / 朋友圈</button></div><div class="prose">${esc(p[pubTab]).replaceAll(esc(e.registration_path),esc(link()))}</div><div class="form-actions">${button('复制文案',recap?'copy-recap':'copy-content',false,'copy')}</div><div class="section"><h2>宣传节奏</h2><ul class="timeline">${p.schedule.map((s,i)=>`<li><time>0${i+1}</time><span>${esc(s)}</span></li>`).join('')}</ul></div></div><div><div class="poster"><div class="poster-photo"></div><span class="eyebrow">CAMPUS TOGETHER / ${recap?'活动回顾':'校园活动'}</span><h2>${esc(e.brief.name)}</h2><p>${recap?`${e.metrics.registration} 人报名 · ${e.metrics.attendance} 人到场` :esc(e.brief.objective)}</p><p>${fmt(e.brief.date)}<br>${esc(e.brief.location)}<br>${esc(e.brief.organizer)}</p><canvas id="qr" aria-label="活动入口二维码"></canvas><span class="small">${recap?'活动参与者入口':'扫码报名 · 期待相遇'}</span></div><div class="form-actions">${button('下载海报',recap?'poster-recap':'poster',false,'download')}</div></div></div>`;
}
function registrationView() {
  if (!event.registration_path) return empty('报名入口尚未创建','确认策划后，由系统自动创建入口。');
  return `<div class="link-box">${icon('link')}<a target="_blank" rel="noopener" href="${esc(link())}">${esc(link())}</a>${button('复制链接','copy-link',false,'copy')}${button('二维码','show-qr',false,'qr-code')}</div>${event.state==='PLAN_CONFIRMED'||event.state==='WAITING_PUBLICITY_CONFIRMATION'?'<div class="inline-note warning">报名入口已创建，宣传确认后开放提交。</div>':''}${metricCards(event)}<div class="section-head"><h2>报名人员 <span class="small muted">${event.registrations.length} 人</span></h2><div class="actions"><input class="search" id="search" aria-label="搜索报名人员" placeholder="搜索姓名、邮箱、学院">${button('导出名单','export',false,'download')}${event.state==='REGISTRATION_OPEN'?button('开启现场签到','start',true,'radio'):''}</div></div><div id="registration-table">${registrationTable(event.registrations)}</div><div class="columns section"><div><h2>近 7 天报名趋势</h2>${trend()}</div><div><h2>学院分布</h2>${distribution()}</div></div>`;
}
function registrationTable(rows) {
  return rows.length?`<div class="table-wrap"><table><thead><tr><th>参与者</th><th>学院 / 年级</th><th>邮箱</th><th>需求与提问</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.college)}<br><span class="small muted">${esc(r.grade)}</span></td><td>${esc(r.email)}</td><td class="wrap">${esc(r.needs||'无特殊需求')}${r.question?`<br><span class="muted">问：${esc(r.question)}</span>`:''}${r.answer?`<br>答：${esc(r.answer)}`:''}</td><td><span class="badge ${r.checked_at?'':'gray'}">${r.checked_at?(r.late?'迟到已签到':'已签到'):['FEEDBACK','WAITING_REVIEW_CONFIRMATION','WAITING_RECAP_CONFIRMATION','COMPLETED'].includes(event.state)?'未到':'已报名'}</span></td><td>${event.state==='LIVE'&&!r.checked_at?`<button class="icon-btn" title="为 ${esc(r.name)} 签到" data-checkin="${r.id}">${icon('scan-line')}</button>`:''}${r.question&&['REGISTRATION_OPEN','LIVE','FEEDBACK'].includes(event.state)?`<button class="icon-btn" title="回复提问" data-answer="${r.id}">${icon('message-square')}</button>`:''}</td></tr>`).join('')}</tbody></table></div>`:empty('暂无报名人员','报名成功后，参与者名单会显示在这里。');
}
function trend() {
  const days=Array.from({length:7},(_,i)=>{const d=new Date();d.setDate(d.getDate()-6+i);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;});
  const counts=days.map(d=>event.registrations.filter(r=>r.at.startsWith(d)).length),max=Math.max(1,...counts);
  return `<div class="trend">${counts.map(c=>`<div class="trend-col"><span>${c}</span><div class="bar" style="height:${c/max*85}px"></div></div>`).join('')}</div><div class="trend-labels">${days.map(d=>`<span>${d.slice(5)}</span>`).join('')}</div>`;
}
function distribution() {
  const map={};event.registrations.forEach(r=>map[r.college]=(map[r.college]||0)+1);
  return Object.entries(map).length?`<ul class="timeline">${Object.entries(map).sort((a,b)=>b[1]-a[1]).map(([name,n])=>`<li><time>${n} 人</time><span>${esc(name)}</span></li>`).join('')}</ul>`:'<p class="muted small" style="margin-top:20px">暂无报名数据</p>';
}
function onsiteView() {
  const e=event;
  if(!e.plan) return empty('现场尚未准备','请先完成策划与宣传确认。');
  const live=e.state==='LIVE',p=e.pending_adjustment;
  const current=live?[...e.plan.timeline].reverse().find(t=>new Date(t.time)<=new Date()):null;
  const next=live?e.plan.timeline.find(t=>new Date(t.time)>new Date()):null;
  return `<div class="section-head"><h2>${live?'活动现场':'现场执行记录'}</h2><div class="actions">${e.state==='REGISTRATION_OPEN'?button('开启现场签到','start',true,'radio'):''}${live?button('结束活动，收集反馈','finish',true,'flag'):''}</div></div>${metricCards(e)}${live?`<div class="inline-note">当前环节：${esc(current?.title||'活动开始前准备')} · ${next?`下一环节：${esc(next.title)}，${Math.max(0,Math.ceil((new Date(next.time)-new Date())/60000))} 分钟后开始`:'时间线已全部结束'}<span class="small muted">（按设备当前时间计算）</span></div>`:''}${p?`<div class="inline-note warning"><strong>流程调整待确认</strong><p>${esc(p.reason)} · 从“${esc(e.plan.timeline.find(t=>t.id===p.item_id)?.title)}”起顺延 ${p.minutes} 分钟</p><div class="actions">${button('采纳调整','approve_adjustment',true,'check')}${button('暂不调整','reject_adjustment',false,'x')}</div></div>`:''}<div class="columns"><div><div class="section-head"><h2>执行 Timeline</h2>${live&&!p?button('提出调整','adjust-dialog',false,'clock-3'):''}</div>${timeline(e.plan.timeline)}</div><div><div class="section-head"><h2>参与者反馈</h2><span class="small muted">${e.feedback_pool.length} 条</span></div>${feedbackList()}</div></div><div class="section"><div class="section-head"><h2>现场签到</h2>${button('刷新数据','refresh',false,'refresh-cw')}</div>${registrationTable(e.registrations)}</div><div class="section"><h2>现场调整记录</h2><ul class="timeline">${e.adjustments.map(a=>`<li><time>+${a.minutes} 分钟</time><span>${esc(a.reason)}<small>${fmt(a.at)} · 已批准</small></span></li>`).join('')||'<li><span class="muted">暂无流程调整</span></li>'}</ul></div>`;
}
function feedbackList() { return event.feedback_pool.length?event.feedback_pool.map(f=>`<div class="feedback-item"><span class="badge gray">${f.phase==='live'?'现场反馈':'活动后反馈'}</span> <span class="rating">${f.rating?'★'.repeat(f.rating):'未评分'}</span><p>${esc(f.comment)}</p><span class="small muted">${fmt(f.at)}</span></div>`).join(''):'<p class="muted small">暂无反馈</p>'; }
function reviewView() {
  const e=event,r=e.review;
  if(!r) return empty('让每次活动都有下一次的进步',e.state==='FEEDBACK'?`当前已收到 ${e.metrics.feedback} 位参与者的反馈，可生成复盘报告。`:'活动结束后，根据报名、到场和反馈数据生成复盘。',e.state==='FEEDBACK'?button('生成活动复盘','review',true,'sparkles'):'');
  return `<div class="section-head"><h2>活动复盘报告</h2><div class="actions">${e.state==='WAITING_REVIEW_CONFIRMATION'?button('重新生成','review',false,'refresh-cw')+button('确认复盘，生成总结','confirm_review',true,'check'):''}${button('导出报告','report-download',false,'download')}</div></div><p class="prose">${esc(r.summary)}</p><div class="section"><div class="section-head"><h2>目标 vs 实际</h2><span class="small muted">评分样本 ${r.metrics.rating_count} 份</span></div>${comparison(e.plan.targets,r.comparison)}</div><div class="columns section"><div><h2>下一次改进建议</h2><ul class="check-list">${r.suggestions.map(s=>`<li>${esc(s)}</li>`).join('')}</ul><div class="section"><h2>宣传效果</h2><p class="muted small">当前仅记录报名来源，未接入外部平台曝光和阅读数据。</p>${sourceTable()}</div></div><div><h2>参与者评价</h2>${feedbackList()}</div></div><div class="section"><h2>执行与调整记录</h2><div class="spacer"></div>${logs(e.logs.filter(l=>['现场','总控'].includes(l.agent)).slice(-8))}</div>${e.recap?`<div class="section">${publicityView(true)}</div>`:''}`;
}
function sourceTable(){const map={};event.registrations.forEach(r=>map[r.source]=(map[r.source]||0)+1);return `<ul class="timeline">${Object.entries(map).map(([s,n])=>`<li><time>${n} 人</time><span>${esc(s)}</span></li>`).join('')}</ul>`;}
function agentPanel() {
  const role={plan:'planning',publicity:'publicity',registration:'registration',onsite:'onsite',review:'review'}[page];
  if(!role)return '';
  const setting=agentSettings[role]||{}, e=event;
  let body='';
  if(setting.error)body+=`<div class="inline-note warning">${esc(setting.error)}</div>`;
  if(role==='publicity'&&['PLAN_CONFIRMED','WAITING_PUBLICITY_CONFIRMATION'].includes(e.state)&&e.publicity)body+=`<div class="actions">${button('智能修改文案','revise-publicity',false,'sparkles')}</div>`;
  if(role==='registration'&&['REGISTRATION_OPEN','LIVE','FEEDBACK'].includes(e.state)){
    body+=`<div class="actions">${button('分析报名情况','analyze_registration',false,'sparkles')}</div>`;
    const a=e.registration_analysis;if(a)body+=`<p class="prose analysis-summary">${esc(a.summary)}</p><ul class="check-list">${a.suggestions.map(s=>`<li>${esc(s)}</li>`).join('')}</ul>${a.needs_attention.length?`<p class="small muted">待处理：${a.needs_attention.map(esc).join('；')}</p>`:''}`;
  }
  if(role==='onsite'){
    if(e.state==='LIVE'&&!e.pending_adjustment)body+=`<form id="onsite-agent-form"><div class="field"><label for="onsite-message">现场情况</label><textarea id="onsite-message" name="message" maxlength="6000" placeholder="补充工作人员观察到的情况，例如嘉宾预计晚到 20 分钟"></textarea></div><div class="form-actions"><button class="primary" type="submit">${icon('sparkles')}分析现场并提出建议</button></div></form>`;
    const a=e.onsite_analysis;if(a)body+=`<p class="prose analysis-summary">${esc(a.summary)}</p>${a.issues.map(i=>`<div class="feedback-item"><strong>${esc(i.topic)}</strong><p>${esc(i.suggestion)}</p><p class="small muted">依据：${i.evidence_ids.map(esc).join('、')||'工作人员情况 / 时间线'}</p></div>`).join('')}`;
  }
  if(role==='review'&&e.review?.findings?.length)body+=e.review.findings.map(f=>`<div class="feedback-item"><p>${esc(f.observation)}</p>${f.hypothesis?`<p class="muted">可能原因：${esc(f.hypothesis)}</p>`:''}<p class="small muted">依据：${f.evidence_ids.map(esc).join('、')}</p></div>`).join('');
  if(role==='review'&&e.state==='WAITING_RECAP_CONFIRMATION')body+=button('智能修改总结','revise-recap',false,'sparkles');
  return body?`<section class="agent-workspace">${body}</section>`:'';
}
function answerModal(r){
  const draft=r.answer_draft;
  modal(`<h2>回复参与者提问</h2><p>${esc(r.question)}</p>${draft?`<div class="inline-note ${draft.needs_human?'warning':''}"><strong>${draft.needs_human?'需要负责人补充确认':'答复草稿'}</strong><p>${esc(draft.reason)}</p><p class="small">依据：${draft.evidence.map(esc).join('；')||'暂无明确依据'}</p></div>`:''}<form id="answer-form" data-ticket="${r.id}"><div class="field"><label for="answer">答复</label><textarea id="answer" name="answer" required maxlength="5000">${esc(draft?.answer||r.answer||'')}</textarea></div><div class="form-actions"><button type="button" data-ai-answer="${r.id}">${icon('sparkles')}生成答复草稿</button><button type="submit" class="primary">确认并保存答复</button></div></form>`);
}
function renderHome() {
  const cards=events.map(e=>`<button class="project-card" data-open="${e.id}"><div class="card-head">${badge(e.state)}<span class="small muted">${esc(e.brief.owner||'')}</span></div><h3>${esc(e.brief.name)}</h3><div class="event-meta"><span>${icon('calendar-days')}${day(e.brief.date)}</span><span>${icon('map-pin')}${esc(e.brief.location||'地点待确定')}</span></div><div class="card-stats"><span>${icon('users')}${e.metrics.registration} 人报名</span><span>${icon('scan-line')}${e.metrics.attendance} 人签到</span><span>${icon('message-square')}${e.metrics.feedback} 条反馈</span></div><div class="card-foot"><span>下一步：${esc(nextTasks[e.state][0])}</span>${icon('arrow-up-right')}</div></button>`).join('');
  const last=events.find(e=>e.id===sessionStorage.getItem('campus-event'));
  $('#app').innerHTML=`<main class="home-shell"><header class="topbar"><div class="breadcrumb"><strong>校园共创</strong></div><div class="top-actions"><span class="small muted">${events.length} 场活动</span></div></header><div class="content"><div class="heading"><div><h1>项目列表</h1><p>点击项目进入活动总览，或创建新的活动。</p></div><div class="actions">${last?button('返回总览','back-overview',false,'layout-dashboard'):''}${events.length?button('新建活动','new',true,'plus'):''}</div></div>${events.length?`<div class="project-grid">${cards}</div>`:empty('还没有活动项目','创建第一个活动，开始从策划到归档的全流程管理。',button('新建活动','new',true,'plus'))}</div></main>`;
  refresh();
}
function openProject(id) { const found=events.find(e=>e.id===id); if(!found) return; event=found; view='workspace'; page='overview'; sessionStorage.setItem('campus-event',id); sessionStorage.setItem('campus-view','workspace'); render(); }
function goHome() { view='home'; sessionStorage.setItem('campus-view','home'); render(); }
function render() {
  if(publicId) return renderPublic();
  if(!key) return login();
  if(!event || view==='home') return renderHome();
  const selected=pages.find(p=>p[0]===page);
  $('#app').innerHTML=`<div class="shell"><aside class="sidebar"><div class="brand"><span class="brand-mark">${icon('sprout')}</span>校园共创</div><div class="sidebar-label">活动管理</div><nav class="nav">${pages.map(([id,ico,title])=>`<button data-page="${id}" class="${page===id?'active':''}">${icon(ico)}${title}${id==='registration'&&event?`<span class="nav-count">${event.metrics.registration}</span>`:''}</button>`).join('')}</nav></aside><main class="main"><header class="topbar"><div class="top-actions"><button class="icon-btn" data-action="go-home" title="返回项目列表">${icon('arrow-left')}</button>${events.length?`<select aria-label="切换活动" id="event-select">${events.map(e=>`<option value="${e.id}" ${e.id===event?.id?'selected':''}>${esc(e.brief.name)}</option>`).join('')}</select>`:''}<button class="icon-btn" data-action="refresh" title="刷新活动数据">${icon('refresh-cw')}</button></div></header><div class="content"><div class="heading"><div><h1>${selected[2]}</h1><p>${page==='overview'?'策划、宣传、报名、现场与复盘，一站式管理活动全流程。':esc(event?.brief.name||'')}</p></div><div class="actions">${event?.registration_path&&page==='overview'?`<a href="${esc(link())}" target="_blank" rel="noopener"><button>${icon('external-link')}参与者入口</button></a>`:''}</div></div>${event?({overview,plan:planView,publicity:publicityView,registration:registrationView,onsite:onsiteView,review:reviewView}[page])():empty('你的下一场活动，从这里开始','创建活动，填写需求，开始筹备。',button('创建第一场活动','new',true,'plus'))}</div></main></div>`;
  if(event)document.querySelector('.heading').insertAdjacentHTML('afterend',agentPanel());
  const scroller=$('.chat-scroll'); if(scroller) scroller.scrollTop=scroller.scrollHeight;
  refresh();
}
function login() { $('#app').innerHTML=`<div class="login panel"><div class="brand"><span class="brand-mark">${icon('sprout')}</span>校园共创</div><h1>负责人登录</h1><form id="login-form">${field('key','负责人访问密钥','password','','required autocomplete="current-password"')}<div class="form-actions"><button class="primary" type="submit">登录${icon('arrow-right')}</button></div></form></div>`;refresh(); }
async function loadEvents(){
  const result=await Promise.all([api('/api/events'),api('/api/agents')]);events=result[0];agentSettings=result[1];
  if(!booted){booted=true;const saved=sessionStorage.getItem('campus-event');event=events.find(e=>e.id===saved)||null;view=event&&sessionStorage.getItem('campus-view')!=='home'?'workspace':'home';}
  else{event=events.find(e=>e.id===event?.id)||null;if(!event&&view==='workspace')view='home';}
  render();
}
let booted=false;
async function act(action,data={}){if(['planning_chat','plan','plan_from_brief','publicity','regenerate_recap','answer_question','analyze_registration','analyze_onsite','review','confirm_review'].includes(action))toast('正在处理，请稍候…');event=await api(`/api/events/${event.id}/actions/${action}`,{...data,expected_version:event.version});events=events.map(e=>e.id===event.id?event:e);render();toast('已完成：'+labels[event.state]);}
function modal(html) { $('#modal').innerHTML=html;$('#modal').showModal();refresh(); }
async function streamPlanningChat(data) {
  const message = String(data.message || '').trim();
  if (!message || !event) return;
  const e = event;
  e.planning_messages = [...(e.planning_messages || []), {role: 'user', content: message}];
  render();
  let pendingText = '', gotDelta = false, finished = false, errorMessage = '';
  const appendPending = () => {
    const scroll = $('.chat-scroll'); if (!scroll) return;
    scroll.querySelector('.chat-row.pending')?.remove();
    if (pendingText) scroll.insertAdjacentHTML('beforeend', `<div class="chat-row pending"><div class="chat-bubble"><p>${esc(pendingText)}</p></div></div>`);
    scroll.scrollTop = scroll.scrollHeight;
  };
  const handleFrame = (frame) => {
    const lines = frame.split('\n');
    let name = '', payload = null;
    for (const line of lines) {
      if (line.startsWith('event: ')) name = line.slice(7).trim();
      else if (line.startsWith('data: ')) { try { payload = JSON.parse(line.slice(6)); } catch { payload = null; } }
    }
    if (!payload) return;
    if (name === 'delta') { gotDelta = true; pendingText += payload.text || ''; appendPending(); }
    else if (name === 'tool') {
      pendingText = '';
      const scroll = $('.chat-scroll');
      if (scroll) {
        scroll.querySelector('.chat-row.pending')?.remove();
        const label = payload.name === 'generate_plan' ? '正在生成活动计划…' : '正在读取活动信息…';
        scroll.insertAdjacentHTML('beforeend', `<div class="chat-row pending"><div class="chat-bubble tool-status">${icon('loader-circle')}<span>${label}</span></div></div>`);
        scroll.scrollTop = scroll.scrollHeight;
        refresh();
      }
    }
    else if (name === 'message') {
      if (!gotDelta) { e.planning_messages = [...(e.planning_messages || []), {role: 'assistant', content: payload.reply, questions: payload.questions || [], missing_fields: payload.missing_fields || []}]; render(); }
    } else if (name === 'done') { event = payload; events = events.map(x => x.id === payload.id ? payload : x); finished = true; render(); }
    else if (name === 'error') errorMessage = payload.message || '生成失败';
  };
  try {
    const response = await fetch('/api/events/' + e.id + '/chat_stream', {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + key}, body: JSON.stringify({message, expected_version: e.version})});
    if (!response.ok || !response.body) throw new Error((await response.json().catch(() => ({}))).error || '流式接口不可用');
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const frames = buffer.split('\n\n');
      buffer = frames.pop();
      frames.forEach(handleFrame);
    }
    if (buffer.trim()) handleFrame(buffer);
    if (errorMessage) throw new Error(errorMessage);
    if (!finished) throw new Error('流式响应中断');
    toast('已完成：' + labels[event.state]);
  } catch (err) {
    toast(err.message, true);
    await act('planning_chat', data);
  }
}
function confirmAction(action,title,description) { modal(`<h2>${title}</h2><p>${description}</p><div class="form-actions">${button('取消','close',false,'x')}<button class="primary" data-confirm="${action}">${icon('check')}确认执行</button></div>`); }
async function drawQR(){try{await window.QRCode.toCanvas($('#qr'),link(),{width:180,margin:2,color:{dark:'#244830',light:'#ffffff'}});}catch(e){toast('二维码生成失败',true);}}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function poster(recap=false){
  const c=document.createElement('canvas');c.width=900;c.height=1260;const ctx=c.getContext('2d');ctx.fillStyle='#dce8d7';ctx.fillRect(0,0,900,1260);
  const image=new Image();image.src='/static/campus.jpg';await image.decode();ctx.drawImage(image,0,0,image.width,image.height,0,0,900,340);
  ctx.fillStyle='#244830';ctx.font='22px sans-serif';ctx.fillText('CAMPUS TOGETHER / '+(recap?'活动回顾':'校园活动'),64,405);
  let y=480;function wrap(s,font,line,maxY){ctx.font=font;let row='';for(const char of s){if(ctx.measureText(row+char).width>760){ctx.fillText(row,64,y);y+=line;row=char;if(y>maxY)return;}else row+=char;}if(y<=maxY){ctx.fillText(row,64,y);y+=line;}}
  wrap(event.brief.name,'bold 48px sans-serif',66,650);y+=10;
  wrap(recap?`${event.metrics.registration} 人报名 · ${event.metrics.attendance} 人到场`:event.brief.objective,'26px sans-serif',42,790);
  y=Math.max(y+20,850);wrap(fmt(event.brief.date),'24px sans-serif',36,950);wrap(event.brief.location,'24px sans-serif',36,950);wrap(event.brief.organizer,'24px sans-serif',36,1000);
  const qr=document.createElement('canvas');await window.QRCode.toCanvas(qr,link(),{width:170,margin:2});ctx.drawImage(qr,64,1030);ctx.font='22px sans-serif';ctx.fillText(recap?'活动参与者入口':'扫码报名 · 期待相遇',265,1110);
  c.toBlob(b=>download(b,'活动海报.png'));
}

document.addEventListener('click',ev=>{
  const target=ev.target.closest('button');if(!target||target.disabled)return;
  if(target.dataset.open){openProject(target.dataset.open);return;}
  if(target.dataset.page){page=target.dataset.page;render();return;}
  if(target.dataset.tab){pubTab=target.dataset.tab;render();return;}
  if(target.dataset.chatExample){const t=$('#planning-message');if(t){t.value=target.dataset.chatExample;t.focus();}return;}
  if(target.dataset.publicTab){renderPublic(target.dataset.publicTab);return;}
  if(target.dataset.checkin){run(()=>act('checkin',{ticket:target.dataset.checkin}));return;}
  if(target.dataset.answer){answerModal(event.registrations.find(r=>r.id===target.dataset.answer));return;}
  if(target.dataset.aiAnswer){run(async()=>{await act('answer_question',{ticket:target.dataset.aiAnswer});answerModal(event.registrations.find(r=>r.id===target.dataset.aiAnswer));});return;}
  if(target.dataset.confirm){$('#modal').close();run(()=>act(target.dataset.confirm));return;}
  const action=target.dataset.action;if(!action)return;ev.preventDefault();
  if(action==='close')return $('#modal').close();
  if(action==='go-home')return goHome();
  if(action==='back-overview')return openProject(sessionStorage.getItem('campus-event'));
  if(action==='new')return modal(`<h2>新建校园活动</h2><form id="new-form">${field('name','活动名称','text','','required placeholder="为这次相聚起个名字" maxlength="100"')}<div class="form-actions">${button('取消','close',false,'x')}<button type="submit" class="primary">${icon('plus')}创建活动</button></div></form>`);
  if(action==='revise-publicity'||action==='revise-recap')return modal(`<h2>修改${action==='revise-recap'?'活动总结':'宣传内容'}</h2><form id="agent-revise-form" data-kind="${action==='revise-recap'?'regenerate_recap':'publicity'}"><div class="field"><label for="agent-instruction">修改要求</label><textarea id="agent-instruction" name="instruction" required maxlength="6000" placeholder="例如：缩短群聊文案，突出适合零基础同学"></textarea></div><div class="form-actions"><button type="submit" class="primary">生成新草稿</button></div></form>`);
  if(action==='edit-brief')return modal(`<h2>填写活动需求</h2>${planForm()}`);
  if(action==='edit-copy'||action==='edit-recap'){const p=action==='edit-copy'?event.publicity:event.recap;return modal(`<h2>编辑宣传文案</h2><form id="copy-form" data-recap="${action==='edit-recap'}"><div class="field"><label>微信公众号</label><textarea name="article" rows="8" required>${esc(p.article)}</textarea></div><div class="spacer"></div><div class="field"><label>微信群 / 朋友圈</label><textarea name="group" rows="5" required>${esc(p.group)}</textarea></div><div class="form-actions"><button class="primary" type="submit">保存文案</button></div></form>`);}
  if(action==='adjust-dialog')return modal(`<h2>提出现场流程调整</h2><form id="adjust-form"><div class="field"><label>调整起点</label><select name="item_id">${event.plan.timeline.map(t=>`<option value="${t.id}">${t.time.slice(11,16)} ${esc(t.title)}</option>`).join('')}</select></div><div class="spacer"></div>${field('minutes','该环节及后续环节顺延（分钟）','number',10,'required min="1" max="180"')}<div class="spacer"></div><div class="field"><label>调整原因</label><textarea name="reason" required placeholder="如：嘉宾预计晚到 20 分钟"></textarea></div><div class="form-actions"><button class="primary" type="submit">提交待确认建议</button></div></form>`);
  const confirmations={confirm_plan:['开始实施','确认后将创建报名入口，进入宣传准备阶段；当前方案将保留快照。'],confirm_publicity:['确认宣传并开放报名','本站报名入口将立即开放。外部渠道的文案和海报需手动发布。'],start:['开启现场签到','将关闭新报名并开放参与者签到。'],finish:['结束现场活动','将关闭签到，继续收集参与者的活动后反馈。'],confirm_review:['确认复盘结果','将使用当前复盘数据生成活动总结宣传稿。'],confirm_recap:['确认总结并归档','活动将标记为已归档。总结文案需手动发布到外部渠道。'],approve_adjustment:['确认调整正式时间线','正式执行时间线将更新，并保存本次修改记录。']};
  if(confirmations[action])return confirmAction(action,...confirmations[action]);
  run(async()=>{
    if(action==='refresh'){if(publicId){await loadPublic();}else await loadEvents();toast('数据已更新');}
    else if(action==='copy-link'){await navigator.clipboard.writeText(link());toast('报名链接已复制');}
    else if(action==='copy-content'||action==='copy-recap'){await navigator.clipboard.writeText((action==='copy-recap'?event.recap:event.publicity)[pubTab].replaceAll(event.registration_path,link()));toast('文案已复制');}
    else if(action==='poster'||action==='poster-recap')await poster(action==='poster-recap');
    else if(action==='show-qr'){modal(`<h2>活动报名二维码</h2><canvas id="modal-qr"></canvas><p class="small muted">${esc(link())}</p><div class="form-actions">${button('关闭','close',false,'x')}</div>`);await window.QRCode.toCanvas($('#modal-qr'),link(),{width:240,margin:2});}
    else if(action==='export'){const response=await fetch(`/api/events/${event.id}/export`,{headers:{Authorization:'Bearer '+key}});if(!response.ok)throw new Error('导出失败');download(await response.blob(),'报名名单.csv');}
    else if(action==='report-download'){const r=event.review;const report=`# ${event.brief.name} · 活动复盘\n\n${r.summary}\n\n## 目标与实际\n\n${r.comparison.map(x=>`${x.key}: 目标 ${x.target}，实际 ${x.actual??'暂无数据'}`).join('\n')}\n\n## 改进建议\n\n${r.suggestions.join('\n\n')}\n\n## 现场调整\n\n${event.adjustments.map(a=>`${a.at} ${a.reason}，顺延 ${a.minutes} 分钟`).join('\n')||'无'}\n`;download(new Blob([report],{type:'text/markdown;charset=utf-8'}),'活动复盘.md');}
    else if(action==='self-checkin'){await api(`/api/public/${publicId}/checkin`,{ticket:ticket()});await loadPublic('ticket');toast('签到成功');}
    else await act(action);
  });
});
document.addEventListener('submit',ev=>{
  ev.preventDefault();const form=ev.target,data=formData(form);
  run(async()=>{
    if(form.id==='login-form'){key=data.key.trim();await loadEvents();sessionStorage.setItem('campus-key',key);}
    if(form.id==='new-form'){event=await api('/api/events',data);events.unshift(event);view='workspace';page='overview';sessionStorage.setItem('campus-event',event.id);sessionStorage.setItem('campus-view','workspace');$('#modal').close();render();toast('活动已创建');}
    if(form.id==='plan-form'){await act('plan',data);$('#modal').close();}
    if(form.id==='planning-chat-form')await streamPlanningChat(data);
    if(form.id==='onsite-agent-form')await act('analyze_onsite',data);
    if(form.id==='agent-revise-form'){await act(form.dataset.kind,data);$('#modal').close();}
    if(form.id==='copy-form'){await act(form.dataset.recap==='true'?'edit_recap':'edit_publicity',data);$('#modal').close();}
    if(form.id==='adjust-form'){await act('adjust',data);$('#modal').close();}
    if(form.id==='answer-form'){await act('answer',{...data,ticket:form.dataset.ticket});$('#modal').close();}
    if(form.id==='register-form'){const r=await api(`/api/public/${publicId}/register`,data);localStorage.setItem('ticket-'+publicId,r.ticket);await loadPublic('ticket');toast('报名成功，请保管报名凭证');}
    if(form.id==='ticket-form'){await api(`/api/public/${publicId}/ticket`,data);localStorage.setItem('ticket-'+publicId,data.ticket);await loadPublic('ticket');}
    if(form.id==='feedback-form'){await api(`/api/public/${publicId}/feedback`,{...data,ticket:ticket()});toast('反馈已保存，感谢参与');}
  });
});
document.addEventListener('input',ev=>{if(ev.target.id==='search'){const q=ev.target.value.toLowerCase();$('#registration-table').innerHTML=registrationTable(event.registrations.filter(r=>[r.name,r.email,r.college].some(v=>v.toLowerCase().includes(q))));refresh();}if(ev.target.id==='planning-message'){ev.target.style.height='auto';ev.target.style.height=Math.min(ev.target.scrollHeight,200)+'px';}});
document.addEventListener('keydown',ev=>{if(ev.key==='Enter'&&!ev.shiftKey&&ev.target.id==='planning-message'){ev.preventDefault();ev.target.form.requestSubmit();}});
document.addEventListener('change',ev=>{if(ev.target.id==='event-select'){event=events.find(e=>e.id===ev.target.value);if(event)sessionStorage.setItem('campus-event',event.id);render();}});
$('#modal').addEventListener('close',()=>{if(!$('#modal').open)$('#modal').innerHTML='';});

function ticket(){return localStorage.getItem('ticket-'+publicId)||'';}
let ticketInfo=null,publicTab='register';
async function loadPublic(tab){publicData=await api('/api/public/'+publicId);ticketInfo=null;if(ticket()){try{ticketInfo=await api(`/api/public/${publicId}/ticket`,{ticket:ticket()});}catch{localStorage.removeItem('ticket-'+publicId);}}renderPublic(tab||(ticketInfo?'ticket':'register'));}
function renderPublic(tab){
  if(tab)publicTab=tab;
  if(!publicData)return;
  const e=publicData,b=e.brief;
  let body='';
  if(publicTab==='register'){
    body=ticketInfo?`<div class="ticket"><h2>你已成功报名</h2><p>${esc(ticketInfo.name)}，期待与你相遇。</p><button data-public-tab="ticket">查看报名凭证${icon('arrow-right')}</button></div>`:e.state!=='REGISTRATION_OPEN'?empty('当前未开放报名',labels[e.state]):`<div class="section-head"><h2>活动报名</h2><span class="badge">剩余 ${e.remaining} 个名额</span></div><p class="muted small">报名信息仅供活动负责人组织活动使用。</p><form id="register-form"><div class="form-grid">${field('name','姓名 *','text','','required maxlength="80"')}${field('email','邮箱 *','email','','required')}${field('college','学院 *','text','','required')}${field('grade','年级','text','','placeholder="如：大二"')}<div class="field full"><label>特殊需求</label><textarea name="needs" maxlength="1000" placeholder="无障碍、饮食或其他参与需求"></textarea></div><div class="field full"><label>想提前了解什么？</label><textarea name="question" maxlength="1000" placeholder="向负责人提问"></textarea></div><div class="field"><label>从哪里了解到活动？</label><select name="source"><option>直接访问</option><option>微信公众号</option><option>微信群</option><option>朋友圈</option><option>校园论坛</option></select></div></div><div class="form-actions"><button class="primary" type="submit" ${e.remaining?'':'disabled'}>${icon('send')}提交报名</button></div></form>`;
  }else if(publicTab==='ticket'){
    body=ticketInfo?`<div class="ticket"><h2>${esc(ticketInfo.name)}，报名成功</h2><p class="small muted">报名凭证</p><code>${esc(ticket())}</code><span class="badge">${ticketInfo.checked_at?'已签到 · '+fmt(ticketInfo.checked_at):'待签到'}</span></div>${e.state==='LIVE'&&!ticketInfo.checked_at?button('确认现场签到','self-checkin',true,'scan-line'):''}${ticketInfo.question?`<div class="section"><h2>我的提问</h2><p>${esc(ticketInfo.question)}</p><div class="inline-note" style="margin-top:15px">${esc(ticketInfo.answer||'等待负责人答复')}</div></div>`:''}`:`<h2>查询报名凭证</h2><form id="ticket-form">${field('ticket','报名凭证','text','','required')}<div class="form-actions"><button class="primary" type="submit">查看报名</button></div></form>`;
  }else{
    body=!ticketInfo?empty('请先查询报名凭证','报名并签到后可提交反馈。'):!['LIVE','FEEDBACK'].includes(e.state)?empty('当前未开放反馈',labels[e.state]):!ticketInfo.checked_at?empty('请先完成签到','签到成功后可提交活动反馈。'):`<h2>${e.state==='LIVE'?'现场反馈':'活动后反馈'}</h2><form id="feedback-form"><div class="field"><label>整体满意度</label><select name="rating"><option value="">仅提交文字反馈</option><option value="5">5 · 非常满意</option><option value="4">4 · 满意</option><option value="3">3 · 一般</option><option value="2">2 · 不满意</option><option value="1">1 · 非常不满意</option></select></div><div class="spacer"></div><div class="field"><label>评价、问题或改进建议</label><textarea name="comment" required maxlength="2000" rows="6"></textarea></div><div class="form-actions"><button class="primary" type="submit">${icon('send')}提交反馈</button></div></form>`;
  }
  $('#app').innerHTML=`<main class="public-shell"><header class="public-top"><div class="brand"><span class="brand-mark">${icon('sprout')}</span>校园共创</div></header><div class="event-feature public-hero">${badge(e.state)}<h2>${esc(b.name)}</h2><div class="event-meta"><span>${icon('calendar-days')}${fmt(b.date)}</span><span>${icon('map-pin')}${esc(b.location||'待确定')}</span></div></div><div class="public-content"><p>${esc(b.objective||'活动准备中')}</p><p class="small muted">主办方：${esc(b.organizer||'待确定')}</p><div class="spacer"></div><div class="tabbar">${[['register','活动报名'],['ticket','我的报名'],['feedback','参与反馈']].map(([id,title])=>`<button data-public-tab="${id}" class="${publicTab===id?'active':''}">${title}</button>`).join('')}<button data-action="refresh" title="刷新活动状态">${icon('refresh-cw')}</button></div>${body}</div></main>`;refresh();
}

(async()=>{try{const health=await api('/api/health');mode=health.mode;publicOrigin=health.public_base_url||location.origin;if(publicId)await loadPublic();else if(key)await loadEvents();else login();}catch(e){if(publicId)$('#app').innerHTML=empty('活动暂时无法访问',esc(e.message));else{key='';login();}toast(e.message,true);}})();
setInterval(()=>{if(!busy&&document.visibilityState==='visible'&&!$('#modal').open&&event&&page==='onsite'&&!document.querySelector('input:focus,textarea:focus'))run(loadEvents);},30000);
