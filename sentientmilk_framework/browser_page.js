// Her view of a page and what acting on it needs. It runs in the brain's own isolated world of the page
// (Page.createIsolatedWorld): the page's scripts cannot see it, and it sees the page's DOM as it is.
// browser.py evaluates this function once per document with the first id to give out, then calls __milk.
(function install(base) {
  if (globalThis.__milk) return globalThis.__milk.next();
  let next = base, menus = true;
  const ids = new WeakMap(), byId = new Map();
  // frames of another site run in processes of their own, read in worlds of their own: browser.py gives each
  // frame's iframe element here its key, and a view says where that frame's own view goes
  const marks = new WeakMap(), marked = new Map();
  addEventListener('contextmenu', e => { if (!menus) e.preventDefault(); });  // her right clicks: the page's menu only
  let lastChange = performance.now();
  const observer = new MutationObserver(() => { lastChange = performance.now(); });
  const watched = new WeakSet();
  function watch(doc) {
    if (watched.has(doc)) return;
    watched.add(doc);
    observer.observe(doc, {subtree: true, childList: true, attributes: true, characterData: true});
  }
  watch(document);

  const ACTIVE_ROLES = new Set(['button', 'link', 'checkbox', 'radio', 'tab', 'menuitem', 'menuitemcheckbox',
    'menuitemradio', 'option', 'switch', 'combobox', 'textbox', 'searchbox', 'slider', 'spinbutton', 'treeitem']);
  const GROUP_ROLES = {dialog: 'dialog', alertdialog: 'dialog', navigation: 'nav', main: 'main', banner: 'header',
    contentinfo: 'footer', complementary: 'aside', form: 'form', search: 'search', menu: 'menu', menubar: 'menu',
    listbox: 'listbox', tablist: 'tabs', tree: 'tree', grid: 'table', table: 'table', radiogroup: 'group',
    toolbar: 'toolbar'};
  const GROUP_TAGS = {dialog: 'dialog', form: 'form', nav: 'nav', main: 'main', header: 'header', footer: 'footer',
    aside: 'aside', table: 'table', fieldset: 'group'};
  const LISTS = new Set(['ul', 'ol', 'menu']);
  const INLINE = new Set(['inline', 'inline-block', 'inline-flex', 'inline-grid', 'contents', 'ruby']);
  const SKIPPED = new Set(['script', 'style', 'noscript', 'template', 'head', 'meta', 'link', 'title']);
  const COLLAPSE = 25, SHOWN = 20, NAME = 80, LINE = 300;
  const VIEW = 12000, PROSE = 2;  // characters a whole view holds before its runs of text show their start only

  const clean = text => (text || '').replace(/\s+/g, ' ').trim();
  const cut = (text, limit) => text.length > limit ? text.slice(0, limit - 1) + '…' : text;
  const quote = text => '"' + text.replace(/"/g, "'") + '"';
  const style = el => el.ownerDocument.defaultView.getComputedStyle(el);

  function idOf(el) {
    if (!ids.has(el)) {
      next += 1;
      ids.set(el, next);
      byId.set(next, new WeakRef(el));
    }
    return ids.get(el);
  }
  function get(id) {
    const el = byId.get(Number(String(id).replace(/^e/, '')))?.deref();
    return el && el.isConnected ? el : null;
  }
  function shown(el) {
    if (el.checkVisibility && !el.checkVisibility({visibilityProperty: true})) return false;
    const s = style(el);
    return s.display === 'contents' || el.getClientRects().length > 0;
  }
  function deepActive() {
    let active = document.activeElement;
    while (active) {
      const inner = active.shadowRoot?.activeElement ||
        (active.tagName === 'IFRAME' && safeDoc(active)?.activeElement);
      if (!inner || inner === active) break;
      active = inner;
    }
    return active;
  }
  function safeDoc(frame) {
    try { return frame.contentDocument; } catch (e) { return null; }
  }
  function children(node) {
    if (node.nodeType === 1 && node.shadowRoot) return node.shadowRoot.childNodes;
    if (node.tagName === 'SLOT') {
      const assigned = node.assignedNodes({flatten: true});
      return assigned.length ? assigned : node.childNodes;
    }
    return node.childNodes;
  }

  function role(el) {
    const given = (el.getAttribute('role') || '').split(' ')[0];
    if (given) return given;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'select';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const type = (el.type || 'text').toLowerCase();
      if (type === 'hidden') return '';
      if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
      if (type === 'checkbox' || type === 'radio') return type;
      if (type === 'range') return 'slider';
      if (type === 'file') return 'file input';
      if (['date', 'time', 'datetime-local', 'month', 'week', 'color'].includes(type)) return type + ' input';
      return type === 'search' ? 'searchbox' : 'textbox';
    }
    if (el.isContentEditable && !(el.parentElement && el.parentElement.isContentEditable)) return 'editable';
    return '';
  }
  function pointer(el) {
    const cursor = style(el).cursor;
    if (cursor !== 'pointer') return false;
    const parent = el.parentElement || el.getRootNode().host;
    return !parent || style(parent).cursor !== 'pointer';
  }
  function active(el) {
    const r = role(el);
    if (ACTIVE_ROLES.has(r) || ['select', 'file input', 'editable', 'slider'].includes(r) || r.endsWith(' input'))
      return r;
    if (el.disabled === undefined && (el.hasAttribute('onclick') || (el.tabIndex >= 0 && el.hasAttribute('tabindex')))
        && !GROUP_ROLES[r]) return 'clickable';
    if (!r && pointer(el)) return 'clickable';
    return '';
  }
  function textOf(el, limit = NAME, skip = null) {
    let out = '';
    (function each(node) {
      for (const child of children(node)) {
        if (out.length > limit * 2) return;
        if (child === skip) continue;
        if (child.nodeType === 3) out += child.textContent;
        else if (child.nodeType === 1 && !SKIPPED.has(child.tagName.toLowerCase()) &&
                 child.getAttribute('aria-hidden') !== 'true' && shown(child)) {
          if (child.tagName === 'IMG' && child.alt) out += ' ' + child.alt + ' ';
          else each(child);
          if (!INLINE.has(style(child).display)) out += ' ';
        }
      }
    })(el);
    return cut(clean(out), limit);
  }
  function nameOf(el) {
    const label = clean(el.getAttribute('aria-label'));
    if (label) return cut(label, NAME);
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const text = clean(by.split(/\s+/).map(id => {
        const target = el.getRootNode().getElementById?.(id) || el.ownerDocument.getElementById(id);
        return target ? textOf(target) : '';
      }).join(' '));
      if (text) return cut(text, NAME);
    }
    if (el.labels && el.labels.length) {
      const text = clean([...el.labels].map(l => textOf(l, NAME, el)).join(' '));
      if (text) return cut(text, NAME);
    }
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' && ['submit', 'button', 'reset'].includes(el.type)) return cut(clean(el.value) || el.type, NAME);
    if (tag === 'img' || (tag === 'input' && el.type === 'image')) return cut(clean(el.alt), NAME);
    if (!['input', 'textarea', 'select'].includes(tag)) {
      const text = textOf(el);
      if (text) return text;
    }
    const svgTitle = el.querySelector?.('svg title');
    return cut(clean(el.getAttribute('title') || el.getAttribute('placeholder') || el.getAttribute('aria-placeholder')
      || el.querySelector?.('img[alt]')?.alt || svgTitle?.textContent || ''), NAME);
  }
  function href(el) {
    const link = el.getAttribute('href');
    if (!link || link.startsWith('javascript:') || link === '#') return '';
    try {
      const url = new URL(link, el.baseURI);
      return cut(url.origin === location.origin ? url.pathname + url.search + url.hash : url.href, NAME);
    } catch (e) { return ''; }
  }
  function describe(el, full) {
    const r = active(el) || role(el), tag = el.tagName.toLowerCase(), states = [];
    let value = null, extra = '';
    const aria = name => el.getAttribute('aria-' + name);
    if (el.disabled || aria('disabled') === 'true') states.push('disabled');
    if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) states.push(el.checked ? 'checked' : 'not checked');
    else if (aria('checked')) states.push(aria('checked') === 'true' ? 'checked' : aria('checked') === 'mixed' ? 'mixed' : 'not checked');
    if (aria('expanded')) states.push(aria('expanded') === 'true' ? 'expanded' : 'collapsed');
    if (aria('selected') === 'true' || (tag === 'option' && el.selected)) states.push('selected');
    if (aria('pressed') === 'true') states.push('pressed');
    if (el.required || aria('required') === 'true') states.push('required');
    if (el.readOnly || aria('readonly') === 'true') states.push('read-only');
    if (aria('invalid') === 'true') states.push('invalid');
    if (el === deepActive()) states.push('focused');
    if (r === 'file input' && !shown(el)) states.push('hidden');
    if (tag === 'select') {
      const options = [...el.options];
      value = el.selectedOptions[0] ? clean(el.selectedOptions[0].text) : '';
      const listed = full ? options : options.slice(0, 12);
      extra = ' (options: ' + listed.map(o => cut(clean(o.text), 40)).join(' | ') +
        (options.length > listed.length ? ` | … ${options.length - listed.length} more` : '') + ')';
    } else if (tag === 'input' || tag === 'textarea') {
      if (el.type === 'password') value = el.value ? `(${el.value.length} characters)` : null;
      else if (!['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file'].includes(el.type))
        value = el.value ? cut(el.value.replace(/\s+/g, ' '), full ? 2000 : 120) : null;
      if (el.type === 'range') extra = ` (${el.min || 0}-${el.max || 100})`;
      if (el.type === 'file') extra = el.files && el.files.length ? ` (${[...el.files].map(f => f.name).join(', ')})` :
        (el.accept ? ` (accepts ${el.accept})` : '');
    } else if (r === 'editable') {
      value = cut(clean(el.innerText), full ? 4000 : 200) || null;
    } else if (aria('valuenow')) {
      value = aria('valuetext') || aria('valuenow');
    }
    if (tag === 'a') extra = href(el) ? ` -> ${href(el)}` : '';
    return {role: r || tag, name: nameOf(el), states, value, extra};
  }
  function token(el, full, labels) {
    // {t: what it is, x: what a line of its own adds (a link's address, a list's options)}
    const d = describe(el, full), id = idOf(el);
    labels[id] = d.role + (d.name ? ' ' + quote(d.name) : '');
    return {t: `${d.role} e${id}` + (d.name ? ' ' + quote(d.name) : '') +
      (d.states.length ? ` [${d.states.join(', ')}]` : '') + (d.value !== null ? ` = ${quote(d.value)}` : ''), x: d.extra};
  }

  function build(root, options) {
    const lines = [], labels = {}, full = !!options.full;
    let line = null;
    const flush = () => {
      if (line && line.parts.some(p => typeof p !== 'string' || p.trim())) lines.push(line);
      line = null;
    };
    const add = (part, depth) => {
      if (!line) line = {depth, parts: []};
      line.parts.push(part);
    };
    const head = (text, depth) => { flush(); lines.push({depth, parts: [text], head: true}); };

    function group(el, r) {
      const tag = el.tagName.toLowerCase();
      if (tag === 'dialog' && !el.open) return '';
      const given = el.getAttribute('role');
      if (given) return GROUP_ROLES[given.split(' ')[0]] || '';
      if (tag === 'header' || tag === 'footer') {  // only the page's own, not each article's
        const outer = el.parentElement && el.parentElement.closest('article, section, main, aside, nav');
        if (outer) return '';
      }
      return GROUP_TAGS[tag] || '';
    }
    function items(el) {
      return [...children(el)].filter(c => c.nodeType === 1 && shown(c));
    }
    function visit(el, depth) {
      const tag = el.tagName.toLowerCase();
      if (SKIPPED.has(tag)) return;
      const r = active(el);
      if (!shown(el)) {  // a file input is often hidden behind a button of the page's own: it still takes files
        if (r === 'file input') { flush(); add(token(el, full, labels), depth); flush(); }
        return;
      }
      if (el.getAttribute('aria-hidden') === 'true' && !r) {  // decoration (icon glyphs): only what can be used
        for (const child of el.querySelectorAll('a[href], button, input, select, textarea, [role], [tabindex]'))
          if (active(child) && shown(child)) { flush(); add(token(child, full, labels), depth); flush(); }
        return;
      }
      const display = style(el).display, block = !INLINE.has(display);
      if (tag === 'iframe' || tag === 'frame') {
        const doc = safeDoc(el), title = clean(el.title || el.name || '');
        if (!doc || !doc.body) {
          let host = '';
          try { host = new URL(el.src, location.href).host; } catch (e) {}
          if (marks.has(el)) {
            head(`frame${title ? ' ' + quote(title) : ''} (another site${host ? ': ' + host : ''})`, depth);
            head(`⟦frame ${marks.get(el)}⟧`, depth + 1);
            return;
          }
          head(`frame${title ? ' ' + quote(title) : ''} (another site${host ? ': ' + host : ''}; not readable here: ` +
               `use a picture and point)`, depth);
          return;
        }
        watch(doc);
        head(`frame${title ? ' ' + quote(title) : ''}`, depth);
        walk(doc.body, depth + 1);
        flush();
        return;
      }
      if (r) {
        const inner = el.querySelector?.('a[href], button, input, select, textarea, [role=button], [role=link], [role=checkbox], [onclick]');
        if (inner && r === 'clickable' && shown(inner)) {  // a clickable card with links and buttons in it
          const card = token(el, full, labels);
          head(card.t + card.x, depth);
          walk(el, depth + 1);
          flush();
          return;
        }
        if (block) flush();
        add(token(el, full, labels), depth);
        if (block) flush();
        return;
      }
      if (tag === 'img' && clean(el.alt)) { add(`img ${quote(cut(clean(el.alt), NAME))}`, depth); return; }
      if (tag === 'canvas') { add(`canvas ${el.width}x${el.height} (a picture shows it)`, depth); return; }
      if (tag === 'video') {
        add(`video${el.title ? ' ' + quote(el.title) : ''} [${el.paused ? 'paused' : 'playing'}]`, depth);
        return;
      }
      if (tag === 'label' && el.control) {  // its words are the field's name: only what is in it
        for (const child of el.querySelectorAll('*'))  // a hidden file input behind its label still takes files
          if (active(child) && (shown(child) || active(child) === 'file input')) add(token(child, full, labels), depth);
        return;
      }
      const heading = /^h[1-6]$/.test(tag) ? Number(tag[1]) : el.getAttribute('role') === 'heading' ?
        Number(el.getAttribute('aria-level') || 2) : 0;
      if (heading) {
        flush();
        add('#'.repeat(heading) + ' ', depth);
        walk(el, depth);
        flush();
        return;
      }
      const kind = group(el);
      const list = LISTS.has(tag) || ['list', 'listbox', 'menu', 'menubar', 'tablist', 'tree', 'grid', 'table'].includes(el.getAttribute('role'));
      const rows = tag === 'table' ? [...el.querySelectorAll(':scope > tr, :scope > * > tr')] : null;
      const entries = rows || (list ? items(el) : null);
      const collapsed = entries && !full && entries.length > COLLAPSE;
      if (kind || collapsed) {
        const name = clean(el.getAttribute('aria-label')) || (tag === 'fieldset' ? textOf(el.querySelector('legend') || el, NAME) : '');
        const what = (kind || 'list') + (name ? ' ' + quote(name) : '');
        if (collapsed) labels[idOf(el)] = what;
        head(what + (collapsed ? ` e${idOf(el)} (${entries.length} items)` : ''), depth);
        if (collapsed) {
          if (rows) for (const row of entries.slice(0, SHOWN)) { visit(row, depth + 1); flush(); }
          else for (const child of entries.slice(0, SHOWN)) { visit(child, depth + 1); flush(); }
          head(`… ${entries.length - SHOWN} more: browser_view part=e${idOf(el)}`, depth + 1);
        } else {
          walk(el, depth + 1);
        }
        flush();
        return;
      }
      if (display === 'list-item' || tag === 'li') { flush(); add('- ', depth); walk(el, depth); flush(); return; }
      if (display === 'table-row' || tag === 'tr') {
        flush();
        walk(el, depth);
        if (line) line.row = true;  // a table's row, not prose
        flush();
        return;
      }
      if (display === 'table-cell' || tag === 'td' || tag === 'th') {
        if (line && line.parts.length) add(' | ', depth);
        walk(el, depth);
        return;
      }
      if (block) flush();
      walk(el, depth);
      if (block) flush();
    }
    function walk(node, depth) {
      for (const child of children(node)) {
        if (child.nodeType === 3) {
          const text = child.textContent.replace(/\s+/g, ' ');
          if (text.trim() || (line && line.parts.length)) add(text, depth);
        } else if (child.nodeType === 1) visit(child, depth);
      }
    }
    if (root === document.body || root === document.documentElement) walk(document.body, 0);
    else visit(root, 0);
    flush();
    let out = [];
    for (const item of lines) {
      if (item.head) { out.push({depth: item.depth, text: item.parts[0]}); continue; }
      // things without words between them (a row of fields, a toolbar) each get a line of their own, saying all of
      // themselves (after a heading's #s or a list's -); things in a sentence stay in it, [in brackets]
      const tokens = item.parts.filter(p => typeof p !== 'string');
      const words = item.parts.filter(p => typeof p === 'string').join('');
      const prefix = (words.match(/^\s*(#+ |- )/) || ['', ''])[1];
      if (tokens.length && !clean(words).replace(/^(#+|-)$/, '')) {
        tokens.forEach((token, index) => out.push({depth: item.depth, text: (index ? '' : prefix) + token.t + token.x}));
        continue;
      }
      let text = clean(item.parts.map(p => typeof p === 'string' ? p : `[${p.t}]`).join(''));
      if (!full) text = cut(text, LINE);
      if (text) out.push({depth: item.depth, text, prose: !item.row && !/^(#+ |- )/.test(text)});
    }
    if (!full && out.reduce((sum, item) => sum + item.text.length + item.depth * 2 + 1, 0) > VIEW) {
      // a long page: its prose is browser_read's; the view keeps its shape, what can be used, and how each run
      // of text begins
      const kept = [];
      for (let start = 0; start < out.length;) {
        if (!out[start].prose) { kept.push(out[start++]); continue; }
        let end = start;
        while (end < out.length && out[end].prose) end++;
        kept.push(...out.slice(start, start + PROSE));
        const rest = out.slice(start + PROSE, end);
        if (rest.length) {
          const links = rest.reduce((sum, item) => sum + (item.text.match(/\[[a-z ]+ e\d+/g) || []).length, 0);
          kept.push({depth: rest[0].depth, text: `… ${rest.length} more lines of text` +
            (links ? ` with ${links} links` : '') + ': browser_read reads them, find= finds words or a link'});
        }
        start = end;
      }
      out = kept;
    }
    return {lines: out, labels};
  }

  function frameOffset(el) {
    let x = 0, y = 0, view = el.ownerDocument.defaultView;
    while (view && view.frameElement) {
      const frame = view.frameElement, r = frame.getBoundingClientRect();
      x += r.left + frame.clientLeft;
      y += r.top + frame.clientTop;
      view = frame.ownerDocument.defaultView;
    }
    return [x, y];
  }
  function short(el) {
    let node = el;
    while (node && node.nodeType === 1 && !active(node) && !group(node, '') && node !== document.body) node = node.parentElement;
    const target = node && node.nodeType === 1 && node !== document.body ? node : el;
    const d = describe(target, false);
    const text = d.name || textOf(target, 60);
    return `${d.role} e${idOf(target)}${text ? ' ' + quote(text) : ''}`;
    function group(n) { return n.tagName && (GROUP_TAGS[n.tagName.toLowerCase()] || GROUP_ROLES[n.getAttribute('role')]); }
  }

  const api = {
    next: () => next,
    sync: n => { next = Math.max(next, n); },  // ids go on from the tab's latest, whichever world gave it
    menu: on => { menus = on; },
    mark(el, key) { marks.set(el, key); marked.set(key, new WeakRef(el)); },
    offsetOf(key) {  // where a marked frame's own top left is, in this world's window
      const el = marked.get(key)?.deref();
      if (!el || !el.isConnected) return null;
      const r = el.getBoundingClientRect(), s = style(el), [ox, oy] = frameOffset(el);
      return [ox + r.left + el.clientLeft + parseFloat(s.paddingLeft || 0),
              oy + r.top + el.clientTop + parseFloat(s.paddingTop || 0)];
    },
    changed: () => document.readyState === 'loading' ? 0 : performance.now() - lastChange,
    view(options) {  // options.find is browser.py's, over every world's lines
      let root = document.body;
      if (options.part) {
        root = get(options.part);
        if (!root) return {gone: true};
      }
      const built = build(root || document.documentElement, {full: !!options.full});
      const lines = built.lines;
      const doc = document.documentElement;
      return {text: lines.map(item => '  '.repeat(item.depth) + item.text).join('\n'), labels: built.labels,
              next, title: document.title, url: location.href,
              scroll: [Math.round(scrollY), Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0),
                       innerHeight, innerWidth]};
    },
    locate(id, hitTest = true) {
      const el = get(id);
      if (!el) return {gone: true};
      el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
      const r = el.getBoundingClientRect(), [ox, oy] = frameOffset(el);
      const tag = el.tagName.toLowerCase(), type = (el.type || '').toLowerCase();
      const info = {x: ox + r.left + r.width / 2, y: oy + r.top + r.height / 2, width: r.width, height: r.height,
        tag, type, label: describe(el, false).role + ' ' + quote(nameOf(el)),
        editable: (tag === 'input' && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'range', 'color',
          'date', 'time', 'datetime-local', 'month', 'week'].includes(type)) || tag === 'textarea' || el.isContentEditable,
        file: tag === 'input' && type === 'file', select: tag === 'select',
        check: tag === 'input' && (type === 'checkbox' || type === 'radio') ||
          ['checkbox', 'radio', 'switch'].includes(el.getAttribute('role')),
        checked: el.checked === true || el.getAttribute('aria-checked') === 'true',
        setter: tag === 'input' && ['range', 'color', 'date', 'time', 'datetime-local', 'month', 'week'].includes(type),
        disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'};
      if (!r.width || !r.height) info.hidden = true;
      if (hitTest && !info.hidden) {
        const doc = el.ownerDocument;
        let hit = doc.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        while (hit && hit.shadowRoot) {
          const inner = hit.shadowRoot.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          if (!inner || inner === hit) break;
          hit = inner;
        }
        const related = hit && (hit === el || el.contains(hit) || hit.contains(el) || hit.control === el ||
          (el.labels && [...el.labels].includes(hit)) || el.getRootNode().host === hit ||
          (el.shadowRoot && el.shadowRoot.contains(hit)));
        if (hit && !related) info.covered = short(hit);
      }
      info.next = next;
      return info;
    },
    at(x, y) {  // what is at a point of the window (main-frame CSS pixels), for a click by point
      let hit = document.elementFromPoint(x, y);
      while (hit && hit.tagName === 'IFRAME' && safeDoc(hit)) {
        const r = hit.getBoundingClientRect();
        x -= r.left + hit.clientLeft;
        y -= r.top + hit.clientTop;
        hit = safeDoc(hit).elementFromPoint(x, y);
      }
      if (hit && hit.tagName === 'IFRAME' && marks.has(hit)) {  // a frame of another site: its own world says
        const r = hit.getBoundingClientRect();
        return {frame: marks.get(hit), x: x - r.left - hit.clientLeft, y: y - r.top - hit.clientTop, next};
      }
      while (hit && hit.shadowRoot) {
        const inner = hit.shadowRoot.elementFromPoint(x, y);
        if (!inner || inner === hit) break;
        hit = inner;
      }
      return {label: hit && hit !== document.documentElement ? short(hit) : '', next};
    },
    element: id => get(id),
    focus(id) {
      const el = get(id);
      if (!el) return false;
      el.focus({preventScroll: true});
      if (el.isContentEditable) {
        const range = el.ownerDocument.createRange();
        range.selectNodeContents(el);
        const selection = el.ownerDocument.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      } else if (el.select) el.select();
      return true;
    },
    value(id) {
      const el = get(id);
      return el ? (el.isContentEditable ? el.innerText : el.value) : null;
    },
    choose(id, wanted) {
      const el = get(id);
      if (!el) return {gone: true};
      const set = (proto, value) => Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
      if (el.tagName === 'SELECT') {
        const options = [...el.options], text = String(wanted).trim().toLowerCase();
        const option = options.find(o => clean(o.text).toLowerCase() === text) ||
          options.find(o => o.value.toLowerCase() === text) || options.find(o => clean(o.text).toLowerCase().includes(text));
        if (!option) return {error: `No option ${quote(String(wanted))}. Options: ` + options.map(o => clean(o.text)).join(' | ')};
        set(HTMLSelectElement.prototype, option.value);
        option.selected = true;
      } else {
        set(HTMLInputElement.prototype, String(wanted));
        if (el.value !== String(wanted)) return {error: `It did not take ${quote(String(wanted))} (it shows ${quote(el.value)}).`};
      }
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return {value: el.tagName === 'SELECT' ? clean(el.selectedOptions[0]?.text || '') : el.value};
    },
    scrollBy(id, pages) {
      const el = id ? get(id) : null;
      if (id && !el) return {gone: true};
      const target = el || document.scrollingElement || document.documentElement;
      const before = el ? el.scrollTop : scrollY;
      if (pages === 'top' || pages === 'bottom') {
        const top = pages === 'top' ? 0 : target.scrollHeight;
        el ? el.scrollTo({top, behavior: 'instant'}) : window.scrollTo({top, behavior: 'instant'});
      } else {
        const by = Number(pages) * (el ? el.clientHeight : innerHeight) * 0.85;
        el ? el.scrollBy({top: by, behavior: 'instant'}) : window.scrollBy({top: by, behavior: 'instant'});
      }
      const after = el ? el.scrollTop : scrollY;
      return {moved: Math.round(after - before), at: Math.round(after),
              end: Math.round((el ? el.scrollHeight - el.clientHeight : document.documentElement.scrollHeight - innerHeight))};
    },
    has(text) {
      const wanted = String(text).toLowerCase();
      const docs = [document, ...[...document.querySelectorAll('iframe')].map(safeDoc).filter(Boolean)];
      return docs.some(doc => (doc.body?.innerText || '').toLowerCase().includes(wanted));
    },
    read() {
      const out = [];
      let line = '';
      const flush = () => { if (clean(line)) out.push(clean(line)); line = ''; };
      (function each(node) {
        for (const child of children(node)) {
          if (child.nodeType === 3) { line += child.textContent; continue; }
          if (child.nodeType !== 1) continue;
          const tag = child.tagName.toLowerCase();
          if (SKIPPED.has(tag) || !shown(child)) continue;
          if (tag === 'iframe') {
            const doc = safeDoc(child);
            if (doc?.body) { flush(); each(doc.body); flush(); }
            else if (marks.has(child)) { flush(); out.push(`⟦frame ${marks.get(child)}⟧`); }
            continue;
          }
          const block = !INLINE.has(style(child).display);
          if (block) flush();
          if (/^h[1-6]$/.test(tag)) { line += '#'.repeat(Number(tag[1])) + ' '; each(child); flush(); out.push(''); continue; }
          if (tag === 'li') { line += '- '; each(child); flush(); continue; }
          if (tag === 'a' && href(child)) {
            const text = textOf(child, 200);
            line += text ? ` [${text}](${child.href}) ` : '';
            continue;
          }
          if (tag === 'img' && clean(child.alt)) { line += ` [image: ${clean(child.alt)}] `; continue; }
          if (tag === 'td' || tag === 'th') { line += ' | '; each(child); continue; }
          if (tag === 'br') { flush(); continue; }
          each(child);
          if (block) { flush(); if (tag === 'p' || tag === 'section' || tag === 'article') out.push(''); }
        }
      })(document.body);
      flush();
      return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
    },
  };
  globalThis.__milk = api;
  return next;
})
