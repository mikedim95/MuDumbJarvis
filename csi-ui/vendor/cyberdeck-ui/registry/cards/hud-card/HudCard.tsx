import type { ReactNode } from 'react';
import './hud-card.css';

interface Props {
  title: string;
  children: ReactNode;
  /** Shown top-left as "[ 01 ]". */
  index?: number;
  tags?: string[];
  href?: string;
  linkLabel?: string;
}

export function HudCard({ title, children, index, tags = [], href, linkLabel = 'Open' }: Props) {
  return (
    <article className='cy-hud-card'>
      <header className='cy-hud-card__header'>
        <span className='cy-hud-card__index'>
          {index !== undefined && `[ ${String(index).padStart(2, '0')} ]`}
        </span>
        {href && (
          <a className='cy-hud-card__link' href={href} aria-label={linkLabel}>
            <svg viewBox='0 0 24 24' width='18' height='18' fill='none' stroke='currentColor' strokeWidth='2' strokeLinecap='round' strokeLinejoin='round' aria-hidden='true'>
              <path d='M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6' /><path d='M15 3h6v6' /><path d='M10 14 21 3' />
            </svg>
          </a>
        )}
      </header>
      <h3 className='cy-hud-card__title'>{title}</h3>
      <p className='cy-hud-card__body'>{children}</p>
      {tags.length > 0 && (
        <ul className='cy-hud-card__tags'>
          {tags.map((tag) => <li key={tag}>{tag}</li>)}
        </ul>
      )}
    </article>
  );
}
