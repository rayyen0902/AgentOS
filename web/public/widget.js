(function () {
  'use strict';

  var scriptTag = document.currentScript;
  if (!scriptTag) return;

  var tenantId = scriptTag.getAttribute('data-tenant-id');
  if (!tenantId) {
    console.error('[AgentOS Widget] data-tenant-id is required');
    return;
  }

  var baseUrl = 'https://hufu.cn';

  // Create iframe
  var container = document.createElement('div');
  container.style.cssText = 'position:fixed;bottom:20px;right:20px;width:380px;height:560px;z-index:9999;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.25);';

  var iframe = document.createElement('iframe');
  iframe.src = baseUrl + '/widget?tenant_id=' + encodeURIComponent(tenantId);
  iframe.style.cssText = 'width:100%;height:100%;border:none;';
  iframe.title = 'AgentOS Chat';

  // Toggle button
  var toggleBtn = document.createElement('button');
  toggleBtn.textContent = '💬 护肤顾问';
  toggleBtn.style.cssText = 'position:fixed;bottom:20px;right:20px;padding:12px 20px;background:#e94560;color:#fff;border:none;border-radius:24px;font-size:14px;cursor:pointer;box-shadow:0 4px 12px rgba(233,69,96,0.4);z-index:9998;transition:transform 0.2s,opacity 0.2s;';

  var isOpen = false;
  toggleBtn.addEventListener('click', function () {
    isOpen = !isOpen;
    if (isOpen) {
      document.body.appendChild(container);
      container.appendChild(iframe);
      toggleBtn.style.opacity = '0';
      toggleBtn.style.pointerEvents = 'none';
    } else {
      if (container.parentNode) container.parentNode.removeChild(container);
      toggleBtn.style.opacity = '1';
      toggleBtn.style.pointerEvents = 'auto';
    }
  });

  // Listen for postMessage from iframe (close, resize, etc.)
  window.addEventListener('message', function (event) {
    if (event.origin !== baseUrl) return;
    if (event.data?.type === 'WIDGET_CLOSE') {
      isOpen = false;
      if (container.parentNode) container.parentNode.removeChild(container);
      toggleBtn.style.opacity = '1';
      toggleBtn.style.pointerEvents = 'auto';
    }
    if (event.data?.type === 'WIDGET_RESIZE' && event.data.height) {
      container.style.height = Math.min(event.data.height, 800) + 'px';
    }
  });

  document.body.appendChild(toggleBtn);
})();
