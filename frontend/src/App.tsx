import { Route, Routes } from 'react-router-dom'
import DashboardPage from './pages/DashboardPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import IdePage from './pages/IdePage'
import ConceptsPage from './pages/ConceptsPage'
import AssessmentPage from './pages/AssessmentPage'
import NotFoundPage from './pages/NotFoundPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/projects/:id" element={<ProjectDetailPage />} />
      <Route path="/projects/:id/ide" element={<IdePage />} />
      <Route path="/projects/:id/assessment" element={<AssessmentPage />} />
      <Route path="/concepts" element={<ConceptsPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
