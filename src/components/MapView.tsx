import type { Spot } from '../data/types';
import { MAP_SIZE, ParkMap } from '../map/ParkMap';
import styles from './MapView.module.css';

// 지도 전체를 보여주고 그 위에 번호 마커를 HTML로 올린다.
// 폰(세로)은 화면 폭에, 가로 화면은 화면 높이에 맞춘다.
export function MapView({ spots }: { spots: Spot[] }) {
  return (
    <div className={styles.scroller}>
      <div className={styles.map}>
        <ParkMap className={styles.image} />
        {spots.map((s) => (
          <a
            key={s.id}
            href={`#/spot/${s.id}`}
            className={styles.marker}
            style={{
              left: `${(s.map.x / MAP_SIZE.width) * 100}%`,
              top: `${(s.map.y / MAP_SIZE.height) * 100}%`,
            }}
            aria-label={`${s.no}번 ${s.name}`}
          >
            <span className={styles.dot}>{s.no}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
