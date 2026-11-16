import type { ReactNode } from 'react';
import './status-badge.css';

type Status = 'online' | 'away' | 'offline' | 'alert';

interface Props {
  status: Status;
  /** Defaults to the status name. */
  children?: ReactNode;
}

export function StatusBadge({ status, children = status }: Props) {
  return <span className={`cy-status cy-status--${status}`}>{children}</span>;
}
