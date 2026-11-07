({ prefix, maxElements }) => {
  const selector = [
    'a[href]', 'button', 'input', 'select', 'textarea', 'summary',
    '[role="button"]', '[role="link"]', '[role="tab"]', '[role="menuitem"]',
    '[role="checkbox"]', '[role="radio"]', '[role="switch"]', '[role="combobox"]',
    '[role="option"]', '[role="treeitem"]', '[onclick]',
    '[tabindex]:not([tabindex="-1"])', '[contenteditable="true"]'
  ].join(',');
  const customTags = new Set(['div', 'span', 'li', 'article', 'section']);
  const interactiveRoles = new Set([
    'button', 'link', 'tab', 'menuitem', 'checkbox', 'radio', 'switch', 'combobox', 'option', 'treeitem'
  ]);
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
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
  const visibleControlLabels = [...document.querySelectorAll('input,textarea,select,[role="combobox"]')]
    .filter(element => {
      try { return visible(element); } catch { return false; }
    })
    .map(element => clean(element.getAttribute('aria-label') || element.getAttribute('placeholder') ||
      [...(element.labels || [])].map(label => clean(label.innerText || label.textContent)).join(' ')))
    .filter(label => label.length >= 3);
  const activeElement = document.activeElement;
  const activeValue = activeElement && ['input', 'textarea'].includes(activeElement.tagName.toLowerCase())
    ? clean(activeElement.value).toLowerCase() : '';
  const customPointerRoot = element => {
    const tag = element.tagName.toLowerCase();
    if (!customTags.has(tag) || !visible(element)) return false;
    const rect = element.getBoundingClientRect();
    if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= innerHeight || rect.left >= innerWidth) return false;
    if (getComputedStyle(element).cursor !== 'pointer') return false;
    const text = clean(element.innerText || element.textContent);
    if (!text || text.length > 140) return false;
    // Prefer the semantic child when a broad clickable wrapper also contains a
    // visible input/button. Exposing both can make the agent click the wrapper
    // repeatedly and toggle the control closed instead of using its input.
    if ([...element.querySelectorAll(selector)].some(visible)) return false;
    // Some widgets render a clickable trigger next to a dropdown input while
    // repeating the input's placeholder in the trigger text. Keep only the
    // input reference when those labels overlap.
    if (visibleControlLabels.some(label => text.toLowerCase().includes(label.toLowerCase()))) return false;
    for (let node = parentOrHost(element); node; node = parentOrHost(node)) {
      const ancestorTag = node.tagName?.toLowerCase();
      if (ancestorTag && ['a', 'button', 'input', 'select', 'textarea', 'summary'].includes(ancestorTag)) return false;
      if (interactiveRoles.has(node.getAttribute?.('role'))) return false;
      if (node.getAttribute?.('tabindex') !== null && getComputedStyle(node).cursor === 'pointer') return false;
      if (customTags.has(ancestorTag) && getComputedStyle(node).cursor === 'pointer') return false;
    }
    return true;
  };
  const roots = [document];
  const candidates = [];
  const seen = new Set();
  while (roots.length) {
    const root = roots.shift();
    for (const previous of root.querySelectorAll('[data-nlqa-ref]')) previous.removeAttribute('data-nlqa-ref');
    for (const element of root.querySelectorAll(selector)) {
      if (!seen.has(element)) {
        candidates.push({ element, root, custom: false });
        seen.add(element);
      }
    }
    for (const host of root.querySelectorAll('*')) {
      if (host.shadowRoot?.mode === 'open') roots.push(host.shadowRoot);
      if (!seen.has(host) && customPointerRoot(host)) {
        candidates.push({ element: host, root, custom: true });
        seen.add(host);
      }
    }
  }
  const accessibleName = (element, root) => {
    const labelledBy = clean(element.getAttribute('aria-labelledby')).split(' ').filter(Boolean)
      .map(id => clean(root.getElementById?.(id)?.innerText)).filter(Boolean).join(' ');
    const labels = [...(element.labels || [])].map(label => clean(label.innerText || label.textContent)).filter(Boolean).join(' ');
    const content = clean(element.innerText || element.textContent);
    return clean(element.getAttribute('aria-label') || labelledBy || labels || element.getAttribute('alt') ||
      element.getAttribute('title') || element.getAttribute('placeholder') || content ||
      (element.getAttribute('type') === 'password' ? '' : element.value) || '');
  };
  const overlayAncestor = element => {
    for (let node = element; node; node = parentOrHost(node)) {
      if (node.matches?.('dialog[open],[role="dialog"],[aria-modal="true"]')) return true;
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      const zIndex = Number.parseInt(style.zIndex, 10);
      if (style.position === 'fixed' && Number.isFinite(zIndex) && zIndex >= 10 &&
          rect.width >= innerWidth * 0.75 && rect.height >= innerHeight * 0.5) return true;
    }
    return false;
  };
  const visibleCandidates = candidates.filter(({ element }) => {
    try { return visible(element); } catch { return false; }
  }).map(({ element, root, custom }, index) => {
    const rect = element.getBoundingClientRect();
    const role = clean(element.getAttribute('role'));
    const tag = element.tagName.toLowerCase();
    const type = clean(element.getAttribute('type')).toLowerCase();
    const name = accessibleName(element, root);
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
    return { element, index, tag, role, type, name, state, value, options,
      optionCount: tag === 'select' ? element.options.length : 0,
      inViewport: rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth,
      overlay: overlayAncestor(element), custom };
  });
  const dismissWords = /\b(accept|agree|understand|continue|dismiss|close|got it|okay|ok)\b/i;
  const actionPriority = item => {
    if (item.overlay) return dismissWords.test(item.name) ? 6 : 5;
    if (item.custom && activeValue.length >= 2 && item.name.toLowerCase().includes(activeValue)) return 5;
    if (['input', 'select', 'textarea'].includes(item.tag) || item.custom ||
        ['combobox', 'checkbox', 'radio', 'switch', 'option'].includes(item.role)) return 4;
    if (['button', 'tab', 'menuitem'].includes(item.role) || item.tag === 'button') return 3;
    if (item.tag === 'a' || item.role === 'link') return 1;
    return 2;
  };
  // Put form controls ahead of navigation and social links, even when the page
  // has fewer elements than the output cap. Otherwise a footer link can be
  // offered before the custom form control the test needs.
  visibleCandidates.sort((a, b) => actionPriority(b) - actionPriority(a) ||
    Number(b.inViewport) - Number(a.inViewport) || a.index - b.index);
  const truncated = visibleCandidates.length > maxElements;
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
    if (item.options.length) desc.push(`options=${JSON.stringify(item.options)}${item.optionCount > 15 ? `(+${item.optionCount - 15})` : ''}`);
    if (item.overlay) desc.push('top-overlay');
    if (item.custom) desc.push('custom control');
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
    hash: (hash >>> 0).toString(16), truncated };
}
