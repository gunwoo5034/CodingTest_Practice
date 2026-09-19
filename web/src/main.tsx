import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker';
import { App } from './App';
import './styles.css';

self.MonacoEnvironment = {
  getWorker(_: string, label: string) { return label === 'typescript' || label === 'javascript' ? new tsWorker() : new editorWorker(); },
};

loader.config({ monaco });
monaco.editor.defineTheme('loopcode-light', {
  base: 'vs',
  inherit: true,
  rules: [
    { token: 'comment', foreground: '6E7781', fontStyle: 'italic' },
    { token: 'keyword', foreground: '0066CC' },
    { token: 'string', foreground: '0A7A3D' },
    { token: 'number', foreground: '9A3E00' },
  ],
  colors: {
    'editor.background': '#FFFFFF',
    'editor.foreground': '#1D1D1F',
    'editorLineNumber.foreground': '#A1A1A6',
    'editorLineNumber.activeForeground': '#515154',
    'editorCursor.foreground': '#0066CC',
    'editor.selectionBackground': '#BBDDFB',
    'editor.inactiveSelectionBackground': '#E1EFFB',
    'editorIndentGuide.background1': '#E5E5EA',
    'editorIndentGuide.activeBackground1': '#C7C7CC',
    'editorGutter.background': '#FFFFFF',
    'editorWidget.background': '#FFFFFF',
    'editorWidget.border': '#D2D2D7',
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>);
