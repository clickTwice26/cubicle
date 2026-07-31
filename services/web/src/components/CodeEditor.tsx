import { Suspense, lazy } from 'react'
import { Skeleton } from './ui'

export interface EditorProps {
  value: string
  onChange?: (next: string) => void
  language?: 'python' | 'text'
  minHeight?: number
  readOnly?: boolean
}

// CodeMirror is a large dependency and only the file being edited needs it, so
// it is split into its own chunk and loaded on demand.
const CodeMirrorEditor = lazy(() => import('./CodeMirrorEditor'))

export function CodeEditor({ minHeight = 360, ...props }: EditorProps) {
  return (
    <Suspense
      fallback={
        <div className="p-4">
          <Skeleton style={{ height: minHeight - 32 }} className="w-full" />
        </div>
      }
    >
      <CodeMirrorEditor minHeight={minHeight} {...props} />
    </Suspense>
  )
}
