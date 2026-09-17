import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { EditProblemPage } from './pages/EditProblemPage';
import { LibraryPage } from './pages/LibraryPage';
import { NewProblemPage } from './pages/NewProblemPage';
import { WorkspacePage } from './pages/WorkspacePage';

export function App() {
  return <Routes><Route element={<AppShell />}><Route index element={<LibraryPage />} /><Route path="problems/new" element={<NewProblemPage />} /><Route path="problems/:id/edit" element={<EditProblemPage />} /><Route path="problems/:id" element={<WorkspacePage />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes>;
}
