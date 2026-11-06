module.exports = {
  presets: [
    [
      '@babel/preset-env',
      { targets: { node: 'current' }, useBuiltIns: 'usage', corejs: '3.38' },
    ],
    '@babel/preset-typescript',
  ],
  plugins: [],
}
