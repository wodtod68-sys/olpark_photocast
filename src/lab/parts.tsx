import { useState } from 'react';
import { lab, SCORE_KO, type LabImage } from './api';
import s from './lab.module.css';

// 기준 사진과 결과를 나란히 + 전후 슬라이더(같은 3:4 비율이라 겹쳐 볼 수 있다)
export function Compare({ base, img, label }: { base?: string; img: string; label?: string }) {
  const [mode, setMode] = useState<'pair' | 'slide'>('pair');
  const [pos, setPos] = useState(50);
  return (
    <div className={s.compare}>
      <div className={s.compareBar}>
        {label && <span className={s.muted}>{label}</span>}
        {base && (
          <span className={s.seg}>
            <button className={mode === 'pair' ? s.segOn : s.segBtn} onClick={() => setMode('pair')}>
              나란히
            </button>
            <button className={mode === 'slide' ? s.segOn : s.segBtn} onClick={() => setMode('slide')}>
              전후 슬라이더
            </button>
          </span>
        )}
        <a className={s.link} href={img} target="_blank" rel="noreferrer">
          원본 크기
        </a>
      </div>
      {!base || mode === 'pair' ? (
        <div className={base ? s.pair : undefined}>
          {base && (
            <figure>
              <img src={base} alt="기준 사진" />
              <figcaption>기준 사진</figcaption>
            </figure>
          )}
          <figure>
            <img src={img} alt="생성 결과" />
            <figcaption>결과</figcaption>
          </figure>
        </div>
      ) : (
        <>
          <div className={s.slider}>
            <img src={base} alt="기준 사진" />
            <img src={img} alt="생성 결과" className={s.over} style={{ clipPath: `inset(0 0 0 ${pos}%)` }} />
            <span className={s.divider} style={{ left: `${pos}%` }} />
          </div>
          <input className={s.range} type="range" min={0} max={100} value={pos} onChange={(e) => setPos(Number(e.target.value))} />
          <p className={s.muted}>왼쪽 = 기준 사진, 오른쪽 = 결과</p>
        </>
      )}
    </div>
  );
}

export function ScoreBox({ image, onSaved }: { image: LabImage; onSaved?: () => void }) {
  const [scores, setScores] = useState<Record<string, number>>(image.scores ?? {});
  const [note, setNote] = useState(image.note ?? '');
  const [msg, setMsg] = useState('');
  const save = () =>
    lab(`/images/${image.id}/score`, { body: { scores, note } })
      .then(() => {
        setMsg('저장됨');
        onSaved?.();
      })
      .catch((e) => setMsg(e.message));
  return (
    <div className={s.score}>
      {Object.entries(SCORE_KO).map(([k, label]) => (
        <label key={k}>
          {label}
          <select value={scores[k] ?? ''} onChange={(e) => setScores({ ...scores, [k]: Number(e.target.value) })}>
            <option value="">-</option>
            {[1, 2, 3, 4, 5].map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
      ))}
      <textarea placeholder="메모: 무엇을 바꿨고 무엇이 나아졌나" value={note} rows={2} onChange={(e) => setNote(e.target.value)} />
      <button className={s.btn} disabled={Object.keys(scores).length < 3} onClick={save}>
        점수 저장
      </button>
      {msg && <span className={s.muted}>{msg}</span>}
    </div>
  );
}

// unified diff를 줄마다 색칠
export function DiffView({ text }: { text: string }) {
  if (!text) return <p className={s.muted}>차이 없음</p>;
  return (
    <pre className={s.diff}>
      {text.split('\n').map((l, i) => (
        <span key={i} className={l.startsWith('+') && !l.startsWith('+++') ? s.add : l.startsWith('-') && !l.startsWith('---') ? s.del : l.startsWith('@@') ? s.hunk : undefined}>
          {l}
          {'\n'}
        </span>
      ))}
    </pre>
  );
}
