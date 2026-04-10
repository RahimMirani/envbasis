import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from 'react';

interface OwnerOnlyHintProps {
  children: ReactNode;
  message: string;
  className?: string;
}

export default function OwnerOnlyHint({
  children,
  message,
  className,
}: OwnerOnlyHintProps) {
  const [isVisible, setIsVisible] = useState(false);
  const hideTimeoutRef = useRef<number | null>(null);

  const clearHideTimeout = () => {
    if (hideTimeoutRef.current !== null) {
      window.clearTimeout(hideTimeoutRef.current);
      hideTimeoutRef.current = null;
    }
  };

  const showHint = () => {
    clearHideTimeout();
    setIsVisible(true);
  };

  const hideHint = () => {
    clearHideTimeout();
    setIsVisible(false);
  };

  const showTemporaryHint = () => {
    showHint();
    hideTimeoutRef.current = window.setTimeout(() => {
      setIsVisible(false);
      hideTimeoutRef.current = null;
    }, 1600);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLSpanElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }

    event.preventDefault();
    showTemporaryHint();
  };

  useEffect(() => {
    return () => {
      clearHideTimeout();
    };
  }, []);

  return (
    <span
      className={`owner-only-hint ${isVisible ? 'is-visible' : ''} ${className ?? ''}`.trim()}
      onMouseEnter={showHint}
      onMouseLeave={hideHint}
      onFocus={showHint}
      onBlur={hideHint}
      onClick={showTemporaryHint}
      onTouchStart={showTemporaryHint}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      role="button"
      aria-label={message}
    >
      <span className="owner-only-hint-target">{children}</span>
      <span className="owner-only-popup" role="status" aria-live="polite">
        {message}
      </span>
    </span>
  );
}
