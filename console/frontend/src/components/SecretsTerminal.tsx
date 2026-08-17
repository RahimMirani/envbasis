import { useEffect, useMemo, useState } from 'react';

// A quiet product demo: an .env types itself out, every value is encrypted
// in place, and the sync confirms. Decorative only — pages mark it aria-hidden.

const COMMAND = 'envbasis push --env production';
const ENV_LINES = [
  { key: 'DATABASE_URL', value: 'postgres://prod-db-1:5432/core' },
  { key: 'STRIPE_SECRET_KEY', value: 'sk_live_51Hx2P9fKq83M' },
  { key: 'JWT_SIGNING_KEY', value: 'hs512$c81f42aa9de1' },
  { key: 'OPENAI_API_KEY', value: 'sk-proj-mN4wXz8PqT2v' },
];
const OK_LINE = '4 secrets encrypted · synced to production';
const MASK = '••••••••••••';

const CHARS_PER_TICK = 1.6;
const TICK_MS = 30;

const LINE_TEXTS = [COMMAND, ...ENV_LINES.map((l) => `${l.key}=${l.value}`)];
const OFFSETS = LINE_TEXTS.reduce<number[]>((acc, text) => {
  acc.push((acc[acc.length - 1] ?? 0) + text.length);
  return acc;
}, []);
const TOTAL_CHARS = OFFSETS[OFFSETS.length - 1];

const T_TYPED = Math.ceil(TOTAL_CHARS / CHARS_PER_TICK);
const MASK_START = T_TYPED + 18;
const MASK_EVERY = 9;
const OK_AT = MASK_START + ENV_LINES.length * MASK_EVERY + 10;
const END_TICK = OK_AT + 2;

function LockGlyph() {
  return (
    <svg
      className="t-lock"
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
    >
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

export default function SecretsTerminal() {
  const prefersReduced = useMemo(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  );
  const [tick, setTick] = useState(prefersReduced ? END_TICK : 0);

  useEffect(() => {
    if (prefersReduced) return;
    const id = setInterval(() => {
      setTick((t) => {
        if (t >= END_TICK) {
          clearInterval(id);
          return t;
        }
        return t + 1;
      });
    }, TICK_MS);
    return () => clearInterval(id);
  }, [prefersReduced]);

  const availChars = tick * CHARS_PER_TICK;
  const typedFor = (i: number) => {
    const start = i === 0 ? 0 : OFFSETS[i - 1];
    return Math.max(0, Math.min(LINE_TEXTS[i].length, Math.floor(availChars - start)));
  };
  const typing = tick < T_TYPED;
  const maskedCount = Math.max(0, Math.min(ENV_LINES.length, Math.floor((tick - MASK_START) / MASK_EVERY) + 1));
  const okShown = tick >= OK_AT;

  const cmdTyped = typedFor(0);
  return (
    <div className="secrets-terminal">
      <div className="terminal-bar">
        <span className="terminal-dot" />
        <span className="terminal-dot" />
        <span className="terminal-dot" />
        <span className="terminal-title">production.env — envbasis</span>
      </div>
      <div className="terminal-body">
        <div className="t-line t-cmd">
          <span className="t-prompt">$ </span>
          {COMMAND.slice(0, cmdTyped)}
          {typing && cmdTyped < COMMAND.length && <span className="t-cursor" />}
        </div>
        {ENV_LINES.map((line, i) => {
          const typed = typedFor(i + 1);
          if (typed === 0) return null;
          const keyShown = line.key.slice(0, typed);
          const valueChars = Math.max(0, typed - line.key.length - 1);
          const masked = i < maskedCount;
          const isTypingThis = typing && typed < LINE_TEXTS[i + 1].length;
          return (
            <div className="t-line" key={line.key}>
              <span className="t-key">{keyShown}</span>
              {typed > line.key.length && <span className="t-eq">=</span>}
              {masked ? (
                <>
                  <span className="t-masked">{MASK}</span>
                  <LockGlyph />
                </>
              ) : (
                valueChars > 0 && <span className="t-val">{line.value.slice(0, valueChars)}</span>
              )}
              {isTypingThis && <span className="t-cursor" />}
            </div>
          );
        })}
        {okShown && <div className="t-line t-ok">✓ {OK_LINE}</div>}
        {okShown && (
          <div className="t-line t-cmd">
            <span className="t-prompt">$ </span>
            <span className="t-cursor" />
          </div>
        )}
      </div>
    </div>
  );
}
