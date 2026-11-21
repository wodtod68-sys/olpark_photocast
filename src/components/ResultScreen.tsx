import { useEffect, useState } from 'react';
import { getForecast } from '../data/api';
import type { Forecast, Spot } from '../data/types';
import { CrowdReading } from './CrowdReading';
import { ForecastImage } from './ForecastImage';
import { TopBar } from './TopBar';
import { WhenPicker } from './WhenPicker';
import styles from './ResultScreen.module.css';

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

interface Props {
  spot: Spot;
  today: Date;
  date: string;
  hour: number;
  onChange: (date: string | null, hour: number | null) => void;
}

export function ResultScreen({ spot, today, date, hour, onChange }: Props) {
  const datetime = `${date}T${String(hour).padStart(2, '0')}:00`;
  const [forecast, setForecast] = useState<Forecast | null>(null);

  useEffect(() => {
    let cancelled = false;
    getForecast(spot.id, datetime).then((f) => {
      if (!cancelled) setForecast(f);
    });
    return () => {
      cancelled = true;
    };
  }, [spot.id, datetime]);

  // 이전 조건의 결과가 잠깐 보이지 않도록 지금 조건과 맞을 때만 쓴다
  const current = forecast && forecast.spotId === spot.id && forecast.datetime === datetime ? forecast : null;

  const [y, m, d] = date.split('-').map(Number);
  const when = `${m}.${d} (${WEEKDAYS[new Date(y, m - 1, d).getDay()]}) ${String(hour).padStart(2, '0')}:00`;

  return (
    <>
      <TopBar back={`#/spot/${spot.id}`} backLabel="날짜·시간">
        <p className={styles.title}>
          <span className={styles.spotName}>{spot.name}</span>
          <span className={`num ${styles.when}`}>{when}</span>
        </p>
      </TopBar>
      <main className={styles.stage}>
        <div className={styles.photo} key={datetime}>
          <ForecastImage
            src={current?.image.src ?? null}
            alt={current?.image.alt ?? ''}
            position={current?.status === 'ready' ? spot.photo.position : undefined}
            summary={current?.summary}
          />
        </div>

        <div className={styles.side}>
          {current && (
            <div key={datetime} className={styles.fade}>
              <CrowdReading crowd={current.crowd} />
            </div>
          )}
          <p className={styles.note}>AI 예상 이미지는 분위기를 보여주는 참고용이며, 실제 촬영 결과와 다를 수 있습니다.</p>
          {current?.status === 'fallback' && current.note && <p className={styles.note}>{current.note}</p>}
          <div className={styles.change}>
            <WhenPicker today={today} date={date} hour={hour} onChange={onChange} />
          </div>
        </div>
      </main>
    </>
  );
}
