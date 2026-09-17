import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LibraryPage } from './LibraryPage';

const mocks = vi.hoisted(() => ({ problems: vi.fn(), deleteProblem: vi.fn() }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: mocks }));

const summaries = [
  { id: 'solved', title: '완료한 문제', status: 'ready' as const, test_revision: 2, updated_at: '2026-01-01T00:00:00Z', is_solved: true },
  { id: 'open', title: '도전할 문제', status: 'ready' as const, test_revision: 1, updated_at: '2026-01-01T00:00:00Z', is_solved: false },
];

describe('LibraryPage solved state', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.problems.mockResolvedValue(summaries); });

  it('shows solved separately from preparation status and filters by it', async () => {
    render(<MemoryRouter><LibraryPage /></MemoryRouter>);
    await screen.findByRole('heading', { name: '완료한 문제' });
    expect(document.querySelectorAll('.status-badge.status-ready')).toHaveLength(2);
    expect(screen.getByTitle('전체 통과한 제출 기록이 있습니다.')).toHaveTextContent('풀이 완료');
    fireEvent.click(screen.getByRole('button', { name: '풀이 완료' }));
    expect(screen.getByRole('heading', { name: '완료한 문제' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '도전할 문제' })).not.toBeInTheDocument();
  });
});
