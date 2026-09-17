import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker';
import { App } from './App';
import './styles.css';
import './mobile.css';

self.MonacoEnvironment = {
  getWorker(_: string, label: string) { return label === 'typescript' || label === 'javascript' ? new tsWorker() : new editorWorker(); },
};

loader.config({ monaco });
monaco.editor.defineTheme('loopcode-dark', {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'comment', foreground: '71869D', fontStyle: 'italic' },
    { token: 'keyword', foreground: '78E7C5' },
    { token: 'string', foreground: 'E8CF8D' },
    { token: 'number', foreground: '9FC5FF' },
  ],
  colors: {
    'editor.background': '#07111E',
    'editor.foreground': '#DCE6F1',
    'editorLineNumber.foreground': '#41566D',
    'editorLineNumber.activeForeground': '#8CA0B7',
    'editorCursor.foreground': '#5EE6BD',
    'editor.selectionBackground': '#214B56',
    'editor.inactiveSelectionBackground': '#173540',
    'editorIndentGuide.background1': '#15283B',
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>);
