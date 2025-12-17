
import React, { useState } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { CheckCircle, XCircle, RotateCcw, Save, Image as ImageIcon } from 'lucide-react';
import { Question, useQuestionStore } from '../store/questionStore';
import { toast } from 'sonner';

interface QuestionDetailProps {
  question: Question;
  onClose: () => void;
  mode?: 'view' | 'answer-select';
}

const OPTION_SYMBOLS = ['①', '②', '③', '④'];

const QuestionDetail: React.FC<QuestionDetailProps> = ({ question, onClose, mode = 'view' }) => {
  const { updateQuestion } = useQuestionStore();
  const [selectedAnswer, setSelectedAnswer] = useState<number | null>(null);
  const [showResult, setShowResult] = useState(false);
  const [isEditingAnswer, setIsEditingAnswer] = useState(false);

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

  const handleSelectAnswer = (index: number) => {
    if (isEditingAnswer) {
      // 정답 편집 모드
      setSelectedAnswer(index);
    } else if (!showResult) {
      // 정답 확인 모드
      setSelectedAnswer(index);
      setShowResult(true);
    }
  };

  const handleReset = () => {
    setSelectedAnswer(null);
    setShowResult(false);
  };

  const handleSaveNewAnswer = () => {
    if (selectedAnswer !== null && selectedAnswer !== question.correctAnswer) {
      updateQuestion(question.id, { correctAnswer: selectedAnswer });
      toast.success(`정답이 ${OPTION_SYMBOLS[selectedAnswer]}번으로 변경되었습니다.`);
      setIsEditingAnswer(false);
      setSelectedAnswer(null);
    }
  };

  const handleStartEditAnswer = () => {
    setIsEditingAnswer(true);
    setSelectedAnswer(question.correctAnswer);
    setShowResult(false);
  };

  const handleCancelEdit = () => {
    setIsEditingAnswer(false);
    setSelectedAnswer(null);
  };

  const getOptionStyle = (index: number) => {
    if (isEditingAnswer) {
      // 정답 편집 모드
      if (selectedAnswer === index) {
        return 'bg-blue-100 border-blue-500 ring-2 ring-blue-500';
      }
      if (index === question.correctAnswer) {
        return 'bg-gray-100 border-gray-300';
      }
      return 'bg-gray-50 border-gray-200 hover:border-blue-300 cursor-pointer';
    }

    if (showResult) {
      // 결과 표시 모드
      if (index === question.correctAnswer) {
        return 'bg-green-100 border-green-500 text-green-800';
      }
      if (selectedAnswer === index && index !== question.correctAnswer) {
        return 'bg-red-100 border-red-500 text-red-800';
      }
      return 'bg-gray-50 border-gray-200';
    }

    if (selectedAnswer === index) {
      return 'bg-blue-100 border-blue-500';
    }

    return 'bg-gray-50 border-gray-200 hover:border-blue-300 cursor-pointer';
  };

  const getOptionIcon = (index: number) => {
    if (isEditingAnswer && selectedAnswer === index) {
      return <CheckCircle className="w-5 h-5 text-blue-600 ml-auto" />;
    }

    if (showResult) {
      if (index === question.correctAnswer) {
        return <CheckCircle className="w-5 h-5 text-green-600 ml-auto" />;
      }
      if (selectedAnswer === index && index !== question.correctAnswer) {
        return <XCircle className="w-5 h-5 text-red-600 ml-auto" />;
      }
    }

    return null;
  };

  const isCorrect = showResult && selectedAnswer === question.correctAnswer;

  return (
    <Dialog open={!!question} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditingAnswer ? '정답 수정' : '문제 상세보기'}
          </DialogTitle>
          <DialogDescription>
            {isEditingAnswer
              ? '새로운 정답을 선택하고 저장 버튼을 클릭하세요.'
              : '선택지를 클릭하여 정답을 확인하세요.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          {/* 문제 이미지 */}
          {question.imageData && (
            <div>
              <h3 className="text-lg font-medium text-gray-900 mb-3 flex items-center">
                <ImageIcon className="w-5 h-5 mr-2" />
                문제 이미지
              </h3>
              <Card>
                <CardContent className="p-2">
                  <img
                    src={question.imageData}
                    alt="문제 이미지"
                    className="max-h-64 object-contain mx-auto rounded"
                  />
                </CardContent>
              </Card>
            </div>
          )}

          {/* 문제 내용 */}
          <div>
            <h3 className="text-lg font-medium text-gray-900 mb-3">문제</h3>
            <p className="text-gray-700 leading-relaxed">{question.question}</p>
          </div>

          {/* 결과 표시 */}
          {showResult && !isEditingAnswer && (
            <div className={`p-4 rounded-lg ${isCorrect ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
              <div className="flex items-center gap-2">
                {isCorrect ? (
                  <>
                    <CheckCircle className="w-6 h-6 text-green-600" />
                    <span className="font-bold text-green-800">정답입니다!</span>
                  </>
                ) : (
                  <>
                    <XCircle className="w-6 h-6 text-red-600" />
                    <span className="font-bold text-red-800">
                      오답입니다. 정답은 {OPTION_SYMBOLS[question.correctAnswer]}번입니다.
                    </span>
                  </>
                )}
              </div>
            </div>
          )}

          {/* 선택지 */}
          <div>
            <h3 className="text-lg font-medium text-gray-900 mb-3">
              보기 {isEditingAnswer && <span className="text-sm text-blue-600">(클릭하여 정답 선택)</span>}
            </h3>
            <div className="space-y-2">
              {question.options.map((option: string, index: number) => (
                <div
                  key={index}
                  onClick={() => handleSelectAnswer(index)}
                  className={`p-4 rounded-lg border-2 transition-all ${getOptionStyle(index)} ${
                    !showResult || isEditingAnswer ? 'cursor-pointer' : ''
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className={`flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold ${
                      showResult && index === question.correctAnswer
                        ? 'bg-green-500 text-white'
                        : showResult && selectedAnswer === index && index !== question.correctAnswer
                          ? 'bg-red-500 text-white'
                          : isEditingAnswer && selectedAnswer === index
                            ? 'bg-blue-500 text-white'
                            : 'bg-gray-200 text-gray-700'
                    }`}>
                      {OPTION_SYMBOLS[index]}
                    </span>
                    <span className="flex-1">{option}</span>
                    {getOptionIcon(index)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 해설 */}
          {question.explanation && showResult && (
            <div>
              <h3 className="text-lg font-medium text-gray-900 mb-3">해설</h3>
              <Card>
                <CardContent className="pt-4">
                  <p className="text-gray-700 leading-relaxed">{question.explanation}</p>
                </CardContent>
              </Card>
            </div>
          )}

          {/* 메타데이터 */}
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
                <span className="text-sm font-medium text-gray-600">현재 정답:</span>
                <Badge className="ml-2 bg-green-100 text-green-800">
                  {OPTION_SYMBOLS[question.correctAnswer]}번
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

        <DialogFooter className="flex gap-2 sm:gap-2">
          {isEditingAnswer ? (
            <>
              <Button variant="outline" onClick={handleCancelEdit}>
                취소
              </Button>
              <Button
                onClick={handleSaveNewAnswer}
                disabled={selectedAnswer === null || selectedAnswer === question.correctAnswer}
                className="bg-blue-600 hover:bg-blue-700"
              >
                <Save className="w-4 h-4 mr-2" />
                정답 저장
              </Button>
            </>
          ) : (
            <>
              {showResult && (
                <Button variant="outline" onClick={handleReset}>
                  <RotateCcw className="w-4 h-4 mr-2" />
                  다시 풀기
                </Button>
              )}
              <Button variant="outline" onClick={handleStartEditAnswer}>
                정답 수정
              </Button>
              <Button onClick={onClose}>
                닫기
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default QuestionDetail;
