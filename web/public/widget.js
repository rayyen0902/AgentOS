(function () {
  'use strict';

  var scriptTag = document.currentScript;
  if (!scriptTag) return;

  var tenantId = scriptTag.getAttribute('data-tenant-id');
  if (!tenantId) {
    console.error('[AgentOS Widget] data-tenant-id is required');
    return;
  }

  var baseUrl = scriptTag.getAttribute('data-api-base') || 'https://knownot.cc';

  // ============================================================
  // Shadow DOM host — the toggle button and iframe container live
  // inside a closed shadow root so no host-page CSS leaks in or out.
  // ============================================================
  var host = document.createElement('div');
  host.setAttribute('data-agentos-widget-host', '1');
  host.style.cssText = 'all:initial;';
  var shadow = host.attachShadow({ mode: 'closed' });

  // Shadow-scoped reset stylesheet
  var shadowStyle = document.createElement('style');
  shadowStyle.textContent = [
    ':host{all:initial;}',
    '.aw-container{position:fixed;bottom:84px;right:20px;width:380px;height:560px;z-index:2147483646;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.25);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}',
    '.aw-container iframe{width:100%;height:100%;border:none}',
    '.aw-toggle{position:fixed;bottom:20px;right:20px;padding:12px 20px;background:#e94560;color:#fff;border:none;border-radius:24px;font-size:14px;cursor:pointer;box-shadow:0 4px 12px rgba(233,69,96,0.4);z-index:2147483647;transition:transform 0.2s,opacity 0.2s;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;line-height:1.4}',
    '.aw-toggle:hover{opacity:0.9}',
  ].join('\n');
  shadow.appendChild(shadowStyle);

  // Container & iframe
  var container = document.createElement('div');
  container.className = 'aw-container';
  container.style.display = 'none';

  var iframe = document.createElement('iframe');
  iframe.src = baseUrl + '/widget?tenant_id=' + encodeURIComponent(tenantId);
  iframe.title = 'AgentOS Chat';
  iframe.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups');
  container.appendChild(iframe);
  shadow.appendChild(container);

  // Toggle button
  var toggleBtn = document.createElement('button');
  toggleBtn.className = 'aw-toggle';
  toggleBtn.textContent = '💬 护肤顾问'; // 💬 护肤顾问
  shadow.appendChild(toggleBtn);

  var isOpen = false;
  toggleBtn.addEventListener('click', function () {
    isOpen = !isOpen;
    if (isOpen) {
      container.style.display = '';
      toggleBtn.style.opacity = '0';
      toggleBtn.style.pointerEvents = 'none';
    } else {
      container.style.display = 'none';
      toggleBtn.style.opacity = '1';
      toggleBtn.style.pointerEvents = 'auto';
    }
  });

  // postMessage from iframe
  window.addEventListener('message', function (event) {
    if (event.origin !== baseUrl) return;
    var d = event.data;
    if (d && d.type === 'WIDGET_CLOSE') {
      isOpen = false;
      container.style.display = 'none';
      toggleBtn.style.opacity = '1';
      toggleBtn.style.pointerEvents = 'auto';
    }
    if (d && d.type === 'WIDGET_RESIZE' && d.height) {
      container.style.height = Math.min(d.height, 800) + 'px';
    }
  });

  document.body.appendChild(host);
})();
