import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from './AppShell';

const mocks = vi.hoisted(() => ({ health: vi.fn().mockResolvedValue({ database: 'ok', runner_available: true, ai_configured: false, detail: '' }) }));
vi.mock('../api/client', async (load) => ({ ...(await load<typeof import('../api/client')>()), api: mocks }));

describe('AppShell navigation', () => {
  it('keeps explicit accessible names when mobile CSS hides the labels', () => {
    render(<MemoryRouter><Routes><Route element={<AppShell />}><Route index element={<div>목록</div>} /></Route></Routes></MemoryRouter>);
    expect(screen.getByRole('link', { name: '문제 목록' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '문제 등록' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '서비스 상태' })).toBeInTheDocument();
  });
});
