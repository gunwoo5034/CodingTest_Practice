import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NewProblemPage } from './NewProblemPage';

const mocks = vi.hoisted(() => ({ folders: vi.fn(), createProblem: vi.fn(), analyze: vi.fn() }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: mocks }));

describe('NewProblemPage folder assignment', () => {
  beforeEach(() => { vi.resetAllMocks(); mocks.folders.mockResolvedValue([{ id: 'algo', name: '알고리즘', problem_count: 0 }]); mocks.createProblem.mockResolvedValue({ id: 'created' }); mocks.analyze.mockResolvedValue({ id: 'analyzed' }); });

  it('includes the chosen folder in manual creation', async () => {
    render(<MemoryRouter><NewProblemPage /></MemoryRouter>);
    fireEvent.change(await screen.findByRole('combobox', { name: '저장할 폴더' }), { target: { value: 'algo' } });
    fireEvent.change(screen.getByLabelText('문제 텍스트'), { target: { value: '두 수 더하기\n설명' } });
    fireEvent.click(screen.getByRole('button', { name: '직접 입력으로 등록' }));
    await waitFor(() => expect(mocks.createProblem).toHaveBeenCalledWith(expect.objectContaining({ folder_id: 'algo' })));
  });

  it('includes the chosen folder in AI analysis without starting automatically', async () => {
    render(<MemoryRouter><NewProblemPage /></MemoryRouter>);
    fireEvent.change(await screen.findByRole('combobox', { name: '저장할 폴더' }), { target: { value: 'algo' } });
    fireEvent.change(screen.getByLabelText('문제 텍스트'), { target: { value: '분석할 문제' } });
    expect(mocks.analyze).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'AI로 구조 분석' }));
    await waitFor(() => expect(mocks.analyze).toHaveBeenCalledWith(expect.objectContaining({ folder_id: 'algo' })));
  });

  it('waits for a folder query to resolve before allowing registration', async () => {
    let resolveFolders!: (value: Array<{ id: string; name: string; problem_count: number }>) => void;
    mocks.folders.mockReturnValue(new Promise((resolve) => { resolveFolders = resolve; }));
    render(<MemoryRouter initialEntries={['/?folder=algo']}><NewProblemPage /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('문제 텍스트'), { target: { value: '두 수 더하기' } });
    const create = screen.getByRole('button', { name: '직접 입력으로 등록' });
    expect(create).toBeDisabled();
    fireEvent.click(create);
    expect(mocks.createProblem).not.toHaveBeenCalled();
    resolveFolders([{ id: 'algo', name: '알고리즘', problem_count: 0 }]);
    await waitFor(() => expect(create).toBeEnabled());
    fireEvent.click(create);
    await waitFor(() => expect(mocks.createProblem).toHaveBeenCalledWith(expect.objectContaining({ folder_id: 'algo' })));
  });

  it('offers a retry when folders cannot be loaded', async () => {
    mocks.folders.mockRejectedValueOnce(new Error('폴더를 불러올 수 없습니다.')).mockResolvedValueOnce([{ id: 'algo', name: '알고리즘', problem_count: 0 }]);
    const user = userEvent.setup(); render(<MemoryRouter><NewProblemPage /></MemoryRouter>);
    expect(await screen.findByText('폴더를 불러올 수 없습니다.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '폴더 다시 불러오기' }));
    expect(await screen.findByRole('option', { name: '알고리즘' })).toBeInTheDocument();
    expect(mocks.folders).toHaveBeenCalledTimes(2);
  });
});
