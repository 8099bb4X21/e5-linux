#!/usr/bin/env python3
"""Test the OpenWrt audio lifecycle with fake ALSA, never a modem."""
import importlib.machinery
import importlib.util
from pathlib import Path
source = Path(__file__).resolve().parents[1] / 'overlay/usr/libexec/e5-voice-audio'
loader = importlib.machinery.SourceFileLoader('openwrt_voice', str(source))
spec = importlib.util.spec_from_loader(loader.name, loader)
voice = importlib.util.module_from_spec(spec)
loader.exec_module(voice)
class Hardware:
    def __init__(self): self.speaker = False; self.events = []
    def start(self): self.events.append('start')
    def stop(self): self.events.append('stop'); self.speaker = False
    def set_speaker(self, value): self.speaker = value
    def mute(self, value): self.events.append(('mute', value))
hw=Hardware(); suspends=[]; c=voice.Controller(hw,suspends.append)
assert not c.update([{'id':'0','state':'--'}],{})['active']
assert not hw.events and not suspends
assert c.update([{'id':'1','state':'dialing'}],{})['active']
assert suspends==[True] and hw.events==['start']
# No timer expires or ends an active call; only observed modem state controls audio.
for _ in range(100): assert c.update([{'id':'1','state':'active'}],{})['active']
assert hw.events==['start']
r=c.update([{'id':'1','state':'active'}],{'speaker':True,'muted':True})
assert r['speaker'] and r['muted']
assert ('mute', True) in hw.events
assert not c.update([{'id':'1','state':'terminated'}],{})['active']
assert hw.events[-1]=='stop' and suspends==[True,False]
class Fails(Hardware):
    def start(self): raise RuntimeError('PCM not available')
f=voice.Controller(Fails(),suspends.append)
r=f.update([{'id':'2','state':'active'}],{})
assert not r['active'] and r['error']=='PCM not available'
# The watcher has no API or CLI branch for starting, answering or ending calls.
text=source.read_text()
for forbidden in ('--start','--accept','--hangup','--voice-create-call','--voice-delete-call'):
    assert forbidden not in text
print('OpenWrt voice audio checks passed')
# Notification lifecycle: incoming rings alert, answering stops owned alerts;
# an already-active call only vibrates for a waiting call.
from unittest.mock import patch
class AlertProcess:
    pid = 987654
    def poll(self): return None
spawned=[]; now=[0]
def spawn(argv): spawned.append(argv); return AlertProcess()
ringer=voice.RingAlert(spawn,lambda:now[0])
with patch.object(voice.os,'killpg') as kill:
    ringer.update([{'id':'3','state':'ringing-in'}],{'sound':True,'vibrate':True,'tone':'call'},False)
    assert spawned[0][0]=='paplay' and spawned[1][0]=='e5-vibrate'
    ringer.update([{'id':'3','state':'active'}],{'sound':True,'vibrate':True},True)
    assert kill.call_count==2 and not ringer.call_ids
    spawned.clear();now[0]=3
    ringer.update([{'id':'4','state':'waiting'}],{'sound':True,'vibrate':True},True)
    assert len(spawned)==1 and spawned[0][0]=='e5-vibrate'
    ringer.update([],{'sound':False,'vibrate':False},False)
assert not voice.Controller(Hardware(),suspends.append).update([{'id':'5','state':'ringing-in'}],{})['active']
print('Incoming ringtone/vibration checks passed')

# Card changes reinitialize the shared frontend even if polling misses the gap.
hw=Hardware();changes=[];control=voice.Controller(hw,changes.append)
assert control.update([{'id':'a','state':'active','card':0}],{})['sim']=='SIM1'
assert control.update([{'id':'b','state':'active','card':1}],{})['sim']=='SIM2'
assert hw.events==['start','stop','start'] and changes==[True,False,True]
print('Voice source-card transition checks passed')

# Terminated D-Bus objects can accumulate. Read their final state once, keep
# active/held calls fresh, and forget tombstones when an object disappears.
dead=voice.CALL_PATH+'7';active=voice.CALL_PATH+'8';queries=[]
paths=[dead,active]
def mm(*args):
    queries.append(args)
    if args[0]=='-m':return {'modem.voice.calls':paths.copy()}
    return {'call':{'properties':{'state':'terminated' if args[1]==dead else 'active',
                                 'sim-slot':'2','number':'test'}}}
cache=set()
with patch.object(voice,'mm_json',side_effect=mm):
    assert voice.calls(cache)[0]['card']==1
    queries.clear();assert voice.calls(cache)[0]['state']=='active'
    assert ('-o',dead) not in queries and ('-o',active) in queries
    paths[:]=[active];voice.calls(cache);assert not cache
    paths[:]=[dead,active];queries.clear();voice.calls(cache)
    assert ('-o',dead) in queries
print('Call cache and source SIM checks passed')

# Feed the monitor pipe as dbus-monitor would: a split profile line must wake
# the observer, owner changes clear tombstones, shutdown reaps the monitor.
import os,threading
read_fd,write_fd=os.pipe()
class Monitor:
    stdout=os.fdopen(read_fd,'rb',buffering=0)
    ended=False
    def poll(self):return 0 if self.ended else None
    def terminate(self):self.ended=True
    def wait(self,timeout=None):return 0
monitor=Monitor();stop=threading.Event();changed=threading.Event();reset=threading.Event()
with patch.object(voice.subprocess,'Popen',return_value=monitor):
    worker=threading.Thread(target=voice.watch_call_changes,args=(stop,changed,reset))
    worker.start();assert changed.wait(1)
    changed.clear();reset.clear()
    os.write(write_fd,b'sig\t123\torg.freedesktop.DBus\tNameOwner')
    assert not changed.wait(.05)
    os.write(write_fd,b'Changed\n')
    assert changed.wait(1) and reset.is_set()
    stop.set();worker.join(2)
assert not worker.is_alive() and monitor.ended and monitor.stdout.closed
os.close(write_fd)
print('D-Bus event wake, split lines and monitor cleanup checks passed')
