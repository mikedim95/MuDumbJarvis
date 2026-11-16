import './profile-card.css';

type Status = 'online' | 'away' | 'offline';

interface Props {
  name: string;
  role: string;
  initials: string;
  status?: Status;
  stats?: { label: string; value: string }[];
}

const STATUS_LABELS: Record<Status, string> = {
  online: 'Online',
  away: 'Away',
  offline: 'Offline',
};

export function ProfileCard({ name, role, initials, status = 'offline', stats = [] }: Props) {
  return (
    <article className='cy-profile'>
      <div className='cy-profile__avatar'>
        <span className='cy-profile__initials' aria-hidden='true'>{initials}</span>
        <span className={`cy-profile__status cy-profile__status--${status}`}>
          <span className='cy-sr-only'>{STATUS_LABELS[status]}</span>
        </span>
      </div>
      <div className='cy-profile__info'>
        <h3 className='cy-profile__name'>{name}</h3>
        <p className='cy-profile__role'>{role}</p>
      </div>
      {stats.length > 0 && (
        <dl className='cy-profile__stats'>
          {stats.map((stat) => (
            <div key={stat.label}>
              <dt>{stat.label}</dt>
              <dd>{stat.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  );
}
