import Editor from '@monaco-editor/react';
import { Play, Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Language } from '../api/client';
import { languages } from '../lib/domain';

type Props = {
  initialLanguage: Language;
  initialSource: string;
  onSaveDraft: (language: Language, source: string) => Promise<unknown>;
  onLoadDraft: (language: Language) => Promise<string>;
  onRun: (language: Language, source: string) => Promise<unknown> | unknown;
  onSubmit: (language: Language, source: string) => Promise<unknown> | unknown;
  submitDisabled: boolean;
  busy?: boolean;
  onLanguageChange?: (language: Language, source: string) => void;
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
  useEffect(() => { sourceRef.current = source; languageRef.current = language; props.onLanguageChange?.(language, source); }, [language, source]);
  useEffect(() => () => { window.clearTimeout(timer.current); if (dirtyRef.current) void props.onSaveDraft(languageRef.current, sourceRef.current); }, []);

  const edit = (next = '') => {
    setSource(next);
    dirtyRef.current = true;
    setSaving('saving');
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      props.onSaveDraft(language, next).then(() => { dirtyRef.current = false; setSaving('saved'); }).catch(() => setSaving('error'));
    }, 800);
  };

  const switchLanguage = async (next: Language) => {
    if (next === language) return;
    window.clearTimeout(timer.current);
    setSwitching(true);
    setSaving('saving');
    try {
      await props.onSaveDraft(language, sourceRef.current);
      dirtyRef.current = false;
      const loaded = await props.onLoadDraft(next);
      setLanguage(next);
      setSource(loaded);
      setSaving('saved');
    } catch { setSaving('error'); } finally { setSwitching(false); }
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
        <button className="button ghost" disabled={props.busy} onClick={() => props.onRun(language, source)}><Play size={16} /> 실행</button>
        <button className="button primary" disabled={props.busy || props.submitDisabled} onClick={() => props.onSubmit(language, source)}><Send size={16} /> 제출</button>
      </div>
    </header>
    <Editor
      height="100%" language={current.monaco} value={source} onChange={edit}
      theme="loopcode-dark" options={{ readOnly: switching, minimap: { enabled: false }, fontSize: 14, lineHeight: 23, padding: { top: 18 }, scrollBeyondLastLine: false, automaticLayout: true, tabSize: 2, roundedSelection: false }}
    />
  </section>;
}
