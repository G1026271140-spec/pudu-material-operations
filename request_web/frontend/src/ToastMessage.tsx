import { Children, isValidElement, useLayoutEffect, useRef, useState } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import './toast-message.css';

function signature(value: ReactNode): string {
  return Children.toArray(value).map(child => isValidElement<{ children?: ReactNode }>(child) ? signature(child.props.children) : String(child)).join('');
}
export default function ToastMessage({ children, className = '', role = 'status', ...props }: HTMLAttributes<HTMLDivElement>) {
  const marker = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState('');
  const content = signature(children);
  useLayoutEffect(() => {
    const update = () => setVisible(!marker.current?.parentElement?.closest('[hidden]'));
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.body, { attributes: true, subtree: true, attributeFilter: ['hidden'] });
    return () => observer.disconnect();
  }, []);
  let host = document.getElementById('global-toast-stack');
  if (!host) { host = document.createElement('div'); host.id = 'global-toast-stack'; host.setAttribute('popover', 'manual'); host.setAttribute('aria-label', document.documentElement.lang.startsWith('zh') ? '操作提示' : 'Notifications'); document.body.appendChild(host); }
  useLayoutEffect(() => {
    if (visible && dismissed !== content && host && typeof host.showPopover === 'function') {
      if (host.matches(':popover-open')) host.hidePopover();
      host.showPopover();
    }
  }, [visible, dismissed, content, host]);
  return <><span ref={marker} hidden />{visible && dismissed !== content && createPortal(<div {...props} className={`global-toast ${className}`} role={role} aria-live={role === 'alert' ? 'assertive' : 'polite'}>
    <div className="global-toast-content">{children}</div><button type="button" className="global-toast-close" aria-label="关闭提示 / Dismiss notification" onClick={event => { event.stopPropagation(); setDismissed(content); }}>×</button>
  </div>, host)}</>;
}
