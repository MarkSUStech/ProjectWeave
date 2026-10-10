import { Route, Routes, useLocation } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { AppearanceProvider } from './components/settings/AppearanceProvider'
import { useUiReducedMotion } from './hooks/useUiReducedMotion'
import { TooltipProvider } from './components/ui/upstream/tooltip'
import { AppShell } from './components/AppShell'
import { Spinner } from './components/ui/Feedback'
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ProjectDetailPage = lazy(() => import('./pages/ProjectDetailPage'))
const IdePage = lazy(() => import('./pages/IdePage'))
const ConceptsPage = lazy(() => import('./pages/ConceptsPage'))
const AssessmentPage = lazy(() => import('./pages/AssessmentPage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))

export default function App() {
  const location = useLocation()
  const ide = location.pathname.endsWith('/ide')
  const reduced = useUiReducedMotion()
  const routes = <Suspense fallback={<Spinner label="正在加载页面…" />}><Routes location={location}>
    <Route path="/" element={<DashboardPage />} />
    <Route path="/projects/:id" element={<ProjectDetailPage />} />
    <Route path="/projects/:id/ide" element={<IdePage />} />
    <Route path="/projects/:id/assessment" element={<AssessmentPage />} />
    <Route path="/concepts" element={<ConceptsPage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes></Suspense>
  return (
    <AppearanceProvider>
      <TooltipProvider delayDuration={350}><AnimatePresence mode="wait" initial={false}>
        <motion.div key={location.pathname} className="min-h-full" initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: reduced ? 1 : 0 }} transition={{ duration: reduced ? 0 : 0.2 }}>
          {ide ? routes : <AppShell>{routes}</AppShell>}
        </motion.div>
      </AnimatePresence></TooltipProvider>
    </AppearanceProvider>
  )
}
