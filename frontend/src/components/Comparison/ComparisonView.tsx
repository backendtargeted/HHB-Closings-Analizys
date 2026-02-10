import { useState } from 'react';
import { compareAnalyses } from '../../services/api';

const ComparisonView = () => {
  const [selectedJobIds] = useState<string[]>([]);
  const [comparisonData, setComparisonData] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleCompare = async () => {
    if (selectedJobIds.length < 2) {
      alert('Please select at least 2 analyses to compare');
      return;
    }

    setIsLoading(true);
    try {
      const result = await compareAnalyses(selectedJobIds);
      setComparisonData(result);
    } catch (error) {
      console.error('Comparison error:', error);
      alert('Failed to compare analyses');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="bg-surface rounded-lg shadow-md p-6">
      <h2 className="text-2xl font-bold mb-6">Compare Analyses</h2>
      
      <div className="space-y-4">
        <p className="text-gray-600">
          Select multiple analysis runs to compare their results side-by-side.
        </p>
        
        <div className="flex gap-4">
          <button
            onClick={handleCompare}
            disabled={selectedJobIds.length < 2 || isLoading}
            className="px-4 py-2 bg-navy text-white rounded-lg hover:bg-opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? 'Comparing...' : 'Compare Selected'}
          </button>
        </div>

        {comparisonData && (
          <div className="mt-6">
            <h3 className="text-lg font-semibold mb-4">Comparison Results</h3>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-navy">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-white uppercase">Metric</th>
                    {Object.keys(comparisonData.comparisons).map((jobId) => (
                      <th key={jobId} className="px-6 py-3 text-left text-xs font-medium text-white uppercase">
                        {jobId.substring(0, 8)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="bg-surface divide-y divide-gray-200">
                  {comparisonData.comparisons &&
                    Object.entries(
                      comparisonData.comparisons[Object.keys(comparisonData.comparisons)[0]]?.stats || {}
                    ).map(([metric, _]) => (
                      <tr key={metric} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          {metric.replace(/_/g, ' ')}
                        </td>
                        {Object.values(comparisonData.comparisons).map((comp: any, idx) => (
                          <td key={idx} className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {comp.stats[metric] !== undefined
                              ? typeof comp.stats[metric] === 'number'
                                ? comp.stats[metric].toFixed(1)
                                : comp.stats[metric]
                              : '-'}
                          </td>
                        ))}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ComparisonView;
