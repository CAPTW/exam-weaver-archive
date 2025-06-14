
import React, { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Download, Terminal, Server, Database, CheckCircle, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';

const LocalSetup = () => {
  const [mcpEndpoint, setMcpEndpoint] = useState('http://localhost:11434');
  const [useLocalModel, setUseLocalModel] = useState(true);
  const [connectionStatus, setConnectionStatus] = useState<'checking' | 'connected' | 'failed' | 'idle'>('idle');

  const testMCPConnection = async () => {
    setConnectionStatus('checking');
    try {
      const response = await fetch(`${mcpEndpoint}/api/tags`);
      if (response.ok) {
        setConnectionStatus('connected');
        toast.success('로컬 AI 모델 서버에 성공적으로 연결되었습니다!');
      } else {
        throw new Error('연결 실패');
      }
    } catch (error) {
      setConnectionStatus('failed');
      toast.error('로컬 AI 모델 서버에 연결할 수 없습니다.');
    }
  };

  const downloadInstructions = [
    {
      step: 1,
      title: 'GitHub 연동',
      description: 'Lovable에서 GitHub 버튼을 클릭하여 프로젝트를 GitHub에 연동하세요.',
      icon: <Download className="w-5 h-5" />
    },
    {
      step: 2,
      title: '로컬 클론',
      description: 'git clone <repository-url> 명령으로 프로젝트를 로컬에 복제하세요.',
      icon: <Terminal className="w-5 h-5" />
    },
    {
      step: 3,
      title: 'Ollama 설치',
      description: 'https://ollama.ai에서 Ollama를 다운로드하고 설치하세요.',
      icon: <Server className="w-5 h-5" />
    },
    {
      step: 4,
      title: '한국어 모델 다운로드',
      description: 'ollama pull eeve-korean-10.8b 명령으로 한국어 모델을 다운로드하세요.',
      icon: <Database className="w-5 h-5" />
    }
  ];

  const koreanModels = [
    { name: 'eeve-korean-10.8b', size: '6.4GB', description: '한국어 특화 중간 크기 모델' },
    { name: 'llama3-korean', size: '4.7GB', description: 'Llama3 기반 한국어 모델' },
    { name: 'solar-10.7b', size: '6.1GB', description: 'Solar 기반 한국어 모델' },
    { name: 'kullm', size: '7.4GB', description: '고려대학교 한국어 언어모델' }
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">로컬 환경 구축</h2>
        <p className="text-gray-600">PDF 파싱과 AI 분석을 위한 로컬 개발 환경을 설정하세요.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>로컬 다운로드 가이드</CardTitle>
            <CardDescription>전체 프로젝트를 로컬 환경으로 이전하는 방법</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {downloadInstructions.map((instruction) => (
                <div key={instruction.step} className="flex items-start space-x-3 p-3 border rounded-lg">
                  <div className="flex-shrink-0">
                    {instruction.icon}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center space-x-2 mb-1">
                      <Badge variant="outline">{instruction.step}</Badge>
                      <h4 className="font-medium">{instruction.title}</h4>
                    </div>
                    <p className="text-sm text-gray-600">{instruction.description}</p>
                  </div>
                </div>
              ))}
            </div>
            
            <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <h4 className="font-medium text-blue-900 mb-2">추가 설정 (로컬 환경)</h4>
              <div className="text-sm text-blue-800 space-y-1">
                <p>• npm install 또는 yarn install로 의존성 설치</p>
                <p>• npm run dev로 개발 서버 실행</p>
                <p>• public/pdfjs/ 폴더에 PDF.js worker 파일들 복사</p>
                <p>• .env.local 파일에 환경 변수 설정</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>로컬 AI 모델 설정</CardTitle>
            <CardDescription>Ollama 기반 한국어 모델 연동</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="local-model">로컬 모델 사용</Label>
              <Switch
                id="local-model"
                checked={useLocalModel}
                onCheckedChange={setUseLocalModel}
              />
            </div>
            
            <div>
              <Label htmlFor="mcp-endpoint">MCP 엔드포인트</Label>
              <Input
                id="mcp-endpoint"
                value={mcpEndpoint}
                onChange={(e) => setMcpEndpoint(e.target.value)}
                placeholder="http://localhost:11434"
              />
            </div>
            
            <Button
              onClick={testMCPConnection}
              disabled={connectionStatus === 'checking'}
              className="w-full"
              variant={connectionStatus === 'connected' ? 'default' : 'outline'}
            >
              {connectionStatus === 'checking' && '연결 확인 중...'}
              {connectionStatus === 'connected' && (
                <>
                  <CheckCircle className="w-4 h-4 mr-2" />
                  연결됨
                </>
              )}
              {connectionStatus === 'failed' && (
                <>
                  <AlertCircle className="w-4 h-4 mr-2" />
                  연결 실패
                </>
              )}
              {connectionStatus === 'idle' && '연결 테스트'}
            </Button>

            <div className="space-y-3">
              <h4 className="font-medium">추천 한국어 모델</h4>
              {koreanModels.map((model) => (
                <div key={model.name} className="p-3 border rounded-lg">
                  <div className="flex justify-between items-start mb-1">
                    <span className="font-mono text-sm">{model.name}</span>
                    <Badge variant="secondary">{model.size}</Badge>
                  </div>
                  <p className="text-xs text-gray-600">{model.description}</p>
                  <code className="text-xs bg-gray-100 px-2 py-1 rounded mt-1 block">
                    ollama pull {model.name}
                  </code>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>로컬 환경의 장점</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
            <div>
              <h4 className="font-medium text-gray-900 mb-2">성능 최적화</h4>
              <ul className="space-y-1 text-gray-600">
                <li>• PDF.js worker 로컬 파일 사용</li>
                <li>• 네트워크 의존성 제거</li>
                <li>• 빠른 파싱 속도</li>
                <li>• 안정적인 메모리 관리</li>
              </ul>
            </div>
            <div>
              <h4 className="font-medium text-gray-900 mb-2">프라이버시 보호</h4>
              <ul className="space-y-1 text-gray-600">
                <li>• 문서가 외부로 전송되지 않음</li>
                <li>• API 키 불필요</li>
                <li>• 완전한 오프라인 작업</li>
                <li>• 데이터 보안 강화</li>
              </ul>
            </div>
            <div>
              <h4 className="font-medium text-gray-900 mb-2">개발 자유도</h4>
              <ul className="space-y-1 text-gray-600">
                <li>• 코드 수정 및 커스터마이징</li>
                <li>• 다양한 한국어 모델 실험</li>
                <li>• 빌드 및 배포 자유</li>
                <li>• 확장 기능 개발</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default LocalSetup;
