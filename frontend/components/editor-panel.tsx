"use client";

import { useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import type { Monaco } from "@monaco-editor/react";

import { CheckCircleIcon, FileCodeIcon, GitBranchIcon, SaveIcon } from "@/components/icons";
import type { ValidationErrorDetail } from "@/lib/types";

const SANDBOX_MONACO_THEME = "spinbox-sandbox";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => <div className="editor-fallback">Loading editor...</div>,
});

function matchesValidationDetail(left: ValidationErrorDetail | null, right: ValidationErrorDetail | null): boolean {
  if (!left || !right) {
    return false;
  }

  return (
    left.detail === right.detail &&
    left.kind === right.kind &&
    (left.line ?? null) === (right.line ?? null) &&
    (left.column ?? null) === (right.column ?? null)
  );
}

interface EditorPanelProps {
  path: string;
  value: string;
  dirty: boolean;
  saving: boolean;
  error: ValidationErrorDetail | null;
  validationError: ValidationErrorDetail | null;
  onChange: (value: string) => void;
  onSave: () => void;
}

export function EditorPanel({
  path,
  value,
  dirty,
  saving,
  error,
  validationError,
  onChange,
  onSave,
}: EditorPanelProps) {
  const monacoRef = useRef<Monaco | null>(null);
  const modelRef = useRef<any>(null);
  const lineCount = value.split("\n").length;
  const pathSegments = path.split("/").filter(Boolean);
  const fileName = pathSegments[pathSegments.length - 1] ?? "routes.py";
  const workspaceName = "main";
  const showLastSaveError = dirty && error && !matchesValidationDetail(error, validationError);

  function handleBeforeMount(monaco: Monaco) {
    monaco.editor.defineTheme(SANDBOX_MONACO_THEME, {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "comment", foreground: "6A9955" },
        { token: "string", foreground: "CE9178" },
        { token: "keyword", foreground: "569CD6" },
        { token: "type.identifier", foreground: "4EC9B0" },
        { token: "number", foreground: "B5CEA8" },
      ],
      colors: {
        "editor.background": "#1E1E1E",
        "editorLineNumber.foreground": "#6F6F76",
        "editorLineNumber.activeForeground": "#85858D",
        "editor.lineHighlightBackground": "#FFFFFF06",
        "editor.selectionBackground": "#264F78AA",
        "editor.inactiveSelectionBackground": "#264F7866",
        "editorCursor.foreground": "#AEAFAD",
        "editorWhitespace.foreground": "#FFFFFF10",
        "editorIndentGuide.background1": "#FFFFFF10",
        "scrollbarSlider.background": "#79797959",
        "scrollbarSlider.hoverBackground": "#7979798C",
        "scrollbarSlider.activeBackground": "#797979A6",
      },
    });
  }

  useEffect(() => {
    const monaco = monacoRef.current;
    const model = modelRef.current;
    if (!monaco || !model) {
      return;
    }

    const activeError = validationError ?? error;
    monaco.editor.setModelMarkers(model, "spinbox-validation", []);
    monaco.editor.setModelMarkers(model, "spinbox-save", []);
    if (activeError?.line) {
      const startColumn = Math.max(activeError.column ?? 1, 1);
      monaco.editor.setModelMarkers(model, validationError ? "spinbox-validation" : "spinbox-save", [
        {
          startLineNumber: activeError.line,
          startColumn,
          endLineNumber: activeError.line,
          endColumn: startColumn + 1,
          message: activeError.detail,
          severity: monaco.MarkerSeverity.Error,
        },
      ]);
      return;
    }

  }, [error, validationError]);

  return (
    <section className="editor-panel">
      <div className="editor-panel__topbar">
        <div className="editor-panel__tab">
          <FileCodeIcon className="editor-panel__tab-icon" />
          <span>{fileName}</span>
        </div>
        <div className="editor-panel__toolbar">
          <div className={`editor-panel__saved ${dirty ? "editor-panel__saved--dirty" : ""}`}>
            <CheckCircleIcon className="editor-panel__saved-icon" />
            <span>{dirty ? "Unsaved" : "Saved"}</span>
          </div>
          <button className="editor-panel__save" type="button" onClick={onSave} disabled={!dirty || saving}>
            <SaveIcon className="editor-panel__save-icon" />
            <span>{saving ? "Saving" : "Save"}</span>
          </button>
          <button className="editor-panel__toolbar-icon" type="button" aria-label="More editor actions" />
        </div>
      </div>
      <div className="editor-panel__subbar">
        <GitBranchIcon className="editor-panel__subbar-icon" />
        <span className="editor-panel__subbar-text">{workspaceName}</span>
        <span className="editor-panel__subbar-separator">/</span>
        <span className="editor-panel__subbar-text">{fileName}</span>
        <span className="editor-panel__language">Python</span>
      </div>
      {validationError ? <p className="editor-panel__error">Current issue: {validationError.detail}</p> : null}
      {showLastSaveError ? <p className="editor-panel__error">Last save failed: {error.detail}</p> : null}
      <div className="editor-panel__shell">
        <div className="editor-panel__monaco">
          <MonacoEditor
            beforeMount={handleBeforeMount}
            onMount={(editor, monaco) => {
              modelRef.current = editor.getModel();
              monacoRef.current = monaco;
              const activeError = validationError ?? error;
              monaco.editor.setModelMarkers(modelRef.current, "spinbox-validation", []);
              monaco.editor.setModelMarkers(modelRef.current, "spinbox-save", []);
              if (activeError?.line && modelRef.current) {
                const startColumn = Math.max(activeError.column ?? 1, 1);
                monaco.editor.setModelMarkers(
                  modelRef.current,
                  validationError ? "spinbox-validation" : "spinbox-save",
                  [
                  {
                    startLineNumber: activeError.line,
                    startColumn,
                    endLineNumber: activeError.line,
                    endColumn: startColumn + 1,
                    message: activeError.detail,
                    severity: monaco.MarkerSeverity.Error,
                  },
                  ],
                );
              }
            }}
            path={path}
            height="100%"
            language="python"
            theme={SANDBOX_MONACO_THEME}
            value={value}
            onChange={(nextValue) => onChange(nextValue ?? "")}
            options={{
              automaticLayout: true,
              minimap: { enabled: false },
              glyphMargin: false,
              folding: false,
              scrollBeyondLastLine: false,
              wordWrap: "off",
              lineNumbersMinChars: 3,
              lineHeight: 21,
              fontSize: 13,
              fontFamily: "'JetBrains Mono', monospace",
              padding: { top: 12, bottom: 12 },
              smoothScrolling: true,
              stickyScroll: { enabled: false },
              scrollbar: {
                vertical: "auto",
                horizontal: "auto",
                verticalScrollbarSize: 12,
                horizontalScrollbarSize: 12,
                alwaysConsumeMouseWheel: false,
              },
              overviewRulerBorder: false,
              overviewRulerLanes: 0,
              renderLineHighlight: "line",
              roundedSelection: false,
              tabSize: 4,
              insertSpaces: true,
            }}
          />
        </div>
      </div>
      <div className="editor-panel__footer">
        <div className="editor-panel__footer-group">
          <span>{lineCount} lines</span>
          <span>UTF-8</span>
        </div>
        <div className="editor-panel__footer-group">
          <span>Python 3.11</span>
          <span>FastAPI 0.110</span>
        </div>
      </div>
    </section>
  );
}
