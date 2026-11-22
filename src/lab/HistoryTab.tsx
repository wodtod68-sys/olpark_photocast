import { useEffect, useState } from 'react';
import { lab, overridesText, SCORE_KO, type Experiment, type LabSpot, type Me, type Template } from './api';
import { Compare, ScoreBox } from './parts';
import s from './lab.module.css';

const avg = (o?: Record<string, number>) => {
  const v = Object.values(o ?? {});
  return v.length ? (v.reduce((a, b) => a + b, 0) / v.length).toFixed(1) : '-';
};

export function HistoryTab({ me }: { me: Me }) {
  const [spots, setSpots] = useState<LabSpot[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [f, setF] = useState({ user: '', spot: '', template_id: '' });
  const [rows, setRows] = useState<Experiment[]>([]);
  const [pick, setPick] = useState<number[]>([]);
  const [err, setErr] = useState('');

  useEffect(() => {
    lab<LabSpot[]>('/spots').then(setSpots);
    lab<Template[]>('/templates').then(setTemplates);
  }, []);
  const load = () => {
    const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    lab<Experiment[]>(`/experiments?${q}`).then(setRows).catch((e) => setErr(e.message));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [f]);

  const spotName = (id: string) => spots.find((x) => x.id === id)?.name ?? id;
  const baseUrl = (id: string) => spots.find((x) => x.id === id)?.base_url;
  const toggle = (id: number) => setPick(pick.includes(id) ? pick.filter((x) => x !== id) : [...pick.slice(-1), id]);
  const picked = pick.map((id) => rows.find((r) => r.id === id)).filter(Boolean) as Experiment[];

  return (
    <div className={s.single}>
      <div className={s.filters}>
        <select value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })}>
          <option value="">모든 사람</option>
          {me.users.map((u) => (
            <option key={u}>{u}</option>
          ))}
        </select>
        <select value={f.spot} onChange={(e) => setF({ ...f, spot: e.target.value })}>
          <option value="">모든 스팟</option>
          {spots.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
        </select>
        <select value={f.template_id} onChange={(e) => setF({ ...f, template_id: e.target.value })}>
          <option value="">모든 템플릿</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} · {t.owner}
            </option>
          ))}
        </select>
        <button className={s.btnGhost} onClick={load}>
          새로고침
        </button>
        <span className={s.muted}>두 개를 체크하면 아래에 나란히 비교 (같은 조건, 다른 템플릿 비교용)</span>
      </div>
      {err && <p className={s.error}>{err}</p>}

      {picked.length === 2 && (
        <div className={s.versus}>
          {picked.map((e, i) => {
            const other = picked[1 - i].prompt_text.split('\n');
            return (
              <div key={e.id} className={s.col}>
                <h3 className={s.h3}>
                  #{e.id} · {e.template_name} · {e.user}
                </h3>
                <p className={s.muted}>
                  {spotName(e.spot)} {e.target_datetime.replace('T', ' ')} · {overridesText(e.overrides)} · {e.model}
                </p>
                <pre className={s.prompt}>
                  {e.prompt_text.split('\n').map((l, j) => (
                    <span key={j} className={other.includes(l) ? undefined : s.add}>
                      {l}
                      {'\n'}
                    </span>
                  ))}
                </pre>
                {e.images.map((im) => (
                  <div key={im.id}>
                    <Compare base={baseUrl(e.spot)} img={im.url} />
                    <ScoreBox image={im} onSaved={load} />
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}

      <table className={s.table}>
        <thead>
          <tr>
            <th></th>
            <th>#</th>
            <th>만든 때</th>
            <th>사람</th>
            <th>스팟·시각</th>
            <th>템플릿</th>
            <th>덮어쓰기</th>
            <th>이미지</th>
            <th>점수 평균</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id} className={pick.includes(e.id) ? s.picked : undefined}>
              <td>
                <input type="checkbox" checked={pick.includes(e.id)} onChange={() => toggle(e.id)} />
              </td>
              <td>{e.id}</td>
              <td>{new Date(e.created_at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td>
              <td>{e.user}</td>
              <td>
                {spotName(e.spot)}
                <br />
                {e.target_datetime.replace('T', ' ')}
              </td>
              <td>
                {e.template_name}
                {Object.keys(e.template_edits).length ? <span className={s.muted}> +편집</span> : null}
                {e.grid_cell ? <span className={s.muted}> (그리드)</span> : null}
              </td>
              <td className={s.small}>{overridesText(e.overrides)}</td>
              <td>
                <div className={s.thumbs}>
                  {e.images.map((im) => (
                    <a key={im.id} href={im.url} target="_blank" rel="noreferrer">
                      <img src={im.url} alt="" />
                    </a>
                  ))}
                </div>
              </td>
              <td title={e.images.map((im) => Object.entries(im.scores ?? {}).map(([k, v]) => `${SCORE_KO[k]} ${v}`).join(', ')).join(' / ')}>
                {e.images.map((im) => avg(im.scores)).join(' / ')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <p className={s.muted}>아직 실험이 없어요.</p>}
    </div>
  );
}
