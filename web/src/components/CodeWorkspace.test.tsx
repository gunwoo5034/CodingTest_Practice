import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CodeWorkspace } from './CodeWorkspace';

vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange }: { value?: string; onChange?: (value: string) => void }) => (
    <textarea aria-label="코드 편집기" value={value} onChange={(event) => onChange?.(event.target.value)} />
  ),
}));

describe('CodeWorkspace', () => {
  it('saves the current language before switching drafts', async () => {
    const user = userEvent.setup();
    const saveDraft = vi.fn().mockResolvedValue(undefined);
    const loadDraft = vi.fn().mockResolvedValue('function solution(numbers) { return 0; }');
    render(
      <CodeWorkspace
        initialLanguage="python"
        initialSource="def solution(numbers):\n    return 0"
        onSaveDraft={saveDraft}
        onLoadDraft={loadDraft}
        onRun={vi.fn()}
        onSubmit={vi.fn()}
        submitDisabled={false}
      />,
    );

    await user.clear(screen.getByLabelText('코드 편집기'));
    await user.type(screen.getByLabelText('코드 편집기'), 'def solution(numbers):\n    return 1');
    await user.selectOptions(screen.getByLabelText('언어 선택'), 'javascript');

    expect(saveDraft).toHaveBeenCalledWith('python', 'def solution(numbers):\n    return 1');
    expect(loadDraft).toHaveBeenCalledWith('javascript');
    expect(await screen.findByDisplayValue('function solution(numbers) { return 0; }')).toBeInTheDocument();
  });

  it('runs code only after the user presses 실행', async () => {
    const user = userEvent.setup();
    const run = vi.fn().mockResolvedValue(undefined);
    render(
      <CodeWorkspace initialLanguage="python" initialSource="pass" onSaveDraft={vi.fn()} onLoadDraft={vi.fn()} onRun={run} onSubmit={vi.fn()} submitDisabled={false} />,
    );
    expect(run).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '실행' }));
    expect(run).toHaveBeenCalledWith('python', 'pass');
  });

  it('flushes an edited draft when leaving the workspace', async () => {
    const user = userEvent.setup();
    const saveDraft = vi.fn().mockResolvedValue(undefined);
    const view = render(
      <CodeWorkspace initialLanguage="javascript" initialSource="function solution() {}" onSaveDraft={saveDraft} onLoadDraft={vi.fn()} onRun={vi.fn()} onSubmit={vi.fn()} submitDisabled={false} />,
    );
    fireEvent.change(screen.getByLabelText('코드 편집기'), { target: { value: 'function solution() { return 1; }' } });
    view.unmount();
    await act(async () => { await Promise.resolve(); });
    expect(saveDraft).toHaveBeenCalledWith('javascript', 'function solution() { return 1; }');
  });

  it('serializes an older autosave before the final save used for a language switch', async () => {
    vi.useFakeTimers();
    let finishFirst!: () => void;
    const first = new Promise<void>((resolve) => { finishFirst = resolve; });
    const saveDraft = vi.fn().mockImplementationOnce(() => first).mockResolvedValue(undefined);
    const loadDraft = vi.fn().mockResolvedValue('function solution() {}');
    render(<CodeWorkspace initialLanguage="python" initialSource="old" onSaveDraft={saveDraft} onLoadDraft={loadDraft} onRun={vi.fn()} onSubmit={vi.fn()} submitDisabled={false} />);

    fireEvent.change(screen.getByLabelText('코드 편집기'), { target: { value: 'edit A' } });
    await act(async () => { vi.advanceTimersByTime(800); });
    fireEvent.change(screen.getByLabelText('코드 편집기'), { target: { value: 'edit B' } });
    fireEvent.change(screen.getByLabelText('언어 선택'), { target: { value: 'javascript' } });
    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(screen.getByText('저장 중…')).toBeInTheDocument();

    await act(async () => { finishFirst(); await first; });
    expect(saveDraft).toHaveBeenNthCalledWith(2, 'python', 'edit B');
    vi.useRealTimers();
    expect(await screen.findByDisplayValue('function solution() {}')).toBeInTheDocument();
  });
});
