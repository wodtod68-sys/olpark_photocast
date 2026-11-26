// 가짜 데이터. 모델 출력이 정해지기 전까지 화면을 채우는 용도이고, api.ts 밖에서는 쓰지 않는다.
import { CROWD_LEVELS, type CrowdLevel, type Forecast, type Spot } from './types';

const PHOTO_CREDIT = '한국관광재단 · 공공누리 제1유형';
// 1·2·3·5·7경 사진 출처: 한국체육산업개발 올림픽공원 9경 소개 (https://www.ksponco.or.kr/olympicpark/olpark9/view.html)
const NEW_PHOTO_CREDIT = '한국체육산업개발';

// 올림픽공원 9경. no = 몇 경인지. 지도 좌표는 ParkMap(안내 지도) 픽셀
export const MOCK_SPOTS: Spot[] = [
  {
    // 지도 위치: 안내 지도에 인쇄된 1경 핀 자리
    id: 'peace_plaza',
    no: 1,
    name: '세계평화의문',
    scene: '1경',
    description: '서울올림픽을 기념해 세운 문. 넓은 광장 끝에 선 양 날개 밑면의 화려한 벽화와 가운데 오륜 마크가 보인다.',
    photo: { src: 'images/peace_plaza.jpg', position: '50% 50%', credit: NEW_PHOTO_CREDIT },
    map: { x: 338, y: 1451 },
  },
  {
    // 지도 위치: 안내 지도에 인쇄된 2경 핀은 남서쪽(641, 1563)이지만, 동쪽이라는 위치 정보를 따랐다.
    // 공원 지도(OSM)의 2번 위치를 동쪽 경치(4·7·8·9경)로 맞춘 변환식으로 옮긴 값
    id: 'thumb',
    no: 2,
    name: '엄지손가락',
    scene: '2경',
    description: '잔디 원형 화단 위에 거대한 엄지손가락 조각이 서 있다. 뒤로 가로수 길이 곧게 이어진다.',
    photo: { src: 'images/thumb.jpg', position: '50% 50%', credit: NEW_PHOTO_CREDIT },
    map: { x: 2081, y: 914 },
  },
  {
    // 지도 위치: 안내 지도에 인쇄된 3경 핀 자리
    id: 'mongchon_lake',
    no: 3,
    name: '몽촌해자',
    scene: '3경',
    description: '몽촌토성을 둘러싼 물길. 분수가 솟는 수면에 건너편 건물과 국기 광장이 비친다.',
    photo: { src: 'images/mongchon_lake.jpg', position: '68% 50%', credit: NEW_PHOTO_CREDIT },
    map: { x: 831, y: 1384 },
  },
  {
    // 지도 위치: 안내 지도에 인쇄된 4경 핀 자리
    id: 'gyeong4',
    no: 4,
    name: '대화',
    scene: '4경',
    description: '잔디 광장 한가운데 콘크리트 기둥 두 개 위로 녹슨 금속판이 얹힌 조형물. 돌길이 조형물로 곧게 이어진다.',
    photo: { src: 'images/gyeong4.jpg', position: '50% 45%', credit: '직접 촬영 (2026-11-22)' },
    map: { x: 1056, y: 1330 },
  },
  {
    // 지도 위치: 안내 지도에 인쇄된 5경 핀 자리
    id: 'toseong_trail',
    no: 5,
    name: '몽촌토성 산책로',
    scene: '5경',
    description: '몽촌토성 능선을 따라 난 산책로. 잔디 언덕 너머로 몽촌해자와 도시 풍경이 내려다보인다.',
    photo: { src: 'images/toseong_trail.jpg', position: '72% 50%', credit: NEW_PHOTO_CREDIT },
    map: { x: 840, y: 1140 },
  },
  {
    id: 'naholo',
    no: 6,
    name: '나홀로나무',
    scene: '6경',
    description:
      '몽촌토성 잔디 언덕에 홀로 선 나무. 능선과 하늘만 들어와 구도가 단순하고, 영화·광고 배경으로 자주 쓰인다.',
    photo: { src: 'images/naholo.jpg', position: '50% 62%', credit: PHOTO_CREDIT },
    map: { x: 536, y: 548 },
  },
  {
    // 지도 위치: 안내 지도에 인쇄된 7경 핀 자리
    id: 'lake88',
    no: 7,
    name: '88호수 팔각정',
    scene: '7경',
    description: '숲으로 둘러싸인 88호수 건너편에 팔각정이 선다. 바람이 없는 날에는 수면에 숲과 정자가 비친다.',
    photo: { src: 'images/lake88.jpg', position: '59% 50%', credit: NEW_PHOTO_CREDIT },
    map: { x: 1234, y: 497 },
  },
  {
    id: 'wild',
    no: 8,
    name: '들꽃마루길',
    scene: '8경',
    description: '언덕 위 정자를 향해 오르는 길 양옆으로 들꽃이 이어진다. 꽃이 핀 계절에 촬영객이 몰린다.',
    photo: { src: 'images/wild.jpg', position: '50% 38%', credit: PHOTO_CREDIT },
    map: { x: 1900, y: 1530 },
  },
  {
    id: 'rose',
    no: 9,
    name: '장미광장',
    scene: '9경',
    description:
      '흰 기둥의 원형 정자 앞으로 장미 화단이 펼쳐진다. 5~6월 개화기에 가장 붐비고, 그 밖의 계절에는 한산하다.',
    photo: { src: 'images/rose.jpg', position: '50% 45%', credit: PHOTO_CREDIT },
    map: { x: 2262, y: 1545 },
  },
];

// ── 가짜 행사 일정 ─────────────────────────────────────────────
const EVENTS: { date: string; hour: number; title: string }[] = [
  { date: '2026-11-21', hour: 19, title: 'KSPO DOME 공연' },
  { date: '2026-11-22', hour: 17, title: 'KSPO DOME 공연' },
  { date: '2026-11-27', hour: 19, title: 'KSPO DOME 공연' },
  { date: '2026-11-28', hour: 18, title: 'KSPO DOME 공연' },
  { date: '2026-11-29', hour: 17, title: 'KSPO DOME 공연' },
  { date: '2026-12-05', hour: 19, title: 'KSPO DOME 공연' },
  { date: '2026-12-06', hour: 16, title: 'KSPO DOME 공연' },
];
// 공연 시작 시각 기준 앞뒤 시간의 인파 증가량
const EVENT_RAMP: Record<number, number> = { [-3]: 8, [-2]: 16, [-1]: 26, 0: 22, 1: 10 };

// 스팟별 성향
const SPOT_TRAITS: Record<string, { base: number; event: number }> = {
  naholo: { base: 1.0, event: 0.3 },
  wild: { base: 0.8, event: 0.5 },
  rose: { base: 0.75, event: 0.9 },
  gyeong4: { base: 0.7, event: 0.4 },
  peace_plaza: { base: 0.8, event: 0.4 },
  thumb: { base: 0.7, event: 0.6 },
  mongchon_lake: { base: 0.8, event: 0.4 },
  toseong_trail: { base: 0.8, event: 0.3 },
  lake88: { base: 0.7, event: 0.5 },
};

// 시간대별 기본 인파 (06~21시)
const HOUR_CURVE: Record<number, number> = {
  6: 8, 7: 12, 8: 16, 9: 22, 10: 30, 11: 38, 12: 45, 13: 50,
  14: 55, 15: 58, 16: 58, 17: 52, 18: 44, 19: 36, 20: 26, 21: 18,
};

// 서울 월별 대략 일출·일몰 시각 (시 단위)
const SUNRISE = [7.7, 7.3, 6.7, 6.0, 5.4, 5.2, 5.4, 5.8, 6.2, 6.6, 7.1, 7.6];
const SUNSET = [17.6, 18.1, 18.6, 19.0, 19.4, 19.9, 19.9, 19.5, 18.9, 18.2, 17.5, 17.3];

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

function parse(datetime: string) {
  const [date, time] = datetime.split('T');
  const [y, m, d] = date.split('-').map(Number);
  const hour = Number(time.slice(0, 2));
  const dow = new Date(y, m - 1, d).getDay();
  return { date, y, m, d, hour, dow };
}

// 같은 입력이면 항상 같은 값 (0~1)
function hash(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0) / 4294967295;
}

function levelOf(score: number): CrowdLevel {
  let level = CROWD_LEVELS[0].level;
  for (const l of CROWD_LEVELS) if (score >= l.min) level = l.level;
  return level;
}

function crowd(spotId: string, datetime: string) {
  const { date, m, hour, dow } = parse(datetime);
  const traits = SPOT_TRAITS[spotId];
  const weekend = dow === 0 || dow === 6;

  let score = HOUR_CURVE[hour] * traits.base;
  if (weekend) score *= 1.25;
  else if (dow === 5 && hour >= 17) score *= 1.15;

  // 가장 크게 작용한 요인을 근거로 쓴다
  const factors: { amount: number; reason: string }[] = [];

  const event = EVENTS.find((e) => e.date === date && EVENT_RAMP[hour - e.hour] !== undefined);
  if (event) {
    const amount = EVENT_RAMP[hour - event.hour] * traits.event;
    factors.push({ amount, reason: `${String(event.hour).padStart(2, '0')}:00 ${event.title}` });
  }
  if (spotId === 'naholo' && weekend && hour >= 13 && hour <= 17) {
    factors.push({ amount: 10, reason: '주말 오후 스냅 촬영 집중' });
  }
  if (spotId === 'rose' && (m === 5 || m === 6)) {
    factors.push({ amount: score * 0.45, reason: '장미 개화기 방문객 증가' });
  }

  for (const f of factors) score += f.amount;
  score += (hash(spotId + datetime) - 0.5) * 8;
  score = Math.round(Math.min(100, Math.max(0, score)));

  const top = factors.sort((a, b) => b.amount - a.amount)[0];
  const reason = top && top.amount >= 8 ? top.reason : generalReason(weekend, dow, hour);
  return { score, level: levelOf(score), reason };
}

function generalReason(weekend: boolean, dow: number, hour: number) {
  if (weekend) {
    if (hour < 10) return '주말 이른 오전, 산책객 위주';
    if (hour <= 17) return `${WEEKDAYS[dow]}요일 ${hour < 12 ? '오전' : '오후'} 나들이객 집중`;
    return '주말 저녁, 방문객이 빠지는 시간';
  }
  if (hour < 11) return '평일 오전, 산책객 위주';
  if (hour <= 17) return '평일 낮, 인근 직장인·산책객';
  return '평일 저녁, 퇴근 후 산책객';
}

// ── placeholder 이미지 ─────────────────────────────────────────
// 시간대 색감의 단색 면 두 개 + 스팟 실루엣 + 텍스트. 실제 이미지가 생기면 public/images/ 경로로 바꾼다.
const TONES = {
  night: { sky: '#24282C', ground: '#141514', shape: '#0B0C0B' },
  dawn: { sky: '#8A9198', ground: '#3B3D36', shape: '#2A2B26' },
  morning: { sky: '#CDD3CC', ground: '#6A7254', shape: '#4E553E' },
  day: { sky: '#DCDFD6', ground: '#636B4B', shape: '#474D35' },
  golden: { sky: '#E2A266', ground: '#5A432E', shape: '#3A2A1C' },
  blue: { sky: '#56606B', ground: '#23252A', shape: '#15161A' },
};

function toneOf(m: number, hour: number) {
  const rise = SUNRISE[m - 1];
  const set = SUNSET[m - 1];
  if (hour < rise - 0.5 || hour >= set + 1) return TONES.night;
  if (hour < rise + 1) return TONES.dawn;
  if (hour >= set) return TONES.blue;
  if (hour >= set - 1.5) return TONES.golden;
  if (hour < rise + 3) return TONES.morning;
  return TONES.day;
}

// 1200×900, 지평선 y=520
const MOTIFS: Record<string, (t: typeof TONES.day) => string> = {
  naholo: (t) => `
    <path d="M0 560 Q600 400 1200 560 L1200 900 L0 900Z" fill="${t.ground}"/>
    <rect x="693" y="330" width="16" height="130" fill="${t.shape}"/>
    <circle cx="701" cy="300" r="118" fill="${t.shape}"/>`,
  wild: (t) => `
    <path d="M0 540 Q500 470 1200 560 L1200 900 L0 900Z" fill="${t.ground}"/>
    <path d="M520 400 L880 400 L850 424 L550 424Z" fill="${t.shape}"/>
    <rect x="590" y="424" width="14" height="110" fill="${t.shape}"/>
    <rect x="796" y="424" width="14" height="110" fill="${t.shape}"/>`,
  rose: (t) => `
    <ellipse cx="600" cy="660" rx="430" ry="80" fill="none" stroke="${t.shape}" stroke-width="4"/>
    <g fill="${t.shape}">${Array.from({ length: 13 }, (_, i) => {
      const a = (i / 13) * Math.PI;
      return `<circle cx="${600 + Math.cos(a) * 430}" cy="${660 - Math.sin(a) * 80}" r="26"/>`;
    }).join('')}</g>`,
  gyeong4: (t) => `
    <rect x="540" y="250" width="50" height="280" fill="${t.shape}"/>
    <rect x="610" y="250" width="50" height="280" fill="${t.shape}"/>
    <path d="M530 250 L590 150 L610 150 L670 250Z" fill="${t.shape}"/>`,
  peace_plaza: (t) => `
    <rect x="520" y="250" width="50" height="270" fill="${t.shape}"/>
    <rect x="630" y="250" width="50" height="270" fill="${t.shape}"/>
    <path d="M300 230 L570 230 L570 250 L380 330Z" fill="${t.shape}"/>
    <path d="M900 230 L630 230 L630 250 L820 330Z" fill="${t.shape}"/>`,
  thumb: (t) => `
    <ellipse cx="600" cy="530" rx="200" ry="30" fill="${t.ground}"/>
    <rect x="545" y="230" width="110" height="300" rx="55" fill="${t.shape}"/>`,
  mongchon_lake: (t) => `
    <rect y="470" width="1200" height="60" fill="${t.ground}" opacity="0.6"/>
    <path d="M560 470 Q575 330 590 470Z M660 470 Q680 290 700 470Z" fill="${t.shape}"/>`,
  toseong_trail: (t) => `
    <path d="M0 560 Q450 360 1200 500 L1200 900 L0 900Z" fill="${t.ground}"/>
    <path d="M820 420 Q900 520 1020 640" fill="none" stroke="${t.shape}" stroke-width="14"/>`,
  lake88: (t) => `
    <rect y="470" width="1200" height="60" fill="${t.ground}" opacity="0.6"/>
    <path d="M540 400 L600 350 L660 400Z" fill="${t.shape}"/>
    <rect x="565" y="400" width="70" height="70" fill="${t.shape}"/>`,
};

function placeholder(spot: Spot, datetime: string) {
  const { y, m, d, hour, dow } = parse(datetime);
  const t = toneOf(m, hour);
  const when = `${y}. ${m}. ${d}. (${WEEKDAYS[dow]}) ${String(hour).padStart(2, '0')}:00`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900" width="1200" height="900">
    <rect width="1200" height="520" fill="${t.sky}"/>
    <rect y="520" width="1200" height="380" fill="${t.ground}"/>
    ${MOTIFS[spot.id](t)}
    <g font-family="'Noto Serif KR','Nanum Myeongjo',serif" fill="#F3EEE4" text-anchor="middle">
      <text x="600" y="740" font-size="64" font-weight="700">${spot.name}</text>
      <text x="600" y="792" font-size="30" font-family="sans-serif">${when}</text>
      <text x="600" y="840" font-size="22" font-family="monospace" opacity="0.7">PLACEHOLDER</text>
    </g>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export function mockForecast(spotId: string, datetime: string): Forecast {
  const spot = MOCK_SPOTS.find((s) => s.id === spotId);
  if (!spot) throw new Error(`알 수 없는 스팟: ${spotId}`);
  return {
    spotId,
    datetime,
    image: { src: placeholder(spot, datetime), alt: `${spot.name} 예상 배경 (자리표시 이미지)` },
    crowd: crowd(spotId, datetime),
  };
}
