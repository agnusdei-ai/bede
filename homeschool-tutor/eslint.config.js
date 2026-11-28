// ESLint for the app's TypeScript (code-health tracker #924).
//
// Deliberately small: the TypeScript compiler already checks types, so this
// adds what tsc cannot see, chiefly React hook rules (a missing effect
// dependency is a stale value at runtime, and nothing else catches it) and
// the typescript-eslint correctness set. Tests may use `any` to stand in for
// browser globals; shipped code may not.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'ios', 'android', 'node_modules', 'coverage'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' }],
    },
  },
  {
    files: ['src/**/*.test.{ts,tsx}', 'src/test/**'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    // A mock records the element it was called on, which needs `this`.
    rules: { '@typescript-eslint/no-explicit-any': 'off', '@typescript-eslint/no-this-alias': 'off' },
  },
)
