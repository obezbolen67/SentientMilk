// The popup, and the same page in a tab: right after Load unpacked (#setup), and the page SentientMilk's Connect
// opens (#code=...), which hands its code over and closes itself once connected. It shows what background.js
// keeps in storage (status) and asks it to act.
const $ = id => document.getElementById(id);
const given = new URLSearchParams(location.hash.slice(1)).get('code');
const CODE = /(\d+)-([\w-]{8,})/;
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
// state -> tone, line, more, [button, its look, what it asks]; {key} is filled from the status
const STATES = {
  starting: ['muted', 'Starting…', ''],
  connecting: ['muted', 'Connecting to SentientMilk…', ''],
  connected: ['ok', '✓ Connected to SentientMilk {brain}',
              s => s.tabs ? `She has ${plural(s.tabs, 'tab')} open here, in the purple SentientMilk group.`
                          : 'She works here only in tabs of her own, in a purple SentientMilk group, when you ask her to.',
              ['Disconnect', 'bad', {unplug: true}]],
  waiting: ['muted', 'Waiting for SentientMilk',
            'Nothing answers on port {port} yet. This connects by itself once SentientMilk starts.',
            ['Try now', '', {use: true}]],
  'no-code': ['muted', 'Not connected yet',
              'In SentientMilk, open Tools › Her browser and press Connect my Chrome, or paste its code below.'],
  'wrong-code': ['bad', '✗ This code is not your SentientMilk\'s',
                 'Copy it again from SentientMilk (Tools › Her browser › Your Chrome) and paste it below.'],
  busy: ['warn', 'SentientMilk is using {other}', 'Use this one instead to have her tabs here.',
         ['Use this {name} instead', '', {use: true}]],
  replaced: ['warn', 'SentientMilk moved to {other}', 'It was connected there. Use this one to bring her back.',
             ['Use this {name} instead', '', {use: true}]],
  'old-extension': ['warn', 'This extension is older than SentientMilk {brain}',
                    'Reload it to pick up the newer files. If that does not help, Load unpacked again from the ' +
                    'folder SentientMilk shows.', ['Reload extension', '', {reload: true}]],
  'old-brain': ['warn', 'SentientMilk is older than this extension',
                'Update SentientMilk, and this connects by itself.'],
  foreign: ['bad', '✗ Port {port} belongs to another program',
            'Something other than SentientMilk answers there. Check the code, or the port SentientMilk uses.'],
  disconnected: ['muted', 'Disconnected', 'She cannot use this {name} until you connect again.',
                 ['Connect', '', {use: true}]],
};
const ASKS_FOR_CODE = ['starting', 'no-code', 'wrong-code', 'waiting', 'foreign'];
let ask = null, closing = false;

function render(status = {state: 'starting'}) {
  const s = {...status, name: (status.browser || 'Chrome').split(' ')[0]};
  const [tone, line, more, button] = STATES[s.state] || STATES.starting;
  const fill = text => (typeof text === 'function' ? text(s) : text).replace(/\{(\w+)\}/g, (_, key) => s[key] ?? '');
  $('legend').textContent = `This ${s.name}`;
  $('line').className = `line ${tone}`;
  $('line').textContent = fill(line);
  $('more').textContent = fill(more);
  $('act').hidden = !button;
  if (button) {
    $('act').textContent = fill(button[0]);
    $('act').className = button[1];
    ask = button[2];
  }
  $('code-card').hidden = !ASKS_FOR_CODE.includes(s.state);
  if (given && s.state === 'connected' && !closing) {  // the Connect page has done its part
    closing = true;
    $('more').textContent += ' This tab closes by itself.';
    setTimeout(() => chrome.tabs.getCurrent(tab => tab && chrome.tabs.remove(tab.id)), 2500);
  }
}

$('act').onclick = () => ask && chrome.runtime.sendMessage(ask);
$('form').onsubmit = event => {
  event.preventDefault();
  const ok = CODE.test($('code').value);
  $('hint').hidden = ok;
  $('hint').textContent = 'That is not a code. SentientMilk\'s look like 48217‑x1Yz…';  // a hyphen that keeps it whole
  if (ok) chrome.runtime.sendMessage({use: true, code: $('code').value});
};
chrome.storage.onChanged.addListener(changes => { if (changes.status) render(changes.status.newValue); });

document.body.classList.toggle('page', location.hash.length > 1);
$('version').textContent = `extension · ${chrome.runtime.getManifest().version}`;
// wakes background.js too, whose status may be from before Chrome put it to sleep
chrome.runtime.sendMessage(given ? {use: true, code: given} : {wake: true}).catch(() => {});
chrome.storage.local.get(['status', 'code']).then(({status, code = ''}) => {
  $('code').value = given || code;
  render(status);
  if (!$('code-card').hidden && !given) $('code').focus();
});
