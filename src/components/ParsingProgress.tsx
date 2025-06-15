
import React from 'react';
import { Progress } from '@/components/ui/progress';

interface ParsingProgressProps {
  progress: number;
  uploading: boolean;
}

const ParsingProgress: React.FC<ParsingProgressProps> = ({ progress, uploading }) => {
  if (!uploading) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">파싱 진행률</span>
        <span className="text-sm text-gray-500">{progress}%</span>
      </div>
      <Progress value={progress} className="w-full" />
    </div>
  );
};

export default ParsingProgress;
