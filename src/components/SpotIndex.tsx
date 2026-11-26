import type { Spot } from '../data/types';
import styles from './SpotIndex.module.css';

// 지도 아래 스팟 목록. 사진으로 어떤 곳인지 바로 보이게 한다
export function SpotIndex({ spots }: { spots: Spot[] }) {
  return (
    <section className={styles.wrap}>
      <ol className={styles.index}>
        {spots.map((s) => (
          <li key={s.id}>
            <a href={`#/spot/${s.id}`} className={styles.row}>
              <img
                className={styles.thumb}
                src={`${import.meta.env.BASE_URL}${s.photo.src}`}
                alt=""
                style={{ objectPosition: s.photo.position }}
              />
              <span className="spot-no">{s.no}</span>
              <span className={styles.name}>{s.name}</span>
            </a>
          </li>
        ))}
      </ol>
      {spots.length > 0 && (
        <p className={styles.credit}>사진 출처: {[...new Set(spots.map((s) => s.photo.credit))].join(' / ')}</p>
      )}
    </section>
  );
}
