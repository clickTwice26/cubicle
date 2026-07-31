import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { sql, PostgreSQL } from '@codemirror/lang-sql'
import { useMemo } from 'react'
import type { EditorProps } from './CodeEditor'

const PYTHON = [python()]
const SQL = [sql({ dialect: PostgreSQL, upperCaseKeywords: false })]
const PLAIN: never[] = []

export default function CodeMirrorEditor({
  value,
  onChange,
  language = 'python',
  minHeight = 360,
  readOnly = false,
}: EditorProps) {
  const extensions = useMemo(
    () => (language === 'python' ? PYTHON : language === 'sql' ? SQL : PLAIN),
    [language],
  )

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      readOnly={readOnly}
      extensions={extensions}
      minHeight={`${minHeight}px`}
      basicSetup={{
        lineNumbers: true,
        foldGutter: false,
        highlightActiveLine: !readOnly,
        highlightActiveLineGutter: !readOnly,
        autocompletion: false,
        searchKeymap: false,
        bracketMatching: true,
        closeBrackets: !readOnly,
      }}
      theme="none"
    />
  )
}
