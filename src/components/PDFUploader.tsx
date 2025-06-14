
import React, { useState, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Upload, FileText, CheckCircle, AlertCircle, Key } from 'lucide-react';
import { useQuestionStore, Question } from '../store/questionStore';
import { toast } from 'sonner';
import { extractTextFromPDF, parseQuestionsWithAI } from '../utils/pdfParser';

const PDFUploader = () => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [subject, setSubject] = useState('');
  const [examSession, setExamSession] = useState('');
  const [geminiApiKey, setGeminiApiKey] = useState('');
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

  const parseRealPDF = async () => {
    if (!file || !geminiApiKey.trim()) {
      toast.error('PDF 파일과 Gemini API 키를 모두 입력해주세요.');
      return;
    }

    setUploading(true);
    setProgress(0);

    try {
      // Step 1: PDF 텍스트 추출
      toast.info('PDF 파일에서 텍스트를 추출하는 중...');
      setProgress(25);
      
      const { text, pages } = await extractTextFromPDF(file);
      
      if (!text.trim()) {
        throw new Error('PDF에서 텍스트를 추출할 수 없습니다. 스캔된 이미지 PDF일 가능성이 있습니다.');
      }

      // Step 2: Gemini AI로 문제 파싱
      toast.info('Gemini AI가 문제를 분석하고 구조화하는 중...');
      setProgress(50);

      const questions = await parseQuestionsWithAI(text, subject, examSession, geminiApiKey);
      
      if (questions.length === 0) {
        throw new Error('PDF에서 유효한 객관식 문제를 찾을 수 없습니다.');
      }

      // Step 3: 데이터베이스에 저장
      toast.info('문제를 데이터베이스에 저장하는 중...');
      setProgress(75);

      addQuestions(questions);
      setProgress(100);

      toast.success(`${questions.length}개의 문제가 성공적으로 파싱되어 저장되었습니다! (총 ${pages}페이지 처리)`);
      
      // 폼 초기화
      setFile(null);
      setSubject('');
      setExamSession('');
      
    } catch (error) {
      console.error('PDF 파싱 오류:', error);
      toast.error(error.message || '파싱 중 오류가 발생했습니다.');
    } finally {
      setUploading(false);
      setProgress(0);
    }
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
            <CardTitle>파싱 설정</CardTitle>
            <CardDescription>문제 파싱에 필요한 정보를 입력하세요.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label htmlFor="apiKey" className="flex items-center space-x-2">
                <Key className="w-4 h-4" />
                <span>Google Gemini API 키</span>
              </Label>
              <Input
                id="apiKey"
                type="password"
                placeholder="AIza..."
                value={geminiApiKey}
                onChange={(e) => setGeminiApiKey(e.target.value)}
                className="font-mono text-sm"
              />
              <p className="text-xs text-gray-500 mt-1">
                한글 문제 파싱을 위해 Google Gemini API가 필요합니다.
              </p>
            </div>
            
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
              onClick={parseRealPDF}
              disabled={!file || !geminiApiKey.trim() || uploading}
              className="w-full"
            >
              {uploading ? '파싱 중...' : 'Gemini로 PDF 파싱 시작'}
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center space-x-2">
            <AlertCircle className="w-5 h-5 text-blue-600" />
            <span>Gemini 파싱 안내</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div>
              <h4 className="font-medium text-gray-900 mb-2">지원되는 형식</h4>
              <ul className="space-y-1 text-gray-600">
                <li>• 텍스트 기반 PDF (스캔 이미지 X)</li>
                <li>• 4지선다형 객관식 문제</li>
                <li>• 한글 기출문제</li>
                <li>• 명확한 문제 구조</li>
              </ul>
            </div>
            <div>
              <h4 className="font-medium text-gray-900 mb-2">Gemini AI 파싱 기능</h4>
              <ul className="space-y-1 text-gray-600">
                <li>• 문제와 선택지 자동 분리</li>
                <li>• 정답 추론</li>
                <li>• 키워드 해시태그 생성</li>
                <li>• 난이도 자동 분석</li>
              </ul>
            </div>
          </div>
          <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-md">
            <p className="text-sm text-yellow-800">
              <strong>주의:</strong> Gemini API 키는 브라우저에 저장되지 않으며, 파싱 과정에서만 사용됩니다.
              Google AI Studio에서 무료 API 키를 발급받을 수 있습니다.
            </p>
          </div>
          <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-md">
            <p className="text-sm text-blue-800">
              <strong>MCP 대안:</strong> API 연결 대신 MCP(Model Context Protocol)를 통한 로컬 모델 연결도 고려해볼 수 있습니다.
              Ollama, LM Studio 등의 오픈소스 도구를 활용하여 로컬에서 모델을 실행할 수 있습니다.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default PDFUploader;
