import { ArrowLeft, Bot, Braces, CheckCircle2, Clock3, Edit3, FlaskConical, History, Plus, Terminal, XCircle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Link, useParams } from 'react-router-dom';
import { api, pollJob, type ChatTurn, type Job, type Language, type Problem, type TestCase, type TutorMode } from '../api/client';
import { CodeWorkspace } from '../components/CodeWorkspace';
import { StatusBadge } from '../components/StatusBadge';
import { TutorDrawer } from '../components/TutorDrawer';
import { formatDate, languageLabel, parseJsonValue, statusLabels, typeLabel } from '../lib/domain';
import { draftKey, waitForDraftSaves } from '../lib/draftSaveQueue';

type DockTab = 'tests' | 'results' | 'history';
const markdownPlugins = [remarkGfm];
const displayValue = (value: unknown) => JSON.stringify(value) ?? 'null';

export function WorkspacePage() {
  const { id = '' } = useParams(); const [problem, setProblem] = useState<Problem | null>(null); const [initialSource, setInitialSource] = useState('');
  const [job, setJob] = useState<Job | null>(null); const [submissions, setSubmissions] = useState<Job[]>([]); const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [tab, setTab] = useState<DockTab>('tests'); const [busy, setBusy] = useState(false); const [tutorBusy, setTutorBusy] = useState(false); const [tutorOpen, setTutorOpen] = useState(false); const [error, setError] = useState('');
  const [split, setSplit] = useState(43); const current = useRef<{ language: Language; source: string }>({ language: 'python', source: '' });
  const loadRevision = useRef(0); const loadedId = useRef(''); const runOperation = useRef(0); const tutorOperation = useRef(0);
  const reloadProblem = async () => { const routeId = id; const value = await api.problem(routeId); if (loadedId.current === routeId) setProblem(value); };
  useEffect(() => {
    const revision = ++loadRevision.current; runOperation.current += 1; tutorOperation.current += 1; loadedId.current = ''; setProblem(null); setInitialSource(''); setJob(null); setSubmissions([]); setTurns([]); setError(''); setBusy(false); setTutorBusy(false);
    Promise.all([api.problem(id), waitForDraftSaves(draftKey(id, 'python')).then(() => api.draft(id, 'python')), api.submissions(id), api.chat(id)]).then(([p,d,s,c]) => {
      if (loadRevision.current !== revision) return;
      loadedId.current = id; setProblem(p); setInitialSource(d.source); current.current = { language: 'python', source: d.source }; setSubmissions(s); setTurns(c);
    }).catch((e: Error) => { if (loadRevision.current === revision) setError(e.message); });
    return () => { if (loadRevision.current === revision) loadRevision.current += 1; };
  }, [id]);
  const run = async (mode: 'run' | 'submit', language: Language, source: string) => {
    const routeId = id; if (loadedId.current !== routeId) return; const operation = ++runOperation.current; const active = () => loadedId.current === routeId && runOperation.current === operation;
    setBusy(true); setError(''); setTab('results');
    try {
      const started = await api.startJob(routeId, { mode, language, source }); if (!active()) return; setJob(started);
      const result = await pollJob(() => api.job(started.id)); if (!active()) return; setJob(result);
      if (mode === 'submit') { const history = await api.submissions(routeId); if (!active()) return; const refreshed = await api.problem(routeId); if (!active()) return; setSubmissions(history); setProblem(refreshed); }
      if (result.error && active()) setError(result.error);
    } catch (e) { if (active()) setError((e as Error).message); }
    finally { if (active()) setBusy(false); }
  };
  const tutor = async (mode: TutorMode, message: string) => {
    const routeId = id; const operation = ++tutorOperation.current; const active = () => loadedId.current === routeId && tutorOperation.current === operation;
    setTutorBusy(true); setError('');
    try { await api.tutor(routeId, { mode, message, language: current.current.language, source: current.current.source }); if (!active()) return; const history = await api.chat(routeId); if (active()) setTurns(history); }
    catch (e) { if (active()) setError((e as Error).message); throw e; }
    finally { if (active()) setTutorBusy(false); }
  };
  const resize = (event: React.PointerEvent) => { const target = event.currentTarget.parentElement!; event.currentTarget.setPointerCapture(event.pointerId); const move = (next: PointerEvent) => { const rect = target.getBoundingClientRect(); setSplit(Math.min(68, Math.max(28, ((next.clientX - rect.left) / rect.width) * 100))); }; const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); }; window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); };
  if (!problem) return <div className="workspace-loading">{error || '작업공간을 준비하는 중…'}</div>;
  const publicTests = problem.tests.filter((item) => item.kind === 'public');
  return <div className="workspace-page">
    <header className="workspace-header"><div className="workspace-title"><Link aria-label="문제 목록" to="/"><ArrowLeft /></Link><div><span className="eyebrow">PRACTICE WORKSPACE</span><h1>{problem.title}</h1></div><StatusBadge status={problem.status} />{problem.is_solved && <span className="status-badge status-solved" title="전체 통과한 제출 기록이 있습니다.">풀이 완료</span>}</div><div className="workspace-meta"><span>{problem.time_limit_ms.toLocaleString()} ms</span><span>{problem.memory_limit_mb} MB</span><Link to={`/problems/${id}/edit`} className="button ghost"><Edit3 size={16} /> 문제 편집</Link><button className={`button tutor-toggle ${tutorOpen ? 'active' : ''}`} onClick={() => setTutorOpen(!tutorOpen)}><Bot size={17} /> 풀이 도우미</button></div></header>
    {error && <div className="workspace-alert"><XCircle size={17} />{error}<button onClick={() => setError('')}>닫기</button></div>}
    <div className="workspace-content" style={{ gridTemplateColumns: `${split}% 6px 1fr` }}>
      <section className="statement-pane"><div className="statement-scroll">
        <section className="problem-section"><h2>문제 설명</h2><div className="problem-markdown"><ReactMarkdown remarkPlugins={markdownPlugins}>{problem.statement}</ReactMarkdown></div></section>
        <section className="problem-section"><h2>제한사항</h2>{problem.constraints.length > 0 ? <ul>{problem.constraints.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p className="empty-copy">등록된 제한사항이 없습니다.</p>}</section>
        <section className="problem-section"><h2>입출력 예</h2><div className="example-table-wrap"><table className="example-table" aria-label="입출력 예"><thead><tr>{problem.signature.parameters.map((param) => <th key={param.name} scope="col">{param.name}</th>)}<th scope="col">result</th></tr></thead><tbody>{publicTests.map((test) => <tr key={test.id}>{problem.signature.parameters.map((param, index) => <td key={`${test.id}-${param.name}-${index}`}><code>{index < test.args.length ? displayValue(test.args[index]) : '—'}</code></td>)}<td><code>{displayValue(test.expected)}</code></td></tr>)}</tbody></table>{publicTests.length === 0 && <p className="empty-copy">등록된 공개 예제가 없습니다.</p>}</div></section>
        <section className="problem-section"><h2>입출력 예 설명</h2>{problem.example_explanation.trim() ? <div className="problem-markdown"><ReactMarkdown remarkPlugins={markdownPlugins}>{problem.example_explanation}</ReactMarkdown></div> : <p className="empty-copy">등록된 입출력 예 설명이 없습니다.</p>}</section>
        <details className="function-details"><summary>함수 정보</summary><div className="signature-card"><div><span>매개변수</span>{problem.signature.parameters.map((param) => <code key={param.name}>{param.name}: {typeLabel(param.type)}</code>)}</div><div><span>반환</span><code>{typeLabel(problem.signature.return_type)}</code></div></div></details>
      </div></section>
      <div className="resize-handle" role="separator" aria-label="문제와 코드 너비 조절" onPointerDown={resize} />
      <div className="right-workspace"><div className="editor-slot"><CodeWorkspace key={id} problemId={id} initialLanguage="python" initialSource={initialSource} onSaveDraft={(language, source) => api.saveDraft(id, language, source)} onLoadDraft={async (language) => (await api.draft(id, language)).source} onRun={(language, source) => run('run', language, source)} onSubmit={(language, source) => run('submit', language, source)} submitDisabled={problem.status !== 'ready'} busy={busy} onLanguageChange={(language, source) => { current.current = { language, source }; }} onSaveError={(message) => { if (loadedId.current === id) setError(message); }} /></div>
        <BottomDock tab={tab} setTab={setTab} problem={problem} job={job} submissions={submissions} busy={busy} reload={reloadProblem} />
      </div>
    </div>
    <TutorDrawer key={id} open={tutorOpen} turns={turns} busy={tutorBusy} onClose={() => setTutorOpen(false)} onSend={tutor} />
  </div>;
}

function BottomDock({ tab, setTab, problem, job, submissions, busy, reload }: { tab: DockTab; setTab: (tab: DockTab) => void; problem: Problem; job: Job | null; submissions: Job[]; busy: boolean; reload: () => Promise<void> }) {
  const [expanded, setExpanded] = useState(true); const [source, setSource] = useState<Job | null>(null);
  return <section className={`bottom-dock ${expanded ? '' : 'collapsed'}`}><header><nav>{([['tests', <FlaskConical size={15} />, '테스트'], ['results', <Terminal size={15} />, '실행 결과'], ['history', <History size={15} />, '제출 기록']] as const).map(([id, icon, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => { setTab(id); setExpanded(true); }}>{icon}{label}{id === 'results' && busy && <i className="mini-spinner" />}</button>)}</nav><button className="dock-toggle" onClick={() => setExpanded(!expanded)}>{expanded ? '접기' : '펼치기'}</button></header>
    {expanded && <div className="dock-content">{tab === 'tests' && <TestsPanel problem={problem} reload={reload} />}{tab === 'results' && <ResultsPanel job={job} />}{tab === 'history' && <HistoryPanel jobs={submissions} onSource={setSource} />}</div>}
    {source && <div className="source-overlay"><header><div><strong>{languageLabel(source.language)}</strong><span>{formatDate(source.created_at)} · 테스트 v{source.test_revision}</span></div><button className="icon-button" aria-label="제출 코드 닫기" onClick={() => setSource(null)}><XCircle /></button></header><pre><code>{source.source}</code></pre></div>}
  </section>;
}

function TestsPanel({ problem, reload }: { problem: Problem; reload: () => Promise<void> }) {
  const [adding, setAdding] = useState(false); const [args, setArgs] = useState('[]'); const [expected, setExpected] = useState('null'); const [computed, setComputed] = useState<unknown>(undefined); const [error, setError] = useState('');
  const parseArgs = () => { const value = parseJsonValue(args); if (!Array.isArray(value)) throw new Error('args는 JSON 배열이어야 합니다.'); return value; };
  const compute = async () => { try { const result = await api.expected(problem.id, { args: parseArgs(), current_expected: expected.trim() ? parseJsonValue(expected) : null }); setComputed(result.computed); } catch (e) { setError((e as Error).message); } };
  const add = async () => { try { await api.createTest(problem.id, { kind: 'user', args: parseArgs(), expected: parseJsonValue(expected) }); setAdding(false); setComputed(undefined); await reload(); } catch (e) { setError((e as Error).message); } };
  return <div className="tests-panel"><div className="test-list">{problem.tests.map((test, index) => <TestRow key={test.id} test={test} index={index} problemId={problem.id} reload={reload} />)}<button className="add-case" onClick={() => setAdding(true)}><Plus size={16} /> 사용자 테스트 추가</button></div>{adding && <div className="case-composer"><div className="composer-head"><div><strong>새 테스트</strong><p>long 값은 정밀도 보존을 위해 문자열로 입력하세요.</p></div><button className="icon-button" onClick={() => setAdding(false)}><XCircle /></button></div><div className="test-fields"><label>args<textarea value={args} onChange={(e) => setArgs(e.target.value)} /></label><label>expected<textarea value={expected} onChange={(e) => { setExpected(e.target.value); setComputed(undefined); }} /></label></div>{computed !== undefined && <div className="computed-value"><span>계산된 기대값</span><code>{JSON.stringify(computed)}</code><button onClick={() => setExpected(JSON.stringify(computed))}>이 값 적용</button></div>}{error && <small className="field-error">{error}</small>}<div className="inline-actions"><button className="button ghost" disabled={problem.status !== 'ready'} onClick={() => void compute()}><Braces size={16} /> 기대값 계산</button><button className="button primary" onClick={() => void add()}>테스트 저장</button></div></div>}</div>;
}

function TestRow({ test, index, problemId, reload }: { test: TestCase; index: number; problemId: string; reload: () => Promise<void> }) {
  const [editing, setEditing] = useState(false); const [args, setArgs] = useState(JSON.stringify(test.args)); const [expected, setExpected] = useState(JSON.stringify(test.expected)); const [error, setError] = useState('');
  const save = async () => { try { const a = parseJsonValue(args); if (!Array.isArray(a)) throw new Error('args는 JSON 배열이어야 합니다.'); await api.updateTest(problemId, test.id, { args: a, expected: parseJsonValue(expected) }); setEditing(false); await reload(); } catch (e) { setError((e as Error).message); } };
  const remove = async () => { try { setError(''); await api.deleteTest(problemId, test.id); await reload(); } catch (e) { setError((e as Error).message); } };
  if (editing) return <div className="inline-case-edit"><div className="test-fields"><label>args<textarea value={args} onChange={(e) => setArgs(e.target.value)} /></label><label>expected<textarea value={expected} onChange={(e) => setExpected(e.target.value)} /></label></div>{error && <small className="field-error">{error}</small>}<div className="inline-actions"><button className="button subtle" onClick={() => setEditing(false)}>취소</button><button className="button primary" onClick={() => void save()}>저장</button></div></div>;
  return <><div className="case-row"><span className={`case-kind ${test.kind}`}>{test.kind === 'public' ? '공개' : '사용자'}</span><strong>테스트 {index + 1}</strong><code>{JSON.stringify(test.args)}</code><span>→</span><code>{JSON.stringify(test.expected)}</code><button className="text-button" onClick={() => setEditing(true)}>편집</button>{test.kind === 'user' && <button className="icon-button danger" aria-label={`테스트 ${index + 1} 삭제`} onClick={() => void remove()}><XCircle size={15} /></button>}</div>{error && <small className="field-error">{error}</small>}</>;
}

function ResultsPanel({ job }: { job: Job | null }) {
  if (!job) return <div className="empty compact"><Terminal /><strong>코드를 실행하면 결과가 여기에 표시됩니다</strong></div>;
  if (['queued','running'].includes(job.status)) return <div className="job-running"><i className="spinner" /><div><strong>{job.mode === 'submit' ? '제출을 채점하고 있습니다' : '테스트를 실행하고 있습니다'}</strong><p>격리된 환경에서 각 테스트를 확인합니다.</p></div></div>;
  return <div className="results-panel">{job.summary && <div className={`result-summary ${job.summary.all_passed ? 'passed' : 'failed'}`}>{job.summary.all_passed ? <CheckCircle2 /> : <XCircle />}<div><strong>{job.summary.all_passed ? '모든 테스트를 통과했습니다' : `${job.summary.passed} / ${job.summary.total} 테스트 통과`}</strong><p>최대 {job.summary.max_time_ms.toFixed(1)} ms · {(job.summary.max_memory_kb / 1024).toFixed(1)} MB</p></div></div>}{job.error && <div className="notice error">{job.error}</div>}<div className="result-list">{(job.results ?? []).map((result, i) => <details key={result.id} className={`result-row result-${result.status}`}><summary><span>{result.status === 'passed' ? <CheckCircle2 /> : <XCircle />}</span><strong>테스트 {i + 1}</strong><StatusBadge status={result.status} /><em>{result.time_ms.toFixed(1)} ms · {(result.memory_kb / 1024).toFixed(1)} MB</em></summary>{result.visibility !== 'hidden' ? <div className="result-detail"><div><span>기대값</span><code>{JSON.stringify(result.expected)}</code></div><div><span>실제값</span><code>{JSON.stringify(result.actual)}</code></div>{result.stdout && <div className="result-log"><span>출력</span><pre>{result.stdout}</pre></div>}{result.stderr && <div className="result-log stderr"><span>오류 출력</span><pre>{result.stderr}</pre></div>}</div> : <p className="hidden-note">히든 테스트의 입력과 출력은 공개되지 않습니다.</p>}</details>)}</div></div>;
}

function HistoryPanel({ jobs, onSource }: { jobs: Job[]; onSource: (job: Job) => void }) {
  if (!jobs.length) return <div className="empty compact"><Clock3 /><strong>아직 제출 기록이 없습니다</strong><p>실행 기록은 현재 세션에만 표시됩니다.</p></div>;
  return <div className="history-list">{jobs.map((item) => <button key={item.id} onClick={() => onSource(item)}><span className={item.summary?.all_passed ? 'history-mark passed' : 'history-mark failed'}>{item.summary?.all_passed ? '✓' : '×'}</span><div><strong>{item.summary ? `${item.summary.passed} / ${item.summary.total} 통과` : statusLabels[item.status]}</strong><p>{languageLabel(item.language)} · 테스트 v{item.test_revision}</p></div><time>{formatDate(item.created_at)}</time><code>코드 보기</code></button>)}</div>;
}
