import { CROWD_LEVELS, type Forecast } from '../data/types';
import styles from './CrowdReading.module.css';

// 4단계는 색이 아니라 숫자, 라벨, 눈금 위치로 구분한다
export function CrowdReading({ crowd }: { crowd: Forecast['crowd'] }) {
  return (
    <section className={styles.crowd} aria-label="혼잡도">
      <h2 className="label">혼잡도</h2>
      <p className={styles.reading}>
        <span className={`num ${styles.score}`}>{crowd.score}</span>
        <span className={`num ${styles.outof}`}>/100</span>
        <span className={styles.level}>{crowd.level}</span>
      </p>

      <div className={styles.scale} aria-hidden="true">
        <span className={styles.pointer} style={{ left: `${crowd.score}%` }} />
        {CROWD_LEVELS.map((l, i) => {
          const max = CROWD_LEVELS[i + 1]?.min ?? 100;
          return (
            <div
              key={l.level}
              className={styles.step}
              style={{ flexGrow: max - l.min }}
              data-current={l.level === crowd.level || undefined}
            >
              <span className={styles.bar} />
              <span className={styles.stepLabel}>{l.level}</span>
            </div>
          );
        })}
      </div>

      <p className={styles.reason}>
        <span className="label">근거</span>
        <span>{crowd.reason}</span>
      </p>
    </section>
  );
}
