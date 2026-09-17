import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TutorDrawer } from './TutorDrawer';

describe('TutorDrawer', () => {
  it('does not call AI until the user sends a message', async () => {
    const user = userEvent.setup();
    const send = vi.fn().mockResolvedValue(undefined);
    render(<TutorDrawer open turns={[]} onClose={vi.fn()} onSend={send} busy={false} />);
    expect(send).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText('도우미에게 보낼 내용'), '첫 단서가 필요해요');
    await user.click(screen.getByRole('button', { name: '질문 보내기' }));
    expect(send).toHaveBeenCalledWith('hint', '첫 단서가 필요해요');
  });

  it('requires an explicit confirmation before requesting a full solution', async () => {
    const user = userEvent.setup();
    const send = vi.fn().mockResolvedValue(undefined);
    render(<TutorDrawer open turns={[]} onClose={vi.fn()} onSend={send} busy={false} />);
    await user.click(screen.getByRole('radio', { name: '정답 풀이' }));
    await user.type(screen.getByLabelText('도우미에게 보낼 내용'), '전체 풀이');
    expect(screen.getByRole('button', { name: '정답 요청 확인' })).toBeDisabled();
    await user.click(screen.getByLabelText('정답 코드 요청에 동의합니다'));
    await user.click(screen.getByRole('button', { name: '정답 요청 확인' }));
    expect(send).toHaveBeenCalledWith('solution', '전체 풀이');
  });
});
