import type { ComponentProps } from 'react'
import { Button as ShadcnButton } from './upstream/button'

export interface ButtonProps extends Omit<ComponentProps<typeof ShadcnButton>, 'variant' | 'size'> {
  variant?: 'primary' | 'outline' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
}

/** 保持业务调用契约，基础交互与 Slot 复用 shadcn/ui。 */
export function Button({ variant = 'primary', size = 'md', ...props }: ButtonProps) {
  return <ShadcnButton variant={variant === 'primary' ? 'default' : variant === 'danger' ? 'destructive' : variant} size={size === 'md' ? 'default' : size} {...props} />
}
