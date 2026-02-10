import { useMemo } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import type { AnalysisResult } from '../../types/analysis';
import HelpTooltip from '../HelpTooltip';

interface ChannelBreakdownProps {
  results: AnalysisResult[];
}

const COLORS = ['#1B3A57', '#F4B942', '#8B7355'];

const ChannelBreakdown = ({ results }: ChannelBreakdownProps) => {
  const data = useMemo(() => {
    const totals = { CC: 0, SMS: 0, DM: 0 };
    results.forEach((result) => {
      totals.CC += result.CC_Count;
      totals.SMS += result.SMS_Count;
      totals.DM += result.DM_Count;
    });
    return Object.entries(totals).map(([name, value]) => ({ name, value }));
  }, [results]);

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <h3 className="text-lg font-semibold text-stone-800">Total Contacts by Channel</h3>
        <HelpTooltip text="Total contacts by channel (CC, SMS, DM) from the Tags column, counted only before each deal's close date." />
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart margin={{ top: 10, right: 10, bottom: 10, left: 10 }}>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={52}
            outerRadius={88}
            paddingAngle={1}
            dataKey="value"
            stroke="transparent"
            label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
            labelLine={false}
          >
            {data.map((_, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="#fafaf9" strokeWidth={1} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{ borderRadius: '8px', border: '1px solid #e7e5e4' }}
            formatter={(value: number) => [value, 'Contacts']}
          />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
};

export default ChannelBreakdown;
