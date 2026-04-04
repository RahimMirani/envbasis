import type { PointerEvent } from 'react';

export function updateButtonGlow(event: PointerEvent<HTMLButtonElement>): void {
  const rect = event.currentTarget.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;

  event.currentTarget.style.setProperty('--x', `${x}px`);
  event.currentTarget.style.setProperty('--y', `${y}px`);
}

export function resetButtonGlow(event: PointerEvent<HTMLButtonElement>): void {
  event.currentTarget.style.setProperty('--x', '50%');
  event.currentTarget.style.setProperty('--y', '50%');
}
