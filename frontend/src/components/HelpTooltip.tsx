import { useState, useRef, useEffect } from 'react';

interface HelpTooltipProps {
  text: string;
  className?: string;
}

const HelpTooltip = ({ text, className = '' }: HelpTooltipProps) => {
  const [show, setShow] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setShow(false);
    };
    if (show) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [show]);

  return (
    <div className={`relative inline-flex ${className}`} ref={ref}>
      <button
        type="button"
        onClick={() => setShow(!show)}
        onBlur={() => setShow(false)}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-stone-300 bg-surface text-stone-500 hover:bg-stone-200 hover:text-navy focus:outline-none focus:ring-2 focus:ring-navy/30"
        aria-label="Help"
      >
        <span className="text-xs font-semibold">?</span>
      </button>
      {show && (
        <div className="absolute bottom-full left-0 z-20 mb-1 w-56 rounded-lg border border-stone-200 bg-surface p-3 text-left text-sm text-stone-600 shadow-lg">
          {text}
        </div>
      )}
    </div>
  );
};

export default HelpTooltip;
