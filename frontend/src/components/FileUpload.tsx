import { useState, useCallback, useEffect } from 'react';
import { useDropzone } from 'react-dropzone';

interface FileUploadProps {
  onUpload: (closingsFile: File | null, csvFile: File, asOf?: string | null) => Promise<void>;
  isLoading: boolean;
  progress: number;
  statusMessage: string;
  isError: boolean;
  error: Error | null;
  onComplete: () => void;
  analysisStatus?: string;
}

const FileUpload = ({
  onUpload,
  isLoading,
  progress,
  statusMessage,
  isError,
  error,
  onComplete,
  analysisStatus,
}: FileUploadProps) => {
  const [closingsFile, setClosingsFile] = useState<File | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const onDropClosings = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setClosingsFile(acceptedFiles[0]);
    }
  }, []);

  const onDropCsv = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setCsvFile(acceptedFiles[0]);
    }
  }, []);

  const {
    getRootProps: getClosingsRootProps,
    getInputProps: getClosingsInputProps,
    isDragActive: isClosingsDragActive,
  } = useDropzone({
    onDrop: onDropClosings,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
    },
    multiple: false,
  });

  const {
    getRootProps: getCsvRootProps,
    getInputProps: getCsvInputProps,
    isDragActive: isCsvDragActive,
  } = useDropzone({
    onDrop: onDropCsv,
    accept: {
      'text/csv': ['.csv'],
    },
    multiple: false,
  });

  const handleSubmit = async () => {
    if (csvFile) {
      try {
        await onUpload(closingsFile, csvFile, null);
      } catch (err) {
        console.error('Upload error:', err);
      }
    }
  };

  useEffect(() => {
    if (analysisStatus === 'completed' && !isLoading) {
      const timer = setTimeout(() => {
        onComplete();
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [analysisStatus, isLoading, onComplete]);

  return (
    <div className="w-full">
      <div className="rounded-2xl border border-stone-200/90 bg-white ring-1 ring-stone-900/5 shadow-sm p-6 sm:p-8">
        <div className="mb-6">
          <h2 className="text-2xl font-bold tracking-tight text-navy">Regular update</h2>
          <p className="text-stone-600 text-sm mt-1.5 leading-relaxed">
            Upload the latest REISift (or equivalent) contact-history export. Closed deals are derived from CSV tags
            by default; optional closings workbook upload is legacy-only.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div>
            <label className="block text-sm font-semibold text-stone-700 mb-2">
              Closings workbook (optional/legacy)
            </label>
            <div
              {...getClosingsRootProps()}
              className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
                isClosingsDragActive
                  ? 'border-navy bg-navy/5'
                  : 'border-stone-200 hover:border-navy/60 bg-stone-50/50'
              }`}
            >
              <input {...getClosingsInputProps()} />
              {closingsFile ? (
                <div className="text-green-600">
                  <p className="font-medium">✓ {closingsFile.name}</p>
                  <p className="text-sm text-gray-500 mt-1">
                    {(closingsFile.size / 1024).toFixed(2)} KB
                  </p>
                </div>
              ) : (
                <div>
                  <p className="text-gray-600">
                    {isClosingsDragActive
                      ? 'Drop optional closings workbook here'
                      : 'Optional: drag & drop closings workbook or click to select'}
                  </p>
                  <p className="text-sm text-gray-500 mt-2">.xlsx, .xls</p>
                </div>
              )}
            </div>
          </div>

          <div>
            <label className="block text-sm font-semibold text-stone-700 mb-2">
              Contact history (CSV)
            </label>
            <div
              {...getCsvRootProps()}
              className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
                isCsvDragActive
                  ? 'border-navy bg-navy/5'
                  : 'border-stone-200 hover:border-navy/60 bg-stone-50/50'
              }`}
            >
              <input {...getCsvInputProps()} />
              {csvFile ? (
                <div className="text-green-600">
                  <p className="font-medium">✓ {csvFile.name}</p>
                  <p className="text-sm text-gray-500 mt-1">
                    {(csvFile.size / 1024).toFixed(2)} KB
                  </p>
                </div>
              ) : (
                <div>
                  <p className="text-gray-600">
                    {isCsvDragActive
                      ? 'Drop the CSV file here'
                      : 'Drag & drop CSV file or click to select'}
                  </p>
                  <p className="text-sm text-gray-500 mt-2">.csv</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {isLoading && (
          <div className="mb-6">
            <div className="flex justify-between items-center mb-2">
              <span className="text-sm font-medium text-stone-700">{statusMessage}</span>
              <span className="text-sm font-medium tabular-nums text-stone-500">{progress}%</span>
            </div>
            <div className="w-full h-2.5 rounded-full bg-stone-200 overflow-hidden">
              <div
                className="bg-gradient-to-r from-gold to-amber-500 h-full rounded-full transition-all duration-300 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {isError && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200/90 rounded-xl">
            <p className="text-red-900 font-semibold text-sm">Something went wrong</p>
            <p className="text-red-700/90 text-sm mt-1 leading-relaxed">
              {error?.message || 'An error occurred during analysis'}
            </p>
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!csvFile || isLoading}
          className={`w-full py-3.5 px-6 rounded-xl font-semibold text-sm sm:text-base transition-all ${
            !csvFile || isLoading
              ? 'bg-stone-200 text-stone-500 cursor-not-allowed'
              : 'bg-navy text-white hover:bg-navy/90 shadow-md hover:shadow-lg'
          }`}
        >
          {isLoading ? 'Analyzing…' : 'Run analysis'}
        </button>
      </div>
    </div>
  );
};

export default FileUpload;
