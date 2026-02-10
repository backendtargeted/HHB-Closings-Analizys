import { useState, useEffect, useRef } from 'react';
import { exportResults } from '../../services/api';

interface ExportMenuProps {
  jobId: string;
}

const ExportMenu = ({ jobId }: ExportMenuProps) => {
  const [isExporting, setIsExporting] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  const handleExport = async (format: 'excel' | 'csv' | 'json') => {
    setIsExporting(true);
    try {
      const blob = await exportResults(jobId, format);
      
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `analysis_${jobId}.${format === 'json' ? 'json' : format}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error('Export error:', error);
      alert('Failed to export results');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="px-4 py-2 bg-navy text-white rounded-lg hover:bg-opacity-90 transition-colors"
      >
        Export
      </button>
      {isOpen && (
        <div className="absolute right-0 mt-2 w-48 bg-surface rounded-lg shadow-lg py-2 z-10 border border-gray-200">
          <button
            onClick={() => {
              handleExport('excel');
              setIsOpen(false);
            }}
            disabled={isExporting}
            className="w-full text-left px-4 py-2 hover:bg-stone-100 transition-colors disabled:opacity-50"
          >
            {isExporting ? 'Exporting...' : 'Export as Excel'}
          </button>
          <button
            onClick={() => {
              handleExport('csv');
              setIsOpen(false);
            }}
            disabled={isExporting}
            className="w-full text-left px-4 py-2 hover:bg-stone-100 transition-colors disabled:opacity-50"
          >
            {isExporting ? 'Exporting...' : 'Export as CSV'}
          </button>
          <button
            onClick={() => {
              handleExport('json');
              setIsOpen(false);
            }}
            disabled={isExporting}
            className="w-full text-left px-4 py-2 hover:bg-stone-100 transition-colors disabled:opacity-50"
          >
            {isExporting ? 'Exporting...' : 'Export as JSON'}
          </button>
        </div>
      )}
    </div>
  );
};

export default ExportMenu;
