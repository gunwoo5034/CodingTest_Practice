import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, MemoryRouter, Route, RouterProvider, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EditProblemPage } from './EditProblemPage';

const mocks = vi.hoisted(() => ({ problem: vi.fn(), folders: vi.fn(), moveProblem: vi.fn(), updateProblem: vi.fn(), updateTest: vi.fn(), createTest: vi.fn(), deleteTest: vi.fn(), generate: vi.fn(), generationJob: vi.fn() }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: mocks }));
const problem = { id: 'p1', title: '합계', status: 'analyzed' as const, test_revision: 1, updated_at: '2026-01-01T00:00:00Z', statement: '설명', example_explanation: '기존 예제 설명', constraints: ['n > 0'], signature: { parameters: [{ name: 'n', type: { base: 'int' as const, dimensions: 0 as const } }], return_type: { base: 'int' as const, dimensions: 0 as const } }, templates: { python: '' }, time_limit_ms: 2000, memory_limit_mb: 256, tests: [{ id: 't1', kind: 'public' as const, position: 0, args: [1], expected: 1, suite_version: 1 }], output_format: null, is_solved: false, folder_id: null };
const problemFor = (id: string) => ({ ...problem, id, title: `문제 ${id.toUpperCase()}`, tests: problem.tests.map((test) => ({ ...test, id: `${id}-test` })) });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }
const renderPage = () => render(<MemoryRouter initialEntries={['/problems/p1/edit']}><Routes><Route path="/problems/:id/edit" element={<EditProblemPage />} /></Routes></MemoryRouter>);

describe('EditProblemPage examples', () => {
  beforeEach(() => { vi.resetAllMocks(); mocks.problem.mockResolvedValue(problem); mocks.folders.mockResolvedValue([{ id: 'algo', name: '알고리즘', problem_count: 0 }]); mocks.updateProblem.mockResolvedValue(problem); mocks.createTest.mockResolvedValue(problem.tests[0]); });
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

  it('does not generate or apply a save after its route changed', async () => {
    const saveA = deferred<typeof problem>();
    mocks.problem.mockImplementation((id: string) => Promise.resolve(problemFor(id)));
    mocks.updateProblem.mockImplementation((id: string) => id === 'a' ? saveA.promise : Promise.resolve(problemFor(id)));
    const router = createMemoryRouter([{ path: '/problems/:id/edit', element: <EditProblemPage /> }], { initialEntries: ['/problems/a/edit'] });
    render(<RouterProvider router={router} />);
    await screen.findByDisplayValue('문제 A');
    fireEvent.click(screen.getByRole('button', { name: '테스트 준비 시작' }));
    await waitFor(() => expect(mocks.updateProblem).toHaveBeenCalledWith('a', expect.anything()));
    await router.navigate('/problems/b/edit');
    expect(await screen.findByDisplayValue('문제 B')).toBeInTheDocument();
    saveA.resolve(problemFor('a'));
    await Promise.resolve(); await Promise.resolve();
    expect(screen.getByDisplayValue('문제 B')).toBeInTheDocument();
    expect(mocks.generate).not.toHaveBeenCalled();
  });

  it('keeps a changed example dirty when deletion fails', async () => {
    mocks.deleteTest.mockRejectedValue(new Error('예제를 삭제할 수 없습니다.'));
    renderPage();
    fireEvent.change(await screen.findByLabelText('args'), { target: { value: '[2]' } });
    fireEvent.click(screen.getByRole('button', { name: '예제 1 삭제' }));
    expect(await screen.findAllByText('예제를 삭제할 수 없습니다.')).not.toHaveLength(0);
    expect(screen.getByText(/저장하지 않은 예제/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '테스트 준비 시작' })).toBeDisabled();
  });

  it('loads and saves the editable example explanation', async () => {
    mocks.updateProblem.mockImplementation((_id: string, body: Record<string, unknown>) => Promise.resolve({ ...problem, example_explanation: body.example_explanation as string }));
    renderPage();
    const explanation = await screen.findByLabelText(/입출력 예 설명/);
    expect(explanation).toHaveValue('기존 예제 설명');
    fireEvent.change(explanation, { target: { value: '수정한 **설명**' } });
    fireEvent.click(screen.getByRole('button', { name: '변경사항 저장' }));
    await waitFor(() => expect(mocks.updateProblem).toHaveBeenCalledWith('p1', expect.objectContaining({ example_explanation: '수정한 **설명**' })));
    expect(screen.getByLabelText(/입출력 예 설명/)).toHaveValue('수정한 **설명**');
  });

  it('moves folders without replacing unsaved problem fields', async () => {
    mocks.moveProblem.mockResolvedValue({ ...problem, folder_id: 'algo' });
    renderPage();
    const title = await screen.findByDisplayValue('합계');
    fireEvent.change(title, { target: { value: '아직 저장하지 않은 제목' } });
    fireEvent.change(screen.getByRole('combobox', { name: '문제 폴더' }), { target: { value: 'algo' } });
    await waitFor(() => expect(mocks.moveProblem).toHaveBeenCalledWith('p1', 'algo'));
    expect(screen.getByDisplayValue('아직 저장하지 않은 제목')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: '문제 폴더' })).toHaveValue('algo');
  });

  it('explains the possible format-repair call without implying expected values change', async () => {
    renderPage();
    expect(await screen.findByText('반환 형식이 맞지 않으면 AI 보정 요청이 최대 1회 추가됩니다. 기대값은 유지됩니다.')).toBeInTheDocument();
  });

  it.each([
    ['concat_decimal', '숫자 이어 붙이기'],
    ['space_separated', '공백 구분'],
    ['comma_separated', '쉼표 구분'],
    ['json_array', 'JSON 배열'],
  ] as const)('shows an installed %s return adaptation on a ready problem', async (outputFormat, label) => {
    mocks.problem.mockResolvedValue({ ...problem, status: 'ready', output_format: outputFormat });
    renderPage();
    expect(await screen.findByText(`반환 표현 보정 적용: ${label}`)).toBeInTheDocument();
  });

  it.each([
    ['ready', null],
    ['ready', 'none'],
    ['analyzed', 'space_separated'],
  ] as const)('does not show an applied adaptation for %s / %s', async (status, outputFormat) => {
    mocks.problem.mockResolvedValue({ ...problem, status, output_format: outputFormat });
    renderPage();
    await screen.findByText('테스트 준비');
    expect(screen.queryByText(/반환 표현 보정 적용:/)).not.toBeInTheDocument();
  });

  it('shows the installed adaptation after generation completes and reloads the problem', async () => {
    mocks.problem.mockResolvedValueOnce({ ...problem, status: 'generating', latest_generation_job_id: 'generation-1' }).mockResolvedValueOnce({ ...problem, status: 'ready', output_format: 'comma_separated' });
    mocks.generationJob.mockResolvedValue({ id: 'generation-1', status: 'completed' });
    renderPage();
    expect(await screen.findByText('반환 표현 보정 적용: 쉼표 구분')).toBeInTheDocument();
    expect(mocks.problem).toHaveBeenCalledTimes(2);
  });
});
