import { useId, useState, type ReactNode } from 'react';

interface CollapsibleSectionProps {
  id?: string;
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  badge?: string;
  children: ReactNode;
}

const CollapsibleSection = ({
  id,
  title,
  subtitle,
  defaultOpen = true,
  badge,
  children,
}: CollapsibleSectionProps) => {
  const [open, setOpen] = useState(defaultOpen);
  const autoId = useId();
  const sectionId = id ?? autoId;

  return (
    <section
      id={sectionId}
      className="rounded-2xl border border-stone-200 bg-white shadow-sm scroll-mt-24"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={`${sectionId}-panel`}
        className="flex w-full items-start justify-between gap-3 px-5 py-4 text-left hover:bg-stone-50/80 rounded-2xl transition-colors"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-stone-900">{title}</h3>
            {badge ? (
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-stone-100 text-stone-600">
                {badge}
              </span>
            ) : null}
          </div>
          {subtitle ? <p className="text-sm text-stone-500 mt-1">{subtitle}</p> : null}
        </div>
        <span className="shrink-0 text-sm font-medium text-stone-500 mt-0.5">
          {open ? 'Hide' : 'Show'}
        </span>
      </button>
      {open ? (
        <div id={`${sectionId}-panel`} className="px-5 pb-5 pt-0 border-t border-stone-100">
          <div className="pt-4">{children}</div>
        </div>
      ) : null}
    </section>
  );
};

export default CollapsibleSection;
