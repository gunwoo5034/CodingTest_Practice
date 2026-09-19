import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LibraryPage } from './LibraryPage';

const mocks = vi.hoisted(() => ({ problems: vi.fn(), folders: vi.fn(), createFolder: vi.fn(), updateFolder: vi.fn(), deleteFolder: vi.fn(), moveProblem: vi.fn(), deleteProblem: vi.fn() }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: mocks }));

const folders = [{ id: 'algo', name: '알고리즘', problem_count: 1 }, { id: 'data', name: '자료구조', problem_count: 0 }];
const summaries = [
  { id: 'solved', title: '완료한 문제', status: 'ready' as const, test_revision: 2, updated_at: '2026-01-01T00:00:00Z', is_solved: true, folder_id: 'algo' },
  { id: 'open', title: '도전할 문제', status: 'ready' as const, test_revision: 1, updated_at: '2026-01-01T00:00:00Z', is_solved: false, folder_id: null },
];
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }

describe('LibraryPage folders', () => {
  beforeEach(() => { vi.resetAllMocks(); mocks.problems.mockResolvedValue(summaries); mocks.folders.mockResolvedValue(folders); });

  it('combines a folder selection with the solved filter', async () => {
    render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    await screen.findByRole('heading', { name: '완료한 문제' });
    fireEvent.click(screen.getByRole('button', { name: '알고리즘 1' }));
    fireEvent.click(screen.getByRole('button', { name: '풀이 완료' }));
    expect(screen.getByRole('heading', { name: '완료한 문제' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '도전할 문제' })).not.toBeInTheDocument();
    expect(screen.getByTitle('전체 통과한 제출 기록이 있습니다.')).toHaveTextContent('풀이 완료');
  });

  it('keeps a folder name editable when creation fails', async () => {
    mocks.createFolder.mockRejectedValue(new Error('같은 이름의 폴더가 있습니다.'));
    const user = userEvent.setup(); render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    await screen.findByRole('heading', { name: '완료한 문제' });
    await user.click(screen.getByRole('button', { name: '폴더 추가' }));
    const input = screen.getByRole('textbox', { name: '폴더 이름' });
    await user.type(input, '그리디');
    await user.click(screen.getByRole('button', { name: '폴더 만들기' }));
    expect(await screen.findByText('같은 이름의 폴더가 있습니다.')).toBeInTheDocument();
    expect(input).toHaveValue('그리디');
  });

  it('traps focus, closes with Escape, and restores focus to the opener', async () => {
    const user = userEvent.setup(); render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    await screen.findByRole('heading', { name: '완료한 문제' });
    const opener = screen.getByRole('button', { name: '폴더 추가' });
    await user.click(opener);
    const dialog = screen.getByRole('dialog'); const close = screen.getByRole('button', { name: '폴더 창 닫기' }); const save = screen.getByRole('button', { name: '폴더 만들기' });
    save.focus(); fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(close).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('focuses a control in the delete dialog and restores the live folder menu button', async () => {
    const user = userEvent.setup(); render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    await screen.findByRole('heading', { name: '완료한 문제' });
    const opener = screen.getByRole('button', { name: '알고리즘 폴더 관리' });
    await user.click(opener);
    await user.click(screen.getByRole('button', { name: '삭제' }));
    const dialog = screen.getByRole('dialog');
    expect(screen.getByRole('button', { name: '폴더 창 닫기' })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('renames and deletes a folder while explaining that its problems stay', async () => {
    mocks.updateFolder.mockResolvedValue({ id: 'algo', name: '동적 계획법', problem_count: 1 });
    mocks.deleteFolder.mockResolvedValue(undefined);
    mocks.folders.mockResolvedValueOnce(folders).mockResolvedValueOnce([{ id: 'data', name: '자료구조', problem_count: 0 }]);
    mocks.problems.mockResolvedValueOnce(summaries).mockResolvedValueOnce(summaries.map((item) => item.id === 'solved' ? { ...item, folder_id: null } : item));
    const user = userEvent.setup(); render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    await screen.findByRole('heading', { name: '완료한 문제' });
    await user.click(screen.getByRole('button', { name: '알고리즘 폴더 관리' }));
    await user.click(screen.getByRole('button', { name: '이름 변경' }));
    const rename = screen.getByRole('textbox', { name: '폴더 이름' });
    await user.clear(rename); await user.type(rename, '동적 계획법');
    await user.click(screen.getByRole('button', { name: '이름 저장' }));
    expect(await screen.findByRole('button', { name: '동적 계획법 1' })).toBeInTheDocument();
    const renamedOpener = screen.getByRole('button', { name: '동적 계획법 폴더 관리' });
    expect(renamedOpener).toHaveFocus();
    await user.click(renamedOpener);
    await user.click(screen.getByRole('button', { name: '삭제' }));
    expect(screen.getByText(/문제는 삭제되지 않고 미분류로 이동합니다/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '폴더 삭제' }));
    await waitFor(() => expect(mocks.deleteFolder).toHaveBeenCalledWith('algo'));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: '폴더 추가' })).toHaveFocus();
  });

  it('moves a problem using the card folder selector', async () => {
    const move = deferred<Record<string, unknown>>(); mocks.moveProblem.mockReturnValue(move.promise); mocks.folders.mockResolvedValueOnce(folders).mockResolvedValueOnce(folders);
    const user = userEvent.setup(); render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    await screen.findByRole('heading', { name: '도전할 문제' });
    const selector = screen.getByRole('combobox', { name: '도전할 문제 폴더 이동' });
    await user.selectOptions(selector, 'data');
    await waitFor(() => expect(mocks.moveProblem).toHaveBeenCalledWith('open', 'data'));
    expect(selector).toBeDisabled();
    move.resolve({ ...summaries[1], folder_id: 'data' });
    await waitFor(() => expect(selector).toBeEnabled());
    expect(selector).toHaveValue('data');
  });
});
