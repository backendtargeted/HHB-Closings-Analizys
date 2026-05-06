import { useState, useMemo } from 'react';
import type { AnalysisCompleteResponse } from '../types/analysis';
import ContactDistribution from './Charts/ContactDistribution';
import ChannelBreakdown from './Charts/ChannelBreakdown';
import FilterPanel from './Filters/FilterPanel';
import ExportMenu from './Export/ExportMenu';
import ResultsTable from './ResultsTable';
import HelpTooltip from './HelpTooltip';
import LifecycleSection from './LifecycleSection';

const STAT_HELP: Record<string, string> = {
  Total_Deals: 'Total number of closed deals in the Excel file.',
  Matched_Deals: 'Deals with at least one matching CSV record by address.',
  Unmatched_Deals: 'Deals with no matching CSV record.',
  Match_Rate: 'Share of deals that were matched to contact history.',
  Average_Contacts_per_Deal: 'Average number of contacts (CC + SMS + DM) per matched deal, before close date.',
  Median_Contacts_per_Deal: 'Median number of contacts per matched deal.',
  Max_Contacts: 'Highest number of contacts for any matched deal.',
  Min_Contacts: 'Lowest number of contacts among matched deals.',
  Total_CC_Contacts: 'Sum of all CC (mail) contacts before close dates.',
  Total_SMS_Contacts: 'Sum of all SMS contacts before close dates.',
  Total_DM_Contacts: 'Sum of all DM (direct mail) contacts before close dates.',
  Average_Days_to_Close: 'Average days from first contact to deal close (matched deals only).',
  Median_Days_to_Close: 'Median days from first contact to deal close.',
  Funnel_Acquired_Count: 'Matched deals with a List Purchased 8020 tag before close.',
  Funnel_Researched_Count: 'Matched deals with a Skip Traced tag before close.',
  Funnel_First_Contacted_Count: 'Matched deals with at least one (8020) CC/SMS/DM tag before close.',
  Funnel_Engaged_Count: 'Matched deals reaching an engaged CRM label on (SF) tags before close.',
  Funnel_Converted_Count: 'Matched deals with converted-style (SF) status before close.',
  Funnel_Acquired_Rate_Pct: 'Share of matched deals that reached list-purchased stage.',
  Engaged_To_Converted_Rate_Pct: 'Among engaged deals, share that also reached converted (SF) stage.',
  Top_Paths_Json: 'JSON blob of top ordered tag paths (for Paths tab).',
  First_Touch_Breakdown_Json: 'JSON blob of first-touch channel counts (for First touch tab).',
};

const CORE_STAT_ORDER = [
  'Total_Deals',
  'Matched_Deals',
  'Unmatched_Deals',
  'Match_Rate',
  'Average_Contacts_per_Deal',
  'Median_Contacts_per_Deal',
  'Max_Contacts',
  'Min_Contacts',
  'Total_CC_Contacts',
  'Total_SMS_Contacts',
  'Total_DM_Contacts',
  'Average_Days_to_Close',
  'Median_Days_to_Close',
] as const;

const LIFECYCLE_STAT_ORDER = [
  'Funnel_Acquired_Count',
  'Funnel_Researched_Count',
  'Funnel_First_Contacted_Count',
  'Funnel_Engaged_Count',
  'Funnel_Converted_Count',
  'Funnel_Acquired_Rate_Pct',
  'Engaged_To_Converted_Rate_Pct',
] as const;

interface AnalysisResultsProps {
  results: AnalysisCompleteResponse | undefined;
  onNewAnalysis: () => void;
}

const AnalysisResults = ({ results, onNewAnalysis }: AnalysisResultsProps) => {
  const [filters, setFilters] = useState({
    leadSource: [] as string[],
    minContacts: 0,
    maxContacts: Infinity,
    matchFound: null as boolean | null,
    search: '',
    highestStages: [] as string[],
    firstTouchChannels: [] as string[],
  });

  const filteredResults = useMemo(() => {
    if (!results) return [];

    return results.results.filter((result) => {
      if (filters.leadSource.length > 0 && !filters.leadSource.includes(result.Lead_Source)) {
        return false;
      }
      if (result.Total_Contacts < filters.minContacts || result.Total_Contacts > filters.maxContacts) {
        return false;
      }
      if (filters.matchFound !== null && result.Match_Found !== filters.matchFound) {
        return false;
      }
      if (filters.search && !result.Address.toLowerCase().includes(filters.search.toLowerCase())) {
        return false;
      }
      if (filters.highestStages.length > 0) {
        const hs = result.Highest_Stage ?? '';
        if (!filters.highestStages.includes(hs)) return false;
      }
      if (filters.firstTouchChannels.length > 0) {
        const ch = result.First_Touch_Channel ?? 'None';
        if (!filters.firstTouchChannels.includes(ch)) return false;
      }
      return true;
    });
  }, [results, filters]);

  if (!results) {
    return <div>No results available</div>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-surface rounded-lg border border-stone-200 shadow-sm p-6">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-2xl font-bold">Analysis Results</h2>
            <p className="text-gray-600 mt-1">
              {results.matched_count} of {results.total_deals} deals matched
            </p>
            {results.as_of ? (
              <p className="text-sm text-amber-900 mt-2 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 max-w-xl">
                <strong>As-of snapshot:</strong> {results.as_of} — only deals with{' '}
                <strong>Date Closed</strong> on or before this day were included.
              </p>
            ) : null}
          </div>
          <div className="flex gap-3">
            <ExportMenu jobId={results.job_id} />
            <button
              onClick={onNewAnalysis}
              className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors"
            >
              New Analysis
            </button>
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {CORE_STAT_ORDER.filter((key) => key in results.stats).map((key) => {
            const value = results.stats[key as keyof typeof results.stats];
            return (
              <div
                key={key}
                className="bg-surface rounded-lg border border-stone-200 shadow-sm p-4 border-l-4 border-l-gold"
              >
                <div className="flex items-center gap-1">
                  <p className="text-sm text-stone-600 uppercase tracking-wide">{key.replace(/_/g, ' ')}</p>
                  <HelpTooltip text={STAT_HELP[key] ?? 'Summary statistic from this analysis.'} />
                </div>
                <p className="text-2xl font-bold text-navy mt-2">
                  {typeof value === 'number' ? value.toFixed(1) : String(value ?? '—')}
                </p>
              </div>
            );
          })}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {LIFECYCLE_STAT_ORDER.filter((key) => key in results.stats && results.stats[key as keyof typeof results.stats] != null).map(
            (key) => {
              const value = results.stats[key as keyof typeof results.stats];
              return (
                <div
                  key={key}
                  className="bg-surface rounded-lg border border-amber-200/80 shadow-sm p-4 border-l-4 border-l-amber-500"
                >
                  <div className="flex items-center gap-1">
                    <p className="text-sm text-stone-600 uppercase tracking-wide">{key.replace(/_/g, ' ')}</p>
                    <HelpTooltip text={STAT_HELP[key] ?? 'Lifecycle summary from Tags.'} />
                  </div>
                  <p className="text-2xl font-bold text-navy mt-2">
                    {typeof value === 'number' ? value.toFixed(1) : String(value ?? '—')}
                  </p>
                </div>
              );
            }
          )}
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-surface rounded-lg border border-stone-200 shadow-sm p-6">
          <ContactDistribution results={filteredResults} />
        </div>
        <div className="bg-surface rounded-lg border border-stone-200 shadow-sm p-6">
          <ChannelBreakdown results={filteredResults} />
        </div>
      </div>

      <LifecycleSection stats={results.stats} />

      {/* Filters and Table */}
      <div className="bg-surface rounded-lg border border-stone-200 shadow-sm p-6">
        <FilterPanel
          results={results.results}
          filters={filters}
          onFiltersChange={setFilters}
        />
        <div className="mt-6">
          <ResultsTable results={filteredResults} />
        </div>
      </div>
    </div>
  );
};

export default AnalysisResults;
