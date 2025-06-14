
import React, { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Download, FileText, Settings, Shuffle } from 'lucide-react';
import { useQuestionStore } from '../store/questionStore';
import { toast } from 'sonner';

const ExamGenerator = () => {
  const { questions } = useQuestionStore();
  const [examTitle, setExamTitle] = useState('');
  const [questionCount, setQuestionCount] = useState(20);
  const [selectedHashtags, setSelectedHashtags] = useState<string[]>([]);
  const [selectedQuestions, setSelectedQuestions] = useState<any[]>([]);
  const [includeAnswerSheet, setIncludeAnswerSheet] = useState(true);
  const [randomizeOrder, setRandomizeOrder] = useState(true);

  const allHashtags = Array.from(new Set(questions.flatMap(q => q.hashtags)));

  const handleHashtagToggle = (hashtag: string) => {
    setSelectedHashtags(prev => 
      prev.includes(hashtag) 
        ? prev.filter(h => h !== hashtag)
        : [...prev, hashtag]
    );
  };

  const generateExam = () => {
    let filteredQuestions = questions;
    
    if (selectedHashtags.length > 0) {
      filteredQuestions = questions.filter(q => 
        q.hashtags.some(tag => selectedHashtags.includes(tag))
      );
    }

    if (filteredQuestions.length < questionCount) {
      toast.error(`선택된 조건에 맞는 문제가 ${filteredQuestions.length}개밖에 없습니다.`);
      return;
    }

    let examQuestions = [...filteredQuestions];
    
    if (randomizeOrder) {
      examQuestions = examQuestions.sort(() => Math.random() - 0.5);
    }
    
    examQuestions = examQuestions.slice(0, questionCount);
    setSelectedQuestions(examQuestions);
    
    toast.success(`${questionCount}개 문제로 시험지가 생성되었습니다!`);
  };

  const downloadExam = () => {
    if (selectedQuestions.length === 0) {
      toast.error('먼저 시험지를 생성해주세요.');
      return;
    }

    // 시험지 HTML 생성
    const examHTML = generateExamHTML();
    const blob = new Blob([examHTML], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    
    const link = document.createElement('a');
    link.href = url;
    link.download = `${examTitle || '시험지'}.html`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    toast.success('시험지가 다운로드되었습니다!');
  };

  const generateExamHTML = () => {
    return `
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${examTitle || '시험지'}</title>
    <style>
        body { font-family: 'Malgun Gothic', sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .header { text-align: center; border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }
        .question { margin-bottom: 30px; page-break-inside: avoid; }
        .question-number { font-weight: bold; font-size: 1.1em; margin-bottom: 10px; }
        .options { margin-left: 20px; }
        .option { margin: 8px 0; }
        .answer-sheet { page-break-before: always; }
        @media print { .no-print { display: none; } }
    </style>
</head>
<body>
    <div class="header">
        <h1>${examTitle || '시험지'}</h1>
        <p>총 ${selectedQuestions.length}문항 (각 문항당 배점: ${100 / selectedQuestions.length}점)</p>
        <p>시험 시간: 60분</p>
    </div>
    
    ${selectedQuestions.map((question, index) => `
        <div class="question">
            <div class="question-number">${index + 1}. ${question.question}</div>
            <div class="options">
                ${question.options.map((option, optionIndex) => `
                    <div class="option">① ${option}</div>
                `.replace('①', ['①', '②', '③', '④'][optionIndex])).join('')}
            </div>
        </div>
    `).join('')}
    
    ${includeAnswerSheet ? `
        <div class="answer-sheet">
            <h2>정답표</h2>
            <table border="1" style="width: 100%; border-collapse: collapse;">
                <tr>
                    <th style="padding: 10px;">문항</th>
                    <th style="padding: 10px;">정답</th>
                    <th style="padding: 10px;">해설</th>
                </tr>
                ${selectedQuestions.map((question, index) => `
                    <tr>
                        <td style="padding: 10px; text-align: center;">${index + 1}</td>
                        <td style="padding: 10px; text-align: center;">${['①', '②', '③', '④'][question.correctAnswer]}</td>
                        <td style="padding: 10px;">${question.explanation || ''}</td>
                    </tr>
                `).join('')}
            </table>
        </div>
    ` : ''}
</body>
</html>`;
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">시험지 생성</h2>
        <p className="text-gray-600">원하는 조건에 맞는 맞춤형 시험지를 생성하고 다운로드하세요.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <Settings className="w-5 h-5" />
              <span>시험지 설정</span>
            </CardTitle>
            <CardDescription>시험지의 기본 정보를 설정하세요.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label htmlFor="examTitle">시험지 제목</Label>
              <Input
                id="examTitle"
                placeholder="예: 정보처리기사 모의고사"
                value={examTitle}
                onChange={(e) => setExamTitle(e.target.value)}
              />
            </div>
            
            <div>
              <Label htmlFor="questionCount">문제 수</Label>
              <Input
                id="questionCount"
                type="number"
                min="1"
                max={questions.length}
                value={questionCount}
                onChange={(e) => setQuestionCount(Number(e.target.value))}
              />
              <p className="text-xs text-gray-500 mt-1">
                최대 {questions.length}문제까지 선택 가능
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="includeAnswerSheet"
                  checked={includeAnswerSheet}
                  onCheckedChange={setIncludeAnswerSheet}
                />
                <Label htmlFor="includeAnswerSheet">정답표 포함</Label>
              </div>
              
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="randomizeOrder"
                  checked={randomizeOrder}
                  onCheckedChange={setRandomizeOrder}
                />
                <Label htmlFor="randomizeOrder">문제 순서 랜덤화</Label>
              </div>
            </div>

            <Button onClick={generateExam} className="w-full">
              <Shuffle className="w-4 h-4 mr-2" />
              시험지 생성
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>해시태그 필터</CardTitle>
            <CardDescription>포함할 해시태그를 선택하세요. (선택 안함 = 전체)</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2 max-h-60 overflow-y-auto">
              {allHashtags.map(hashtag => (
                <Badge
                  key={hashtag}
                  variant={selectedHashtags.includes(hashtag) ? "default" : "outline"}
                  className="cursor-pointer hover:bg-blue-100"
                  onClick={() => handleHashtagToggle(hashtag)}
                >
                  {hashtag}
                </Badge>
              ))}
            </div>
            {selectedHashtags.length > 0 && (
              <div className="mt-4">
                <p className="text-sm text-gray-600 mb-2">선택된 해시태그:</p>
                <div className="flex flex-wrap gap-1">
                  {selectedHashtags.map(tag => (
                    <Badge key={tag} className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {selectedQuestions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <FileText className="w-5 h-5" />
              <span>생성된 시험지 미리보기</span>
            </CardTitle>
            <CardDescription>
              {selectedQuestions.length}문제가 선택되었습니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4 max-h-60 overflow-y-auto">
              {selectedQuestions.slice(0, 3).map((question, index) => (
                <div key={question.id} className="border-l-4 border-blue-500 pl-4">
                  <p className="font-medium text-sm">
                    {index + 1}. {question.question}
                  </p>
                  <div className="text-xs text-gray-600 mt-1">
                    {question.hashtags.slice(0, 3).join(', ')}
                  </div>
                </div>
              ))}
              {selectedQuestions.length > 3 && (
                <p className="text-sm text-gray-500 text-center">
                  ... 외 {selectedQuestions.length - 3}문제
                </p>
              )}
            </div>
            
            <div className="flex space-x-2 mt-4">
              <Button onClick={downloadExam} className="flex-1">
                <Download className="w-4 h-4 mr-2" />
                HTML 다운로드
              </Button>
              <Button variant="outline" onClick={generateExam}>
                <Shuffle className="w-4 h-4 mr-2" />
                재생성
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default ExamGenerator;
