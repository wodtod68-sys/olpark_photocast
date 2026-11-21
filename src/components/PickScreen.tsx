import type { Spot } from '../data/types';
import { resultHash } from '../route';
import { TopBar } from './TopBar';
import { WhenPicker } from './WhenPicker';
import styles from './PickScreen.module.css';

interface Props {
  spot: Spot;
  today: Date;
  date: string | null;
  hour: number | null;
  onChange: (date: string | null, hour: number | null) => void;
}

export function PickScreen({ spot, today, date, hour, onChange }: Props) {
  const ready = date !== null && hour !== null;
  return (
    <>
      <TopBar back="#/" backLabel="지도" />
      <div className={styles.stage}>
        <figure className={styles.figure}>
          <img
            className={styles.photo}
            src={`${import.meta.env.BASE_URL}${spot.photo.src}`}
            alt={`${spot.name} 사진`}
            style={{ objectPosition: spot.photo.position }}
          />
          <figcaption className={styles.credit}>사진 출처: {spot.photo.credit}</figcaption>
        </figure>
        <main className={styles.page}>
          <header className={styles.head}>
            <span className={`spot-no ${styles.no}`}>{spot.no}</span>
            <h1 className={styles.name}>{spot.name}</h1>
            <p className={styles.desc}>{spot.description}</p>
          </header>

          <WhenPicker today={today} date={date} hour={hour} onChange={onChange} />

          {ready ? (
            <a className={styles.go} href={resultHash(spot.id, date, hour)}>
              예상 이미지 보기 →
            </a>
          ) : (
            <p className={`${styles.go} ${styles.waiting}`}>
              {date === null && hour === null ? '날짜와 시간을 고르세요' : date === null ? '날짜를 고르세요' : '시간을 고르세요'}
            </p>
          )}
        </main>
      </div>
    </>
  );
}
