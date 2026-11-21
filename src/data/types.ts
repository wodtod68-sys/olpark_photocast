// 화면과 데이터 사이의 약속. 실제 모델 결과가 와도 이 모양을 유지한다.

export interface Spot {
  id: string;
  no: number; // 지도 마커 번호
  name: string;
  scene?: string; // 올림픽공원 9경 번호 (예: '6경')
  description: string;
  // 스팟 대표 사진 (public/ 기준 경로). position은 사진을 잘라 보여줄 때의 중심점, credit은 출처 표기
  photo: { src: string; position: string; credit: string };
  // 지도 위 위치. 지도 이미지의 픽셀 좌표(ParkMap의 MAP_SIZE) 기준
  map: { x: number; y: number };
}

export type CrowdLevel = '여유' | '보통' | '약간 붐빔' | '붐빔';

// 점수 구간. 화면의 눈금도 이 값으로 그린다
export const CROWD_LEVELS: { level: CrowdLevel; min: number }[] = [
  { level: '여유', min: 0 },
  { level: '보통', min: 30 },
  { level: '약간 붐빔', min: 55 },
  { level: '붐빔', min: 75 },
];

// AI 예상 이미지 서버(server/)가 함께 돌려주는 조건값
export interface ForecastConditions {
  sun_elev: number; // 태양 고도(도)
  light_stage: string; // L0~L5
  direction: string; // front-lit | back-lit | side-left | side-right
  sky: string;
  haze: string; // H0~H4
  precip: string;
  trees: { name: string; stage: string }[];
  source: { weather: unknown; air: string };
}

export interface Forecast {
  spotId: string;
  datetime: string; // 'YYYY-MM-DDTHH:00' (한국 시간)
  image: { src: string; alt: string };
  crowd: { score: number; level: CrowdLevel; reason: string };
  // 아래는 서버 연결 시에만 채워진다
  conditions?: ForecastConditions;
  summary?: string; // 화면에 보여줄 한 줄 조건 요약
  status?: 'ready' | 'fallback'; // fallback = 서버 실패·한도 초과로 자리표시 이미지
  note?: string; // fallback 사유
}
