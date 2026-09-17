import type { Language } from '../api/client';

type QueueEntry = { promise: Promise<unknown>; save: () => Promise<unknown> };
const pending = new Map<string, QueueEntry>();

export const draftKey = (problemId: string, language: Language) => `${problemId}:${language}`;

export function enqueueDraftSave<T>(key: string, save: () => Promise<T>): Promise<T> {
  const previous = pending.get(key)?.promise ?? Promise.resolve();
  const request = previous.catch(() => undefined).then(save);
  const entry: QueueEntry = { promise: request, save };
  pending.set(key, entry);
  void request.then(() => {
    if (pending.get(key) === entry) pending.delete(key);
  }).catch(() => undefined);
  return request;
}

export async function waitForDraftSaves(key: string): Promise<void> {
  const entry = pending.get(key);
  if (!entry) return;
  try { await entry.promise; }
  catch {
    if (pending.get(key) !== entry) return waitForDraftSaves(key);
    await enqueueDraftSave(key, entry.save);
  }
}
