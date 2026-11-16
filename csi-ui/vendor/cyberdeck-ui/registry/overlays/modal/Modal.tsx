'use client';

import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';
import './modal.css';

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Buttons for the footer. */
  actions?: ReactNode;
}

export function Modal({ open, onClose, title, children, actions }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className='cy-modal'
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className='cy-modal__inner'>
        <header className='cy-modal__header'>
          <h2 id={titleId}>{title}</h2>
          <button type='button' className='cy-modal__close' aria-label='Close' onClick={onClose}>✕</button>
        </header>
        <div className='cy-modal__body'>{children}</div>
        {actions && <footer className='cy-modal__actions'>{actions}</footer>}
      </div>
    </dialog>
  );
}
