import * as pdfjsLib from 'pdfjs-dist';
import { Question } from '../store/questionStore';

// PDF.js worker 설정 - Vite 환경에 맞게 수정
pdfjsLib.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjsLib.version}/build/pdf.worker.min.js`;

export interface ParsedPDFContent {
  text: string;
  pages: number;
}

export async function extractTextFromPDF(file: File): Promise<ParsedPDFContent> {
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  
  let fullText = '';
  
  for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
    const page = await pdf.getPage(pageNum);
    const textContent = await page.getTextContent();
    const pageText = textContent.items
      .map((item: any) => item.str)
      .join(' ');
    fullText += pageText + '\n';
  }
  
  return {
    text: fullText,
    pages: pdf.numPages
  };
}

export async function parseQuestionsWithGemini(
  pdfText: string, 
  subject: string, 
  examSession: string,
  apiKey: string
): Promise<Question[]> {
  const prompt = `
다음은 한국어 기출문제 PDF에서 추출한 텍스트입니다. 이 텍스트를 분석하여 객관식 문제들을 찾아 JSON 형태로 구조화해주세요.

과목: ${subject}
회차: ${examSession}

추출할 정보:
1. 문제 번호와 문제 내용
2. 4개의 선택지 (①, ②, ③, ④ 또는 1, 2, 3, 4)
3. 정답 (0-3 인덱스)
4. 관련 키워드 해시태그
5. 난이도 추정 (easy, medium, hard)

응답 형식 (JSON 배열):
[
  {
    "question": "문제 내용",
    "options": ["선택지1", "선택지2", "선택지3", "선택지4"],
    "correctAnswer": 정답인덱스(0-3),
    "hashtags": ["${subject}", "${examSession}", "키워드1", "키워드2"],
    "difficulty": "easy|medium|hard",
    "explanation": "해설 (있는 경우)"
  }
]

PDF 텍스트:
${pdfText.substring(0, 8000)} // 너무 긴 텍스트는 잘라서 전송

다음 조건을 만족하는 완전한 객관식 문제만 추출해주세요:
- 문제 내용이 명확히 구분되는 것
- 4개의 선택지가 모두 있는 것
- 한국어로 작성된 것
- 의미있는 문제인 것

JSON 배열만 응답해주세요.`;

  try {
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        contents: [
          {
            parts: [
              {
                text: prompt
              }
            ]
          }
        ],
        generationConfig: {
          temperature: 0.1,
          topK: 40,
          topP: 0.95,
          maxOutputTokens: 4096,
        },
        safetySettings: [
          {
            category: "HARM_CATEGORY_HARASSMENT",
            threshold: "BLOCK_MEDIUM_AND_ABOVE"
          },
          {
            category: "HARM_CATEGORY_HATE_SPEECH",
            threshold: "BLOCK_MEDIUM_AND_ABOVE"
          },
          {
            category: "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold: "BLOCK_MEDIUM_AND_ABOVE"
          },
          {
            category: "HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold: "BLOCK_MEDIUM_AND_ABOVE"
          }
        ]
      }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(`Gemini API 오류: ${response.status} - ${errorData.error?.message || response.statusText}`);
    }

    const data = await response.json();
    
    if (!data.candidates || data.candidates.length === 0) {
      throw new Error('Gemini API에서 응답을 받지 못했습니다.');
    }

    const content = data.candidates[0].content.parts[0].text;
    
    // JSON 부분만 추출
    const jsonMatch = content.match(/\[[\s\S]*\]/);
    if (!jsonMatch) {
      throw new Error('AI 응답에서 JSON을 찾을 수 없습니다.');
    }

    const parsedQuestions = JSON.parse(jsonMatch[0]);
    
    // Question 타입에 맞게 변환하고 ID 추가
    return parsedQuestions.map((q: any) => ({
      id: Math.random().toString(36).substr(2, 9),
      question: q.question,
      options: q.options,
      correctAnswer: q.correctAnswer,
      hashtags: q.hashtags,
      difficulty: q.difficulty,
      explanation: q.explanation
    }));

  } catch (error) {
    console.error('Gemini 파싱 오류:', error);
    throw new Error(`문제 파싱 중 오류가 발생했습니다: ${error.message}`);
  }
}

// OpenAI 호환성을 위해 기존 함수명 유지하되 내부에서 Gemini 사용
export async function parseQuestionsWithAI(
  pdfText: string, 
  subject: string, 
  examSession: string,
  apiKey: string
): Promise<Question[]> {
  return parseQuestionsWithGemini(pdfText, subject, examSession, apiKey);
}
