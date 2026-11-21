import styles from './WhenPicker.module.css';

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];
const HOURS = Array.from({ length: 16 }, (_, i) => i + 6); // 06~21시
const DAYS_AHEAD = 7; // 오늘부터 1주일 뒤까지

function dateKey(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// 오늘이면 이미 지난 시각은 고를 수 없다
function isPastHour(today: Date, date: string, hour: number) {
  return date === dateKey(today) && hour < today.getHours();
}

interface Props {
  today: Date;
  date: string | null;
  hour: number | null;
  onChange: (date: string | null, hour: number | null) => void;
}

export function WhenPicker({ today, date, hour, onChange }: Props) {
  const days = Array.from({ length: DAYS_AHEAD + 1 }, (_, i) => {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i);
    return { key: dateKey(d), day: d.getDate(), month: d.getMonth() + 1, dow: d.getDay(), isToday: i === 0 };
  });

  const pickDate = (key: string) => {
    onChange(key, hour !== null && isPastHour(today, key, hour) ? null : hour);
  };

  return (
    <div className={styles.picker}>
      <fieldset>
        <legend className={`label ${styles.legend}`}>날짜</legend>
        <div className={styles.grid}>
          {days.map((d) => (
            <button
              key={d.key}
              type="button"
              className={styles.cell}
              aria-pressed={date === d.key}
              aria-label={`${d.month}월 ${d.day}일 ${WEEKDAYS[d.dow]}요일`}
              onClick={() => pickDate(d.key)}
            >
              <span className={styles.sub}>{d.isToday ? '오늘' : WEEKDAYS[d.dow]}</span>
              <span className={`num ${styles.big}`}>{d.day}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className={`label ${styles.legend}`}>시간</legend>
        <div className={styles.grid}>
          {HOURS.map((h) => {
            const past = date !== null && isPastHour(today, date, h);
            return (
              <button
                key={h}
                type="button"
                className={styles.cell}
                aria-pressed={hour === h}
                aria-label={`${h}시`}
                disabled={past}
                onClick={() => onChange(date, h)}
              >
                <span className={`num ${styles.big}`}>{String(h).padStart(2, '0')}</span>
              </button>
            );
          })}
        </div>
      </fieldset>
    </div>
  );
}
