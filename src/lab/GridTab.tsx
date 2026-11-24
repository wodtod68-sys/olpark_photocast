import { useEffect, useState } from 'react';
import { GRID_KO, lab, tomorrowKST, type LabSpot, type Me, type Template } from './api';
import s from './lab.module.css';

interface Plan {
  template_name: string;
  date: string;
  model: string;
  n_new: number;
  cost_usd: number;
  remaining: number;
  cells: { spot: string; cond: string; cached: boolean; summary?: string; error?: string }[];
}
interface Matrix {
  spots: string[];
  conds: string[];
  cells: Record<string, { image_id: number; url: string; scores: Record<string, number> }>;
}

export function GridTab({ me, onUsage }: { me: Me; onUsage: () => void }) {
  const [spots, setSpots] = useState<LabSpot[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tid, setTid] = useState<number | null>(null);
  const [date, setDate] = useState(tomorrowKST());
  const [model, setModel] = useState(me.default_model);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [job, setJob] = useState<{ status: string; done: number; total: number; errors: string[] } | null>(null);
  const [mine, setMine] = useState<Matrix | null>(null);
  const [shared, setShared] = useState<Matrix | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const sharedT = templates.find((t) => t.current_shared);
  useEffect(() => {
    lab<LabSpot[]>('/spots').then(setSpots);
    lab<Template[]>('/templates').then((ts) => {
      setTemplates(ts);
      setTid((ts.find((t) => t.owner === me.user && !t.is_shared) ?? ts.find((t) => t.current_shared))?.id ?? null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadMatrices = () => {
    if (tid) lab<Matrix>(`/grid/matrix?template_id=${tid}&date=${date}`).then(setMine);
    if (sharedT) lab<Matrix>(`/grid/matrix?template_id=${sharedT.id}&date=${date}`).then(setShared);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadMatrices, [tid, date, sharedT?.id]);

  const estimate = async () => {
    setBusy(true);
    setErr('');
    try {
      setPlan(await lab<Plan>('/grid', { body: { template_id: tid, date, model, confirm: false } }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    if (!plan || !window.confirm(`${plan.n_new}장을 새로 만들어요. 비용 약 $${plan.cost_usd}. 실행할까요?`)) return;
    try {
      const { job: id } = await lab('/grid', { body: { template_id: tid, date, model, confirm: true } });
      const poll = async () => {
        const j = await lab(`/grid/job/${id}`);
        setJob(j);
        loadMatrices();
        if (j.status !== 'done') setTimeout(poll, 4000);
        else onUsage();
      };
      poll();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const spotName = (id: string) => spots.find((x) => x.id === id)?.name ?? id;
  const grid = (m: Matrix | null, title: string) => (
    <div className={s.col}>
      <h3 className={s.h3}>{title}</h3>
      {m && (
        <table className={s.grid}>
          <thead>
            <tr>
              <th></th>
              {m.conds.map((c) => (
                <th key={c}>{GRID_KO[c] ?? c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {m.spots.map((sp) => (
              <tr key={sp}>
                <th>{spotName(sp)}</th>
                {m.conds.map((c) => {
                  const cell = m.cells[`${sp}|${c}`];
                  return (
                    <td key={c}>
                      {cell ? (
                        <a href={cell.url} target="_blank" rel="noreferrer">
                          <img src={cell.url} alt="" />
                        </a>
                      ) : (
                        <span className={s.muted}>없음</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );

  return (
    <div className={s.single}>
      <p className={s.muted}>
        4곳 × 대표 조건 5개(07시 · 12시 · 16:30 골든 · 흐림 · 비). 모두 "맑은 날 가정"에서 시작해 날짜의 실제 예보와 상관없이 같은 조건으로 비교해요.
        한 번 돌리면 최대 20장(하루 한도 전부)이니 둘이 상의하고 돌리세요.
      </p>
      <div className={s.filters}>
        <select value={tid ?? ''} onChange={(e) => (setTid(Number(e.target.value)), setPlan(null))}>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.current_shared ? '★ ' : ''}
              {t.name} · {t.owner}
            </option>
          ))}
        </select>
        <input type="date" value={date} onChange={(e) => (setDate(e.target.value), setPlan(null))} />
        <select value={model} onChange={(e) => (setModel(e.target.value), setPlan(null))}>
          {Object.entries(me.models).map(([k, m]) => (
            <option key={k} value={k}>
              {m.name}
            </option>
          ))}
        </select>
        <button className={s.btnGhost} disabled={busy || !tid} onClick={estimate}>
          {busy ? '계산 중…' : '비용 확인'}
        </button>
      </div>
      {err && <p className={s.error}>{err}</p>}
      {plan && (
        <div className={s.confirm}>
          <p>
            <b>{plan.template_name}</b> · {plan.date} · {plan.model}: 새로 만들 <b>{plan.n_new}장</b>, 비용 약 <b>${plan.cost_usd}</b> {me.daily_limit ? `(오늘 남은 ${plan.remaining}장)` : ''}
          </p>
          <ul className={s.small}>
            {plan.cells.map((c) => (
              <li key={`${c.spot}${c.cond}`}>
                {spotName(c.spot)} · {GRID_KO[c.cond]}: {c.error ? `오류 ${c.error}` : c.cached ? '이미 있음(0원)' : c.summary}
              </li>
            ))}
          </ul>
          <button className={s.btn} disabled={plan.n_new === 0 || plan.n_new > plan.remaining} onClick={run}>
            실행 ({plan.n_new}장, ${plan.cost_usd})
          </button>
          {plan.n_new > plan.remaining && <span className={s.error}> 오늘 남은 수량이 부족해요</span>}
        </div>
      )}
      {job && (
        <p className={s.note}>
          진행 {job.done}/{job.total} {job.status === 'done' ? '— 완료' : '…'} {job.errors.length ? `오류 ${job.errors.length}건: ${job.errors.join(' / ')}` : ''}
        </p>
      )}
      <div className={s.versus}>
        {grid(mine, `선택한 템플릿 (${templates.find((t) => t.id === tid)?.name ?? ''})`)}
        {grid(shared, `현재 shared (${sharedT?.name ?? ''})`)}
      </div>
    </div>
  );
}
