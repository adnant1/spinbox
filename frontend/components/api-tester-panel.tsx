"use client";

import { useLayoutEffect, useRef } from "react";

import { BeakerIcon, SendIcon } from "@/components/icons";
import { ResponsePanel } from "@/components/response-panel";
import type { ProxyExecutionResult, SandboxRoute } from "@/lib/types";

interface ApiTesterPanelProps {
  endpoints: SandboxRoute[];
  method: string;
  path: string;
  body: string;
  sending: boolean;
  error: string | null;
  response: ProxyExecutionResult | null;
  onEndpointSelect: (endpoint: SandboxRoute) => void;
  onPathChange: (value: string) => void;
  onBodyChange: (value: string) => void;
  onSend: () => void;
}

export function ApiTesterPanel({
  endpoints,
  method,
  path,
  body,
  sending,
  error,
  response,
  onEndpointSelect,
  onPathChange,
  onBodyChange,
  onSend,
}: ApiTesterPanelProps) {
  const showBody = method === "POST" || method === "PUT" || method === "PATCH";
  const bodyTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  useLayoutEffect(() => {
    const textarea = bodyTextareaRef.current;
    if (!textarea || !showBody) {
      return;
    }

    textarea.style.height = "0px";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [body, showBody]);

  return (
    <section className="api-tester">
      <div className="api-tester__header">
        <BeakerIcon className="api-tester__header-icon" />
        <span className="api-tester__header-title">API Tester</span>
      </div>
      <div className="api-tester__body">
        <div className={`api-tester__request ${showBody ? "api-tester__request--with-body" : ""}`}>
          <div className="api-tester__label">Request</div>
          <div className="api-tester__request-row">
            <div className={`api-tester__method-badge api-tester__method-badge--${method.toLowerCase()}`}>{method}</div>
            <input
              className="api-tester__path-input"
              value={path}
              onChange={(event) => onPathChange(event.target.value)}
              placeholder="/users"
              aria-label="Endpoint path"
            />
          </div>
          {endpoints.length > 0 ? (
            <div className="api-tester__endpoint-list">
              {endpoints.map((endpoint) => {
                const active = endpoint.method === method && endpoint.path === path;
                return (
                  <button
                    key={`${endpoint.method}-${endpoint.path}`}
                    className={active ? "api-tester__endpoint api-tester__endpoint--active" : "api-tester__endpoint"}
                    type="button"
                    onClick={() => onEndpointSelect(endpoint)}
                  >
                    <span className={`api-tester__endpoint-method api-tester__endpoint-method--${endpoint.method.toLowerCase()}`}>
                      {endpoint.method}
                    </span>
                    <span className="api-tester__endpoint-path">{endpoint.path}</span>
                  </button>
                );
              })}
            </div>
          ) : null}
          {showBody ? (
            <label className="api-tester__body-field">
              <div className="api-tester__body-header">
                <span className="api-tester__body-title">Request body</span>
                <span className="api-tester__body-badge">JSON</span>
              </div>
              <textarea ref={bodyTextareaRef} value={body} onChange={(event) => onBodyChange(event.target.value)} />
            </label>
          ) : null}
          <button className="api-tester__send" type="button" onClick={onSend} disabled={sending}>
            <SendIcon className="api-tester__send-icon" />
            <span>{sending ? "Sending request" : "Send Request"}</span>
          </button>
          {error ? <p className="api-tester__error">{error}</p> : null}
        </div>
        <ResponsePanel response={response} />
      </div>
    </section>
  );
}
