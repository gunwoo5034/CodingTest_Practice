import type { components } from './schema';
import { formatApiError } from '../lib/domain';

export type Problem = components['schemas']['ProblemPublic'];
export type ProblemSummary = components['schemas']['ProblemSummary'];
export type Folder = components['schemas']['FolderPublic'];
export type Health = components['schemas']['HealthPublic'];
export type Draft = components['schemas']['DraftPublic'];
export type Job = components['schemas']['JobPublic'];
export type GenerationJob = components['schemas']['GenerationJobPublic'];
export type TestCase = components['schemas']['TestCasePublic'];
export type ChatTurn = components['schemas']['ChatTurnPublic'];
export type Language = components['schemas']['JobCreate']['language'];
export type Signature = components['schemas']['Signature'];
export type TutorMode = components['schemas']['TutorRequest']['mode'];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers,
  });
  if (!response.ok) {
    let data: unknown;
    try { data = await response.json(); } catch { data = null; }
    throw new Error(formatApiError(data) || `요청 실패 (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>('/api/health'),
  folders: () => request<Folder[]>('/api/folders'),
  createFolder: (name: string) => request<Folder>('/api/folders', { method: 'POST', ...json({ name }) }),
  updateFolder: (id: string, name: string) => request<Folder>(`/api/folders/${id}`, { method: 'PATCH', ...json({ name }) }),
  deleteFolder: (id: string) => request<void>(`/api/folders/${id}`, { method: 'DELETE' }),
  problems: () => request<ProblemSummary[]>('/api/problems'),
  problem: (id: string) => request<Problem>(`/api/problems/${id}`),
  createProblem: (body: components['schemas']['ProblemCreate']) => request<Problem>('/api/problems', { method: 'POST', ...json(body) }),
  analyze: (body: components['schemas']['AnalyzeRequest']) => request<Problem>('/api/problems/analyze', { method: 'POST', ...json(body) }),
  updateProblem: (id: string, body: components['schemas']['ProblemUpdate']) => request<Problem>(`/api/problems/${id}`, { method: 'PATCH', ...json(body) }),
  deleteProblem: (id: string) => request<void>(`/api/problems/${id}`, { method: 'DELETE' }),
  moveProblem: (id: string, folderId: string | null) => request<Problem>(`/api/problems/${id}/folder`, { method: 'PUT', ...json({ folder_id: folderId }) }),
  createTest: (id: string, body: components['schemas']['TestCaseCreate']) => request<TestCase>(`/api/problems/${id}/tests`, { method: 'POST', ...json(body) }),
  updateTest: (id: string, testId: string, body: components['schemas']['TestCaseUpdate']) => request<TestCase>(`/api/problems/${id}/tests/${testId}`, { method: 'PATCH', ...json(body) }),
  deleteTest: (id: string, testId: string) => request<void>(`/api/problems/${id}/tests/${testId}`, { method: 'DELETE' }),
  expected: (id: string, body: components['schemas']['ExpectedCompute']) => request<components['schemas']['ExpectedResult']>(`/api/problems/${id}/tests/expected`, { method: 'POST', ...json(body) }),
  draft: (id: string, language: Language) => request<Draft>(`/api/problems/${id}/drafts/${language}`),
  saveDraft: (id: string, language: Language, source: string) => request<Draft>(`/api/problems/${id}/drafts/${language}`, { method: 'PUT', ...json({ source }) }),
  startJob: (id: string, body: components['schemas']['JobCreate']) => request<Job>(`/api/problems/${id}/jobs`, { method: 'POST', ...json(body) }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  submissions: (id: string) => request<Job[]>(`/api/problems/${id}/submissions`),
  generate: (id: string) => request<GenerationJob>(`/api/problems/${id}/ai/generate`, { method: 'POST', ...json({}) }),
  generationJob: (id: string) => request<GenerationJob>(`/api/generation-jobs/${id}`),
  chat: (id: string) => request<ChatTurn[]>(`/api/problems/${id}/chat`),
  tutor: (id: string, body: components['schemas']['TutorRequest']) => request<components['schemas']['TutorResponse']>(`/api/problems/${id}/ai/chat`, { method: 'POST', ...json(body) }),
};

export async function pollJob<T extends { status: string }>(load: () => Promise<T>, interval = 700): Promise<T> {
  for (;;) {
    const value = await load();
    if (!['queued', 'running'].includes(value.status)) return value;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}
