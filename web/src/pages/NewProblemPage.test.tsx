import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
});
