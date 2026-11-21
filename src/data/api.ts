// 화면은 이 두 함수만 부른다. 실제 모델 결과가 오면 이 파일의 구현만 바꾼다.
import type { Forecast, Spot } from './types';
import { MOCK_SPOTS, mockForecast } from './mock';

export async function getSpots(): Promise<Spot[]> {
  return MOCK_SPOTS;
}

// datetime: 'YYYY-MM-DDTHH:00' (한국 시간)
export async function getForecast(spotId: string, datetime: string): Promise<Forecast> {
  return mockForecast(spotId, datetime);
}
