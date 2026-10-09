// Run with ucode test_screen_bands.uc /path/to/staged/settings.uc.
// Every modem/config/command operation is mocked; never modifies a real lock.
'use strict';
let caps = {lte:'1,3,5,8,34,39,40,41', nr:'1,5,8,28,41,78'};
let commands = [], queries = [], present = true, lte_value = [], nr_value = [];
let ctx = {
    run: () => 1, uci: () => ({get: () => null}),
    modem_present: () => present, cells: () => [], cell_locks: () => [],
    sim_card: () => 0, payload_ints: () => [134,134,0],
    lte_bands: () => lte_value, nr_bands: () => nr_value,
    NR_V1: [1,2,3,5,7,8,12,20,25,28,66,70,71,74],
    NR_V3: [34,38,39,40,41,50,51,77,78,79], NR_SUPER: [75,76,80,81,82,83,84,86],
    at: (cmd) => { push(commands, cmd); return ''; },
    sh_json: (cmd) => { push(queries,cmd); return index(cmd, 'lock caps') >= 0 ? caps : {}; }
};
let categories = loadfile(ARGV[0], {raw_mode:true})()(ctx);
let network = filter(categories, c => c.id == 'network')[0];
function check(ok, message) { if (!ok) die(message); }
function item(id) { return filter(network.items(), i => i.id == id)[0]; }
function choices(id) { return join(',', map(item(id).options, o => o.value)); }
check(choices('lte_bands') == caps.lte, 'LTE differs from dashboard');
check(choices('nr_bands') == caps.nr, 'NR differs from modem capability');
caps.nr = '3,77,79';
check(choices('nr_bands') == caps.nr, 'NR capabilities did not refresh');
commands = [];nr_value = [77];
check(network.set('nr_bands', [77]) == null, 'Dynamic NR candidate rejected');
check(commands[0] == 'AT+SPLBAND=2,0,0,128,0', 'NR candidate encoded incorrectly');
commands = [];
check(network.set('nr_bands', [78]) != null && !length(commands), 'Unsupported NR silently filtered/written');
check(network.set('lte_bands', [38]) != null && !length(commands), 'Unsupported LTE silently filtered/written');
lte_value = [1,3,5,8,34,39,40,41];nr_value = [];
check(network.set('bands_default', null) == null, 'Default bands failed');
check(commands[0] == 'AT+SPLBAND=1,0,450,0,149,0', 'Default uses old LTE bands');
caps.nr = '';commands = [];
check(!length(item('nr_bands').options), 'Missing NR capability invented bands');
commands = [];
check(network.set('nr_bands', [78]) != null && !length(commands), 'Missing capability allowed a lock');
check(network.set('nr_bands', []) == null, 'Missing capability prevented unlock');
present = false;queries = [];network.items();
check(index(queries, '/usr/libexec/unisoc-modem/lock caps lte') >= 0, 'No-modem view queried NR');
print('Screen band candidates, dynamic validation, encoding, defaults and failure handling: PASS\n');
