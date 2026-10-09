#!/usr/bin/env python3
"""Run on OpenWrt with ucode: isolated counters, ledger and ubus object."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

source=Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix='dual-traffic-') as directory:
    root=Path(directory)
    for name in ['data','run','net']: (root/name).mkdir()
    for name in ['traffic','traffic-core.uc']: shutil.copy(source/name,root/name)
    card=root/'card';card.write_text('0')
    def counters(slot,rx,tx):
        dev=root/'net'/('sipa_eth8' if slot else 'sipa_eth0')
        (dev/'statistics').mkdir(parents=True,exist_ok=True)
        (dev/'ifindex').write_text(str(slot+50))
        (dev/'statistics/rx_bytes').write_text(str(rx))
        (dev/'statistics/tx_bytes').write_text(str(tx))
    counters(0,1000,200);counters(1,3000,400)
    day=time.strftime('%Y-%m-%d');month=day[:7]
    old={'version':1,'config':{'plan_name':'legacy','monthly_gb':20},'started_at':int(time.time()),
         'last':{'device':'sipa_eth0','boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 'ifindex':50,'rx':1000,'tx':200,'at':int(time.time())},
         'days':{day:{'rx':12345,'tx':234}},'months':{month:{'rx':12345,'tx':234}},
         'pending_rx':0,'pending_tx':0,'adjustment':None}
    (root/'data/state.json').write_text(json.dumps(old))
    bus='test.dualtraffic.'+str(os.getpid())
    env={**os.environ,'MU300_TRAFFIC_DIR':str(root/'data'),'MU300_TRAFFIC_RUN':str(root/'run'),
         'MU300_TRAFFIC_SYS':str(root/'net'),'MU300_TRAFFIC_CARD':str(card),'MU300_TRAFFIC_BUS':bus}
    def rpc(method,args=None):
        return json.loads(subprocess.check_output(['ubus','call',bus,method,json.dumps(args or {})]))
    def start():
        proc=subprocess.Popen(['ucode',str(root/'traffic')],env=env,stderr=subprocess.PIPE)
        for _ in range(30):
            if proc.poll() is not None: raise AssertionError(proc.stderr.read().decode())
            result=subprocess.run(['ubus','call',bus,'get','{}'],capture_output=True)
            if result.returncode==0:return proc
            time.sleep(.1)
        proc.terminate();proc.wait();raise AssertionError('no ubus object')
    proc=start()
    try:
        first=rpc('get',{'slot':'0'});second=rpc('get',{'slot':'1'})
        assert first['days'][0]['rx']==12345 and second['days'][0]['rx']==0,(first,second)
        assert json.loads((root/'data/state-v1.json').read_text())==old
        counters(0,1100,220);counters(1,3300,440);rpc('flush')
        a=rpc('get',{'slot':'0'});b=rpc('get',{'slot':'1'})
        assert a['days'][0]['rx']==12445 and a['days'][0]['tx']==254,a
        assert b['days'][0]['rx']==300 and b['days'][0]['tx']==40,b
        assert rpc('set',{'slot':'1','payload':json.dumps({'plan_name':'second','monthly_gb':55})})['ok']==1
        assert rpc('get',{'slot':'0'})['config']['plan_name']=='legacy'
        assert rpc('get',{'slot':'1'})['config']['monthly_gb']==55
        assert rpc('get',{'slot':'2'})['error']=='invalid_slot'
        assert rpc('set',{'slot':'1','payload':'{"device":"sipa_eth0"}'})['ok']==0
        card.write_text('1');rpc('flush');assert rpc('get')['slot']==1
        assert json.loads((root/'run/view.json').read_text())['slot']==1
    finally:proc.terminate();proc.wait(timeout=5)
    proc=start()
    try:
        assert rpc('get',{'slot':'0'})['days']==a['days']
        assert rpc('get',{'slot':'1'})['days']==b['days']
        assert rpc('get',{'slot':'1'})['config']['plan_name']=='second'
    finally:proc.terminate();proc.wait(timeout=5)
print('PASS: isolated SIM counters, legacy migration, settings, data-SIM switch and restart')
