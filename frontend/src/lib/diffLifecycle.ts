interface DiffModelOwner {
  getModel(): { original: { dispose: () => void }; modified: { dispose: () => void } } | null
  setModel: (model: null) => void
}

/** Monaco 要求先解除 Diff 模型绑定，再释放模型；避免包装库默认释放顺序的异常。 */
export function releaseDiffModels(editor: DiffModelOwner): void {
  const models = editor.getModel()
  editor.setModel(null)
  models?.original.dispose()
  models?.modified.dispose()
}
