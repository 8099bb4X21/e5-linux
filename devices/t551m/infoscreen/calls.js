/* Incoming calls have their own wake path; the lock underneath stays locked. */
'use strict';
window.T551MCalls = (() => {
    const live = new Set(['dialing','ringing-out','ringing-in','waiting','active','held']);
    let showing=false, ringing=new Set(), guardUntil=0, booted=false;
    const guarded=new WeakSet();
    const active=()=>showing;
    function attach(frame) {
        const doc=frame.contentDocument;
        if(!doc||guarded.has(doc))return;
        guarded.add(doc);
        for(const type of ['touchstart','touchend','pointerdown','pointerup','mousedown','mouseup','click'])
            frame.contentWindow.addEventListener(type,event=>{
                if(showing && (blank || performance.now()<guardUntil || last?.screen?.touch===false)) {
                    event.preventDefault();event.stopImmediatePropagation();
                }
            },{capture:true,passive:false});
    }
    function update(data) {
        if(data.error || !Array.isArray(data.calls))return;
        const calls=data.calls.filter(c=>live.has(c.state));
        const incoming=calls.filter(c=>c.state==='ringing-in'||c.state==='waiting');
        const fresh=incoming.some(c=>!ringing.has(String(c.id)));
        ringing=new Set(incoming.map(c=>String(c.id)));
        if(incoming.length && (fresh || (!showing && !blank))) {
            if(blank && data.wake===false)return;
            if(blank)setBlank(false);
            if(T551MPower.isOpen())T551MPower.close();
            if(!showing){
                showing=true;
                guardUntil=performance.now()+600;
                document.body.classList.add('phone-overlay');
                clearTimeout(idleTimer);
                if(appOpen)closeApp();
                openApp({id:'phone',name:{zh:'电话',en:'Phone'},entry:'index.html',callOverlay:true});
                applyTouch();
            }
        }
        if(showing && !calls.length){
            showing=false;
            document.body.classList.remove('phone-overlay');
            if(appOpen?.id==='phone')closeApp();
            applyTouch();resetIdle();
        }
    }
    async function pollCalls() {
        const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),2500);
        try {
            const response=await fetch('/api/plugins/phone/live',{cache:'no-store',signal:controller.signal});
            if(response.ok)update(await response.json());
        } catch(_) {} finally {clearTimeout(timeout);setTimeout(pollCalls,350);}
    }
    function boot(){if(!booted){booted=true;pollCalls();}}
    return {active,update,attach,boot};
})();
