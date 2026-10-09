'use strict';
'require view';
'require rpc';
'require poll';
'require mu300.common as M';

const getCpu = rpc.declare({object:'e5-cpu',method:'get',expect:{}});
const applyCpu = rpc.declare({object:'e5-cpu',method:'apply',params:['changes','persist'],expect:{}});
const resetCpu = rpc.declare({object:'e5-cpu',method:'reset',expect:{}});
const text = (zh,en) => M.translate(zh);
const mhz = value => value == null ? '—' : (value / 1000) + ' MHz';
const effectiveRange = p => text('当前有效范围：','Effective range: ') + mhz(p.effective_min ?? p.min) + ' – ' + mhz(p.effective_max ?? p.max);
const mv = value => value == null ? '—' : (value / 1000) + ' mV';
const offsetLabel = value => value == 0 ? text('原厂电压（0 mV）','Factory voltage (0 mV)') : (value > 0 ? '+' : '') + mv(value);
const voltageNow = p => text('当前偏移：','Active offset: ') + offsetLabel(p.voltage_offset) + text(' · 实测 ',' · Measured ') + mv(p.voltage_actual);

function node(tag, cls, value) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value != null) el.textContent = value;
    return el;
}
function field(label, input) {
    const wrap = node('label','cpu-field');
    wrap.append(node('span',null,label),input);
    return wrap;
}
function select(values, current, label) {
    const el = node('select');
    values.forEach(value => {
        const option = node('option',null,label ? label(value) : value);
        option.value = value; el.append(option);
    });
    el.value = current;
    return el;
}

return view.extend({
    load: function() { return getCpu(); },
    render: function(state) {
        M.injectCss();
        this.root = node('div','mud cpu-settings');
        const style = node('style',null,`
.cpu-settings{max-width:1200px;margin:auto}.cpu-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}
.cpu-head h2{margin:0}.cpu-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}
.cpu-settings .mud-card{padding:18px}.cpu-card-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:18px}
.cpu-card-head h3{margin:0}.cpu-current{font-size:1.2rem;font-weight:650;color:var(--brand,var(--primary,#239b82));font-variant-numeric:tabular-nums}
.cpu-field{display:flex;flex-direction:column;gap:7px;margin:14px 0;font-size:.85rem}.cpu-field select,.cpu-field input[type=number]{width:100%;min-height:40px;padding:8px 10px;border-radius:9px;border:1px solid var(--hairline,var(--border,#8885));background:var(--surface,var(--background,#fff));color:inherit}
.cpu-note{font-size:.8rem;line-height:1.6;color:var(--text-muted,var(--text-light,#888));margin:12px 0;overflow-wrap:anywhere}
.cpu-settings details{margin-top:16px;border-top:1px solid #8883;padding-top:12px}.cpu-settings summary{cursor:pointer;font-size:.85rem}
.cpu-settings table{width:100%;font-size:.8rem;margin-top:12px}.cpu-settings td,.cpu-settings th{padding:6px 0;text-align:left;font-variant-numeric:tabular-nums}
.cpu-footer{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:16px}.cpu-persist{display:flex;align-items:center;gap:8px;font-size:.85rem}
.cpu-message{font-size:.85rem;line-height:1.6;margin-top:12px;overflow-wrap:anywhere}.cpu-message.error{color:var(--danger,#df596a)}
.cpu-thermal{margin-top:14px}.cpu-thermal-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px 20px}
@media(max-width:450px){.cpu-grid{grid-template-columns:1fr}.cpu-settings .mud-card{padding:14px}.cpu-head{align-items:flex-start}.cpu-current{font-size:1rem}}
`);
        this.root.append(style);
        this.content = node('div'); this.root.append(this.content);
        this.paint(state);
        poll.add(() => {
            if (!this.root.isConnected || document.hidden || this.busy) return Promise.resolve();
            return getCpu().then(s => {
                if (!s.ok) throw new Error(s.error || 'CPU unavailable');
                (s.policies || []).forEach(p => {
                    const el = this.root.querySelector('[data-current="'+p.id+'"]');
                    if (el) el.textContent = mhz(p.current);
                    const limits = this.root.querySelector('[data-limits="'+p.id+'"]');
                    if (limits) limits.textContent = effectiveRange(p);
                    const voltage = this.root.querySelector('[data-voltage="'+p.id+'"]');
                    if (voltage) voltage.textContent = voltageNow(p);
                });
                (s.zones || []).forEach(z => {
                    const el = this.root.querySelector('[data-temperature="'+z.id+'"]');
                    if (el) el.textContent = z.temp == null ? '—' : (z.temp / 1000).toFixed(1) + ' °C';
                });
            }).catch(e => this.message(e.message,true));
        },2);
        return this.root;
    },
    message: function(value,error) {
        this.messageBox.textContent = M.translate(value);
        this.messageBox.classList.toggle('error',!!error);
    },
    paint: function(s) {
        this.state = s;
        this.content.replaceChildren();
        this.inputs = []; this.thermalInputs = [];
        const head = node('div','cpu-head');
        head.append(node('h2',null,text('CPU 设置','CPU settings')),
            node('span','cpu-note',text('频率 · 电压 · 温控','Frequency · Voltage · Thermal')));
        this.content.append(head);
        if (!s.ok || !s.available) this.content.append(node('div','mud-card',M.translate(s.error) || text('CPU 调频驱动尚未就绪','The CPU frequency driver is not ready')));
        const grid = node('div','cpu-grid');
        (s.policies || []).forEach(p => {
            const card = node('section','mud-card'), title = node('div','cpu-card-head');
            const now = node('span','cpu-current',mhz(p.current)); now.dataset.current = p.id;
            title.append(node('h3',null,'CPU '+p.cpus.replace(/ /g,', ')),now);
            const governor = select(p.governors,p.governor), low = select(p.frequencies,p.min,mhz), high = select(p.frequencies,p.max,mhz);
            governor.dataset.setting = p.id+'_governor'; low.dataset.setting = p.id+'_min'; high.dataset.setting = p.id+'_max';
            card.append(title,field(text('调速器','Governor'),governor),field(text('最低频率','Minimum frequency'),low),field(text('最高频率','Maximum frequency'),high));
            const limits = node('p','cpu-note',effectiveRange(p)); limits.dataset.limits = p.id; card.append(limits);
            card.append(node('p','cpu-note',text('schedutil 按负载调频；powersave 请求最低频率。上下限相同可固定频率，温控仍可降频。','schedutil follows load; powersave requests the minimum. Equal limits fix the requested frequency; thermal limits still apply.')));
            let voltage = null;
            if (p.voltage_boot_writable) {
                const values = [];
                for (let v = s.voltage_min; v <= s.voltage_max; v += s.voltage_step) values.push(v);
                voltage = select(values,p.voltage_next,offsetLabel);
                voltage.dataset.setting = p.id+'_voltage_next';
                const actual = node('p','cpu-note',voltageNow(p)); actual.dataset.voltage = p.id;
                card.append(field(text('下次启动电压偏移','Voltage offset on next boot'),voltage),actual,
                    node('p','cpu-note',text('保存后重启生效，CPU 与 SRAM 由固件同步调整。降压可能不稳定，建议每次只调一档；异常断电或崩溃后，下次启动自动恢复原厂电压。','Saved separately and applied after reboot. Firmware adjusts CPU and SRAM together. Undervolting can be unstable: change one step at a time. An unclean shutdown restores factory voltage on the next boot.')));
            }
            const details = node('details'), summary = node('summary',null,text('查看频率与电压表','Frequency and voltage table'));
            const table = node('table'), header = node('tr');
            header.append(node('th',null,'MHz'),node('th',null,'mV')); table.append(header);
            (p.voltages || []).forEach(v => { const row=node('tr'); row.append(node('td',null,v.khz/1000),node('td',null,v.uv/1000));table.append(row); });
            details.append(summary,table,node('p','cpu-note',text('此表为当前生效的固件电压表。偏移作用于整个供电域，不能逐频点单独改压，也不新增超频档位。','The active firmware voltage table. Offsets apply to the whole domain; individual frequency edits and extra overclock states are unavailable.')));
            card.append(details); grid.append(card);
            this.inputs.push({p,governor,low,high,voltage});
        });
        this.content.append(grid);
        (s.zones || []).forEach(z => {
            const card = node('section','mud-card cpu-thermal'), head = node('div','cpu-card-head');
            const temp = node('span','cpu-current',z.temp == null ? '—' : (z.temp/1000).toFixed(1)+' °C'); temp.dataset.temperature=z.id;
            head.append(node('h3',null,text('温控','Thermal')+' · '+z.name),temp);card.append(head);
            const fields = node('div','cpu-thermal-grid');
            const critical=z.trips.filter(t=>['critical','hot'].includes(t.type)).map(t=>t.temp/1000-10);
            z.trips.forEach(t => {
                if (t.writable) {
                    const input=node('input'); input.type='number';input.min=40;input.max=Math.min(100,...critical);input.step=1;input.value=t.temp/1000;
                    input.dataset.setting=z.id+'_trip'+t.id;
                    fields.append(field((t.throttles_cpu === false ? text('被动温控起点','Passive monitoring threshold') : text('降频触发温度','CPU throttling threshold'))+' (°C)',input));
                    this.thermalInputs.push({z,t,input});
                } else fields.append(node('div','cpu-note',(t.type==='critical'?text('过热关机保护','Critical shutdown'):t.type)+' · '+t.temp/1000+' °C'));
            });
            card.append(fields,node('p','cpu-note',text('被动温控起点用于更频繁地检测温度，达到降频触发温度才限制 CPU。阈值按顺序递增，原厂回差与过热关机保护保持生效。','Passive monitoring increases temperature checks; CPU throttling starts at the bound trip. Trips must increase in order. Factory hysteresis and critical shutdown remain active.')));this.content.append(card);
        });
        const footer=node('div','cpu-footer'),label=node('label','cpu-persist');
        this.persist=node('input');this.persist.type='checkbox';this.persist.checked=!!s.persistent;
        label.append(this.persist,node('span',null,text('开机应用调频与温控','Apply frequency and thermal settings at boot')));
        const apply=node('button','mud-btn primary',text('应用设置','Apply settings'));
        const reset=node('button','mud-btn',text('恢复默认','Restore defaults'));
        apply.disabled=!s.available;reset.disabled=!s.available;
        apply.onclick=()=>this.change(false);reset.onclick=()=>this.change(true);
        footer.append(label,apply,reset);this.content.append(footer,node('p','cpu-note',text('调频与温控可即时应用；电压设置独立保存，重启后生效。恢复默认后，电压也需要重启才能还原。关机充电始终使用原厂电压。','Frequency and thermal settings apply immediately; voltage settings are saved separately and need a reboot, including when restoring defaults. Charger-only boot uses factory voltage.')));
        this.messageBox=node('div','cpu-message');this.messageBox.setAttribute('role','status');this.content.append(this.messageBox);
        if (s.last_boot_error) this.message(text('上次开机配置未应用：','The boot profile was rejected: ')+s.last_boot_error,true);
        if (s.voltage_error) this.message(text('电压配置已回退：','Voltage profile reverted: ')+s.voltage_error,true);
        else if (s.voltage_reboot_required) this.message(text('电压配置已保存，重启后生效','Voltage settings saved; reboot to apply'));
    },
    change: async function(reset) {
        if(this.busy) return;
        try {
            const changes={policies:[],thermal:[]};
            if(!reset) {
                this.inputs.forEach(({p,governor,low,high,voltage})=>{
                    if(+low.value>+high.value) throw new Error(text('最低频率不能大于最高频率','Minimum frequency must not exceed maximum'));
                    const item={id:p.id,cpus:p.cpus,min:+low.value,max:+high.value,governor:governor.value};
                    if(voltage) item.voltage_next=+voltage.value;
                    changes.policies.push(item);
                });
                this.thermalInputs.forEach(({z,t,input})=>{
                    if(!input.checkValidity()) throw new Error(text('请填写有效的温度阈值','Enter a valid temperature threshold'));
                    changes.thermal.push({zone:z.name,trip:t.id,temp:+input.value*1000});
                });
            }
            this.busy=true;this.content.querySelectorAll('button,input,select').forEach(e=>e.disabled=true);
            const result=await (reset?resetCpu():applyCpu(changes,this.persist.checked));
            if(!result.ok) throw new Error(result.error||'Failed');
            this.paint(result);this.message(result.voltage_reboot_required ? text('调频与温控已应用；电压配置已保存，重启后生效','Frequency and thermal settings applied; reboot to apply saved voltage settings') : text('已应用，并读取确认当前设置','Applied and confirmed by kernel readback'));
        } catch(e) { this.message(e.message,true); }
        finally {this.busy=false;this.content.querySelectorAll('button,input,select').forEach(e=>e.disabled=!this.state.available);}
    },
    handleSaveApply:null,handleSave:null,handleReset:null
});
