import { Settings2 } from 'lucide-react'
import { Button } from '../ui/Button'
import { SettingsDialog } from './SettingsDialog'

export function SettingsButton() {
  return <SettingsDialog trigger={<Button variant="ghost" size="sm" aria-label="打开界面设置">
    <Settings2 className="size-4" /><span className="hidden lg:inline">设置</span>
  </Button>} />
}
