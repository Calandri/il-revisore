import { defineConfig } from 'vite';
import dts from 'vite-plugin-dts';
import { resolve } from 'path';

export default defineConfig({
  plugins: [
    dts({
      insertTypesEntry: true,
    }),
  ],
  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'IssueWidget',
      formats: ['umd', 'es', 'iife'],
      fileName: (format) => {
        if (format === 'iife') return 'issue-widget.min.js';
        return `issue-widget.${format}.js`;
      },
    },
    rollupOptions: {
      output: {
        globals: {},
        inlineDynamicImports: true,
      },
    },
    minify: 'esbuild',
    sourcemap: true,
    cssCodeSplit: false,
  },
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
});
