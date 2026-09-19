import { FileImage, FileText, Sparkles, Upload } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, type Folder } from '../api/client';

const allowed = ['image/png', 'image/jpeg', 'image/webp'];
type ImageValue = { name: string; mime: 'image/png' | 'image/jpeg' | 'image/webp'; base64: string };

export function NewProblemPage() {
  const [text, setText] = useState(''); const [image, setImage] = useState<ImageValue | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [folders, setFolders] = useState<Folder[]>([]); const [folderId, setFolderId] = useState(''); const [params] = useSearchParams();
  const input = useRef<HTMLInputElement>(null); const navigate = useNavigate();
  const choose = async (file?: File) => {
    if (!file) return; setError('');
    if (!allowed.includes(file.type)) return setError('PNG, JPEG, WebP 이미지만 사용할 수 있습니다.');
    if (file.size > 10 * 1024 * 1024) return setError('이미지는 10MB 이하여야 합니다.');
    const dataUrl = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file); });
    setImage({ name: file.name, mime: file.type as ImageValue['mime'], base64: dataUrl.split(',')[1] });
  };
  useEffect(() => {
    const paste = (event: ClipboardEvent) => { const file = [...(event.clipboardData?.files ?? [])].find((item) => item.type.startsWith('image/')); if (file) { event.preventDefault(); void choose(file); } };
    window.addEventListener('paste', paste); return () => window.removeEventListener('paste', paste);
  }, []);
  useEffect(() => { let active = true; api.folders().then((value) => { if (!active) return; setFolders(value); const requested = params.get('folder'); if (requested && value.some((folder) => folder.id === requested)) setFolderId(requested); }).catch((e: Error) => { if (active) setError(e.message); }); return () => { active = false; }; }, [params]);
  const analyze = async () => { setBusy(true); setError(''); try { const created = await api.analyze({ text: text.trim() || null, image_base64: image?.base64 ?? null, image_mime: image?.mime ?? null, folder_id: folderId || null }); navigate(`/problems/${created.id}/edit`, { state: { justAnalyzed: true } }); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const manual = async () => { if (!text.trim()) return setError('직접 등록하려면 문제 설명을 입력해 주세요.'); setBusy(true); setError(''); try { const created = await api.createProblem({ title: text.trim().split('\n')[0].slice(0, 200), statement: text, example_explanation: '', constraints: [], signature: { parameters: [{ name: 'numbers', type: { base: 'int', dimensions: 1 } }], return_type: { base: 'int', dimensions: 0 } }, source_text: text, folder_id: folderId || null }); navigate(`/problems/${created.id}/edit`); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  return <div className="page narrow-page"><header className="page-header compact"><div><span className="eyebrow">NEW PROBLEM</span><h1>문제를 가져오세요</h1><p>텍스트나 문제 이미지를 올리면 풀이에 필요한 구조를 정리합니다.</p></div></header>
    <div className="import-layout"><section className="surface import-card"><div className="section-heading"><span className="step">01</span><div><h2>문제 원문</h2><p>복사한 텍스트를 그대로 붙여 넣어도 됩니다.</p></div></div><textarea className="source-input" aria-label="문제 텍스트" value={text} onChange={(e) => setText(e.target.value)} placeholder={'문제 설명, 제한사항, 입출력 예제를 붙여 넣으세요.\n\n이미지만으로도 분석할 수 있습니다.'} /></section>
      <section className={`surface upload-card ${image ? 'has-file' : ''}`} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); void choose(e.dataTransfer.files[0]); }} onClick={() => input.current?.click()}><input ref={input} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => void choose(e.target.files?.[0])} /><span className="upload-icon">{image ? <FileImage /> : <Upload />}</span>{image ? <><strong>{image.name}</strong><p>이미지가 준비됐습니다. 클릭해서 바꿀 수 있어요.</p></> : <><strong>이미지를 놓거나 선택하세요</strong><p>붙여넣기도 가능 · PNG, JPEG, WebP · 최대 10MB</p></>}</section>
    </div>
    <label className="folder-select-field"><span>저장할 폴더</span><select aria-label="저장할 폴더" value={folderId} onChange={(event) => setFolderId(event.target.value)}><option value="">미분류</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select><small>나중에 문제 편집 화면에서도 바꿀 수 있습니다.</small></label>
    <div className="privacy-note"><Sparkles size={17} /><p><strong>분석은 이 버튼을 누를 때만 시작됩니다.</strong> 추출된 내용은 다음 화면에서 모두 수정할 수 있습니다.</p></div>
    {error && <div className="notice error">{error}</div>}
    <footer className="form-footer"><button className="button ghost large" disabled={busy || !text.trim()} onClick={() => void manual()}><FileText size={18} /> 직접 입력으로 등록</button><button className="button primary large" disabled={busy || (!text.trim() && !image)} onClick={() => void analyze()}><Sparkles size={18} /> {busy ? '분석 중…' : 'AI로 구조 분석'}</button></footer>
  </div>;
}
