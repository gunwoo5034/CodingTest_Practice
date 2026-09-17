import { Bot, Send, X } from 'lucide-react';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import type { ChatTurn, TutorMode } from '../api/client';

type Props = { open: boolean; turns: ChatTurn[]; onClose: () => void; onSend: (mode: TutorMode, message: string) => Promise<unknown>; busy: boolean };

export function TutorDrawer({ open, turns, onClose, onSend, busy }: Props) {
  const [mode, setMode] = useState<TutorMode>('hint');
  const [message, setMessage] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const submit = async () => {
    if (!message.trim() || (mode === 'solution' && !confirmed)) return;
    try { await onSend(mode, message.trim()); setMessage(''); setConfirmed(false); } catch { /* Parent renders the actionable API error; preserve this draft. */ }
  };
  if (!open) return null;
  return <aside className="tutor-drawer" aria-label="AI 풀이 도우미">
    <header><div><span className="icon-tile"><Bot size={18} /></span><strong>풀이 도우미</strong><small>요청할 때만 AI를 사용합니다</small></div><button className="icon-button" aria-label="도우미 닫기" onClick={onClose}><X /></button></header>
    <div className="mode-picker" role="radiogroup" aria-label="도우미 모드">
      {([['hint', '힌트'], ['question', '질문'], ['solution', '정답 풀이']] as const).map(([id, label]) => <label key={id} className={mode === id ? 'active' : ''}><input type="radio" name="tutor-mode" value={id} checked={mode === id} onChange={() => { setMode(id); setConfirmed(false); }} />{label}</label>)}
    </div>
    <div className="chat-stream">
      {turns.length === 0 && <div className="empty compact"><Bot size={24} /><strong>막힌 지점을 이야기해 보세요</strong><p>코드를 읽고 다음 한 걸음을 함께 찾습니다.</p></div>}
      {turns.map((turn, index) => <div className="chat-pair" key={`${turn.created_at}-${index}`}><div className="bubble user">{turn.user_message}</div><div className="bubble assistant"><ReactMarkdown>{turn.assistant_message}</ReactMarkdown></div></div>)}
    </div>
    <div className="chat-compose">
      {mode === 'solution' && <label className="solution-confirm"><input type="checkbox" aria-label="정답 코드 요청에 동의합니다" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> 전체 풀이와 정답 코드를 요청합니다.</label>}
      <textarea aria-label="도우미에게 보낼 내용" value={message} onChange={(event) => setMessage(event.target.value)} placeholder={mode === 'hint' ? '어디서 막혔는지 적어 주세요' : '궁금한 내용을 구체적으로 적어 주세요'} />
      <button className="button primary wide" disabled={busy || !message.trim() || (mode === 'solution' && !confirmed)} onClick={() => void submit()}><Send size={16} /> {mode === 'solution' ? '정답 요청 확인' : '질문 보내기'}</button>
    </div>
  </aside>;
}
