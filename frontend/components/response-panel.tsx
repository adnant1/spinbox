import { CopyIcon, SendIcon } from "@/components/icons";
import type { ProxyExecutionResult } from "@/lib/types";

interface ResponsePanelProps {
  response: ProxyExecutionResult | null;
}

function renderBody(data: unknown): string {
  if (data === null || data === undefined) {
    return "No response body";
  }
  if (typeof data === "string") {
    return data;
  }
  return JSON.stringify(data, null, 2);
}

function renderHighlightedJson(data: unknown): React.ReactNode {
  const text = renderBody(data);
  const lines = text.split("\n");

  return lines.map((line, index) => {
    const keyMatch = line.match(/^(\s*)"([^"]+)":\s*(.*)$/);

    if (!keyMatch) {
      return (
        <span key={`${line}-${index}`} className="response-panel__line">
          {line}
          {index < lines.length - 1 ? "\n" : ""}
        </span>
      );
    }

    const [, indent, key, rawValue] = keyMatch;
    let value: React.ReactNode = rawValue;

    if (/^".*"$/.test(rawValue)) {
      value = <span className="response-panel__value response-panel__value--string">{rawValue}</span>;
    } else if (/^-?\d+(\.\d+)?$/.test(rawValue)) {
      value = <span className="response-panel__value response-panel__value--number">{rawValue}</span>;
    }

    return (
      <span key={`${line}-${index}`} className="response-panel__line">
        {indent}
        <span className="response-panel__key">"{key}"</span>
        {": "}
        {value}
        {index < lines.length - 1 ? "\n" : ""}
      </span>
    );
  });
}

export function ResponsePanel({ response }: ResponsePanelProps) {
  return (
    <section className="response-panel">
      <div className="response-panel__header">
        <span className="response-panel__title">Response</span>
      </div>
      {response ? (
        <>
          <div className="response-panel__meta">
            <span className="response-panel__meta-time">{response.durationMs}ms</span>
            <span className={response.status >= 400 ? "response-panel__status response-panel__status--danger" : "response-panel__status"}>
              {response.status >= 400 ? `${response.status} Error` : `${response.status} OK`}
            </span>
            <button className="response-panel__copy" type="button" aria-label="Copy response body">
              <CopyIcon className="response-panel__copy-icon" />
            </button>
          </div>
          <pre className="response-panel__body">{renderHighlightedJson(response.data)}</pre>
        </>
      ) : (
        <div className="response-panel__empty">
          <div className="response-panel__empty-icon-wrap">
            <SendIcon className="response-panel__empty-icon" />
          </div>
          <p>Send a request to see the response</p>
        </div>
      )}
    </section>
  );
}
