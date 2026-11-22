// 프롬프트 실험실 (#/lab). 공개 화면과 분리된 화면이고, 이 파일부터 따로 불러온다(lazy).
import { useEffect, useState } from 'react';
import { fmtBytes, lab, type Me } from './api';
import { ExperimentTab } from './ExperimentTab';
import { GridTab } from './GridTab';
import { HistoryTab } from './HistoryTab';
import { RealPhotoTab } from './RealPhotoTab';
import s from './lab.module.css';

const TABS = [
  ['exp', '실험'],
  ['history', '기록'],
  ['grid', '그리드'],
  ['real', '실제 사진'],
] as const;
type Tab = (typeof TABS)[number][0];

function Login({ onDone }: { onDone: (m: Me) => void }) {
  const [pass, setPass] = useState('');
  const [users, setUsers] = useState<string[] | null>(null);
  const [err, setErr] = useState('');
  const check = async () => {
    setErr('');
    try {
      const r = await lab<{ users: string[] }>('/login', { body: { passcode: pass } });
      setUsers(r.users);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const enter = async (user: string) => {
    try {
      await lab('/login', { body: { passcode: pass, user } });
      onDone(await lab<Me>('/me'));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className={s.login}>
      <h1 className={s.title}>프롬프트 실험실</h1>
      {!users ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            check();
          }}
        >
          <label className={s.field}>
            공용 비밀번호
            <input type="password" value={pass} autoFocus onChange={(e) => setPass(e.target.value)} />
          </label>
          <button className={s.btnBig} disabled={!pass}>
            확인
          </button>
        </form>
      ) : (
        <>
          <p>누구세요?</p>
          <div className={s.users}>
            {users.map((u) => (
              <button key={u} className={s.btnBig} onClick={() => enter(u)}>
                {u}
              </button>
            ))}
          </div>
        </>
      )}
      {err && <p className={s.error}>{err}</p>}
      <p className={s.muted}>
        <a className={s.link} href="#/">
          ← 공개 화면으로
        </a>
      </p>
    </div>
  );
}

export default function LabApp() {
  const [me, setMe] = useState<Me | null>(null);
  const [checked, setChecked] = useState(false);
  const [tab, setTab] = useState<Tab>('exp');
  const [storage, setStorage] = useState<{ lab_data_bytes: number; disk_free_bytes: number; files: number } | null>(null);

  const refreshMe = () => {
    lab<Me>('/me').then(setMe).catch(() => setMe(null));
    lab('/storage').then(setStorage).catch(() => {});
  };
  useEffect(() => {
    lab<Me>('/me')
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setChecked(true));
  }, []);
  useEffect(() => {
    if (me) lab('/storage').then(setStorage).catch(() => {});
  }, [me?.user, tab]);

  if (!checked) return null;
  if (!me) return <Login onDone={setMe} />;
  return (
    <div className={s.lab}>
      <header className={s.top}>
        <h1 className={s.title}>프롬프트 실험실</h1>
        <nav className={s.tabs}>
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? s.tabOn : s.tab} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
        </nav>
        <div className={s.meta}>
          <b>{me.user}</b>
          <span>
            오늘 남은 생성 {me.remaining}/{me.daily_limit}장
          </span>
          {storage && (
            <span title={`파일 ${storage.files}개`}>
              실험 이미지 {fmtBytes(storage.lab_data_bytes)} · 디스크 여유 {fmtBytes(storage.disk_free_bytes)}
            </span>
          )}
          <a className={s.link} href="#/">
            공개 화면
          </a>
          <button className={s.link} onClick={() => lab('/logout', { body: {} }).then(() => setMe(null))}>
            나가기
          </button>
        </div>
      </header>
      <main className={s.main}>
        {tab === 'exp' && <ExperimentTab me={me} onUsage={refreshMe} />}
        {tab === 'history' && <HistoryTab me={me} />}
        {tab === 'grid' && <GridTab me={me} onUsage={refreshMe} />}
        {tab === 'real' && <RealPhotoTab me={me} onUsage={refreshMe} />}
      </main>
    </div>
  );
}
