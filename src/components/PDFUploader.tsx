
import React, { useState } from 'react';
import { useQuestionStore } from '../store/questionStore';
import { toast } from 'sonner';
import { extractTextFromPDF, parseQuestionsWithAI, parseQuestionsWithHeuristics } from '../utils/pdfParser';
import FileUploadZone from './FileUploadZone';
import ParsingSettings from './ParsingSettings';
import ParsingProgress from './ParsingProgress';
import ParsingInfo from './ParsingInfo';

const PDFUploader = () => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [subject, setSubject] = useState('');
  const [examSession, setExamSession] = useState('');
  const [geminiApiKey, setGeminiApiKey] = useState('');
  const [useLocalModel, setUseLocalModel] = useState(true);
  const [useHeuristicParser, setUseHeuristicParser] = useState(true);
  const [mcpEndpoint, setMcpEndpoint] = useState('http://localhost:11434');
  const { addQuestions } = useQuestionStore();

  const parseRealPDF = async () => {
    if (!file) {
      toast.error('PDF 파일을 선택해주세요.');
      return;
    }

    if (!useHeuristicParser && !useLocalModel && !geminiApiKey.trim()) {
      toast.error('로컬 모델을 사용하지 않는 경우 Gemini API 키가 필요합니다.');
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

      // Step 2: AI로 문제 파싱
      const parserType = useHeuristicParser
        ? '규칙 기반 파서'
        : useLocalModel
          ? '로컬 AI 모델'
          : 'Gemini AI';
      toast.info(`${parserType}이 문제를 분석하고 구조화하는 중...`);
      setProgress(50);

      const questions = useHeuristicParser
        ? parseQuestionsWithHeuristics(text, subject, examSession)
        : await parseQuestionsWithAI(
            text,
            subject,
            examSession,
            geminiApiKey,
            useLocalModel,
            mcpEndpoint
          );

      if (questions.length === 0) {
        throw new Error(
          useHeuristicParser
            ? '규칙 기반 파서가 문제를 찾지 못했습니다. AI 파서를 사용하거나 PDF가 텍스트 기반인지 확인해주세요.'
            : 'PDF에서 유효한 객관식 문제를 찾을 수 없습니다.'
        );
      }

      if (useHeuristicParser) {
        const fallbackAnswers = questions.filter(question => question.explanation?.includes('임시 정답')).length;
        if (fallbackAnswers > 0) {
          toast.warning(`${fallbackAnswers}개의 문제는 정답 표기가 없어 1번을 임시 정답으로 설정했습니다.`);
        }
      }

      // Step 3: 데이터베이스에 저장
      toast.info('문제를 데이터베이스에 저장하는 중...');
      setProgress(75);

      addQuestions(questions);
      setProgress(100);

      const successType = useHeuristicParser
        ? '규칙 기반 파서'
        : useLocalModel
          ? '로컬 AI 모델'
          : 'Gemini AI';

      toast.success(`${questions.length}개의 문제가 성공적으로 파싱되어 저장되었습니다! (총 ${pages}페이지 처리, ${successType} 사용)`);
      
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
        <FileUploadZone 
          file={file} 
          setFile={setFile} 
          uploading={uploading}
        />

        <div className="space-y-4">
          <ParsingSettings
            subject={subject}
            setSubject={setSubject}
            examSession={examSession}
            setExamSession={setExamSession}
            geminiApiKey={geminiApiKey}
            setGeminiApiKey={setGeminiApiKey}
            useLocalModel={useLocalModel}
            setUseLocalModel={setUseLocalModel}
            useHeuristicParser={useHeuristicParser}
            setUseHeuristicParser={setUseHeuristicParser}
            mcpEndpoint={mcpEndpoint}
            setMcpEndpoint={setMcpEndpoint}
            onParseClick={parseRealPDF}
            file={file}
            uploading={uploading}
          />
          
          <ParsingProgress progress={progress} uploading={uploading} />
        </div>
      </div>

      <ParsingInfo />
    </div>
  );
};

export default PDFUploader;
