'use strict';
'require view';
'require rpc';
'require ui';
'require uci';
'require form';
// Forwarding-only page: reuse T551M's single dual-SIM forwarding backend.
var callTest = rpc.declare({ object: 'e5-sms', method: 'forward_test', params: [ 'card' ] });
var callLog = rpc.declare({ object: 'e5-sms', method: 'forward_log', expect: { log: [] } });
var JSON_BODY = '{"from":"{from}","text":"{text}","time":"{time}","sim":"{sim}","device":"{device}"}';

// what a preset fills in; KEY, TOKEN and the like are the user's own
var PRESETS = {
	json: { name: '通用 JSON webhook', method: 'POST', type: 'application/json',
		url: 'https://example.com/sms', body: JSON_BODY },
	bark: { name: 'Bark (iOS)', method: 'POST', type: 'application/json',
		url: 'https://api.day.app/push',
		body: '{"device_key":"你的Key","title":"短信 {from}","body":"{text}","group":"E5"}' },
	pushplus: { name: 'PushPlus (微信)', method: 'POST', type: 'application/json',
		url: 'https://www.pushplus.plus/send',
		body: '{"token":"你的Token","title":"短信 {from}","content":"{text}\\n\\n{time} {sim}","template":"txt"}' },
	serverchan: { name: 'Server 酱', method: 'POST', type: 'application/x-www-form-urlencoded',
		url: 'https://sctapi.ftqq.com/你的SendKey.send',
		body: 'title={from}&desp={text}' },
	telegram: { name: 'Telegram Bot', method: 'POST', type: 'application/json',
		url: 'https://api.telegram.org/bot你的Token/sendMessage',
		body: '{"chat_id":"你的ChatID","text":"短信 {from}\\n{text}\\n{time}"}' },
	wecom: { name: '企业微信群机器人', method: 'POST', type: 'application/json',
		url: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的Key',
		body: '{"msgtype":"text","text":{"content":"短信 {from}\\n{text}\\n{time}"}}' },
	dingtalk: { name: '钉钉群机器人', method: 'POST', type: 'application/json',
		url: 'https://oapi.dingtalk.com/robot/send?access_token=你的Token',
		body: '{"msgtype":"text","text":{"content":"短信 {from}\\n{text}\\n{time}"}}' }
};

function safeText(value) {
	return document.createTextNode(String(value == null ? '' : value));
}

function notify(ok, text) {
	ui.addNotification(null, E('p', {}, safeText(text)), ok ? 'info' : 'danger');
}

return view.extend({
    load: function() { return Promise.all([callLog(), uci.load('e5-notify')]); },
	handleTest: function(card, ev) {
		var btn = ev.currentTarget;
		btn.disabled = true;
		return callTest(card).then(function(r) {
			if (r && r.ok) notify(true, '测试转发成功（HTTP ' + r.code + '）');
			else notify(false, '测试转发失败：' + ((r && r.error) || '?') + '　（先保存设置再测试）');
			return callLog();
		}).then(L.bind(function(log) {
			var box = document.getElementById('e5-sms-log');
			if (box) box.replaceChildren(this.renderLog(log));
		}, this)).finally(function() { btn.disabled = false; });
	},

	renderLog: function(log) {
		if (!log || !log.length)
			return E('p', { 'class': 'cbi-section-descr' }, '还没有转发过');
		return E('table', { 'class': 'table' }, [
			E('tr', { 'class': 'tr table-titles' }, [
				E('th', { 'class': 'th' }, '时间'), E('th', { 'class': 'th' }, '来源卡'), E('th', { 'class': 'th' }, '来自'), E('th', { 'class': 'th' }, '结果')
			])
		].concat(log.slice(0, 20).map(function(e) {
			return E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td', 'style': 'white-space:nowrap' }, new Date(e.time * 1000).toLocaleString()),
				E('td', { 'class': 'td' }, e.sim || '—'),
				E('td', { 'class': 'td' }, safeText((e.test ? '（测试）' : '') + (e.from || ''))),
				E('td', { 'class': 'td', 'style': 'word-break:break-word' },
					safeText(e.ok ? '成功 HTTP ' + e.code : '失败：' + (e.error || ('HTTP ' + e.code))))
			]);
		})));
	},

	render: function(data) {
		var m = new form.Map('e5-notify');
		var common = m.section(form.NamedSection, 'forward', 'forward', '转发模式'); common.addremove = false;
		var mode = common.option(form.ListValue, 'mode', '配置方式');
		mode.value('shared', '两张卡共用一套'); mode.value('per_sim', '两张卡分别设置'); mode.default = 'shared'; mode.rmempty = false;
		function profile(section, title, card, separate) {
		var s = m.section(form.NamedSection, section, 'forward', title); s.addremove = false;
		var o;
		o = s.option(form.Flag, 'enabled', '启用转发');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');

		o = s.option(form.ListValue, '_preset', '套用预设', '选一个会填好下面的网址、方式和正文，把其中的 Key / Token 换成你自己的');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.value('', '—');
		Object.keys(PRESETS).forEach(function(k) { o.value(k, PRESETS[k].name); });
		o.cfgvalue = function() { return ''; };
		o.write = o.remove = function() {};
		o.onchange = function(ev, section_id, value) {
			var p = PRESETS[value];
			if (!p) return;
			var set = L.bind(function(name, v) {
				var opt = this.map.lookupOption(name, section_id);
				if (opt && opt[0]) opt[0].getUIElement(section_id).setValue(v);
			}, this);
			set('url', p.url);
			set('method', p.method);
			set('content_type', p.type);
			set('body', p.body);
		};

		o = s.option(form.Value, 'url', '网址');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.placeholder = 'https://example.com/sms';
		o.validate = function(section_id, v) {
			return (v == '' || /^https?:\/\/\S+$/.test(v)) ? true : '要以 http:// 或 https:// 开头';
		};

		o = s.option(form.ListValue, 'method', '方式');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.value('POST');
		o.value('GET');
		o.default = 'POST';

		o = s.option(form.ListValue, 'content_type', '正文类型');
		o.value('application/json', 'JSON (application/json)');
		o.value('application/x-www-form-urlencoded', '表单 (x-www-form-urlencoded)');
		o.value('text/plain', '纯文本 (text/plain)');
		o.default = 'application/json';
		o.depends({ 'e5-notify.forward.mode': separate ? 'per_sim' : 'shared', method: 'POST' });

		o = s.option(form.TextValue, 'body', '正文模板');
		o.rows = 5;
		o.monospace = true;
		o.default = JSON_BODY;
		o.depends({ 'e5-notify.forward.mode': separate ? 'per_sim' : 'shared', method: 'POST' });

		o = s.option(form.DynamicList, 'header', '额外的请求头', '例如 Authorization: Bearer xxx');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.placeholder = 'Name: value';

		o = s.option(form.Value, 'timeout', '超时（秒）');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.datatype = 'range(1,120)';
		o.default = '10';

		o = s.option(form.Button, '_test', '测试');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.inputtitle = '发一条测试消息';
		o.inputstyle = 'apply';
		o.onclick = L.bind(this.handleTest, this, card);
		// Keep the other mode's saved targets when its fields are hidden.
		s.children.forEach(function(option) { option.retain = true; });
		}
		profile.call(this, 'forward', '共用转发配置', 0, false);
		profile.call(this, 'forward_sim1', 'SIM1 转发配置', 0, true);
		profile.call(this, 'forward_sim2', 'SIM2 转发配置', 1, true);


        return m.render().then(L.bind(function(mapEl) {
            return E('div', { 'class': 'e5-sms-page' }, [
                E('link', { 'rel': 'stylesheet', 'href': L.resource('view/mu300/forward.css') }),
                E('h2', {}, '短信转发'),
                E('p', {}, '两张卡可以共用配置或分别转发，按短信来源卡选择目标。'),
                mapEl,
                E('h3', {}, '最近的转发'),
                E('div', { 'id': 'e5-sms-log' }, this.renderLog(data[0]))
            ]);
        }, this));
    }
});
