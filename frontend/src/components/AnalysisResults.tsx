import { useState, useMemo } from 'react';
import type { AnalysisCompleteResponse } from '../types/analysis';
import ContactDistribution from './Charts/ContactDistribution';
import ChannelBreakdown from './Charts/ChannelBreakdown';
import FilterPanel from './Filters/FilterPanel';
import ExportMenu from './Export/ExportMenu';
import ResultsTable from './ResultsTable';
import HelpTooltip from './HelpTooltip';

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
};

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
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {Object.entries(results.stats).slice(0, 8).map(([key, value]) => (
          <div key={key} className="bg-surface rounded-lg border border-stone-200 shadow-sm p-4 border-l-4 border-l-gold">
            <div className="flex items-center gap-1">
              <p className="text-sm text-stone-600 uppercase tracking-wide">{key.replace(/_/g, ' ')}</p>
              <HelpTooltip text={STAT_HELP[key] ?? 'Summary statistic from this analysis.'} />
            </div>
            <p className="text-2xl font-bold text-navy mt-2">
              {typeof value === 'number' ? value.toFixed(1) : value}
            </p>
          </div>
        ))}
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
