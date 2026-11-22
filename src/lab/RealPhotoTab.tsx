import { useEffect, useState } from 'react';
import { lab, LabError, type LabSpot, type Me, type Template } from './api';
import s from './lab.module.css';

interface Upload {
  taken_at: string;
  taken_at_source: string;
  baseline: { base: Record<string, number>; align: string; sky_mask: string };
  matches: { image_id: number; ground_dE: number; base_ground_dE: number; panel_url: string; template: string }[];
  real_url: string;
}
interface Board {
  template_id: number;
  name: string;
  owner: string;
  n: number;
  mean_ground_dE: number;
  mean_no_change_dE: number;
  improvement_pct: number | null;
}

export function RealPhotoTab({ me, onUsage }: { me: Me; onUsage: () => void }) {
  const [spots, setSpots] = useState<LabSpot[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [spot, setSpot] = useState('naholo');
  const [file, setFile] = useState<File | null>(null);
  const [manual, setManual] = useState('');
  const [needTime, setNeedTime] = useState(false);
  const [tid, setTid] = useState<string>('');
  const [gen, setGen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Upload | null>(null);
  const [err, setErr] = useState('');
  const [board, setBoard] = useState<Board[]>([]);
  const [history, setHistory] = useState<{ id: number; spot: string; taken_at: string; uploader: string; url: string; matched_image_ids: number[] }[]>([]);

  const reload = () => {
    lab<Board[]>('/leaderboard').then(setBoard);
    lab('/real-photos').then(setHistory);
  };
  useEffect(() => {
    lab<LabSpot[]>('/spots').then(setSpots);
    lab<Template[]>('/templates').then(setTemplates);
    reload();
  }, []);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setErr('');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('spot', spot);
    if (manual) fd.append('taken_at', manual);
    if (tid) fd.append('template_id', tid);
    fd.append('generate_missing', String(gen));
    fd.append('model', me.default_model);
    try {
      setRes(await lab<Upload>('/real-photo', { form: fd }));
      setNeedTime(false);
      reload();
    } catch (e) {
      if (e instanceof LabError && e.status === 422) setNeedTime(true);
      setErr((e as Error).message);
    } finally {
      setBusy(false);
      onUsage();
    }
  };

  const spotName = (id: string) => spots.find((x) => x.id === id)?.name ?? id;
  const price = me.models[me.default_model]?.price ?? 0;

  return (
    <div className={s.single}>
      <div className={s.uploadBox}>
        <h2 className={s.h2}>실제 사진 올리기</h2>
        <p className={s.muted}>
          같은 자리·같은 방향에서 찍은 사진(폰 원본 HEIC도 가능). 촬영 시각 ±30분 안의 예측(덮어쓰기 없이 만든 것)을 찾아 기준 사진에 맞춰 정렬하고 채점해요.
        </p>
        <label className={s.field}>
          스팟
          <select value={spot} onChange={(e) => setSpot(e.target.value)}>
            {spots.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
        <label className={s.field}>
          사진
          <input type="file" accept="image/*,.heic,.heif" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        {needTime && (
          <label className={s.field}>
            촬영 시각 (사진에 EXIF 시각이 없어요)
            <input type="datetime-local" value={manual} onChange={(e) => setManual(e.target.value)} />
          </label>
        )}
        <label className={s.field}>
          같이 비교할 템플릿 (shared는 항상 포함)
          <select value={tid} onChange={(e) => setTid(e.target.value)}>
            <option value="">shared만</option>
            {templates
              .filter((t) => !t.current_shared)
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} · {t.owner}
                </option>
              ))}
          </select>
        </label>
        <label className={s.check}>
          <input type="checkbox" checked={gen} onChange={(e) => setGen(e.target.checked)} />
          그 시각 예측이 없으면 새로 만들기 (템플릿당 ${price}, 오늘 남은 {me.remaining}장)
        </label>
        <button className={s.btnBig} disabled={!file || busy} onClick={upload}>
          {busy ? '정렬·채점 중…' : '올리고 채점'}
        </button>
        {err && <p className={s.error}>{err}</p>}
      </div>

      {res && (
        <div className={s.result}>
          <p>
            촬영 {res.taken_at.replace('T', ' ')} ({res.taken_at_source === 'exif' ? 'EXIF' : '직접 입력'}) · 정렬 {res.baseline.align} · 하늘 마스크 {res.baseline.sky_mask}
          </p>
          <p>
            기준 사진을 그대로 뒀을 때(변화 없음) 지면 ΔE <b>{res.baseline.base.ground_dE.toFixed(2)}</b>, 하늘 ΔE {res.baseline.base.sky_dE.toFixed(2)}
          </p>
          {!res.matches.length && <p className={s.muted}>비교할 예측이 없어요. 위에서 "새로 만들기"를 켜거나, 실험 탭에서 그 시각으로 먼저 만들어 두세요.</p>}
          {res.matches.map((m) => (
            <div key={m.image_id}>
              <p>
                <b>{m.template}</b> · 이미지 #{m.image_id}: 지면 ΔE <b>{m.ground_dE.toFixed(2)}</b> (변화 없음 {m.base_ground_dE.toFixed(2)},{' '}
                {m.base_ground_dE ? `${(100 * (1 - m.ground_dE / m.base_ground_dE)).toFixed(0)}% 개선` : ''})
              </p>
              <a href={m.panel_url} target="_blank" rel="noreferrer">
                <img className={s.panel} src={m.panel_url} alt="비교 패널" />
              </a>
            </div>
          ))}
        </div>
      )}

      <h2 className={s.h2}>템플릿별 평균 ΔE 순위</h2>
      <table className={s.table}>
        <thead>
          <tr>
            <th>순위</th>
            <th>템플릿</th>
            <th>채점 수</th>
            <th>평균 지면 ΔE</th>
            <th>변화 없음 ΔE</th>
            <th>개선</th>
          </tr>
        </thead>
        <tbody>
          {board.map((b, i) => (
            <tr key={b.template_id}>
              <td>{i + 1}</td>
              <td>
                {b.name} · {b.owner}
              </td>
              <td>{b.n}</td>
              <td>{b.mean_ground_dE}</td>
              <td>{b.mean_no_change_dE}</td>
              <td>{b.improvement_pct === null ? '-' : `${b.improvement_pct}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!board.length && <p className={s.muted}>아직 채점된 예측이 없어요.</p>}

      <h2 className={s.h2}>올린 사진</h2>
      <div className={s.thumbs}>
        {history.map((h) => (
          <a key={h.id} href={h.url} target="_blank" rel="noreferrer" title={`${spotName(h.spot)} ${h.taken_at} · ${h.uploader} · 비교 ${h.matched_image_ids.length}장`}>
            <img src={h.url} alt="" />
          </a>
        ))}
      </div>
    </div>
  );
}
