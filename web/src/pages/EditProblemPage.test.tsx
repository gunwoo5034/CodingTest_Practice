import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EditProblemPage } from './EditProblemPage';

const mocks = vi.hoisted(() => ({ problem: vi.fn(), updateProblem: vi.fn(), updateTest: vi.fn(), createTest: vi.fn(), deleteTest: vi.fn(), generate: vi.fn() }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: mocks }));
const problem = { id: 'p1', title: '합계', status: 'analyzed' as const, test_revision: 1, updated_at: '2026-01-01T00:00:00Z', statement: '설명', constraints: ['n > 0'], signature: { parameters: [{ name: 'n', type: { base: 'int' as const, dimensions: 0 as const } }], return_type: { base: 'int' as const, dimensions: 0 as const } }, templates: { python: '' }, time_limit_ms: 2000, memory_limit_mb: 256, tests: [{ id: 't1', kind: 'public' as const, position: 0, args: [1], expected: 1, suite_version: 1 }] };
const renderPage = () => render(<MemoryRouter initialEntries={['/problems/p1/edit']}><Routes><Route path="/problems/:id/edit" element={<EditProblemPage />} /></Routes></MemoryRouter>);

describe('EditProblemPage examples', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.problem.mockResolvedValue(problem); mocks.updateProblem.mockResolvedValue(problem); mocks.createTest.mockResolvedValue(problem.tests[0]); });
  it('blocks generation while a visible example has unsaved edits', async () => {
    renderPage();
    const args = await screen.findByLabelText('args');
    fireEvent.change(args, { target: { value: '[2]' } });
    expect(screen.getByRole('button', { name: '테스트 준비 시작' })).toBeDisabled();
    expect(screen.getByText(/저장하지 않은 예제/)).toBeInTheDocument();
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it('creates an added extracted example as public', async () => {
    const user = userEvent.setup(); renderPage();
    await screen.findByText('공개 예제');
    await user.click(screen.getByRole('button', { name: '예제 추가' }));
    const editor = screen.getByText('추가').closest('.test-editor') as HTMLElement;
    fireEvent.change(within(editor).getByLabelText('args'), { target: { value: '[3]' } });
    fireEvent.change(within(editor).getByLabelText('expected'), { target: { value: '3' } });
    await user.click(within(editor).getByRole('button', { name: '추가' }));
    await waitFor(() => expect(mocks.createTest).toHaveBeenCalledWith('p1', { kind: 'public', args: [3], expected: 3 }));
  });
});
