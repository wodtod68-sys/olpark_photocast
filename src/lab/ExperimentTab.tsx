import { useEffect, useMemo, useState } from 'react';
import {
  BLOCK_KO,
  lab,
  tomorrowKST,
  type Composed,
  type LabImage,
  type LabSpot,
  type Me,
  type Overrides,
  type Template,
} from './api';
import { Compare, DiffView, ScoreBox } from './parts';
import s from './lab.module.css';

interface Result {
  experiment_id: number;
  spot: string;
  datetime: string;
  template: string;
  overrides: Overrides;
  prompt: string;
  cost: number;
  images: LabImage[];
}

const STATE_ROWS: { key: string; label: string }[] = [
  { key: 'direct_sun', label: '직사광' },
  { key: 'haze', label: '연무' },
  { key: 'sky', label: '하늘' },
  { key: 'precip', label: '강수' },
];

export function ExperimentTab({ me, onUsage }: { me: Me; onUsage: () => void }) {
  const [spots, setSpots] = useState<LabSpot[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [spot, setSpot] = useState('naholo');
  const [date, setDate] = useState(tomorrowKST());
  const [time, setTime] = useState('16:30');
  const [tid, setTid] = useState<number | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [ov, setOv] = useState<Overrides>({});
  const [data, setData] = useState<Composed | null>(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(false);
  const [diff, setDiff] = useState<string | null>(null);
  const [promoteInfo, setPromoteInfo] = useState<{ message: string; diff: string } | null>(null);
  const [tplMsg, setTplMsg] = useState('');
  const [model, setModel] = useState(me.default_model);
  const [n, setN] = useState(1);
  const [results, setResults] = useState<Result[]>([]);
  const [genBusy, setGenBusy] = useState(false);
  const [genErr, setGenErr] = useState('');

  const loadTemplates = () => lab<Template[]>('/templates').then((ts) => (setTemplates(ts), ts));
  useEffect(() => {
    lab<LabSpot[]>('/spots').then(setSpots);
    loadTemplates().then((ts) => {
      const mine = ts.find((t) => t.owner === me.user && !t.is_shared);
      setTid((mine ?? ts.find((t) => t.current_shared))?.id ?? null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 조건·템플릿·편집이 바뀌면 0.4초 뒤 프롬프트 다시 조립(무료)
  useEffect(() => {
    if (tid === null) return;
    setLoading(true);
    const h = setTimeout(() => {
      lab<Composed>('/prompt', { body: { spot, datetime: `${date}T${time}`, overrides: ov, template_id: tid, edits } })
        .then((d) => {
          setData(d);
          setErr('');
        })
        .catch((e) => setErr(e.message))
        .finally(() => setLoading(false));
    }, 400);
    return () => clearTimeout(h);
  }, [spot, date, time, tid, ov, edits]);

  const tpl = templates.find((t) => t.id === tid);
  const dirty = Object.keys(edits).length > 0;
  const canSave = !!tpl && !tpl.is_shared && tpl.owner === me.user && dirty;
  const spotInfo = spots.find((x) => x.id === spot);
  const price = me.models[model]?.price ?? 0;

  const setOvKey = (k: string, v: unknown) => {
    const next = { ...ov };
    if (v === '' || v === undefined || v === null) delete next[k];
    else next[k] = v;
    setOv(next);
  };

  const changeTemplate = (id: number) => {
    if (dirty && !window.confirm('저장하지 않은 문장 편집이 있어요. 버리고 템플릿을 바꿀까요?')) return;
    setEdits({});
    setDiff(null);
    setTid(id);
  };

  const fork = async () => {
    const name = window.prompt('새 템플릿 이름', `${me.user} 실험 ${new Date().toLocaleDateString('ko-KR')}`);
    if (!name || tid === null) return;
    const t = await lab<Template>(`/templates/${tid}/fork`, { body: { name } });
    await loadTemplates();
    setTid(t.id); // 편집 중이던 문장은 그대로 새 템플릿에 남겨 저장할 수 있게
    setTplMsg(`'${t.name}' 만듦 — 편집 중인 문장은 그대로 남아 있어요. 저장을 누르세요.`);
  };

  const save = async () => {
    const note = window.prompt('무엇을 바꿨나요? (메모)', tpl?.note ?? '') ?? undefined;
    try {
      await lab(`/templates/${tid}`, { method: 'PUT', body: { edits, note } });
      setEdits({});
      await loadTemplates();
      setTplMsg('저장했어요');
    } catch (e) {
      setTplMsg((e as Error).message);
    }
  };

  const showDiff = async () => {
    const d = await lab<Record<string, string>>('/templates/diff', { body: { a: tid, edits } });
    setDiff([d.templates_yaml, d.rules_yaml, d.delta_yaml].filter(Boolean).join('\n'));
  };

  const promote = async (confirm: boolean) => {
    try {
      if (!confirm) {
        const r = await lab(`/templates/${tid}/promote`, { body: { confirm: false } });
        setPromoteInfo({ message: r.message, diff: [r.diff.templates_yaml, r.diff.rules_yaml, r.diff.delta_yaml].filter(Boolean).join('\n') });
      } else {
        const t = await lab<Template>(`/templates/${tid}/promote`, { body: { confirm: true } });
        setPromoteInfo(null);
        await loadTemplates();
        setTplMsg(`'${t.name}'으로 승격했어요. 공개 화면도 이 버전을 써요.`);
      }
    } catch (e) {
      setTplMsg((e as Error).message);
    }
  };

  const exportTpl = () => window.open(`/api/lab/templates/${tid}/export`, '_blank');
  const importTpl = async (f: File | undefined) => {
    if (!f) return;
    try {
      const t = await lab<Template>('/templates/import', { body: { bundle: await f.text() } });
      await loadTemplates();
      setTid(t.id);
      setEdits({});
      setTplMsg(`'${t.name}' 가져왔어요`);
    } catch (e) {
      setTplMsg((e as Error).message);
    }
  };

  const generate = async () => {
    setGenBusy(true);
    setGenErr('');
    try {
      const r = await lab('/generate', {
        body: { spot, datetime: `${date}T${time}`, overrides: ov, template_id: tid, edits, model, n },
      });
      setResults([
        {
          experiment_id: r.experiment_id,
          spot,
          datetime: `${date} ${time}`,
          template: (tpl?.name ?? '') + (dirty ? ' + 저장 안 한 편집' : ''),
          overrides: ov,
          prompt: r.prompt,
          cost: r.cost,
          images: r.images,
        },
        ...results,
      ]);
    } catch (e) {
      setGenErr((e as Error).message);
    } finally {
      setGenBusy(false);
      onUsage();
    }
  };

  const ds = data?.data_state;
  const groundOv: string[] | undefined = ov.ground;
  const sortedTemplates = useMemo(
    () => [...templates].sort((a, b) => Number(b.current_shared) - Number(a.current_shared) || b.id - a.id),
    [templates],
  );

  return (
    <div className={s.three}>
      {/* ── 왼쪽: 조건 ───────────────────────── */}
      <section className={s.col}>
        <h2 className={s.h2}>조건</h2>
        <label className={s.field}>
          스팟
          <select value={spot} onChange={(e) => setSpot(e.target.value)}>
            {spots.map((x) => (
              <option key={x.id} value={x.id} disabled={!!x.error}>
                {x.name}
                {x.error ? ' (설정 오류)' : ''}
              </option>
            ))}
          </select>
        </label>
        <div className={s.row2}>
          <label className={s.field}>
            날짜 (과거도 가능)
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className={s.field}>
            시각
            <input type="time" value={time} step={600} onChange={(e) => setTime(e.target.value)} />
          </label>
        </div>
        {spotInfo?.base_url && (
          <figure className={s.baseThumb}>
            <img src={spotInfo.base_url} alt="기준 사진" />
            <figcaption>기준 사진 {spotInfo.base_datetime?.replace('T', ' ')}</figcaption>
          </figure>
        )}
        {data && (
          <>
            <p className={s.summary}>
              <b>목표</b> {data.summary_ko}
            </p>
            <p className={s.muted}>기준: {data.summary_ko_base}</p>
          </>
        )}

        <h3 className={s.h3}>
          상태표 덮어쓰기
          <button className={s.link} onClick={() => setOv({})} disabled={!Object.keys(ov).length}>
            데이터 값으로 되돌리기
          </button>
        </h3>
        {ds && data && (
          <table className={s.state}>
            <tbody>
              <tr>
                <th>빛</th>
                <td colSpan={2}>{ds.light} <span className={s.muted}>(시각으로만 바뀜)</span></td>
              </tr>
              <tr>
                <th>방향</th>
                <td colSpan={2}>{ds.direction}</td>
              </tr>
              <tr>
                <th>날씨 가정</th>
                <td colSpan={2}>
                  <label className={s.check}>
                    <input type="checkbox" checked={ov.assume === 'clear'} onChange={(e) => setOvKey('assume', e.target.checked ? 'clear' : '')} />
                    예보 대신 맑은 날로 가정
                  </label>
                </td>
              </tr>
              {STATE_ROWS.map(({ key, label }) => (
                <tr key={key} className={ov[key] ? s.overridden : undefined}>
                  <th>{label}</th>
                  <td>
                    <select value={ov[key] ?? ''} onChange={(e) => setOvKey(key, e.target.value)}>
                      <option value="">데이터: {String((ds as unknown as Record<string, unknown>)[key])}</option>
                      {(data.choices as unknown as Record<string, string[]>)[key].map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
              <tr className={groundOv ? s.overridden : undefined}>
                <th>지면</th>
                <td>
                  <label className={s.check}>
                    <input type="checkbox" checked={!!groundOv} onChange={(e) => setOvKey('ground', e.target.checked ? [...ds.ground] : '')} />
                    덮어쓰기 (데이터: {ds.ground.join(', ') || '없음'})
                  </label>
                  {groundOv &&
                    data.choices.ground.map((g) => (
                      <label key={g} className={s.check}>
                        <input
                          type="checkbox"
                          checked={groundOv.includes(g)}
                          onChange={(e) => setOvKey('ground', e.target.checked ? [...groundOv, g] : groundOv.filter((x) => x !== g))}
                        />
                        {g}
                      </label>
                    ))}
                </td>
              </tr>
              {Object.entries(data.choices.trees).map(([sp, stages]) => (
                <tr key={sp} className={ov.trees?.[sp] ? s.overridden : undefined}>
                  <th>{ds.trees_ko[sp]?.split(' ')[0] ?? sp}</th>
                  <td>
                    <select
                      value={ov.trees?.[sp] ?? ''}
                      onChange={(e) => {
                        const t = { ...(ov.trees ?? {}) };
                        if (e.target.value) t[sp] = e.target.value;
                        else delete t[sp];
                        setOvKey('trees', Object.keys(t).length ? t : '');
                      }}
                    >
                      <option value="">데이터: {ds.trees_ko[sp]}</option>
                      {stages.map((st) => (
                        <option key={st} value={st}>
                          {st}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && (
          <details className={s.details}>
            <summary>원데이터·출처 (접기)</summary>
            <pre className={s.pre}>{JSON.stringify({ sources: data.sources, raw: data.raw, delta: data.delta }, null, 1)}</pre>
          </details>
        )}
      </section>

      {/* ── 가운데: 템플릿 문장 ───────────────────── */}
      <section className={s.col}>
        <h2 className={s.h2}>프롬프트 템플릿</h2>
        <div className={s.tplBar}>
          <select value={tid ?? ''} onChange={(e) => changeTemplate(Number(e.target.value))}>
            {sortedTemplates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.current_shared ? '★ ' : ''}
                {t.name} · {t.owner}
                {t.is_shared && !t.current_shared ? ' (지난 shared)' : ''}
              </option>
            ))}
          </select>
          <button className={s.btnGhost} onClick={fork}>
            fork
          </button>
          <button className={s.btn} disabled={!canSave} onClick={save} title={tpl?.is_shared ? 'shared는 fork해서 고치세요' : ''}>
            저장{dirty ? ` (${Object.keys(edits).length})` : ''}
          </button>
          <button className={s.btnGhost} onClick={showDiff}>
            shared와 diff
          </button>
          {tpl && !tpl.is_shared && (
            <button className={s.btnGhost} onClick={() => promote(false)}>
              shared로 승격…
            </button>
          )}
          <button className={s.btnGhost} onClick={exportTpl}>
            파일로 내보내기
          </button>
          <label className={s.btnGhost}>
            가져오기
            <input type="file" accept=".yaml,.yml" hidden onChange={(e) => importTpl(e.target.files?.[0])} />
          </label>
        </div>
        {tpl?.is_shared && <p className={s.muted}>공용(shared) 버전은 직접 저장할 수 없어요. 고친 뒤 fork를 누르면 편집이 새 템플릿으로 옮겨져요.</p>}
        {tplMsg && <p className={s.note}>{tplMsg}</p>}
        {promoteInfo && (
          <div className={s.confirm}>
            <p>{promoteInfo.message}</p>
            <DiffView text={promoteInfo.diff} />
            <button className={s.btn} onClick={() => promote(true)}>
              승격 확인
            </button>
            <button className={s.btnGhost} onClick={() => setPromoteInfo(null)}>
              취소
            </button>
          </div>
        )}
        {diff !== null && (
          <details open className={s.details}>
            <summary>
              shared와의 차이 (편집 중 포함) <button className={s.link} onClick={() => setDiff(null)}>닫기</button>
            </summary>
            <DiffView text={diff} />
          </details>
        )}
        {err && <p className={s.error}>{err}</p>}
        <p className={s.muted}>
          이번 조건에서 실제로 쓰이는 문장만 블록 순서대로 보여요. 중괄호 자리({'{elev}'} 등)는 지우지 마세요. {loading ? '조립 중…' : ''}
        </p>
        {data?.order.map((b) => (
          <div key={b} className={s.block}>
            <h4 className={s.h4}>{BLOCK_KO[b] ?? b}</h4>
            {data.block_keys[b].map((k) => {
              const v = edits[k] ?? data.key_values[k] ?? '';
              const changed = k in edits;
              return (
                <div key={k} className={s.keyRow}>
                  <div className={s.keyHead}>
                    <code className={changed ? s.keyChanged : s.key}>{k}</code>
                    {changed && (
                      <button
                        className={s.link}
                        onClick={() => {
                          const c = { ...edits };
                          delete c[k];
                          setEdits(c);
                        }}
                      >
                        되돌리기
                      </button>
                    )}
                  </div>
                  <textarea
                    className={changed ? s.taChanged : s.ta}
                    value={v}
                    rows={Math.min(6, Math.ceil((v.length || 1) / 60))}
                    onChange={(e) => setEdits({ ...edits, [k]: e.target.value })}
                  />
                </div>
              );
            })}
            <p className={s.blockOut}>→ {data.blocks[b]}</p>
          </div>
        ))}
        {data && (
          <>
            <h3 className={s.h3}>완성 프롬프트 미리보기</h3>
            <pre className={s.prompt}>{data.prompt}</pre>
          </>
        )}
      </section>

      {/* ── 오른쪽: 생성 ───────────────────────── */}
      <section className={s.col}>
        <h2 className={s.h2}>생성</h2>
        <div className={s.row2}>
          <label className={s.field}>
            모델
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {Object.entries(me.models).map(([k, m]) => (
                <option key={k} value={k}>
                  {m.name} (${m.price})
                </option>
              ))}
            </select>
          </label>
          <label className={s.field}>
            장수
            <select value={n} onChange={(e) => setN(Number(e.target.value))}>
              {[1, 2, 3].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className={s.cost}>
          예상 비용 최대 <b>${(price * n).toFixed(3)}</b> · 오늘 남은 {me.remaining}장
          <br />
          <span className={s.muted}>같은 프롬프트·샘플은 캐시라 0원. 한 장에 15~20초.</span>
        </p>
        <button className={s.btnBig} disabled={genBusy || !data || me.remaining < 1} onClick={generate}>
          {genBusy ? `만드는 중… (${n}장)` : `생성 ${n}장`}
        </button>
        {genErr && <p className={s.error}>{genErr}</p>}
        {results.map((r) => (
          <div key={r.experiment_id} className={s.result}>
            <p className={s.muted}>
              #{r.experiment_id} · {spots.find((x) => x.id === r.spot)?.name} {r.datetime} · {r.template} · ${r.cost.toFixed(3)}
            </p>
            {r.images.map((im, i) =>
              im.error ? (
                <p key={i} className={s.error}>
                  실패: {im.error}
                </p>
              ) : (
                <div key={im.id}>
                  <Compare
                    base={spots.find((x) => x.id === r.spot)?.base_url}
                    img={im.url}
                    label={`${im.cached ? '캐시' : `${im.latency}s`}`}
                  />
                  <ScoreBox image={im} />
                </div>
              ),
            )}
            <details className={s.details}>
              <summary>이 실험의 프롬프트</summary>
              <pre className={s.prompt}>{r.prompt}</pre>
            </details>
          </div>
        ))}
      </section>
    </div>
  );
}
