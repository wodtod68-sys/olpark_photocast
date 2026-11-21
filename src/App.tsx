import { useEffect, useState } from 'react';
import { getSpots } from './data/api';
import type { Spot } from './data/types';
import { MapScreen } from './components/MapScreen';
import { PickScreen } from './components/PickScreen';
import { ResultScreen } from './components/ResultScreen';
import { resultHash } from './route';

// 주소
//   #/                               지도
//   #/spot/<id>                      날짜·시간 고르기
//   #/spot/<id>/<YYYY-MM-DD>/<시>     예상 이미지
type Route =
  | { view: 'map' }
  | { view: 'pick'; spotId: string }
  | { view: 'result'; spotId: string; date: string; hour: number };

function readRoute(): Route {
  const m = window.location.hash.match(/^#\/spot\/([\w-]+)(?:\/(\d{4}-\d{2}-\d{2})\/(\d{1,2}))?/);
  if (!m) return { view: 'map' };
  if (m[2]) return { view: 'result', spotId: m[1], date: m[2], hour: Number(m[3]) };
  return { view: 'pick', spotId: m[1] };
}

export function App() {
  const [spots, setSpots] = useState<Spot[]>([]);
  const [route, setRoute] = useState(readRoute);
  const [today] = useState(() => new Date());
  // 고른 날짜·시간은 스팟을 바꿔도 유지한다
  const [date, setDate] = useState<string | null>(null);
  const [hour, setHour] = useState<number | null>(null);

  useEffect(() => {
    getSpots().then(setSpots);
    const onHash = () => setRoute(readRoute());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    if (route.view === 'result') {
      setDate(route.date);
      setHour(route.hour);
    }
    window.scrollTo(0, 0);
  }, [route]);

  const spot = route.view === 'map' ? null : spots.find((s) => s.id === route.spotId);

  if (route.view === 'map' || !spot) return <MapScreen spots={spots} />;

  const choose = (d: string | null, h: number | null) => {
    setDate(d);
    setHour(h);
    // 결과 화면에서 바꾸면 바로 갱신. 뒤로가기 기록은 쌓지 않는다
    if (route.view === 'result') {
      if (d && h !== null) window.location.replace(resultHash(spot.id, d, h));
      else window.location.hash = `#/spot/${spot.id}`;
    }
  };

  if (route.view === 'pick') {
    return <PickScreen spot={spot} today={today} date={date} hour={hour} onChange={choose} />;
  }
  return <ResultScreen spot={spot} today={today} date={route.date} hour={route.hour} onChange={choose} />;
}
