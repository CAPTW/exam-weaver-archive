import React, { useState, useEffect, useRef } from 'react';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent } from '@/components/ui/card';
import { Plus, X, Image as ImageIcon, Upload, CheckCircle2 } from 'lucide-react';
import { Question, useQuestionStore } from '../store/questionStore';
import { toast } from 'sonner';

interface QuestionEditorProps {
  question?: Question | null;
  isOpen: boolean;
  onClose: () => void;
  mode: 'create' | 'edit';
}

const OPTION_SYMBOLS = ['①', '②', '③', '④'];

const QuestionEditor: React.FC<QuestionEditorProps> = ({ question, isOpen, onClose, mode }) => {
  const { addQuestion, updateQuestion } = useQuestionStore();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [formData, setFormData] = useState({
    question: '',
    options: ['', '', '', ''],
    correctAnswer: 0,
    hashtags: [] as string[],
    difficulty: 'medium' as Question['difficulty'],
    explanation: '',
    imageData: '' as string | undefined
  });

  const [newHashtag, setNewHashtag] = useState('');
  const [selectedAnswer, setSelectedAnswer] = useState<number | null>(null);

  useEffect(() => {
    if (mode === 'edit' && question) {
      setFormData({
        question: question.question,
        options: [...question.options],
        correctAnswer: question.correctAnswer,
        hashtags: [...question.hashtags],
        difficulty: question.difficulty,
        explanation: question.explanation || '',
        imageData: question.imageData
      });
      setSelectedAnswer(question.correctAnswer);
    } else {
      setFormData({
        question: '',
        options: ['', '', '', ''],
        correctAnswer: 0,
        hashtags: [],
        difficulty: 'medium',
        explanation: '',
        imageData: undefined
      });
      setSelectedAnswer(null);
    }
  }, [question, mode, isOpen]);

  const handleOptionChange = (index: number, value: string) => {
    const newOptions = [...formData.options];
    newOptions[index] = value;
    setFormData({ ...formData, options: newOptions });
  };

  const handleSelectAnswer = (index: number) => {
    setSelectedAnswer(index);
    setFormData({ ...formData, correctAnswer: index });
  };

  const handleAddHashtag = () => {
    const tag = newHashtag.trim();
    if (tag && !formData.hashtags.includes(tag)) {
      setFormData({ ...formData, hashtags: [...formData.hashtags, tag] });
      setNewHashtag('');
    }
  };

  const handleRemoveHashtag = (tag: string) => {
    setFormData({
      ...formData,
      hashtags: formData.hashtags.filter(t => t !== tag)
    });
  };

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.size > 5 * 1024 * 1024) {
        toast.error('이미지 크기는 5MB 이하여야 합니다.');
        return;
      }

      const reader = new FileReader();
      reader.onload = (event) => {
        const base64 = event.target?.result as string;
        setFormData({ ...formData, imageData: base64 });
        toast.success('이미지가 추가되었습니다.');
      };
      reader.readAsDataURL(file);
    }
  };

  const handleRemoveImage = () => {
    setFormData({ ...formData, imageData: undefined });
  };

  const handleSubmit = () => {
    if (!formData.question.trim()) {
      toast.error('문제 내용을 입력해주세요.');
      return;
    }

    const filledOptions = formData.options.filter(opt => opt.trim());
    if (filledOptions.length < 4) {
      toast.error('4개의 선택지를 모두 입력해주세요.');
      return;
    }

    if (selectedAnswer === null) {
      toast.error('정답을 선택해주세요.');
      return;
    }

    const questionData = {
      question: formData.question.trim(),
      options: formData.options.map(opt => opt.trim()),
      correctAnswer: selectedAnswer,
      hashtags: formData.hashtags,
      difficulty: formData.difficulty,
      explanation: formData.explanation.trim() || undefined,
      imageData: formData.imageData
    };

    if (mode === 'edit' && question) {
      updateQuestion(question.id, questionData);
      toast.success('문제가 수정되었습니다.');
    } else {
      addQuestion(questionData);
      toast.success('새 문제가 추가되었습니다.');
    }

    onClose();
  };

  const getOptionStyle = (index: number) => {
    if (selectedAnswer === index) {
      return 'border-green-500 bg-green-50 ring-2 ring-green-500';
    }
    return 'border-gray-200 hover:border-blue-300';
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {mode === 'edit' ? '문제 수정' : '새 문제 추가'}
          </DialogTitle>
          <DialogDescription>
            {mode === 'edit'
              ? '문제 정보를 수정하세요. 정답을 클릭하여 선택할 수 있습니다.'
              : '새로운 문제를 입력하세요. 선택지를 클릭하면 정답으로 설정됩니다.'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* 문제 내용 */}
          <div className="space-y-2">
            <Label htmlFor="question">문제 내용 *</Label>
            <Textarea
              id="question"
              value={formData.question}
              onChange={(e) => setFormData({ ...formData, question: e.target.value })}
              placeholder="문제 내용을 입력하세요..."
              className="min-h-[100px]"
            />
          </div>

          {/* 이미지 업로드 */}
          <div className="space-y-2">
            <Label>문제 이미지 (선택)</Label>
            <div className="flex items-center gap-4">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleImageUpload}
                className="hidden"
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload className="w-4 h-4 mr-2" />
                이미지 업로드
              </Button>
              {formData.imageData && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleRemoveImage}
                  className="text-red-600"
                >
                  <X className="w-4 h-4 mr-2" />
                  이미지 제거
                </Button>
              )}
            </div>
            {formData.imageData && (
              <Card className="mt-2">
                <CardContent className="p-2">
                  <img
                    src={formData.imageData}
                    alt="문제 이미지"
                    className="max-h-48 object-contain mx-auto rounded"
                  />
                </CardContent>
              </Card>
            )}
          </div>

          {/* 선택지 - 클릭하면 정답으로 선택 */}
          <div className="space-y-3">
            <Label>선택지 * (클릭하여 정답 선택)</Label>
            <div className="grid gap-3">
              {formData.options.map((option, index) => (
                <div
                  key={index}
                  className={`flex items-center gap-3 p-3 rounded-lg border-2 cursor-pointer transition-all ${getOptionStyle(index)}`}
                  onClick={() => handleSelectAnswer(index)}
                >
                  <div className={`flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold ${
                    selectedAnswer === index
                      ? 'bg-green-500 text-white'
                      : 'bg-gray-100 text-gray-600'
                  }`}>
                    {OPTION_SYMBOLS[index]}
                  </div>
                  <Input
                    value={option}
                    onChange={(e) => {
                      e.stopPropagation();
                      handleOptionChange(index, e.target.value);
                    }}
                    onClick={(e) => e.stopPropagation()}
                    placeholder={`선택지 ${index + 1}을 입력하세요`}
                    className="flex-1 border-0 focus-visible:ring-0 bg-transparent"
                  />
                  {selectedAnswer === index && (
                    <CheckCircle2 className="w-6 h-6 text-green-500" />
                  )}
                </div>
              ))}
            </div>
            {selectedAnswer !== null && (
              <p className="text-sm text-green-600 font-medium">
                정답: {OPTION_SYMBOLS[selectedAnswer]} 번
              </p>
            )}
          </div>

          {/* 난이도 */}
          <div className="space-y-2">
            <Label>난이도</Label>
            <Select
              value={formData.difficulty}
              onValueChange={(value: Question['difficulty']) =>
                setFormData({ ...formData, difficulty: value })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="easy">쉬움</SelectItem>
                <SelectItem value="medium">보통</SelectItem>
                <SelectItem value="hard">어려움</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* 해시태그 */}
          <div className="space-y-2">
            <Label>해시태그</Label>
            <div className="flex gap-2">
              <Input
                value={newHashtag}
                onChange={(e) => setNewHashtag(e.target.value)}
                placeholder="해시태그 입력"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddHashtag();
                  }
                }}
              />
              <Button type="button" variant="outline" onClick={handleAddHashtag}>
                <Plus className="w-4 h-4" />
              </Button>
            </div>
            {formData.hashtags.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {formData.hashtags.map((tag, index) => (
                  <Badge
                    key={index}
                    variant="secondary"
                    className="cursor-pointer hover:bg-red-100"
                    onClick={() => handleRemoveHashtag(tag)}
                  >
                    {tag}
                    <X className="w-3 h-3 ml-1" />
                  </Badge>
                ))}
              </div>
            )}
          </div>

          {/* 해설 */}
          <div className="space-y-2">
            <Label htmlFor="explanation">해설 (선택)</Label>
            <Textarea
              id="explanation"
              value={formData.explanation}
              onChange={(e) => setFormData({ ...formData, explanation: e.target.value })}
              placeholder="해설을 입력하세요..."
              className="min-h-[80px]"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            취소
          </Button>
          <Button onClick={handleSubmit}>
            {mode === 'edit' ? '수정 완료' : '문제 추가'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default QuestionEditor;
