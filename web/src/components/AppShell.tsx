import { Activity, BookOpen, Plus, Settings, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { api, type Health } from '../api/client';

export function AppShell() {
  const [health, setHealth] = useState<Health | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { void api.health().then(setHealth).catch(() => setHealth(null)); }, []);
  const healthy = health?.runner_available && health.ai_configured;
  return <div className="app-shell">
    <aside className="global-nav">
      <NavLink to="/" className="brand" aria-label="LoopCode 홈"><span>LC</span><strong>LoopCode</strong></NavLink>
      <nav aria-label="주 메뉴">
        <NavLink to="/" end><BookOpen /><span>문제</span></NavLink>
        <NavLink to="/problems/new"><Plus /><span>등록</span></NavLink>
      </nav>
      <button className="nav-button" onClick={() => setOpen(true)}><Settings /><span>상태</span><i className={healthy ? 'dot ok' : 'dot warn'} /></button>
    </aside>
    <main className="app-main"><Outlet /></main>
    {open && <div className="drawer-backdrop" onMouseDown={() => setOpen(false)}>
      <aside className="settings-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><span className="eyebrow">LOCAL SERVICES</span><h2>서비스 상태</h2></div><button className="icon-button" aria-label="상태 창 닫기" onClick={() => setOpen(false)}><X /></button></header>
        {!health ? <div className="notice error">백엔드에 연결할 수 없습니다. Docker Compose 실행 상태를 확인하세요.</div> : <>
          <ServiceRow label="로컬 데이터베이스" ok={health.database === 'ok'} detail="문제와 풀이 기록을 로컬에 보관합니다." />
          <ServiceRow label="코드 실행기" ok={health.runner_available} detail={health.runner_available ? '격리 실행 환경이 준비됐습니다.' : health.detail} />
          <ServiceRow label="AI 연결" ok={health.ai_configured} detail={health.ai_configured ? '문제 분석과 풀이 도움을 요청할 수 있습니다.' : '.env에 OPENAI_API_KEY를 설정하면 AI 기능을 사용할 수 있습니다.'} />
          <div className="settings-note"><Activity size={17} /><p>코드 실행, 제출, 자동 저장에는 AI를 사용하지 않습니다.</p></div>
        </>}
      </aside>
    </div>}
  </div>;
}

function ServiceRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return <div className="service-row"><span className={ok ? 'service-icon ok' : 'service-icon warn'}>{ok ? '✓' : '!'}</span><div><strong>{label}</strong><p>{detail}</p></div></div>;
}
