import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import type { AnalysisResult } from '../../types/analysis';
import HelpTooltip from '../HelpTooltip';

interface ContactDistributionProps {
  results: AnalysisResult[];
}

const ContactDistribution = ({ results }: ContactDistributionProps) => {
  const data = useMemo(() => {
    const distribution: Record<number, number> = {};
    results.forEach((result) => {
      const count = result.Total_Contacts;
      distribution[count] = (distribution[count] || 0) + 1;
    });
    return Object.entries(distribution)
      .map(([count, deals]) => ({ contacts: parseInt(count), deals }))
      .sort((a, b) => a.contacts - b.contacts);
  }, [results]);

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <h3 className="text-lg font-semibold text-stone-800">Contact Count Distribution</h3>
        <HelpTooltip text="Number of deals by total contact count. Only matched deals are included." />
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 24 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" opacity={0.8} vertical={false} />
          <XAxis
            dataKey="contacts"
            tick={{ fontSize: 12, fill: '#57534e' }}
            axisLine={{ stroke: '#d6d3d1' }}
            tickLine={{ stroke: '#d6d3d1' }}
            label={{ value: 'Number of Contacts', position: 'insideBottom', offset: -8 }}
          />
          <YAxis
            tick={{ fontSize: 12, fill: '#57534e' }}
            axisLine={{ stroke: '#d6d3d1' }}
            tickLine={{ stroke: '#d6d3d1' }}
            label={{ value: 'Number of Deals', angle: -90, position: 'insideLeft' }}
          />
          <Tooltip
            contentStyle={{ borderRadius: '8px', border: '1px solid #e7e5e4' }}
            cursor={{ fill: '#fafaf9', stroke: '#d6d3d1' }}
          />
          <Bar dataKey="deals" fill="#1B3A57" radius={[4, 4, 0, 0]} name="Deals" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default ContactDistribution;
