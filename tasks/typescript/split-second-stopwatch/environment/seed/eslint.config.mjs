// @ts-check

import tsEslint from 'typescript-eslint'

export default tsEslint.config(...tsEslint.configs.recommended, {
  ignores: [
    // # Protected or generated
    '.git/**/*',
    '.vscode/**/*',

    //# When using npm
    'node_modules/**/*',

    // # Configuration files
    'babel.config.cjs',
    'jest.config.cjs',
  ],
})
