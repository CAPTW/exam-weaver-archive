
import React, { useState, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Upload, FileText, CheckCircle, AlertCircle } from 'lucide-react';
import { useQuestionStore, Question } from '../store/questionStore';
import { toast } from 'sonner';

const PDFUploader = () => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [subject, setSubject] = useState('');
  const [examSession, setExamSession] = useState('');
  const { addQuestions } = useQuestionStore();

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
  }, []);

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
  }, []);

  const simulateParsing = async () => {
    setUploading(true);
    setProgress(0);

    // 시뮬레이션된 파싱 과정
    const steps = [
      { message: 'PDF 파일 읽는 중...', progress: 20 },
      { message: '문제 텍스트 추출 중...', progress: 40 },
      { message: '보기 및 이미지 인식 중...', progress: 60 },
      { message: '해시태그 생성 중...', progress: 80 },
      { message: '데이터베이스 저장 중...', progress: 100 }
    ];

    for (const step of steps) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      setProgress(step.progress);
      toast.info(step.message);
    }

    // 샘플 문제 데이터 생성 (타입 안전하게)
    const sampleQuestions: Question[] = [
      {
        id: Math.random().toString(36).substr(2, 9),
        question: 'SQL에서 테이블의 구조를 변경하는 명령어는?',
        options: ['SELECT', 'ALTER', 'INSERT', 'DELETE'],
        correctAnswer: 1,
        hashtags: [subject || '정보처리기사', examSession || '2024년 1회', 'SQL', '데이터베이스'],
        difficulty: 'medium' as const,
        explanation: 'ALTER 명령어는 테이블의 구조를 변경할 때 사용됩니다.'
      },
      {
        id: Math.random().toString(36).substr(2, 9),
        question: '객체지향 프로그래밍의 특징이 아닌 것은?',
        options: ['캡슐화', '상속', '다형성', '순차성'],
        correctAnswer: 3,
        hashtags: [subject || '정보처리기사', examSession || '2024년 1회', '객체지향', '프로그래밍'],
        difficulty: 'easy' as const,
        explanation: '순차성은 객체지향 프로그래밍의 특징이 아닙니다.'
      }
    ];

    addQuestions(sampleQuestions);
    setUploading(false);
    toast.success(`${sampleQuestions.length}개 문제가 성공적으로 파싱되었습니다!`);
    setFile(null);
    setSubject('');
    setExamSession('');
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">PDF 업로드</h2>
        <p className="text-gray-600">기출문제 PDF 파일을 업로드하여 자동으로 문제를 파싱하고 데이터베이스에 저장합니다.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
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
                />
              </div>
              
              {file && (
                <Button
                  onClick={() => setFile(null)}
                  variant="outline"
                  size="sm"
                  className="w-full"
                >
                  파일 제거
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>문제 정보</CardTitle>
            <CardDescription>파싱할 문제의 메타데이터를 입력하세요.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label htmlFor="subject">과목명</Label>
              <Input
                id="subject"
                placeholder="예: 정보처리기사, 컴활 1급"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="examSession">시험 회차</Label>
              <Input
                id="examSession"
                placeholder="예: 2024년 1회, 2023년 3회"
                value={examSession}
                onChange={(e) => setExamSession(e.target.value)}
              />
            </div>
            
            {uploading && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">파싱 진행률</span>
                  <span className="text-sm text-gray-500">{progress}%</span>
                </div>
                <Progress value={progress} className="w-full" />
              </div>
            )}

            <Button
              onClick={simulateParsing}
              disabled={!file || uploading}
              className="w-full"
            >
              {uploading ? '파싱 중...' : '문제 파싱 시작'}
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <AlertCircle className="w-5 h-5 text-blue-600" />
            <span>파싱 가이드라인</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div>
              <h4 className="font-medium text-gray-900 mb-2">지원되는 형식</h4>
              <ul className="space-y-1 text-gray-600">
                <li>• 4지선다형 객관식 문제</li>
                <li>• 한글/영문 텍스트</li>
                <li>• 이미지 포함 문제</li>
                <li>• 표준 PDF 형식</li>
              </ul>
            </div>
            <div>
              <h4 className="font-medium text-gray-900 mb-2">자동 생성 정보</h4>
              <ul className="space-y-1 text-gray-600">
                <li>• 과목별 해시태그</li>
                <li>• 키워드 해시태그</li>
                <li>• 회차 정보</li>
                <li>• 난이도 분석</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </div>
    </div>
  );
};

export default PDFUploader;
