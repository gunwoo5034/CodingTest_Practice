import { ArrowRight, BookOpen, MoreHorizontal, Plus, Search, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type ProblemSummary } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { formatDate } from '../lib/domain';

export function LibraryPage() {
  const [items, setItems] = useState<ProblemSummary[]>([]); const [query, setQuery] = useState(''); const [filter, setFilter] = useState('all');
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const load = () => { setLoading(true); api.problems().then(setItems).catch((e: Error) => setError(e.message)).finally(() => setLoading(false)); };
  useEffect(load, []);
  const filtered = useMemo(() => items.filter((item) => (filter === 'all' || (filter === 'solved' ? item.is_solved : item.status === filter)) && item.title.toLowerCase().includes(query.toLowerCase())), [items, filter, query]);
  const remove = async (item: ProblemSummary) => { if (!confirm(`“${item.title}” 문제와 기록을 삭제할까요?`)) return; try { await api.deleteProblem(item.id); setItems((all) => all.filter((value) => value.id !== item.id)); } catch (e) { setError((e as Error).message); } };
  return <div className="page library-page">
    <header className="page-header"><div><span className="eyebrow">PROBLEM LIBRARY</span><h1>오늘은 어떤 문제를 풀까요?</h1><p>직접 모은 문제를 분석하고, 네 가지 언어로 반복해서 연습하세요.</p></div><Link className="button primary large" to="/problems/new"><Plus size={18} /> 새 문제 등록</Link></header>
    <section className="library-toolbar"><label className="search-box"><Search size={18} /><input aria-label="문제 검색" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="문제 이름으로 검색" /></label><div className="filter-pills">{[['all','전체'],['solved','풀이 완료'],['ready','풀이 가능'],['draft','편집 중'],['needs_review','검토 필요']] .map(([id,label]) => <button key={id} className={filter === id ? 'active' : ''} onClick={() => setFilter(id)}>{label}</button>)}</div></section>
    {error && <div className="notice error">{error}<button onClick={load}>다시 시도</button></div>}
    {loading ? <div className="loading-grid">{[1,2,3].map((n) => <div className="skeleton card" key={n} />)}</div> : filtered.length === 0 ? <div className="empty"><BookOpen /><strong>{items.length ? '검색 결과가 없습니다' : '첫 문제를 등록해 보세요'}</strong><p>{items.length ? '다른 검색어나 상태를 선택해 보세요.' : '문제 텍스트나 이미지만 있으면 시작할 수 있습니다.'}</p>{!items.length && <Link className="button primary" to="/problems/new">문제 등록하기</Link>}</div> : <div className="problem-grid">{filtered.map((item, index) => <article className="problem-card" key={item.id}>
      <div className="card-top"><span className="problem-number">{String(index + 1).padStart(2, '0')}</span><div className="card-badges"><StatusBadge status={item.status} />{item.is_solved && <span className="status-badge status-solved" title="전체 통과한 제출 기록이 있습니다.">풀이 완료</span>}</div></div><h2>{item.title}</h2><p>테스트 리비전 {item.test_revision} · {formatDate(item.updated_at)}</p><div className="card-actions"><Link to={`/problems/${item.id}`} className="card-open">문제 풀기 <ArrowRight size={17} /></Link><Link aria-label={`${item.title} 편집`} className="icon-button" to={`/problems/${item.id}/edit`}><MoreHorizontal /></Link><button aria-label={`${item.title} 삭제`} className="icon-button danger" onClick={() => void remove(item)}><Trash2 size={17} /></button></div>
    </article>)}</div>}
  </div>;
}
