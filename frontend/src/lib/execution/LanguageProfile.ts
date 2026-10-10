/**
 * Language Profile：描述一种编程语言的元数据与能力，不含运行逻辑。
 *
 * 语言扩展 = 注册一个 Profile + 实现一个 Backend，不需要修改
 * Curriculum Engine、Learner Engine 或 TeachingScene。
 */

export interface LanguageProfile {
  /** 唯一标识（如 'typescript', 'python', 'cpp'）。 */
  languageId: string
  displayName: string
  /** 源码文件扩展名（不含点，小写）。 */
  sourceExtensions: string[]
  /** 测试文件命名模式（如 /\.test\.ts$/）。 */
  testFilePattern: RegExp
  /** 模块系统：决定 import 解译策略。 */
  moduleSystem: 'esm' | 'commonjs' | 'python-import' | 'cpp-include' | 'none'
  /** 该语言支持的执行后端。 */
  supportedBackends: string[]
  /** 可选：注释前缀（用于生成任务初始代码等）。 */
  commentPrefix?: string
}

/** TypeScript / JavaScript Profile（当前唯一完整支持的语言）。 */
export const typescriptProfile: LanguageProfile = {
  languageId: 'typescript',
  displayName: 'TypeScript / JavaScript',
  sourceExtensions: ['ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs', 'mts', 'cts'],
  testFilePattern: /\.test\.[cm]?[jt]s$/,
  moduleSystem: 'esm',
  supportedBackends: ['browser-worker'],
  commentPrefix: '//',
}

/**
 * Python Profile（P4.2a 仅定义元数据，不伪造运行能力）。
 * 支持后端为空 → registry 会返回"不支持"错误。
 */
export const pythonProfile: LanguageProfile = {
  languageId: 'python',
  displayName: 'Python',
  sourceExtensions: ['py'],
  testFilePattern: /_test\.py$|test_.*\.py$/,
  moduleSystem: 'python-import',
  supportedBackends: [], // 待 remote-pytest 后端实现
  commentPrefix: '#',
}

/**
 * C++ Profile（P4.2a 仅定义元数据，不伪造运行能力）。
 * 支持后端为空 → registry 会返回"不支持"错误。
 */
export const cppProfile: LanguageProfile = {
  languageId: 'cpp',
  displayName: 'C++',
  sourceExtensions: ['cpp', 'cc', 'cxx', 'c', 'h', 'hpp'],
  testFilePattern: /_test\.cpp$|test_.*\.cpp$/,
  moduleSystem: 'cpp-include',
  supportedBackends: [], // 待 remote-cmake 后端实现
  commentPrefix: '//',
}

/** 已注册的语言 Profile 注册表。 */
const profiles = new Map<string, LanguageProfile>()

export function registerProfile(profile: LanguageProfile): void {
  profiles.set(profile.languageId, profile)
}

export function getProfile(languageId: string): LanguageProfile | undefined {
  return profiles.get(languageId)
}

export function listProfiles(): LanguageProfile[] {
  return [...profiles.values()]
}

/** 根据文件扩展名推断语言。 */
export function detectLanguage(filePath: string): string | null {
  const ext = filePath.split('.').pop()?.toLowerCase() ?? ''
  for (const profile of profiles.values()) {
    if (profile.sourceExtensions.includes(ext)) return profile.languageId
  }
  return null
}

/** 判断文件是否为该语言的测试文件。 */
export function isTestFile(filePath: string, languageId: string): boolean {
  const profile = profiles.get(languageId)
  return profile ? profile.testFilePattern.test(filePath) : false
}

// 注册内置 Profile
registerProfile(typescriptProfile)
registerProfile(pythonProfile)
registerProfile(cppProfile)
