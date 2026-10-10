/**
 * 构建在 Web Worker（module 模式）中执行用户代码的脚本文本。
 *
 * 两种模式：
 * - buildWorkerSource：普通运行，输出流式回传，结束发 done；
 * - buildTestSource：注入微型测试运行时（describe/it/test + expect 断言），
 *   用例逐个执行并回传 test-result，最后发 test-summary + done。
 *
 * Worker 无法访问 DOM 与应用状态；终止权在主线程（见 runJavaScript）。
 */

const CONSOLE_CAPTURE = `const __serialize = (value) => {
  if (typeof value === 'string') return value
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  if (typeof value === 'function') return 'ƒ ' + (value.name || 'anonymous') + '()'
  if (typeof value === 'symbol') return value.toString()
  if (typeof value === 'bigint') return value.toString() + 'n'
  if (value instanceof Error) return value.stack || String(value)
  if (value instanceof Date) return value.toISOString()
  try {
    const seen = new WeakSet()
    return JSON.stringify(value, (_key, v) => {
      if (typeof v === 'object' && v !== null) {
        if (seen.has(v)) return '[Circular]'
        seen.add(v)
      }
      if (typeof v === 'function') return 'ƒ ' + (v.name || 'anonymous') + '()'
      if (typeof v === 'bigint') return v.toString() + 'n'
      return v
    }, 2)
  } catch (err) {
    return String(value)
  }
}
const __send = (level, args) => {
  self.postMessage({ type: 'console', level, text: args.map((a) => __serialize(a)).join(' ') })
}
self.console = {
  log: (...a) => __send('log', a),
  info: (...a) => __send('info', a),
  warn: (...a) => __send('warn', a),
  error: (...a) => __send('error', a),
  debug: (...a) => __send('log', a),
}
// 变量状态观察 API（§9.4）：学生在代码中调用 observe('name', value)，
// 值经 __serialize 后流式上报，供 variables-state 组件渲染真实执行数据。
function observe(name, value) {
  self.postMessage({ type: 'observed', name: String(name), text: __serialize(value) })
}`

export function buildWorkerSource(userCode: string): string {
  return `${CONSOLE_CAPTURE}
;(async () => {
${userCode}
})()
  .then((result) => {
    self.postMessage({ type: 'done', result: __serialize(result) })
  })
  .catch((err) => {
    self.postMessage({ type: 'error', message: err && err.stack ? String(err.stack) : String(err) })
  })
`
}

/** 测试运行时：用例收集、断言库与顺序执行。 */
const TEST_RUNTIME = `
const __deepEqual = (a, b, seen) => {
  if (a === b) return true
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return Object.is(a, b)
  if (seen.has(a)) return false
  seen.add(a)
  if (Array.isArray(a) !== Array.isArray(b)) return false
  if (a instanceof Date && b instanceof Date) return a.getTime() === b.getTime()
  const keysA = Object.keys(a)
  const keysB = Object.keys(b)
  if (keysA.length !== keysB.length) return false
  return keysA.every((k) => __deepEqual(a[k], b[k], seen))
}
const __tests = []
const __suite = { prefix: '' }
const __fullName = (name) => (__suite.prefix ? __suite.prefix + ' › ' + name : name)
function describe(name, fn) {
  const prev = __suite.prefix
  __suite.prefix = __fullName(name)
  try { fn() } finally { __suite.prefix = prev }
}
function it(name, fn) { __tests.push({ name: __fullName(name), fn }) }
const test = it
const __assert = (condition, message) => {
  if (!condition) throw new Error(message)
}
const __makeMatchers = (actual, negated) => ({
  toBe(expected) {
    __assert((actual === expected) !== negated,
      negated
        ? 'expected value NOT to be ' + __serialize(expected) + '（实际相等）'
        : 'expected ' + __serialize(actual) + ' to be ' + __serialize(expected))
  },
  toEqual(expected) {
    const equal = __deepEqual(actual, expected, new WeakSet())
    __assert(equal !== negated,
      negated
        ? 'expected values NOT to be deeply equal'
        : 'expected values to be deeply equal:\\n  actual:   ' + __serialize(actual) + '\\n  expected: ' + __serialize(expected))
  },
  toBeTruthy() {
    __assert(Boolean(actual) === !negated,
      negated ? 'expected value NOT to be truthy: ' + __serialize(actual) : 'expected ' + __serialize(actual) + ' to be truthy')
  },
  toBeFalsy() {
    __assert(Boolean(actual) === negated,
      negated ? 'expected value NOT to be falsy: ' + __serialize(actual) : 'expected ' + __serialize(actual) + ' to be falsy')
  },
  toContain(item) {
    let contains = false
    if (typeof actual === 'string') contains = actual.includes(item)
    else if (Array.isArray(actual)) contains = actual.includes(item)
    __assert(contains === !negated,
      negated
        ? 'expected ' + __serialize(actual) + ' NOT to contain ' + __serialize(item)
        : 'expected ' + __serialize(actual) + ' to contain ' + __serialize(item))
  },
  toThrow(expectedPart) {
    __assert(typeof actual === 'function', 'toThrow 只能用于函数，收到 ' + __serialize(actual))
    let thrown = null
    try { actual() } catch (err) { thrown = err }
    const threw = thrown !== null
    const partOk = threw && (expectedPart === undefined || String(thrown.message || thrown).includes(expectedPart))
    __assert((threw && partOk) === !negated,
      negated
        ? 'expected function NOT to throw（或错误不含 ' + __serialize(expectedPart) + '）'
        : 'expected function to throw' + (expectedPart !== undefined ? '（含 ' + __serialize(expectedPart) + '）' : '') + (threw ? '，实际抛出：' + String(thrown && thrown.message) : '，实际未抛出'))
  },
  get not() { return __makeMatchers(actual, !negated) },
})
function expect(actual) { return __makeMatchers(actual, false) }`

export function buildTestSource(userCode: string): string {
  return `${CONSOLE_CAPTURE}${TEST_RUNTIME}
;(async () => {
${userCode}
})()
  .then(async () => {
    let passed = 0
    let failed = 0
    for (const testCase of __tests) {
      const startedAt = Date.now()
      try {
        await testCase.fn()
        passed += 1
        self.postMessage({ type: 'test-result', name: testCase.name, status: 'passed', durationMs: Date.now() - startedAt })
      } catch (err) {
        failed += 1
        self.postMessage({
          type: 'test-result',
          name: testCase.name,
          status: 'failed',
          error: err && err.message ? String(err.message) : String(err),
          durationMs: Date.now() - startedAt,
        })
      }
    }
    self.postMessage({ type: 'test-summary', total: __tests.length, passed, failed })
    self.postMessage({ type: 'done', result: __tests.length + ' tests' })
  })
  .catch((err) => {
    self.postMessage({ type: 'error', message: err && err.stack ? String(err.stack) : String(err) })
  })
`
}
