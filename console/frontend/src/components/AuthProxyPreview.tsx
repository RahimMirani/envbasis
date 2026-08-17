import { useEffect, useMemo, useState } from 'react';

const PATH = 'POST /openai/v1/chat/completions';
const AUTH_LABEL = 'Authorization: Bearer ';
const TOKEN = 'envb_mi_8f2c…';
const TICK_MS = 28;
const HOLD_TICKS = 70;
const LOOP_GAP = 36;

function LockGlyph() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function Cursor() {
  return <span className="auth-proxy-cursor" />;
}

export default function AuthProxyPreview() {
  const prefersReduced = useMemo(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  );
  const [tick, setTick] = useState(0);

  const pathDone = 8 + PATH.length;
  const authDone = pathDone + 10 + AUTH_LABEL.length + TOKEN.length;
  const sendingAt = authDone + 12;
  const proxyAt = sendingAt + 16;
  const allowedAt = proxyAt + 18;
  const droppedAt = allowedAt + 16;
  const injectedAt = droppedAt + 16;
  const resetAt = injectedAt + HOLD_TICKS + LOOP_GAP;

  useEffect(() => {
    if (prefersReduced) return undefined;
    const id = window.setInterval(() => {
      setTick((current) => (current + 1 >= resetAt ? 0 : current + 1));
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, [prefersReduced, resetAt]);

  const pathTyped = prefersReduced ? PATH.length : Math.max(0, Math.min(PATH.length, tick - 8));
  const authStarted = prefersReduced || tick >= pathDone + 10;
  const authBudget = prefersReduced ? AUTH_LABEL.length + TOKEN.length : Math.max(0, tick - pathDone - 10);
  const authLabelTyped = Math.min(AUTH_LABEL.length, authBudget);
  const tokenTyped = Math.max(0, Math.min(TOKEN.length, authBudget - AUTH_LABEL.length));
  const typingPath = !prefersReduced && tick < pathDone && pathTyped < PATH.length;
  const typingAuth = !prefersReduced && authStarted && tick < authDone && tokenTyped < TOKEN.length;
  const sending = prefersReduced || tick >= sendingAt;
  const proxyVisible = prefersReduced || tick >= proxyAt;
  const allowed = prefersReduced || tick >= allowedAt;
  const dropped = prefersReduced || tick >= droppedAt;
  const injected = prefersReduced || tick >= injectedAt;

  return (
    <div className="auth-preview">
      <div className="auth-preview-card">
        <div className="auth-preview-top">
          <div className="auth-preview-project">
            <img src="/envbasis-mark.png" alt="" className="auth-preview-mark" />
            <span>Proxy server</span>
          </div>
          <span className="auth-preview-env">
            <span className="env-dot env-dot-production" />
            Production
          </span>
        </div>

        <div className="auth-preview-toolbar">
          <span>Agent proxy</span>
        </div>

        <div className="auth-proxy-flow">
          <div className={`auth-proxy-step${sending && !injected ? ' is-sending' : ''}`}>
            <span className="auth-proxy-label">Agent</span>
            <p className="auth-proxy-path">
              {PATH.slice(0, pathTyped)}
              {typingPath && <Cursor />}
            </p>
            {authStarted && (
              <p className="auth-proxy-meta">
                {AUTH_LABEL.slice(0, authLabelTyped)}
                <span className={`auth-proxy-token${dropped ? ' is-dropped' : ''}`}>
                  {TOKEN.slice(0, tokenTyped)}
                </span>
                {typingAuth && <Cursor />}
              </p>
            )}
          </div>

          <div className={`auth-proxy-rail${sending ? ' is-live' : ''}`} aria-hidden="true">
            <span className="auth-proxy-packet" />
          </div>

          <div className={`auth-proxy-step${proxyVisible ? ' is-visible' : ' is-pending'}${injected ? ' is-active' : ''}`}>
            <span className="auth-proxy-label">EnvBasis proxy</span>
            {proxyVisible && (
              <>
                <p className="auth-proxy-path">
                  {allowed ? 'Path allowed · machine token dropped' : 'Inspecting request…'}
                </p>
                <p className={`auth-proxy-meta auth-proxy-secret${injected ? ' is-locked' : ''}`}>
                  {injected ? (
                    <>
                      OPENAI_API_KEY <span className="auth-proxy-mask">••••••••••••</span>
                      <span className="auth-preview-lock">
                        <LockGlyph />
                      </span>
                    </>
                  ) : dropped ? (
                    'Injecting vaulted credential…'
                  ) : (
                    'Resolving provider credential…'
                  )}
                </p>
              </>
            )}
          </div>
        </div>
      </div>
      <p className="auth-demo-caption">
        Agents call OpenAI, Anthropic, and GitHub through EnvBasis. Provider keys never leave the vault.
      </p>
    </div>
  );
}
