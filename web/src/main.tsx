import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

console.info(`[AgentOS] env=${import.meta.env.VITE_ENV || 'development'}`);

// Register Service Worker for PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(
      (reg) => {
        console.log('SW registered:', reg.scope);

        // Listen for updates
        reg.addEventListener('updatefound', () => {
          const installing = reg.installing;
          if (!installing) return;
          installing.addEventListener('statechange', () => {
            if (installing.state === 'installed' && navigator.serviceWorker.controller) {
              // New version available
              const update = window.confirm('有新版本可用，是否刷新？');
              if (update) {
                window.location.reload();
              }
            }
          });
        });
      },
      (err) => {
        console.warn('SW registration failed:', err);
      }
    );

    // Detect controller change (skipWaiting activated)
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      console.log('SW controller changed');
    });
  });
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
