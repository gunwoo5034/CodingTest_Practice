import type { components } from '../api/schema';

export type TypeDescriptor = components['schemas']['TypeDescriptor'];
export type Language = components['schemas']['JobCreate']['language'];

export const languages: { id: Language; label: string; monaco: string }[] = [
  { id: 'python', label: 'Python 3.12', monaco: 'python' },
  { id: 'cpp', label: 'C++17', monaco: 'cpp' },
  { id: 'java', label: 'Java 21', monaco: 'java' },
  { id: 'javascript', label: 'JavaScript · Node.js 22', monaco: 'javascript' },
];

export function languageLabel(id: Language) {
  return languages.find((item) => item.id === id)?.label ?? id;
}

export function formatApiError(value: unknown): string {
  if (value instanceof Error) return value.message;
  if (!value || typeof value !== 'object') return '요청을 완료하지 못했습니다.';
  const detail = (value as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item);
        const typed = item as { loc?: (string | number)[]; msg?: string };
        const location = typed.loc?.filter((part) => part !== 'body').join('.');
        return [location, typed.msg].filter(Boolean).join(': ');
      })
      .join('\n');
  }
  return '서버 응답을 확인할 수 없습니다.';
}

export function parseJsonValue(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    throw new Error('올바른 JSON 형식으로 입력해 주세요.');
  }
}

export function typeLabel(type: TypeDescriptor): string {
  const arrays = '[]'.repeat(type.dimensions);
  return `${type.base}${arrays}${type.base === 'long' ? ' · 값은 문자열' : ''}`;
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export const statusLabels: Record<string, string> = {
  draft: '편집 중', analyzed: '분석 완료', generating: '테스트 준비 중', ready: '풀이 가능', needs_review: '검토 필요',
  queued: '대기 중', running: '실행 중', completed: '완료', failed: '실패', interrupted: '중단됨',
  passed: '통과', wrong_answer: '오답', compile_error: '컴파일 오류', runtime_error: '실행 오류',
  time_limit: '시간 초과', memory_limit: '메모리 초과', output_limit: '출력 초과', system_error: '서비스 오류',
};
