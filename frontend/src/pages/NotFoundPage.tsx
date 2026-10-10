import { Link } from 'react-router-dom'
import { Button } from '../components/ui/Button'

export default function NotFoundPage() {
  return (
    <div className="grid min-h-full place-items-center px-6">
      <div className="text-center">
        <p className="mb-2 font-mono text-5xl text-ink-faint">404</p>
        <p className="mb-6 text-sm text-ink-dim">页面不存在或已被删除。</p>
        <Link to="/">
          <Button variant="outline">返回项目列表</Button>
        </Link>
      </div>
    </div>
  )
}
