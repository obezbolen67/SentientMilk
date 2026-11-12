// The popup, and the page SentientMilk opens to connect (popup.html#code=...): the code is kept, then used.
const field = document.getElementById('code'), shown = document.getElementById('state');

async function keep(code) {
  await chrome.storage.local.set({code: code.trim()});
  chrome.runtime.sendMessage({connect: true});
}

chrome.runtime.onMessage.addListener(message => { if (message.state) shown.textContent = message.state; });
document.getElementById('save').onclick = () => keep(field.value);
(async () => {
  const given = new URLSearchParams(location.hash.slice(1)).get('code');
  if (given) await keep(given);
  const {code = '', state = 'not connected'} = await chrome.storage.local.get(['code', 'state']);
  field.value = code;
  shown.textContent = state;
})();
