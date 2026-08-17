import {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown } from 'lucide-react';

export interface SelectOption {
  value: string;
  label: string;
  /** Optional colored dot class, e.g. envDotClass('dev'). */
  dotClass?: string;
}

interface SelectProps {
  value: string;
  options: readonly SelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  id?: string;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}

const MENU_MAX_HEIGHT = 260;
const OPTION_HEIGHT = 34;

export function envDotClass(environmentName: string): string {
  // Environment names can contain spaces or symbols; keep the class name valid.
  const slug = String(environmentName || '')
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-');
  return `env-dot env-dot-${slug}`;
}

export default function Select({
  value,
  options,
  onChange,
  disabled = false,
  id,
  placeholder = 'Select…',
  className,
  ariaLabel,
}: SelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({});
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((option) => option.value === value) ?? null;

  useLayoutEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const updatePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) {
        return;
      }
      const estimatedHeight = Math.min(options.length * OPTION_HEIGHT + 10, MENU_MAX_HEIGHT);
      const spaceBelow = window.innerHeight - rect.bottom;
      const openUp = spaceBelow < estimatedHeight + 12 && rect.top > estimatedHeight + 12;
      const width = Math.max(rect.width, 180);
      setMenuStyle({
        position: 'fixed',
        left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
        width,
        top: openUp ? rect.top - estimatedHeight - 6 : rect.bottom + 6,
        maxHeight: estimatedHeight,
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [isOpen, options.length]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setIsOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const optionButtons = menuRef.current?.querySelectorAll<HTMLButtonElement>('[data-select-option]');
    if (!optionButtons?.length) {
      return;
    }
    const activeIndex = options.findIndex((option) => option.value === value);
    // preventScroll: the portal sits at the end of <body>, so focusing before the
    // fixed position is applied would scroll the whole page to the bottom.
    (optionButtons[activeIndex >= 0 ? activeIndex : 0] ?? optionButtons[0]).focus({
      preventScroll: true,
    });
    // Focus only when the menu opens; re-running on parent re-renders would
    // yank keyboard focus back to the selected option mid-navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const handleSelect = (nextValue: string) => {
    setIsOpen(false);
    triggerRef.current?.focus();
    if (nextValue !== value) {
      onChange(nextValue);
    }
  };

  const handleTriggerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      setIsOpen(true);
    }
  };

  const handleMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Tab') {
      setIsOpen(false);
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Home' && event.key !== 'End') {
      return;
    }
    event.preventDefault();
    const optionButtons = [...(menuRef.current?.querySelectorAll<HTMLButtonElement>('[data-select-option]') ?? [])];
    if (optionButtons.length === 0) {
      return;
    }
    const currentIndex = optionButtons.findIndex((button) => button === document.activeElement);
    let nextIndex = currentIndex;
    if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = optionButtons.length - 1;
    } else if (event.key === 'ArrowDown') {
      nextIndex = Math.min(currentIndex + 1, optionButtons.length - 1);
    } else {
      nextIndex = Math.max(currentIndex - 1, 0);
    }
    optionButtons[nextIndex]?.focus();
  };

  return (
    <>
      <button
        type="button"
        ref={triggerRef}
        id={id}
        className={`ui-select-trigger${isOpen ? ' is-open' : ''}${className ? ` ${className}` : ''}`}
        onClick={() => setIsOpen((current) => !current)}
        onKeyDown={handleTriggerKeyDown}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={ariaLabel}
      >
        {selected?.dotClass && <span className={selected.dotClass} />}
        <span className={`ui-select-value${selected ? '' : ' ui-select-placeholder'}`}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown size={13} className="ui-select-chevron" />
      </button>
      {isOpen &&
        createPortal(
          <div
            ref={menuRef}
            className="ui-select-menu"
            style={menuStyle}
            role="listbox"
            aria-label={ariaLabel}
            onKeyDown={handleMenuKeyDown}
          >
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                className={`ui-select-option${option.value === value ? ' is-active' : ''}`}
                onClick={() => handleSelect(option.value)}
                data-select-option
              >
                {option.dotClass && <span className={option.dotClass} />}
                <span className="ui-select-option-label">{option.label}</span>
                {option.value === value && <Check size={14} className="ui-select-check" />}
              </button>
            ))}
          </div>,
          document.body
        )}
    </>
  );
}
