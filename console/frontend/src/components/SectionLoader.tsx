import { useEffect, useState } from 'react';

interface SectionLoaderProps {
  label: string;
}

export default function SectionLoader({ label }: SectionLoaderProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setVisible(true), 150);
    return () => clearTimeout(id);
  }, []);

  if (!visible) return null;

  return (
    <div className="section-loader" aria-live="polite" aria-busy="true">
      <span className="section-loader-text">{label}</span>
      <span className="section-loader-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}
