import Editor from '@monaco-editor/react';
import { Play, Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Language } from '../api/client';
import { languages } from '../lib/domain';
import { draftKey, enqueueDraftSave, waitForDraftSaves } from '../lib/draftSaveQueue';

type Props = {
  problemId: string;
  initialLanguage: Language;
  initialSource: string;
  onSaveDraft: (language: Language, source: string) => Promise<unknown>;
  onLoadDraft: (language: Language) => Promise<string>;
  onRun: (language: Language, source: string) => Promise<unknown> | unknown;
  onSubmit: (language: Language, source: string) => Promise<unknown> | unknown;
  submitDisabled: boolean;
  busy?: boolean;
  onLanguageChange?: (language: Language, source: string) => void;
  onSaveError?: (message: string) => void;
};

export function CodeWorkspace(props: Props) {
  const [language, setLanguage] = useState(props.initialLanguage);
  const [source, setSource] = useState(props.initialSource);
  const [saving, setSaving] = useState<'saved' | 'saving' | 'error'>('saved');
  const [switching, setSwitching] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const sourceRef = useRef(source);
  const languageRef = useRef(language);
  const dirtyRef = useRef(false);
  const revisionRef = useRef(0);
  const actionRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => { sourceRef.current = source; languageRef.current = language; props.onLanguageChange?.(language, source); }, [language, source]);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      actionRef.current += 1;
      window.clearTimeout(timer.current);
      if (dirtyRef.current) void enqueueSave(languageRef.current, sourceRef.current, revisionRef.current).catch((error: Error) => props.onSaveError?.(error.message));
    };
  }, []);

  const enqueueSave = (targetLanguage: Language, targetSource: string, revision: number) => {
    const request = enqueueDraftSave(draftKey(props.problemId, targetLanguage), () => props.onSaveDraft(targetLanguage, targetSource));
    return request.then((result) => {
      if (revisionRef.current === revision && languageRef.current === targetLanguage && sourceRef.current === targetSource) {
        dirtyRef.current = false;
        if (mountedRef.current) setSaving('saved');
      }
      return result;
    }).catch((error) => {
      if (revisionRef.current === revision && mountedRef.current) setSaving('error');
      throw error;
    });
  };

  const edit = (next = '') => {
    setSource(next);
    dirtyRef.current = true;
    const revision = ++revisionRef.current;
    setSaving('saving');
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      void enqueueSave(language, next, revision).catch(() => undefined);
    }, 800);
  };

  const switchLanguage = async (next: Language) => {
    if (next === language) return;
    window.clearTimeout(timer.current);
    setSwitching(true);
    setSaving('saving');
    try {
      await enqueueSave(language, sourceRef.current, revisionRef.current);
      await waitForDraftSaves(draftKey(props.problemId, next));
      const loaded = await props.onLoadDraft(next);
      setLanguage(next);
      languageRef.current = next;
      setSource(loaded);
      sourceRef.current = loaded;
      setSaving('saved');
    } catch { setSaving('error'); } finally { setSwitching(false); }
  };

  const runAction = async (action: Props['onRun'] | Props['onSubmit']) => {
    const operation = ++actionRef.current;
    window.clearTimeout(timer.current);
    setSaving('saving');
    try {
      await enqueueSave(languageRef.current, sourceRef.current, revisionRef.current);
      if (!mountedRef.current || actionRef.current !== operation) return;
      await action(languageRef.current, sourceRef.current);
    } catch { if (mountedRef.current && actionRef.current === operation) setSaving('error'); }
  };

  const current = languages.find((item) => item.id === language)!;
  return <section className="code-workspace" aria-label="코드 작성 영역">
    <header className="pane-toolbar">
      <div className="language-control">
        <span className="eyebrow">언어</span>
        <select aria-label="언어 선택" disabled={switching} value={language} onChange={(event) => void switchLanguage(event.target.value as Language)}>
          {languages.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </div>
      <span className={`save-state ${saving}`}>{saving === 'saved' ? '저장됨' : saving === 'saving' ? '저장 중…' : '저장 실패'}</span>
      <div className="toolbar-actions">
        <button className="button ghost" disabled={props.busy || switching} onClick={() => void runAction(props.onRun)}><Play size={16} /> 실행</button>
        <button className="button primary" disabled={props.busy || switching || props.submitDisabled} onClick={() => void runAction(props.onSubmit)}><Send size={16} /> 제출</button>
      </div>
    </header>
    <Editor
      height="100%" language={current.monaco} value={source} onChange={edit}
      theme="loopcode-dark" options={{ readOnly: switching, minimap: { enabled: false }, fontSize: 14, lineHeight: 23, padding: { top: 18 }, scrollBeyondLastLine: false, automaticLayout: true, tabSize: 2, roundedSelection: false }}
    />
  </section>;
}
