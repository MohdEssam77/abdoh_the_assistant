KaTeX 0.19.1 (MIT, see LICENSE) from the npm package `katex`: `dist/katex.min.js`,
`dist/katex.min.css` and the `.woff2` fonts (the app's webview reads woff2, so the CSS's
woff/ttf fallbacks are left out). The board (`../../board.js`) uses it for math.

`contrib/mhchem.min.js`: KaTeX's mhchem extension (\ce{} for chemistry), from the same
KaTeX 0.19.1 release, unchanged.
