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
            <strong className="text-stone-800">Data sources:</strong> The Excel file contains closed deals (Address, Date Closed, Lead Source). The CSV file contains contact history with a <code className="bg-stone-100 px-1 rounded">Tags</code> column used to count contacts.
          </p>
          <p>
            <strong className="text-stone-800">Matching:</strong> Deals are matched to CSV rows by normalizing addresses (lowercase, standard abbreviations, no punctuation) and optional city. If no exact match is found, we try a partial street match, then street number plus city.
          </p>
          <p>
            <strong className="text-stone-800">Contact counts:</strong> The Tags column is parsed for patterns like <code className="bg-stone-100 px-1 rounded">(8020) CC - MM-YYYY</code>, <code className="bg-stone-100 px-1 rounded">(8020) SMS - MM-YYYY</code>, and <code className="bg-stone-100 px-1 rounded">(8020) DM - MM-YYYY</code>. Only contacts with a date <strong>before</strong> each deal&apos;s Date Closed are counted. CC_Count, SMS_Count, and DM_Count are the per-channel totals; Total_Contacts is their sum.
          </p>
          <p>
            <strong className="text-stone-800">Summary stats:</strong> Match rate is the share of deals with at least one matching CSV record. Averages and medians are over Total_Contacts for matched deals. Channel totals (Total CC/SMS/DM Contacts) are the sum of those counts across all matched deals. Average/Median Days to Close use the time from first contact to Date Closed when available.
          </p>
        </div>
      )}
    </div>
  );
};

export default MethodologySection;
