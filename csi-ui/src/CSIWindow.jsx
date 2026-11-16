import React, {useLayoutEffect, useRef, useState} from 'react';
import {Rnd} from 'react-rnd';
import {motion, useReducedMotion} from 'motion/react';

const clamp = (value, lower, upper) => Math.min(Math.max(Number(value) || 0, lower), Math.max(lower, upper));

/** A view-only, bounded floating window. Persistence belongs to the caller. */
export default function CSIWindow({id, title, icon, status = 'waiting', rect,
  focused = false, updated = false, compact = false, zIndex = 1, children,
  onFocus, onRectChange, onClose, onMinimize}) {
  const host = useRef(null);
  const reduced = useReducedMotion();
  const [bounds, setBounds] = useState({width: window.innerWidth, height: window.innerHeight});
  useLayoutEffect(() => {
    if (!host.current) return undefined;
    const measure = () => {
      const {width, height} = host.current.getBoundingClientRect();
      setBounds(previous => previous.width === width && previous.height === height ? previous : {width, height});
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);

  const availableWidth = Math.max(1, bounds.width);
  const availableHeight = Math.max(1, bounds.height);
  const minWidth = Math.min(240, availableWidth);
  const minHeight = Math.min(170, availableHeight);
  const width = compact ? Math.max(1, availableWidth - 16) : clamp(rect?.width || 360, minWidth, availableWidth);
  const height = compact ? Math.max(1, availableHeight - 16) : clamp(rect?.height || 300, minHeight, availableHeight);
  const position = compact ? {x: Math.min(8, availableWidth - width), y: Math.min(8, availableHeight - height)} : {
    x: clamp(rect?.x || 0, 0, availableWidth - width), y: clamp(rect?.y || 0, 0, availableHeight - height)
  };
  const save = next => onRectChange?.({x: clamp(next.x, 0, availableWidth - next.width),
    y: clamp(next.y, 0, availableHeight - next.height), width: next.width, height: next.height});
  const keyMove = event => {
    if (compact || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    // Only the title bar itself is a movement handle; native child controls
    // keep their ordinary keyboard interaction.
    if (event.target !== event.currentTarget) return;
    event.preventDefault(); onFocus?.();
    const step = event.altKey ? 1 : 16;
    const dx = event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0;
    const dy = event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0;
    if (event.shiftKey) save({x: position.x, y: position.y,
      width: clamp(width + dx, minWidth, availableWidth - position.x),
      height: clamp(height + dy, minHeight, availableHeight - position.y)});
    else save({...position, x: position.x + dx, y: position.y + dy, width, height});
  };
  const statusText = String(status || 'waiting');
  const statusClass = /^(?:no|0) warnings?$/i.test(statusText) ? 'cy-status--online' : /fail|block|error|warning|cancel/i.test(statusText) ? 'cy-status--alert' :
    /paus|waiting|pending|review|queue|backlog/i.test(statusText) ? 'cy-status--away' : 'cy-status--online';

  return <motion.div ref={host} className="csi-window-layer"
    style={{position: 'absolute', inset: 0, pointerEvents: 'none', zIndex}}
    initial={reduced ? false : {opacity: 0, y: 10}}
    animate={{opacity: 1, y: 0}}
    exit={reduced ? {opacity: 0} : {opacity: 0, y: 8}}
    transition={{duration: reduced ? 0 : 0.18}}>
    <Rnd bounds="parent" size={{width, height}} position={position}
      minWidth={minWidth} minHeight={minHeight} maxWidth={availableWidth} maxHeight={availableHeight}
      disableDragging={compact} enableResizing={!compact}
      dragHandleClassName="csi-window-handle"
      cancel=".csi-window-controls,button,input,textarea,select,a,.nodrag"
      resizeHandleComponent={{bottomRight: <span className="csi-resize-handle" data-csi-resize={id} aria-hidden="true"/>}}
      className={`csi-window-shell${focused ? ' is-focused' : ''}${updated ? ' has-update' : ''}`}
      style={{pointerEvents: 'auto'}}
      onDragStart={() => onFocus?.()}
      onResizeStart={() => onFocus?.()}
      onDragStop={(_, data) => save({x: data.x, y: data.y, width, height})}
      onResizeStop={(_, __, element, ___, next) => save({...next,
        width: element.offsetWidth, height: element.offsetHeight})}>
      <section className="csi-window-panel cy-hud-card" data-csi-window={id}
        data-focused={focused ? 'true' : 'false'} aria-labelledby={`csi-title-${id}`}
        onPointerDown={() => onFocus?.()} onFocusCapture={() => onFocus?.()}>
        <header className="csi-window-handle" tabIndex={0} onKeyDown={keyMove}
          title={compact ? title : 'Drag to move. Arrow keys move; Shift + arrows resize.'}>
          <span className="csi-window-icon" aria-hidden="true">{icon || '◇'}</span>
          <h2 id={`csi-title-${id}`}>{title}</h2>
          <span className="csi-window-controls">
            <button type="button" aria-label={`Minimize ${title}`} title="Minimize" data-csi-minimize={id}
              onClick={() => onMinimize?.()}>−</button>
            <button type="button" aria-label={`Close ${title}`} title="Close" data-csi-close={id}
              onClick={() => onClose?.()}>×</button>
          </span>
        </header>
        <div className="csi-window-meta">
          <span className={`cy-status ${statusClass}`}>{statusText.replaceAll('_', ' ')}</span>
          <span className="csi-window-updated" role="status">{updated ? 'NEW DATA' : 'PAPERCLIP RECORD'}</span>
        </div>
        <div className="csi-window-content">{children}</div>
        {!compact && <span className="csi-resize-corner" aria-hidden="true"/>}
      </section>
    </Rnd>
  </motion.div>;
}
