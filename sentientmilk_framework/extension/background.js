// SentientMilk's extension: her tabs in this Chrome (the user's own, with their sign-ins), for the brain on this
// computer (browser.py, extension.py). It speaks the DevTools protocol with the brain over a WebSocket on
// 127.0.0.1: a page's commands go to chrome.debugger as they are; what a browser does (tabs, windows,
// downloads) it does itself with the extension APIs, and tells as the protocol's events. Her tabs are the ones
// the brain opened, and the tabs and windows they open; the user's own tabs are never touched.

const VERSION = chrome.runtime.getManifest().version;
let socket = null, pinger = null;
const attached = new Map();   // tabId -> target id: her tabs, with the debugger on
const targets = new Map();    // target id -> tabId: hers (attached or not yet)
const children = new Map();   // session id of a frame of another site -> tabId
const loads = new Map();      // download id -> {target, told}

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

async function say(state) {
  await chrome.storage.local.set({state});
  chrome.action.setBadgeText({text: state === 'connected' ? 'on' : ''});
  chrome.runtime.sendMessage({state}).catch(() => {});  // an open popup shows it
}

async function connect() {
  if (socket && socket.readyState <= WebSocket.OPEN) return;
  const {code = ''} = await chrome.storage.local.get('code');
  const match = /^(\d+)-(\S+)$/.exec(code.trim());
  if (!match) return say('no code yet: paste the one SentientMilk shows (Tools > Her browser > Your Chrome)');
  const ws = new WebSocket(`ws://127.0.0.1:${match[1]}/extension`);
  socket = ws;
  ws.onopen = () => ws.send(JSON.stringify({hello: {token: match[2], version: VERSION, agent: navigator.userAgent}}));
  ws.onmessage = event => handle(JSON.parse(event.data));
  ws.onerror = () => {};
  ws.onclose = event => {
    if (socket !== ws) return;
    socket = null;
    clearInterval(pinger);
    for (const tabId of [...attached.keys()]) chrome.debugger.detach({tabId}).catch(() => {});
    attached.clear();
    children.clear();
    say(event.reason || 'not connected: SentientMilk is not running, or it was restarted');
    if (ws.welcomed) setTimeout(connect, 2000);  // it was connected: again soon (else every half minute)
  };
}

async function handle(message) {
  if (message.welcome) {
    if (socket) socket.welcomed = true;
    clearInterval(pinger);
    pinger = setInterval(() => send({method: 'Extension.ping', params: {}}), 20000);  // keeps this worker awake
    return say('connected');
  }
  if (message.id === undefined) return;
  try {
    send({id: message.id, result: (await run(message.method, message.params || {}, message.sessionId)) || {}});
  } catch (error) {
    send({id: message.id, error: {message: String((error && error.message) || error)}});
  }
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
  for (const [targetId, id] of [...targets]) {
    if (id !== tabId) continue;
    targets.delete(targetId);
    send({method: 'Target.targetDestroyed', params: {targetId}});
  }
});

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
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

chrome.runtime.onMessage.addListener(message => {
  if (message.connect) {
    if (socket) { const old = socket; socket = null; old.close(); }
    connect();
  }
});
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.alarms.create('connect', {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(connect);
connect();
