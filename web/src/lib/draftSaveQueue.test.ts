import { describe, expect, it, vi } from 'vitest';
import { draftKey, enqueueDraftSave, waitForDraftSaves } from './draftSaveQueue';

describe('draft save queue', () => {
  it('retries the latest failed final save before the draft is loaded again', async () => {
    const key = draftKey('retry-after-unmount', 'python');
    const save = vi.fn().mockRejectedValueOnce(new Error('temporary failure')).mockResolvedValue(undefined);
    await expect(enqueueDraftSave(key, save)).rejects.toThrow('temporary failure');
    await waitForDraftSaves(key);
    expect(save).toHaveBeenCalledTimes(2);
  });
});
