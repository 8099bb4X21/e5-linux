// Exercise the shipped LuCI functions with mocked RPC; no device actions.
const fs = require('fs'), assert = require('assert');
const base = 'openwrt/luci-app-t551m/htdocs/luci-static/resources/';
const common = fs.readFileSync(base+'mu300/common.js','utf8');
const locks = fs.readFileSync(base+'view/mu300/locks.js','utf8');
const waiter = common.slice(common.indexOf('function waitLockJob('),common.indexOf('\nvar ',common.indexOf('function waitLockJob(')));
const busy = common.slice(common.indexOf('function busy('),common.indexOf('\n/*',common.indexOf('function busy(')));
new Function(common);new Function(locks);new Function(fs.readFileSync(base+'view/mu300/home.js','utf8'));
(async()=>{
    let queue = [{state:'running'},{state:'done',ok:1}], timers=new Map(), counter=0;
    const set=(fn,ms)=>{if(ms===240000){timers.set(++counter,fn);return counter;}queueMicrotask(fn);return ++counter;};
    const wait = new Function('callLockStatus','setTimeout','clearTimeout',waiter+';return waitLockJob;')(
        async()=>queue.shift(),set,id=>timers.delete(id));
    await wait({ok:1,id:'job'});
    queue=[{state:'error',error:'AT rejected'}];
    await assert.rejects(wait({ok:1,id:'job'}),/AT rejected/);
    await assert.rejects(wait({ok:0,error:'bad request'}),/bad request/);
    let removed=0;
    const clearBusy=new Function(busy+';return busy;')();
    clearBusy({classList:{contains:()=>false,remove:()=>{}},querySelectorAll:()=>[{remove:()=>removed++}]},false);
    assert.equal(removed,1,'paint() removed the busy class, but spinner still needs removal');
    let messages=[], cleared=0;
    const M={waitLockJob:async()=>{throw new Error('No AT response')},busy:()=>cleared++};
    const view=new Function('view','M',locks+';')({extend:x=>x},M);
    const instance={...view,note:(text,type)=>messages.push({text,type}),refresh:()=>{},_applying:true};
    await instance.readback({ok:1,id:'job'},{});
    assert.equal(cleared,1);assert.equal(instance._applying,false);
    assert(messages.some(m=>m.type==='error'&&m.text.includes('No AT response')));
    M.waitLockJob=async()=>({state:'done',ok:1});M.callLockGet=async()=>({ts:1,mode:{label:'4g'}});
    instance.paint=()=>{};instance.paintServing=()=>{};
    await instance.readback({ok:1,id:'job'},{});
    assert.equal(instance.lastLock.mode.label,'4g');assert.equal(messages.at(-1).type,'success');
    console.log('PASS: job success/error, clock-independent completion, spinner cleanup, failed and successful readback');
})().catch(e=>{console.error(e);process.exitCode=1});
