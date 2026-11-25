// 화면은 이 두 함수만 부른다. 실제 모델 결과가 오면 이 파일의 구현만 바꾼다.
import type { CrowdLevel, Forecast, Spot } from './types';
import { MOCK_SPOTS, mockForecast } from './mock';

// AI 예상 이미지 서버 주소. 설정돼 있으면 서버를 부른다.
// 개발: 빈 값(VITE_API_BASE=)이면 vite 프록시(/api → localhost:8000)를 탄다.
const API_BASE: string | undefined = import.meta.env.VITE_API_BASE;

export async function getSpots(): Promise<Spot[]> {
  return MOCK_SPOTS;
}

// 혼잡도 엔진(crowd/)이 만든 정적 JSON. public/crowd_forecast.json, 2026-12-01 ~ 2027-02-28 07~22시
interface CrowdRecord {
  spot_id: string;
  datetime: string;
  crowd_score: number;
  crowd_level: CrowdLevel;
  reason: string;
}
let crowdTable: Promise<Map<string, CrowdRecord>> | undefined;

function loadCrowd(): Promise<Map<string, CrowdRecord>> {
  crowdTable ??= fetch(`${import.meta.env.BASE_URL}crowd_forecast.json`)
    .then((res) => (res.ok ? (res.json() as Promise<CrowdRecord[]>) : []))
    .then((rows) => new Map(rows.map((r) => [`${r.spot_id}|${r.datetime}`, r])))
    .catch(() => new Map());
  return crowdTable;
}

// JSON에 있는 스팟·시각이면 엔진 값, 없으면(기간 밖, 엔진에 없는 스팟) mock 값
async function crowdFor(spotId: string, datetime: string, fallback: Forecast['crowd']): Promise<Forecast['crowd']> {
  const r = (await loadCrowd()).get(`${spotId}|${datetime}`);
  return r ? { score: r.crowd_score, level: r.crowd_level, reason: r.reason } : fallback;
}

// datetime: 'YYYY-MM-DDTHH:00' (한국 시간)
// 이미지는 서버 결과, 혼잡도는 엔진 JSON(없으면 mock). 서버 실패·한도 초과면 자리표시 이미지와 사유를 넘긴다.
export async function getForecast(spotId: string, datetime: string): Promise<Forecast> {
  const base = mockForecast(spotId, datetime);
  const mock = { ...base, crowd: await crowdFor(spotId, datetime, base.crowd) };
  if (API_BASE === undefined) return mock;

  try {
    const query = new URLSearchParams({ spot: spotId, datetime });
    const res = await fetch(`${API_BASE}/api/forecast?${query}`);
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new Error(body?.detail ?? `서버 응답 ${res.status}`);
    const name = MOCK_SPOTS.find((s) => s.id === spotId)?.name ?? spotId;
    return {
      ...mock,
      image: { src: `${API_BASE}${body.image_url}`, alt: `${name} 예상 배경 (AI 생성 이미지)` },
      conditions: body.conditions,
      summary: body.summary_ko,
      status: 'ready',
    };
  } catch (e) {
    const reason = e instanceof Error ? e.message : String(e);
    return { ...mock, status: 'fallback', note: `예상 이미지를 만들지 못해 자리표시 이미지를 보여줍니다. (${reason})` };
  }
}
