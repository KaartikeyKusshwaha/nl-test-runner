({ prefix, maxElements }) => {
  const selector = [
    'a[href]', 'button', 'input', 'select', 'textarea', 'summary',
    '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
    '[role="checkbox"]', '[role="radio"]', '[role="switch"]', '[role="combobox"]',
    '[role="option"]', '[role="treeitem"]', '[onclick]',
    '[tabindex]:not([tabindex="-1"])', '[contenteditable="true"]'
  ].join(',');
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const roots = [document];
  const candidates = [];
  while (roots.length) {
    const root = roots.shift();
    for (const previous of root.querySelectorAll('[data-nlqa-ref]')) previous.removeAttribute('data-nlqa-ref');
    for (const element of root.querySelectorAll(selector)) candidates.push({ element, root });
    for (const host of root.querySelectorAll('*')) if (host.shadowRoot?.mode === 'open') roots.push(host.shadowRoot);
  }
  const parentOrHost = element => element?.parentElement ||
    (element?.getRootNode?.() instanceof ShadowRoot ? element.getRootNode().host : null);
  const visible = element => {
    const rect = element.getBoundingClientRect();
    for (let node = element; node; node = parentOrHost(node)) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0' || node.hidden) return false;
    }
    return rect.width > 0 && rect.height > 0;
  };
  const accessibleName = (element, root) => {
    const labelledBy = clean(element.getAttribute('aria-labelledby')).split(' ').filter(Boolean)
      .map(id => clean(root.getElementById?.(id)?.innerText)).filter(Boolean).join(' ');
    const labels = [...(element.labels || [])].map(label => clean(label.innerText || label.textContent)).filter(Boolean).join(' ');
    const content = clean(element.innerText || element.textContent);
    return clean(element.getAttribute('aria-label') || labelledBy || labels || element.getAttribute('alt') ||
      element.getAttribute('title') || element.getAttribute('placeholder') || content ||
      (element.getAttribute('type') === 'password' ? '' : element.value) || '');
  };
  const visibleCandidates = candidates.filter(({ element }) => {
    try { return visible(element); } catch { return false; }
  }).map(({ element, root }, index) => {
    const rect = element.getBoundingClientRect();
    const role = clean(element.getAttribute('role'));
    const tag = element.tagName.toLowerCase();
    const type = clean(element.getAttribute('type')).toLowerCase();
    const state = [];
    if (element.disabled || element.getAttribute('aria-disabled') === 'true') state.push('disabled');
    if (element.required || element.getAttribute('aria-required') === 'true') state.push('required');
    if (element.checked || element.getAttribute('aria-checked') === 'true') state.push('checked');
    if (element.selected || element.getAttribute('aria-selected') === 'true') state.push('selected');
    if (element.getAttribute('aria-expanded') !== null) state.push(`expanded=${element.getAttribute('aria-expanded')}`);
    let value = '';
    if (type === 'password') value = '****';
    else if (['input', 'textarea'].includes(tag)) value = clean(element.value);
    const options = tag === 'select' ? [...element.options].slice(0, 15).map(option => clean(option.label || option.text)).filter(Boolean) : [];
    return { element, root, index, tag, role, type, name: accessibleName(element, root), state, value,
      href: tag === 'a' ? clean(element.href).slice(0, 160) : '', options,
      optionCount: tag === 'select' ? element.options.length : 0,
      inViewport: rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth };
  });
  if (visibleCandidates.length > maxElements) {
    visibleCandidates.sort((a, b) => Number(b.inViewport) - Number(a.inViewport) ||
      Number(['input','select','textarea','button'].includes(b.tag)) - Number(['input','select','textarea','button'].includes(a.tag)) || a.index - b.index);
  }
  const selected = visibleCandidates.slice(0, maxElements);
  const elements = [];
  const lines = selected.map((item, index) => {
    const ref = `e${index + 1}`;
    item.element.setAttribute('data-nlqa-ref', ref);
    elements.push({ ref: prefix ? `${prefix}:${ref}` : ref, frameIndex: prefix ? Number(prefix.slice(1)) : 0 });
    const desc = [item.role || item.tag, JSON.stringify(item.name || '')];
    if (item.type) desc.push(`type=${item.type}`);
    if (item.state.length) desc.push(item.state.join(','));
    if (item.value) desc.push(`value=${JSON.stringify(item.value)}`);
    if (item.href) desc.push(`href=${JSON.stringify(item.href)}`);
    if (item.options.length) desc.push(`options=${JSON.stringify(item.options)}${item.optionCount > 15 ? `(+${item.optionCount - 15})` : ''}`);
    return `[${elements[elements.length - 1].ref}] ${desc.join(' ')}`;
  });
  const bodyText = clean(document.body?.innerText).slice(0, 2000);
  const headings = [...document.querySelectorAll('h1,h2,h3')].map(element => clean(element.innerText)).filter(Boolean).slice(0, 10);
  const alerts = [...document.querySelectorAll('[role="alert"],[role="status"],[aria-live],.alert,.toast,.notification,dialog[open],[role="dialog"]')]
    .filter(visible).map(element => clean(element.innerText)).filter(Boolean).slice(0, 20);
  const signature = `${location.href}|${lines.join('\n')}`;
  let hash = 2166136261;
  for (let index = 0; index < signature.length; index++) hash = Math.imul(hash ^ signature.charCodeAt(index), 16777619);
  return { title: document.title || '', url: location.href, elements, lines, text: bodyText, headings, alerts,
    hash: (hash >>> 0).toString(16), truncated: visibleCandidates.length > selected.length };
}
