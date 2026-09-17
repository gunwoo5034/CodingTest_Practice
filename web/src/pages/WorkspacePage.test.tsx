import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkspacePage } from './WorkspacePage';

const mocks = vi.hoisted(() => ({ problem: vi.fn(), draft: vi.fn(), submissions: vi.fn(), chat: vi.fn(), startJob: vi.fn(), job: vi.fn(), tutor: vi.fn(), deleteTest: vi.fn(), workspaceRuns: new Map<string, (language: 'python', source: string) => Promise<unknown>>(), workspaceSubmits: new Map<string, (language: 'python', source: string) => Promise<unknown>>() }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: mocks }));
vi.mock('../components/CodeWorkspace', () => ({ CodeWorkspace: ({ problemId, initialSource, onRun, onSubmit }: { problemId: string; initialSource: string; onRun: (language: 'python', source: string) => Promise<unknown>; onSubmit: (language: 'python', source: string) => Promise<unknown> }) => { mocks.workspaceRuns.set(problemId, onRun); mocks.workspaceSubmits.set(problemId, onSubmit); return <div data-testid="editor-source">{initialSource}<button onClick={() => void onRun('python', initialSource)}>mock run</button><button onClick={() => void onSubmit('python', initialSource)}>mock submit</button></div>; } }));
vi.mock('../components/TutorDrawer', () => ({ TutorDrawer: ({ onSend }: { onSend: (mode: 'hint', message: string) => Promise<void> }) => <button onClick={() => void onSend('hint', '도와줘').catch(() => undefined)}>mock tutor</button> }));

function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void; const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
const makeProblem = (id: string, title: string) => ({ id, title, status: 'ready' as const, test_revision: 1, updated_at: '2026-01-01T00:00:00Z', statement: title, example_explanation: '', constraints: [], signature: { parameters: [{ name: 'n', type: { base: 'int' as const, dimensions: 0 as const } }], return_type: { base: 'int' as const, dimensions: 0 as const } }, templates: { python: 'same' }, time_limit_ms: 2000, memory_limit_mb: 256, tests: [], output_format: null, is_solved: false });

describe('WorkspacePage route identity', () => {
  beforeEach(() => { vi.resetAllMocks(); mocks.workspaceRuns.clear(); mocks.workspaceSubmits.clear(); mocks.submissions.mockResolvedValue([]); mocks.chat.mockResolvedValue([]); mocks.draft.mockResolvedValue({ source: '' }); });
  it('ignores an older problem load after navigating to another problem', async () => {
    const a = deferred<ReturnType<typeof makeProblem>>(); const b = deferred<ReturnType<typeof makeProblem>>();
    const draftA = deferred<{ source: string }>(); const draftB = deferred<{ source: string }>();
    mocks.problem.mockImplementation((id: string) => id === 'a' ? a.promise : b.promise);
    mocks.draft.mockImplementation((id: string) => id === 'a' ? draftA.promise : draftB.promise);
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    await router.navigate('/problems/b');
    b.resolve(makeProblem('b', '문제 B')); draftB.resolve({ source: 'B source' });
    expect(await screen.findByRole('heading', { level: 1, name: '문제 B' })).toBeInTheDocument();
    expect(screen.getByTestId('editor-source')).toHaveTextContent('B source');
    a.resolve(makeProblem('a', '문제 A')); draftA.resolve({ source: 'A source' });
    await Promise.resolve(); await Promise.resolve();
    expect(screen.queryByText('문제 A')).not.toBeInTheDocument();
    expect(screen.getByTestId('editor-source')).toHaveTextContent('B source');
  });

  it('ignores a completed run and tutor failure from the previous route', async () => {
    const oldJob = deferred<Record<string, unknown>>(); const oldTutor = deferred<never>();
    mocks.problem.mockImplementation((id: string) => Promise.resolve(makeProblem(id, `문제 ${id.toUpperCase()}`)));
    mocks.startJob.mockImplementation((id: string) => Promise.resolve({ id: `${id}-job`, status: 'queued', mode: 'run', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z' }));
    mocks.job.mockImplementation((jobId: string) => jobId === 'a-job' ? oldJob.promise : Promise.resolve({ id: 'b-job', status: 'completed', mode: 'run', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z', summary: { all_passed: true, passed: 1, total: 1, max_time_ms: 1, max_memory_kb: 1 }, results: [] }));
    mocks.tutor.mockImplementation((id: string) => id === 'a' ? oldTutor.promise : Promise.resolve({}));
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    await screen.findByRole('heading', { name: '문제 A' });
    fireEvent.click(screen.getByRole('button', { name: 'mock run' }));
    fireEvent.click(screen.getByRole('button', { name: 'mock tutor' }));
    await router.navigate('/problems/b');
    await screen.findByRole('heading', { name: '문제 B' });
    fireEvent.click(screen.getByRole('button', { name: 'mock run' }));
    expect(await screen.findByText('모든 테스트를 통과했습니다')).toBeInTheDocument();
    oldJob.resolve({ id: 'a-job', status: 'failed', mode: 'run', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z', error: 'A 실행 오류' });
    oldTutor.reject(new Error('A 튜터 오류'));
    await Promise.resolve(); await Promise.resolve();
    expect(screen.queryByText(/A 실행 오류|A 튜터 오류/)).not.toBeInTheDocument();
    expect(screen.getByText('모든 테스트를 통과했습니다')).toBeInTheDocument();
  });

  it('renders a user-test deletion failure', async () => {
    mocks.problem.mockResolvedValue({ ...makeProblem('a', '문제 A'), tests: [{ id: 'user-1', kind: 'user', position: 0, args: [1], expected: 1, suite_version: 1 }] });
    mocks.deleteTest.mockRejectedValue(new Error('테스트 삭제 실패'));
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    fireEvent.click(await screen.findByRole('button', { name: '테스트 1 삭제' }));
    await waitFor(() => expect(screen.getByText('테스트 삭제 실패')).toBeInTheDocument());
  });

  it('rejects a captured run callback after another problem has loaded', async () => {
    mocks.problem.mockImplementation((id: string) => Promise.resolve(makeProblem(id, `문제 ${id.toUpperCase()}`)));
    const currentRun = deferred<Record<string, unknown>>();
    mocks.startJob.mockImplementation((id: string) => id === 'b' ? Promise.resolve({ id: 'b-job', status: 'queued', mode: 'run', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z' }) : Promise.reject(new Error('stale A started')));
    mocks.job.mockReturnValue(currentRun.promise);
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    await screen.findByRole('heading', { name: '문제 A' });
    const staleRun = mocks.workspaceRuns.get('a')!;
    await router.navigate('/problems/b');
    await screen.findByRole('heading', { name: '문제 B' });
    void mocks.workspaceRuns.get('b')!('python', 'B source');
    await waitFor(() => expect(mocks.startJob).toHaveBeenCalledWith('b', expect.anything()));
    await staleRun('python', 'A source');
    expect(mocks.startJob).toHaveBeenCalledTimes(1);
  });

  it('renders ordered problem sections, public examples by parameter name, and GFM explanation', async () => {
    mocks.problem.mockResolvedValue({ ...makeProblem('a', '두 수 계산'), statement: '두 수를 계산하세요.', constraints: ['각 수는 0 이상입니다.'], example_explanation: '| 경우 | 설명 |\n| --- | --- |\n| 1 | 첫 예시 |', signature: { parameters: [{ name: 'left', type: { base: 'int', dimensions: 0 } }, { name: 'right', type: { base: 'int', dimensions: 0 } }], return_type: { base: 'int', dimensions: 0 } }, tests: [{ id: 'public-1', kind: 'public', position: 0, args: [2, 3], expected: 5, suite_version: 1 }, { id: 'user-1', kind: 'user', position: 1, args: [99, 1], expected: 100, suite_version: 1 }] });
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    await screen.findByRole('heading', { name: '두 수 계산' });
    const sectionHeadings = screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent);
    expect(sectionHeadings.slice(0, 4)).toEqual(['문제 설명', '제한사항', '입출력 예', '입출력 예 설명']);
    const examples = screen.getByRole('table', { name: '입출력 예' });
    expect(within(examples).getByRole('columnheader', { name: 'left' })).toBeInTheDocument();
    expect(within(examples).getByRole('columnheader', { name: 'right' })).toBeInTheDocument();
    expect(within(examples).getByRole('columnheader', { name: 'result' })).toBeInTheDocument();
    expect(within(examples).getByText('2')).toBeInTheDocument();
    expect(within(examples).queryByText('99')).not.toBeInTheDocument();
    const tables = screen.getAllByRole('table');
    expect(tables).toHaveLength(2);
    expect(within(tables[1]).getByRole('columnheader', { name: '경우' })).toBeInTheDocument();
    expect(within(tables[1]).getByRole('columnheader', { name: '설명' })).toBeInTheDocument();
  });

  it('shows an honest state when no example explanation was stored', async () => {
    mocks.problem.mockResolvedValue(makeProblem('a', '설명 없는 문제'));
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    expect(await screen.findByText('등록된 입출력 예 설명이 없습니다.')).toBeInTheDocument();
  });

  it('labels logs separately while preserving real newlines and literal backslash-n text', async () => {
    const stdout = 'first line\nsecond line\n\\n\n'; const stderr = 'error line\n\\n';
    mocks.problem.mockResolvedValue(makeProblem('a', '로그 문제'));
    mocks.startJob.mockResolvedValue({ id: 'job', status: 'queued', mode: 'run', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z' });
    mocks.job.mockResolvedValue({ id: 'job', status: 'completed', mode: 'run', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z', summary: { all_passed: true, passed: 1, total: 1, max_time_ms: 1, max_memory_kb: 1 }, results: [{ id: 'result', visibility: 'public', status: 'passed', expected: 1, actual: 1, stdout, stderr, time_ms: 1, memory_kb: 1 }] });
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    fireEvent.click(await screen.findByRole('button', { name: 'mock run' }));
    const outputLabel = await screen.findByText('출력'); const errorLabel = screen.getByText('오류 출력');
    expect(outputLabel.parentElement?.querySelector('pre')?.textContent).toBe(stdout);
    expect(errorLabel.parentElement?.querySelector('pre')?.textContent).toBe(stderr);
  });

  it('refreshes solved state after a completed submit but not after a run', async () => {
    mocks.problem.mockResolvedValueOnce(makeProblem('a', '제출 문제')).mockResolvedValueOnce({ ...makeProblem('a', '제출 문제'), is_solved: true });
    mocks.startJob.mockImplementation((_id: string, body: { mode: string }) => Promise.resolve({ id: `${body.mode}-job`, status: 'queued', mode: body.mode, language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z' }));
    mocks.job.mockResolvedValue({ id: 'job', status: 'completed', mode: 'submit', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z', summary: { all_passed: true, passed: 1, total: 1, max_time_ms: 1, max_memory_kb: 1 }, results: [] });
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    await screen.findByRole('heading', { name: '제출 문제' });
    await mocks.workspaceRuns.get('a')!('python', 'run source');
    expect(mocks.problem).toHaveBeenCalledTimes(1);
    expect(screen.queryByTitle('전체 통과한 제출 기록이 있습니다.')).not.toBeInTheDocument();
    await mocks.workspaceSubmits.get('a')!('python', 'submit source');
    expect(await screen.findByTitle('전체 통과한 제출 기록이 있습니다.')).toHaveTextContent('풀이 완료');
    expect(mocks.problem).toHaveBeenCalledTimes(2);
  });

  it('keeps a solved refresh when submission history refresh fails', async () => {
    mocks.problem.mockResolvedValueOnce(makeProblem('a', '제출 문제')).mockResolvedValueOnce({ ...makeProblem('a', '제출 문제'), is_solved: true });
    mocks.submissions.mockResolvedValueOnce([]).mockRejectedValueOnce(new Error('제출 기록을 불러오지 못했습니다'));
    mocks.startJob.mockResolvedValue({ id: 'submit-job', status: 'queued', mode: 'submit', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z' });
    mocks.job.mockResolvedValue({ id: 'submit-job', status: 'completed', mode: 'submit', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z', summary: { all_passed: true, passed: 1, total: 1, max_time_ms: 1, max_memory_kb: 1 }, results: [] });
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    await screen.findByRole('heading', { name: '제출 문제' });
    await mocks.workspaceSubmits.get('a')!('python', 'submit source');
    expect(await screen.findByTitle('전체 통과한 제출 기록이 있습니다.')).toHaveTextContent('풀이 완료');
    expect(screen.getByText('제출 기록을 불러오지 못했습니다')).toBeInTheDocument();
  });

  it('keeps refreshed submission history when solved-state refresh fails', async () => {
    const submission = { id: 'history-job', status: 'completed', mode: 'submit', language: 'python', source: 'submitted source', test_revision: 1, created_at: '2026-01-01T00:00:00Z', summary: { all_passed: true, passed: 1, total: 1, max_time_ms: 1, max_memory_kb: 1 }, results: [] };
    mocks.problem.mockResolvedValueOnce(makeProblem('a', '제출 문제')).mockRejectedValueOnce(new Error('완료 상태를 불러오지 못했습니다'));
    mocks.submissions.mockResolvedValueOnce([]).mockResolvedValueOnce([submission]);
    mocks.startJob.mockResolvedValue({ ...submission, status: 'queued' });
    mocks.job.mockResolvedValue(submission);
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    await screen.findByRole('heading', { name: '제출 문제' });
    await mocks.workspaceSubmits.get('a')!('python', 'submit source');
    fireEvent.click(screen.getByRole('button', { name: '제출 기록' }));
    expect(screen.getByText('1 / 1 통과')).toBeInTheDocument();
    expect(screen.getByText('완료 상태를 불러오지 못했습니다')).toBeInTheDocument();
  });

  it('does not apply a late solved refresh from the previous problem', async () => {
    const lateSolved = deferred<ReturnType<typeof makeProblem>>();
    const lateHistory = deferred<Array<Record<string, unknown>>>();
    let deferARefresh = false;
    mocks.problem.mockImplementation((id: string) => id === 'a' && deferARefresh ? lateSolved.promise : Promise.resolve(makeProblem(id, `문제 ${id.toUpperCase()}`)));
    mocks.submissions.mockImplementation((id: string) => id === 'a' && deferARefresh ? lateHistory.promise : Promise.resolve(id === 'b' ? [{ id: 'b-history', status: 'completed', mode: 'submit', language: 'python', source: 'B source', test_revision: 1, created_at: '2026-01-01T00:00:00Z', summary: { all_passed: false, passed: 0, total: 1, max_time_ms: 1, max_memory_kb: 1 }, results: [] }] : []));
    mocks.startJob.mockResolvedValue({ id: 'submit-job', status: 'queued', mode: 'submit', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z' });
    mocks.job.mockResolvedValue({ id: 'submit-job', status: 'completed', mode: 'submit', language: 'python', source: '', test_revision: 1, created_at: '2026-01-01T00:00:00Z', summary: { all_passed: true, passed: 1, total: 1, max_time_ms: 1, max_memory_kb: 1 }, results: [] });
    const router = createMemoryRouter([{ path: '/problems/:id', element: <WorkspacePage /> }], { initialEntries: ['/problems/a'] });
    render(<RouterProvider router={router} />);
    await screen.findByRole('heading', { name: '문제 A' });
    deferARefresh = true;
    const submitA = mocks.workspaceSubmits.get('a')!('python', 'source');
    await waitFor(() => expect(mocks.problem).toHaveBeenCalledTimes(2));
    await router.navigate('/problems/b');
    await screen.findByRole('heading', { name: '문제 B' });
    lateSolved.resolve({ ...makeProblem('a', '문제 A'), is_solved: true });
    lateHistory.resolve([{ id: 'a-history', status: 'completed', mode: 'submit', language: 'python', source: 'A source', test_revision: 1, created_at: '2026-01-01T00:00:00Z', summary: { all_passed: true, passed: 1, total: 1, max_time_ms: 1, max_memory_kb: 1 }, results: [] }]);
    await submitA;
    expect(screen.getByRole('heading', { name: '문제 B' })).toBeInTheDocument();
    expect(screen.queryByTitle('전체 통과한 제출 기록이 있습니다.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '제출 기록' }));
    expect(screen.getByText('0 / 1 통과')).toBeInTheDocument();
    expect(screen.queryByText('1 / 1 통과')).not.toBeInTheDocument();
  });
});
