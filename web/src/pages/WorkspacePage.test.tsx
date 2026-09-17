import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkspacePage } from './WorkspacePage';

const mocks = vi.hoisted(() => ({ problem: vi.fn(), draft: vi.fn(), submissions: vi.fn(), chat: vi.fn() }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: { problem: mocks.problem, draft: mocks.draft, submissions: mocks.submissions, chat: mocks.chat } }));
vi.mock('../components/CodeWorkspace', () => ({ CodeWorkspace: ({ initialSource }: { initialSource: string }) => <div data-testid="editor-source">{initialSource}</div> }));

function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }
const makeProblem = (id: string, title: string) => ({ id, title, status: 'ready' as const, test_revision: 1, updated_at: '2026-01-01T00:00:00Z', statement: title, constraints: [], signature: { parameters: [{ name: 'n', type: { base: 'int' as const, dimensions: 0 as const } }], return_type: { base: 'int' as const, dimensions: 0 as const } }, templates: { python: 'same' }, time_limit_ms: 2000, memory_limit_mb: 256, tests: [] });

describe('WorkspacePage route identity', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.submissions.mockResolvedValue([]); mocks.chat.mockResolvedValue([]); });
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
});
