
import React from 'react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { CheckCircle } from 'lucide-react';

interface QuestionDetailProps {
  question: any;
  onClose: () => void;
}

const QuestionDetail: React.FC<QuestionDetailProps> = ({ question, onClose }) => {
  const getDifficultyColor = (difficulty: string) => {
    switch (difficulty) {
      case 'easy': return 'bg-green-100 text-green-800';
      case 'medium': return 'bg-yellow-100 text-yellow-800';
      case 'hard': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const getDifficultyLabel = (difficulty: string) => {
    switch (difficulty) {
      case 'easy': return '쉬움';
      case 'medium': return '보통';
      case 'hard': return '어려움';
      default: return difficulty;
    }
  };

  return (
    <Dialog open={!!question} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>문제 상세보기</DialogTitle>
          <DialogDescription>문제의 상세 정보를 확인하세요.</DialogDescription>
        </DialogHeader>
        
        <div className="space-y-6">
          <div>
            <h3 className="text-lg font-medium text-gray-900 mb-3">문제</h3>
            <p className="text-gray-700 leading-relaxed">{question.question}</p>
          </div>

          <div>
            <h3 className="text-lg font-medium text-gray-900 mb-3">보기</h3>
            <div className="space-y-2">
              {question.options.map((option: string, index: number) => (
                <div
                  key={index}
                  className={`p-3 rounded-lg border ${
                    index === question.correctAnswer
                      ? 'bg-green-50 border-green-200 text-green-800'
                      : 'bg-gray-50 border-gray-200'
                  }`}
                >
                  <div className="flex items-center space-x-2">
                    <span className="font-medium">{index + 1}.</span>
                    <span>{option}</span>
                    {index === question.correctAnswer && (
                      <CheckCircle className="w-4 h-4 text-green-600 ml-auto" />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {question.explanation && (
            <div>
              <h3 className="text-lg font-medium text-gray-900 mb-3">해설</h3>
              <Card>
                <CardContent className="pt-4">
                  <p className="text-gray-700 leading-relaxed">{question.explanation}</p>
                </CardContent>
              </Card>
            </div>
          )}

          <div>
            <h3 className="text-lg font-medium text-gray-900 mb-3">메타데이터</h3>
            <div className="space-y-3">
              <div>
                <span className="text-sm font-medium text-gray-600">난이도:</span>
                <Badge className={`ml-2 ${getDifficultyColor(question.difficulty)}`}>
                  {getDifficultyLabel(question.difficulty)}
                </Badge>
              </div>
              
              <div>
                <span className="text-sm font-medium text-gray-600">해시태그:</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {question.hashtags.map((tag: string, index: number) => (
                    <Badge key={index} variant="outline" className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default QuestionDetail;
