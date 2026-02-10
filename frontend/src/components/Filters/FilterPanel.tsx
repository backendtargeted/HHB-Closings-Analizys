import { useMemo } from 'react';
import type { AnalysisResult } from '../../types/analysis';

interface FilterPanelProps {
  results: AnalysisResult[];
  filters: {
    leadSource: string[];
    minContacts: number;
    maxContacts: number;
    matchFound: boolean | null;
    search: string;
  };
  onFiltersChange: (filters: FilterPanelProps['filters']) => void;
}

const FilterPanel = ({ results, filters, onFiltersChange }: FilterPanelProps) => {
  const uniqueLeadSources = useMemo(() => {
    const sources = new Set(results.map((r) => r.Lead_Source));
    return Array.from(sources).sort();
  }, [results]);

  const maxContacts = useMemo(() => {
    return Math.max(...results.map((r) => r.Total_Contacts), 0);
  }, [results]);

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Filters</h3>
      
      {/* Search */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Search Address
        </label>
        <input
          type="text"
          value={filters.search}
          onChange={(e) =>
            onFiltersChange({ ...filters, search: e.target.value })
          }
          placeholder="Search by address..."
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
        />
      </div>

      {/* Lead Source Filter */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Lead Source
        </label>
        <div className="flex flex-wrap gap-2">
          {uniqueLeadSources.map((source) => (
            <button
              key={source}
              onClick={() => {
                const newSources = filters.leadSource.includes(source)
                  ? filters.leadSource.filter((s) => s !== source)
                  : [...filters.leadSource, source];
                onFiltersChange({ ...filters, leadSource: newSources });
              }}
              className={`px-3 py-1 rounded-full text-sm transition-colors ${
                filters.leadSource.includes(source)
                  ? 'bg-navy text-white'
                  : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
              }`}
            >
              {source}
            </button>
          ))}
        </div>
      </div>

      {/* Contact Count Range */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Contact Count Range
        </label>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1">
            <label htmlFor="min-contacts" className="text-sm text-gray-600">Min</label>
            <input
              id="min-contacts"
              type="number"
              min={0}
              max={maxContacts}
              value={filters.minContacts}
              onChange={(e) => {
                const v = e.target.value === '' ? 0 : parseInt(e.target.value, 10);
                onFiltersChange({ ...filters, minContacts: isNaN(v) ? 0 : Math.max(0, v) });
              }}
              className="w-24 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
            />
          </div>
          <span className="text-gray-500">to</span>
          <div className="flex items-center gap-1">
            <label htmlFor="max-contacts" className="text-sm text-gray-600">Max</label>
            <input
              id="max-contacts"
              type="number"
              min={0}
              max={maxContacts}
              placeholder="No limit"
              value={filters.maxContacts === Infinity ? '' : filters.maxContacts}
              onChange={(e) => {
                const raw = e.target.value.trim();
                const v = raw === '' ? Infinity : parseInt(raw, 10);
                onFiltersChange({
                  ...filters,
                  maxContacts: raw === '' ? Infinity : (isNaN(v) ? maxContacts : Math.min(maxContacts, Math.max(0, v))),
                });
              }}
              className="w-24 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
            />
          </div>
          <span className="text-xs text-gray-500">Leave max empty for no limit</span>
        </div>
      </div>

      {/* Match Status */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Match Status
        </label>
        <div className="flex gap-2">
          {[
            { label: 'All', value: null },
            { label: 'Matched', value: true },
            { label: 'No Match', value: false },
          ].map((option) => (
            <button
              key={option.label}
              onClick={() =>
                onFiltersChange({ ...filters, matchFound: option.value })
              }
              className={`px-4 py-2 rounded-lg text-sm transition-colors ${
                filters.matchFound === option.value
                  ? 'bg-navy text-white'
                  : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default FilterPanel;
