
import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AlertCircle } from 'lucide-react';

const ParsingInfo: React.FC = () => {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center space-x-2">
          <AlertCircle className="w-5 h-5 text-blue-600" />
          <span>파싱 안내</span>
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
            <h4 className="font-medium text-gray-900 mb-2">파싱 기능</h4>
            <ul className="space-y-1 text-gray-600">
              <li>• 규칙 기반 파서로 빠른 기본 파싱</li>
              <li>• 문제와 선택지 자동 분리</li>
              <li>• 정답 추론</li>
              <li>• 키워드 해시태그 생성</li>
              <li>• 난이도 자동 분석</li>
            </ul>
          </div>
        </div>
        <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-md">
          <p className="text-sm text-green-800">
            <strong>규칙 기반 파서:</strong> 별도의 AI 환경 없이도 기본적인 문제 분류와 정답 매핑이 가능합니다.
            실제 AI 파서가 필요할 때만 스위치를 끄고 로컬 또는 Gemini 연동을 사용하세요.
          </p>
        </div>

        <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded-md">
          <p className="text-sm text-yellow-800">
            <strong>주의:</strong> Gemini API 키는 브라우저에 저장되지 않으며, 파싱 과정에서만 사용됩니다.
            Google AI Studio에서 무료 API 키를 발급받을 수 있습니다.
          </p>
        </div>
        <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-md">
          <p className="text-sm text-blue-800">
            <strong>로컬 AI:</strong> 로컬 환경에서 Ollama를 사용하여 한국어 모델(EEVE-Korean, Llama-3-Korean 등)을 
            실행할 수 있습니다. API 키 없이도 안전하고 빠른 파싱이 가능합니다.
          </p>
        </div>
      </CardContent>
    </Card>
  );
};

export default ParsingInfo;
