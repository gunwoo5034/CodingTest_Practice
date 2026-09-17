import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkspacePage } from './WorkspacePage';

const mocks = vi.hoisted(() => ({ problem: vi.fn(), draft: vi.fn(), submissions: vi.fn(), chat: vi.fn(), startJob: vi.fn(), job: vi.fn(), tutor: vi.fn(), deleteTest: vi.fn() }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: mocks }));
vi.mock('../components/CodeWorkspace', () => ({ CodeWorkspace: ({ initialSource, onRun }: { initialSource: string; onRun: (language: 'python', source: string) => Promise<unknown> }) => <div data-testid="editor-source">{initialSource}<button onClick={() => void onRun('python', initialSource)}>mock run</button></div> }));
vi.mock('../components/TutorDrawer', () => ({ TutorDrawer: ({ onSend }: { onSend: (mode: 'hint', message: string) => Promise<void> }) => <button onClick={() => void onSend('hint', '도와줘').catch(() => undefined)}>mock tutor</button> }));

function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void; const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }
const makeProblem = (id: string, title: string) => ({ id, title, status: 'ready' as const, test_revision: 1, updated_at: '2026-01-01T00:00:00Z', statement: title, constraints: [], signature: { parameters: [{ name: 'n', type: { base: 'int' as const, dimensions: 0 as const } }], return_type: { base: 'int' as const, dimensions: 0 as const } }, templates: { python: 'same' }, time_limit_ms: 2000, memory_limit_mb: 256, tests: [] });

describe('WorkspacePage route identity', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.submissions.mockResolvedValue([]); mocks.chat.mockResolvedValue([]); mocks.draft.mockResolvedValue({ source: '' }); });
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
});
