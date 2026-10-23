import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import Portal from './Portal';
import './styles.css';

// The public origin previously hosted Streamlit. Remove any origin-scoped
// worker/cache left by that client before rendering the replacement frontend,
// so stale tabs cannot keep reviving old /_stcore resources after a refresh.
if ('serviceWorker' in navigator) {
  void navigator.serviceWorker
    .getRegistrations()
    .then((registrations) => Promise.all(registrations.map((item) => item.unregister())));
}
if ('caches' in window) {
  void caches.keys().then((keys) => Promise.all(keys.map((key) => caches.delete(key))));
}

createRoot(document.getElementById('root')!).render(<StrictMode><Portal/></StrictMode>);
