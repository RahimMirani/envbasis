import { useEffect, useRef } from 'react';

interface CheckboxProps {
  checked: boolean;
  onChange: () => void;
  indeterminate?: boolean;
  disabled?: boolean;
  'aria-label'?: string;
}

export default function Checkbox({
  checked,
  onChange,
  indeterminate = false,
  disabled = false,
  'aria-label': ariaLabel,
}: CheckboxProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = indeterminate;
    }
  }, [indeterminate]);

  return (
    <label className={`cb-root${disabled ? ' cb-disabled' : ''}`}>
      <input
        ref={inputRef}
        type="checkbox"
        className="cb-input"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        aria-label={ariaLabel}
      />
      <span className="cb-box" aria-hidden="true">
        <svg
          className="cb-check"
          viewBox="0 0 12 10"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <polyline
            points="1.5,5 5,8.5 10.5,1.5"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="cb-dash" />
      </span>
    </label>
  );
}
