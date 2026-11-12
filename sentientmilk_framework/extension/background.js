// SentientMilk's extension: her tabs in this Chrome (the user's own, with their sign-ins), for the brain on this
// computer (browser.py, extension.py). It speaks the DevTools protocol with the brain over a WebSocket on
// 127.0.0.1: a page's commands go to chrome.debugger as they are; what a browser does (tabs, windows,
// downloads) it does itself with the extension APIs, and tells as the protocol's events. Her tabs are the ones
// the brain opened, and the tabs and windows they open; the user's own tabs are never touched.
//
// Connecting: the brain speaks first (protocol, version, a nonce) and this answers with an HMAC of the nonce
// keyed with the code's token, so a program that took the port never learns it. Closes the brain gives a reason
// for (extension.py): a wrong code is not tried again until it changes; another browser having SentientMilk is
// tried every half minute, and taken over only when the user says so here; an older extension reloads itself
// once (its files were likely updated with SentientMilk). Anything else is tried again soon, then every half
// minute. Disconnect stops all of it until the user connects again.

const VERSION = chrome.runtime.getManifest().version;
const PROTOCOL = 1;  // extension.py's PROTOCOL
const PAGE = chrome.runtime.getURL('popup.html');
const RETRY = [1, 2, 4, 8, 15];  // s between tries while this worker lives; after them, the half-minute alarm
const CLOSES = {4001: 'wrong-code', 4002: 'old-extension', 4003: 'busy', 4004: 'replaced'};
const DISCONNECTED = 4100;
const TROUBLE = ['wrong-code', 'busy', 'replaced', 'old-extension', 'old-brain', 'foreign'];
const BROWSER = (() => {  // as the user calls it: "Edge 140"
  for (const [mark, name] of [['Edg', 'Edge'], ['OPR', 'Opera'], ['Chrome', 'Chrome']]) {
    const found = new RegExp(mark + '/(\\d+)').exec(navigator.userAgent);
    if (found) return `${name} ${found[1]}`;
  }
  return 'Chrome';
})();
const icons = state => Object.fromEntries([16, 32, 48, 128].map(size => [size, `icons/${state}-${size}.png`]));

let socket = null, pinger = null, timer = null, tries = 0, status = {state: 'starting'};
const attached = new Map();   // tabId -> target id: her tabs, with the debugger on
const targets = new Map();    // target id -> tabId: hers (attached or not yet)
const children = new Map();   // session id of a frame of another site -> tabId
const loads = new Map();      // download id -> {target, told}
const reloaded = new Set();   // connect pages reloaded once already

function send(message) {
  if (socket && socket.welcomed && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

async function say(state, more = {}) {
  status = {state, browser: BROWSER, version: VERSION, ...more};
  await show();
}

async function show() {  // the popup reads it; the toolbar button wears it
  const tabs = attached.size, trouble = TROUBLE.includes(status.state), on = status.state === 'connected';
  await chrome.storage.local.set({status: {...status, tabs}});
  chrome.action.setIcon({path: icons(on ? 'on' : 'off')}).catch(() => {});
  chrome.action.setBadgeText({text: trouble ? '!' : on && tabs ? String(tabs) : ''});
  chrome.action.setBadgeBackgroundColor({color: trouble ? '#f2c35b' : '#3ddcd2'});
  if (chrome.action.setBadgeTextColor) chrome.action.setBadgeTextColor({color: '#180a14'});
  const words = {
    connected: tabs ? `connected, ${tabs} tab${tabs > 1 ? 's' : ''} of hers here` : 'connected',
    connecting: 'connecting', waiting: 'waiting for SentientMilk to start', 'no-code': 'not connected yet',
    'wrong-code': 'the code is not this SentientMilk\'s', busy: `in use in ${status.other}`,
    replaced: `moved to ${status.other}`, 'old-extension': 'this extension needs a reload',
    'old-brain': 'SentientMilk needs an update', foreign: `port ${status.port} is another program's`,
    disconnected: 'disconnected'}[status.state];
  chrome.action.setTitle({title: words ? `SentientMilk: ${words}` : 'SentientMilk'});
}

const newer = (a, b) => {  // dotted versions
  const x = String(a).split('.').map(Number), y = String(b).split('.').map(Number);
  for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
};

async function connect(take = false) {
  if (socket) return;  // open, or on its way
  clearTimeout(timer);
  const kept = await chrome.storage.local.get(['code', 'disconnected', 'refused']);
  if (socket) return;  // another call got there meanwhile
  if (kept.disconnected && !take) return say('disconnected');
  const code = kept.code || '', match = /^(\d+)-([\w-]+)$/.exec(code);
  if (!match) return say('no-code');
  if (kept.refused === code && !take) return say('wrong-code');  // not again until the code changes
  const ws = new WebSocket(`ws://127.0.0.1:${match[1]}/extension`);
  Object.assign(ws, {code, port: match[1], token: match[2], take});
  socket = ws;
  if (take || status.state === 'starting') say('connecting', {port: ws.port});
  ws.silence = setTimeout(() => ws.close(), 15000);  // it says nothing: not SentientMilk
  ws.onopen = () => { ws.opened = true; };
  ws.onmessage = event => {
    let message;
    try { message = JSON.parse(event.data); } catch (error) { return ws.close(); }
    if (!ws.greeted) return greet(ws, message);
    handle(ws, message);
  };
  ws.onclose = event => closed(ws, event);
}

async function greet(ws, message) {
  clearTimeout(ws.silence);
  const hi = message.sentientmilk;
  if (!hi || !hi.nonce) return ws.close();
  ws.greeted = true;
  ws.brain = hi.version;
  if (hi.protocol !== PROTOCOL) {
    ws.outdated = hi.protocol > PROTOCOL ? 'old-extension' : 'old-brain';
    if (ws.outdated === 'old-brain' || !(await reloadFor(hi.version))) ws.close();
    return;
  }
  if (newer(hi.version, VERSION) && await reloadFor(hi.version)) return;  // SentientMilk was updated: its files too
  const bytes = text => new TextEncoder().encode(text);
  const key = await crypto.subtle.importKey('raw', bytes(ws.token), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
  const signed = new Uint8Array(await crypto.subtle.sign('HMAC', key, bytes(hi.nonce)));
  let {instance} = await chrome.storage.local.get('instance');
  if (!instance) await chrome.storage.local.set({instance: instance = crypto.randomUUID()});
  if (ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({hello: {protocol: PROTOCOL, proof: [...signed].map(b => b.toString(16).padStart(2, '0')).join(''),
                                  instance, version: VERSION, name: BROWSER, take: ws.take}}));
}

async function reloadFor(version) {  // once for each version of SentientMilk, so files still older never loop
  const {reloaded: done} = await chrome.storage.local.get('reloaded');
  if (done === version) return false;
  await chrome.storage.local.set({reloaded: version});
  chrome.runtime.reload();
  return true;
}

async function handle(ws, message) {
  if (message.welcome) {
    ws.welcomed = true;
    tries = 0;
    await chrome.storage.local.remove('refused');
    clearInterval(pinger);
    pinger = setInterval(() => send({method: 'Extension.ping', params: {}}), 20000);  // keeps this worker awake
    return say('connected', {brain: message.welcome.version});
  }
  if (message.id === undefined) return;
  try {
    send({id: message.id, result: (await run(message.method, message.params || {}, message.sessionId)) || {}});
  } catch (error) {
    send({id: message.id, error: {message: String((error && error.message) || error)}});
  }
}

function letGo() {  // her tabs stay open, without the debugger (and Chrome's bar)
  clearInterval(pinger);
  for (const tabId of [...attached.keys()]) chrome.debugger.detach({tabId}).catch(() => {});
  attached.clear();
  children.clear();
}

function closed(ws, event) {
  clearTimeout(ws.silence);
  if (socket !== ws) return;
  socket = null;
  letGo();
  if (ws.unplugged) return say('disconnected');
  if (ws.outdated) return say(ws.outdated, {brain: ws.brain});
  if (ws.opened && !ws.greeted)  // 0.13's brain waited for the code instead
    return say(event.reason === 'no hello' ? 'old-brain' : 'foreign', {port: ws.port});
  const state = CLOSES[event.code];
  if (state === 'wrong-code') chrome.storage.local.set({refused: ws.code});
  if (state) return say(state, {other: event.reason, brain: ws.brain});  // busy: the half-minute alarm tries again
  say('waiting', {port: ws.port});
  if (tries < RETRY.length) timer = setTimeout(connect, RETRY[tries++] * 1000);
}

async function use(given, take = true) {  // the user connects: with a code, or the one kept
  let code = (await chrome.storage.local.get('code')).code;
  if (given !== undefined) {
    const found = /(\d+)-([\w-]{8,})/.exec(given);  // from a pasted page address too
    if (!found) return;
    code = found[0];
  }
  await chrome.storage.local.set({disconnected: false, ...(code ? {code} : {})});
  // connected with it, or the user's own try on the way (the connect page and its pick-up); a try of the alarm's
  // gives way, since it would not take over from another browser
  if (socket && socket.code === code && (socket.welcomed || socket.take)) {
    send({method: 'Extension.connectPage', params: {}});  // the panel's Connect hears it worked
    return;
  }
  if (socket) {
    const old = socket;
    socket = null;
    letGo();
    old.close();
  }
  tries = 0;
  connect(take);
}

async function unplug() {
  await chrome.storage.local.set({disconnected: true});
  clearTimeout(timer);
  if (!socket) return say('disconnected');
  socket.unplugged = true;
  socket.close(DISCONNECTED, 'the user disconnected');
}

async function pickUp(tab) {  // the panel's Connect, to a Chrome that was not running: blocked while this loaded
  const url = tab.pendingUrl || tab.url || '';
  if (!url.startsWith(PAGE + '#') || reloaded.has(tab.id) || tab.title === 'SentientMilk') return;
  const code = new URLSearchParams(url.split('#')[1]).get('code');
  if (!code) return;
  reloaded.add(tab.id);
  await use(code);
  chrome.tabs.reload(tab.id).catch(() => {});  // now the page itself, which says how it went
}

async function group(tabId) {  // her tabs wear SentientMilk's colour, so the user tells them from their own
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab.groupId !== chrome.tabGroups.TAB_GROUP_ID_NONE) return;  // one she opened joins its opener's
    const [mine] = await chrome.tabGroups.query({windowId: tab.windowId, title: 'SentientMilk'});
    const groupId = await chrome.tabs.group(
      mine ? {tabIds: tabId, groupId: mine.id} : {tabIds: tabId, createProperties: {windowId: tab.windowId}});
    if (!mine) await chrome.tabGroups.update(groupId, {title: 'SentientMilk', color: 'purple'});
  } catch (error) {}  // a popup window has no groups
}

async function targetOf(tabId) {  // the tab's DevTools target id (its main frame's id too)
  for (let tries = 0; tries < 100; tries++) {
    const found = (await chrome.debugger.getTargets()).find(t => t.tabId === tabId && t.type === 'page');
    if (found) { targets.set(found.id, tabId); return found.id; }
    await new Promise(done => setTimeout(done, 50));
  }
  throw new Error('No target for the tab');
}

async function tabOf(targetId) {
  if (targets.has(targetId)) return targets.get(targetId);
  const found = (await chrome.debugger.getTargets()).find(t => t.id === targetId && t.tabId !== undefined);
  if (!found) throw new Error('No target with given id found');
  targets.set(targetId, found.tabId);
  return found.tabId;
}

const bounds = w => ({left: w.left, top: w.top, width: w.width, height: w.height, windowState: w.state});

async function run(method, params, sessionId) {
  if (sessionId) {  // a page's (or one of its frames') own command
    const tabId = sessionId.startsWith('tab:') ? Number(sessionId.slice(4)) : children.get(sessionId);
    if (tabId === undefined || !attached.has(tabId)) throw new Error('Session with given id not found');
    return chrome.debugger.sendCommand(sessionId.startsWith('tab:') ? {tabId} : {tabId, sessionId}, method, params);
  }
  switch (method) {
    case 'Target.setDiscoverTargets':
    case 'Browser.setDownloadBehavior':
      return {};
    case 'Target.createTarget': {  // in a window of its own, behind what the user is using unless asked
      const made = await chrome.windows.create({url: params.url || 'about:blank', focused: !params.background,
                                                width: 1280, height: 900, type: 'normal'});
      return {targetId: await targetOf(made.tabs[0].id)};
    }
    case 'Target.attachToTarget': {
      const tabId = await tabOf(params.targetId);
      if (!attached.has(tabId)) {
        try {
          await chrome.debugger.attach({tabId}, '1.3');
        } catch (error) {  // still attached from before this worker started again: still hers
          if (!/already attached/i.test(String(error && error.message))) throw error;
          await chrome.debugger.sendCommand({tabId}, 'Runtime.evaluate', {expression: '0'});
        }
      }
      attached.set(tabId, params.targetId);
      group(tabId);
      show();
      return {sessionId: 'tab:' + tabId};
    }
    case 'Target.closeTarget':
      await chrome.tabs.remove(await tabOf(params.targetId));
      return {success: true};
    case 'Target.activateTarget': {
      const tab = await chrome.tabs.update(await tabOf(params.targetId), {active: true});
      await chrome.windows.update(tab.windowId, {focused: true});
      return {};
    }
    case 'Browser.getWindowForTarget': {
      const tab = await chrome.tabs.get(await tabOf(params.targetId));
      return {windowId: tab.windowId, bounds: bounds(await chrome.windows.get(tab.windowId))};
    }
    case 'Browser.getWindowBounds':
      return {bounds: bounds(await chrome.windows.get(params.windowId))};
    case 'Browser.setWindowBounds': {
      const b = params.bounds || {};
      const change = b.windowState ? {state: b.windowState} : {};
      for (const key of ['left', 'top', 'width', 'height']) if (b[key] !== undefined) change[key] = b[key];
      await chrome.windows.update(params.windowId, change);
      return {};
    }
    default:
      throw new Error(`${method} is not there in the user's Chrome`);
  }
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!attached.has(source.tabId)) return;
  if (method === 'Target.attachedToTarget') children.set(params.sessionId, source.tabId);
  if (method === 'Target.detachedFromTarget') children.delete(params.sessionId);
  send({method, params, sessionId: source.sessionId || 'tab:' + source.tabId});
});

chrome.debugger.onDetach.addListener((source, reason) => {
  const target = attached.get(source.tabId);
  if (target === undefined) return;
  attached.delete(source.tabId);
  for (const [session, tabId] of [...children]) if (tabId === source.tabId) children.delete(session);
  show();
  // the user pressed Cancel on Chrome's bar: she lets go of every tab there, which stay open
  send({method: reason === 'canceled_by_user' ? 'Extension.canceled' : 'Target.detachedFromTarget',
        params: {sessionId: 'tab:' + source.tabId, targetId: target, reason}});
});

chrome.tabs.onCreated.addListener(async tab => {  // a tab or a window one of hers opened is hers too
  if (tab.openerTabId === undefined || !attached.has(tab.openerTabId)) return;
  try {
    const targetId = await targetOf(tab.id);
    send({method: 'Target.targetCreated', params: {targetInfo: {
      targetId, type: 'page', openerId: attached.get(tab.openerTabId), url: tab.pendingUrl || tab.url || ''}}});
  } catch (error) {}
});

chrome.tabs.onRemoved.addListener(tabId => {
  reloaded.delete(tabId);
  for (const [targetId, id] of [...targets]) {
    if (id !== tabId) continue;
    targets.delete(targetId);
    send({method: 'Target.targetDestroyed', params: {targetId}});
  }
});

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.status === 'complete') pickUp(tab);
  const targetId = attached.get(tabId);
  if (targetId && (change.url || change.title))
    send({method: 'Target.targetInfoChanged', params: {targetInfo: {targetId, type: 'page', url: tab.url,
                                                                    title: tab.title}}});
});

// downloads: one that a tab of hers started is hers (it goes to her working folder); the user's stay theirs
chrome.downloads.onCreated.addListener(async item => {
  const origin = url => { try { return new URL(url).origin; } catch (e) { return ''; } };
  const mine = [];
  for (const [tabId, target] of attached) {
    try { mine.push({target, url: (await chrome.tabs.get(tabId)).url}); } catch (error) {}
  }
  // the page it came from, else a page of hers on its site
  const from = mine.find(tab => item.referrer && tab.url === item.referrer) ||
    mine.find(tab => origin(tab.url) && origin(tab.url) === origin(item.referrer)) ||
    mine.find(tab => origin(tab.url) && origin(tab.url) === origin(item.finalUrl || item.url));
  if (!from) return;
  loads.set(item.id, {target: from.target, told: false});
  if (item.filename) begin(item.id, item.filename, item.url);
});

function begin(id, filename, url) {
  const load = loads.get(id);
  if (!load || load.told) return;
  load.told = true;
  send({method: 'Browser.downloadWillBegin', params: {guid: String(id), frameId: load.target, url,
                                                      suggestedFilename: filename.split(/[\\/]/).pop()}});
}

chrome.downloads.onChanged.addListener(async delta => {
  if (!loads.has(delta.id)) return;
  if (delta.filename && delta.filename.current) begin(delta.id, delta.filename.current, '');
  const state = delta.state && delta.state.current;
  if (state === 'complete' || state === 'interrupted') {
    const [item] = await chrome.downloads.search({id: delta.id});
    begin(delta.id, (item && item.filename) || 'download', (item && item.url) || '');
    loads.delete(delta.id);
    send({method: 'Browser.downloadProgress', params: {guid: String(delta.id),
      state: state === 'complete' ? 'completed' : 'canceled', filePath: (item && item.filename) || ''}});
  }
});

chrome.runtime.onMessage.addListener(message => {  // the popup, or the connect page
  if (message.use) use(message.code);
  if (message.unplug) unplug();
  if (message.reload) chrome.runtime.reload();
});
chrome.runtime.onInstalled.addListener(async ({reason}) => {
  if (reason === 'install' && !(await chrome.storage.local.get('code')).code)
    chrome.tabs.create({url: PAGE + '#setup'});  // what to do next, right after Load unpacked
});
chrome.runtime.onStartup.addListener(() => connect());
chrome.alarms.create('connect', {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(() => connect());
chrome.tabs.query({}).then(tabs => tabs.forEach(pickUp));
connect();
