import { ArrowRight, BookOpen, Folder as FolderIcon, FolderOpen, MoreHorizontal, Pencil, Plus, Search, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, type Folder, type ProblemSummary } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { formatDate } from '../lib/domain';

type FolderDialog = { kind: 'create'; folder?: never } | { kind: 'rename' | 'delete'; folder: Folder };

export function LibraryPage() {
  const [items, setItems] = useState<ProblemSummary[]>([]); const [folders, setFolders] = useState<Folder[]>([]); const [query, setQuery] = useState(''); const [filter, setFilter] = useState('all');
  const [params, setParams] = useSearchParams(); const selectedFolder = params.get('folder') ?? 'all';
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true); const [dialog, setDialog] = useState<FolderDialog | null>(null); const [menu, setMenu] = useState(''); const [moving, setMoving] = useState<Set<string>>(new Set()); const loadRevision = useRef(0); const dialogOpener = useRef<HTMLElement | null>(null); const folderMenuOpeners = useRef(new Map<string, HTMLButtonElement>());
  const load = async () => {
    const revision = ++loadRevision.current; setLoading(true); setError('');
    const [problemsResult, foldersResult] = await Promise.allSettled([api.problems(), api.folders()]);
    if (loadRevision.current !== revision) return;
    const errors: string[] = [];
    if (problemsResult.status === 'fulfilled') setItems(problemsResult.value); else errors.push((problemsResult.reason as Error).message);
    if (foldersResult.status === 'fulfilled') setFolders(foldersResult.value); else errors.push((foldersResult.reason as Error).message);
    setError(errors.join(' · ')); setLoading(false);
  };
  useEffect(() => { void load(); return () => { loadRevision.current += 1; }; }, []);
  useEffect(() => { if (!loading && selectedFolder !== 'all' && selectedFolder !== 'unfiled' && !folders.some((folder) => folder.id === selectedFolder)) setParams({}, { replace: true }); }, [folders, loading, selectedFolder, setParams]);
  const chooseFolder = (value: string) => setParams(value === 'all' ? {} : { folder: value });
  const filtered = useMemo(() => items.filter((item) => {
    const inFolder = selectedFolder === 'all' || (selectedFolder === 'unfiled' ? !item.folder_id : item.folder_id === selectedFolder);
    const inStatus = filter === 'all' || (filter === 'solved' ? item.is_solved : item.status === filter);
    return inFolder && inStatus && item.title.toLowerCase().includes(query.toLowerCase());
  }), [items, filter, query, selectedFolder]);
  const unfiledCount = items.filter((item) => !item.folder_id).length;
  const folderName = (id?: string | null) => folders.find((folder) => folder.id === id)?.name ?? '미분류';
  const remove = async (item: ProblemSummary) => { if (!confirm(`“${item.title}” 문제와 기록을 삭제할까요?`)) return; try { await api.deleteProblem(item.id); setItems((all) => all.filter((value) => value.id !== item.id)); setFolders((all) => all.map((folder) => folder.id === item.folder_id ? { ...folder, problem_count: Math.max(0, folder.problem_count - 1) } : folder)); } catch (e) { setError((e as Error).message); } };
  const move = async (item: ProblemSummary, folderId: string) => { if (moving.has(item.id)) return; setMoving((current) => new Set(current).add(item.id)); setError(''); try { const moved = await api.moveProblem(item.id, folderId || null); setItems((all) => all.map((value) => value.id === item.id ? { ...value, folder_id: moved.folder_id } : value)); try { setFolders(await api.folders()); } catch (e) { setError((e as Error).message); } } catch (e) { setError((e as Error).message); } finally { setMoving((current) => { const next = new Set(current); next.delete(item.id); return next; }); } };
  const openDialog = (value: FolderDialog, opener: HTMLElement) => { dialogOpener.current = opener; setDialog(value); };
  const newProblemHref = selectedFolder !== 'all' && selectedFolder !== 'unfiled' ? `/problems/new?folder=${encodeURIComponent(selectedFolder)}` : '/problems/new';
  return <div className="page library-page">
    <header className="page-header"><div><span className="eyebrow">PROBLEM LIBRARY</span><h1>오늘은 어떤 문제를 풀까요?</h1><p>직접 모은 문제를 유형별로 정리하고, 네 가지 언어로 반복해서 연습하세요.</p></div><Link className="button primary large" to={newProblemHref}><Plus size={18} /> 새 문제 등록</Link></header>
    <div className="library-layout"><aside className="folder-sidebar" aria-label="문제 폴더"><header><strong>문제 보관함</strong><button className="icon-button" aria-label="폴더 추가" onClick={(event) => openDialog({ kind: 'create' }, event.currentTarget)}><Plus size={17} /></button></header><div className="folder-list">
      <button className={selectedFolder === 'all' ? 'active' : ''} onClick={() => chooseFolder('all')}><BookOpen size={17} /><span>전체</span><em>{items.length}</em></button>
      <button className={selectedFolder === 'unfiled' ? 'active' : ''} onClick={() => chooseFolder('unfiled')}><FolderOpen size={17} /><span>미분류</span><em>{unfiledCount}</em></button>
      {folders.map((folder) => <div className="folder-row" key={folder.id}><button className={selectedFolder === folder.id ? 'active' : ''} onClick={() => chooseFolder(folder.id)}><FolderIcon size={17} /><span title={folder.name}>{folder.name}</span><em>{folder.problem_count}</em></button><button ref={(element) => { if (element) folderMenuOpeners.current.set(folder.id, element); else folderMenuOpeners.current.delete(folder.id); }} className="folder-menu-button" aria-label={`${folder.name} 폴더 관리`} onClick={() => setMenu(menu === folder.id ? '' : folder.id)}><MoreHorizontal size={16} /></button>{menu === folder.id && <div className="folder-menu"><button onClick={(event) => { openDialog({ kind: 'rename', folder }, folderMenuOpeners.current.get(folder.id) ?? event.currentTarget); setMenu(''); }}><Pencil size={14} /> 이름 변경</button><button className="danger" onClick={(event) => { openDialog({ kind: 'delete', folder }, folderMenuOpeners.current.get(folder.id) ?? event.currentTarget); setMenu(''); }}><Trash2 size={14} /> 삭제</button></div>}</div>)}
    </div></aside><main className="library-content">
      <section className="library-toolbar"><label className="search-box"><Search size={18} /><input aria-label="문제 검색" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="문제 이름으로 검색" /></label><div className="filter-pills">{[['all','전체'],['solved','풀이 완료'],['ready','풀이 가능'],['draft','편집 중'],['needs_review','검토 필요']].map(([value,label]) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label}</button>)}</div></section>
      {error && <div className="notice error">{error}<button onClick={() => void load()}>다시 시도</button></div>}
      {loading ? <div className="loading-grid">{[1,2,3].map((n) => <div className="skeleton card" key={n} />)}</div> : filtered.length === 0 ? <div className="empty"><BookOpen /><strong>{items.length ? '조건에 맞는 문제가 없습니다' : '첫 문제를 등록해 보세요'}</strong><p>{items.length ? '다른 폴더, 검색어 또는 상태를 선택해 보세요.' : '문제 텍스트나 이미지만 있으면 시작할 수 있습니다.'}</p>{!items.length && <Link className="button primary" to={newProblemHref}>문제 등록하기</Link>}</div> : <div className="problem-grid">{filtered.map((item, index) => <article className="problem-card" key={item.id}>
        <div className="card-top"><span className="problem-number">{String(index + 1).padStart(2, '0')}</span><div className="card-badges"><StatusBadge status={item.status} />{item.is_solved && <span className="status-badge status-solved" title="전체 통과한 제출 기록이 있습니다.">풀이 완료</span>}</div></div><h2>{item.title}</h2><p className="card-folder"><FolderIcon size={13} /> {folderName(item.folder_id)}</p><p>테스트 리비전 {item.test_revision} · {formatDate(item.updated_at)}</p><label className="move-control"><span>폴더</span><select aria-label={`${item.title} 폴더 이동`} disabled={moving.has(item.id)} value={item.folder_id ?? ''} onChange={(event) => void move(item, event.target.value)}><option value="">미분류</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label><div className="card-actions"><Link to={`/problems/${item.id}`} className="card-open">문제 풀기 <ArrowRight size={17} /></Link><Link aria-label={`${item.title} 편집`} className="icon-button" to={`/problems/${item.id}/edit`}><Pencil size={16} /></Link><button aria-label={`${item.title} 삭제`} className="icon-button danger" onClick={() => void remove(item)}><Trash2 size={17} /></button></div>
      </article>)}</div>}
    </main></div>
    {dialog && <FolderEditor dialog={dialog} returnFocus={dialogOpener.current} onClose={() => setDialog(null)} onCreated={(folder) => setFolders((current) => [...current, folder])} onRenamed={(folder) => setFolders((current) => current.map((item) => item.id === folder.id ? folder : item))} onDeleted={async (id) => { if (selectedFolder === id) chooseFolder('all'); await load(); }} />}
  </div>;
}

function FolderEditor({ dialog, returnFocus, onClose, onCreated, onRenamed, onDeleted }: { dialog: FolderDialog; returnFocus: HTMLElement | null; onClose: () => void; onCreated: (folder: Folder) => void; onRenamed: (folder: Folder) => void; onDeleted: (id: string) => Promise<void> }) {
  const [name, setName] = useState(dialog.kind === 'create' ? '' : dialog.folder.name); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const input = useRef<HTMLInputElement>(null);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => { input.current?.focus(); return () => { returnFocus?.focus(); }; }, [returnFocus]);
  const submit = async () => { if (busy) return; if (!name.trim()) return setError('폴더 이름을 입력해 주세요.'); setBusy(true); setError(''); try { if (dialog.kind === 'create') onCreated(await api.createFolder(name)); else onRenamed(await api.updateFolder(dialog.folder.id, name)); onClose(); } catch (e) { setError((e as Error).message); setBusy(false); } };
  const remove = async () => { if (dialog.kind !== 'delete') return; setBusy(true); setError(''); try { await api.deleteFolder(dialog.folder.id); await onDeleted(dialog.folder.id); onClose(); } catch (e) { setError((e as Error).message); setBusy(false); } };
  const keyDown = (event: React.KeyboardEvent) => { if (event.key === 'Escape' && !busy) { event.preventDefault(); onClose(); return; } if (event.key !== 'Tab') return; const focusable = [...(panel.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]') ?? [])]; if (!focusable.length) return; const first = focusable[0]; const last = focusable[focusable.length - 1]; if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } };
  return <div className="modal-backdrop" onMouseDown={() => { if (!busy) onClose(); }}><section ref={panel} className="folder-dialog" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title" onKeyDown={keyDown} onMouseDown={(event) => event.stopPropagation()}><header><div><span className="eyebrow">FOLDER</span><h2 id="folder-dialog-title">{dialog.kind === 'create' ? '새 폴더' : dialog.kind === 'rename' ? '폴더 이름 변경' : '폴더 삭제'}</h2></div><button className="icon-button" disabled={busy} aria-label="폴더 창 닫기" onClick={onClose}><X /></button></header>{dialog.kind === 'delete' ? <p>“{dialog.folder.name}” 폴더를 삭제합니다. 문제는 삭제되지 않고 미분류로 이동합니다.</p> : <label className="dialog-field">폴더 이름<input ref={input} disabled={busy} maxLength={60} value={name} onChange={(event) => setName(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void submit(); }} /></label>}{error && <div className="notice error">{error}</div>}<footer><button className="button ghost" disabled={busy} onClick={onClose}>취소</button>{dialog.kind === 'delete' ? <button className="button danger-fill" disabled={busy} onClick={() => void remove()}>폴더 삭제</button> : <button className="button primary" disabled={busy} onClick={() => void submit()}>{dialog.kind === 'create' ? '폴더 만들기' : '이름 저장'}</button>}</footer></section></div>;
}
