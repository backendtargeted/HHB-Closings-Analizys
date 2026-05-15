import { useState } from 'react';

const MethodologySection = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="rounded-lg border border-stone-200 bg-surface shadow-sm">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-navy hover:bg-stone-100/50 rounded-lg transition-colors"
      >
        <span className="font-semibold">How the analysis works</span>
        <span className="text-stone-500 text-sm">{isOpen ? 'Hide' : 'Show'}</span>
      </button>
      {isOpen && (
        <div className="px-4 pb-4 pt-1 text-stone-600 text-sm space-y-3 border-t border-stone-100">
          <p>
            <strong className="text-stone-800">Data sources:</strong> Core analysis runs from the contact-history CSV using the{' '}
            <code className="bg-stone-100 px-1 rounded">Tags</code> column. Closed deals are derived from tags such as{' '}
            <code className="bg-stone-100 px-1 rounded">(CLOSED) 8020 - MM/YYYY</code> and converted-style SF status tags. Optional closings workbook upload is legacy-only (address-based match).
          </p>
          <p>
            <strong className="text-stone-800">Matching:</strong> CSV-only mode attaches each deal to the same export row (by row index). Legacy workbook mode matches by normalized address and city, with partial-street and street-number fallbacks.
          </p>
          <p>
            <strong className="text-stone-800">Contact counts:</strong> Tags matching{' '}
            <code className="bg-stone-100 px-1 rounded">(8020) CC|SMS|DM - MM/YYYY</code> are counted only when their date is{' '}
            <strong>before</strong> the deal&apos;s Date Closed. CC, SMS, and DM counts sum to Total Contacts.{' '}
            <code className="bg-stone-100 px-1 rounded">(CLOSED) 8020</code>, list purchase, skip trace, and{' '}
            <code className="bg-stone-100 px-1 rounded">(SF)</code> tags do not add to channel totals.
          </p>
          <p>
            <strong className="text-stone-800">Duplicate tags:</strong> If the same tag token appears twice on one row (e.g. after a double REISift import), identical events are deduplicated by type, date, channel, and label so counts are not doubled.
          </p>
          <p>
            <strong className="text-stone-800">Other tag families:</strong>{' '}
            <code className="bg-stone-100 px-1 rounded">List Purchased 8020</code>,{' '}
            <code className="bg-stone-100 px-1 rounded">Skip Traced</code>, and{' '}
            <code className="bg-stone-100 px-1 rounded">(SF) UPDATED|STATUS</code> drive the{' '}
            <strong>lead lifecycle</strong> funnel, paths, and SF trail. Import CRM history via Past patches, then re-export contacts so these appear in Tags.
          </p>
          <p>
            <strong className="text-stone-800">Lifecycle stages:</strong> Acquired → Researched → First contacted → Engaged (SF allow-list) → Converted. Stages use tags strictly before Date Closed. &quot;Highest stage&quot; excludes the always-on closed stage. Path strings dedupe only consecutive identical steps.
          </p>
          <p>
            <strong className="text-stone-800">Summary stats:</strong> Match rate = deals with a matched CSV row. Channel totals sum per-deal counts across matched deals. Month-granular 8020 tags use the first of the month internally; SF tags use calendar days.
          </p>
          <p className="text-xs text-stone-500 border-t border-stone-100 pt-2">
            Full methodology: repo{' '}
            <code className="bg-stone-100 px-1 rounded">docs/REPORT_METHODOLOGY.md</code> and operator{' '}
            <code className="bg-stone-100 px-1 rounded">RUNBOOK.md</code>.
          </p>
        </div>
      )}
    </div>
  );
};

export default MethodologySection;
