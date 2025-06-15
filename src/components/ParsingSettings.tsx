
import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Key, Server } from 'lucide-react';

interface ParsingSettingsProps {
  subject: string;
  setSubject: (subject: string) => void;
  examSession: string;
  setExamSession: (examSession: string) => void;
  geminiApiKey: string;
  setGeminiApiKey: (key: string) => void;
  useLocalModel: boolean;
  setUseLocalModel: (use: boolean) => void;
  mcpEndpoint: string;
  setMcpEndpoint: (endpoint: string) => void;
  onParseClick: () => void;
  file: File | null;
  uploading: boolean;
}

const ParsingSettings: React.FC<ParsingSettingsProps> = ({
  subject,
  setSubject,
  examSession,
  setExamSession,
  geminiApiKey,
  setGeminiApiKey,
  useLocalModel,
  setUseLocalModel,
  mcpEndpoint,
  setMcpEndpoint,
  onParseClick,
  file,
  uploading
}) => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>파싱 설정</CardTitle>
        <CardDescription>문제 파싱에 필요한 정보를 입력하세요.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between p-3 border rounded-lg">
          <div className="flex items-center space-x-2">
            <Server className="w-4 h-4" />
            <Label htmlFor="local-model">로컬 AI 모델 사용</Label>
          </div>
          <Switch
            id="local-model"
            checked={useLocalModel}
            onCheckedChange={setUseLocalModel}
          />
        </div>

        {useLocalModel ? (
          <div>
            <Label htmlFor="mcp-endpoint">MCP 엔드포인트</Label>
            <Input
              id="mcp-endpoint"
              placeholder="http://localhost:11434"
              value={mcpEndpoint}
              onChange={(e) => setMcpEndpoint(e.target.value)}
            />
            <p className="text-xs text-gray-500 mt-1">
              Ollama 서버 주소를 입력하세요. 로컬에서 실행 중인 한국어 모델이 필요합니다.
            </p>
          </div>
        ) : (
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
        )}
        
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

        <Button
          onClick={onParseClick}
          disabled={!file || (!useLocalModel && !geminiApiKey.trim()) || uploading}
          className="w-full"
        >
          {uploading ? '파싱 중...' : 'AI로 PDF 파싱 시작'}
        </Button>
      </CardContent>
    </Card>
  );
};

export default ParsingSettings;
