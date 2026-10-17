#!/usr/bin/env ucode
// mu300-smsfwd / E5 pool adapter.
//
// E5 keeps its two-SIM inbox in one JSON file (/etc/e5-sms/inbox.json). The
// forwarding sidecar reads a message spool (a next_id cursor plus msg/<id>
// files). This adapter materializes that spool from the inbox, additively
// (only ids not yet written are created), so it is cheap to run on every
// forwarding poll.
//
// Written under the pool directory given as ARGV[0]:
//   <pool>/next_id     the highest materialized message id
//   <pool>/msg/<id>    headers, a blank line, then the body
//
// Only received, non-deleted, non-hidden incoming messages are materialized.
// Historical (SIM-imported) messages are tagged source=sim so the sidecar's
// timestamp gate keeps them out of forwarding.
'use strict';

import { readfile, writefile, stat } from 'fs';

const INBOX = getenv('E5_SMS_INBOX') ?? '/etc/e5-sms/inbox.json';
const HIDDEN = getenv('E5_SMS_HIDDEN') ?? '/etc/unisoc-modem/hidden-sms.json';
const BASE = getenv('E5_SMS_RUN') ?? '/tmp/run/e5-sms';

function read_json(path) {
	try { return json(readfile(path) ?? ''); }
	catch (e) { return null; }
}

let pool = ARGV[0] ?? '/run/mu300-smsfwd-pool';
let data = read_json(INBOX);
if (type(data) != 'object' || type(data.messages) != 'array')
	exit(0);

let hidden = {};
let h = read_json(HIDDEN) ?? read_json(BASE + '/hidden.json');
if (type(h) == 'array')
	for (let id in h) hidden[`${h[id]}`] = true;

system(sprintf('mkdir -p %s/msg 2>/dev/null', pool));
let msgs = pool + '/msg';

let max_id = 0;
for (let m in data.messages) {
	if (type(m) != 'object')
		continue;
	if (m.direction != 'in' || m.state != 'received' || m.deleted)
		continue;
	let id = +m.id;
	if (!id)
		continue;
	if (hidden[`${id}`])
		continue;
	if (id > max_id)
		max_id = id;
	let file = sprintf('%s/%06d', msgs, id);
	if (stat(file))
		continue;
	let num = `${m.number ?? ''}`;
	let text = `${m.text ?? ''}`;
	let epoch = (+m.first_seen > 0) ? +m.first_seen : ((+m.epoch > 0) ? +m.epoch : 0);
	let time = `${m.time ?? ''}`;
	let source = m.historical ? 'sim' : 'direct';
	let body = sprintf('dir: mt\nfrom: %s\nreceived: %d\nscts: %s\nsource: %s\ncoding: text\n\n%s',
		num, epoch, time, source, text);
	writefile(file, body);
}

if (max_id > 0)
	writefile(pool + '/next_id', sprintf('%d\n', max_id));

exit(0);