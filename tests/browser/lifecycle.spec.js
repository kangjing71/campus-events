const { test, expect } = require('@playwright/test');
const { spawn } = require('node:child_process');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
let processHandle, providerHandle, folder, url, adminKey;
const PYTHON = process.env.PYTHON_BIN || 'python3';

test.beforeAll(async () => {
  folder = mkdtempSync(join(tmpdir(), 'campus-e2e-'));
  providerHandle = spawn(PYTHON, ['tests/mock_provider.py', '--port', '18769'], { cwd: process.cwd(), env: { ...process.env }, stdio: ['ignore', 'pipe', 'pipe'] });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Mock provider did not start')), 10000);
    providerHandle.stdout.on('data', d => { if (d.toString().includes('Mock ready')) { clearTimeout(timer); resolve(); } });
    providerHandle.on('exit', code => { clearTimeout(timer); reject(new Error('Mock provider exited '+code)); });
  });
  processHandle = spawn(PYTHON, ['server.py', '--port', '18765', '--public-base-url', 'http://localhost:18765'], {
    cwd: process.cwd(), env: { ...process.env, EVENT_DB: join(folder, 'events.sqlite3'), MODEL_URL: '', AGENT_ENV_FILE:join(folder,'.env'),
      PLANNING_API_URL: 'http://127.0.0.1:18769/planning', PLANNING_MODEL: 'test-planning', PLANNING_MODE: 'model', PLANNING_API_KEY: 'test', PLANNING_PROTOCOL: 'chat_completions',
      ...Object.fromEntries(['PUBLICITY','REGISTRATION','ONSITE','REVIEW'].map(r=>[r+'_MODE','rules'])) },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  let stderr = '';
  processHandle.stderr.on('data', d => stderr += d);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Server did not start: '+stderr)), 10000);
    processHandle.stdout.on('data', d => {
      const match = d.toString().match(/Campus Events: (.+)/);
      if (match) { url=match[1].trim();adminKey=url.split('#key=')[1];clearTimeout(timer);resolve(); }
    });
    processHandle.on('exit', code => {clearTimeout(timer);reject(new Error('Server exited '+code+': '+stderr));});
  });
});
test.afterAll(async () => {
  if(processHandle && processHandle.exitCode === null){processHandle.kill();await new Promise(resolve=>processHandle.on('exit',resolve));}
  if(providerHandle && providerHandle.exitCode === null){providerHandle.kill();await new Promise(resolve=>providerHandle.on('exit',resolve));}
  if(folder)rmSync(folder,{recursive:true,force:true});
});

test('complete organizer and participant lifecycle', async ({ page, browser, request }) => {
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);
  await page.evaluate(()=>{window.qrLinks=[];const draw=window.QRCode.toCanvas;window.QRCode.toCanvas=function(canvas,text,options){window.qrLinks.push(text);return draw.call(this,canvas,text,options);};});
  await page.getByRole('button',{name:'新建活动',exact:true}).click();
  await page.getByLabel('活动名称',{exact:true}).fill('校园 AI 创新交流夜');
  await page.getByRole('button',{name:'创建活动',exact:true}).click();
  await page.getByRole('button',{name:'开始策划'}).click();
  await page.getByLabel('用一段话描述活动').fill('先讨论目标');
  await page.getByRole('button',{name:'发送'}).click();
  await expect(page.locator('.chat-row:not(.pending)')).toHaveCount(2);
  await expect(page.locator('.chat-scroll')).toContainText('请补充时间地点');
  await page.getByLabel('用一段话描述活动').fill('补齐活动信息');
  await page.getByRole('button',{name:'发送'}).click();
  await expect(page.locator('.chat-row:not(.pending)')).toHaveCount(4);
  await page.getByLabel('用一段话描述活动').fill('信息齐了，请生成方案');
  await page.getByRole('button',{name:'发送'}).click();
  await expect(page.locator('.plan-card')).toContainText('模型策划：加入跨学院讨论，按时结束。');
  await page.getByRole('button',{name:'开始实施'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'宣传中心'}).click();
  await page.getByRole('button',{name:'生成宣传内容'}).click();
  await expect(page.locator('#qr')).toBeVisible();
  await expect.poll(()=>page.locator('#qr').evaluate(c=>{const p=c.getContext('2d').getImageData(0,0,c.width,c.height).data;return p.some((v,i)=>i%4===0&&v<100);})).toBe(true);
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button',{name:'下载海报'}).click();
  const poster = await downloadPromise;
  expect(poster.suggestedFilename()).toBe('活动海报.png');
  await poster.saveAs('test-results/poster.png');
  await page.getByRole('button',{name:'确认宣传并开放报名'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'报名管理'}).click();
  const joinUrl=await page.locator('.link-box a').getAttribute('href');
  expect(joinUrl).toMatch(/^http:\/\/localhost:18765\/join\//);
  const qrLinks=await page.evaluate(()=>window.qrLinks);
  expect(qrLinks.length).toBeGreaterThan(1);
  expect(qrLinks.every(link=>link===joinUrl)).toBe(true);
  expect(joinUrl).not.toContain(adminKey);
  const eventId=joinUrl.split('/').pop();
  const unauthorized=await request.get('http://127.0.0.1:18765/api/events');
  expect(unauthorized.status()).toBe(401);
  const bypass=await request.post(`http://127.0.0.1:18765/api/events/${eventId}/actions/confirm_recap`,{headers:{Authorization:'Bearer '+adminKey},data:{}});
  expect(bypass.status()).toBe(400);
  const publicResponse=await request.get(`http://127.0.0.1:18765/api/public/${eventId}`);
  expect(await publicResponse.json()).not.toHaveProperty('registrations');

  const context=await browser.newContext();
  const participant=await context.newPage();participant.on('pageerror',e=>errors.push(e.message));
  await participant.goto(joinUrl);
  await participant.getByLabel('姓名 *').fill('李同学');
  await participant.getByLabel('邮箱 *').fill('student@example.com');
  await participant.getByLabel('学院 *').fill('计算机学院');
  await participant.locator('[name=question]').fill('需要带电脑吗？');
  await participant.screenshot({path:'test-results/registration.png',fullPage:true});
  await participant.getByRole('button',{name:'提交报名'}).click();
  await expect(participant.getByRole('heading',{name:'李同学，报名成功'})).toBeVisible();
  const ticket=await participant.locator('.ticket code').textContent();
  expect(ticket.length).toBeGreaterThan(10);
  await page.getByRole('button',{name:'刷新活动数据'}).click();
  await expect(page.getByRole('cell',{name:'李同学'})).toBeVisible();
  const stale = await request.post(`http://127.0.0.1:18765/api/events/${eventId}/actions/start`, {headers:{Authorization:'Bearer '+adminKey},data:{expected_version:-1}});
  expect(stale.status()).toBe(400);
  expect((await stale.json()).error).toContain('已更新');
  await page.getByRole('button',{name:'回复提问'}).click();
  await page.getByLabel('答复').fill('不需要，欢迎轻装参加。');
  await page.getByRole('button',{name:'确认并保存答复'}).click();
  await page.getByRole('button',{name:'活动总览'}).click();
  await page.screenshot({path:'test-results/overview.png',fullPage:true});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('button',{name:'现场执行'}).click();
  await page.getByRole('button',{name:'开启现场签到',exact:true}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await participant.reload();
  await expect(participant.getByText('不需要，欢迎轻装参加。')).toBeVisible();
  await participant.getByRole('button',{name:'确认现场签到'}).click();
  await expect(participant.locator('.ticket .badge')).toContainText('已签到');
  await participant.getByRole('button',{name:'参与反馈'}).click();
  await participant.locator('[name=rating]').selectOption('4');
  await participant.locator('[name=comment]').fill('希望多留一点讨论时间。');
  await participant.getByRole('button',{name:'提交反馈'}).click();
  await expect(participant.locator('#toast')).toContainText('反馈已保存');
  await page.getByRole('button',{name:'刷新活动数据'}).click();
  await page.getByRole('button',{name:'提出调整'}).click();
  await page.locator('[name=reason]').fill('增加讨论时间');
  await page.getByRole('button',{name:'提交待确认建议'}).click();
  await page.getByRole('button',{name:'采纳调整'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'结束活动，收集反馈'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await participant.reload();
  await participant.getByRole('button',{name:'参与反馈'}).click();
  await participant.locator('[name=rating]').selectOption('5');
  await participant.locator('[name=comment]').fill('增加讨论后收获很大。');
  await participant.getByRole('button',{name:'提交反馈'}).click();
  await expect(participant.locator('#toast')).toContainText('反馈已保存');
  await page.getByRole('button',{name:'刷新活动数据'}).click();
  await page.getByRole('button',{name:'活动复盘'}).click();
  await page.getByRole('button',{name:'生成活动复盘'}).click();
  await expect(page.getByText('评分样本 1 份',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'确认复盘，生成总结'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await page.getByRole('button',{name:'确认总结并归档'}).click();
  await page.getByRole('button',{name:'确认执行'}).click();
  await expect(page.locator('#toast')).toContainText('已归档');
  await page.reload();
  await expect(page.getByText('本次活动已归档')).toBeVisible();
  await page.getByRole('button',{name:'活动复盘'}).click();
  await page.screenshot({path:'test-results/report.png',fullPage:true});
  expect(errors).toEqual([]);
  await context.close();
});
