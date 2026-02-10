import { useState, useCallback, useEffect } from 'react';
import { useDropzone } from 'react-dropzone';

interface FileUploadProps {
  onUpload: (excelFile: File, csvFile: File) => Promise<void>;
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
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const onDropExcel = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setExcelFile(acceptedFiles[0]);
    }
  }, []);

  const onDropCsv = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setCsvFile(acceptedFiles[0]);
    }
  }, []);

  const {
    getRootProps: getExcelRootProps,
    getInputProps: getExcelInputProps,
    isDragActive: isExcelDragActive,
  } = useDropzone({
    onDrop: onDropExcel,
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
    if (excelFile && csvFile) {
      try {
        await onUpload(excelFile, csvFile);
      } catch (err) {
        console.error('Upload error:', err);
      }
    }
  };

  // Check if analysis is complete - use useEffect to avoid infinite loops
  useEffect(() => {
    if (analysisStatus === 'completed' && !isLoading) {
      const timer = setTimeout(() => {
        onComplete();
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [analysisStatus, isLoading, onComplete]);

  return (
    <div className="max-w-4xl mx-auto">
      <div className="bg-surface rounded-lg shadow-md p-6">
        <h2 className="text-2xl font-bold mb-6">Upload Files</h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          {/* Excel File Upload */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Closed Deals File (Excel)
            </label>
            <div
              {...getExcelRootProps()}
              className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                isExcelDragActive
                  ? 'border-navy bg-blue-50'
                  : 'border-gray-300 hover:border-navy'
              }`}
            >
              <input {...getExcelInputProps()} />
              {excelFile ? (
                <div className="text-green-600">
                  <p className="font-medium">✓ {excelFile.name}</p>
                  <p className="text-sm text-gray-500 mt-1">
                    {(excelFile.size / 1024).toFixed(2)} KB
                  </p>
                </div>
              ) : (
                <div>
                  <p className="text-gray-600">
                    {isExcelDragActive
                      ? 'Drop the Excel file here'
                      : 'Drag & drop Excel file or click to select'}
                  </p>
                  <p className="text-sm text-gray-500 mt-2">.xlsx, .xls</p>
                </div>
              )}
            </div>
          </div>

          {/* CSV File Upload */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Contact History File (CSV)
            </label>
            <div
              {...getCsvRootProps()}
              className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                isCsvDragActive
                  ? 'border-navy bg-blue-50'
                  : 'border-gray-300 hover:border-navy'
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

        {/* Progress Bar */}
        {isLoading && (
          <div className="mb-6">
            <div className="flex justify-between items-center mb-2">
              <span className="text-sm font-medium text-gray-700">
                {statusMessage}
              </span>
              <span className="text-sm text-gray-500">{progress}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2.5">
              <div
                className="bg-gold h-2.5 rounded-full transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Error Message */}
        {isError && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-red-800 font-medium">Error</p>
            <p className="text-red-600 text-sm mt-1">
              {error?.message || 'An error occurred during analysis'}
            </p>
          </div>
        )}

        {/* Submit Button */}
        <button
          onClick={handleSubmit}
          disabled={!excelFile || !csvFile || isLoading}
          className={`w-full py-3 px-6 rounded-lg font-medium transition-colors ${
            !excelFile || !csvFile || isLoading
              ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
              : 'bg-success text-white hover:bg-green-600'
          }`}
        >
          {isLoading ? 'Analyzing...' : 'Run Analysis'}
        </button>
      </div>
    </div>
  );
};

export default FileUpload;
