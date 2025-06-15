
import React, { useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Upload, CheckCircle } from 'lucide-react';
import { toast } from 'sonner';

interface FileUploadZoneProps {
  file: File | null;
  setFile: (file: File | null) => void;
  uploading: boolean;
}

const FileUploadZone: React.FC<FileUploadZoneProps> = ({ file, setFile, uploading }) => {
  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile && selectedFile.type === 'application/pdf') {
      setFile(selectedFile);
    } else {
      toast.error('PDF 파일만 업로드 가능합니다.');
    }
  };

  const handleDrop = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const droppedFile = event.dataTransfer.files[0];
    if (droppedFile && droppedFile.type === 'application/pdf') {
      setFile(droppedFile);
    } else {
      toast.error('PDF 파일만 업로드 가능합니다.');
    }
  }, [setFile]);

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>파일 업로드</CardTitle>
        <CardDescription>PDF 파일을 드래그하거나 클릭하여 업로드하세요.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div
            className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors duration-200 relative ${
              file ? 'border-green-300 bg-green-50' : 'border-gray-300 hover:border-blue-400'
            }`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
          >
            {file ? (
              <div className="space-y-3">
                <CheckCircle className="w-12 h-12 text-green-600 mx-auto" />
                <div>
                  <p className="text-sm font-medium text-green-800">{file.name}</p>
                  <p className="text-xs text-green-600">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <Upload className="w-12 h-12 text-gray-400 mx-auto" />
                <div>
                  <p className="text-sm font-medium text-gray-700">PDF 파일을 드래그하여 업로드</p>
                  <p className="text-xs text-gray-500">또는 클릭하여 파일 선택</p>
                </div>
              </div>
            )}
            
            <input
              type="file"
              accept=".pdf"
              onChange={handleFileChange}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              disabled={uploading}
            />
          </div>
          
          {file && (
            <Button
              onClick={() => setFile(null)}
              variant="outline"
              size="sm"
              className="w-full"
              disabled={uploading}
            >
              파일 제거
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

export default FileUploadZone;
