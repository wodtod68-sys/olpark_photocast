// 프롬프트 실험실 API (/api/lab). 로그인 쿠키로 인증하므로 같은 출처(vite 프록시 또는 서버가 내준 화면)에서 쓴다.

export class LabError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function lab<T = any>(path: string, init?: { method?: string; body?: unknown; form?: FormData }): Promise<T> {
  const method = init?.method ?? (init?.body !== undefined || init?.form ? 'POST' : 'GET');
  const opts: RequestInit = { method, credentials: 'same-origin' };
  if (init?.form) opts.body = init.form;
  else if (init?.body !== undefined) {
    opts.body = JSON.stringify(init.body);
    opts.headers = { 'Content-Type': 'application/json' };
  }
  const res = await fetch(`/api/lab${path}`, opts);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    throw new LabError(res.status, typeof d === 'string' ? d : JSON.stringify(d ?? `서버 응답 ${res.status}`));
  }
  return data as T;
}

export interface Me {
  user: string;
  remaining: number;
  daily_limit: number;
  models: Record<string, { id: string; name: string; price: number }>;
  default_model: string;
  users: string[];
}

export interface LabSpot {
  id: string;
  name: string;
  base_datetime?: string;
  base_url?: string;
  error?: string;
}

export interface Template {
  id: number;
  name: string;
  owner: string;
  parent_id: number | null;
  note: string;
  is_shared: boolean;
  current_shared: boolean;
  created_at: string;
  updated_at: string | null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Overrides = Record<string, any>;

export interface StateView {
  light: string;
  direction: string;
  direct_sun: string;
  haze: string;
  sky: string;
  precip: string;
  ground: string[];
  trees: Record<string, string>;
  trees_ko: Record<string, string>;
  landmarks: Record<string, string>;
}

export interface Composed {
  prompt: string;
  order: string[];
  blocks: Record<string, string>;
  block_keys: Record<string, string[]>;
  key_values: Record<string, string>;
  lighting_mode: string;
  summary_ko: string;
  summary_ko_base: string;
  base_state: StateView;
  data_state: StateView;
  target_state: StateView;
  choices: {
    assume: string[];
    direct_sun: string[];
    haze: string[];
    sky: string[];
    precip: string[];
    ground: string[];
    trees: Record<string, string[]>;
  };
  delta: { delta: Record<string, number>; rules_version: string };
  raw: unknown;
  sources: unknown;
}

export interface LabImage {
  id: number;
  url: string;
  cost: number;
  latency: number | null;
  cached: boolean;
  scores?: Record<string, number>;
  note?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metrics?: any;
  error?: string;
}

export interface Experiment {
  id: number;
  user: string;
  spot: string;
  target_datetime: string;
  overrides: Overrides;
  template_id: number;
  template_name: string;
  template_edits: Record<string, string>;
  prompt_text: string;
  model: string;
  grid_cell: string | null;
  created_at: string;
  images: LabImage[];
}

export const fmtBytes = (n: number) =>
  n > 2 ** 30 ? `${(n / 2 ** 30).toFixed(1)}GB` : n > 2 ** 20 ? `${(n / 2 ** 20).toFixed(1)}MB` : `${Math.round(n / 1024)}KB`;

export const BLOCK_KO: Record<string, string> = {
  time_change: '시간 변화',
  preserve: '보존',
  lighting: '태양·날씨',
  consequences: '결과(빛·그림자)',
  exposure: '노출 변화',
  sky_air: '하늘·대기',
  trees: '수목',
  ground: '지면',
  no_beautify: '미화 금지',
};

export const SCORE_KO: Record<string, string> = { cond: '조건 반영', struct: '구조 보존', nobeauty: '미화 억제' };

export const GRID_KO: Record<string, string> = {
  morning_0700: '07시',
  noon_1200: '12시',
  golden_1630: '16:30 골든',
  overcast_1200: '흐림',
  rain_1200: '비',
};

export function tomorrowKST(): string {
  const d = new Date(Date.now() + 9 * 3600e3 + 86400e3);
  return d.toISOString().slice(0, 10);
}

export const overridesText = (o: Overrides) =>
  Object.keys(o).length ? Object.entries(o).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ') : '데이터 그대로';
