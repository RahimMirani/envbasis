import { useRef } from 'react';
import Modal from './Modal';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  description: string;
  errorMessage?: string | null;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
  isBusy?: boolean;
  tone?: 'primary' | 'danger';
}

export default function ConfirmDialog({
  isOpen,
  title,
  description,
  errorMessage,
  confirmLabel,
  onConfirm,
  onClose,
  isBusy = false,
  tone = 'danger',
}: ConfirmDialogProps) {
  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={title}
      initialFocusRef={cancelButtonRef}
      footer={
        <>
          <button ref={cancelButtonRef} className="btn btn-secondary" onClick={onClose} disabled={isBusy}>
            Cancel
          </button>
          <button className={`btn ${tone === 'danger' ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm} disabled={isBusy}>
            {isBusy ? 'Working...' : confirmLabel}
          </button>
        </>
      }
    >
      <p>{description}</p>
      {errorMessage ? (
        <p className="confirm-dialog-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </Modal>
  );
}
