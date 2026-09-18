const { test, expect } = require('@playwright/test');
const { spawn } = require('node:child_process');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const PYTHON = process.env.PYTHON_BIN || 'python3';
let server, provider, folder, url, key;
async function launch(args, env, match){
  const child=spawn(PYTHON,args,{cwd:process.cwd(),env,stdio:['ignore','pipe','pipe']});
  let error='';child.stderr.on('data',d=>error+=d);
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{child.kill();reject(new Error(error||'startup timeout'));},10000);
    child.stdout.on('data',d=>{const result=d.toString().match(match);if(result){clearTimeout(timer);resolve([child,result]);}});
    child.on('exit',()=>{clearTimeout(timer);reject(new Error(error));});
  });
}
test.beforeAll(async()=>{
  folder=mkdtempSync(join(tmpdir(),'campus-model-e2e-'));
  [provider]=await launch(['tests/mock_provider.py','--port','18768'],process.env,/Mock ready/);
  const env={...process.env,EVENT_DB:join(folder,'data.db'),AGENT_ENV_FILE:join(folder,'.env'),MODEL_URL:''};
  for(const role of ['PLANNING','PUBLICITY','REGISTRATION','ONSITE','REVIEW']){
    env[role+'_API_URL']='http://127.0.0.1:18768/'+role.toLowerCase();env[role+'_MODEL']='test-'+role;env[role+'_MODE']='model';env[role+'_API_KEY']='test';env[role+'_PROTOCOL']='chat_completions';
  }
  const result=await launch(['server.py','--port','18767'],env,/Campus Events: (.+)/);
  server=result[0];url=result[1][1].trim();key=url.split('#key=')[1];
});
test.afterAll(async()=>{
  for(const child of [server,provider])if(child&&child.exitCode===null){child.kill();await new Promise(r=>child.on('exit',r));}
  if(folder)rmSync(folder,{recursive:true,force:true});
});
test('five model roles are operable from the UI with approval gates',async({page,request})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);
  await page.getByRole('button',{name:'Agent 连接状态'}).click();
  await page.getByRole('button',{name:'测试策划 Agent'}).click();
  await expect(page.locator('#toast')).toContainText('测试通过');
  await page.getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('button',{name:'新建活动',exact:true}).click();
  await page.getByLabel('活动名称',{exact:true}).fill('智能策划活动');
  await page.getByRole('button',{name:'创建活动',exact:true}).click();
  await expect(page.getByText('5 / 5 个模型已配置')).toBeVisible();
  await page.getByRole('button',{name:'开始策划'}).click();
  await page.getByLabel('活动想法或补充信息').fill('先讨论目标');
  await page.getByRole('button',{name:'发送给策划 Agent'}).click();
  await expect(page.locator('.agent-chat')).toContainText('请补充时间地点');
  await page.getByLabel('活动想法或补充信息').fill('补齐活动信息');
  await page.getByRole('button',{name:'发送给策划 Agent'}).click();
  await expect(page.locator('#plan-form [name=name]')).toHaveValue('模型生成的校园交流会');
  await page.getByRole('button',{name:'根据已收集需求生成方案'}).click();
  await expect(page.getByText('模型策划：加入跨学院讨论，按时结束。',{exact:true})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'test-results/model-planning-mobile.png',fullPage:true});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button',{name:'确认策划方案',exact:true}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'宣传中心'}).click();
  await page.getByRole('button',{name:'生成宣传内容'}).click();
  await expect(page.locator('.prose')).toContainText('模型公众号');
  await page.getByRole('button',{name:'让 Agent 修改文案'}).click();
  await page.getByLabel('修改要求').fill('缩短文案');
  await page.getByRole('button',{name:'生成新草稿'}).click();
  await page.getByRole('button',{name:'确认宣传并开放报名'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'报名管理'}).click();
  const joinUrl=await page.locator('.link-box a').getAttribute('href'),id=joinUrl.split('/').pop();
  const response=await request.post(`http://127.0.0.1:18767/api/public/${id}/register`,{data:{name:'同学',email:'student@example.com',college:'学院',question:'在哪里举办？'}});
  const {ticket}=await response.json();
  await page.getByRole('button',{name:'刷新活动数据'}).click();
  await page.getByRole('button',{name:'分析报名情况'}).click();
  await expect(page.locator('.analysis-summary')).toContainText('已报名 1 人');
  await page.getByRole('button',{name:'回复提问'}).click();
  await page.getByRole('button',{name:'生成答复草稿'}).click();
  await expect(page.getByLabel('答复')).toHaveValue('活动地点：大学报告厅');
  let own=await request.post(`http://127.0.0.1:18767/api/public/${id}/ticket`,{data:{ticket}});
  expect((await own.json()).answer).toBeNull();
  await page.getByRole('button',{name:'确认并保存答复'}).click();
  own=await request.post(`http://127.0.0.1:18767/api/public/${id}/ticket`,{data:{ticket}});
  expect((await own.json()).answer).toContain('大学报告厅');
  await page.getByRole('button',{name:'现场执行'}).click();
  await page.getByRole('button',{name:'开启现场签到',exact:true}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await request.post(`http://127.0.0.1:18767/api/public/${id}/checkin`,{data:{ticket}});
  await page.getByRole('button',{name:'刷新活动数据'}).click();
  await page.getByLabel('现场情况',{exact:true}).fill('嘉宾迟到十分钟');
  await page.getByRole('button',{name:'分析现场并提出建议'}).click();
  await expect(page.getByText('流程调整待确认',{exact:true})).toBeVisible();
  await page.screenshot({path:'test-results/model-onsite-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'采纳调整'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'结束活动，收集反馈'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'活动复盘'}).click();
  await page.getByRole('button',{name:'生成活动复盘'}).click();
  await expect(page.getByText('实际报名 1 人。',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'确认复盘，生成总结'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'确认总结并归档'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await expect(page.locator('#toast')).toContainText('已归档');
  const runs=await request.get('http://127.0.0.1:18767/api/agent-runs',{headers:{Authorization:'Bearer '+key}});
  expect(new Set((await runs.json()).filter(r=>r.status==='success').map(r=>r.role)).size).toBe(5);
  expect(errors).toEqual([]);
});

test('independent role links run real tasks without changing events',async({page,request})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const headers={Authorization:'Bearer '+key};
  const before=await (await request.get('http://127.0.0.1:18767/api/events',{headers})).json();
  await page.goto('http://127.0.0.1:18767/agents/planning');
  await expect(page.getByLabel('负责人访问密钥')).toBeVisible();
  await page.getByLabel('负责人访问密钥').fill(key);
  await page.getByRole('button',{name:'进入测试'}).click();
  await page.getByRole('button',{name:'测试连接',exact:true}).click();
  await expect(page.locator('#toast')).toContainText('测试通过');
  await page.getByLabel('补充要求 / 对话消息').fill('先讨论目标');
  await page.getByRole('button',{name:'运行效果测试'}).click();
  await expect(page.locator('#result')).toContainText('请补充时间地点');
  await page.getByRole('button',{name:'继续补充需求'}).click();
  expect(JSON.parse(await page.getByLabel('测试数据（JSON）').inputValue()).history.length).toBe(2);
  await page.getByLabel('补充要求 / 对话消息').fill('补齐信息');
  await page.getByRole('button',{name:'运行效果测试'}).click();
  await expect(page.locator('#result')).toContainText('模型生成的校园交流会');
  await page.getByLabel('测试任务').selectOption('generate_plan');
  await page.getByRole('button',{name:'运行效果测试'}).click();
  await expect(page.locator('#result')).toContainText('模型策划');
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'下载结果',exact:true}).click();
  expect((await download).suggestedFilename()).toBe('planning-generate_plan-result.json');
  for(const [roleName,label,tasks]of [
    ['publicity','宣传',['generate_publicity','generate_recap']],
    ['registration','报名',['answer_question','analyze_registration']],
    ['onsite','现场',['analyze_onsite']],['review','复盘',['generate_review']]]){
    await page.getByRole('link',{name:label+' Agent',exact:true}).click();
    await expect(page).toHaveURL('http://127.0.0.1:18767/agents/'+roleName);
    for(const task of tasks){
      await page.getByLabel('测试任务').selectOption(task);
      await page.getByRole('button',{name:'运行效果测试'}).click();
      await expect(page.locator('#result')).toContainText('结构校验通过');
      await expect(page.locator('#result')).toContainText('模型生成');
    }
    if(roleName==='onsite')await page.screenshot({path:'test-results/independent-onsite-desktop.png',fullPage:true});
    if(roleName==='registration'){
      await page.setViewportSize({width:390,height:844});
      await page.screenshot({path:'test-results/independent-registration-mobile.png',fullPage:true});
      await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
      await page.setViewportSize({width:1440,height:1000});
    }
  }
  await page.getByLabel('测试数据（JSON）').fill('{bad');
  await page.getByRole('button',{name:'运行效果测试'}).click();
  await expect(page.locator('#input-error')).toContainText('不是有效 JSON');
  await page.getByRole('button',{name:'恢复示例输入'}).click();
  const invalid=JSON.parse(await page.getByLabel('测试数据（JSON）').inputValue());
  invalid.feedback[0].participant_index=40;
  await page.getByLabel('测试数据（JSON）').fill(JSON.stringify(invalid));
  await page.getByRole('button',{name:'运行效果测试'}).click();
  await expect(page.locator('#result')).toContainText('反馈必须引用已签到');
  await expect(page.getByRole('button',{name:'下载结果',exact:true})).toBeDisabled();
  await page.getByLabel('本角色最近的测试').selectOption('0');
  await expect(page.locator('#result')).toContainText('模型复盘');
  const after=await (await request.get('http://127.0.0.1:18767/api/events',{headers})).json();
  expect(after).toEqual(before);
  expect(errors).toEqual([]);
});
