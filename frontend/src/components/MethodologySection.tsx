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
            <code className="bg-stone-100 px-1 rounded">Tags</code> column. <strong>Date Closed</strong> requires a{' '}
            <code className="bg-stone-100 px-1 rounded">(CLOSED) 8020 - MM/YYYY</code> tag and/or a closings workbook row (earliest wins). SF{' '}
            <code className="bg-stone-100 px-1 rounded">converted</code> / under contract sets <strong>Date Under Contract</strong> only — contract signed is not the same as closed. Optional closings workbook upload is legacy-only (address-based match).
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
            <strong className="text-stone-800">Lifecycle stages:</strong> Acquired → Researched → First contacted → Engaged (SF allow-list) → Converted (SF &quot;converted&quot; = under contract / contract signed). Stages use tags strictly before Date Closed. Settlement closed is a separate milestone from contract signed. Path strings dedupe only consecutive identical steps.
          </p>
          <p>
            <strong className="text-stone-800">Summary stats:</strong> Match rate = deals with a matched CSV row. Channel totals sum per-deal counts across matched deals. Month-granular 8020 tags use the first of the month internally; SF tags use calendar days.
          </p>
          <p>
            <strong className="text-stone-800">Salesforce Create Date (all gates):</strong> When
            marketing called or texted that LIP / 8020 / CourtAlerts list and pushed the lead into
            the CRM. Clock, not source. First list is the credit. Campaign / Lead Source is extra.
            Never compare Create Date to list month to relabel credit as already in Salesforce,
            After LIP, or After 8020. Create Date may still filter a report window (Gates 2–4) or
            compute lag (Gates 3, 5, 6, and 7).
          </p>
          <p>
            <strong className="text-stone-800">Gate 5 probate:</strong> Universe is REISift rows tagged{' '}
            <code className="bg-stone-100 px-1 rounded">Probates NY Nassau|Queens|Suffolk M-YYYY</code>
            {' '}(38 locked tags; Nassau from Apr 2025, including Nassau/Queens 3-2026 with no drop).
            8020 is a competing list provider on the same row (
            <code className="bg-stone-100 px-1 rounded">List Purchased 8020</code>
            ). First list is the QL credit when the row matches a Qualified Lead whose Create Date is
            on or after that first-list month. Earlier CRM rows are not conversions. Campaign is
            extra. Primary/Secondary Reason for Selling comes only from the Transactions pipeline
            after address match. Lag buckets (Same month / 1–3 / 4–6 / 7–12 / 13+) are split by
            first-list source: LIP Probates, 8020, and Same month.
          </p>
          <p>
            <strong className="text-stone-800">Gate 6 Court Alerts:</strong> Universe is the Court
            Alerts CSV (parseable address + created_on). REISift supplies competing{' '}
            <code className="bg-stone-100 px-1 rounded">List Purchased 8020</code> tags by address.
            First list is the QL credit when Create Date is on or after that first-list month.
            Lag buckets split by Court Alerts / 8020 / Same month. Reasons from Transactions only.
          </p>
          <p>
            <strong className="text-stone-800">Gate 7 Investor &amp; In-List Sold:</strong> Universe is
            CleanREISift{' '}
            <code className="bg-stone-100 px-1 rounded">sold_properties_full.csv</code> with{' '}
            <code className="bg-stone-100 px-1 rounded">investor</code> and{' '}
            <code className="bg-stone-100 px-1 rounded">in_my_records</code> flags. Primary KPI:{' '}
            <em>lost to investor</em> = in-list AND investor AND not Closed (rate vs in-list), with
            furthest-stage breakdown. Canonical pipeline: Prospect (8020) → Marketed → Lead (Podio/SF)
            → Qualified Lead → Opportunity → Under contract → Closed. Grain = unique property × sold month.
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
